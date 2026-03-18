from __future__ import annotations

import io
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import BASE_DIR


def test_health_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_dataset_upload_success(client: TestClient, tmp_path) -> None:
    csv_path = tmp_path / "sample.csv"
    csv_path.write_text("timestamp,close\n2020-01-01,100\n2020-01-02,101\n", encoding="utf-8")

    with csv_path.open("rb") as f:
        files = {"file": ("sample.csv", f, "text/csv")}
        data = {
            "name": "test-dataset",
            "symbol": "TEST",
            "timeframe": "1d",
        }
        response = client.post("/datasets", data=data, files=files)

    assert response.status_code == 200
    body = response.json()
    assert body["id"] > 0
    assert body["rows_count"] == 2


def test_strategy_upload_success(client: TestClient) -> None:
    strategy_file = BASE_DIR / "examples" / "sample_strategy_ma_cross.py"
    assert strategy_file.exists()

    with strategy_file.open("rb") as f:
        files = {"file": (strategy_file.name, f, "text/x-python")}
        data = {
            "name": "ma-cross",
            "description": "test strategy",
            "default_params_json": '{"fast_window": 5, "slow_window": 20}',
        }
        response = client.post("/strategies", data=data, files=files)

    assert response.status_code == 200
    body = response.json()
    assert body["id"] > 0
    assert body["name"] == "ma-cross"


def _create_dataset(client: TestClient) -> int:
    csv_bytes = io.BytesIO(b"timestamp,close\n2020-01-01,100\n2020-01-02,101\n2020-01-03,102\n")
    files = {"file": ("sample.csv", csv_bytes, "text/csv")}
    data = {"name": "bt-dataset", "symbol": "BT", "timeframe": "1d"}
    response = client.post("/datasets", data=data, files=files)
    assert response.status_code == 200
    return response.json()["id"]


def _create_strategy(client: TestClient) -> int:
    strategy_file = BASE_DIR / "examples" / "sample_strategy_ma_cross.py"
    with strategy_file.open("rb") as f:
        files = {"file": (strategy_file.name, f, "text/x-python")}
        data = {"name": "bt-strategy", "description": "for backtest"}
        response = client.post("/strategies", data=data, files=files)
    assert response.status_code == 200
    return response.json()["id"]


def test_backtest_success(client: TestClient) -> None:
    dataset_id = _create_dataset(client)
    strategy_id = _create_strategy(client)

    payload = {
        "dataset_id": dataset_id,
        "strategy_id": strategy_id,
        "params": {"fast_window": 1, "slow_window": 2},
        "settings": {"initial_capital": 1000000},
    }
    response = client.post("/backtests", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["id"] > 0


def test_optimization_success(client: TestClient) -> None:
    dataset_id = _create_dataset(client)
    strategy_id = _create_strategy(client)

    payload = {
        "dataset_id": dataset_id,
        "strategy_id": strategy_id,
        "search_space": {
            "fast_window": [1, 2],
            "slow_window": [3, 4],
        },
        "settings": {"initial_capital": 1000000},
        "objective_metric": "net_profit",
    }
    response = client.post("/optimizations", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["id"] > 0


def test_search_space_empty_list_400(client: TestClient) -> None:
    dataset_id = _create_dataset(client)
    strategy_id = _create_strategy(client)

    payload = {
        "dataset_id": dataset_id,
        "strategy_id": strategy_id,
        "search_space": {
            "fast_window": [],
        },
        "settings": {"initial_capital": 1000000},
        "objective_metric": "net_profit",
    }
    response = client.post("/optimizations", json=payload)
    assert response.status_code == 400
    assert "must not be an empty list" in response.json()["detail"]


def test_search_space_too_many_combinations_400(client: TestClient) -> None:
    dataset_id = _create_dataset(client)
    strategy_id = _create_strategy(client)

    # 1001 combinations (e.g. 1 param with 1001 candidates)
    big_list = list(range(1001))
    payload = {
        "dataset_id": dataset_id,
        "strategy_id": strategy_id,
        "search_space": {
            "fast_window": big_list,
        },
        "settings": {"initial_capital": 1000000},
        "objective_metric": "net_profit",
    }
    response = client.post("/optimizations", json=payload)
    assert response.status_code == 400
    assert "exceeds the maximum of 1000" in response.json()["detail"]


def test_backtest_result_fetch_success(client: TestClient) -> None:
    dataset_id = _create_dataset(client)
    strategy_id = _create_strategy(client)

    payload = {
        "dataset_id": dataset_id,
        "strategy_id": strategy_id,
        "params": {"fast_window": 1, "slow_window": 2},
        "settings": {"initial_capital": 1000000},
    }
    run_resp = client.post("/backtests", json=payload)
    assert run_resp.status_code == 200
    run_id = run_resp.json()["id"]

    res_resp = client.get(f"/backtests/{run_id}/result")
    assert res_resp.status_code == 200
    body = res_resp.json()
    assert "metrics" in body
    assert "trades" in body
    assert "equity_series" in body


def test_optimization_result_fetch_success(client: TestClient) -> None:
    dataset_id = _create_dataset(client)
    strategy_id = _create_strategy(client)

    payload = {
        "dataset_id": dataset_id,
        "strategy_id": strategy_id,
        "search_space": {
            "fast_window": [1, 2],
            "slow_window": [3, 4],
        },
        "settings": {"initial_capital": 1000000},
        "objective_metric": "net_profit",
    }
    run_resp = client.post("/optimizations", json=payload)
    assert run_resp.status_code == 200
    run_id = run_resp.json()["id"]

    res_resp = client.get(f"/optimizations/{run_id}/result")
    assert res_resp.status_code == 200
    body = res_resp.json()
    assert "trials" in body
    assert "best_params" in body
    assert "best_score" in body
    assert "objective_metric" in body


def test_optimization_list_api_with_filters(client: TestClient) -> None:
    # create one grid and one random optimization
    dataset_id = _create_dataset(client)
    strategy_id = _create_strategy(client)

    grid_payload = {
        "dataset_id": dataset_id,
        "strategy_id": strategy_id,
        "search_space": {
            "fast_window": [1, 2],
            "slow_window": [3, 4],
        },
        "settings": {"initial_capital": 1000000},
        "objective_metric": "net_profit",
        "search_mode": "grid",
    }
    resp1 = client.post("/optimizations", json=grid_payload)
    assert resp1.status_code == 200

    random_payload = {
        "dataset_id": dataset_id,
        "strategy_id": strategy_id,
        "search_space": {
            "fast_window": [1, 2],
            "slow_window": [3, 4],
        },
        "settings": {"initial_capital": 1000000},
        "objective_metric": "net_profit",
        "search_mode": "random",
        "n_trials": 2,
    }
    resp2 = client.post("/optimizations", json=random_payload)
    assert resp2.status_code == 200

    # list all
    list_resp = client.get("/optimizations")
    assert list_resp.status_code == 200
    runs = list_resp.json()
    assert isinstance(runs, list)
    assert len(runs) >= 2

    # filter by search_mode
    list_random = client.get("/optimizations", params={"search_mode": "random"})
    assert list_random.status_code == 200
    for r in list_random.json():
        assert r.get("search_mode") == "random"

    # apply limit
    list_limited = client.get("/optimizations", params={"limit": 1})
    assert list_limited.status_code == 200
    assert len(list_limited.json()) <= 1


def test_backtest_fail_when_strategy_has_no_backtest(client: TestClient, tmp_path) -> None:
    # dataset with close column
    csv_bytes = io.BytesIO(b"timestamp,close\n2020-01-01,100\n")
    files = {"file": ("sample.csv", csv_bytes, "text/csv")}
    data = {"name": "no-backtest-dataset", "symbol": "NB", "timeframe": "1d"}
    ds_resp = client.post("/datasets", data=data, files=files)
    assert ds_resp.status_code == 200
    dataset_id = ds_resp.json()["id"]

    # strategy that does NOT define backtest()
    code = "def foo():\n    return 1\n"
    py_path = tmp_path / "no_backtest.py"
    py_path.write_text(code, encoding="utf-8")
    with py_path.open("rb") as f:
        files = {"file": (py_path.name, f, "text/x-python")}
        data = {"name": "no-backtest-strategy", "description": "no backtest func"}
        st_resp = client.post("/strategies", data=data, files=files)
    assert st_resp.status_code == 200
    strategy_id = st_resp.json()["id"]

    payload = {
        "dataset_id": dataset_id,
        "strategy_id": strategy_id,
        "params": {},
        "settings": {},
    }
    bt_resp = client.post("/backtests", json=payload)
    assert bt_resp.status_code == 500
    # failed run should be recorded
    list_resp = client.get("/backtests")
    assert list_resp.status_code == 200
    runs = list_resp.json()
    assert any(r["status"] == "failed" for r in runs)


def test_backtest_fail_when_dataset_has_no_close_column(client: TestClient, tmp_path) -> None:
    # dataset without close column
    csv_bytes = io.BytesIO(b"timestamp,open,high,low\n2020-01-01,1,2,0\n")
    files = {"file": ("noclose.csv", csv_bytes, "text/csv")}
    data = {"name": "no-close-dataset", "symbol": "NC", "timeframe": "1d"}
    ds_resp = client.post("/datasets", data=data, files=files)
    assert ds_resp.status_code == 200
    dataset_id = ds_resp.json()["id"]

    strategy_id = _create_strategy(client)

    payload = {
        "dataset_id": dataset_id,
        "strategy_id": strategy_id,
        "params": {"fast_window": 1, "slow_window": 2},
        "settings": {"initial_capital": 1000000},
    }
    bt_resp = client.post("/backtests", json=payload)
    assert bt_resp.status_code == 500
    list_resp = client.get("/backtests")
    assert list_resp.status_code == 200
    runs = list_resp.json()
    assert any(r["status"] == "failed" for r in runs)


def _create_small_dataset(client: TestClient, rows: int) -> int:
    # rows 行分のダミーデータを作成
    lines = ["timestamp,close"]
    for i in range(rows):
        lines.append(f"2020-01-{i+1:02d},{100 + i}")
    csv_bytes = io.BytesIO("\n".join(lines).encode("utf-8"))
    files = {"file": ("sample.csv", csv_bytes, "text/csv")}
    data = {"name": f"wf-dataset-{rows}", "symbol": "WF", "timeframe": "1d"}
    response = client.post("/datasets", data=data, files=files)
    assert response.status_code == 200
    return response.json()["id"]


def test_walk_forward_success(client: TestClient) -> None:
    dataset_id = _create_small_dataset(client, rows=400)
    strategy_id = _create_strategy(client)

    payload = {
        "dataset_id": dataset_id,
        "strategy_id": strategy_id,
        "search_space": {
            "fast_window": [1, 2],
            "slow_window": [3, 4],
        },
        "settings": {"initial_capital": 1000000},
        "objective_metric": "net_profit",
        "train_bars": 200,
        "test_bars": 50,
        "step_bars": 50,
        "min_trades": None,
    }
    resp = client.post("/walk-forward", json=payload)
    assert resp.status_code == 200
    run = resp.json()
    assert run["id"] > 0
    assert run["status"] in ("running", "success", "failed", "success")

    # list
    list_resp = client.get("/walk-forward")
    assert list_resp.status_code == 200
    runs = list_resp.json()
    assert any(r["id"] == run["id"] for r in runs)

    # get by id
    get_resp = client.get(f"/walk-forward/{run['id']}")
    assert get_resp.status_code == 200

    # result
    result_resp = client.get(f"/walk-forward/{run['id']}/result")
    assert result_resp.status_code == 200
    result_body = result_resp.json()
    assert "windows" in result_body
    assert "summary" in result_body
    assert isinstance(result_body["windows"], list)
    assert len(result_body["windows"]) >= 1
    summary = result_body["summary"]
    assert "avg_oos_score" in summary


def test_walk_forward_dataset_too_short_400(client: TestClient) -> None:
    # dataset with fewer bars than train_bars + test_bars
    dataset_id = _create_small_dataset(client, rows=10)
    strategy_id = _create_strategy(client)

    payload = {
        "dataset_id": dataset_id,
        "strategy_id": strategy_id,
        "search_space": {
            "fast_window": [1, 2],
        },
        "settings": {"initial_capital": 1000000},
        "objective_metric": "net_profit",
        "train_bars": 8,
        "test_bars": 5,
        "step_bars": 5,
        "min_trades": None,
    }
    resp = client.post("/walk-forward", json=payload)
    assert resp.status_code == 400
    assert "fewer bars than train_bars + test_bars" in resp.json()["detail"]


def test_walk_forward_search_space_empty_list_400(client: TestClient) -> None:
    dataset_id = _create_small_dataset(client, rows=400)
    strategy_id = _create_strategy(client)

    payload = {
        "dataset_id": dataset_id,
        "strategy_id": strategy_id,
        "search_space": {
            "fast_window": [],
        },
        "settings": {"initial_capital": 1000000},
        "objective_metric": "net_profit",
        "train_bars": 200,
        "test_bars": 50,
        "step_bars": 50,
        "min_trades": None,
    }
    resp = client.post("/walk-forward", json=payload)
    assert resp.status_code == 400
    assert "must not be an empty list" in resp.json()["detail"]


def test_walk_forward_invalid_bars_400(client: TestClient) -> None:
    dataset_id = _create_small_dataset(client, rows=400)
    strategy_id = _create_strategy(client)

    # train_bars <= 0
    payload = {
        "dataset_id": dataset_id,
        "strategy_id": strategy_id,
        "search_space": {
            "fast_window": [1, 2],
        },
        "settings": {"initial_capital": 1000000},
        "objective_metric": "net_profit",
        "train_bars": 0,
        "test_bars": 50,
        "step_bars": 50,
        "min_trades": None,
    }
    resp = client.post("/walk-forward", json=payload)
    assert resp.status_code == 400

    # test_bars <= 0
    payload["train_bars"] = 200
    payload["test_bars"] = 0
    resp = client.post("/walk-forward", json=payload)
    assert resp.status_code == 400

