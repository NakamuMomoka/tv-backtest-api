from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from app_utils.api import fetch_json
from app_utils.trials_analysis import (
    build_trials_dataframe_from_jobs,
    render_trials_analysis,
    render_trials_ranking,
)


def render() -> None:
    st.title("Optimization ジョブ一覧")

    col_filters = st.container()
    with col_filters:
        col1, col2, col3 = st.columns(3)
        with col1:
            status_filter = st.selectbox(
                "Status フィルタ",
                options=["all", "pending", "running", "success", "failed"],
                index=0,
                key="opt_jobs_status_filter",
            )
        with col2:
            mode_filter = st.selectbox(
                "search_mode フィルタ",
                options=["all", "grid", "random"],
                index=0,
                key="opt_jobs_mode_filter",
            )
        with col3:
            limit = st.number_input(
                "最大件数 (limit)",
                min_value=1,
                max_value=500,
                value=50,
                step=1,
                key="opt_jobs_limit",
            )

    params: dict[str, Any] = {"limit": int(limit)}
    if status_filter != "all":
        params["status"] = status_filter
    if mode_filter != "all":
        params["search_mode"] = mode_filter

    if st.button("ジョブ一覧を再読み込み"):
        pass  # Streamlit の再実行トリガ

    list_status, list_data = fetch_json("GET", "/optimizations", params=params)
    if list_status == 200 and isinstance(list_data, list):
        if list_data:
            df_jobs = pd.DataFrame(list_data)
            display_cols = [
                "id",
                "created_at",
                "status",
                "dataset_id",
                "strategy_id",
                "search_mode",
                "objective_metric",
                "requested_trials",
                "executed_trials",
                "best_score",
                "message",
                "error_message",
            ]
            df_show = df_jobs[[c for c in display_cols if c in df_jobs.columns]]
            st.subheader("Optimization ジョブ一覧")
            st.dataframe(df_show, use_container_width=True)

            job_ids = df_show["id"].tolist()
            selected_job = st.selectbox(
                "詳細を表示するジョブ ID",
                options=job_ids,
                key="opt_jobs_selected_id",
            )

            # 分析対象モード
            st.markdown("#### 分析対象モード")
            mode = st.radio(
                "分析対象",
                options=["job単位", "strategy単位"],
                index=0,
                key="opt_jobs_analysis_mode",
                horizontal=True,
            )

            if mode == "job単位" and selected_job:
                st.markdown("##### ジョブ詳細")
                d_status, d_data = fetch_json("GET", f"/optimizations/{selected_job}")
                if d_status == 200 and isinstance(d_data, dict):
                    st.json(d_data)

                    st.write("search_mode:", d_data.get("search_mode", "grid"))
                    st.write("status:", d_data.get("status"))
                    if d_data.get("message"):
                        st.info(str(d_data.get("message")))
                    if d_data.get("error_message"):
                        st.error(str(d_data.get("error_message")))

                    if d_data.get("status") == "success":
                        r_status, r_data = fetch_json(
                            "GET",
                            f"/optimizations/{selected_job}/result",
                        )
                        if r_status == 200 and isinstance(r_data, dict):
                            st.write("best_score:", r_data.get("best_score"))
                            st.write("best_params:")
                            st.json(r_data.get("best_params") or {})

                            trials = r_data.get("trials") or []
                            if trials:
                                df_for_analysis = render_trials_ranking(
                                    trials,
                                    key_prefix="opt_jobs_trials",
                                )
                                if df_for_analysis is not None:
                                    render_trials_analysis(
                                        df_for_analysis,
                                        key_prefix="opt_jobs_trials",
                                    )
                    elif d_data.get("status") in ("pending", "running"):
                        st.info("このジョブはまだ完了していません。")
                else:
                    st.error(f"ジョブ詳細取得に失敗しました: {d_status}")

            # strategy単位分析
            if mode == "strategy単位":
                st.markdown("##### Strategy 単位分析")
                # 対象 strategy を選択
                strat_ids = sorted(df_show["strategy_id"].dropna().unique().tolist())
                if not strat_ids:
                    st.info("Strategy 単位分析に利用できるジョブがありません。")
                    return
                strat_id = st.selectbox(
                    "Strategy ID を選択",
                    options=strat_ids,
                    key="opt_jobs_strategy_analysis_id",
                )
                # 追加フィルタ（任意）
                ds_ids = sorted(df_show["dataset_id"].dropna().unique().tolist())
                ds_filter = st.selectbox(
                    "Dataset ID (任意)",
                    options=["all"] + ds_ids,
                    key="opt_jobs_strategy_dataset_filter",
                )
                obj_metrics = sorted(
                    [o for o in df_show["objective_metric"].dropna().unique().tolist() if o],
                )
                obj_filter = st.selectbox(
                    "objective_metric (任意)",
                    options=["all"] + obj_metrics,
                    key="opt_jobs_strategy_obj_filter",
                )

                target_jobs: list[dict[str, Any]] = []
                for job in list_data:
                    if job.get("status") != "success":
                        continue
                    if job.get("strategy_id") != strat_id:
                        continue
                    if ds_filter != "all" and job.get("dataset_id") != ds_filter:
                        continue
                    if obj_filter != "all" and job.get("objective_metric") != obj_filter:
                        continue
                    target_jobs.append(job)

                if not target_jobs:
                    st.info("指定された条件に一致する成功ジョブがありません。")
                    return

                # 各ジョブの trials を個別に取得して jobs 構造に詰める
                jobs_with_trials: list[dict[str, Any]] = []
                for job in target_jobs:
                    jid = job.get("id")
                    r_status, r_data = fetch_json("GET", f"/optimizations/{jid}/result")
                    if r_status == 200 and isinstance(r_data, dict):
                        job_copy = dict(job)
                        job_copy["trials"] = r_data.get("trials") or []
                        jobs_with_trials.append(job_copy)

                if not jobs_with_trials:
                    st.info("対象ジョブに利用可能な trials がありません。")
                    return

                df_all = build_trials_dataframe_from_jobs(
                    jobs_with_trials,
                    strategy_id=strat_id,
                    dataset_id=None if ds_filter == "all" else ds_filter,
                    objective_metric=None if obj_filter == "all" else obj_filter,
                )
                if df_all.empty:
                    st.info("条件に合う trial がありません。")
                    return

                st.write(f"対象ジョブ数: {len(jobs_with_trials)}")
                st.write(f"対象トライアル数: {len(df_all)}")

                # trials_analysis は trials:list を受けるので、records に戻して利用
                trials_for_ui = df_all.to_dict(orient="records")
                df_for_analysis = render_trials_ranking(
                    trials_for_ui,
                    key_prefix="opt_jobs_strategy",
                )
                if df_for_analysis is not None:
                    render_trials_analysis(
                        df_for_analysis,
                        key_prefix="opt_jobs_strategy",
                    )
        else:
            st.info("現在登録されている Optimization ジョブはありません。")
    else:
        st.error(f"ジョブ一覧取得に失敗しました: {list_status}")

