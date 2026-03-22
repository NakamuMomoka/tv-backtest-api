from pathlib import Path
import os


BASE_DIR = Path(__file__).resolve().parent.parent.parent
APP_DIR = BASE_DIR / "app"

# ストレージディレクトリ（CSV・戦略コード・結果保存先）
STORAGE_DIR = BASE_DIR / "storage"
DATASETS_DIR = STORAGE_DIR / "datasets"
STRATEGIES_DIR = STORAGE_DIR / "strategies"
TV_REFERENCES_DIR = STORAGE_DIR / "tv_references"
RESULTS_DIR = STORAGE_DIR / "results"
BACKTEST_RESULTS_DIR = RESULTS_DIR / "backtests"
OPTIMIZATION_RESULTS_DIR = RESULTS_DIR / "optimizations"
WALK_FORWARD_RESULTS_DIR = RESULTS_DIR / "walk_forward"

SQLITE_PATH = BASE_DIR / "tv-backtest-api.db"
SQLALCHEMY_DATABASE_URL = f"sqlite:///{SQLITE_PATH}"

# Optimization search space limits (can be overridden via env)
OPT_SEARCH_SPACE_WARNING_THRESHOLD = int(
    os.getenv("OPT_SEARCH_SPACE_WARNING_THRESHOLD", "5000"),
)
OPT_SEARCH_SPACE_HARD_LIMIT = int(
    os.getenv("OPT_SEARCH_SPACE_HARD_LIMIT", "100000"),
)

# Default fee setting (Bitget futures taker: 0.06% / side)
DEFAULT_FEE_RATE = float(os.getenv("DEFAULT_FEE_RATE", "0.0006"))

DATASETS_DIR.mkdir(parents=True, exist_ok=True)
STRATEGIES_DIR.mkdir(parents=True, exist_ok=True)
TV_REFERENCES_DIR.mkdir(parents=True, exist_ok=True)
BACKTEST_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
OPTIMIZATION_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
WALK_FORWARD_RESULTS_DIR.mkdir(parents=True, exist_ok=True)

