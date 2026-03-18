from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class DatasetBase(BaseModel):
    id: int
    name: str
    symbol: Optional[str] = None
    timeframe: Optional[str] = None
    file_path: str
    rows_count: Optional[int] = None
    created_at: datetime
     # builtin 管理用メタデータ
    dataset_key: Optional[str] = None
    is_builtin: bool = False
    source_type: str = "uploaded"

    class Config:
        from_attributes = True


class DatasetListItem(DatasetBase):
    pass


class DatasetDetail(DatasetBase):
    pass

