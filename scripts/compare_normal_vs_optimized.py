from __future__ import annotations

import argparse
import json

from app.db.session import SessionLocal
from app.services.optimization_validation import (
    compare_backtest_results_normal_vs_optimized,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare normal vs optimization-mode backtest outputs.",
    )
    parser.add_argument("--dataset-id", type=int, required=True)
    parser.add_argument("--strategy-id", type=int, required=True)
    parser.add_argument("--params-json", type=str, default="{}")
    parser.add_argument("--settings-json", type=str, default="{}")
    parser.add_argument("--start-date", type=str, default=None)
    parser.add_argument("--end-date", type=str, default=None)
    parser.add_argument(
        "--no-trades",
        action="store_true",
        help="Skip trade list comparison (metrics only).",
    )
    args = parser.parse_args()

    params = json.loads(args.params_json) if args.params_json else {}
    settings = json.loads(args.settings_json) if args.settings_json else {}

    db = SessionLocal()
    try:
        result = compare_backtest_results_normal_vs_optimized(
            db,
            dataset_id=args.dataset_id,
            strategy_id=args.strategy_id,
            params=params,
            settings=settings,
            start_date=args.start_date,
            end_date=args.end_date,
            compare_trade_list=not args.no_trades,
        )
    finally:
        db.close()

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
