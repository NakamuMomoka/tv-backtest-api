import json
from pathlib import Path

import pandas as pd
from sqlalchemy.orm import Session

from app.core.config import BASE_DIR
from app.db.session import Base, SessionLocal, engine
from app.models import dataset as dataset_model  # noqa: F401
from app.models.dataset import Dataset


def load_manifest() -> list[dict]:
    manifest_path = BASE_DIR / "datasets" / "manifest.json"
    if not manifest_path.is_file():
        raise SystemExit(f"datasets manifest.json not found: {manifest_path}")
    with manifest_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise SystemExit("datasets/manifest.json must be a JSON array.")
    return data


def seed_builtin_datasets() -> None:
    # DB が無くてもテーブルを作成
    Base.metadata.create_all(bind=engine)

    manifest = load_manifest()
    datasets_dir = BASE_DIR / "datasets"

    db: Session = SessionLocal()
    try:
        for item in manifest:
            key = item.get("key")
            name = item.get("name")
            symbol = item.get("symbol")
            timeframe = item.get("timeframe")
            rel_file = item.get("file")

            if not key or not name or not rel_file:
                raise SystemExit(f"Invalid dataset manifest entry: {item!r}")

            csv_path = datasets_dir / rel_file
            if not csv_path.is_file():
                raise SystemExit(f"Builtin dataset CSV not found: {csv_path}")

            try:
                df = pd.read_csv(csv_path)
                rows_count = int(df.shape[0])
            except Exception as exc:  # noqa: BLE001
                raise SystemExit(f"Failed to read builtin dataset CSV {csv_path}: {exc}")

            existing = (
                db.query(Dataset)
                .filter(Dataset.dataset_key == key)
                .first()
            )

            if existing:
                existing.name = name
                existing.symbol = symbol
                existing.timeframe = timeframe
                existing.file_path = str(csv_path)
                existing.rows_count = rows_count
                existing.is_builtin = True
                existing.source_type = "builtin"
            else:
                dataset = Dataset(
                    name=name,
                    symbol=symbol,
                    timeframe=timeframe,
                    file_path=str(csv_path),
                    rows_count=rows_count,
                    dataset_key=key,
                    is_builtin=True,
                    source_type="builtin",
                )
                db.add(dataset)

        db.commit()
    finally:
        db.close()


def main() -> None:
    seed_builtin_datasets()


if __name__ == "__main__":
    main()

