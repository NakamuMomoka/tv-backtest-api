from __future__ import annotations

import time

from fastapi.testclient import TestClient

from app.services.optimization_service import _score_from_metrics


def test_objective_metric_persists_in_run_and_result_successfully(client: TestClient) -> None:
    # arrange dataset & strategy
    from .test_api import _create_dataset, _create_strategy  # re-use helpers

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
        "objective_metric": "profit_factor",
    }

    # 1. POST /optimizations で指定した objective_metric が保存されること
    # NOTE: 非同期起動だが、HTTP レイヤの仕様としては 200 を維持している。
    #       将来 202 などに変えたくなった場合は、このテストも合わせて更新する。
    run_resp = client.post("/optimizations", json=payload)
    assert run_resp.status_code == 200
    run_body = run_resp.json()
    run_id = run_body["id"]
    assert run_body["objective_metric"] == "profit_factor"

    # 2. 非同期ジョブ完了後も GET /optimizations/{id} で objective_metric が保持されること
    #    （小さな sleep を挟みつつ success になるのを待つ）
    get_body = None
    for _ in range(50):
        time.sleep(0.2)
        get_resp = client.get(f"/optimizations/{run_id}")
        assert get_resp.status_code == 200
        get_body = get_resp.json()
        assert get_body["objective_metric"] == "profit_factor"
        if get_body["status"] == "success":
            break
    else:
        raise AssertionError("Optimization did not finish within expected attempts")

    # 3. GET /optimizations/{id}/result の objective_metric が保存値と一致すること
    assert get_body is not None
    assert get_body["status"] == "success"

    result_resp = client.get(f"/optimizations/{run_id}/result")
    assert result_resp.status_code == 200
    result_body = result_resp.json()
    assert result_body["objective_metric"] == "profit_factor"


def test_score_from_metrics_changes_with_different_objective_metric() -> None:
    metrics = {
        "net_profit": 1000.0,
        "profit_factor": 1.5,
    }

    score_net_profit = _score_from_metrics(metrics, "net_profit")
    score_profit_factor = _score_from_metrics(metrics, "profit_factor")

    assert score_net_profit != score_profit_factor
    assert score_net_profit == 1000.0
    assert score_profit_factor == 1.5

