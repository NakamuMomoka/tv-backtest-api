from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

from app.db.session import Base


class TvReferenceRun(Base):
    __tablename__ = "tv_reference_runs"

    id = Column(Integer, primary_key=True, index=True)
    reference_key = Column(String(128), unique=True, nullable=True, index=True)

    name = Column(String(255), nullable=False)
    strategy_id = Column(Integer, nullable=False, index=True)
    dataset_id = Column(Integer, nullable=False, index=True)
    start_date = Column(String(32), nullable=True)
    end_date = Column(String(32), nullable=True)

    params_json = Column(Text, nullable=True)
    summary_json = Column(Text, nullable=True)
    trades_csv_path = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)

    is_builtin = Column(Boolean, nullable=False, default=False)
    source_type = Column(String(32), nullable=False, default="uploaded")

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

