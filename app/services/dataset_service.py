from pathlib import Path
import json
from typing import Any

import pandas as pd
from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import DATASETS_DIR
from app.models.dataset import Dataset


def _ensure_csv_extension(filename: str) -> None:
    suffix = Path(filename).suffix.lower()
    if suffix != ".csv":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only .csv files are allowed for datasets.",
        )


def create_dataset(
    db: Session,
    *,
    name: str,
    symbol: str | None,
    timeframe: str | None,
    upload_file: UploadFile,
) -> Dataset:
    _ensure_csv_extension(upload_file.filename or "")

    dataset = Dataset(
        name=name,
        symbol=symbol,
        timeframe=timeframe,
        file_path="",  # 後で更新
        dataset_key=None,
        is_builtin=False,
        source_type="uploaded",
    )
    db.add(dataset)
    db.commit()
    db.refresh(dataset)

    original_name = Path(upload_file.filename or "dataset.csv").name
    stored_name = f"{dataset.id}_{original_name}"
    stored_path = DATASETS_DIR / stored_name

    with stored_path.open("wb") as f:
        while chunk := upload_file.file.read(1024 * 1024):
            f.write(chunk)

    try:
        df = pd.read_csv(stored_path)
        rows_count = int(df.shape[0])
    except Exception as exc:  # noqa: BLE001
        stored_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to parse CSV: {exc}",
        ) from exc

    dataset.file_path = str(stored_path)
    dataset.rows_count = rows_count
    db.add(dataset)
    db.commit()
    db.refresh(dataset)

    return dataset


def list_datasets(db: Session) -> list[Dataset]:
    return db.query(Dataset).order_by(Dataset.id.desc()).all()


def get_dataset(db: Session, dataset_id: int) -> Dataset:
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found.",
        )
    return dataset


def delete_dataset(db: Session, dataset_id: int) -> dict[str, Any]:
    """物理削除。アップロードファイルは削除するが、repo 管理の builtin ファイルは削除しない。"""
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found.",
        )

    file_path = Path(dataset.file_path) if dataset.file_path else None
    # uploaded のみファイル削除（is_builtin=False, source_type="uploaded" を想定）
    if (
        file_path
        and not dataset.is_builtin
        and dataset.source_type == "uploaded"
        and file_path.is_file()
    ):
        file_path.unlink(missing_ok=True)

    db.delete(dataset)
    db.commit()
    return {"ok": True, "deleted_id": dataset_id}


def sync_builtin_datasets(db: Session) -> dict[str, Any]:
    """datasets/manifest.json をもとに builtin dataset を DB と同期する。"""
    manifest_path = Path(__file__).resolve().parent.parent.parent / "datasets" / "manifest.json"

    try:
        with manifest_path.open("r", encoding="utf-8") as f:
            manifest = json.load(f)
    except FileNotFoundError:
        return {"created": [], "updated": [], "skipped": [], "error": f"manifest not found: {manifest_path}"}
    except Exception as exc:  # noqa: BLE001
        return {"created": [], "updated": [], "skipped": [], "error": f"failed to read manifest: {exc}"}

    if isinstance(manifest, list):
        items = manifest
    else:
        items = manifest.get("datasets") or []

    created: list[dict[str, Any]] = []
    updated: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for item in items:
        key = item.get("key")
        if not key:
            continue

        dataset = (
            db.query(Dataset)
            .filter(Dataset.dataset_key == key)
            .one_or_none()
        )

        name = item.get("name") or key
        symbol = item.get("symbol")
        timeframe = item.get("timeframe")
        file_path = str(Path("datasets") / item.get("file")) if item.get("file") else ""

        if dataset is None:
            dataset = Dataset(
                dataset_key=key,
                name=name,
                symbol=symbol,
                timeframe=timeframe,
                file_path=file_path,
                rows_count=None,
                is_builtin=True,
                source_type="builtin",
            )
            db.add(dataset)
            db.flush()
            created.append(
                {"id": dataset.id, "dataset_key": key, "name": name},
            )
        else:
            changed = False
            if dataset.name != name:
                dataset.name = name
                changed = True
            if dataset.symbol != symbol:
                dataset.symbol = symbol
                changed = True
            if dataset.timeframe != timeframe:
                dataset.timeframe = timeframe
                changed = True
            if dataset.file_path != file_path:
                dataset.file_path = file_path
                changed = True
            if not dataset.is_builtin:
                dataset.is_builtin = True
                changed = True
            if dataset.source_type != "builtin":
                dataset.source_type = "builtin"
                changed = True

            info = {"id": dataset.id, "dataset_key": key, "name": dataset.name}
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

