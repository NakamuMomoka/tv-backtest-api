from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class WalkForwardCreate(BaseModel):
    dataset_id: int
    strategy_id: int
    search_space: dict[str, Any]
    settings: Optional[dict[str, Any]] = Field(default=None)
    objective_metric: Optional[str] = Field(default=None)
    start_date: Optional[str] = Field(default=None, description="開始日 (例: '2023-01-01')")
    end_date: Optional[str] = Field(default=None, description="終了日 (例: '2023-12-31')")
    train_bars: int
    test_bars: int
    step_bars: Optional[int] = Field(default=None)
    min_trades: Optional[int] = Field(default=None)


class WalkForwardRunRead(BaseModel):
    id: int
    dataset_id: int
    strategy_id: int
    search_space_json: Optional[str] = None
    settings_json: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    objective_metric: Optional[str] = None
    train_bars: int
    test_bars: int
    step_bars: int
    status: str
    summary_json: Optional[str] = None
    result_path: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime
    finished_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class WalkForwardResultRead(BaseModel):
    windows: list[dict[str, Any]]
    summary: dict[str, Any]

