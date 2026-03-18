from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.backtest_run import BacktestRun
from app.schemas.backtest import (
    BacktestCreate,
    BacktestResultRead,
    BacktestRunRead,
)
from app.services import backtest_service


router = APIRouter(prefix="/backtests", tags=["backtests"])


@router.post(
    "",
    response_model=BacktestRunRead,
    summary="Run backtest once (synchronous)",
)
def create_backtest(
    payload: BacktestCreate,
    db: Session = Depends(get_db),
) -> BacktestRunRead:
    run = backtest_service.create_backtest_run(
        db,
        dataset_id=payload.dataset_id,
        strategy_id=payload.strategy_id,
        params=payload.params,
        settings=payload.settings,
        start_date=payload.start_date,
        end_date=payload.end_date,
    )
    return BacktestRunRead.model_validate(run)


@router.get(
    "",
    response_model=list[BacktestRunRead],
    summary="List backtest runs",
)
def list_backtests(
    db: Session = Depends(get_db),
) -> list[BacktestRunRead]:
    runs = backtest_service.list_backtest_runs(db)
    return [BacktestRunRead.model_validate(r) for r in runs]


@router.get(
    "/{backtest_run_id}",
    response_model=BacktestRunRead,
    summary="Get backtest run by id",
)
def get_backtest(
    backtest_run_id: int,
    db: Session = Depends(get_db),
) -> BacktestRunRead:
    run = backtest_service.get_backtest_run(db, run_id=backtest_run_id)
    return BacktestRunRead.model_validate(run)


@router.get(
    "/{backtest_run_id}/result",
    response_model=BacktestResultRead,
    summary="Get backtest result JSON",
)
def get_backtest_result(
    backtest_run_id: int,
    db: Session = Depends(get_db),
) -> BacktestResultRead:
    run: BacktestRun = backtest_service.get_backtest_run(db, run_id=backtest_run_id)
    result_dict = backtest_service.get_backtest_result(run)
    return BacktestResultRead(**result_dict)

