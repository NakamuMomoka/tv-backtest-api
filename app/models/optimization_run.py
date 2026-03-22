from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, Float

from app.db.session import Base


class OptimizationRun(Base):
    __tablename__ = "optimization_runs"

    id = Column(Integer, primary_key=True, index=True)
    dataset_id = Column(Integer, ForeignKey("datasets.id"), nullable=False, index=True)
    strategy_id = Column(
        Integer, ForeignKey("strategies.id"), nullable=False, index=True
    )
    start_date = Column(String(32), nullable=True)
    end_date = Column(String(32), nullable=True)
    search_space_json = Column(Text, nullable=True)
    settings_json = Column(Text, nullable=True)
    objective_metric = Column(String(64), nullable=True)
    # "grid" or "random" (default: grid when None)
    search_mode = Column(String(16), nullable=True)
    # Requested number of trials when search_mode="random"
    n_trials = Column(Integer, nullable=True)
    status = Column(String(32), nullable=False, default="pending")
    best_params_json = Column(Text, nullable=True)
    best_score = Column(Float, nullable=True)
    result_path = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    # Stats for grid / random search
    requested_trials = Column(Integer, nullable=True)
    executed_trials = Column(Integer, nullable=True)
    total_candidate_combinations = Column(Integer, nullable=True)
    excluded_previously_tested = Column(Integer, nullable=True)
    message = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    # random / guided_random のセット分割実行（いずれも None なら従来の単発 n_trials）
    trials_per_set = Column(Integer, nullable=True)
    set_count = Column(Integer, nullable=True)
    total_planned_trials = Column(Integer, nullable=True)
    completed_sets = Column(Integer, nullable=True)
    current_set_index = Column(Integer, nullable=True)
    last_progress_at = Column(DateTime, nullable=True)

