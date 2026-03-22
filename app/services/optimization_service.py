from __future__ import annotations

import itertools
import json
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import time

import pandas as pd
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import DEFAULT_FEE_RATE, OPTIMIZATION_RESULTS_DIR
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
from app.services.optimization_guidance import (
    build_guided_search_space,
    collect_relevant_trials,
    sample_guided_random_unseen_params,
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


def _total_combinations(search_space: dict[str, list[Any]]) -> int:
    total = 1
    for values in search_space.values():
        total *= max(len(values), 1)
    return int(total)


def _sample_random_unseen_params(
    *,
    search_space: dict[str, list[Any]],
    n_trials: int,
    previously_tested: set[str],
) -> tuple[list[dict[str, Any]], int]:
    """Sample unique random params without full enumeration."""
    if n_trials <= 0:
        return [], 0

    keys = list(search_space.keys())
    if not keys:
        return ([{}] if n_trials > 0 and "{}" not in previously_tested else []), 0

    selected: list[dict[str, Any]] = []
    seen_local: set[str] = set()
    attempts = 0
    max_attempts = max(n_trials * 50, 1000)

    while len(selected) < n_trials and attempts < max_attempts:
        attempts += 1
        params = {k: random.choice(search_space[k]) for k in keys}
        sig = params_signature(params)
        if sig in seen_local or sig in previously_tested:
            continue
        seen_local.add(sig)
        selected.append(params)

    return selected, attempts


def _build_timing_summary_from_trial_list(trials: list[dict[str, Any]]) -> dict[str, Any] | None:
    """trials[].timings から timing_summary を構築。"""
    timing_items = [
        (t.get("timings") if isinstance(t, dict) else None) for t in trials
    ]
    timing_items = [t for t in timing_items if isinstance(t, dict)]
    if not timing_items:

        return None

    def _avg_sum(key: str) -> tuple[float, float]:
        vals = [float(x.get(key) or 0.0) for x in timing_items]
        return float(sum(vals) / len(vals)) if vals else 0.0, float(sum(vals)) if vals else 0.0

    avg_strategy_exec_sec, sum_strategy_exec_sec = _avg_sum("strategy_exec_sec")
    avg_result_extract_sec, sum_result_extract_sec = _avg_sum("result_extract_sec")
    avg_jsonable_sec, sum_jsonable_sec = _avg_sum("jsonable_sec")
    avg_db_update_sec, sum_db_update_sec = _avg_sum("db_update_sec")
    avg_trial_total_sec, sum_trial_total_sec = _avg_sum("trial_total_sec")

    return {
        "count": len(timing_items),
        "avg_strategy_exec_sec": avg_strategy_exec_sec,
        "sum_strategy_exec_sec": sum_strategy_exec_sec,
        "avg_result_extract_sec": avg_result_extract_sec,
        "sum_result_extract_sec": sum_result_extract_sec,
        "avg_jsonable_sec": avg_jsonable_sec,
        "sum_jsonable_sec": sum_jsonable_sec,
        "avg_db_update_sec": avg_db_update_sec,
        "sum_db_update_sec": sum_db_update_sec,
        "avg_trial_total_sec": avg_trial_total_sec,
        "sum_trial_total_sec": sum_trial_total_sec,
    }


def _write_partial_optimization_result(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(to_jsonable(payload), f, ensure_ascii=False, indent=2)


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
    trials_per_set: int | None = None,
    set_count: int | None = None,
) -> OptimizationRun:
    # Ensure dataset/strategy exist up front for fast failure.
    _get_dataset_or_404(db, dataset_id)
    _get_strategy_or_404(db, strategy_id)

    settings_used = dict(settings or {})
    settings_used["fee_rate"] = float(settings_used.get("fee_rate", DEFAULT_FEE_RATE))

    search_space_json = json.dumps(to_jsonable(search_space or {}))
    settings_json = json.dumps(to_jsonable(settings_used))

    total_planned: int | None = None
    tps_i: int | None = None
    sc_i: int | None = None
    if trials_per_set is not None and set_count is not None:
        if trials_per_set > 0 and set_count > 0:
            tps_i = int(trials_per_set)
            sc_i = int(set_count)
            total_planned = tps_i * sc_i

    n_trials_stored = int(total_planned) if total_planned is not None else n_trials

    run = OptimizationRun(
        dataset_id=dataset_id,
        strategy_id=strategy_id,
        start_date=start_date,
        end_date=end_date,
        search_space_json=search_space_json,
        settings_json=settings_json,
        objective_metric=objective_metric,
        search_mode=search_mode,
        n_trials=n_trials_stored,
        trials_per_set=tps_i,
        set_count=sc_i,
        total_planned_trials=total_planned,
        completed_sets=0 if total_planned is not None else None,
        current_set_index=0 if total_planned is not None else None,
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

        # NOTE:
        # - grid: 全列挙（API側でハード上限チェック済み）
        # - random: 全列挙せず、必要 trial 数だけサンプリングする
        total_candidate_combinations = _total_combinations(search_space)

        # Collect previously tested signatures (same dataset/strategy/start/end/objective_metric)
        previously_tested: set[str] = set()
        if search_mode in ("random", "guided_random"):
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

        # guided_random metadata (stored into result JSON + OptimizationRun.message)
        guidance_mode_used: str | None = None
        guidance_source_job_count: int | None = None
        guidance_source_trial_count: int | None = None
        sampling_mix_ratio: dict[str, float] | None = None
        fallback_reason: str | None = None

        objective_key = objective_metric or "net_profit"
        guidance_build_meta: dict[str, Any] = {}
        guided_param_ranges: dict[str, Any] | None = None

        use_batch = (
            search_mode in ("random", "guided_random")
            and getattr(run, "trials_per_set", None) is not None
            and getattr(run, "set_count", None) is not None
            and int(run.trials_per_set or 0) > 0
            and int(run.set_count or 0) > 0
        )
        attempts = 0

        if search_mode == "grid":
            all_params_list = list(_iter_param_combinations(search_space))
            selected_params_list = all_params_list
            requested_trials = len(all_params_list)
            executed_trials = len(all_params_list)
        elif search_mode == "random":
            if use_batch:
                tps = int(run.trials_per_set or 0)
                sc = int(run.set_count or 0)
                requested_trials = tps * sc
                n_trials = requested_trials
                selected_params_list = []
                excluded_previously_tested = len(previously_tested)
                executed_trials = 0
                guidance_mode_used = "random"
                message = (
                    f"batch_random: trials_per_set={tps}, set_count={sc}, total_planned={requested_trials}"
                )
            else:
                n_trials = run.n_trials or 0
                requested_trials = n_trials

                sampled, attempts = _sample_random_unseen_params(
                    search_space=search_space,
                    n_trials=n_trials,
                    previously_tested=previously_tested,
                )
                selected_params_list = sampled
                excluded_previously_tested = len(previously_tested)

                executed_trials = len(selected_params_list)

                if executed_trials == 0:
                    message = "No unseen candidates remaining."
                elif executed_trials < n_trials:
                    message = (
                        "Could not sample enough unique unseen candidates within attempt budget. "
                        f"requested={n_trials}, executed={executed_trials}, attempts={attempts}."
                    )
                else:
                    message = None

                guidance_mode_used = "random"

        elif search_mode == "guided_random":
            if use_batch:
                tps = int(run.trials_per_set or 0)
                sc = int(run.set_count or 0)
                requested_trials = tps * sc
                n_trials = requested_trials
            else:
                n_trials = run.n_trials or 0
                requested_trials = n_trials

            relevant_trials, guidance_source_meta = collect_relevant_trials(
                db,
                dataset_id=run.dataset_id,
                strategy_id=run.strategy_id,
                start_date=run.start_date,
                end_date=run.end_date,
                objective_metric=objective_key,
                current_search_space=search_space,
                min_total_trades=0,
            )

            guidance_source_job_count = int(guidance_source_meta.get("source_job_count") or 0)
            guidance_source_trial_count = int(guidance_source_meta.get("source_trial_count") or 0)

            guided_param_ranges, guidance_build_meta = build_guided_search_space(
                search_space=search_space,
                relevant_trials=relevant_trials,
            )

            sampling_mix_ratio = guidance_build_meta.get("sampling_mix_ratio") or None

            if guidance_build_meta.get("built"):
                guidance_mode_used = "guided_random"
                fallback_reason = None
                if not use_batch:
                    selected_params_list, executed_trials, attempts = sample_guided_random_unseen_params(
                        search_space=search_space,
                        guided_param_ranges=guided_param_ranges,
                        n_trials=n_trials,
                        previously_tested=previously_tested,
                        sampling_mix_ratio=sampling_mix_ratio or {"guided": 0.7, "expanded": 0.2, "full": 0.1},
                    )
                else:
                    selected_params_list = []
                    executed_trials = 0
            else:
                guidance_mode_used = "fallback_random"
                fallback_reason = str(guidance_build_meta.get("reason") or "Unknown fallback reason.")
                if not use_batch:
                    selected_params_list, _attempts = _sample_random_unseen_params(
                        search_space=search_space,
                        n_trials=n_trials,
                        previously_tested=previously_tested,
                    )
                    executed_trials = len(selected_params_list)
                    attempts = int(_attempts)
                else:
                    selected_params_list = []
                    executed_trials = 0

            excluded_previously_tested = len(previously_tested)

            guidance_summary = (
                f"guided_random(source_jobs={guidance_source_job_count}, "
                f"source_trials={guidance_source_trial_count}, used_mode={guidance_mode_used}"
            )
            if fallback_reason:
                guidance_summary += f", fallback_reason={fallback_reason}"
            guidance_summary += ")"

            if use_batch:
                message = (
                    f"{guidance_summary} batch: trials_per_set={tps}, set_count={sc}, "
                    f"total_planned={requested_trials}"
                )
            elif executed_trials == 0:
                message = f"{guidance_summary}. No unseen candidates remaining."
            elif executed_trials < n_trials:
                message = (
                    f"{guidance_summary}. Could not sample enough unique unseen candidates within attempt budget. "
                    f"requested={n_trials}, executed={executed_trials}, attempts={attempts}."
                )
            else:
                message = guidance_summary

        else:
            raise RuntimeError(f"Unsupported search_mode: {search_mode}")

        skip_standard_loop = bool(
            use_batch and search_mode in ("random", "guided_random"),
        )

        trials: list[dict[str, Any]] = []
        best_params: dict[str, Any] = {}
        best_score: float | None = None
        any_success = False

        started_ts = _utcnow()
        started_monotonic = time.perf_counter()
        per_trial_durations: list[float] = []

        # DB への進捗反映は 10 trial ごとにバッチ更新する
        progress_interval = 10
        trials_completed = 0

        # optimization 用に軽量モードフラグを settings に埋め込む（戦略側で参照可）
        opt_settings = dict(settings or {})
        opt_settings["optimization_mode"] = True
        # AssistPass 用: job 単位の前処理キャッシュを settings 経由で共有する
        try:
            from pathlib import Path as _Path  # 局所 import で循環を避ける

            strategy_path = _Path(strategy.file_path or "")
            if strategy_path.name == "assistpass.py":
                opt_settings.setdefault("_assistpass_cache", {})
        except Exception:
            # file_path が無い/不正な場合はキャッシュ無しで続行
            pass

        core_metric_keys = [
            "net_profit",
            "total_trades",
            "win_rate",
            "gross_profit",
            "gross_loss",
            "profit_factor",
        ]

        def _run_one_trial(params: dict[str, Any]) -> None:
            nonlocal best_score, best_params, any_success, trials_completed
            trial: dict[str, Any] = {"params": params}
            strategy_exec_sec = 0.0
            result_extract_sec = 0.0
            jsonable_sec = 0.0
            db_update_sec = 0.0
            trial_total_sec = 0.0
            t_trial_start = time.perf_counter()
            try:
                t0 = time.perf_counter()
                result = run_strategy_backtest_on_bars(
                    bars=bars,
                    strategy=strategy,
                    params=params,
                    settings=opt_settings,
                )
                t1 = time.perf_counter()
                strategy_exec_sec = t1 - t0
                per_trial_durations.append(strategy_exec_sec)

                t_extract_start = time.perf_counter()
                t_json_start = time.perf_counter()
                metrics = result.get("metrics") or {}
                if not isinstance(metrics, dict):
                    metrics = {}
                metrics = to_jsonable(metrics)
                t_json_end = time.perf_counter()
                jsonable_sec = t_json_end - t_json_start

                trial_metrics = {k: metrics.get(k) for k in core_metric_keys}
                trial["metrics"] = trial_metrics
                score = _score_from_metrics(metrics, objective_metric)
                trial["score"] = score
                any_success = True

                t_extract_end = time.perf_counter()
                result_extract_sec = max(0.0, (t_extract_end - t_extract_start) - jsonable_sec)

                if best_score is None or score > best_score:
                    best_score = score
                    best_params = params
            except StrategyExecutionError as exc:
                trial["error_message"] = str(exc)
                strategy_exec_sec = time.perf_counter() - t0
            except Exception as exc:  # noqa: BLE001
                trial["error_message"] = f"Unexpected error: {exc}"
                strategy_exec_sec = time.perf_counter() - t0

            trial_total_sec = time.perf_counter() - t_trial_start

            trials.append(trial)

            trials_completed += 1
            if trials_completed % progress_interval == 0:
                t_db_start = time.perf_counter()
                run.executed_trials = trials_completed
                run.best_score = best_score
                run.best_params_json = json.dumps(to_jsonable(best_params or {}))
                db.add(run)
                db.commit()
                db_update_sec = time.perf_counter() - t_db_start
                trial_total_sec = time.perf_counter() - t_trial_start

            trial["timings"] = {
                "strategy_exec_sec": strategy_exec_sec,
                "result_extract_sec": result_extract_sec,
                "jsonable_sec": jsonable_sec,
                "db_update_sec": db_update_sec,
                "trial_total_sec": trial_total_sec,
            }

        stopped_reason: str | None = None
        shortfall_reason: str | None = None
        set_durations_sec: list[float] = []

        if skip_standard_loop:
            seen_job: set[str] = set(previously_tested)
            tps = int(run.trials_per_set or 0)
            sc = int(run.set_count or 0)
            result_path_partial = OPTIMIZATION_RESULTS_DIR / f"{run.id}.json"
            run.result_path = str(result_path_partial)
            db.add(run)
            db.commit()

            for set_idx in range(sc):
                run.current_set_index = set_idx
                run.completed_sets = set_idx
                run.last_progress_at = _utcnow()
                db.add(run)
                db.commit()
                db.refresh(run)

                samp_attempts = 0
                if search_mode == "random":
                    sampled, samp_attempts = _sample_random_unseen_params(
                        search_space=search_space,
                        n_trials=tps,
                        previously_tested=seen_job,
                    )
                elif search_mode == "guided_random":
                    if guidance_build_meta.get("built"):
                        sampled, _ex, samp_attempts = sample_guided_random_unseen_params(
                            search_space=search_space,
                            guided_param_ranges=guided_param_ranges or {},
                            n_trials=tps,
                            previously_tested=seen_job,
                            sampling_mix_ratio=sampling_mix_ratio
                            or {"guided": 0.7, "expanded": 0.2, "full": 0.1},
                        )
                    else:
                        sampled, samp_attempts = _sample_random_unseen_params(
                            search_space=search_space,
                            n_trials=tps,
                            previously_tested=seen_job,
                        )
                else:
                    sampled = []

                if not sampled:
                    stopped_reason = "exhausted_candidates"
                    shortfall_reason = f"No unseen candidates at set {set_idx + 1}/{sc}."
                    break

                set_t0 = time.perf_counter()
                for params in sampled:
                    _run_one_trial(params)
                    seen_job.add(params_signature(params))
                set_durations_sec.append(float(time.perf_counter() - set_t0))

                run.completed_sets = set_idx + 1
                run.executed_trials = len(trials)
                run.best_score = best_score
                run.best_params_json = json.dumps(to_jsonable(best_params or {}))
                run.last_progress_at = _utcnow()
                prog_msg = (
                    f"[batch] set {set_idx + 1}/{sc} done, trials={len(trials)}/{tps * sc}, "
                    f"best_score={best_score}"
                )
                run.message = (f"{message} | " if message else "") + prog_msg
                db.add(run)
                db.commit()

                timing_summary_partial = _build_timing_summary_from_trial_list(trials)
                avg_set_dur = (
                    float(sum(set_durations_sec) / len(set_durations_sec))
                    if set_durations_sec
                    else 0.0
                )
                partial_payload = to_jsonable(
                    {
                        "trials": trials,
                        "best_params": best_params,
                        "best_score": best_score,
                        "objective_metric": objective_key,
                        "start_date": run.start_date,
                        "end_date": run.end_date,
                        "search_mode": search_mode,
                        "requested_trials": tps * sc,
                        "executed_trials": len(trials),
                        "total_trials": len(trials),
                        "total_candidate_combinations": total_candidate_combinations,
                        "excluded_previously_tested": excluded_previously_tested,
                        "message": run.message,
                        "guidance_mode_used": guidance_mode_used,
                        "guidance_source_job_count": guidance_source_job_count,
                        "guidance_source_trial_count": guidance_source_trial_count,
                        "guided_param_ranges": guided_param_ranges,
                        "sampling_mix_ratio": sampling_mix_ratio,
                        "fallback_reason": fallback_reason,
                        "started_at": started_ts.isoformat(),
                        "finished_at": None,
                        "partial": True,
                        "timing_summary": timing_summary_partial,
                        "batch_progress": {
                            "trials_per_set": tps,
                            "set_count": sc,
                            "total_planned_trials": tps * sc,
                            "completed_sets": set_idx + 1,
                            "current_set_index": set_idx + 1,
                            "executed_trials": len(trials),
                            "set_durations_sec": list(set_durations_sec),
                            "avg_set_duration_sec": avg_set_dur,
                            "stopped_reason": stopped_reason,
                            "shortfall_reason": shortfall_reason,
                        },
                    },
                )
                _write_partial_optimization_result(result_path_partial, partial_payload)

            if not stopped_reason:
                run.completed_sets = sc
                run.current_set_index = sc
            run.last_progress_at = _utcnow()
            db.add(run)
            db.commit()

        if not skip_standard_loop:
            for params in selected_params_list:
                _run_one_trial(params)

        executed_trials = len(trials)

        # trial 内訳の集計（100 trial 後に平均・合計を出す）
        timing_items = [
            (t.get("timings") if isinstance(t, dict) else None) for t in trials
        ]
        timing_items = [t for t in timing_items if isinstance(t, dict)]

        def _avg_sum(key: str) -> tuple[float, float]:
            vals = [float(x.get(key) or 0.0) for x in timing_items]
            return float(sum(vals) / len(vals)) if vals else 0.0, float(sum(vals)) if vals else 0.0

        timing_summary = None
        if timing_items:
            avg_strategy_exec_sec, sum_strategy_exec_sec = _avg_sum(
                "strategy_exec_sec"
            )
            avg_result_extract_sec, sum_result_extract_sec = _avg_sum(
                "result_extract_sec"
            )
            avg_jsonable_sec, sum_jsonable_sec = _avg_sum("jsonable_sec")
            avg_db_update_sec, sum_db_update_sec = _avg_sum("db_update_sec")
            avg_trial_total_sec, sum_trial_total_sec = _avg_sum("trial_total_sec")

            timing_summary = {
                "count": len(timing_items),
                "avg_strategy_exec_sec": avg_strategy_exec_sec,
                "sum_strategy_exec_sec": sum_strategy_exec_sec,
                "avg_result_extract_sec": avg_result_extract_sec,
                "sum_result_extract_sec": sum_result_extract_sec,
                "avg_jsonable_sec": avg_jsonable_sec,
                "sum_jsonable_sec": sum_jsonable_sec,
                "avg_db_update_sec": avg_db_update_sec,
                "sum_db_update_sec": sum_db_update_sec,
                "avg_trial_total_sec": avg_trial_total_sec,
                "sum_trial_total_sec": sum_trial_total_sec,
            }

        total_duration_sec = float(time.perf_counter() - started_monotonic)

        if skip_standard_loop and set_durations_sec:
            if timing_summary is None:
                timing_summary = {}
            else:
                timing_summary = dict(timing_summary)
            timing_summary["total_duration_sec"] = total_duration_sec
            timing_summary["avg_set_duration_sec"] = float(
                sum(set_durations_sec) / max(len(set_durations_sec), 1),
            )
            timing_summary["completed_sets"] = int(run.completed_sets or 0)

        avg_trial_sec = (
            float(total_duration_sec / executed_trials) if executed_trials and executed_trials > 0 else None
        )
        sum_trial_runtime_sec = float(sum(per_trial_durations)) if per_trial_durations else 0.0
        save_overhead_estimate_sec = float(
            max(0.0, total_duration_sec - sum_trial_runtime_sec)
        )

        # started_at / finished_at は結果 JSON と DB(message) の両方で追えるようにする
        finished_ts = _utcnow()

        final_message_text = run.message if skip_standard_loop and run.message else message
        if skip_standard_loop and stopped_reason:
            final_message_text = (
                f"{final_message_text or ''} | stopped_reason={stopped_reason}"
                f"{', ' + shortfall_reason if shortfall_reason else ''}"
            )

        batch_progress_final: dict[str, Any] | None = None
        if skip_standard_loop:
            tps_f = int(run.trials_per_set or 0)
            sc_f = int(run.set_count or 0)
            batch_progress_final = {
                "trials_per_set": tps_f,
                "set_count": sc_f,
                "total_planned_trials": tps_f * sc_f,
                "completed_sets": int(run.completed_sets or 0),
                "current_set_index": int(run.current_set_index or 0),
                "executed_trials": executed_trials,
                "set_durations_sec": list(set_durations_sec),
                "avg_set_duration_sec": (
                    float(sum(set_durations_sec) / len(set_durations_sec))
                    if set_durations_sec
                    else None
                ),
                "stopped_reason": stopped_reason,
                "shortfall_reason": shortfall_reason,
            }

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
                "total_trials": executed_trials,
                "total_candidate_combinations": total_candidate_combinations,
                "excluded_previously_tested": excluded_previously_tested,
                "message": final_message_text,
                "guidance_mode_used": guidance_mode_used,
                "guidance_source_job_count": guidance_source_job_count,
                "guidance_source_trial_count": guidance_source_trial_count,
                "guided_param_ranges": guided_param_ranges,
                "sampling_mix_ratio": sampling_mix_ratio,
                "fallback_reason": fallback_reason,
                "total_duration_sec": total_duration_sec,
                "avg_trial_sec": avg_trial_sec,
                "started_at": started_ts.isoformat(),
                "finished_at": finished_ts.isoformat(),
                "save_overhead_estimate_sec": save_overhead_estimate_sec,
                "timing_summary": timing_summary,
                "partial": False,
                "stopped_reason": stopped_reason,
                "shortfall_reason": shortfall_reason,
                "batch_progress": batch_progress_final,
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

        run.finished_at = finished_ts
        run.requested_trials = requested_trials
        run.executed_trials = executed_trials
        run.total_candidate_combinations = total_candidate_combinations
        run.excluded_previously_tested = excluded_previously_tested
        # ログ用メッセージに計測情報も含める
        timing_note = ""
        if avg_trial_sec is not None:
            timing_note = (
                f" total_duration_sec={total_duration_sec:.3f}, avg_trial_sec={avg_trial_sec:.4f}"
                f", save_overhead_estimate_sec={save_overhead_estimate_sec:.3f}"
            )
        if timing_summary and "avg_strategy_exec_sec" in timing_summary:
            timing_note += (
                f", avg_strategy_exec_sec={timing_summary['avg_strategy_exec_sec']:.4f}"
                f", avg_result_extract_sec={timing_summary['avg_result_extract_sec']:.4f}"
                f", avg_jsonable_sec={timing_summary['avg_jsonable_sec']:.4f}"
                f", avg_db_update_sec={timing_summary['avg_db_update_sec']:.4f}"
            )
        base_run_msg = run.message if skip_standard_loop and run.message else message
        if base_run_msg:
            run.message = f"{base_run_msg}{timing_note}"
        else:
            run.message = timing_note.strip() or None

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
    total_trials = data.get("total_trials")
    total_duration_sec = data.get("total_duration_sec")
    avg_trial_sec = data.get("avg_trial_sec")
    save_overhead_estimate_sec = data.get("save_overhead_estimate_sec")
    started_at = data.get("started_at")
    finished_at = data.get("finished_at")
    timing_summary = data.get("timing_summary")
    guidance_mode_used = data.get("guidance_mode_used")
    guidance_source_job_count = data.get("guidance_source_job_count")
    guidance_source_trial_count = data.get("guidance_source_trial_count")
    guided_param_ranges = data.get("guided_param_ranges")
    sampling_mix_ratio = data.get("sampling_mix_ratio")
    fallback_reason = data.get("fallback_reason")
    partial = data.get("partial")
    batch_progress = data.get("batch_progress")
    stopped_reason = data.get("stopped_reason")
    shortfall_reason = data.get("shortfall_reason")
    trials_per_set_r = data.get("trials_per_set")
    set_count_r = data.get("set_count")
    total_planned_trials_r = data.get("total_planned_trials")
    completed_sets_r = data.get("completed_sets")
    current_set_index_r = data.get("current_set_index")
    if isinstance(batch_progress, dict):
        trials_per_set_r = trials_per_set_r or batch_progress.get("trials_per_set")
        set_count_r = set_count_r or batch_progress.get("set_count")
        total_planned_trials_r = total_planned_trials_r or batch_progress.get("total_planned_trials")
        completed_sets_r = completed_sets_r or batch_progress.get("completed_sets")
        current_set_index_r = current_set_index_r or batch_progress.get("current_set_index")

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
        "total_trials": total_trials,
        "total_duration_sec": total_duration_sec,
        "avg_trial_sec": avg_trial_sec,
        "save_overhead_estimate_sec": save_overhead_estimate_sec,
        "started_at": started_at,
        "finished_at": finished_at,
        "timing_summary": timing_summary,
        "guidance_mode_used": guidance_mode_used,
        "guidance_source_job_count": guidance_source_job_count,
        "guidance_source_trial_count": guidance_source_trial_count,
        "guided_param_ranges": guided_param_ranges,
        "sampling_mix_ratio": sampling_mix_ratio,
        "fallback_reason": fallback_reason,
        "partial": partial,
        "batch_progress": batch_progress,
        "stopped_reason": stopped_reason,
        "shortfall_reason": shortfall_reason,
        "trials_per_set": trials_per_set_r,
        "set_count": set_count_r,
        "total_planned_trials": total_planned_trials_r,
        "completed_sets": completed_sets_r,
        "current_set_index": current_set_index_r,
    }

