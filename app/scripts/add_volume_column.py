import argparse
from pathlib import Path

import pandas as pd


def normalize_csv(path: Path) -> None:
    if not path.is_file():
        raise SystemExit(f"CSV not found: {path}")

    df = pd.read_csv(path)

    # volume 列が無ければ追加（既存データはそのまま、行数も変えない）
    if "volume" not in df.columns:
        df["volume"] = 1.0

    # 列順を調整: timestamp, open, high, low, close, volume を先頭に、それ以外はそのまま後ろに残す
    desired = ["timestamp", "open", "high", "low", "close", "volume"]
    existing_desired = [c for c in desired if c in df.columns]
    others = [c for c in df.columns if c not in existing_desired]
    df = df[existing_desired + others]

    df.to_csv(path, index=False)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Add volume column to backtest CSV in-place. "
            "If 'volume' column is missing, it is added with default 1.0. "
            "Columns are reordered to start with "
            "[timestamp, open, high, low, close, volume] when present."
        ),
    )
    parser.add_argument(
        "csv_path",
        help="Path to target CSV file.",
    )
    args = parser.parse_args()

    normalize_csv(Path(args.csv_path))


if __name__ == "__main__":
    main()

