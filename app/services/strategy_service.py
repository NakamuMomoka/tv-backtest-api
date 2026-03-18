from pathlib import Path
import json
from typing import Any

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import STRATEGIES_DIR
from app.models.strategy import Strategy


def _ensure_py_extension(filename: str) -> None:
    suffix = Path(filename).suffix.lower()
    if suffix != ".py":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only .py files are allowed for strategies.",
        )


def create_strategy(
    db: Session,
    *,
    name: str,
    description: str | None,
    default_params_json: str | None,
    upload_file: UploadFile,
) -> Strategy:
    _ensure_py_extension(upload_file.filename or "")

    strategy = Strategy(
        name=name,
        description=description,
        file_path="",  # 後で更新
        default_params_json=default_params_json,
        strategy_key=None,
        is_builtin=False,
        source_type="uploaded",
    )
    db.add(strategy)
    db.commit()
    db.refresh(strategy)

    original_name = Path(upload_file.filename or "strategy.py").name
    stored_name = f"{strategy.id}_{original_name}"
    stored_path = STRATEGIES_DIR / stored_name

    with stored_path.open("wb") as f:
        while chunk := upload_file.file.read(1024 * 1024):
            f.write(chunk)

    strategy.file_path = str(stored_path)
    db.add(strategy)
    db.commit()
    db.refresh(strategy)

    return strategy


def list_strategies(db: Session) -> list[Strategy]:
    return db.query(Strategy).order_by(Strategy.id.desc()).all()


def get_strategy(db: Session, strategy_id: int) -> Strategy:
    strategy = db.query(Strategy).filter(Strategy.id == strategy_id).first()
    if strategy is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Strategy not found.",
        )
    return strategy


def delete_strategy(db: Session, strategy_id: int) -> dict[str, Any]:
    """物理削除。アップロードファイルは削除するが、repo 管理の builtin ファイルは削除しない。"""
    strategy = db.query(Strategy).filter(Strategy.id == strategy_id).first()
    if strategy is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Strategy not found.",
        )

    file_path = Path(strategy.file_path) if strategy.file_path else None
    # uploaded のみファイル削除
    if (
        file_path
        and not strategy.is_builtin
        and strategy.source_type == "uploaded"
        and file_path.is_file()
    ):
        file_path.unlink(missing_ok=True)

    db.delete(strategy)
    db.commit()
    return {"ok": True, "deleted_id": strategy_id}


def sync_builtin_strategies(db: Session) -> dict[str, Any]:
    """strategies/manifest.json をもとに builtin strategy を DB と同期する。"""
    manifest_path = Path(__file__).resolve().parent.parent.parent / "strategies" / "manifest.json"

    try:
        with manifest_path.open("r", encoding="utf-8") as f:
            manifest = json.load(f)
    except FileNotFoundError:
        return {
            "created": [],
            "updated": [],
            "skipped": [],
            "error": f"manifest not found: {manifest_path}",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "created": [],
            "updated": [],
            "skipped": [],
            "error": f"failed to read manifest: {exc}",
        }

    if isinstance(manifest, list):
        items = manifest
    else:
        items = manifest.get("strategies") or []

    created: list[dict[str, Any]] = []
    updated: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for item in items:
        key = item.get("key")
        if not key:
            continue

        strategy = (
            db.query(Strategy)
            .filter(Strategy.strategy_key == key)
            .one_or_none()
        )

        name = item.get("name") or key
        description = item.get("description") or ""
        file_path = str(Path("strategies") / item.get("file")) if item.get("file") else ""
        default_params = item.get("default_params") or {}
        default_params_json = json.dumps(default_params, ensure_ascii=False)

        if strategy is None:
            strategy = Strategy(
                strategy_key=key,
                name=name,
                description=description,
                file_path=file_path,
                default_params_json=default_params_json,
                is_builtin=True,
                source_type="builtin",
            )
            db.add(strategy)
            db.flush()
            created.append(
                {
                    "id": strategy.id,
                    "strategy_key": key,
                    "name": name,
                },
            )
        else:
            changed = False
            if strategy.name != name:
                strategy.name = name
                changed = True
            if strategy.description != description:
                strategy.description = description
                changed = True
            if strategy.default_params_json != default_params_json:
                strategy.default_params_json = default_params_json
                changed = True
            if strategy.file_path != file_path:
                strategy.file_path = file_path
                changed = True
            if not strategy.is_builtin:
                strategy.is_builtin = True
                changed = True
            if strategy.source_type != "builtin":
                strategy.source_type = "builtin"
                changed = True

            info = {
                "id": strategy.id,
                "strategy_key": key,
                "name": strategy.name,
            }
            if changed:
                updated.append(info)
            else:
                skipped.append(info)

    db.commit()

    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "error": None,
    }

