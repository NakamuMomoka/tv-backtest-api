from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import TV_REFERENCES_DIR
from app.models.dataset import Dataset
from app.models.strategy import Strategy
from app.models.tv_reference_run import TvReferenceRun


_SUMMARY_KEYS = [
    "net_profit",
    "max_drawdown",
    "total_trades",
    "win_rate",
    "profit_factor",
]


def _safe_json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _validate_json_text_or_400(text: str | None, *, field_name: str) -> str | None:
    if text is None or text == "":
        return None
    try:
        json.loads(text)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{field_name} must be valid JSON text: {exc}",
        ) from exc
    return text


def create_tv_reference(
    db: Session,
    *,
    name: str,
    strategy_id: int,
    dataset_id: int,
    start_date: str | None,
    end_date: str | None,
    params_json: str | None,
    summary: dict[str, Any],
    notes: str | None,
    upload_file: UploadFile,
) -> TvReferenceRun:
    params_json = _validate_json_text_or_400(params_json, field_name="params_json")

    # summary は固定キーのみを保存（余計なキーは落とす）
    summary_norm = {k: summary.get(k) for k in _SUMMARY_KEYS}
    summary_json = _safe_json_dumps(summary_norm)

    ref = TvReferenceRun(
        reference_key=None,
        name=name,
        strategy_id=strategy_id,
        dataset_id=dataset_id,
        start_date=start_date,
        end_date=end_date,
        params_json=params_json,
        summary_json=summary_json,
        trades_csv_path="",  # 後で更新
        notes=notes,
        is_builtin=False,
        source_type="uploaded",
    )
    db.add(ref)
    db.commit()
    db.refresh(ref)

    original_name = Path(upload_file.filename or "trades.csv").name
    stored_name = f"{ref.id}_{original_name}"
    stored_path = TV_REFERENCES_DIR / stored_name

    with stored_path.open("wb") as f:
        while chunk := upload_file.file.read(1024 * 1024):
            f.write(chunk)

    ref.trades_csv_path = str(stored_path)
    db.add(ref)
    db.commit()
    db.refresh(ref)
    return ref


def list_tv_references(db: Session) -> list[TvReferenceRun]:
    return db.query(TvReferenceRun).order_by(TvReferenceRun.id.desc()).all()


def delete_tv_reference(db: Session, tv_reference_id: int) -> dict[str, Any]:
    """物理削除。アップロードCSVは削除するが、repo管理の builtin CSV は削除しない。"""
    ref = db.query(TvReferenceRun).filter(TvReferenceRun.id == tv_reference_id).first()
    if ref is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="TV reference not found.",
        )

    file_path = Path(ref.trades_csv_path) if ref.trades_csv_path else None
    if (
        file_path
        and not ref.is_builtin
        and ref.source_type == "uploaded"
        and file_path.is_file()
    ):
        file_path.unlink(missing_ok=True)

    db.delete(ref)
    db.commit()
    return {"ok": True, "deleted_id": tv_reference_id}


def sync_builtin_tv_references(db: Session) -> dict[str, Any]:
    """tv_references/manifest.json をもとに builtin TV reference を DB と同期する。"""
    manifest_path = Path(__file__).resolve().parent.parent.parent / "tv_references" / "manifest.json"

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
        items = manifest.get("tv_references") or manifest.get("references") or []

    created: list[dict[str, Any]] = []
    updated: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    errors: list[str] = []

    for item in items:
        key = item.get("key") or item.get("reference_key")
        if not key:
            continue

        name = item.get("name") or key
        strategy_id = item.get("strategy_id")
        dataset_id = item.get("dataset_id")
        strategy_key = item.get("strategy_key")
        dataset_key = item.get("dataset_key")
        start_date = item.get("start_date")
        end_date = item.get("end_date")
        params = item.get("params") if "params" in item else item.get("params_json")
        summary = item.get("summary") if "summary" in item else item.get("summary_json")
        notes = item.get("notes")
        trades_file = item.get("trades_csv") or item.get("trades_csv_file") or item.get("trades_file")

        # strategy/dataset の参照は id または key を許可する
        resolved_strategy_id: int | None = int(strategy_id) if strategy_id is not None else None
        resolved_dataset_id: int | None = int(dataset_id) if dataset_id is not None else None

        if resolved_strategy_id is None and strategy_key:
            st = db.query(Strategy).filter(Strategy.strategy_key == strategy_key).one_or_none()
            if st is None:
                errors.append(f"strategy_key not found for key={key}: {strategy_key}")
                continue
            resolved_strategy_id = int(st.id)

        if resolved_dataset_id is None and dataset_key:
            ds = db.query(Dataset).filter(Dataset.dataset_key == dataset_key).one_or_none()
            if ds is None:
                errors.append(f"dataset_key not found for key={key}: {dataset_key}")
                continue
            resolved_dataset_id = int(ds.id)

        if resolved_strategy_id is None or resolved_dataset_id is None:
            errors.append(
                f"missing strategy/dataset reference for key={key} "
                f"(provide strategy_id or strategy_key, dataset_id or dataset_key)",
            )
            continue

        # params / summary は dict の場合は dump、str の場合は JSON として検証
        if isinstance(params, dict):
            params_json = _safe_json_dumps(params)
        else:
            try:
                params_json = _validate_json_text_or_400(
                    str(params) if params is not None else None,
                    field_name="params_json",
                )
            except HTTPException as exc:
                errors.append(f"invalid params_json for key={key}: {exc.detail}")
                continue

        if isinstance(summary, dict):
            summary_norm = {k: summary.get(k) for k in _SUMMARY_KEYS}
            summary_json = _safe_json_dumps(summary_norm)
        elif summary is None:
            summary_json = _safe_json_dumps({k: None for k in _SUMMARY_KEYS})
        else:
            # 文字列として保存するが、最低限 JSON として妥当かはチェック
            try:
                summary_json = _validate_json_text_or_400(
                    str(summary),
                    field_name="summary_json",
                ) or _safe_json_dumps({k: None for k in _SUMMARY_KEYS})
            except HTTPException as exc:
                errors.append(f"invalid summary_json for key={key}: {exc.detail}")
                continue

        trades_csv_path = ""
        if trades_file:
            candidate = Path(__file__).resolve().parent.parent.parent / "tv_references" / trades_file
            if not candidate.is_file():
                errors.append(f"trades csv not found for key={key}: {candidate}")
                continue
            # repo 管理ファイルは相対パスで保持
            trades_csv_path = str(Path("tv_references") / trades_file)

        ref = (
            db.query(TvReferenceRun)
            .filter(TvReferenceRun.reference_key == key)
            .one_or_none()
        )

        if ref is None:
            ref = TvReferenceRun(
                reference_key=key,
                name=name,
                strategy_id=resolved_strategy_id,
                dataset_id=resolved_dataset_id,
                start_date=start_date,
                end_date=end_date,
                params_json=params_json,
                summary_json=summary_json,
                trades_csv_path=trades_csv_path,
                notes=notes,
                is_builtin=True,
                source_type="builtin",
            )
            db.add(ref)
            db.flush()
            created.append({"id": ref.id, "reference_key": key, "name": name})
        else:
            changed = False
            if ref.name != name:
                ref.name = name
                changed = True
            if ref.strategy_id != resolved_strategy_id:
                ref.strategy_id = resolved_strategy_id
                changed = True
            if ref.dataset_id != resolved_dataset_id:
                ref.dataset_id = resolved_dataset_id
                changed = True
            if ref.start_date != start_date:
                ref.start_date = start_date
                changed = True
            if ref.end_date != end_date:
                ref.end_date = end_date
                changed = True
            if ref.params_json != params_json:
                ref.params_json = params_json
                changed = True
            if ref.summary_json != summary_json:
                ref.summary_json = summary_json
                changed = True
            if ref.trades_csv_path != trades_csv_path:
                ref.trades_csv_path = trades_csv_path
                changed = True
            if ref.notes != notes:
                ref.notes = notes
                changed = True
            if not ref.is_builtin:
                ref.is_builtin = True
                changed = True
            if ref.source_type != "builtin":
                ref.source_type = "builtin"
                changed = True

            info = {"id": ref.id, "reference_key": key, "name": ref.name}
            if changed:
                updated.append(info)
            else:
                skipped.append(info)

    db.commit()
    error_msg: str | None = None
    if errors:
        error_msg = "; ".join(errors)

    return {"created": created, "updated": updated, "skipped": skipped, "error": error_msg}

