from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from app.db.session import Base


class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id = Column(Integer, primary_key=True, index=True)
    dataset_id = Column(Integer, ForeignKey("datasets.id"), nullable=False, index=True)
    strategy_id = Column(
        Integer, ForeignKey("strategies.id"), nullable=False, index=True
    )
    start_date = Column(String(32), nullable=True)
    end_date = Column(String(32), nullable=True)
    params_json = Column(Text, nullable=True)
    settings_json = Column(Text, nullable=True)
    status = Column(String(32), nullable=False, default="pending")
    metrics_json = Column(Text, nullable=True)
    result_path = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)

