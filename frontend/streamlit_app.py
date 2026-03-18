import json
import os
from typing import Any

import pandas as pd
import requests
import streamlit as st

from app_pages import backtest, datasets, optimization_jobs, optimizations, strategies, walk_forward
from app_utils.api import init_session_state
from app_utils.trials_analysis import (
    build_trials_dataframe,
    render_trials_analysis,
    render_trials_ranking,
)


def get_base_url() -> str:
    if "base_url" not in st.session_state:
        st.session_state.base_url = "http://localhost:8000"
    return st.session_state.base_url


def render_backtest_summary(run: dict[str, Any] | None, result: dict[str, Any] | None) -> None:
    if not run:
        return

    metrics = result.get("metrics", {}) if isinstance(result, dict) else {}
    net_profit = metrics.get("net_profit")
    trades = metrics.get("total_trades") or metrics.get("trades")
    win_rate = metrics.get("win_rate")

    st.markdown(
        f"""
**Backtest Summary**  
- Run ID: `{run.get("id")}`  
- Status: `{run.get("status")}`  
- Dataset ID: `{run.get("dataset_id")}`  
- Strategy ID: `{run.get("strategy_id")}`  
- Net Profit: `{net_profit}`  
- Trades: `{trades}`  
- Win Rate: `{win_rate}`
""",
    )


def render_optimization_summary(run: dict[str, Any] | None, result: dict[str, Any] | None) -> None:
    if not run:
        return

    best_score = run.get("best_score")
    objective_metric = None
    if isinstance(result, dict):
        objective_metric = result.get("objective_metric")

    st.markdown(
        f"""
**Optimization Summary**  
- Run ID: `{run.get("id")}`  
- Status: `{run.get("status")}`  
- Dataset ID: `{run.get("dataset_id")}`  
- Strategy ID: `{run.get("strategy_id")}`  
- Best Score: `{best_score}`  
- Objective Metric: `{objective_metric}`
""",
    )


def fetch_json(method: str, path: str, **kwargs: Any) -> tuple[int | None, Any]:
    base_url = get_base_url()
    url = f"{base_url.rstrip('/')}{path}"
    try:
        resp = requests.request(method, url, timeout=30, **kwargs)
        try:
            data = resp.json()
        except Exception:  # noqa: BLE001
            data = resp.text
        return resp.status_code, data
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


def render_sidebar() -> None:
    st.sidebar.header("設定")
    base_url = st.sidebar.text_input("API URL", value=get_base_url())
    st.session_state.base_url = base_url

    st.sidebar.markdown("---")
    if st.sidebar.button("リスト再読み込み"):
        st.session_state.pop("datasets", None)
        st.session_state.pop("strategies", None)


def load_datasets() -> list[dict[str, Any]]:
    if "datasets" not in st.session_state:
        status, data = fetch_json("GET", "/datasets")
        if status == 200 and isinstance(data, list):
            st.session_state.datasets = data
        else:
            st.session_state.datasets = []
            st.warning(f"Failed to load datasets: {data}")
    return st.session_state.datasets


def load_strategies() -> list[dict[str, Any]]:
    if "strategies" not in st.session_state:
        status, data = fetch_json("GET", "/strategies")
        if status == 200 and isinstance(data, list):
            st.session_state.strategies = data
        else:
            st.session_state.strategies = []
            st.warning(f"Failed to load strategies: {data}")
    return st.session_state.strategies


def main() -> None:
    st.set_page_config(page_title="TVバックテストツール (MVP)", layout="wide")
    init_session_state()
    render_sidebar()
    pages = {
        "アプリ": [
            st.Page(_render_main_legacy, title="メイン", icon="🏠"),
            st.Page(datasets.render, title="データセット", icon="📂", url_path="datasets"),
            st.Page(strategies.render, title="ストラテジー", icon="🧩", url_path="strategies"),
            st.Page(backtest.render, title="バックテスト", icon="🧪", url_path="backtests"),
            st.Page(optimizations.render, title="最適化", icon="🧮", url_path="optimizations"),
            st.Page(
                optimization_jobs.render,
                title="最適化ジョブ一覧",
                icon="📋",
                url_path="optimization-jobs",
            ),
            st.Page(
                walk_forward.render,
                title="Walk Forward",
                icon="📈",
                url_path="walk-forward",
            ),
        ],
    }
    nav = st.navigation(pages)
    nav.run()


def _render_main_legacy() -> None:

    st.title("TVバックテストツール (MVP)")

    # 概要カード（直近の実行状況 + リソース件数）
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("最終バックテスト ID", st.session_state.get("last_backtest_id") or "-")
    with col2:
        st.metric("最終最適化 ID", st.session_state.get("last_optimization_id") or "-")
    with col3:
        st.metric("最終 Walk Forward ID", st.session_state.get("last_wf_id") or "-")

    datasets = load_datasets()
    strategies = load_strategies()

    col4, col5 = st.columns(2)
    with col4:
        st.metric("データセット数", len(datasets))
    with col5:
        st.metric("ストラテジー数", len(strategies))

    st.markdown("---")

    # 各機能ページへの案内
    st.markdown("#### 機能概要")

    st.markdown(
        "- **データセット**: 検証用 CSV データの一覧とアップロードができます（`データセット` ページ）。",
    )
    st.markdown(
        "- **ストラテジー**: Python ストラテジーの一覧とアップロードができます（`ストラテジー` ページ）。",
    )
    st.markdown(
        "- **バックテスト**: 選択したデータセットとストラテジーで単一バックテストを実行し、詳細結果を確認できます（`バックテスト` ページ）。",
    )
    st.markdown(
        "- **最適化**: パラメータサーチによる最適化ジョブを起動し、試行一覧や分析 UI を確認できます（`最適化` ページ）。",
    )
    st.markdown(
        "- **最適化ジョブ一覧**: 過去の最適化ジョブのステータス・結果を一覧・詳細で確認できます（`最適化ジョブ一覧` ページ）。",
    )
    st.markdown(
        "- **Walk Forward**: Walk Forward 検証の実行、履歴、ウィンドウ別結果からのバックテスト再実行ができます（`Walk Forward` ページ）。",
    )



if __name__ == "__main__":
    main()

