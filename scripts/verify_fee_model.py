#!/usr/bin/env python3
"""手数料モデルの検証（CLI）。

- fee_rate=0: 同一条件で再実行した指標が一致すること（手数料が恒等であることの実証）
- fee_rate=0: optimization_mode 有無で metrics が一致すること
- fee_rate=0.0006: 同上

使い方（リポジトリルートで）::

    python scripts/verify_fee_model.py
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

METRIC_KEYS = [
    "total_trades",
    "net_profit",
    "gross_profit",
    "gross_loss",
    "profit_factor",
    "final_equity",
]


def _load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _synthetic_ohlcv(n: int = 2500) -> pd.DataFrame:
    """全組込み戦略がウォームアップ可能な長さの OHLCV（決定的）。"""
    rng = np.random.default_rng(42)
    t0 = pd.Timestamp("2023-01-01", tz="UTC")
    ts = pd.date_range(t0, periods=n, freq="1h", tz="UTC")
    close = 20000.0 + np.cumsum(rng.normal(0, 50.0, n))
    open_ = np.empty(n, dtype=float)
    open_[0] = float(close[0])
    open_[1:] = close[:-1]
    noise = rng.uniform(0.0005, 0.0015, n)
    high = np.maximum(open_, close) * (1.0 + noise)
    low = np.minimum(open_, close) * (1.0 - noise)
    vol = rng.integers(1000, 10000, n).astype(float)
    return pd.DataFrame(
        {
            "timestamp": ts,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": vol,
        },
    )


def _pick_metrics(raw: dict[str, Any]) -> dict[str, Any]:
    m = raw.get("metrics") or {}
    return {k: m.get(k) for k in METRIC_KEYS}


def _close_enough(a: Any, b: Any, tol: float = 1e-9) -> bool:
    if a is None and b is None:
        return True
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if np.isnan(float(a)) and np.isnan(float(b)):
            return True
        return abs(float(a) - float(b)) <= tol
    return a == b


def _compare_metrics(
    label: str,
    m1: dict[str, Any],
    m2: dict[str, Any],
    *,
    tol: float = 1e-9,
) -> list[str]:
    bad: list[str] = []
    for k in METRIC_KEYS:
        if not _close_enough(m1.get(k), m2.get(k), tol=tol):
            bad.append(f"{label} {k}: {m1.get(k)!r} vs {m2.get(k)!r}")
    return bad


def _run_pair(
    name: str,
    fn: Callable[..., dict[str, Any]],
    bars: pd.DataFrame,
    params: dict[str, Any],
    fee_rate: float,
) -> tuple[list[str], list[str]]:
    """Returns (issues_fee0_repeat, issues_opt_vs_normal)."""
    base_settings: dict[str, Any] = {
        "initial_capital": 100_000.0,
        "fee_rate": fee_rate,
        "optimization_mode": False,
        "collect_trades_for_validation": True,
    }
    opt_settings = {
        **base_settings,
        "optimization_mode": True,
        "collect_trades_for_validation": True,
    }

    r1 = fn(bars, params, base_settings)
    r2 = fn(bars, params, base_settings)
    ro = fn(bars, params, opt_settings)

    m1 = _pick_metrics(r1)
    m2 = _pick_metrics(r2)
    mo = _pick_metrics(ro)

    repeat = _compare_metrics(f"{name} fee_rate={fee_rate} repeat", m1, m2)
    opt_cmp = _compare_metrics(f"{name} fee_rate={fee_rate} opt", m1, mo)
    return repeat, opt_cmp


def main() -> int:
    bars = _synthetic_ohlcv()
    strategies: list[tuple[str, Path, str]] = [
        ("assistpass", ROOT / "strategies" / "builtins" / "assistpass.py", "run_backtest"),
        ("rjv", ROOT / "strategies" / "builtins" / "rjv.py", "backtest"),
        ("motu_chaos_mod_bf_bitget", ROOT / "strategies" / "builtins" / "motu_chaos_mod_bf_bitget.py", "run_backtest"),
        ("sample_strategy_ma_cross", ROOT / "examples" / "sample_strategy_ma_cross.py", "backtest"),
    ]

    all_repeat_issues: list[str] = []
    all_opt_issues: list[str] = []

    report: dict[str, Any] = {"strategies": {}}

    for key, path, fn_name in strategies:
        mod = _load_module(path, f"mod_{key}")
        params = dict(mod.DEFAULT_PARAMS)
        if key == "motu_chaos_mod_bf_bitget":
            params["use_test_period"] = False
        fn = getattr(mod, fn_name)
        entry: dict[str, Any] = {}
        for fee in (0.0, 0.0006):
            rep, opt = _run_pair(key, fn, bars, params, fee_rate=fee)
            all_repeat_issues.extend(rep)
            all_opt_issues.extend(opt)
            entry[f"fee_rate_{fee}"] = {
                "repeat_identical": len(rep) == 0,
                "optimization_matches_normal": len(opt) == 0,
            }
        report["strategies"][key] = entry

    report["repeat_issues"] = all_repeat_issues
    report["optimization_mode_issues"] = all_opt_issues
    report["ok"] = len(all_repeat_issues) == 0 and len(all_opt_issues) == 0

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
