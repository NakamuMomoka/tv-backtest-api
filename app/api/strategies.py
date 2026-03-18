from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.strategy import StrategyDetail, StrategyListItem
from app.services import strategy_service


router = APIRouter(prefix="/strategies", tags=["strategies"])


@router.post(
    "",
    response_model=StrategyDetail,
    summary="Create strategy from Python file",
)
async def create_strategy_endpoint(
    name: str = Form(...),
    description: str | None = Form(default=None),
    default_params_json: str | None = Form(default=None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> StrategyDetail:
    strategy = strategy_service.create_strategy(
        db,
        name=name,
        description=description,
        default_params_json=default_params_json,
        upload_file=file,
    )
    return StrategyDetail.model_validate(strategy)


@router.get(
    "",
    response_model=list[StrategyListItem],
    summary="List strategies",
)
async def list_strategies_endpoint(
    db: Session = Depends(get_db),
) -> list[StrategyListItem]:
    strategies = strategy_service.list_strategies(db)
    return [StrategyListItem.model_validate(st) for st in strategies]


@router.get(
    "/{strategy_id}",
    response_model=StrategyDetail,
    summary="Get strategy by id",
)
async def get_strategy_endpoint(
    strategy_id: int,
    db: Session = Depends(get_db),
) -> StrategyDetail:
    strategy = strategy_service.get_strategy(db, strategy_id=strategy_id)
    return StrategyDetail.model_validate(strategy)


@router.delete(
    "/{strategy_id}",
    summary="Delete strategy by id",
)
async def delete_strategy_endpoint(
    strategy_id: int,
    db: Session = Depends(get_db),
) -> dict:
    return strategy_service.delete_strategy(db, strategy_id=strategy_id)


@router.post(
    "/builtins/sync",
    summary="Sync builtin strategies from manifest",
)
async def sync_builtin_strategies_endpoint(
    db: Session = Depends(get_db),
) -> dict:
    result = strategy_service.sync_builtin_strategies(db)
    return {
        "created_count": len(result.get("created", [])),
        "updated_count": len(result.get("updated", [])),
        "skipped_count": len(result.get("skipped", [])),
        "created": result.get("created", []),
        "updated": result.get("updated", []),
        "skipped": result.get("skipped", []),
        "error": result.get("error"),
    }

