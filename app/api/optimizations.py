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


def _validate_search_space(search_space: dict[str, Any]) -> tuple[dict[str, list[Any]], int]:
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

    return normalized, total_combinations


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
    if mode not in ("grid", "random", "guided_random"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="search_mode must be 'grid', 'random', or 'guided_random'.",
        )
    if (payload.trials_per_set is not None) ^ (payload.set_count is not None):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="trials_per_set and set_count must be specified together.",
        )

    has_batch = (
        payload.trials_per_set is not None
        and payload.set_count is not None
    )
    if has_batch:
        if mode == "grid":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="trials_per_set / set_count are only valid for search_mode 'random' or 'guided_random'.",
            )
        if int(payload.trials_per_set or 0) <= 0 or int(payload.set_count or 0) <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="trials_per_set and set_count must be positive integers.",
            )
        if int(payload.trials_per_set or 0) * int(payload.set_count or 0) <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="total planned trials (trials_per_set * set_count) must be positive.",
            )
    elif mode in ("random", "guided_random"):
        if payload.n_trials is None or payload.n_trials <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="n_trials must be positive when search_mode is 'random' or 'guided_random' "
                "(unless using trials_per_set + set_count).",
            )

    if mode == "grid" and has_batch:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="trials_per_set / set_count cannot be used with grid search.",
        )

    validated_search_space, total_combinations = _validate_search_space(payload.search_space)
    # grid は全探索なので上限を厳密に適用する
    if mode == "grid" and total_combinations > OPT_SEARCH_SPACE_HARD_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Total number of parameter combinations in search_space "
                f"({total_combinations}) exceeds the hard maximum of "
                f"{OPT_SEARCH_SPACE_HARD_LIMIT} for grid search."
            ),
        )

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
        trials_per_set=payload.trials_per_set if has_batch else None,
        set_count=payload.set_count if has_batch else None,
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
        description="Filter by search_mode (grid/random/guided_random)",
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
    if run.status == "failed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=run.error_message or "Optimization failed.",
        )

    # running / pending: 途中保存された result JSON があれば返す（セット分割ジョブ）
    if run.status in ("pending", "running"):
        try:
            result_dict = optimization_service.get_optimization_result(run)
            return OptimizationResultRead(**result_dict)
        except HTTPException as exc:
            if exc.status_code == status.HTTP_404_NOT_FOUND:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Optimization has not finished yet (no result file yet).",
                ) from exc
            raise

    result_dict = optimization_service.get_optimization_result(run)
    return OptimizationResultRead(**result_dict)

