from __future__ import annotations

import json
import math
import random
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import OPTIMIZATION_RESULTS_DIR
from app.models.optimization_run import OptimizationRun


def normalize_params(params: dict[str, Any]) -> dict[str, Any]:
    """Return a key-order-independent normalization for params signature."""
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


def _safe_float(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            return None
    return None


def _percentile(sorted_values: list[float], p: float) -> float:
    """Compute p-th percentile on a sorted list (p in [0,1])."""
    if not sorted_values:
        raise ValueError("sorted_values must not be empty")
    if p <= 0:
        return float(sorted_values[0])
    if p >= 1:
        return float(sorted_values[-1])
    k = (len(sorted_values) - 1) * p
    f = int(math.floor(k))
    c = int(math.ceil(k))
    if f == c:
        return float(sorted_values[f])
    d = k - f
    return float(sorted_values[f] + (sorted_values[c] - sorted_values[f]) * d)


def score_trial_for_guidance(trial: dict[str, Any]) -> float:
    """Score a trial for guidance.

    MVP: use trial["score"] if available; otherwise fall back to metrics-based heuristics.
    """
    raw_score = trial.get("score")
    if isinstance(raw_score, (int, float)):
        return float(raw_score)

    metrics = trial.get("metrics") or {}
    if not isinstance(metrics, dict):
        return 0.0

    # Prefer profit_factor then net_profit as a robust fallback.
    pf = metrics.get("profit_factor")
    if isinstance(pf, (int, float)):
        return float(pf)

    np_ = metrics.get("net_profit")
    if isinstance(np_, (int, float)):
        return float(np_)

    return 0.0


def collect_relevant_trials(
    db: Session,
    *,
    dataset_id: int,
    strategy_id: int,
    start_date: str | None,
    end_date: str | None,
    objective_metric: str,
    current_search_space: dict[str, list[Any]],
    min_total_trades: int = 0,
    top_n_trials_per_job: int = 200,
    max_source_jobs: int = 30,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Collect successful trials relevant for guided search.

    Filters by:
    - dataset_id, strategy_id
    - start_date/end_date when provided
    - objective_metric (using the objective_metric stored inside result JSON)
    """
    q = db.query(OptimizationRun).filter(
        OptimizationRun.dataset_id == dataset_id,
        OptimizationRun.strategy_id == strategy_id,
        OptimizationRun.status == "success",
    )
    if start_date:
        q = q.filter(OptimizationRun.start_date == start_date)
    if end_date:
        q = q.filter(OptimizationRun.end_date == end_date)

    # Limit IO / payload sizes.
    q = q.order_by(OptimizationRun.created_at.desc()).limit(max_source_jobs)
    source_runs = q.all()

    expected_param_keys = set(current_search_space.keys())
    trials: list[dict[str, Any]] = []

    source_job_count = 0
    source_trial_count = 0
    warnings: list[str] = []

    for run in source_runs:
        if not run.result_path:
            continue

        result_path = Path(run.result_path)
        if not result_path.exists():
            # Backward compatibility: if result_path is missing, try computed path.
            computed = OPTIMIZATION_RESULTS_DIR / f"{run.id}.json"
            if computed.exists():
                result_path = computed
            else:
                continue

        try:
            with result_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:  # noqa: BLE001
            warnings.append(f"Skip a source run due to JSON load error (run_id={run.id}).")
            continue

        stored_objective_metric = data.get("objective_metric") or "net_profit"
        if stored_objective_metric != objective_metric:
            continue

        source_job_count += 1
        run_trials = data.get("trials") or []
        if not isinstance(run_trials, list):
            continue

        # Keep only trials that look compatible with current search_space keys.
        compatible: list[dict[str, Any]] = []
        for t in run_trials:
            p = t.get("params") or {}
            if not isinstance(p, dict):
                continue
            if not expected_param_keys.issubset(set(p.keys())):
                # If keys are very different, it is likely an incompatible job.
                continue

            if min_total_trades > 0:
                metrics = t.get("metrics") or {}
                total_trades = None
                if isinstance(metrics, dict):
                    total_trades = metrics.get("total_trades")
                tf = _safe_float(total_trades)
                if tf is None:
                    continue
                if int(tf) < int(min_total_trades):
                    continue

            compatible.append(t)

        compatible.sort(key=score_trial_for_guidance, reverse=True)
        compatible = compatible[:top_n_trials_per_job]

        trials.extend(compatible)
        source_trial_count += len(compatible)

    meta = {
        "source_job_count": source_job_count,
        "source_trial_count": source_trial_count,
        "warnings": warnings,
    }
    return trials, meta


def summarize_param_distribution(
    *,
    param: str,
    values: list[Any],
    full_candidates: list[Any],
    top_trials_cap: int,
) -> dict[str, Any]:
    """Summarize parameter distribution and derive guided/expanded numeric ranges."""
    # Remove None and keep insertion order stable for categorical.
    vals = [v for v in values if v is not None]
    full = [v for v in full_candidates if v is not None]

    # Boolean handling (bool is a subclass of int; exclude it from numeric).
    bool_vals = [v for v in vals if isinstance(v, bool)]
    if bool_vals and len(bool_vals) == len(vals):
        # Pick most frequent boolean as the guided one.
        guided = []
        expanded = []
        expanded_set = set(bool_vals)
        # Count frequency without pandas.
        counts: dict[bool, int] = {}
        for b in bool_vals:
            counts[b] = counts.get(b, 0) + 1
        guided_val = max(counts.keys(), key=lambda k: counts[k])
        guided.append(guided_val)
        expanded = list(expanded_set) if len(expanded_set) >= 2 else guided.copy()
        return {
            "type": "bool",
            "guided_candidates": guided,
            "expanded_candidates": expanded,
        }

    numeric_vals: list[float] = []
    for v in vals:
        fv = _safe_float(v)
        if fv is not None:
            numeric_vals.append(fv)
        else:
            numeric_vals = []
            break

    if numeric_vals and len(numeric_vals) == len(vals):
        numeric_full = []
        for v in full:
            fv = _safe_float(v)
            if fv is not None:
                numeric_full.append(fv)
        if not numeric_full:
            return {"type": "numeric", "guided_candidates": full[:1], "expanded_candidates": full}

        numeric_full_sorted = sorted(set(numeric_full))
        full_min = float(min(numeric_full_sorted))
        full_max = float(max(numeric_full_sorted))

        sorted_top = sorted(numeric_vals)
        p20 = _percentile(sorted_top, 0.2)
        p80 = _percentile(sorted_top, 0.8)
        width = p80 - p20
        pad = width * 0.5 if width > 0 else (full_max - full_min) * 0.1

        guided_min = float(p20)
        guided_max = float(p80)
        expanded_min = max(full_min, float(p20 - pad))
        expanded_max = min(full_max, float(p80 + pad))

        # Convert numeric ranges back to candidate subsets.
        def in_range(v: Any, lo: float, hi: float) -> bool:
            fv = _safe_float(v)
            if fv is None:
                return False
            return lo <= fv <= hi

        guided_candidates = [v for v in full if in_range(v, guided_min, guided_max)]
        expanded_candidates = [v for v in full if in_range(v, expanded_min, expanded_max)]

        if not guided_candidates:
            # If top trials are too narrow due to discreteness, fall back to nearest available candidates.
            guided_candidates = [full[0]] if full else []
        if not expanded_candidates:
            expanded_candidates = full.copy()

        return {
            "type": "numeric",
            "guided_min": guided_min,
            "guided_max": guided_max,
            "expanded_min": float(expanded_min),
            "expanded_max": float(expanded_max),
            "guided_candidates": guided_candidates,
            "expanded_candidates": expanded_candidates,
        }

    # Categorical handling: pick top-most frequent value(s).
    counts: dict[Any, int] = {}
    for v in vals:
        counts[v] = counts.get(v, 0) + 1

    # Guided: most frequent. Expanded: top-2 (or all if only one unique value).
    sorted_items = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    guided_candidates = [sorted_items[0][0]] if sorted_items else []
    if len(sorted_items) >= 2:
        expanded_candidates = [sorted_items[0][0], sorted_items[1][0]]
    else:
        expanded_candidates = guided_candidates.copy()

    # Ensure these candidates exist in full.
    full_set = set(full)
    guided_candidates = [v for v in guided_candidates if v in full_set] or guided_candidates[:1]
    expanded_candidates = [v for v in expanded_candidates if v in full_set] or expanded_candidates[:1]

    if not guided_candidates:
        guided_candidates = full[:1]
    if not expanded_candidates:
        expanded_candidates = full.copy()

    return {
        "type": "categorical",
        "guided_candidates": guided_candidates,
        "expanded_candidates": expanded_candidates,
    }


def build_guided_search_space(
    *,
    search_space: dict[str, list[Any]],
    relevant_trials: list[dict[str, Any]],
    top_k: int = 50,
    min_source_trials: int = 10,
    sampling_mix_ratio: dict[str, float] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build guided parameter candidates/ranges for guided_random.

    Returns:
    - guided_param_ranges: per-parameter guided/expanded candidate subsets
    - meta: guidance meta (e.g., used_top_trials, min_source_trials_hit)
    """
    if sampling_mix_ratio is None:
        sampling_mix_ratio = {"guided": 0.7, "expanded": 0.2, "full": 0.1}

    if len(relevant_trials) < min_source_trials:
        return {}, {
            "built": False,
            "reason": f"Not enough relevant trials (have={len(relevant_trials)}, need>={min_source_trials}).",
            "sampling_mix_ratio": sampling_mix_ratio,
        }

    trials_sorted = sorted(
        relevant_trials,
        key=score_trial_for_guidance,
        reverse=True,
    )
    top_trials = trials_sorted[:top_k]

    # Build per-param candidate subsets.
    guided_param_ranges: dict[str, Any] = {}
    for param, full_candidates in search_space.items():
        top_values: list[Any] = []
        for t in top_trials:
            p = t.get("params") or {}
            if not isinstance(p, dict):
                continue
            if param not in p:
                continue
            top_values.append(p.get(param))

        if not top_values:
            continue

        dist = summarize_param_distribution(
            param=param,
            values=top_values,
            full_candidates=full_candidates,
            top_trials_cap=top_k,
        )
        guided_param_ranges[param] = dist

    if not guided_param_ranges:
        return {}, {
            "built": False,
            "reason": "Could not build guided ranges for any parameter.",
            "sampling_mix_ratio": sampling_mix_ratio,
        }

    meta = {
        "built": True,
        "used_top_trials": len(top_trials),
        "top_k": top_k,
        "sampling_mix_ratio": sampling_mix_ratio,
    }
    return guided_param_ranges, meta


def _choose_bucket(mix_ratio: dict[str, float]) -> str:
    r = random.random()
    guided_p = float(mix_ratio.get("guided", 0.0))
    expanded_p = float(mix_ratio.get("expanded", 0.0))
    full_p = float(mix_ratio.get("full", 0.0))
    # Normalize just in case.
    s = guided_p + expanded_p + full_p
    if s <= 0:
        return "full"
    guided_p /= s
    expanded_p /= s
    full_p /= s
    if r < guided_p:
        return "guided"
    if r < guided_p + expanded_p:
        return "expanded"
    return "full"


def sample_guided_random_unseen_params(
    *,
    search_space: dict[str, list[Any]],
    guided_param_ranges: dict[str, Any],
    n_trials: int,
    previously_tested: set[str],
    sampling_mix_ratio: dict[str, float],
    max_attempts: int | None = None,
) -> tuple[list[dict[str, Any]], int, int]:
    """Sample unique params from guided/expanded/full candidate subsets (no full enumeration)."""
    if n_trials <= 0:
        return [], 0, 0

    keys = list(search_space.keys())

    full_candidates_by_param = {k: list(search_space[k]) for k in keys}
    guided_candidates_by_param: dict[str, list[Any]] = {}
    expanded_candidates_by_param: dict[str, list[Any]] = {}

    for k in keys:
        dist = guided_param_ranges.get(k) or {}
        guided_candidates_by_param[k] = list(dist.get("guided_candidates") or [])
        expanded_candidates_by_param[k] = list(dist.get("expanded_candidates") or [])

    # Fall back to full candidates per-param when guided subset is empty.
    for k in keys:
        if not guided_candidates_by_param[k]:
            guided_candidates_by_param[k] = full_candidates_by_param[k]
        if not expanded_candidates_by_param[k]:
            expanded_candidates_by_param[k] = full_candidates_by_param[k]

    selected: list[dict[str, Any]] = []
    seen_local: set[str] = set()

    attempts = 0
    if max_attempts is None:
        max_attempts = max(n_trials * 50, 1000)

    while len(selected) < n_trials and attempts < max_attempts:
        attempts += 1
        bucket = _choose_bucket(sampling_mix_ratio)
        params: dict[str, Any] = {}
        for k in keys:
            if bucket == "guided":
                params[k] = random.choice(guided_candidates_by_param[k])
            elif bucket == "expanded":
                params[k] = random.choice(expanded_candidates_by_param[k])
            else:
                params[k] = random.choice(full_candidates_by_param[k])

        sig = params_signature(params)
        if sig in previously_tested or sig in seen_local:
            continue
        seen_local.add(sig)
        selected.append(params)

    return selected, len(selected), attempts

