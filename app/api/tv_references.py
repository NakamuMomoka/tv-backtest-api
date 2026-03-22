from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.tv_reference import TvReferenceDetail, TvReferenceListItem
from app.services import tv_reference_service


router = APIRouter(prefix="/tv-references", tags=["tv-references"])


@router.post(
    "",
    response_model=TvReferenceDetail,
    summary="Create TV reference (TradingView benchmark) with trades CSV",
)
async def create_tv_reference_endpoint(
    name: str = Form(...),
    strategy_id: int = Form(...),
    dataset_id: int = Form(...),
    start_date: str | None = Form(default=None),
    end_date: str | None = Form(default=None),
    params_json: str | None = Form(default=None),
    net_profit: float | None = Form(default=None),
    max_drawdown: float | None = Form(default=None),
    total_trades: int | None = Form(default=None),
    win_rate: float | None = Form(default=None),
    profit_factor: float | None = Form(default=None),
    notes: str | None = Form(default=None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> TvReferenceDetail:
    ref = tv_reference_service.create_tv_reference(
        db,
        name=name,
        strategy_id=strategy_id,
        dataset_id=dataset_id,
        start_date=start_date,
        end_date=end_date,
        params_json=params_json,
        summary={
            "net_profit": net_profit,
            "max_drawdown": max_drawdown,
            "total_trades": total_trades,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
        },
        notes=notes,
        upload_file=file,
    )
    return TvReferenceDetail.model_validate(ref)


@router.get(
    "",
    response_model=list[TvReferenceListItem],
    summary="List TV references",
)
async def list_tv_references_endpoint(
    db: Session = Depends(get_db),
) -> list[TvReferenceListItem]:
    refs = tv_reference_service.list_tv_references(db)
    return [TvReferenceListItem.model_validate(r) for r in refs]


@router.delete(
    "/{tv_reference_id}",
    summary="Delete TV reference by id",
)
async def delete_tv_reference_endpoint(
    tv_reference_id: int,
    db: Session = Depends(get_db),
) -> dict:
    return tv_reference_service.delete_tv_reference(db, tv_reference_id=tv_reference_id)


@router.post(
    "/builtins/sync",
    summary="Sync builtin TV references from manifest",
)
async def sync_builtin_tv_references_endpoint(
    db: Session = Depends(get_db),
) -> dict:
    result = tv_reference_service.sync_builtin_tv_references(db)
    return {
        "created_count": len(result.get("created", [])),
        "updated_count": len(result.get("updated", [])),
        "skipped_count": len(result.get("skipped", [])),
        "created": result.get("created", []),
        "updated": result.get("updated", []),
        "skipped": result.get("skipped", []),
        "error": result.get("error"),
    }

