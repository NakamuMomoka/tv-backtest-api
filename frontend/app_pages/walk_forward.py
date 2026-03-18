from __future__ import annotations

import json
from typing import Any

import pandas as pd
import streamlit as st

from app_utils.api import fetch_json, load_datasets, load_strategies


def render() -> None:
    st.title("Walk Forward 検証")

    datasets = load_datasets()
    strategies = load_strategies()
    wf_dataset_options = {f'{d["id"]}: {d["name"]}': d["id"] for d in datasets}
    wf_strategy_options = {f'{s["id"]}: {s["name"]}': s["id"] for s in strategies}

    # 実行フォーム
    st.markdown("#### Walk Forward 実行")
    wf_selected_dataset = st.selectbox(
        "データ（Walk Forward 用）",
        options=list(wf_dataset_options.keys()),
        key="wf_dataset",
    ) if wf_dataset_options else None
    wf_selected_strategy = st.selectbox(
        "ストラテジー（Walk Forward 用）",
        options=list(wf_strategy_options.keys()),
        key="wf_strategy",
    ) if wf_strategy_options else None

    wf_search_space_text = st.text_area(
        "最適化パラメータ (JSON, Walk Forward)",
        value='{"fast_window": [5, 10], "slow_window": [20, 30]}',
        height=100,
        key="wf_search_space",
    )
    wf_settings_text = st.text_area(
        "プロパティ (JSON, Walk Forward)",
        value='{"initial_capital": 1000000}',
        height=80,
        key="wf_settings",
    )
    wf_objective_metric = st.text_input(
        "最適化指標 (Walk Forward)",
        value="net_profit",
        key="wf_objective_metric",
    )

    wf_start_date = st.text_input(
        "開始日 (YYYY-MM-DD, 任意・timestamp 列必須)",
        value="",
        key="wf_start_date",
    )
    wf_end_date = st.text_input(
        "終了日 (YYYY-MM-DD, 任意・timestamp 列必須)",
        value="",
        key="wf_end_date",
    )

    col_wf1, col_wf2, col_wf3, col_wf4 = st.columns(4)
    with col_wf1:
        wf_train_bars = st.number_input("train_bars", min_value=1, value=200, step=1, key="wf_train_bars")
    with col_wf2:
        wf_test_bars = st.number_input("test_bars", min_value=1, value=50, step=1, key="wf_test_bars")
    with col_wf3:
        wf_step_bars = st.number_input(
            "step_bars (0でtest_bars)",
            min_value=0,
            value=50,
            step=1,
            key="wf_step_bars",
        )
    with col_wf4:
        wf_min_trades = st.number_input("min_trades (任意)", min_value=0, value=0, step=1, key="wf_min_trades")

    if st.button("Walk Forward 検証を実行"):
        if not wf_selected_dataset or not wf_selected_strategy:
            st.error("データとストラテジーを選択してください。")
        else:
            try:
                wf_search_space = (
                    json.loads(wf_search_space_text) if wf_search_space_text.strip() else {}
                )
                wf_settings = (
                    json.loads(wf_settings_text) if wf_settings_text.strip() else None
                )
            except json.JSONDecodeError as exc:
                st.error(f"Walk Forward の search_space/settings の JSON が不正です: {exc}")
            else:
                payload = {
                    "dataset_id": wf_dataset_options[wf_selected_dataset],
                    "strategy_id": wf_strategy_options[wf_selected_strategy],
                    "search_space": wf_search_space,
                    "settings": wf_settings,
                    "objective_metric": wf_objective_metric or None,
                    "train_bars": int(wf_train_bars),
                    "test_bars": int(wf_test_bars),
                    "step_bars": int(wf_step_bars) if wf_step_bars > 0 else None,
                    "min_trades": int(wf_min_trades) if wf_min_trades > 0 else None,
                    "start_date": wf_start_date or None,
                    "end_date": wf_end_date or None,
                }
                status, data = fetch_json("POST", "/walk-forward", json=payload)
                st.write("Status:", status)
                if isinstance(data, (dict, list)):
                    st.json(data)
                else:
                    st.write(data)
                if status == 200 and isinstance(data, dict):
                    st.session_state.last_wf_id = data.get("id")

    # 直近結果
    st.markdown("#### 直近の Walk Forward 結果")
    last_wf_id = st.session_state.get("last_wf_id")
    if last_wf_id:
        if st.button("Load Last Walk Forward Result"):
            run_status, run_data = fetch_json("GET", f"/walk-forward/{last_wf_id}")
            res_status, res_data = fetch_json("GET", f"/walk-forward/{last_wf_id}/result")
            st.write("Status:", res_status)
            if res_status == 200 and isinstance(res_data, dict):
                _render_wf_result(res_data, run_status, run_data)
            else:
                if isinstance(res_data, (dict, list)):
                    st.json(res_data)
                else:
                    st.write(res_data)

    # 履歴
    st.markdown("#### Walk Forward 履歴")
    if st.button("Reload Walk Forward Runs"):
        status, data = fetch_json("GET", "/walk-forward")
        if status == 200 and isinstance(data, list):
            st.session_state.wf_runs = data
        else:
            st.warning(f"Failed to load walk-forward runs: {data}")

    wf_runs = st.session_state.get("wf_runs", [])
    if wf_runs:
        df_wf = pd.DataFrame(wf_runs)

        def extract_summary_value(row: pd.Series, key: str) -> Any:
            try:
                sj = row.get("summary_json")
                if not isinstance(sj, str) or not sj:
                    return None
                s = json.loads(sj)
                return s.get(key)
            except Exception:  # noqa: BLE001
                return None

        if "summary_json" in df_wf.columns:
            df_wf["avg_oos_score"] = df_wf.apply(
                lambda r: extract_summary_value(r, "avg_oos_score"),
                axis=1,
            )
            df_wf["success_windows"] = df_wf.apply(
                lambda r: extract_summary_value(r, "success_windows"),
                axis=1,
            )
            df_wf["failed_windows"] = df_wf.apply(
                lambda r: extract_summary_value(r, "failed_windows"),
                axis=1,
            )

        st.write("フィルター（Walk Forward）")
        col_wf_f1, col_wf_f2, col_wf_f3 = st.columns(3)
        with col_wf_f1:
            wf_status_filter = st.multiselect(
                "ステータス",
                options=sorted(df_wf["status"].dropna().unique()),
                default=list(sorted(df_wf["status"].dropna().unique())),
                key="wf_status_filter",
            )
        with col_wf_f2:
            wf_dataset_filter = st.multiselect(
                "データセットID",
                options=sorted(df_wf["dataset_id"].dropna().unique()),
                default=list(sorted(df_wf["dataset_id"].dropna().unique())),
                key="wf_dataset_filter",
            )
        with col_wf_f3:
            wf_strategy_filter = st.multiselect(
                "ストラテジーID",
                options=sorted(df_wf["strategy_id"].dropna().unique()),
                default=list(sorted(df_wf["strategy_id"].dropna().unique())),
                key="wf_strategy_filter",
            )

        wf_mask = (
            df_wf["status"].isin(wf_status_filter)
            & df_wf["dataset_id"].isin(wf_dataset_filter)
            & df_wf["strategy_id"].isin(wf_strategy_filter)
        )
        df_wf_view = df_wf[wf_mask]

        wf_columns = [
            "id",
            "dataset_id",
            "strategy_id",
            "status",
            "train_bars",
            "test_bars",
            "step_bars",
            "avg_oos_score",
            "success_windows",
            "failed_windows",
            "created_at",
            "finished_at",
        ]
        existing_cols = [c for c in wf_columns if c in df_wf_view.columns]
        st.dataframe(df_wf_view[existing_cols], use_container_width=True)

        wf_options = {
            f'{row["id"]}: status={row["status"]}': row["id"]
            for _, row in df_wf_view.iterrows()
        }
        selected_wf_run = st.selectbox(
            "Walk Forward 実行を選択",
            options=list(wf_options.keys()),
            key="wf_history_select",
        )
        if st.button("Load Selected Walk Forward Result"):
            run_id = wf_options[selected_wf_run]
            run_status_sel, run_data_sel = fetch_json("GET", f"/walk-forward/{run_id}")
            _, res_data_sel = fetch_json("GET", f"/walk-forward/{run_id}/result")
            if isinstance(res_data_sel, dict):
                _render_wf_result(res_data_sel, run_status_sel, run_data_sel)


def _render_wf_result(res_data: dict[str, Any], run_status: int, run_data: Any) -> None:
    summary = res_data.get("summary", {})
    windows = res_data.get("windows", [])

    st.subheader("Walk Forward サマリ")
    col_s1, col_s2, col_s3 = st.columns(3)
    with col_s1:
        st.metric("avg_oos_score", summary.get("avg_oos_score"))
        st.metric("median_oos_score", summary.get("median_oos_score"))
    with col_s2:
        st.metric("best_oos_score", summary.get("best_oos_score"))
        st.metric("worst_oos_score", summary.get("worst_oos_score"))
    with col_s3:
        st.metric("success_windows", summary.get("success_windows"))
        st.metric("failed_windows", summary.get("failed_windows"))

    if windows:
        st.subheader("Walk Forward ウィンドウ一覧")
        df_windows = pd.DataFrame(windows)
        preferred_cols = [
            "window_no",
            "status",
            "train_best_score",
            "oos_score",
        ]
        other_cols = [c for c in df_windows.columns if c not in preferred_cols]
        ordered_cols = [c for c in preferred_cols if c in df_windows.columns] + other_cols
        st.dataframe(df_windows[ordered_cols], use_container_width=True)

        if "oos_score" in df_windows.columns:
            st.subheader("OOSスコア推移")
            df_oos = df_windows[["window_no", "oos_score"]].dropna()
            if not df_oos.empty:
                avg_oos = summary.get("avg_oos_score")
                if isinstance(avg_oos, (int, float)):
                    df_oos = df_oos.copy()
                    df_oos["avg_oos_score"] = float(avg_oos)
                st.line_chart(df_oos.set_index("window_no"))

    # 成功ウィンドウからバックテスト再実行
    w_success = [w for w in windows if w.get("status") == "success" and w.get("best_params")]
    if w_success and run_status == 200 and isinstance(run_data, dict):
        st.subheader("結果からバックテスト再実行")
        w_options = [
            f"Window {w['window_no']} (oos_score={w.get('oos_score')})"
            for w in w_success
        ]
        wi = st.selectbox(
            "ウィンドウを選択",
            options=list(range(len(w_success))),
            format_func=lambda i: w_options[i],
            key="wf_rerun_select",
        )
        if st.button("選択したウィンドウのパラメータでバックテストを実行", key="wf_rerun_bt"):
            bp = w_success[wi]["best_params"]
            settings = {}
            raw_settings = run_data.get("settings_json")
            if isinstance(raw_settings, str) and raw_settings:
                try:
                    settings = json.loads(raw_settings)
                except Exception:  # noqa: BLE001
                    settings = {}

            bt_status, bt_data = fetch_json(
                "POST",
                "/backtests",
                json={
                    "dataset_id": run_data["dataset_id"],
                    "strategy_id": run_data["strategy_id"],
                    "params": bp,
                    "settings": settings,
                },
            )
            if bt_status == 200 and isinstance(bt_data, dict):
                st.session_state.last_backtest_id = bt_data.get("id")
                st.success("バックテストを実行しました。左の「直近のテスト結果」で確認できます。")
            else:
                st.error(str(bt_data) if bt_data else "バックテストに失敗しました。")

