from fastapi import FastAPI

from app.api import backtests as backtests_api
from app.api import datasets as datasets_api
from app.api import optimizations as optimizations_api
from app.api import strategies as strategies_api
from app.api import tv_references as tv_references_api
from app.api import walk_forward as walk_forward_api
from app.db.migrations import ensure_optimization_run_batch_columns
from app.db.session import Base, engine
from app.db import base as models_base  # noqa: F401


app = FastAPI(title="TV Backtest API", version="0.1.0")


@app.on_event("startup")
def on_startup() -> None:
    # モデル読み込み済みの Base.metadata から全テーブルを作成
    Base.metadata.create_all(bind=engine)
    ensure_optimization_run_batch_columns(engine)


app.include_router(datasets_api.router)
app.include_router(strategies_api.router)
app.include_router(backtests_api.router)
app.include_router(optimizations_api.router)
app.include_router(walk_forward_api.router)
app.include_router(tv_references_api.router)


@app.get("/health")
def health_check() -> dict:
    return {"status": "ok"}

