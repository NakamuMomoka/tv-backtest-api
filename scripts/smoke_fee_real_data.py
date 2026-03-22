#!/usr/bin/env python3
"""実データ（組み込み BTCUSDT 1h CSV）で fee_rate=0 と 0.0006 のスモーク比較。

    cd /path/to/tv-backtest-api && . .venv/bin/activate && python scripts/smoke_fee_real_data.py
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.dataset_cache import get_dataset_bars

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


def _fmt(v: Any) -> str:
    if v is None:
        return "None"
    if isinstance(v, float):
        return f"{v:.6g}"
    return str(v)


def main() -> int:
    csv_path = ROOT / "datasets" / "builtins" / "1_BITGET_BTCUSDT.P_60.csv"
    if not csv_path.is_file():
        print(f"ERROR: dataset not found: {csv_path}", file=sys.stderr)
        return 1

    bars = get_dataset_bars(csv_path)
    print(f"Dataset: {csv_path.name} rows={len(bars)}")
    print()

    strategies: list[tuple[str, Path, str, dict[str, Any]]] = [
        (
            "assistpass",
            ROOT / "strategies" / "builtins" / "assistpass.py",
            "run_backtest",
            {},
        ),
        (
            "rjv",
            ROOT / "strategies" / "builtins" / "rjv.py",
            "backtest",
            {},
        ),
        (
            "motu_chaos_mod_bf_bitget",
            ROOT / "strategies" / "builtins" / "motu_chaos_mod_bf_bitget.py",
            "run_backtest",
            # 実データ期間が manifest の testPeriod 外だと約定ゼロになるため無効化
            {"use_test_period": False},
        ),
        (
            "sample_strategy_ma_cross",
            ROOT / "examples" / "sample_strategy_ma_cross.py",
            "backtest",
            {},
        ),
    ]

    base_settings: dict[str, Any] = {
        "initial_capital": 100_000.0,
        "optimization_mode": False,
        "collect_trades_for_validation": False,
    }

    for name, path, fn_name, param_extra in strategies:
        mod = _load_module(path, f"mod_{name}")
        params = {**dict(mod.DEFAULT_PARAMS), **param_extra}
        fn = getattr(mod, fn_name)

        print("=" * 72)
        print(f"Strategy: {name}")
        print("-" * 72)

        row0: dict[str, Any] = {}
        row1: dict[str, Any] = {}

        for fee_label, fee in (("fee_rate=0", 0.0), ("fee_rate=0.0006", 0.0006)):
            settings = {**base_settings, "fee_rate": fee}
            out = fn(bars, params, settings)
            m = (out.get("metrics") or {})
            row = {k: m.get(k) for k in METRIC_KEYS}
            if fee == 0.0:
                row0 = row
            else:
                row1 = row

            print(f"  [{fee_label}]")
            for k in METRIC_KEYS:
                print(f"    {k:16s} {_fmt(row.get(k))}")

        # 妥当性チェック（目視用の短文）
        tt0, tt1 = row0.get("total_trades"), row1.get("total_trades")
        if tt0 != tt1:
            print(f"  NOTE: total_trades differs ({tt0} vs {tt1}) — unexpected for fee-only change.")
        else:
            print("  OK: total_trades unchanged (fee does not affect signal count).")

        np0, np1 = float(row0.get("net_profit") or 0), float(row1.get("net_profit") or 0)
        if int(tt0 or 0) > 0:
            if np1 > np0:
                print(f"  NOTE: net_profit higher with fees ({np1} > {np0}) — unusual, review.")
            else:
                print(f"  OK: net_profit with fee <= without fee (delta ≈ {np1 - np0:.6g}).")
        else:
            print("  (skip net_profit fee comparison: zero trades)")
        print()

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
