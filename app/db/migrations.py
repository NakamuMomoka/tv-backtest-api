"""SQLite 向けの軽量スキーマ追補（Alembic 未使用時用）。"""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


def ensure_optimization_run_batch_columns(engine: Engine) -> None:
    """optimization_runs にセット分割最適化用カラムを追加（存在時はスキップ）。"""
    insp = inspect(engine)
    if not insp.has_table("optimization_runs"):
        return

    cols = {c["name"] for c in insp.get_columns("optimization_runs")}
    to_add: list[tuple[str, str]] = []
    if "trials_per_set" not in cols:
        to_add.append(("trials_per_set", "INTEGER"))
    if "set_count" not in cols:
        to_add.append(("set_count", "INTEGER"))
    if "total_planned_trials" not in cols:
        to_add.append(("total_planned_trials", "INTEGER"))
    if "completed_sets" not in cols:
        to_add.append(("completed_sets", "INTEGER"))
    if "current_set_index" not in cols:
        to_add.append(("current_set_index", "INTEGER"))
    if "last_progress_at" not in cols:
        to_add.append(("last_progress_at", "DATETIME"))

    if not to_add:
        return

    with engine.begin() as conn:
        for name, typ in to_add:
            conn.execute(text(f"ALTER TABLE optimization_runs ADD COLUMN {name} {typ}"))
