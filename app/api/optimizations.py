from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.config import OPT_SEARCH_SPACE_HARD_LIMIT
from app.db.session import get_db
from app.schemas.optimization import (
    OptimizationCreate,
    OptimizationResultRead,
    OptimizationRunRead,
)
from app.services import optimization_service


router = APIRouter(prefix="/optimizations", tags=["optimizations"])


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

        if total_combinations > OPT_SEARCH_SPACE_HARD_LIMIT:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Total number of parameter combinations in search_space "
                    f"({total_combinations}) exceeds the hard maximum of "
                    f"{OPT_SEARCH_SPACE_HARD_LIMIT}."
                ),
            )

    return normalized


@router.post(
    "",
    response_model=OptimizationRunRead,
    summary="Enqueue optimization with grid search (asynchronous)",
)
def create_optimization(
    payload: OptimizationCreate,
    db: Session = Depends(get_db),
    background_tasks: BackgroundTasks = None,
) -> OptimizationRunRead:
    # search_mode validation
    mode = (payload.search_mode or "grid").lower()
    if mode not in ("grid", "random"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="search_mode must be 'grid' or 'random'.",
        )
    if mode == "random":
        if payload.n_trials is None or payload.n_trials <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="n_trials must be positive when search_mode='random'.",
            )

    validated_search_space = _validate_search_space(payload.search_space)

    run = optimization_service.enqueue_optimization_run(
        db,
        dataset_id=payload.dataset_id,
        strategy_id=payload.strategy_id,
        search_space=validated_search_space,
        settings=payload.settings,
        objective_metric=payload.objective_metric,
        search_mode=mode,
        n_trials=payload.n_trials,
        start_date=payload.start_date,
        end_date=payload.end_date,
    )

    # Enqueue background job to execute the optimization.
    # NOTE: This is an MVP implementation using FastAPI BackgroundTasks.
    # In the future, this can be replaced with a real job queue (Celery/RQ/etc.).
    if background_tasks is not None:
        background_tasks.add_task(optimization_service.run_optimization_job, run.id)

    return OptimizationRunRead.model_validate(run)


@router.get(
    "",
    response_model=list[OptimizationRunRead],
    summary="List optimization runs",
)
def list_optimizations(
    status_filter: Optional[str] = Query(
        default=None,
        alias="status",
        description="Filter by status (pending/running/success/failed)",
    ),
    search_mode: Optional[str] = Query(
        default=None,
        description="Filter by search_mode (grid/random)",
    ),
    limit: int = Query(
        default=50,
        ge=1,
        le=500,
        description="Maximum number of runs to return",
    ),
    db: Session = Depends(get_db),
) -> list[OptimizationRunRead]:
    runs = optimization_service.list_optimization_runs(
        db,
        status_filter=status_filter,
        search_mode=search_mode,
        limit=limit,
    )
    return [OptimizationRunRead.model_validate(r) for r in runs]


@router.get(
    "/{optimization_run_id}",
    response_model=OptimizationRunRead,
    summary="Get optimization run by id",
)
def get_optimization(
    optimization_run_id: int,
    db: Session = Depends(get_db),
) -> OptimizationRunRead:
    run = optimization_service.get_optimization_run(db, run_id=optimization_run_id)
    return OptimizationRunRead.model_validate(run)


@router.get(
    "/{optimization_run_id}/result",
    response_model=OptimizationResultRead,
    summary="Get optimization result JSON",
)
def get_optimization_result(
    optimization_run_id: int,
    db: Session = Depends(get_db),
) -> OptimizationResultRead:
    run = optimization_service.get_optimization_run(db, run_id=optimization_run_id)
    # Only allow result retrieval once the optimization has finished successfully.
    if run.status in ("pending", "running"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Optimization has not finished yet.",
        )
    if run.status == "failed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=run.error_message or "Optimization failed.",
        )

    result_dict = optimization_service.get_optimization_result(run)
    return OptimizationResultRead(**result_dict)

