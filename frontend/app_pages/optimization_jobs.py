from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from app_utils.api import fetch_json
from app_utils.optimization_ui import (
    render_optimization_progress_banner,
    render_timing_summary_safe,
    safe_best_params,
)
from app_utils.trials_analysis import (
    build_trials_dataframe_from_jobs,
    render_trials_analysis,
    render_trials_ranking,
)


def render() -> None:
    st.title("Optimization ジョブ一覧")
    st.caption(
        "この画面では、最適化ジョブの進捗確認と結果分析を行います。"
        " まず一覧で status を確認し、次に詳細・trial分析へ進んでください。"
    )

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
                options=["all", "grid", "random", "guided_random"],
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
            display_cols_core = [
                "id",
                "status",
                "search_mode",
                "requested_trials",
                "executed_trials",
                "best_score",
                "last_progress_at",
            ]
            display_cols_batch = [
                "trials_per_set",
                "set_count",
                "completed_sets",
                "current_set_index",
                "total_planned_trials",
            ]
            show_batch_cols = st.checkbox(
                "セット分割の詳細列を表示",
                value=False,
                key="opt_jobs_show_batch_cols",
                help="一覧を簡潔に保つため、デフォルトは主要列のみです。",
            )
            use_cols = list(display_cols_core)
            if show_batch_cols:
                use_cols = display_cols_core + [
                    c for c in display_cols_batch if c not in display_cols_core
                ]
            use_cols += [
                c
                for c in ("dataset_id", "strategy_id", "objective_metric", "created_at", "message", "error_message")
                if c not in use_cols
            ]
            df_show = df_jobs[[c for c in use_cols if c in df_jobs.columns]]
            st.subheader("Optimization ジョブ一覧")
            st.dataframe(df_show, use_container_width=True)
            st.caption(
                "見る順番: status → executed / requested → best_score。"
                " セット分割ジョブは「詳細列」で trials_per_set / completed_sets を表示、または下の expander。"
            )

            def _batch_progress_hint(row: dict[str, Any]) -> str:
                tps = row.get("trials_per_set")
                sc = row.get("set_count")
                if tps is None or sc is None:
                    return ""
                done = row.get("completed_sets")
                cur = row.get("current_set_index")
                tot = row.get("total_planned_trials") or (int(tps) * int(sc))
                ex = row.get("executed_trials")
                bs = row.get("best_score")
                return (
                    f"進捗: {done}/{sc} セット完了 | trial: {ex}/{tot} | "
                    f"現在の best_score: {bs}"
                )

            hints = []
            for _, row in df_show.iterrows():
                r = row.to_dict()
                h = _batch_progress_hint(r)
                if h:
                    hints.append(f"ID {r.get('id')}: {h}")
            if hints:
                with st.expander("セット分割ジョブの進捗サマリ", expanded=False):
                    for line in hints:
                        st.caption(line)

            job_ids = df_show["id"].tolist()
            selected_job = st.selectbox(
                "詳細を表示するジョブ ID",
                options=job_ids,
                key="opt_jobs_selected_id",
            )

            # 分析対象モード
            st.markdown("#### 分析対象モード")
            st.caption("job単位: 単一ジョブの結果を深掘り / strategy単位: 複数ジョブを横断分析")
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
                r_data: dict[str, Any] | None = None
                if d_status == 200 and isinstance(d_data, dict):
                    if d_data.get("status") != "failed":
                        r_status, r_data = fetch_json(
                            "GET",
                            f"/optimizations/{selected_job}/result",
                        )
                        if r_status != 200:
                            r_data = None

                    # 上部: 進捗サマリ（途中 JSON でも安全）
                    render_optimization_progress_banner(d_data, r_data)

                    c1, c2, c3 = st.columns(3)
                    with c1:
                        st.metric("status", str(d_data.get("status", "-")))
                    with c2:
                        st.metric(
                            "executed / requested",
                            f'{d_data.get("executed_trials", "-")} / {d_data.get("requested_trials", "-")}',
                        )
                    with c3:
                        st.metric("best_score", d_data.get("best_score") if d_data.get("best_score") is not None else "-")

                    if d_data.get("trials_per_set") and d_data.get("set_count"):
                        st.caption(
                            f"セット分割: **{d_data.get('trials_per_set')} × {d_data.get('set_count')}** "
                            f"・ 予定 trial {d_data.get('total_planned_trials')} "
                            f"・ 完了セット {d_data.get('completed_sets')} / {d_data.get('set_count')}"
                        )

                    if isinstance(r_data, dict):
                        render_timing_summary_safe(r_data)

                    if d_data.get("message"):
                        st.info(str(d_data.get("message")))
                    if d_data.get("error_message"):
                        st.error(str(d_data.get("error_message")))

                    with st.expander("生データ（run / result JSON）", expanded=False):
                        st.markdown("**GET /optimizations/{id}**")
                        st.json(d_data)
                        if r_data is not None:
                            st.markdown("**GET /optimizations/{id}/result**")
                            st.json(r_data)

                    if isinstance(r_data, dict):
                        bp = safe_best_params(r_data)
                        st.write("best_score:", r_data.get("best_score"))
                        st.write("best_params（空の場合はまだ有効 trial なし）:")
                        st.json(bp)

                        trials = r_data.get("trials") or []
                        if trials:
                            st.info("ランキングは PF 重視で確認し、次に感度・相関・分布を見て安定帯を探します。")
                            df_for_analysis = render_trials_ranking(
                                trials,
                                key_prefix="opt_jobs_trials",
                            )
                            if df_for_analysis is not None:
                                render_trials_analysis(
                                    df_for_analysis,
                                    key_prefix="opt_jobs_trials",
                                )
                        elif d_data.get("status") in ("running", "pending"):
                            st.caption("trials がまだ空、または結果ファイル未作成です。しばらく待って再読み込みしてください。")

                    elif d_data.get("status") in ("pending", "running"):
                        st.info(
                            "このジョブは実行中です。途中結果ファイルがまだ無い場合は、"
                            "しばらくしてから再読み込みしてください。"
                        )
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
                st.caption("strategy単位では job_id / dataset_id / objective_metric も含めて比較できます。")

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
        if isinstance(list_data, (dict, list)):
            st.json(list_data)
        else:
            st.write(list_data)

