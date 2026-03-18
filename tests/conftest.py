from __future__ import annotations

from pathlib import Path
from typing import Generator

import pytest
from fastapi.testclient import TestClient

from app.core import config as app_config
from app.main import app


@pytest.fixture(scope="session")
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def override_storage_dirs(tmp_path, monkeypatch) -> None:
    """一時ディレクトリにストレージを切り替える。"""
    storage_root = tmp_path / "storage"
    datasets_dir = storage_root / "datasets"
    strategies_dir = storage_root / "strategies"
    results_dir = storage_root / "results"
    backtests_dir = results_dir / "backtests"
    optimizations_dir = results_dir / "optimizations"

    for d in (
        datasets_dir,
        strategies_dir,
        backtests_dir,
        optimizations_dir,
    ):
        d.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(app_config, "STORAGE_DIR", storage_root)
    monkeypatch.setattr(app_config, "DATASETS_DIR", datasets_dir)
    monkeypatch.setattr(app_config, "STRATEGIES_DIR", strategies_dir)
    monkeypatch.setattr(app_config, "RESULTS_DIR", results_dir)
    monkeypatch.setattr(app_config, "BACKTEST_RESULTS_DIR", backtests_dir)
    monkeypatch.setattr(app_config, "OPTIMIZATION_RESULTS_DIR", optimizations_dir)

