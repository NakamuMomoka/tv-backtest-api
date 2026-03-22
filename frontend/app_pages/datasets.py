from __future__ import annotations

from typing import Any

import streamlit as st

from app_utils.api import fetch, fetch_json, load_datasets


def render() -> None:
    st.title("データセット")
    st.caption("この画面では検証用CSVを管理します。まず一覧確認、次に必要に応じて同期/アップロードしてください。")

    # 一覧
    st.subheader("1) 一覧")
    datasets = load_datasets()
    if datasets:
        with st.container(border=True):
            h_id, h_name, h_symbol, h_tf, h_rows, h_type, h_action = st.columns([1, 2, 2, 1, 1, 1, 1])
            h_id.markdown("**id**")
            h_name.markdown("**name**")
            h_symbol.markdown("**symbol**")
            h_tf.markdown("**timeframe**")
            h_rows.markdown("**rows_count**")
            h_type.markdown("**type**")
            h_action.markdown("**action**")
            st.divider()

            for idx, d in enumerate(datasets):
                did = d.get("id")
                source_type = d.get("source_type") or ("builtin" if d.get("is_builtin") else "uploaded")
                c_id, c_name, c_symbol, c_tf, c_rows, c_type, c_action = st.columns([1, 2, 2, 1, 1, 1, 1])
                c_id.write(str(did))
                c_name.write(str(d.get("name", "")))
                c_symbol.write(str(d.get("symbol") or ""))
                c_tf.write(str(d.get("timeframe") or ""))
                c_rows.write(str(d.get("rows_count") or ""))
                c_type.write(str(source_type))
                if did is not None:
                    if c_action.button("削除", key=f"delete_dataset_{did}"):
                        status, resp = fetch_json("DELETE", f"/datasets/{did}")
                        if status == 200:
                            st.success("データセットを削除しました")
                            st.session_state.pop("datasets", None)
                            st.rerun()
                        else:
                            st.error(f"削除に失敗しました (status={status})")
                            if isinstance(resp, (dict, list)):
                                st.json(resp)
                            else:
                                st.write(resp)
                if idx != len(datasets) - 1:
                    st.divider()
    else:
        st.write("データがありません")

    col_reload, col_sync = st.columns(2)
    with col_reload:
        if st.button("一覧を更新"):
            status, data = fetch_json("GET", "/datasets")
            if status == 200 and isinstance(data, list):
                st.session_state.datasets = data
            else:
                st.warning(f"Failed to load datasets: {data}")
    with col_sync:
        st.markdown("##### Builtin データセット")
        if st.button("Builtin を同期"):
            status, data = fetch_json("POST", "/datasets/builtins/sync")
            st.write("Status:", status)
            if isinstance(data, (dict, list)):
                st.json(data)
            else:
                st.write(data)
            st.session_state.pop("datasets", None)

    # アップロード
    st.markdown("### 2) CSVアップロード")
    st.caption("登録後は一覧を自動更新します。symbol/timeframe は任意です。")
    up_name = st.text_input("データ名", key="upload_dataset_name")
    up_symbol = st.text_input("シンボル", key="upload_dataset_symbol")
    up_timeframe = st.text_input("時間足", key="upload_dataset_timeframe")
    up_file = st.file_uploader("CSVファイル", type=["csv"], key="upload_dataset_file")
    if st.button("データセットを登録"):
        if not up_name or not up_file:
            st.error("Dataset name and CSV file are required.")
        else:
            files: dict[str, Any] = {
                "file": (up_file.name, up_file.getvalue(), "text/csv"),
            }
            data = {
                "name": up_name,
                "symbol": up_symbol,
                "timeframe": up_timeframe,
            }
            status, resp = fetch("POST", "/datasets", files=files, data=data)
            st.write("Status:", status)
            if isinstance(resp, (dict, list)):
                st.json(resp)
            else:
                st.write(resp)
            # キャッシュをクリアして次回 load_datasets で再取得させる
            st.session_state.pop("datasets", None)

