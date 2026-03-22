from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import BACKTEST_RESULTS_DIR, DEFAULT_FEE_RATE
from app.models.backtest_run import BacktestRun
from app.models.dataset import Dataset
from app.models.strategy import Strategy
from app.services.dataset_cache import get_dataset_bars
from app.services.serialization import to_jsonable
from app.services.strategy_runner import StrategyExecutionError, run_strategy_backtest_on_bars


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

def _compute_max_drawdown_from_equity_series(equity_series: Any) -> float:
    """equity_series から金額ベース最大ドローダウンを算出する。

    - equity_series が空/不正なら 0.0
    - 要素は {"equity": ...} の dict / 数値 のどちらでも許容
    """
    if not isinstance(equity_series, list) or not equity_series:
        return 0.0

    equities: list[float] = []
    for pt in equity_series:
        v: Any = None
        if isinstance(pt, dict):
            v = pt.get("equity")
        else:
            v = pt
        try:
            fv = float(v)
        except Exception:
            continue
        if pd.isna(fv):
            continue
        equities.append(float(fv))

    if not equities:
        return 0.0

    peak = equities[0]
    max_dd = 0.0
    for eq in equities:
        if eq > peak:
            peak = eq
        dd = peak - eq
        if dd > max_dd:
            max_dd = dd
    return float(max_dd)


def _get_dataset_or_404(db: Session, dataset_id: int) -> Dataset:
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found.",
        )
    return dataset


def _get_strategy_or_404(db: Session, strategy_id: int) -> Strategy:
    strategy = db.query(Strategy).filter(Strategy.id == strategy_id).first()
    if strategy is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Strategy not found.",
        )
    return strategy


def _filter_bars_by_date(
    bars: pd.DataFrame,
    start_date: str | None,
    end_date: str | None,
) -> pd.DataFrame:
    if not start_date and not end_date:
        return bars

    if "timestamp" in bars.columns:
        ts = pd.to_datetime(bars["timestamp"], errors="coerce", utc=True)
    elif "time" in bars.columns:
        ts = pd.to_datetime(bars["time"], errors="coerce", utc=True, unit="s")
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Dataset must contain 'timestamp' or 'time' column when using start_date/end_date.",
        )
    mask = ~ts.isna()

    if start_date:
        start = pd.to_datetime(start_date, utc=True)
        mask &= ts >= start
    if end_date:
        end = pd.to_datetime(end_date, utc=True)
        mask &= ts <= end

    return bars.loc[mask].copy()


def create_backtest_run(
    db: Session,
    *,
    dataset_id: int,
    strategy_id: int,
    params: dict[str, Any] | None,
    settings: dict[str, Any] | None,
    start_date: str | None,
    end_date: str | None,
) -> BacktestRun:
    dataset = _get_dataset_or_404(db, dataset_id)
    strategy = _get_strategy_or_404(db, strategy_id)

    # ログに使用ストラテジーを出力（検証用）
    try:
        print(
            f"[backtest] strategy_id={strategy.id} "
            f"name={strategy.name!r} file_path={strategy.file_path!r}",
        )
    except Exception:
        # ログ出力失敗は無視
        pass

    settings_used = dict(settings or {})
    settings_used["fee_rate"] = float(settings_used.get("fee_rate", DEFAULT_FEE_RATE))

    params_json = json.dumps(to_jsonable(params or {}))
    settings_json = json.dumps(to_jsonable(settings_used))

    run = BacktestRun(
        dataset_id=dataset.id,
        strategy_id=strategy.id,
        start_date=start_date,
        end_date=end_date,
        params_json=params_json,
        settings_json=settings_json,
        status="running",
        created_at=_utcnow(),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    error_message: str | None = None
    result_data: dict[str, Any] | None = None

    try:
        csv_path = Path(dataset.file_path)
        try:
            bars = get_dataset_bars(csv_path)
        except Exception as exc:  # noqa: BLE001
            raise StrategyExecutionError(f"Failed to load dataset CSV: {exc}") from exc

        bars = _filter_bars_by_date(bars, start_date, end_date)

        result_data = run_strategy_backtest_on_bars(
            bars=bars,
            strategy=strategy,
            params=params or {},
            settings=settings_used,
        )
        normalized_result = to_jsonable(
            {
                **result_data,
                "start_date": start_date,
                "end_date": end_date,
                "strategy_id": strategy.id,
                "strategy_name": strategy.name,
                "strategy_file_path": strategy.file_path,
            },
        )
        # metrics は戦略実装依存なので、共通メトリクスを注入して一貫性を担保する
        metrics = normalized_result.get("metrics") or {}
        equity_series = normalized_result.get("equity_series") or []
        if not isinstance(metrics, dict):
            metrics = {}

        # max_drawdown は equity_series から必ず算出（欠損/None を防ぐ）
        md = metrics.get("max_drawdown")
        if md is None:
            metrics["max_drawdown"] = _compute_max_drawdown_from_equity_series(equity_series)
        else:
            try:
                metrics["max_drawdown"] = float(md)
            except Exception:
                metrics["max_drawdown"] = _compute_max_drawdown_from_equity_series(equity_series)

        normalized_result["metrics"] = metrics
        normalized_metrics = to_jsonable(metrics)
        run.metrics_json = json.dumps(normalized_metrics)

        # trades を CSV として別途保存（検証用）
        trades = normalized_result.get("trades") or []
        if isinstance(trades, list) and trades:
            try:
                df_trades = pd.DataFrame(trades)
                desired_cols = [
                    "entry_index",
                    "exit_index",
                    "entry_time",
                    "exit_time",
                    "entry_price",
                    "exit_price",
                    "pnl",
                ]
                # 指定列が存在するものだけを順序付きで選択
                existing_cols = [c for c in desired_cols if c in df_trades.columns]
                if existing_cols:
                    df_trades = df_trades[existing_cols]
                trades_path = BACKTEST_RESULTS_DIR / f"{run.id}_trades.csv"
                df_trades.to_csv(trades_path, index=False)
            except Exception:
                # CSV 保存失敗はバックテスト自体の失敗にはしない
                pass

        result_path = BACKTEST_RESULTS_DIR / f"{run.id}.json"
        with result_path.open("w", encoding="utf-8") as f:
            json.dump(normalized_result, f, ensure_ascii=False, indent=2)

        run.result_path = str(result_path)
        run.status = "success"
    except StrategyExecutionError as exc:
        error_message = str(exc)
        run.status = "failed"
    except Exception as exc:  # noqa: BLE001
        error_message = f"Unexpected error: {exc}"
        run.status = "failed"

    run.finished_at = _utcnow()
    if error_message:
        run.error_message = error_message

    db.add(run)
    db.commit()
    db.refresh(run)

    if run.status == "failed":
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=run.error_message or "Backtest failed.",
        )

    return run


def list_backtest_runs(db: Session) -> list[BacktestRun]:
    return db.query(BacktestRun).order_by(BacktestRun.id.desc()).all()


def get_backtest_run(db: Session, run_id: int) -> BacktestRun:
    run = db.query(BacktestRun).filter(BacktestRun.id == run_id).first()
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="BacktestRun not found.",
        )
    return run


def get_backtest_result(run: BacktestRun) -> dict[str, Any]:
    if not run.result_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Backtest result not found.",
        )

    path = Path(run.result_path)
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Backtest result file not found.",
        )

    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load backtest result file: {exc}",
        ) from exc

    metrics = data.get("metrics") or {}
    trades = data.get("trades") or []
    equity_series = data.get("equity_series") or []

    if not isinstance(metrics, dict):
        metrics = {}
    if not isinstance(trades, list):
        trades = []
    if not isinstance(equity_series, list):
        equity_series = []

    return {
        "metrics": metrics,
        "trades": trades,
        "equity_series": equity_series,
    }

