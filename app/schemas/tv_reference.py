from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class TvReferenceBase(BaseModel):
    id: int
    reference_key: Optional[str] = None
    name: str
    strategy_id: int
    dataset_id: int
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    params_json: Optional[str] = None
    summary_json: Optional[str] = None
    trades_csv_path: Optional[str] = None
    notes: Optional[str] = None
    is_builtin: bool = False
    source_type: str = "uploaded"
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TvReferenceListItem(TvReferenceBase):
    pass


class TvReferenceDetail(TvReferenceBase):
    pass

