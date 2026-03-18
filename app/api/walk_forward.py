from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.walk_forward import (
    WalkForwardCreate,
    WalkForwardResultRead,
    WalkForwardRunRead,
)
from app.services import walk_forward_service


router = APIRouter(prefix="/walk-forward", tags=["walk-forward"])


def _validate_search_space(search_space: dict[str, Any]) -> dict[str, list[Any]]:
    if not isinstance(search_space, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="search_space must be an object (dict[str, list]).",
        )

    total_combinations = 1
    normalized: dict[str, list[Any]] = {}

    for key, value in search_space.items():
        if not isinstance(key, str) or not key.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="search_space parameter names must be non-empty strings.",
            )

        if not isinstance(value, list):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"search_space['{key}'] must be a list of values.",
            )

        if len(value) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"search_space['{key}'] must not be an empty list.",
            )

        normalized[key] = value
        total_combinations *= len(value)

        if total_combinations > 1000:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Total number of parameter combinations in search_space "
                    f"({total_combinations}) exceeds the maximum of 1000."
                ),
            )

    return normalized


@router.post(
    "",
    response_model=WalkForwardRunRead,
    summary="Run walk-forward optimization and backtest (synchronous)",
)
def create_walk_forward(
    payload: WalkForwardCreate,
    db: Session = Depends(get_db),
) -> WalkForwardRunRead:
    if payload.train_bars <= 0 or payload.test_bars <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="train_bars and test_bars must be > 0.",
        )

    step_bars = payload.step_bars or payload.test_bars
    if step_bars <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="step_bars must be > 0.",
        )

    search_space = _validate_search_space(payload.search_space)

    run = walk_forward_service.create_walk_forward_run(
        db,
        dataset_id=payload.dataset_id,
        strategy_id=payload.strategy_id,
        search_space=search_space,
        settings=payload.settings or {},
        objective_metric=payload.objective_metric,
        train_bars=payload.train_bars,
        test_bars=payload.test_bars,
        step_bars=step_bars,
        min_trades=payload.min_trades,
        start_date=payload.start_date,
        end_date=payload.end_date,
    )
    return WalkForwardRunRead.model_validate(run)


@router.get(
    "",
    response_model=list[WalkForwardRunRead],
    summary="List walk-forward runs",
)
def list_walk_forward_runs(
    db: Session = Depends(get_db),
) -> list[WalkForwardRunRead]:
    runs = walk_forward_service.list_walk_forward_runs(db)
    return [WalkForwardRunRead.model_validate(r) for r in runs]


@router.get(
    "/{run_id}",
    response_model=WalkForwardRunRead,
    summary="Get walk-forward run by id",
)
def get_walk_forward_run(
    run_id: int,
    db: Session = Depends(get_db),
) -> WalkForwardRunRead:
    run = walk_forward_service.get_walk_forward_run(db, run_id=run_id)
    return WalkForwardRunRead.model_validate(run)


@router.get(
    "/{run_id}/result",
    response_model=WalkForwardResultRead,
    summary="Get walk-forward result JSON",
)
def get_walk_forward_result(
    run_id: int,
    db: Session = Depends(get_db),
) -> WalkForwardResultRead:
    run = walk_forward_service.get_walk_forward_run(db, run_id=run_id)
    result_dict = walk_forward_service.get_walk_forward_result(run)
    return WalkForwardResultRead(**result_dict)

