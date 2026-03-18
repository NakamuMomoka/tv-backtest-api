from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

try:  # matplotlib が無い環境でも動くようにする
    import matplotlib  # noqa: F401

    _HAS_MPL = True
except ImportError:  # pragma: no cover - ランタイム環境依存
    _HAS_MPL = False


def build_trials_dataframe(trials: list[dict[str, Any]]) -> pd.DataFrame:
    """trials 配列から DataFrame を構築し、主要メトリクス列を展開する。"""
    df = pd.DataFrame(trials)
    if "metrics" in df.columns:
        def _metric_get(m: Any, key: str) -> Any:
            if isinstance(m, dict):
                return m.get(key)
            return None

        def _total_trades(m: Any) -> Any:
            if not isinstance(m, dict):
                return None
            v = m.get("total_trades")
            if isinstance(v, (int, float, str)):
                return v
            v2 = m.get("trades")
            if isinstance(v2, (int, float, str)):
                return v2
            if isinstance(v2, list):
                return len(v2)
            return None

        df["profit_factor"] = df["metrics"].apply(lambda m: _metric_get(m, "profit_factor"))
        df["net_profit"] = df["metrics"].apply(lambda m: _metric_get(m, "net_profit"))
        df["win_rate"] = df["metrics"].apply(lambda m: _metric_get(m, "win_rate"))
        df["total_trades"] = df["metrics"].apply(_total_trades)

        # profit_factor が欠けている行について、gross_profit / gross_loss から行単位で算出を試みる
        gross_profit = df["metrics"].apply(lambda m: _metric_get(m, "gross_profit"))
        gross_loss = df["metrics"].apply(lambda m: _metric_get(m, "gross_loss"))
        gp = pd.to_numeric(gross_profit, errors="coerce")
        gl = pd.to_numeric(gross_loss, errors="coerce")
        with pd.option_context("mode.use_inf_as_na", True):
            pf_from_gross = gp / gl.where(gl > 0)
        if "profit_factor" in df.columns:
            df["profit_factor"] = pd.to_numeric(df["profit_factor"], errors="coerce").combine_first(
                pf_from_gross,
            )
        else:
            df["profit_factor"] = pf_from_gross

    # 数値列を to_numeric で正規化
    for col in ["profit_factor", "net_profit", "win_rate", "total_trades", "score"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


def build_trials_dataframe_from_jobs(
    jobs: list[dict[str, Any]],
    *,
    strategy_id: int | None = None,
    dataset_id: int | None = None,
    objective_metric: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    """複数 Optimization ジョブの trials をまとめて DataFrame 化する."""
    rows: list[dict[str, Any]] = []
    for job in jobs:
        if job.get("status") != "success":
            continue
        if strategy_id is not None and job.get("strategy_id") != strategy_id:
            continue
        if dataset_id is not None and job.get("dataset_id") != dataset_id:
            continue
        if objective_metric is not None and job.get("objective_metric") != objective_metric:
            continue
        # start_date / end_date は run 情報から拾えるなら条件に使う
        if start_date is not None and job.get("start_date") and job.get("start_date") != start_date:
            continue
        if end_date is not None and job.get("end_date") and job.get("end_date") != end_date:
            continue

        job_id = job.get("id")
        s_id = job.get("strategy_id")
        d_id = job.get("dataset_id")
        obj = job.get("objective_metric")

        # result 側 trials を期待する呼び出し側で展開して渡す想定
        trials = job.get("trials") or []
        for t in trials:
            row = dict(t)  # params / metrics / score など
            row["job_id"] = job_id
            row["strategy_id"] = s_id
            row["dataset_id"] = d_id
            row["objective_metric"] = obj
            # 将来の再集約用に params_signature を付与しておく
            p = t.get("params") or {}
            try:
                import json as _json

                row["params_signature"] = _json.dumps(p, sort_keys=True, ensure_ascii=False)
            except Exception:
                row["params_signature"] = None
            rows.append(row)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    return build_trials_dataframe(df.to_dict(orient="records"))


def render_trials_ranking(
    trials: list[dict[str, Any]],
    *,
    key_prefix: str,
) -> pd.DataFrame | None:
    """トライアル一覧のフィルタ・並び替え UI と DataFrame 表示.

    戻り値は min_trades フィルタ後の DataFrame（分析用）。条件に合う行が無ければ None。
    """
    if not trials:
        return None

    st.write("トライアル一覧（フィルタ・並び替え）")
    col_sort, col_min_trades = st.columns(2)
    with col_sort:
        sort_by = st.selectbox(
            "並び順 (降順)",
            options=["profit_factor", "total_trades", "net_profit", "win_rate", "score"],
            index=0,
            key=f"{key_prefix}_sort_by",
        )
    with col_min_trades:
        min_trades = st.number_input(
            "最低トレード回数 (min_trades)",
            min_value=0,
            value=30,
            step=1,
            key=f"{key_prefix}_min_trades",
        )

    df_trials = build_trials_dataframe(trials)

    df_filtered = df_trials
    if "total_trades" in df_trials.columns:
        df_filtered = df_trials[df_trials["total_trades"].fillna(0) >= int(min_trades)]

    if df_filtered.empty:
        st.info("条件に合う trial がありません。")
        return None

    if sort_by in df_filtered.columns:
        df_sorted = df_filtered.sort_values(
            sort_by,
            ascending=False,
            na_position="last",
        )
    else:
        df_sorted = df_filtered

    df_top = df_sorted.head(10)
    display_cols = [
        "job_id",
        "dataset_id",
        "objective_metric",
        "params",
        "profit_factor",
        "total_trades",
        "net_profit",
        "win_rate",
        "score",
    ]
    cols = [c for c in display_cols if c in df_top.columns]

    if not _HAS_MPL:
        st.dataframe(df_top[cols], use_container_width=True)
    else:
        # スタイリング
        styler = df_top[cols].style
        if "profit_factor" in cols:
            styler = styler.background_gradient(subset=["profit_factor"], cmap="Greens")
        if "net_profit" in cols:
            styler = styler.background_gradient(subset=["net_profit"], cmap="Blues")
        if "total_trades" in cols:
            styler = styler.background_gradient(subset=["total_trades"], cmap="Purples")
        if "win_rate" in cols:
            styler = styler.background_gradient(subset=["win_rate"], cmap="Greens")
        if "score" in cols:
            styler = styler.background_gradient(subset=["score"], cmap="Oranges")

        st.dataframe(styler, use_container_width=True)

    return df_filtered


def render_trials_analysis(
    df_filtered: pd.DataFrame,
    *,
    key_prefix: str,
) -> None:
    """PF/トレード数フィルタ後の DataFrame に対する感度・相関・分布分析 UI."""
    if df_filtered.empty:
        return

    # params 列を展開して数値パラメータを抽出
    if "params" not in df_filtered.columns:
        return
    params_df = pd.json_normalize(df_filtered["params"])
    # bool も 0/1 として扱う
    for col in params_df.select_dtypes(include=["bool"]).columns:
        params_df[col] = params_df[col].astype(int)
    numeric_params = params_df.select_dtypes(include=["number"]).columns.tolist()
    if not numeric_params:
        return

    df_wide = pd.concat([df_filtered.reset_index(drop=True), params_df.reset_index(drop=True)], axis=1)

    st.markdown("###### パラメータ感度")
    metric_options = ["profit_factor", "net_profit", "total_trades", "win_rate", "score"]
    metric_cols = [m for m in metric_options if m in df_wide.columns]
    if metric_cols:
        for p in numeric_params:
            sub = df_wide[[p] + metric_cols].copy()
            grp = sub.groupby(p)
            agg_dict: dict[str, list[str]] = {}
            for m in metric_cols:
                if m == "total_trades":
                    agg_dict[m] = ["mean"]
                else:
                    agg_dict[m] = ["mean", "median"]
            agg = grp.agg(agg_dict)
            agg["count"] = grp.size()
            st.write(f"パラメータ `{p}` の感度")
            if not _HAS_MPL:
                st.dataframe(agg, use_container_width=True)
            else:
                numeric_cols = agg.select_dtypes(include=["number"]).columns
                styler = agg.style.background_gradient(subset=numeric_cols, cmap="Blues")
                st.dataframe(styler, use_container_width=True)

    st.markdown("###### 2パラメータヒートマップ")
    col_x, col_y, col_metric, col_agg = st.columns(4)
    with col_x:
        param_x = st.selectbox(
            "X軸パラメータ",
            options=numeric_params,
            key=f"{key_prefix}_heat_x",
        )
    with col_y:
        param_y = st.selectbox(
            "Y軸パラメータ",
            options=numeric_params,
            index=min(1, len(numeric_params) - 1),
            key=f"{key_prefix}_heat_y",
        )
    with col_metric:
        metric_for_heat = st.selectbox(
            "指標",
            options=[m for m in ["profit_factor", "net_profit", "total_trades", "score"] if m in df_wide.columns],
            key=f"{key_prefix}_heat_metric",
        )
    with col_agg:
        aggfunc_name = st.selectbox(
            "集計方法",
            options=["mean", "median"],
            key=f"{key_prefix}_heat_agg",
        )

    try:
        df_pivot = df_wide.pivot_table(
            index=param_x,
            columns=param_y,
            values=metric_for_heat,
            aggfunc=aggfunc_name,
        )
        if not _HAS_MPL:
            st.dataframe(df_pivot, use_container_width=True)
        else:
            styler_pivot = df_pivot.style.background_gradient(cmap="viridis")
            st.dataframe(styler_pivot, use_container_width=True)
    except Exception:  # noqa: BLE001
        st.info("ヒートマップを生成できませんでした。サンプル数やパラメータ選択を確認してください。")

    st.markdown("###### 相関分析（Spearman）")
    metric_cols_for_corr = [
        m for m in ["profit_factor", "net_profit", "total_trades", "win_rate", "score"]
        if m in df_wide.columns
    ]
    if metric_cols_for_corr and numeric_params:
        sub_corr = df_wide[numeric_params + metric_cols_for_corr].select_dtypes(include=["number"])
        corr = sub_corr.corr(method="spearman")
        corr_rows = [c for c in numeric_params if c in corr.index]
        corr_cols = [c for c in metric_cols_for_corr if c in corr.columns]
        if corr_rows and corr_cols:
            corr_view = corr.loc[corr_rows, corr_cols]
            if not _HAS_MPL:
                st.dataframe(corr_view, use_container_width=True)
            else:
                styler_corr = corr_view.style.background_gradient(
                    cmap="coolwarm",
                    vmin=-1,
                    vmax=1,
                )
                st.dataframe(styler_corr, use_container_width=True)
        else:
            st.info("相関分析に使える列がありません。")
    else:
        st.info("相関分析に使える列がありません。")

    st.markdown("###### 上位候補の分布")
    top_n = st.number_input(
        "上位何件を見るか (profit_factor 順)",
        min_value=1,
        value=50,
        step=1,
        key=f"{key_prefix}_top_n",
    )
    df_top = df_wide.sort_values("profit_factor", ascending=False).head(int(top_n))
    for p in numeric_params:
        vc = df_top[p].value_counts().to_frame(name="count")
        st.write(f"パラメータ `{p}` の分布（上位 {int(top_n)} 件）")
        if not _HAS_MPL:
            st.dataframe(vc, use_container_width=True)
        else:
            styler_vc = vc.style.background_gradient(subset=["count"], cmap="Greens")
            st.dataframe(styler_vc, use_container_width=True)

