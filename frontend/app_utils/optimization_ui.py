"""最適化ジョブの途中結果・セット分割表示用ヘルパー（API の partial JSON でも壊れない）。"""

from __future__ import annotations

from typing import Any

import streamlit as st


def is_partial_result(result: dict[str, Any] | None) -> bool:
    if not isinstance(result, dict):
        return False
    return bool(result.get("partial"))


def render_optimization_progress_banner(
    run_data: dict[str, Any],
    result_data: dict[str, Any] | None,
) -> None:
    """running / pending / partial 時の説明とセット進捗を表示。"""
    status = str(run_data.get("status") or "")
    partial = is_partial_result(result_data)

    if status in ("running", "pending") or partial:
        lines: list[str] = []
        if partial or status in ("running", "pending"):
            lines.append("**途中経過**（最終完了前のスナップショットです。指標は更新され続けます）")
        if partial:
            lines.append("- result JSON の `partial: true` が付いている場合、次のセットで上書き保存されます。")

        tps = run_data.get("trials_per_set")
        sc = run_data.get("set_count")
        if tps is not None and sc is not None:
            tot = run_data.get("total_planned_trials")
            if tot is None:
                try:
                    tot = int(tps) * int(sc)
                except (TypeError, ValueError):
                    tot = "-"
            done = run_data.get("completed_sets")
            ex = run_data.get("executed_trials")
            lines.append(
                f"- **セット分割**: {tps} × {sc}（予定 trial 数: {tot}）"
            )
            lines.append(
                f"- **進捗（DB）**: 完了セット {done} / {sc} ・ 実行済み trial {ex} / {tot}"
            )
            if run_data.get("last_progress_at"):
                lines.append(f"- **最終更新**: `{run_data.get('last_progress_at')}`")

        batch = (result_data or {}).get("batch_progress") if isinstance(result_data, dict) else None
        if isinstance(batch, dict):
            sr = batch.get("stopped_reason")
            sh = batch.get("shortfall_reason")
            if sr or sh:
                lines.append(f"- **打ち切り**: {sr or '-'} / **不足理由**: {sh or '-'}")

        st.info("\n".join(lines))

    # stopped_reason / shortfall_reason（最終 JSON にも載る）
    if isinstance(result_data, dict):
        sr = result_data.get("stopped_reason")
        sh = result_data.get("shortfall_reason")
        if sr or sh:
            st.warning(f"**stopped_reason**: {sr or '-'}  \n**shortfall_reason**: {sh or '-'}")


def render_timing_summary_safe(result_data: dict[str, Any] | None) -> None:
    """timing_summary が空・None でも安全に表示。"""
    if not isinstance(result_data, dict):
        return
    ts = result_data.get("timing_summary")
    if ts is None:
        st.caption("timing_summary: （まだ集計なし、または trial 0 件）")
        return
    if not isinstance(ts, dict):
        st.caption(f"timing_summary: {ts!r}")
        return
    if not ts:
        st.caption("timing_summary: {}")
        return
    with st.expander("timing_summary（途中でも表示可能）", expanded=False):
        st.json(ts)


def safe_best_params(result_data: dict[str, Any] | None) -> dict[str, Any]:
    bp = (result_data or {}).get("best_params") if isinstance(result_data, dict) else None
    return bp if isinstance(bp, dict) else {}


def can_rerun_backtest_from_result(
    run_data: dict[str, Any],
    result_data: dict[str, Any] | None,
) -> bool:
    """途中経過では再実行ボタンを出さない（空 params 防止）。"""
    if run_data.get("status") not in ("success",):
        return False
    if is_partial_result(result_data):
        return False
    params = safe_best_params(result_data)
    return bool(params)
