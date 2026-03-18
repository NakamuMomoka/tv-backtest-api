from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any, Tuple

import pandas as pd

from app.models.strategy import Strategy
from app.services.dataset_cache import get_dataset_bars


class StrategyExecutionError(Exception):
    """Strategy execution failed."""


# key: Path, value: (st_mtime_ns, module)
_STRATEGY_MODULE_CACHE: dict[Path, Tuple[int, ModuleType]] = {}


def clear_strategy_module_cache() -> None:
    """
    Clear cached strategy modules.

    検証用途で戦略ファイルを頻繁に書き換える場合などに、
    モジュールキャッシュを明示的にクリアするために使用します。
    """
    _STRATEGY_MODULE_CACHE.clear()


def _load_module_from_path(path: Path) -> ModuleType:
    if not path.exists():
        raise StrategyExecutionError(f"Strategy file not found: {path}")

    current_mtime = path.stat().st_mtime_ns

    cached = _STRATEGY_MODULE_CACHE.get(path)
    if cached is not None:
        cached_mtime, cached_module = cached
        if cached_mtime == current_mtime:
            return cached_module

    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise StrategyExecutionError("Failed to create module spec for strategy.")

    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)  # type: ignore[union-attr]
    except Exception as exc:  # noqa: BLE001
        raise StrategyExecutionError(f"Error while importing strategy: {exc}") from exc

    _STRATEGY_MODULE_CACHE[path] = (current_mtime, module)
    return module


def run_strategy_backtest(
    *,
    dataset: Dataset,
    strategy: Strategy,
    params: dict[str, Any] | None,
    settings: dict[str, Any] | None,
) -> dict[str, Any]:
    csv_path = Path(dataset.file_path)
    if not csv_path.exists():
        raise StrategyExecutionError(f"Dataset file not found: {csv_path}")

    try:
        bars = get_dataset_bars(csv_path)
    except Exception as exc:  # noqa: BLE001
        raise StrategyExecutionError(f"Failed to load dataset CSV: {exc}") from exc

    return run_strategy_backtest_on_bars(
        bars=bars,
        strategy=strategy,
        params=params,
        settings=settings,
    )


def run_strategy_backtest_on_bars(
    *,
    bars: pd.DataFrame,
    strategy: Strategy,
    params: dict[str, Any] | None,
    settings: dict[str, Any] | None,
) -> dict[str, Any]:
    strategy_path = Path(strategy.file_path)
    module = _load_module_from_path(strategy_path)

    backtest_func = getattr(module, "backtest", None)
    if backtest_func is None or not callable(backtest_func):
        raise StrategyExecutionError("Strategy does not define callable 'backtest'.")

    params = params or {}
    settings = settings or {}

    try:
        result = backtest_func(bars, params, settings)
    except Exception as exc:  # noqa: BLE001
        raise StrategyExecutionError(f"Error while executing backtest: {exc}") from exc

    if not isinstance(result, dict):
        raise StrategyExecutionError("Backtest result must be a dict.")

    metrics = result.get("metrics") or {}
    trades = result.get("trades") or []
    equity_series = result.get("equity_series") or []

    if not isinstance(metrics, dict) or not isinstance(trades, list) or not isinstance(
        equity_series, list
    ):
        raise StrategyExecutionError(
            "Backtest result must contain 'metrics' (dict), 'trades' (list), and 'equity_series' (list).",
        )

    return {
        "metrics": metrics,
        "trades": trades,
        "equity_series": equity_series,
    }

