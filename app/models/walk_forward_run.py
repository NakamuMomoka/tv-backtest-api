from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer, String, Text, ForeignKey

from app.db.session import Base


class WalkForwardRun(Base):
    __tablename__ = "walk_forward_runs"

    id = Column(Integer, primary_key=True, index=True)
    dataset_id = Column(Integer, ForeignKey("datasets.id"), nullable=False, index=True)
    strategy_id = Column(Integer, ForeignKey("strategies.id"), nullable=False, index=True)
    search_space_json = Column(Text, nullable=True)
    settings_json = Column(Text, nullable=True)
    start_date = Column(String(32), nullable=True)
    end_date = Column(String(32), nullable=True)
    objective_metric = Column(String(64), nullable=True)
    train_bars = Column(Integer, nullable=False)
    test_bars = Column(Integer, nullable=False)
    step_bars = Column(Integer, nullable=False)
    status = Column(String(32), nullable=False, default="running")
    summary_json = Column(Text, nullable=True)
    result_path = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)

