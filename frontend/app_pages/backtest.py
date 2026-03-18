from __future__ import annotations

import json
from typing import Any

import pandas as pd
import streamlit as st

from app_utils.api import fetch, fetch_json, load_datasets, load_strategies
from app_utils.renderers import render_backtest_summary


def render() -> None:
    st.title("バックテスト")

    datasets = load_datasets()
    strategies = load_strategies()
    dataset_options = {f'{d["id"]}: {d["name"]}': d["id"] for d in datasets}
    strategy_options = {f'{s["id"]}: {s["name"]}': s for s in strategies}

    # 実行フォーム
    st.subheader("ストラテジーのテスト")
    selected_dataset = st.selectbox(
        "データセット",
        options=list(dataset_options.keys()),
        key="bt_dataset",
    ) if dataset_options else None
    selected_strategy = st.selectbox(
        "ストラテジー",
        options=list(strategy_options.keys()),
        key="bt_strategy",
    ) if strategy_options else None

    # パラメータフォーム自動生成
    params: dict[str, Any] | None = None
    if selected_strategy:
        st.markdown("##### パラメータ")
        st_key = strategy_options[selected_strategy]
        default_params_json = st_key.get("default_params_json")
        try:
            default_params = (
                json.loads(default_params_json)
                if isinstance(default_params_json, str) and default_params_json.strip()
                else {}
            )
        except json.JSONDecodeError:
            default_params = {}

        params = {}
        for p_key, p_default in default_params.items():
            widget_key = f"bt_param_{st_key['id']}_{p_key}"
            if isinstance(p_default, bool):
                params[p_key] = st.checkbox(p_key, value=p_default, key=widget_key)
            elif isinstance(p_default, int):
                params[p_key] = int(
                    st.number_input(p_key, value=float(p_default), step=1.0, key=widget_key),
                )
            elif isinstance(p_default, float):
                params[p_key] = float(
                    st.number_input(p_key, value=p_default, key=widget_key),
                )
            else:
                params[p_key] = st.text_input(
                    p_key,
                    value=str(p_default),
                    key=widget_key,
                )

    settings_text = st.text_area(
        "プロパティ (JSON)",
        value='{"initial_capital": 1000000}',
        height=80,
        key="bt_settings",
    )

    bt_start_date = st.text_input(
        "開始日 (YYYY-MM-DD, 任意・timestamp 列必須)",
        value="",
        key="bt_start_date",
    )
    bt_end_date = st.text_input(
        "終了日 (YYYY-MM-DD, 任意・timestamp 列必須)",
        value="",
        key="bt_end_date",
    )

    if st.button("ストラテジーをテスト"):
        if not selected_dataset or not selected_strategy:
            st.error("Dataset and Strategy must be selected.")
        else:
            try:
                settings = json.loads(settings_text) if settings_text.strip() else None
            except json.JSONDecodeError as exc:
                st.error(f"Invalid JSON in settings: {exc}")
            else:
                st_key = strategy_options[selected_strategy]
                payload = {
                    "dataset_id": dataset_options[selected_dataset],
                    "strategy_id": st_key["id"],
                    "params": params or None,
                    "settings": settings,
                    "start_date": bt_start_date or None,
                    "end_date": bt_end_date or None,
                }
                status, data = fetch_json("POST", "/backtests", json=payload)
                st.write("Status:", status)
                if isinstance(data, (dict, list)):
                    st.json(data)
                else:
                    st.write(data)
                if status == 200 and isinstance(data, dict):
                    st.session_state.last_backtest_id = data.get("id")

    # 直近結果
    st.markdown("##### 直近のテスト結果")
    last_bt_id = st.session_state.get("last_backtest_id")
    if last_bt_id:
        if st.button("Load Last Backtest Result"):
            run_status, run_data = fetch_json("GET", f"/backtests/{last_bt_id}")
            status, data = fetch_json("GET", f"/backtests/{last_bt_id}/result")
            st.write("Status:", status)
            if run_status == 200 and isinstance(run_data, dict):
                render_backtest_summary(run_data, data if isinstance(data, dict) else {})
            if status == 200 and isinstance(data, dict):
                _render_backtest_detail(data)
            else:
                if isinstance(data, (dict, list)):
                    st.json(data)
                else:
                    st.write(data)

    # 履歴
    st.markdown("##### テスト履歴")
    if st.button("Reload Backtest Runs"):
        status, data = fetch_json("GET", "/backtests")
        if status == 200 and isinstance(data, list):
            st.session_state.backtest_runs = data
        else:
            st.warning(f"Failed to load backtests: {data}")

    bt_runs = st.session_state.get("backtest_runs", [])
    if bt_runs:
        df_bt = pd.DataFrame(bt_runs)

        # 追加指標の抽出 (net_profit, trades, win_rate)
        def extract_metric(row: pd.Series, key: str, default: Any = None) -> Any:
            try:
                mj = row.get("metrics_json")
                if not isinstance(mj, str) or not mj:
                    return default
                m = json.loads(mj)
                return m.get(key, default)
            except Exception:  # noqa: BLE001
                return default

        if "metrics_json" in df_bt.columns:
            df_bt["net_profit"] = df_bt.apply(
                lambda r: extract_metric(r, "net_profit"),
                axis=1,
            )
            df_bt["trades"] = df_bt.apply(
                lambda r: extract_metric(r, "total_trades"),
                axis=1,
            )
            df_bt["win_rate"] = df_bt.apply(
                lambda r: extract_metric(r, "win_rate"),
                axis=1,
            )

        # 絞り込み UI
        st.write("フィルター")
        col_f1, col_f2, col_f3 = st.columns(3)
        with col_f1:
            status_filter = st.multiselect(
                "ステータス",
                options=sorted(df_bt["status"].dropna().unique()),
                default=list(sorted(df_bt["status"].dropna().unique())),
                key="bt_status_filter",
            )
        with col_f2:
            dataset_filter = st.multiselect(
                "データセットID",
                options=sorted(df_bt["dataset_id"].dropna().unique()),
                default=list(sorted(df_bt["dataset_id"].dropna().unique())),
                key="bt_dataset_filter",
            )
        with col_f3:
            strategy_filter = st.multiselect(
                "ストラテジーID",
                options=sorted(df_bt["strategy_id"].dropna().unique()),
                default=list(sorted(df_bt["strategy_id"].dropna().unique())),
                key="bt_strategy_filter",
            )

        mask = (
            df_bt["status"].isin(status_filter)
            & df_bt["dataset_id"].isin(dataset_filter)
            & df_bt["strategy_id"].isin(strategy_filter)
        )
        df_bt_view = df_bt.loc[
            mask,
            [
                "id",
                "dataset_id",
                "strategy_id",
                "status",
                "created_at",
                "finished_at",
                "net_profit",
                "trades",
                "win_rate",
            ],
        ]
        st.dataframe(df_bt_view, use_container_width=True)

        bt_options = {f'{r["id"]}: status={r["status"]}': r["id"] for _, r in df_bt_view.iterrows()}
        if bt_options:
            selected_bt_run = st.selectbox(
                "バックテストを選択",
                options=list(bt_options.keys()),
                key="history_bt_select",
            )
            if st.button("Load Selected Backtest Result"):
                run_id = bt_options[selected_bt_run]
                run_status, run_data = fetch_json("GET", f"/backtests/{run_id}")
                status, data = fetch_json("GET", f"/backtests/{run_id}/result")
                st.write("Status:", status)
                if run_status == 200 and isinstance(run_data, dict):
                    render_backtest_summary(run_data, data if isinstance(data, dict) else {})
                if status == 200 and isinstance(data, dict):
                    _render_backtest_detail(data)
                else:
                    if isinstance(data, (dict, list)):
                        st.json(data)
                    else:
                        st.write(data)


def _render_backtest_detail(data: dict[str, Any]) -> None:
    metrics = data.get("metrics", {})
    trades = data.get("trades", [])
    equity_series = data.get("equity_series", [])
    if metrics:
        st.write("パフォーマンス")
        st.table(
            [{"metric": k, "value": v} for k, v in metrics.items()],
        )
    if trades:
        st.write("トレード一覧")
        st.dataframe(trades, use_container_width=True)
    if equity_series:
        st.write("エクイティカーブ")
        try:
            df_eq = pd.DataFrame(equity_series)
            x_col = None
            for candidate in ("time", "timestamp"):
                if candidate in df_eq.columns:
                    x_col = candidate
                    break
            if x_col and "equity" in df_eq.columns:
                st.line_chart(df_eq.set_index(x_col)["equity"])
            elif "equity" in df_eq.columns:
                st.line_chart(df_eq.set_index(df_eq.columns[0])["equity"])
            else:
                st.line_chart(df_eq)
        except Exception:  # noqa: BLE001
            st.json(equity_series)

