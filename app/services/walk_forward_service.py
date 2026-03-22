from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import DEFAULT_FEE_RATE, WALK_FORWARD_RESULTS_DIR
from app.models.dataset import Dataset
from app.models.strategy import Strategy
from app.models.walk_forward_run import WalkForwardRun
from app.services.serialization import to_jsonable
from app.services.dataset_cache import get_dataset_bars
from app.services.strategy_runner import StrategyExecutionError, run_strategy_backtest_on_bars


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


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


def _iter_param_combinations(search_space: dict[str, list[Any]]):
    if not search_space:
        yield {}
        return

    from itertools import product

    keys = list(search_space.keys())
    value_lists = [search_space[k] for k in keys]
    for values in product(*value_lists):
        yield {k: v for k, v in zip(keys, values, strict=True)}


def _score_from_metrics(
    metrics: dict[str, Any],
    objective_metric: str | None,
) -> float:
    if objective_metric and objective_metric in metrics:
        value = metrics.get(objective_metric)
        return float(value) if isinstance(value, (int, float)) else 0.0

    for key in ("net_profit", "profit_factor"):
        if key in metrics and isinstance(metrics[key], (int, float)):
            return float(metrics[key])

    return 0.0


def _compute_oos_score(
    metrics: dict[str, Any],
    objective_metric: str | None,
) -> float:
    return _score_from_metrics(metrics, objective_metric)


def create_walk_forward_run(
    db: Session,
    *,
    dataset_id: int,
    strategy_id: int,
    search_space: dict[str, list[Any]],
    settings: dict[str, Any] | None,
    objective_metric: str | None,
    train_bars: int,
    test_bars: int,
    step_bars: int,
    min_trades: int | None,
    start_date: str | None,
    end_date: str | None,
) -> WalkForwardRun:
    if train_bars <= 0 or test_bars <= 0 or step_bars <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="train_bars, test_bars, and step_bars must be > 0.",
        )

    dataset = _get_dataset_or_404(db, dataset_id)
    strategy = _get_strategy_or_404(db, strategy_id)

    csv_path = Path(dataset.file_path)
    try:
        df = get_dataset_bars(csv_path)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load dataset CSV: {exc}",
        ) from exc

    df = _filter_bars_by_date(df, start_date, end_date)

    total_bars = len(df)
    if total_bars < train_bars + test_bars:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Dataset has fewer bars than train_bars + test_bars.",
        )

    settings_used = dict(settings or {})
    settings_used["fee_rate"] = float(settings_used.get("fee_rate", DEFAULT_FEE_RATE))

    search_space_json = json.dumps(to_jsonable(search_space or {}))
    settings_json = json.dumps(to_jsonable(settings_used))

    run = WalkForwardRun(
        dataset_id=dataset.id,
        strategy_id=strategy.id,
        search_space_json=search_space_json,
        settings_json=settings_json,
        start_date=start_date,
        end_date=end_date,
        objective_metric=objective_metric,
        train_bars=train_bars,
        test_bars=test_bars,
        step_bars=step_bars,
        status="running",
        created_at=_utcnow(),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    windows: list[dict[str, Any]] = []
    any_success = False
    oos_scores: list[float] = []

    window_no = 1
    start = 0
    while True:
        train_start = start
        train_end = train_start + train_bars
        test_start = train_end
        test_end = test_start + test_bars

        if test_end > total_bars:
            break

        window_info: dict[str, Any] = {
            "window_no": window_no,
            "train_range": [int(train_start), int(train_end)],
            "test_range": [int(test_start), int(test_end)],
            "status": "pending",
            "error_message": None,
        }

        train_df = df.iloc[train_start:train_end].copy()
        test_df = df.iloc[test_start:test_end].copy()

        best_params: dict[str, Any] | None = None
        best_score: float | None = None
        window_error: str | None = None

        for params in _iter_param_combinations(search_space):
            try:
                result = run_strategy_backtest_on_bars(
                    bars=train_df,
                    strategy=strategy,
                    params=params,
                    settings=settings_used,
                )
                metrics = result.get("metrics") or {}
                score = _score_from_metrics(metrics, objective_metric)
                if min_trades is not None:
                    trades_count = metrics.get("total_trades") or metrics.get("trades")
                    if isinstance(trades_count, int) and trades_count < min_trades:
                        continue
                if best_score is None or score > best_score:
                    best_score = score
                    best_params = params
            except StrategyExecutionError as exc:
                window_error = str(exc)
            except Exception as exc:  # noqa: BLE001
                window_error = f"Unexpected error during optimization: {exc}"

        if best_params is None:
            window_info["status"] = "failed"
            window_info["error_message"] = window_error or "All trials failed in window."
            windows.append(window_info)
            start += step_bars
            window_no += 1
            continue

        window_info["best_params"] = to_jsonable(best_params)
        window_info["train_best_score"] = best_score

        try:
            test_result = run_strategy_backtest_on_bars(
                bars=test_df,
                strategy=strategy,
                params=best_params,
                settings=settings_used,
            )
            test_metrics = test_result.get("metrics") or {}
            oos_score = _compute_oos_score(test_metrics, objective_metric)
            window_info["test_metrics"] = to_jsonable(test_metrics)
            window_info["oos_score"] = oos_score
            window_info["status"] = "success"
            any_success = True
            oos_scores.append(oos_score)
        except StrategyExecutionError as exc:
            window_info["status"] = "failed"
            window_info["error_message"] = str(exc)
        except Exception as exc:  # noqa: BLE001
            window_info["status"] = "failed"
            window_info["error_message"] = f"Unexpected error during test: {exc}"

        windows.append(window_info)
        start += step_bars
        window_no += 1

    summary: dict[str, Any] = {
        "total_windows": len(windows),
        "success_windows": int(sum(1 for w in windows if w.get("status") == "success")),
        "failed_windows": int(sum(1 for w in windows if w.get("status") == "failed")),
        "avg_oos_score": None,
        "median_oos_score": None,
        "best_oos_score": None,
        "worst_oos_score": None,
        "objective_metric": objective_metric,
    }

    if oos_scores:
        import statistics

        summary["avg_oos_score"] = float(sum(oos_scores) / len(oos_scores))
        try:
            summary["median_oos_score"] = float(statistics.median(oos_scores))
        except statistics.StatisticsError:
            summary["median_oos_score"] = None
        summary["best_oos_score"] = float(max(oos_scores))
        summary["worst_oos_score"] = float(min(oos_scores))

    result_payload = to_jsonable(
        {
            "windows": windows,
            "summary": summary,
            "start_date": start_date,
            "end_date": end_date,
        },
    )

    result_path = WALK_FORWARD_RESULTS_DIR / f"{run.id}.json"
    with result_path.open("w", encoding="utf-8") as f:
        json.dump(result_payload, f, ensure_ascii=False, indent=2)

    run.result_path = str(result_path)
    run.summary_json = json.dumps(to_jsonable(summary))
    run.status = "success" if any_success else "failed"
    if not any_success:
        run.error_message = "All walk-forward windows failed."

    run.finished_at = _utcnow()

    db.add(run)
    db.commit()
    db.refresh(run)

    if not any_success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=run.error_message or "Walk-forward run failed.",
        )

    return run


def list_walk_forward_runs(db: Session) -> list[WalkForwardRun]:
    return db.query(WalkForwardRun).order_by(WalkForwardRun.id.desc()).all()


def get_walk_forward_run(db: Session, run_id: int) -> WalkForwardRun:
    run = db.query(WalkForwardRun).filter(WalkForwardRun.id == run_id).first()
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WalkForwardRun not found.",
        )
    return run


def get_walk_forward_result(run: WalkForwardRun) -> dict[str, Any]:
    if not run.result_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Walk-forward result not found.",
        )

    path = Path(run.result_path)
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Walk-forward result file not found.",
        )

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    windows = data.get("windows") or []
    summary = data.get("summary") or {}

    if not isinstance(windows, list):
        windows = []
    if not isinstance(summary, dict):
        summary = {}

    return {
        "windows": windows,
        "summary": summary,
    }

