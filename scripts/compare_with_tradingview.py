import argparse
import json
from pathlib import Path
from typing import Any, Dict


METRICS = ["net_profit", "profit_factor", "win_rate", "trades", "max_drawdown"]


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def pct_diff(tv_value: Any, engine_value: Any) -> str:
    try:
        tv = float(tv_value)
        eng = float(engine_value)
    except (TypeError, ValueError):
        return "-"
    if tv == 0:
        return "-"
    diff = (eng - tv) / tv * 100.0
    return f"{diff:+.1f}%"


def compare(tv_json: Dict[str, Any], engine_json: Dict[str, Any]) -> None:
    tv_metrics = (tv_json.get("metrics") or {}) if isinstance(tv_json, dict) else {}
    eng_metrics = (engine_json.get("metrics") or {}) if isinstance(engine_json, dict) else {}

    print("TradingView vs Engine comparison")
    print()
    header = f"{'metric':<15} {'tv':>12} {'engine':>12} {'diff':>10}"
    print(header)
    print("-" * len(header))

    for key in METRICS:
        tv_val = tv_metrics.get(key)
        eng_val = eng_metrics.get(key)
        diff = pct_diff(tv_val, eng_val)
        tv_str = "-" if tv_val is None else str(tv_val)
        eng_str = "-" if eng_val is None else str(eng_val)
        print(f"{key:<15} {tv_str:>12} {eng_str:>12} {diff:>10}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare tv-backtest-api backtest result with TradingView benchmark JSON.",
    )
    parser.add_argument(
        "--tv",
        required=True,
        help="Path to TradingView benchmark JSON (e.g. validation/tradingview_results/ma_cross_BTCUSDT_1h_2023.json)",
    )
    parser.add_argument(
        "--engine",
        required=True,
        help="Path to engine backtest result JSON (exported from tv-backtest-api).",
    )
    args = parser.parse_args()

    tv_path = Path(args.tv)
    engine_path = Path(args.engine)

    if not tv_path.is_file():
        raise SystemExit(f"TradingView JSON not found: {tv_path}")
    if not engine_path.is_file():
        raise SystemExit(f"Engine JSON not found: {engine_path}")

    tv_json = load_json(tv_path)
    engine_json = load_json(engine_path)
    compare(tv_json, engine_json)


if __name__ == "__main__":
    main()

