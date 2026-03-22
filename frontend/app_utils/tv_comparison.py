from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

try:  # matplotlib が無い環境でも動くようにする（Styler 背景色用）
    import matplotlib  # noqa: F401

    _HAS_MPL = True
except ImportError:  # pragma: no cover
    _HAS_MPL = False


SUMMARY_KEYS = ["net_profit", "max_drawdown", "total_trades", "win_rate", "profit_factor"]
SUMMARY_CORE_KEYS = ["total_trades", "win_rate", "profit_factor"]
SUMMARY_REFERENCE_KEYS = ["net_profit", "max_drawdown"]


def _repo_root() -> Path:
    # frontend/app_utils/tv_comparison.py -> parents[2] がリポジトリルート
    return Path(__file__).resolve().parents[2]


def _to_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except Exception:  # noqa: BLE001
        return None


def _normalize_datetime_like(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _to_datetime_or_none(v: Any) -> pd.Timestamp | None:
    if v is None:
        return None
    try:
        ts = pd.to_datetime(v, errors="coerce", utc=True)
        if pd.isna(ts):
            return None
        return ts
    except Exception:  # noqa: BLE001
        return None


def _resolve_trades_csv_path(trades_csv_path: str) -> Path:
    p = Path(trades_csv_path)
    if p.is_absolute():
        return p
    return _repo_root() / p


def load_tv_reference_trades_csv(tv_ref: dict[str, Any]) -> tuple[pd.DataFrame | None, str | None]:
    path = tv_ref.get("trades_csv_path")
    if not isinstance(path, str) or not path.strip():
        return None, "trades_csv_path が空です"

    resolved = _resolve_trades_csv_path(path)
    if not resolved.is_file():
        return None, f"trades CSV が見つかりません: {resolved}"

    try:
        df = pd.read_csv(resolved)
        return df, None
    except Exception as exc:  # noqa: BLE001
        return None, f"trades CSV の読み込みに失敗しました: {exc}"


def _extract_summary(tv_ref: dict[str, Any]) -> dict[str, Any]:
    raw = tv_ref.get("summary_json")
    if isinstance(raw, dict):
        obj = raw
    elif isinstance(raw, str) and raw.strip():
        try:
            obj = json.loads(raw)
        except Exception:  # noqa: BLE001
            obj = {}
    else:
        obj = {}
    if not isinstance(obj, dict):
        obj = {}
    return {k: obj.get(k) for k in SUMMARY_KEYS}


def normalize_summary_metrics(
    tv_summary: dict[str, Any],
    app_metrics: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    """summary 比較用に TV/App 側の値を比較可能な形へ正規化する。

    - win_rate: App 側が 0〜1 比率っぽい場合は ×100
    - total_trades: int 化
    - profit_factor/max_drawdown/net_profit: float 化
    - max_drawdown 欠損: warning
    - net_profit 単位不一致疑い: warning
    """
    warnings: list[str] = []

    tv_n: dict[str, Any] = {}
    app_n: dict[str, Any] = {}

    # net_profit
    tv_np = _to_float(tv_summary.get("net_profit"))
    app_np = _to_float(app_metrics.get("net_profit"))
    tv_n["net_profit"] = tv_np
    app_n["net_profit"] = app_np
    if tv_np is not None and app_np is not None:
        if abs(app_np) > abs(tv_np) * 10:
            warnings.append("TV net_profit と App net_profit は単位不一致の可能性があります（差が極端に大きい）")

    # max_drawdown
    tv_md = _to_float(tv_summary.get("max_drawdown"))
    app_md = _to_float(app_metrics.get("max_drawdown"))
    tv_n["max_drawdown"] = tv_md
    app_n["max_drawdown"] = app_md
    if app_md is None:
        warnings.append("App max_drawdown が見つからないため、この指標は一致率平均から除外します")

    # total_trades
    def _to_int(v: Any) -> int | None:
        if v is None:
            return None
        try:
            return int(float(v))
        except Exception:  # noqa: BLE001
            return None

    tv_tt = _to_int(tv_summary.get("total_trades"))
    app_tt = _to_int(app_metrics.get("total_trades") if "total_trades" in app_metrics else app_metrics.get("trades"))
    tv_n["total_trades"] = tv_tt
    app_n["total_trades"] = app_tt

    # win_rate
    tv_wr_raw = _to_float(tv_summary.get("win_rate"))
    app_wr_raw = _to_float(app_metrics.get("win_rate"))
    tv_n["win_rate"] = tv_wr_raw
    if app_wr_raw is None:
        app_n["win_rate"] = None
    else:
        if 0 <= app_wr_raw <= 1.0:
            app_n["win_rate"] = app_wr_raw * 100.0
            warnings.append("App win_rate を 0〜1 比率と判定し、百分率へ正規化しました（×100）")
        else:
            app_n["win_rate"] = app_wr_raw
            if app_wr_raw > 100.0:
                warnings.append("App win_rate が 100 を超えています。単位/定義を確認してください")

    # profit_factor
    tv_pf = _to_float(tv_summary.get("profit_factor"))
    app_pf = _to_float(app_metrics.get("profit_factor"))
    tv_n["profit_factor"] = tv_pf
    app_n["profit_factor"] = app_pf

    return tv_n, app_n, warnings


def _match_percent_numeric(tv: float | None, app: float | None) -> float | None:
    if tv is None or app is None:
        return None
    denom = max(abs(tv), 1e-9)
    p = 100.0 * (1.0 - abs(app - tv) / denom)
    return float(max(0.0, min(100.0, p)))


def _match_percent_total_trades(tv: float | None, app: float | None) -> float | None:
    if tv is None or app is None:
        return None
    try:
        tv_i = int(tv)
        app_i = int(app)
    except Exception:  # noqa: BLE001
        return None
    if tv_i == app_i:
        return 100.0
    denom = max(abs(tv_i), 1)
    p = 100.0 * (1.0 - abs(app_i - tv_i) / denom)
    return float(max(0.0, min(100.0, p)))


def build_summary_comparison(
    tv_ref: dict[str, Any],
    app_metrics: dict[str, Any],
) -> pd.DataFrame:
    tv_raw = _extract_summary(tv_ref)
    tv_norm, app_norm, norm_warnings = normalize_summary_metrics(tv_raw, app_metrics)
    rows: list[dict[str, Any]] = []

    for k in SUMMARY_KEYS:
        tv_v_raw = tv_raw.get(k)
        app_v_raw = app_metrics.get(k)

        tv_v = tv_norm.get(k)
        app_v = app_norm.get(k)

        tv_f = _to_float(tv_v)
        app_f = _to_float(app_v)
        diff = app_f - tv_f if (tv_f is not None and app_f is not None) else None

        status = "ok"
        if tv_f is None or app_f is None:
            status = "missing"
        if k == "win_rate":
            app_wr_raw = _to_float(app_metrics.get("win_rate"))
            if app_wr_raw is not None and 0 <= app_wr_raw <= 1.0:
                status = "normalized"
        if k == "net_profit":
            tv_np = _to_float(tv_norm.get("net_profit"))
            app_np = _to_float(app_norm.get("net_profit"))
            if tv_np is not None and app_np is not None and abs(app_np) > abs(tv_np) * 10:
                status = "unit_mismatch_suspected"

        if k == "total_trades":
            mp = _match_percent_total_trades(tv_f, app_f)
        else:
            mp = _match_percent_numeric(tv_f, app_f)

        role = "core" if k in SUMMARY_CORE_KEYS else "reference"
        rows.append(
            {
                "metric": k,
                "role": role,
                "tv_value": tv_v_raw,
                "app_value": app_v_raw,
                "tv_normalized": tv_f if tv_f is not None else tv_v,
                "app_normalized": app_f if app_f is not None else app_v,
                "diff": diff,
                "match_percent": mp,
                "status": status,
            },
        )

    df = pd.DataFrame(rows)
    # 正規化警告は DataFrame に直接埋めず、render 側で表示する（必要なら呼び出し側で使えるようにする）
    df.attrs["summary_warnings"] = norm_warnings
    return df


def _normalize_trades_df(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """列名ゆらぎを吸収し、比較用の標準列へ寄せる。"""
    warnings: list[str] = []
    df2 = _normalize_column_names(df)

    required = ["side", "entry_time", "exit_time", "entry_price", "exit_price", "pnl"]
    missing = [c for c in required if c not in df2.columns]
    if missing:
        warnings.append(f"trades 列が不足しています: {', '.join(missing)}（可能な範囲で比較します）")

    # normalize
    for c in ["entry_time", "exit_time"]:
        if c in df2.columns:
            df2[c] = df2[c].apply(_normalize_datetime_like)
    for c in ["entry_price", "exit_price", "pnl"]:
        if c in df2.columns:
            df2[c] = pd.to_numeric(df2[c], errors="coerce")
    if "side" in df2.columns:
        df2["side"] = df2["side"].astype(str).str.lower().str.strip()

    return df2, warnings


def _find_matching_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    """候補名（大小・空白差）で列を探す。完全一致のみ（MVP）。"""
    lower_to_col = {str(c).lower().strip(): c for c in df.columns}
    for key in candidates:
        k = str(key).lower().strip()
        if k in lower_to_col:
            return lower_to_col[k]
    return None


def _normalize_column_names(df: pd.DataFrame) -> pd.DataFrame:
    """列名ゆらぎ吸収（英語/日本語の最低限）."""
    colmap: dict[str, str] = {}

    # TradingView 日本語列（今回のサンプル）
    trade_no_col = _find_matching_column(df, ["トレード番号", "trade id", "trade_id", "trade no", "trade_no"])
    type_col = _find_matching_column(df, ["タイプ", "type", "action"])
    time_col = _find_matching_column(df, ["日時", "date", "time", "datetime", "timestamp"])
    price_col = _find_matching_column(df, ["価格 usdt", "price usdt", "price", "open price", "close price"])
    pnl_col = _find_matching_column(df, ["純損益 usdt", "net profit usdt", "profit", "net profit", "pnl", "pnL"])

    if trade_no_col:
        colmap[trade_no_col] = "trade_no"
    if type_col:
        colmap[type_col] = "event_type"
    if time_col:
        colmap[time_col] = "event_time"
    if price_col:
        colmap[price_col] = "event_price"
    if pnl_col:
        colmap[pnl_col] = "event_pnl"

    # 一般的な round-trip 形式（既存）
    entry_col = _find_matching_column(
        df,
        ["entry_time", "entry time", "entry", "open time"],
    )
    exit_col = _find_matching_column(
        df,
        ["exit_time", "exit time", "exit", "close time"],
    )
    side_col = _find_matching_column(df, ["side", "Side", "type", "Type", "direction", "action"])
    ep_col = _find_matching_column(df, ["entry_price", "entry price", "entryprice", "open price"])
    xp_col = _find_matching_column(df, ["exit_price", "exit price", "exitprice", "close price"])
    pnl2_col = _find_matching_column(df, ["pnl", "PnL", "profit", "net profit", "net_profit"])

    if entry_col:
        colmap[entry_col] = "entry_time"
    if exit_col:
        colmap[exit_col] = "exit_time"
    if side_col:
        colmap[side_col] = "side"
    if ep_col:
        colmap[ep_col] = "entry_price"
    if xp_col:
        colmap[xp_col] = "exit_price"
    if pnl2_col:
        colmap[pnl2_col] = "pnl"

    return df.rename(columns=colmap).copy()


def normalize_tv_trades(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """TV trades CSV を round-trip trade 粒度へ寄せる（MVP・簡易）。

    - まず列名ゆらぎ吸収（_normalize_trades_df）
    - すでに1行1トレードっぽければそのまま
    - entry/exit が別行っぽい場合は隣接2行をペアにして結合を試みる
    """
    warnings_set: set[str] = set()
    df2 = _normalize_column_names(df)

    # TradingView 日本語CSV（トレード番号 + エントリー/決済の2行）を優先的に再構成
    if "trade_no" in df2.columns and "event_type" in df2.columns and "event_time" in df2.columns:
        # 代表的な「ロングエントリー / ロング決済 / ショートエントリー / ショート決済」
        def _side_from_event_type(s: Any) -> str | None:
            if s is None:
                return None
            t = str(s).lower()
            if "ロング" in t or "long" in t:
                return "long"
            if "ショート" in t or "short" in t:
                return "short"
            return None

        def _is_entry(s: Any) -> bool:
            t = str(s)
            return ("エントリー" in t) or ("entry" in t.lower())

        def _is_exit(s: Any) -> bool:
            t = str(s)
            return ("決済" in t) or ("exit" in t.lower()) or ("close" in t.lower())

        # 型寄せ
        df2["trade_no"] = pd.to_numeric(df2["trade_no"], errors="coerce")
        df2 = df2.dropna(subset=["trade_no"]).copy()
        df2["trade_no"] = df2["trade_no"].astype(int)

        df2["event_time_dt"] = pd.to_datetime(df2["event_time"], errors="coerce", utc=True)
        # time が parse できない場合でも、元の順序で groupby する

        rows: list[dict[str, Any]] = []
        for trade_no, g in df2.groupby("trade_no", sort=True):
            # entry/exit を探す
            entry_rows = g[g["event_type"].apply(_is_entry)]
            exit_rows = g[g["event_type"].apply(_is_exit)]

            if entry_rows.empty or exit_rows.empty:
                # 期待形式でないトレードはスキップ（warning）
                warnings_set.add("TV trades: entry/exit を判定できない行があり、一部トレードを無視しました")
                continue

            # entry/exit が複数ある場合は最初/最後を採用
            entry = entry_rows.sort_values("event_time_dt", na_position="last").iloc[0].to_dict()
            exit_ = exit_rows.sort_values("event_time_dt", na_position="last").iloc[-1].to_dict()

            side = _side_from_event_type(entry.get("event_type")) or _side_from_event_type(exit_.get("event_type"))

            entry_time = entry.get("event_time")
            exit_time = exit_.get("event_time")

            entry_price = entry.get("event_price")
            exit_price = exit_.get("event_price")

            pnl = exit_.get("event_pnl")
            if pnl is None or (isinstance(pnl, float) and pd.isna(pnl)):
                pnl = entry.get("event_pnl")

            rows.append(
                {
                    "side": side,
                    "entry_time": entry_time,
                    "exit_time": exit_time,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "pnl": pnl,
                },
            )

        if rows:
            out = pd.DataFrame(rows)
            warnings_set.add("TV trades CSV は round-trip trade 単位ではない可能性があるため、trade_no 単位で簡易再構成を適用しました")
            return out, sorted(warnings_set)

    # すでに round-trip っぽい判定: entry_time/exit_time が両方あり、両方埋まっている割合が高い
    if "entry_time" in df2.columns and "exit_time" in df2.columns:
        entry_ok = df2["entry_time"].notna() & (df2["entry_time"].astype(str).str.len() > 0)
        exit_ok = df2["exit_time"].notna() & (df2["exit_time"].astype(str).str.len() > 0)
        both_ok_ratio = float((entry_ok & exit_ok).mean()) if len(df2) else 0.0
        if both_ok_ratio >= 0.8:
            return df2, []

        # entry/exit 別イベントっぽい（片方が空の行が多い）
        if len(df2) >= 2 and both_ok_ratio < 0.2:
            warnings_set.add("TV trades CSV は round-trip trade 単位ではない可能性があるため、隣接2行の簡易正規化を適用しました")
            rows: list[dict[str, Any]] = []
            i = 0
            while i < len(df2) - 1:
                r1 = df2.iloc[i].to_dict()
                r2 = df2.iloc[i + 1].to_dict()

                # entry/exit のどちらがどちらでも良いように、埋まっている方を採用
                entry_time = r1.get("entry_time") or r2.get("entry_time")
                exit_time = r1.get("exit_time") or r2.get("exit_time")

                entry_price = r1.get("entry_price")
                if pd.isna(entry_price):
                    entry_price = r2.get("entry_price")
                exit_price = r1.get("exit_price")
                if pd.isna(exit_price):
                    exit_price = r2.get("exit_price")

                side = r1.get("side") or r2.get("side")
                pnl = r2.get("pnl")
                if pnl is None or (isinstance(pnl, float) and pd.isna(pnl)):
                    pnl = r1.get("pnl")

                rows.append(
                    {
                        "side": side,
                        "entry_time": entry_time,
                        "exit_time": exit_time,
                        "entry_price": entry_price,
                        "exit_price": exit_price,
                        "pnl": pnl,
                    },
                )
                i += 2
            return pd.DataFrame(rows), sorted(warnings_set)

    warnings_set.add("TV trades CSV が round-trip trade 単位か判定できませんでした（正規化なしで比較します）")
    return df2, sorted(warnings_set)


def match_trades(
    tv_trades_df: pd.DataFrame,
    app_trades: list[dict[str, Any]],
    *,
    price_tol_ratio: float = 0.001,  # 0.1%
    pnl_tol_ratio: float = 0.01,  # 1%
) -> dict[str, Any]:
    comparison_warnings: list[str] = []

    tv_raw_rows = int(len(tv_trades_df))
    # TV trades (round-trip normalize)
    tv_norm_df, tv_norm_warn = normalize_tv_trades(tv_trades_df)
    tv_df, tv_warn = _normalize_trades_df(tv_norm_df)
    comparison_warnings.extend(tv_norm_warn)

    # App trades
    app_df_raw = pd.DataFrame(app_trades or [])
    app_df, app_warn = _normalize_trades_df(app_df_raw)

    warns = tv_warn + app_warn + comparison_warnings

    required = ["side", "entry_time", "exit_time", "entry_price", "exit_price", "pnl"]
    missing_tv = [c for c in required if c not in tv_df.columns]
    missing_app = [c for c in required if c not in app_df.columns]
    full_comparison_possible = (not missing_tv) and (not missing_app)
    provisional = not full_comparison_possible
    if provisional:
        warns.append("完全な trades 突合はできていません（必要列が不足しています）。以下は暫定結果です。")

    n_tv = int(len(tv_df))
    n_app = int(len(app_df))
    n_cmp = min(n_tv, n_app)

    matched = 0
    diffs: list[dict[str, Any]] = []

    def close_enough(a: float | None, b: float | None, tol_ratio: float) -> bool:
        if a is None or b is None:
            return False
        if pd.isna(a) or pd.isna(b):
            return False
        denom = max(abs(a), 1e-9)
        return abs(b - a) / denom <= tol_ratio

    for i in range(n_cmp):
        tv_row = tv_df.iloc[i].to_dict()
        app_row = app_df.iloc[i].to_dict()

        ok = True
        # side
        if "side" in tv_row and "side" in app_row:
            if (tv_row.get("side") or "") != (app_row.get("side") or ""):
                ok = False
        # time: datetime比較できるなら datetime、できないなら文字列
        for tcol in ["entry_time", "exit_time"]:
            if tcol in tv_row and tcol in app_row:
                tv_ts = _to_datetime_or_none(tv_row.get(tcol))
                app_ts = _to_datetime_or_none(app_row.get(tcol))
                if tv_ts is not None and app_ts is not None:
                    if tv_ts != app_ts:
                        ok = False
                else:
                    if (str(tv_row.get(tcol) or "").strip()) != (str(app_row.get(tcol) or "").strip()):
                        ok = False
        # price tolerance
        if "entry_price" in tv_row and "entry_price" in app_row:
            ok = ok and close_enough(tv_row.get("entry_price"), app_row.get("entry_price"), price_tol_ratio)
        if "exit_price" in tv_row and "exit_price" in app_row:
            ok = ok and close_enough(tv_row.get("exit_price"), app_row.get("exit_price"), price_tol_ratio)
        # pnl tolerance
        if "pnl" in tv_row and "pnl" in app_row:
            ok = ok and close_enough(tv_row.get("pnl"), app_row.get("pnl"), pnl_tol_ratio)

        if ok:
            matched += 1
        else:
            if full_comparison_possible:
                diffs.append(
                    {
                        "index": i,
                        "tv_side": tv_row.get("side"),
                        "app_side": app_row.get("side"),
                        "tv_entry_time": tv_row.get("entry_time"),
                        "app_entry_time": app_row.get("entry_time"),
                        "tv_exit_time": tv_row.get("exit_time"),
                        "app_exit_time": app_row.get("exit_time"),
                        "tv_entry_price": tv_row.get("entry_price"),
                        "app_entry_price": app_row.get("entry_price"),
                        "tv_exit_price": tv_row.get("exit_price"),
                        "app_exit_price": app_row.get("exit_price"),
                        "tv_pnl": tv_row.get("pnl"),
                        "app_pnl": app_row.get("pnl"),
                    },
                )

    tv_only = max(n_tv - n_cmp, 0)
    app_only = max(n_app - n_cmp, 0)
    denom = max(n_tv, n_app, 1)
    trade_match_percent = matched / denom * 100.0

    return {
        "matched_trades": matched,
        "tv_only_trades": tv_only,
        "app_only_trades": app_only,
        "trade_match_percent": float(trade_match_percent),
        "comparison_warnings": warns,
        "trade_diff_df": pd.DataFrame(diffs),
        "tv_raw_rows": tv_raw_rows,
        "tv_normalized_trades": n_tv,
        "app_trades": n_app,
        "provisional": provisional,
    }


def compute_overall_match_score(
    summary_df: pd.DataFrame,
    trade_match_percent: float,
    *,
    summary_weight: float = 0.5,
    trades_weight: float = 0.5,
) -> dict[str, float]:
    summary_core_avg: float | None = None
    if "match_percent" in summary_df.columns:
        df_core = summary_df
        if "role" in summary_df.columns:
            df_core = summary_df[summary_df["role"] == "core"]
        vals = pd.to_numeric(df_core["match_percent"], errors="coerce").dropna()
        summary_core_avg = float(vals.mean()) if not vals.empty else None

    if summary_core_avg is None:
        overall = float(trade_match_percent)
    else:
        overall = float(summary_core_avg) * summary_weight + float(trade_match_percent) * trades_weight
    return {
        "summary_core_match_avg": summary_core_avg,
        "overall_match_percent": float(overall),
    }


def render_tv_comparison(
    *,
    tv_ref: dict[str, Any],
    backtest_run: dict[str, Any],
    backtest_result: dict[str, Any],
    key_prefix: str,
) -> None:
    app_metrics = backtest_result.get("metrics") if isinstance(backtest_result, dict) else {}
    if not isinstance(app_metrics, dict):
        app_metrics = {}

    # summary compare
    df_summary = build_summary_comparison(tv_ref, app_metrics)
    summary_warnings = list(df_summary.attrs.get("summary_warnings") or [])

    # trades compare
    tv_trades_df, tv_err = load_tv_reference_trades_csv(tv_ref)
    app_trades = backtest_result.get("trades") if isinstance(backtest_result, dict) else []
    if not isinstance(app_trades, list):
        app_trades = []

    if tv_trades_df is None:
        trade_result = {
            "matched_trades": 0,
            "tv_only_trades": 0,
            "app_only_trades": 0,
            "trade_match_percent": 0.0,
            "comparison_warnings": [tv_err] if tv_err else [],
            "trade_diff_df": pd.DataFrame(),
            "tv_raw_rows": 0,
            "tv_normalized_trades": 0,
            "app_trades": int(len(app_trades)),
            "provisional": True,
        }
    else:
        trade_result = match_trades(tv_trades_df, app_trades)

    scores = compute_overall_match_score(df_summary, trade_result["trade_match_percent"])

    st.markdown("#### 比較の信頼度 / 警告")
    if summary_warnings:
        st.markdown("**summary warnings**")
        for w in summary_warnings:
            st.warning(str(w))
    if trade_result.get("comparison_warnings"):
        st.markdown("**trades warnings**")
        for w in trade_result.get("comparison_warnings") or []:
            if w:
                st.warning(str(w))
    if scores.get("summary_core_match_avg") is None:
        st.warning("summary 主指標が不足しているため、総合一致率は trade 一致率のみで算出しています")

    # cards
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("総合一致率", f'{scores["overall_match_percent"]:.1f}%')
    if scores["summary_core_match_avg"] is None:
        c2.metric("summary 主指標一致率", "N/A")
    else:
        c2.metric("summary 主指標一致率", f'{float(scores["summary_core_match_avg"]):.1f}%')
    c3.metric("trade 一致率", f'{trade_result["trade_match_percent"]:.1f}%')
    c4.metric("TV raw CSV 行数", str(trade_result.get("tv_raw_rows", 0)))
    c5.metric("TV normalized trades", str(trade_result.get("tv_normalized_trades", 0)))
    c6.metric("App trades 件数", str(trade_result.get("app_trades", 0)))

    st.caption(
        "注: `net_profit` と `max_drawdown` は参考指標です（初期資金、数量、複利、手数料、slippage、約定差などの影響を受けやすいため）。"
        " 総合一致率には `trade 一致率` と summary の主指標（total_trades / win_rate / profit_factor）のみを使用します。",
    )

    st.markdown("#### summary 比較")
    df_show = df_summary.copy()
    if _HAS_MPL and "match_percent" in df_show.columns:
        styler = df_show.style.background_gradient(subset=["match_percent"], cmap="Greens", vmin=0, vmax=100)
        st.dataframe(styler, use_container_width=True)
    else:
        st.dataframe(df_show, use_container_width=True)

    st.markdown("#### trades 突合結果")
    provisional = bool(trade_result.get("provisional"))
    if provisional:
        st.info("この trades 比較は暫定です（必要列不足などのため）。")
        st.write("暫定一致件数:", trade_result["matched_trades"])
        st.write("暫定一致率:", f'{trade_result["trade_match_percent"]:.1f}%')
    else:
        st.write("matched_trades:", trade_result["matched_trades"])
        st.write("tv_only_trades:", trade_result["tv_only_trades"])
        st.write("app_only_trades:", trade_result["app_only_trades"])

        diffs_df = trade_result.get("trade_diff_df")
        if isinstance(diffs_df, pd.DataFrame) and not diffs_df.empty:
            st.caption("差分（上位 50 件）")
            st.dataframe(diffs_df.head(50), use_container_width=True)
        else:
            st.info("差分はありません。")

    st.markdown("#### 注意")
    st.caption("一致率は MVP の簡易突合ベースです（順序1対1、時刻は文字列一致、価格/損益は誤差許容）。")
    st.caption("TradingView と App で約定仕様や手数料、端数処理が違うとズレます。完全一致を保証するものではありません。")

