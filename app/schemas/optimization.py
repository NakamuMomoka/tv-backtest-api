from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class OptimizationCreate(BaseModel):
    dataset_id: int
    strategy_id: int
    # 実際のバリデーションは API レイヤで詳細チェックする
    search_space: dict[str, Any]
    settings: Optional[dict[str, Any]] = Field(default=None)
    objective_metric: Optional[str] = Field(default=None)
    search_mode: Optional[str] = Field(
        default="grid",
        description='"grid", "random", or "guided_random" (default: "grid")',
    )
    n_trials: Optional[int] = Field(
        default=None,
        description="Random / Guided random の単発実行時の試行数（セット分割を使う場合は省略可）",
    )
    trials_per_set: Optional[int] = Field(
        default=None,
        description="セット分割時: 1セットあたりの trial 数（random/guided_random のみ）",
    )
    set_count: Optional[int] = Field(
        default=None,
        description="セット分割時: セット数。合計 trial = trials_per_set * set_count",
    )
    start_date: Optional[str] = Field(default=None, description="開始日 (例: '2023-01-01')")
    end_date: Optional[str] = Field(default=None, description="終了日 (例: '2023-12-31')")


class OptimizationRunRead(BaseModel):
    id: int
    dataset_id: int
    strategy_id: int
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    search_space_json: Optional[str] = None
    settings_json: Optional[str] = None
    objective_metric: Optional[str] = None
    search_mode: Optional[str] = None
    n_trials: Optional[int] = None
    trials_per_set: Optional[int] = None
    set_count: Optional[int] = None
    total_planned_trials: Optional[int] = None
    completed_sets: Optional[int] = None
    current_set_index: Optional[int] = None
    last_progress_at: Optional[datetime] = None
    status: str
    best_params_json: Optional[str] = None
    best_score: Optional[float] = None
    result_path: Optional[str] = None
    error_message: Optional[str] = None
    requested_trials: Optional[int] = None
    executed_trials: Optional[int] = None
    total_candidate_combinations: Optional[int] = None
    excluded_previously_tested: Optional[int] = None
    message: Optional[str] = None
    created_at: datetime
    finished_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class OptimizationResultRead(BaseModel):
    trials: list[dict[str, Any]]
    best_params: dict[str, Any]
    best_score: Optional[float]
    objective_metric: str
    search_mode: Optional[str] = None
    requested_trials: Optional[int] = None
    executed_trials: Optional[int] = None
    total_candidate_combinations: Optional[int] = None
    excluded_previously_tested: Optional[int] = None
    message: Optional[str] = None
    # job timing / metadata for validation & performance checks
    total_trials: Optional[int] = None
    total_duration_sec: Optional[float] = None
    avg_trial_sec: Optional[float] = None
    save_overhead_estimate_sec: Optional[float] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    timing_summary: Optional[dict[str, Any]] = None

    # guided_random metadata (stored for analysis/UX)
    guidance_mode_used: Optional[str] = None
    guidance_source_job_count: Optional[int] = None
    guidance_source_trial_count: Optional[int] = None
    guided_param_ranges: Optional[dict[str, Any]] = None
    sampling_mix_ratio: Optional[dict[str, float]] = None
    fallback_reason: Optional[str] = None

    # セット分割実行メタ（result JSON / 一覧表示用）
    trials_per_set: Optional[int] = None
    set_count: Optional[int] = None
    total_planned_trials: Optional[int] = None
    completed_sets: Optional[int] = None
    current_set_index: Optional[int] = None
    batch_progress: Optional[dict[str, Any]] = None
    stopped_reason: Optional[str] = None
    shortfall_reason: Optional[str] = None
    partial: Optional[bool] = None

