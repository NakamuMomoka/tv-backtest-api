from __future__ import annotations

import json
from typing import Any

import streamlit as st

from app_utils.api import fetch, fetch_json, load_datasets, load_strategies


def _load_tv_references() -> list[dict[str, Any]]:
    if "tv_references" not in st.session_state:
        status, data = fetch_json("GET", "/tv-references")
        if status == 200 and isinstance(data, list):
            st.session_state.tv_references = data
        else:
            st.session_state.tv_references = []
            st.warning(f"Failed to load tv references: {data}")
    return st.session_state.tv_references


def _summary_value(summary_json: str | None, key: str) -> Any:
    if not summary_json:
        return None
    try:
        obj = json.loads(summary_json)
        if isinstance(obj, dict):
            return obj.get(key)
    except Exception:  # noqa: BLE001
        return None
    return None


def render() -> None:
    st.title("TV基準結果 (TradingView reference)")
    st.caption("この画面では TradingView の基準結果を管理します。比較に使うため、strategy/dataset/期間を揃えて登録してください。")

    datasets = load_datasets()
    strategies = load_strategies()
    dataset_name_by_id = {d["id"]: d.get("name") for d in datasets if "id" in d}
    strategy_name_by_id = {s["id"]: s.get("name") for s in strategies if "id" in s}

    col_reload, col_sync = st.columns(2)
    with col_reload:
        if st.button("Reload TV References"):
            st.session_state.pop("tv_references", None)
    with col_sync:
        st.markdown("##### Builtin 同期")
        if st.button("Builtin を同期"):
            status, data = fetch_json("POST", "/tv-references/builtins/sync")
            st.write("Status:", status)
            if isinstance(data, (dict, list)):
                st.json(data)
            else:
                st.write(data)
            st.session_state.pop("tv_references", None)

    st.subheader("1) 一覧")
    refs = _load_tv_references()
    if refs:
        with st.container(border=True):
            h_id, h_name, h_st, h_ds, h_sd, h_ed, h_tt, h_pf, h_type, h_action = st.columns(
                [1, 2, 2, 2, 1, 1, 1, 1, 1, 1],
            )
            h_id.markdown("**id**")
            h_name.markdown("**name**")
            h_st.markdown("**strategy**")
            h_ds.markdown("**dataset**")
            h_sd.markdown("**start**")
            h_ed.markdown("**end**")
            h_tt.markdown("**total_trades**")
            h_pf.markdown("**profit_factor**")
            h_type.markdown("**type**")
            h_action.markdown("**action**")
            st.divider()

            for idx, r in enumerate(refs):
                rid = r.get("id")
                strategy_id = r.get("strategy_id")
                dataset_id = r.get("dataset_id")
                source_type = r.get("source_type") or ("builtin" if r.get("is_builtin") else "uploaded")

                c_id, c_name, c_st, c_ds, c_sd, c_ed, c_tt, c_pf, c_type, c_action = st.columns(
                    [1, 2, 2, 2, 1, 1, 1, 1, 1, 1],
                )
                c_id.write(str(rid))
                c_name.write(str(r.get("name") or ""))
                c_st.write(str(strategy_name_by_id.get(strategy_id) or strategy_id or ""))
                c_ds.write(str(dataset_name_by_id.get(dataset_id) or dataset_id or ""))
                c_sd.write(str(r.get("start_date") or ""))
                c_ed.write(str(r.get("end_date") or ""))
                c_tt.write(str(_summary_value(r.get("summary_json"), "total_trades") or ""))
                c_pf.write(str(_summary_value(r.get("summary_json"), "profit_factor") or ""))
                c_type.write(str(source_type))

                if rid is not None and c_action.button("削除", key=f"delete_tv_reference_{rid}"):
                    d_status, d_resp = fetch_json("DELETE", f"/tv-references/{rid}")
                    if d_status == 200:
                        st.success("TV基準結果を削除しました")
                        st.session_state.pop("tv_references", None)
                        st.rerun()
                    else:
                        st.error(f"削除に失敗しました (status={d_status})")
                        if isinstance(d_resp, (dict, list)):
                            st.json(d_resp)
                        else:
                            st.write(d_resp)

                if idx != len(refs) - 1:
                    st.divider()
    else:
        st.write("TV基準結果がありません")

    st.subheader("2) 手動登録")
    st.caption("TradingView の結果を基準データとして登録します。summary は入力値を固定で保存します。")

    ds_opts = {f'{d["id"]}: {d.get("name")}': d["id"] for d in datasets}
    st_opts = {f'{s["id"]}: {s.get("name")}': s["id"] for s in strategies}

    col1, col2 = st.columns(2)
    with col1:
        name = st.text_input("name", value="TV reference", key="tvref_name")
        strategy_sel = st.selectbox("strategy", options=list(st_opts.keys()), key="tvref_strategy") if st_opts else None
        dataset_sel = st.selectbox("dataset", options=list(ds_opts.keys()), key="tvref_dataset") if ds_opts else None
        start_date = st.text_input("start_date (YYYY-MM-DD)", value="", key="tvref_start_date")
        end_date = st.text_input("end_date (YYYY-MM-DD)", value="", key="tvref_end_date")
        params_json = st.text_area("params_json (JSON)", value="{}", height=120, key="tvref_params_json")
        notes = st.text_area("notes", value="", height=80, key="tvref_notes")

    with col2:
        net_profit = st.number_input("net_profit", value=0.0, step=0.1, key="tvref_net_profit")
        max_drawdown = st.number_input("max_drawdown", value=0.0, step=0.001, key="tvref_max_drawdown")
        total_trades = st.number_input("total_trades", min_value=0, value=0, step=1, key="tvref_total_trades")
        win_rate = st.number_input("win_rate", value=0.0, step=0.001, key="tvref_win_rate")
        profit_factor = st.number_input("profit_factor", value=0.0, step=0.01, key="tvref_profit_factor")
        trades_file = st.file_uploader("trades CSV upload", type=["csv"], key="tvref_trades_csv")

    if st.button("TV基準結果を登録"):
        if not strategy_sel or not dataset_sel:
            st.error("strategy と dataset を選択してください。")
        elif not trades_file:
            st.error("trades CSV をアップロードしてください。")
        else:
            # params_json は API 側でもバリデーションするが、UI 側でも軽く検証
            try:
                json.loads(params_json or "{}")
            except Exception as exc:  # noqa: BLE001
                st.error(f"params_json が JSON として不正です: {exc}")
                return

            files: dict[str, Any] = {
                "file": (trades_file.name, trades_file.getvalue(), "text/csv"),
            }
            data = {
                "name": name,
                "strategy_id": st_opts[strategy_sel],
                "dataset_id": ds_opts[str(dataset_sel)],
                "start_date": start_date or "",
                "end_date": end_date or "",
                "params_json": params_json or "",
                "net_profit": str(net_profit),
                "max_drawdown": str(max_drawdown),
                "total_trades": str(int(total_trades)),
                "win_rate": str(win_rate),
                "profit_factor": str(profit_factor),
                "notes": notes or "",
            }
            status, resp = fetch("POST", "/tv-references", files=files, data=data)
            st.write("Status:", status)
            if isinstance(resp, (dict, list)):
                st.json(resp)
            else:
                st.write(resp)
            if status == 200:
                st.success("TV基準結果を登録しました")
                st.session_state.pop("tv_references", None)

