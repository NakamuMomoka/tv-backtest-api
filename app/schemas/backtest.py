from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class BacktestCreate(BaseModel):
    dataset_id: int
    strategy_id: int
    params: Optional[dict[str, Any]] = Field(default=None)
    settings: Optional[dict[str, Any]] = Field(default=None)
    start_date: Optional[str] = Field(default=None, description="開始日 (例: '2023-01-01')")
    end_date: Optional[str] = Field(default=None, description="終了日 (例: '2023-12-31')")


class BacktestRunRead(BaseModel):
    id: int
    dataset_id: int
    strategy_id: int
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    params_json: Optional[str] = None
    settings_json: Optional[str] = None
    status: str
    metrics_json: Optional[str] = None
    result_path: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime
    finished_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class BacktestResultRead(BaseModel):
    metrics: dict[str, Any]
    trades: list[dict[str, Any]]
    equity_series: list[dict[str, Any]]

