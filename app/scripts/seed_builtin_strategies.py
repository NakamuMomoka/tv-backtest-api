import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import BASE_DIR
from app.db.session import Base, SessionLocal, engine
from app.models import strategy as strategy_model  # noqa: F401
from app.models.strategy import Strategy


def load_manifest() -> list[dict]:
    manifest_path = BASE_DIR / "strategies" / "manifest.json"
    if not manifest_path.is_file():
        raise SystemExit(f"manifest.json not found: {manifest_path}")
    with manifest_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise SystemExit("strategies/manifest.json must be a JSON array.")
    return data


def seed_builtin_strategies() -> None:
    # DB が無い場合でもテーブルを作成
    Base.metadata.create_all(bind=engine)

    manifest = load_manifest()
    strategies_dir = BASE_DIR / "strategies"

    db: Session = SessionLocal()
    try:
        for item in manifest:
            key = item.get("key")
            name = item.get("name")
            description = item.get("description") or ""
            rel_file = item.get("file")
            default_params = item.get("default_params") or {}

            if not key or not rel_file or not name:
                raise SystemExit(f"Invalid manifest entry: {item!r}")

            file_path = strategies_dir / rel_file
            if not file_path.is_file():
                raise SystemExit(f"Builtin strategy file not found: {file_path}")

            default_params_json = json.dumps(default_params, ensure_ascii=False)

            existing = (
                db.query(Strategy)
                .filter(Strategy.strategy_key == key)
                .first()
            )

            if existing:
                existing.name = name
                existing.description = description
                existing.file_path = str(file_path)
                existing.default_params_json = default_params_json
                existing.is_builtin = True
                existing.source_type = "builtin"
            else:
                strategy = Strategy(
                    name=name,
                    description=description,
                    file_path=str(file_path),
                    default_params_json=default_params_json,
                    strategy_key=key,
                    is_builtin=True,
                    source_type="builtin",
                )
                db.add(strategy)

        db.commit()
    finally:
        db.close()


def main() -> None:
    seed_builtin_strategies()


if __name__ == "__main__":
    main()

