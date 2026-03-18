from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

from app.db.session import Base


class Dataset(Base):
    __tablename__ = "datasets"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    symbol = Column(String(64), nullable=True)
    timeframe = Column(String(32), nullable=True)
    file_path = Column(Text, nullable=False)
    rows_count = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    dataset_key = Column(String(128), unique=True, nullable=True, index=True)
    is_builtin = Column(Boolean, nullable=False, default=False)
    source_type = Column(String(32), nullable=False, default="uploaded")

