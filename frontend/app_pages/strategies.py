from __future__ import annotations

from typing import Any

import streamlit as st

from app_utils.api import fetch, fetch_json, load_strategies


def render() -> None:
    st.title("ストラテジー")
    st.caption("この画面ではストラテジーを管理します。Builtin同期またはPythonアップロードで登録できます。")

    # 一覧
    st.subheader("1) 一覧")
    strategies = load_strategies()
    if strategies:
        # 罫線付きに見えるよう、コンテナ+区切り線で描画
        with st.container(border=True):
            # ヘッダ
            h_id, h_name, h_desc, h_type, h_action = st.columns([1, 2, 4, 1, 1])
            h_id.markdown("**id**")
            h_name.markdown("**name**")
            h_desc.markdown("**description**")
            h_type.markdown("**type**")
            h_action.markdown("**action**")
            st.divider()

            for idx, s in enumerate(strategies):
                sid = s.get("id")
                source_type = s.get("source_type") or ("builtin" if s.get("is_builtin") else "uploaded")
                c_id, c_name, c_desc, c_type, c_action = st.columns([1, 2, 4, 1, 1])
                c_id.write(str(sid))
                c_name.write(str(s.get("name", "")))
                c_desc.write(str(s.get("description") or ""))
                c_type.write(str(source_type))
                if sid is not None:
                    if c_action.button("削除", key=f"delete_strategy_{sid}"):
                        status, resp = fetch_json("DELETE", f"/strategies/{sid}")
                        if status == 200:
                            st.success("ストラテジーを削除しました")
                            st.session_state.pop("strategies", None)
                            st.rerun()
                        else:
                            st.error(f"削除に失敗しました (status={status})")
                            if isinstance(resp, (dict, list)):
                                st.json(resp)
                            else:
                                st.write(resp)
                if idx != len(strategies) - 1:
                    st.divider()
    else:
        st.write("ストラテジーがありません")

    col_reload, col_sync = st.columns(2)
    with col_reload:
        if st.button("一覧を更新"):
            status, data = fetch_json("GET", "/strategies")
            if status == 200 and isinstance(data, list):
                st.session_state.strategies = data
            else:
                st.warning(f"Failed to load strategies: {data}")
    with col_sync:
        st.markdown("##### Builtin ストラテジー")
        if st.button("Builtin を同期"):
            status, data = fetch_json("POST", "/strategies/builtins/sync")
            st.write("Status:", status)
            if isinstance(data, (dict, list)):
                st.json(data)
            else:
                st.write(data)
            st.session_state.pop("strategies", None)

    # アップロード
    st.markdown("### 2) Pythonアップロード")
    st.caption("default_params_json は最適化/バックテスト画面の入力フォーム初期値に使われます。")
    st_name = st.text_input("ストラテジー名", key="upload_strategy_name")
    st_desc = st.text_area("説明", key="upload_strategy_desc")
    st_default_params = st.text_input(
        "デフォルトパラメータ (JSON・任意)",
        value='{"fast_window": 5, "slow_window": 20}',
        key="upload_strategy_params",
    )
    st_file = st.file_uploader(
        "Pythonファイル",
        type=["py"],
        key="upload_strategy_file",
    )
    if st.button("ストラテジーを登録"):
        if not st_name or not st_file:
            st.error("Strategy name and Python file are required.")
        else:
            files: dict[str, Any] = {
                "file": (st_file.name, st_file.getvalue(), "text/x-python"),
            }
            data = {
                "name": st_name,
                "description": st_desc,
                "default_params_json": st_default_params or "",
            }
            status, resp = fetch("POST", "/strategies", files=files, data=data)
            st.write("Status:", status)
            if isinstance(resp, (dict, list)):
                st.json(resp)
            else:
                st.write(resp)
            # キャッシュをクリアして次回 load_strategies で再取得させる
            st.session_state.pop("strategies", None)

