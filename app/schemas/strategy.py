from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class StrategyBase(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    file_path: str
    default_params_json: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    strategy_key: Optional[str] = None
    is_builtin: bool = False
    source_type: str = "uploaded"

    class Config:
        from_attributes = True


class StrategyListItem(StrategyBase):
    pass


class StrategyDetail(StrategyBase):
    pass

