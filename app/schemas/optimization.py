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
        description='"grid" or "random" (default: "grid")',
    )
    n_trials: Optional[int] = Field(
        default=None,
        description="Random search の試行数（search_mode='random' のとき必須）",
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

