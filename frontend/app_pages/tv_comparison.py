from __future__ import annotations

from typing import Any

import streamlit as st

from app_utils.api import fetch_json
from app_utils.tv_comparison import render_tv_comparison


def render() -> None:
    st.title("TV比較")
    st.caption(
        "この画面では TradingView 基準結果と App バックテスト結果を比較します。"
        " まず期間・strategy/dataset が合っているか確認してから比較を実行してください。"
    )
    st.warning(
        "**手数料条件の確認:** TV 側の手数料設定（commission / taker / maker など）と、"
        "本 App のバックテストで使用した **fee_rate（片側ノーショナル比率）** が一致しているか必ず確認してください。"
        " 条件が異なるとトレード一致率・損益指標の一致率が下がります。"
    )

    # 一覧取得
    tv_status, tv_list = fetch_json("GET", "/tv-references")
    bt_status, bt_list = fetch_json("GET", "/backtests")

    if tv_status != 200 or not isinstance(tv_list, list):
        st.error(f"TV reference 一覧取得に失敗しました: status={tv_status}")
        if isinstance(tv_list, (dict, list)):
            st.json(tv_list)
        else:
            st.write(tv_list)
        return

    if bt_status != 200 or not isinstance(bt_list, list):
        st.error(f"Backtest 一覧取得に失敗しました: status={bt_status}")
        if isinstance(bt_list, (dict, list)):
            st.json(bt_list)
        else:
            st.write(bt_list)
        return

    if not tv_list:
        st.info("TV reference が登録されていません。先に「TV基準結果」ページで登録してください。")
        return

    if not bt_list:
        st.info("Backtest run がありません。先に「バックテスト」ページで実行してください。")
        return

    st.markdown("### 比較対象選択")

    tv_opts = {f'{r["id"]}: {r.get("name") or ""}': r for r in tv_list if "id" in r}
    bt_opts = {
        f'{r["id"]}: dataset={r.get("dataset_id")}, strategy={r.get("strategy_id")}, status={r.get("status")}': r
        for r in bt_list
        if "id" in r
    }

    col_tv, col_bt = st.columns(2)
    with col_tv:
        tv_sel = st.selectbox("TV reference", options=list(tv_opts.keys()), key="tv_comp_tv_ref")
    with col_bt:
        bt_sel = st.selectbox("App backtest run", options=list(bt_opts.keys()), key="tv_comp_bt_run")

    tv_ref = tv_opts[tv_sel]
    bt_run = bt_opts[bt_sel]

    st.markdown("### 選択中の情報")
    st.info("比較前チェック: strategy_id / dataset_id / start_date / end_date が一致しているか")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**TV reference**")
        st.write("id:", tv_ref.get("id"))
        st.write("strategy_id:", tv_ref.get("strategy_id"))
        st.write("dataset_id:", tv_ref.get("dataset_id"))
        st.write("start_date:", tv_ref.get("start_date"))
        st.write("end_date:", tv_ref.get("end_date"))
    with c2:
        st.markdown("**Backtest run**")
        st.write("id:", bt_run.get("id"))
        st.write("strategy_id:", bt_run.get("strategy_id"))
        st.write("dataset_id:", bt_run.get("dataset_id"))
        st.write("start_date:", bt_run.get("start_date") or "-")
        st.write("end_date:", bt_run.get("end_date") or "-")
        st.write("status:", bt_run.get("status"))

    if bt_run.get("status") != "success":
        st.warning("選択した backtest run は success ではありません。比較は結果取得できる範囲で行います。")

    if st.button("比較を実行"):
        run_id = bt_run.get("id")
        if run_id is None:
            st.error("backtest run id が不正です")
            return

        # result 取得
        r_status, r_data = fetch_json("GET", f"/backtests/{run_id}/result")
        if r_status != 200 or not isinstance(r_data, dict):
            st.error(f"Backtest result 取得に失敗しました: status={r_status}")
            if isinstance(r_data, (dict, list)):
                st.json(r_data)
            else:
                st.write(r_data)
            return

        st.markdown("### 比較結果")
        st.caption("主判定は trade一致率 + summary主指標一致率です。net_profit / max_drawdown は参考指標です。")
        render_tv_comparison(
            tv_ref=tv_ref,
            backtest_run=bt_run,
            backtest_result=r_data,
            key_prefix=f"tv_comp_{tv_ref.get('id')}_{run_id}",
        )

