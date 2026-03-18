from __future__ import annotations

import time

from fastapi.testclient import TestClient

from app.services.optimization_service import params_signature


def _wait_for_optimization_success(client: TestClient, run_id: int, timeout_seconds: float = 10) -> dict:
    deadline = time.time() + timeout_seconds
    last_body: dict | None = None
    while time.time() < deadline:
        resp = client.get(f"/optimizations/{run_id}")
        assert resp.status_code == 200
        body = resp.json()
        last_body = body
        if body["status"] == "success":
            return body
        time.sleep(0.2)
    raise AssertionError(f"Optimization {run_id} did not succeed within timeout; last body={last_body}")


def _create_dataset_and_strategy(client: TestClient) -> tuple[int, int]:
    from .test_api import _create_dataset, _create_strategy

    dataset_id = _create_dataset(client)
    strategy_id = _create_strategy(client)
    return dataset_id, strategy_id


def test_random_search_basic_creation(client: TestClient) -> None:
    dataset_id, strategy_id = _create_dataset_and_strategy(client)

    payload = {
        "dataset_id": dataset_id,
        "strategy_id": strategy_id,
        "search_space": {
            "fast_window": [1, 2, 3],
            "slow_window": [4, 5],
        },
        "settings": {"initial_capital": 1000000},
        "objective_metric": "net_profit",
        "search_mode": "random",
        "n_trials": 3,
    }

    run_resp = client.post("/optimizations", json=payload)
    assert run_resp.status_code == 200
    body = run_resp.json()
    assert body["search_mode"] == "random"
    assert body["n_trials"] == 3

    run_id = body["id"]
    run_body = _wait_for_optimization_success(client, run_id)
    assert run_body["search_mode"] == "random"
    assert run_body["requested_trials"] == 3
    # executed_trials は search_space や過去履歴次第で変わるが、少なくとも 1 以上であることを期待
    assert run_body["executed_trials"] >= 1

    result_resp = client.get(f"/optimizations/{run_id}/result")
    assert result_resp.status_code == 200
    result_body = result_resp.json()
    assert result_body["search_mode"] == "random"
    assert result_body["requested_trials"] == 3


def test_random_search_no_duplicate_params_within_job(client: TestClient) -> None:
    dataset_id, strategy_id = _create_dataset_and_strategy(client)

    payload = {
        "dataset_id": dataset_id,
        "strategy_id": strategy_id,
        "search_space": {
            "fast_window": [1, 2, 3],
            "slow_window": [4, 5],
        },
        "settings": {"initial_capital": 1000000},
        "objective_metric": "net_profit",
        "search_mode": "random",
        "n_trials": 6,
    }

    run_resp = client.post("/optimizations", json=payload)
    assert run_resp.status_code == 200
    run_id = run_resp.json()["id"]

    _ = _wait_for_optimization_success(client, run_id)

    result_resp = client.get(f"/optimizations/{run_id}/result")
    assert result_resp.status_code == 200
    result_body = result_resp.json()
    trials = result_body["trials"]

    sigs = [params_signature(t["params"]) for t in trials if isinstance(t.get("params"), dict)]
    assert len(sigs) == len(set(sigs))


def test_random_search_excludes_previously_tested_params(client: TestClient) -> None:
    dataset_id, strategy_id = _create_dataset_and_strategy(client)

    base_search_space = {
        "fast_window": [1, 2],
        "slow_window": [4, 5],
    }

    # 1st run: grid search to test all combinations
    first_payload = {
        "dataset_id": dataset_id,
        "strategy_id": strategy_id,
        "search_space": base_search_space,
        "settings": {"initial_capital": 1000000},
        "objective_metric": "net_profit",
        "search_mode": "grid",
    }
    first_resp = client.post("/optimizations", json=first_payload)
    assert first_resp.status_code == 200
    first_id = first_resp.json()["id"]
    _ = _wait_for_optimization_success(client, first_id)

    first_result = client.get(f"/optimizations/{first_id}/result").json()
    first_sigs = {
        params_signature(t["params"])
        for t in first_result["trials"]
        if isinstance(t.get("params"), dict)
    }

    # 2nd run: random search should try to avoid previously tested params
    second_payload = {
        "dataset_id": dataset_id,
        "strategy_id": strategy_id,
        "search_space": base_search_space,
        "settings": {"initial_capital": 1000000},
        "objective_metric": "net_profit",
        "search_mode": "random",
        "n_trials": 10,
    }
    second_resp = client.post("/optimizations", json=second_payload)
    assert second_resp.status_code == 200
    second_id = second_resp.json()["id"]
    second_run = _wait_for_optimization_success(client, second_id)

    # 全候補を 1 回目で使い切っているので、2 回目は executed_trials=0 が期待される
    assert second_run["executed_trials"] == 0
    assert second_run["requested_trials"] == 10
    assert second_run["message"] == "No unseen candidates remaining."

    second_result = client.get(f"/optimizations/{second_id}/result").json()
    second_sigs = {
        params_signature(t["params"])
        for t in second_result["trials"]
        if isinstance(t.get("params"), dict)
    }
    # 実際には trials 自体が空のはず
    assert second_sigs.isdisjoint(first_sigs)


def test_params_signature_key_order_independent() -> None:
    p1 = {"COG_PERIOD": 20, "DOTEN": True}
    p2 = {"DOTEN": True, "COG_PERIOD": 20}

    sig1 = params_signature(p1)
    sig2 = params_signature(p2)

    assert sig1 == sig2


def test_grid_search_compatibility(client: TestClient) -> None:
    dataset_id, strategy_id = _create_dataset_and_strategy(client)

    payload = {
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

    run_resp = client.post("/optimizations", json=payload)
    assert run_resp.status_code == 200
    run_id = run_resp.json()["id"]

    run_body = _wait_for_optimization_success(client, run_id)
    assert run_body["search_mode"] == "grid"
    assert run_body["status"] == "success"

