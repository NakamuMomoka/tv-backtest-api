from __future__ import annotations

import json
from typing import Any

import pandas as pd
import streamlit as st

from app_utils.api import fetch, fetch_json, load_datasets, load_strategies
from app_utils.renderers import render_backtest_summary


def render() -> None:
    st.title("バックテスト")
    st.caption(
        "この画面では単発バックテストを実行し、指標・トレード・エクイティ推移を確認します。"
        " 初回は上から順に「データセット→ストラテジー→期間→実行」で進めてください。"
    )

    datasets = load_datasets()
    strategies = load_strategies()
    dataset_options = {f'{d["id"]}: {d["name"]}': d["id"] for d in datasets}
    strategy_options = {f'{s["id"]}: {s["name"]}': s for s in strategies}

    # 実行フォーム
    st.subheader("1) バックテスト実行")
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
        st.caption("通常はデフォルト値から開始し、差分検証したい項目だけ変更するのがおすすめです。")
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
    bt_fee_percent = st.number_input(
        "手数料 (% / side)",
        min_value=0.0,
        value=0.06,
        step=0.01,
        format="%.4f",
        key="bt_fee_percent",
        help="Bitget先物 taker を想定した既定値です。内部では fee_rate (例: 0.0006) として扱います。",
    )
    st.caption(f"内部 fee_rate: {float(bt_fee_percent) / 100.0:.6f}（entry/exit 両側に適用）")

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

    if st.button("バックテストを実行"):
        if not selected_dataset or not selected_strategy:
            st.error("Dataset and Strategy must be selected.")
        else:
            try:
                settings = json.loads(settings_text) if settings_text.strip() else None
            except json.JSONDecodeError as exc:
                st.error(f"Invalid JSON in settings: {exc}")
            else:
                settings = dict(settings or {})
                settings["fee_rate"] = float(bt_fee_percent) / 100.0
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

    # 履歴一覧（選択して再表示）
    st.markdown("### 2) 実行履歴一覧")
    st.caption("重要列を一覧で確認し、対象行を選んで詳細を表示します。")
    if st.button("履歴一覧を更新"):
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
        st.markdown("#### フィルター")
        col_f1, col_f2, col_f3 = st.columns(3)
        with col_f1:
            status_values = sorted(df_bt["status"].dropna().unique())
            status_filter = st.selectbox(
                "ステータス",
                options=["all"] + status_values,
                key="bt_status_filter",
            )
        with col_f2:
            dataset_values = sorted(df_bt["dataset_id"].dropna().unique())
            dataset_filter = st.selectbox(
                "データセットID",
                options=["all"] + dataset_values,
                key="bt_dataset_filter",
            )
        with col_f3:
            strategy_values = sorted(df_bt["strategy_id"].dropna().unique())
            strategy_filter = st.selectbox(
                "ストラテジーID",
                options=["all"] + strategy_values,
                key="bt_strategy_filter",
            )

        mask = pd.Series(True, index=df_bt.index)
        if status_filter != "all":
            mask &= df_bt["status"] == status_filter
        if dataset_filter != "all":
            mask &= df_bt["dataset_id"] == dataset_filter
        if strategy_filter != "all":
            mask &= df_bt["strategy_id"] == strategy_filter

        df_bt_view = df_bt.loc[
            mask,
            [
                "id",
                "status",
                "dataset_id",
                "strategy_id",
                "created_at",
                "finished_at",
                "net_profit",
                "trades",
                "win_rate",
            ],
        ]
        st.caption(f"表示件数: {len(df_bt_view)} 件")
        st.dataframe(df_bt_view, use_container_width=True)

        bt_options = {
            f'#{r["id"]} | {r["status"]} | ds={r["dataset_id"]} st={r["strategy_id"]}': r["id"]
            for _, r in df_bt_view.iterrows()
        }
        if bt_options:
            selected_bt_run = st.selectbox(
                "表示する実行を選択",
                options=list(bt_options.keys()),
                key="history_bt_select",
            )
            if st.button("詳細を表示"):
                run_id = bt_options[selected_bt_run]
                run_status, run_data = fetch_json("GET", f"/backtests/{run_id}")
                status, data = fetch_json("GET", f"/backtests/{run_id}/result")
                st.write("Status:", status)
                if run_status == 200 and isinstance(run_data, dict):
                    render_backtest_summary(run_data, data if isinstance(data, dict) else {})
                if status == 200 and isinstance(data, dict):
                    st.markdown("---")
                    _render_backtest_detail(data)
                else:
                    if isinstance(data, (dict, list)):
                        st.json(data)
                    else:
                        st.write(data)
        else:
            st.info("条件に一致する履歴がありません。")
    else:
        st.info("まだ実行履歴がありません。まず上の「1) バックテスト実行」から作成してください。")


def _render_backtest_detail(data: dict[str, Any]) -> None:
    metrics = data.get("metrics", {})
    trades = data.get("trades", [])
    equity_series = data.get("equity_series", [])
    if metrics:
        st.write("パフォーマンス")
        fee_rate_used = metrics.get("fee_rate_used")
        if isinstance(fee_rate_used, (int, float)):
            st.caption(
                f"手数料: {float(fee_rate_used) * 100:.4f}% / side "
                f"(fee_rate_used={float(fee_rate_used):.6f}) / 評価は手数料込み"
            )
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

