from __future__ import annotations

import itertools
import json
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import OPTIMIZATION_RESULTS_DIR
from app.db.session import SessionLocal
from app.models.dataset import Dataset
from app.models.optimization_run import OptimizationRun
from app.models.strategy import Strategy
from app.services.dataset_cache import get_dataset_bars
from app.services.serialization import to_jsonable
from app.services.strategy_runner import (
    StrategyExecutionError,
    run_strategy_backtest_on_bars,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _get_dataset_or_404(db: Session, dataset_id: int) -> Dataset:
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found.",
        )
    return dataset


def _get_strategy_or_404(db: Session, strategy_id: int) -> Strategy:
    strategy = db.query(Strategy).filter(Strategy.id == strategy_id).first()
    if strategy is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Strategy not found.",
        )
    return strategy


def _filter_bars_by_date(
    bars: pd.DataFrame,
    start_date: str | None,
    end_date: str | None,
) -> pd.DataFrame:
    if not start_date and not end_date:
        return bars

    if "timestamp" in bars.columns:
        ts = pd.to_datetime(bars["timestamp"], errors="coerce", utc=True)
    elif "time" in bars.columns:
        ts = pd.to_datetime(bars["time"], errors="coerce", utc=True, unit="s")
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Dataset must contain 'timestamp' or 'time' column when using start_date/end_date.",
        )
    mask = ~ts.isna()

    if start_date:
        start = pd.to_datetime(start_date, utc=True)
        mask &= ts >= start
    if end_date:
        end = pd.to_datetime(end_date, utc=True)
        mask &= ts <= end

    return bars.loc[mask].copy()


def _iter_param_combinations(search_space: dict[str, list[Any]]):
    if not search_space:
        yield {}
        return

    keys = list(search_space.keys())
    value_lists = [search_space[k] for k in keys]
    for values in itertools.product(*value_lists):
        yield {k: v for k, v in zip(keys, values, strict=True)}


def _score_from_metrics(
    metrics: dict[str, Any],
    objective_metric: str | None,
) -> float:
    if objective_metric and objective_metric in metrics:
        value = metrics.get(objective_metric)
        return float(value) if isinstance(value, (int, float)) else 0.0

    for key in ("net_profit", "profit_factor"):
        if key in metrics and isinstance(metrics[key], (int, float)):
            return float(metrics[key])

    return 0.0


def normalize_params(params: dict[str, Any]) -> dict[str, Any]:
    """Normalize params for stable comparison.

    Currently we assume values are bool/int/float/str, so we just copy.
    This is the hook to add more complex normalization in the future.
    """
    return dict(params or {})


def params_signature(params: dict[str, Any]) -> str:
    """Return a key-order-independent signature for params."""
    normalized = normalize_params(params)
    return json.dumps(
        normalized,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def collect_previously_tested_signatures(
    db: Session,
    *,
    dataset_id: int,
    strategy_id: int,
    start_date: str | None,
    end_date: str | None,
    objective_metric: str | None,
) -> set[str]:
    """Collect signatures of previously tested params for the given context.

    We consider runs that share:
    - dataset_id
    - strategy_id
    - start_date
    - end_date
    - objective_metric
    """
    q = db.query(OptimizationRun).filter(
        OptimizationRun.dataset_id == dataset_id,
        OptimizationRun.strategy_id == strategy_id,
    )
    if start_date:
        q = q.filter(OptimizationRun.start_date == start_date)
    if end_date:
        q = q.filter(OptimizationRun.end_date == end_date)
    if objective_metric:
        q = q.filter(OptimizationRun.objective_metric == objective_metric)

    signatures: set[str] = set()

    for run in q.all():
        if not run.result_path:
            continue
        path = Path(run.result_path)
        if not path.exists():
            continue
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:  # noqa: BLE001
            continue

        for trial in data.get("trials") or []:
            params = trial.get("params")
            if isinstance(params, dict):
                signatures.add(params_signature(params))

    return signatures


def enqueue_optimization_run(
    db: Session,
    *,
    dataset_id: int,
    strategy_id: int,
    search_space: dict[str, list[Any]],
    settings: dict[str, Any] | None,
    objective_metric: str | None,
    search_mode: str | None,
    n_trials: int | None,
    start_date: str | None,
    end_date: str | None,
) -> OptimizationRun:
    # Ensure dataset/strategy exist up front for fast failure.
    _get_dataset_or_404(db, dataset_id)
    _get_strategy_or_404(db, strategy_id)

    search_space_json = json.dumps(to_jsonable(search_space or {}))
    settings_json = json.dumps(to_jsonable(settings or {}))

    run = OptimizationRun(
        dataset_id=dataset_id,
        strategy_id=strategy_id,
        start_date=start_date,
        end_date=end_date,
        search_space_json=search_space_json,
        settings_json=settings_json,
        objective_metric=objective_metric,
        search_mode=search_mode,
        n_trials=n_trials,
        status="pending",
        created_at=_utcnow(),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def run_optimization_job(optimization_run_id: int) -> None:
    """Execute optimization grid search in background.

    This function is designed to be called from FastAPI BackgroundTasks or
    a future job queue worker. It opens its own DB session.
    """
    db = SessionLocal()
    try:
        run = db.query(OptimizationRun).filter(OptimizationRun.id == optimization_run_id).first()
        if run is None:
            # Nothing we can do; log and exit.
            print(f"[optimization_job] OptimizationRun {optimization_run_id} not found.")
            return

        # Mark as running
        run.status = "running"
        run.error_message = None
        run.finished_at = None
        db.add(run)
        db.commit()
        db.refresh(run)

        # Load dataset and strategy
        dataset = _get_dataset_or_404(db, run.dataset_id)
        strategy = _get_strategy_or_404(db, run.strategy_id)

        csv_path = Path(dataset.file_path)
        try:
            bars = get_dataset_bars(csv_path)
        except Exception as exc:  # noqa: BLE001
            msg = f"Failed to load dataset CSV: {exc}"
            print(f"[optimization_job] {msg}")
            run.status = "failed"
            run.error_message = msg
            run.finished_at = _utcnow()
            db.add(run)
            db.commit()
            return

        bars = _filter_bars_by_date(bars, run.start_date, run.end_date)

        # Decode JSON fields
        try:
            search_space = json.loads(run.search_space_json or "{}")
        except json.JSONDecodeError:
            search_space = {}
        try:
            settings = json.loads(run.settings_json or "{}")
        except json.JSONDecodeError:
            settings = {}

        # Use stored objective_metric if provided; otherwise fall back to default.
        objective_metric = run.objective_metric

        # Decide search mode
        search_mode = (run.search_mode or "grid").lower()

        # Enumerate all candidate combinations (bounded by OPT_SEARCH_SPACE_HARD_LIMIT)
        all_params_list = list(_iter_param_combinations(search_space))
        total_candidate_combinations = len(all_params_list)

        # Collect previously tested signatures (same dataset/strategy/start/end/objective_metric)
        previously_tested: set[str] = set()
        if search_mode == "random":
            previously_tested = collect_previously_tested_signatures(
                db,
                dataset_id=run.dataset_id,
                strategy_id=run.strategy_id,
                start_date=run.start_date,
                end_date=run.end_date,
                objective_metric=objective_metric,
            )

        requested_trials: int | None = None
        executed_trials: int = 0
        excluded_previously_tested: int | None = None
        message: str | None = None

        if search_mode == "grid":
            selected_params_list = all_params_list
            requested_trials = len(all_params_list)
            executed_trials = len(all_params_list)
        else:
            n_trials = run.n_trials or 0
            requested_trials = n_trials

            unseen_params = []
            for p in all_params_list:
                sig = params_signature(p)
                if sig not in previously_tested:
                    unseen_params.append(p)

            excluded_previously_tested = total_candidate_combinations - len(unseen_params)

            random.shuffle(unseen_params)
            if n_trials > 0:
                selected_params_list = unseen_params[:n_trials]
            else:
                selected_params_list = []

            executed_trials = len(selected_params_list)

            if executed_trials == 0:
                message = "No unseen candidates remaining."

        trials: list[dict[str, Any]] = []
        best_params: dict[str, Any] = {}
        best_score: float | None = None
        any_success = False

        for params in selected_params_list:
            trial: dict[str, Any] = {"params": params}
            try:
                result = run_strategy_backtest_on_bars(
                    bars=bars,
                    strategy=strategy,
                    params=params,
                    settings=settings or {},
                )
                normalized_result = to_jsonable(result)
                metrics = normalized_result.get("metrics") or {}
                trial["metrics"] = to_jsonable(metrics)
                score = _score_from_metrics(metrics, objective_metric)
                trial["score"] = score
                any_success = True

                if best_score is None or score > best_score:
                    best_score = score
                    best_params = params
            except StrategyExecutionError as exc:
                trial["error_message"] = str(exc)
            except Exception as exc:  # noqa: BLE001
                trial["error_message"] = f"Unexpected error: {exc}"

            trials.append(trial)

        objective_key = objective_metric or "net_profit"

        result_payload = to_jsonable(
            {
                "trials": trials,
                "best_params": best_params,
                "best_score": best_score,
                "objective_metric": objective_key,
                "start_date": run.start_date,
                "end_date": run.end_date,
                "search_mode": search_mode,
                "requested_trials": requested_trials,
                "executed_trials": executed_trials,
                "total_candidate_combinations": total_candidate_combinations,
                "excluded_previously_tested": excluded_previously_tested,
                "message": message,
            },
        )

        result_path = OPTIMIZATION_RESULTS_DIR / f"{run.id}.json"
        with result_path.open("w", encoding="utf-8") as f:
            json.dump(result_payload, f, ensure_ascii=False, indent=2)

        run.result_path = str(result_path)
        run.best_params_json = json.dumps(to_jsonable(best_params or {}))
        run.best_score = best_score
        # If we had no selected params (e.g. no unseen candidates), treat as success with 0 trials
        if executed_trials == 0 and total_candidate_combinations >= 0:
            run.status = "success"
            run.error_message = message
        else:
            run.status = "success" if any_success else "failed"
            if not any_success and executed_trials > 0:
                run.error_message = "All trials failed."

        run.finished_at = _utcnow()
        run.requested_trials = requested_trials
        run.executed_trials = executed_trials
        run.total_candidate_combinations = total_candidate_combinations
        run.excluded_previously_tested = excluded_previously_tested
        run.message = message

        db.add(run)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        # Best-effort final error recording
        print(f"[optimization_job] Unexpected error for run {optimization_run_id}: {exc}")
        try:
            run = db.query(OptimizationRun).filter(
                OptimizationRun.id == optimization_run_id,
            ).first()
            if run is not None:
                run.status = "failed"
                msg = f"Unexpected error: {exc}"
                run.error_message = msg
                run.finished_at = _utcnow()
                db.add(run)
                db.commit()
        except Exception:  # noqa: BLE001
            # Give up if even error recording fails
            pass
    finally:
        db.close()


def list_optimization_runs(
    db: Session,
    *,
    status_filter: str | None = None,
    search_mode: str | None = None,
    limit: int | None = None,
) -> list[OptimizationRun]:
    q = db.query(OptimizationRun)

    if status_filter:
        q = q.filter(OptimizationRun.status == status_filter)

    if search_mode:
        q = q.filter(OptimizationRun.search_mode == search_mode)

    q = q.order_by(OptimizationRun.created_at.desc())

    if limit is not None:
        q = q.limit(limit)

    return q.all()


def get_optimization_run(db: Session, run_id: int) -> OptimizationRun:
    run = db.query(OptimizationRun).filter(OptimizationRun.id == run_id).first()
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="OptimizationRun not found.",
        )
    return run


def get_optimization_result(run: OptimizationRun) -> dict[str, Any]:
    if not run.result_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Optimization result not found.",
        )

    path = OPTIMIZATION_RESULTS_DIR / f"{run.id}.json"
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Optimization result file not found.",
        )

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    trials = data.get("trials") or []
    best_params = data.get("best_params") or {}
    best_score = data.get("best_score")
    objective_metric = data.get("objective_metric") or "net_profit"
    search_mode = data.get("search_mode")
    requested_trials = data.get("requested_trials")
    executed_trials = data.get("executed_trials")
    total_candidate_combinations = data.get("total_candidate_combinations")
    excluded_previously_tested = data.get("excluded_previously_tested")
    message = data.get("message")

    if not isinstance(trials, list):
        trials = []
    if not isinstance(best_params, dict):
        best_params = {}
    if not isinstance(best_score, (int, float)) and best_score is not None:
        best_score = None
    if not isinstance(objective_metric, str):
        objective_metric = "net_profit"

    return {
        "trials": trials,
        "best_params": best_params,
        "best_score": best_score,
        "objective_metric": objective_metric,
        "search_mode": search_mode,
        "requested_trials": requested_trials,
        "executed_trials": executed_trials,
        "total_candidate_combinations": total_candidate_combinations,
        "excluded_previously_tested": excluded_previously_tested,
        "message": message,
    }

