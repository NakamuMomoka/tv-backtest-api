from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.dataset import Dataset
from app.models.strategy import Strategy
from app.services.dataset_cache import get_dataset_bars
from app.services.strategy_runner import run_strategy_backtest_on_bars

METRIC_KEYS_FOR_EQUIVALENCE = [
    "total_trades",
    "win_rate",
    "gross_profit",
    "gross_loss",
    "profit_factor",
    "net_profit",
]

TRADE_KEYS_FOR_EQUIVALENCE = [
    "side",
    "entry_timestamp",
    "exit_timestamp",
    "entry_price",
    "exit_price",
    "pnl",
]


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
        mask &= ts >= pd.to_datetime(start_date, utc=True)
    if end_date:
        mask &= ts <= pd.to_datetime(end_date, utc=True)
    return bars.loc[mask].copy()


def compare_metrics(
    normal_metrics: dict[str, Any],
    optimized_metrics: dict[str, Any],
    *,
    metric_keys: list[str] | None = None,
    float_tol: float = 1e-12,
) -> dict[str, Any]:
    keys = metric_keys or METRIC_KEYS_FOR_EQUIVALENCE
    mismatches: list[dict[str, Any]] = []

    for key in keys:
        n_val = normal_metrics.get(key)
        o_val = optimized_metrics.get(key)

        if isinstance(n_val, (int, float)) and isinstance(o_val, (int, float)):
            diff = abs(float(n_val) - float(o_val))
            if diff > float_tol:
                mismatches.append(
                    {
                        "key": key,
                        "normal": n_val,
                        "optimized": o_val,
                        "diff": diff,
                    },
                )
        else:
            if n_val != o_val:
                mismatches.append(
                    {
                        "key": key,
                        "normal": n_val,
                        "optimized": o_val,
                    },
                )

    return {
        "match": len(mismatches) == 0,
        "checked_keys": keys,
        "mismatches": mismatches,
    }


def compare_trades(
    normal_trades: list[dict[str, Any]],
    optimized_trades: list[dict[str, Any]],
    *,
    trade_keys: list[str] | None = None,
    float_tol: float = 1e-12,
) -> dict[str, Any]:
    keys = trade_keys or TRADE_KEYS_FOR_EQUIVALENCE
    mismatches: list[dict[str, Any]] = []

    if len(normal_trades) != len(optimized_trades):
        return {
            "match": False,
            "checked_keys": keys,
            "count_mismatch": {
                "normal_count": len(normal_trades),
                "optimized_count": len(optimized_trades),
            },
            "mismatches": [],
        }

    for idx, (n_trade, o_trade) in enumerate(zip(normal_trades, optimized_trades, strict=True)):
        for key in keys:
            n_val = n_trade.get(key)
            o_val = o_trade.get(key)
            if isinstance(n_val, (int, float)) and isinstance(o_val, (int, float)):
                diff = abs(float(n_val) - float(o_val))
                if diff > float_tol:
                    mismatches.append(
                        {
                            "index": idx,
                            "key": key,
                            "normal": n_val,
                            "optimized": o_val,
                            "diff": diff,
                        },
                    )
            else:
                if n_val != o_val:
                    mismatches.append(
                        {
                            "index": idx,
                            "key": key,
                            "normal": n_val,
                            "optimized": o_val,
                        },
                    )

    return {
        "match": len(mismatches) == 0,
        "checked_keys": keys,
        "count_mismatch": None,
        "mismatches": mismatches,
    }


def compare_backtest_results_normal_vs_optimized(
    db: Session,
    *,
    dataset_id: int,
    strategy_id: int,
    params: dict[str, Any] | None,
    settings: dict[str, Any] | None,
    start_date: str | None,
    end_date: str | None,
    compare_trade_list: bool = True,
) -> dict[str, Any]:
    dataset = _get_dataset_or_404(db, dataset_id)
    strategy = _get_strategy_or_404(db, strategy_id)

    bars = get_dataset_bars(Path(dataset.file_path))
    bars = _filter_bars_by_date(bars, start_date, end_date)

    normal_settings = dict(settings or {})
    normal_settings["optimization_mode"] = False
    normal = run_strategy_backtest_on_bars(
        bars=bars,
        strategy=strategy,
        params=params or {},
        settings=normal_settings,
    )

    optimized_settings = dict(settings or {})
    optimized_settings["optimization_mode"] = True
    optimized_settings["collect_trades_for_validation"] = bool(compare_trade_list)
    optimized = run_strategy_backtest_on_bars(
        bars=bars,
        strategy=strategy,
        params=params or {},
        settings=optimized_settings,
    )

    metrics_cmp = compare_metrics(
        normal.get("metrics") or {},
        optimized.get("metrics") or {},
    )

    if compare_trade_list:
        trades_cmp = compare_trades(
            normal.get("trades") or [],
            optimized.get("trades") or [],
        )
    else:
        trades_cmp = {
            "match": None,
            "checked_keys": TRADE_KEYS_FOR_EQUIVALENCE,
            "count_mismatch": None,
            "mismatches": [],
        }

    return {
        "strategy_id": strategy_id,
        "strategy_name": strategy.name,
        "dataset_id": dataset_id,
        "start_date": start_date,
        "end_date": end_date,
        "metrics_comparison": metrics_cmp,
        "trades_comparison": trades_cmp,
        "normal_summary": {
            "metrics": normal.get("metrics") or {},
            "trades_count": len(normal.get("trades") or []),
        },
        "optimized_summary": {
            "metrics": optimized.get("metrics") or {},
            "trades_count": len(optimized.get("trades") or []),
        },
    }
