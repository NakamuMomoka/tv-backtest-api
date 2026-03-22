from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from app.services.strategy_fees import compound_equity_after_side_fee, fee_metrics_meta, fee_rate_from_settings


DEFAULT_PARAMS: dict[str, Any] = {
    "lengthStoch": 28,
    "lengthRSI": 12,
    "smoothK": 20,
    "smoothD": 10,
    "WillyupLine": 80.0,
    "WillylowLine": 20.0,
    "length": 9,
    "lenATR": 5,
    "lenvoly": 45.0,
    "point": 10000.0,
    # Pine の syminfo.mintick 相当。None の場合は close 差分から推定
    "mintick": None,
}


def _timestamp_series(df: pd.DataFrame) -> pd.Series:
    if "timestamp" in df.columns:
        ts = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
        if ts.notna().any():
            return ts

    if "time" in df.columns:
        s = df["time"]
        if pd.api.types.is_numeric_dtype(s):
            first = float(s.dropna().iloc[0]) if s.dropna().any() else 0.0
            unit = "s" if first < 10_000_000_000 else "ms"
            ts = pd.to_datetime(s, unit=unit, errors="coerce", utc=True)
        else:
            ts = pd.to_datetime(s, errors="coerce", utc=True)

        if ts.notna().any():
            return ts

    return pd.to_datetime(pd.RangeIndex(len(df)), unit="s", utc=True)


def _rma(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(
        alpha=1.0 / max(length, 1),
        adjust=False,
        min_periods=length,
    ).mean()


def _rsi(close: pd.Series, length: int) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0.0)
    down = -delta.clip(upper=0.0)

    avg_up = _rma(up, length)
    avg_down = _rma(down, length)
    rs = avg_up / avg_down

    return 100.0 - (100.0 / (1.0 + rs))


def _sma(series: pd.Series, length: int) -> pd.Series:
    return series.rolling(length, min_periods=length).mean()


def _stoch(source: pd.Series, length: int) -> pd.Series:
    lowest = source.rolling(length, min_periods=length).min()
    highest = source.rolling(length, min_periods=length).max()
    span = (highest - lowest).replace(0.0, np.nan)
    return 100.0 * (source - lowest) / span


def _true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr1 = df["high"] - df["low"]
    tr2 = (df["high"] - prev_close).abs()
    tr3 = (df["low"] - prev_close).abs()
    return pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)


def _atr(df: pd.DataFrame, length: int) -> pd.Series:
    return _rma(_true_range(df), length)


def _crossover(a: pd.Series, b: pd.Series | float) -> pd.Series:
    if not isinstance(b, pd.Series):
        b = pd.Series(float(b), index=a.index)
    return (a > b) & (a.shift(1) <= b.shift(1))


def _crossunder(a: pd.Series, b: pd.Series | float) -> pd.Series:
    if not isinstance(b, pd.Series):
        b = pd.Series(float(b), index=a.index)
    return (a < b) & (a.shift(1) >= b.shift(1))


def _infer_mintick(close: pd.Series) -> float:
    diffs = close.diff().abs()
    diffs = diffs[(diffs > 0) & np.isfinite(diffs)]
    if diffs.empty:
        return 0.0001
    return float(diffs.min())


def _to_float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    try:
        return float(value)
    except Exception:
        return None


def run_backtest(
    bars: pd.DataFrame,
    params: dict[str, Any] | None = None,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    AssistPass strategy (Pine v3) port to Python.

    前提:
    - open/high/low/close が必要
    - 売買執行はシグナルバー終値ベース
    - 期間フィルタは strategy 内では行わず、API / service 側で bars を
      request の start_date/end_date に絞り込んでから渡す前提
    """

    params = {**DEFAULT_PARAMS, **(params or {})}
    settings = settings or {}
    optimization_mode = bool(settings.get("optimization_mode"))
    collect_trades_for_validation = bool(settings.get("collect_trades_for_validation"))
    collect_detail_outputs = (not optimization_mode) or collect_trades_for_validation
    cache: dict[str, Any] | None = None
    if optimization_mode:
        c = settings.get("_assistpass_cache")
        if isinstance(c, dict):
            cache = c

    # job 内で共通の前処理済み DataFrame を再利用する
    if cache is not None and "base_df" in cache:
        # base_df 自体は不変前提だが、戦略内で列追加するため shallow copy
        df = cache["base_df"].copy()
    else:
        df = bars.copy().reset_index(drop=True)

    required = {"open", "high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    # ---- base_df の生成（数値化済み OHLCV + timestamp）----
    if cache is not None and "base_df" in cache:
        # すでに base_df を使って df を作っているのでここでは何もしない
        pass
    else:
        for col in ["open", "high", "low", "close"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        if "Volume" in df.columns:
            df["volume"] = pd.to_numeric(df["Volume"], errors="coerce")
        elif "volume" in df.columns:
            df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
        else:
            df["volume"] = np.nan

        df["timestamp"] = _timestamp_series(df)

        if cache is not None:
            # job 単位でそのまま再利用するための base_df を保存
            cache["base_df"] = df.copy()

    length_rsi = int(params["lengthRSI"])
    length_stoch = int(params["lengthStoch"])
    smooth_k = int(params["smoothK"])
    smooth_d = int(params["smoothD"])
    willy_length = int(params["length"])
    willy_up = float(params["WillyupLine"])
    willy_low = float(params["WillylowLine"])
    len_atr = int(params["lenATR"])
    lenvoly = float(params["lenvoly"])
    point = float(params["point"])

    mintick = params.get("mintick")
    if mintick is None:
        mintick = _infer_mintick(df["close"])
    mintick = float(mintick)
    pip = mintick * point if mintick > 0 else 1.0

    # ---- RSI / Stoch / ATR / Williams をキャッシュ ----
    close_series = df["close"]
    cache_key_rsi = f"rsi_len_{length_rsi}"
    if cache is not None and cache_key_rsi in cache:
        rsi1 = cache[cache_key_rsi]
    else:
        rsi1 = _rsi(close_series, length_rsi)
        if cache is not None:
            cache[cache_key_rsi] = rsi1

    # Williams %R (willy) と ATR を fixed-part としてキャッシュ
    cache_key_willy = f"willy_len_{willy_length}"
    if cache is not None and cache_key_willy in cache:
        willy = cache[cache_key_willy]
    else:
        willy_upper = df["high"].rolling(willy_length, min_periods=willy_length).max()
        willy_lower = df["low"].rolling(willy_length, min_periods=willy_length).min()
        willy_span = (willy_upper - willy_lower).replace(0.0, np.nan)
        willy = 100.0 * (close_series - willy_upper) / willy_span + 100.0
        if cache is not None:
            cache[cache_key_willy] = willy

    # Stoch RSI
    k_raw = _stoch(rsi1, length_stoch)
    k = _sma(k_raw, smooth_k)
    d = _sma(k, smooth_d)

    cache_key_atr = f"atr_len_{len_atr}"
    if cache is not None and cache_key_atr in cache:
        atr = cache[cache_key_atr]
    else:
        atr = _atr(df, len_atr)
        if cache is not None:
            cache[cache_key_atr] = atr
    atr_pips = atr / pip

    # Cross conditions
    cross_up = (k > d) & _crossover(willy, willy_low) & (atr_pips < lenvoly)
    cross_up2 = _crossunder(k, d)
    cross_dn = (k < d) & _crossunder(willy, willy_up) & (atr_pips < lenvoly)
    cross_dn2 = _crossover(k, d)

    # Backtest settings
    initial_capital = float(settings.get("initial_capital", 1_000_000.0))
    fee_rate = fee_rate_from_settings(settings)
    equity = initial_capital
    peak_equity = equity
    max_drawdown = 0.0

    position = 0  # 1 long, -1 short, 0 flat
    entry_price: float | None = None
    entry_index: int | None = None
    entry_equity: float | None = None
    state = 0

    trades: list[dict[str, Any]] = []
    realized_pnls: list[float] = []  # optimization_mode=True でも metrics 用に保持
    equity_series: list[dict[str, Any]] = []
    debug_rows: list[dict[str, Any]] = []

    allow_bar_true_count = 0

    if len(df) > 0 and collect_detail_outputs:
        equity_series.append(
            {
                "index": 0,
                "timestamp": df["timestamp"].iloc[0].isoformat(),
                "equity": float(equity),
            }
        )

        if collect_detail_outputs:
            debug_rows.append(
                {
                    "index": 0,
                    "timestamp": df["timestamp"].iloc[0].isoformat(),
                    "close": _to_float_or_none(df["close"].iloc[0]),
                    "timescale": True,
                    "allow_bar": False,
                    "willy": _to_float_or_none(willy.iloc[0]),
                    "k": _to_float_or_none(k.iloc[0]),
                    "d": _to_float_or_none(d.iloc[0]),
                    "atr_pips": _to_float_or_none(atr_pips.iloc[0]),
                    "cross_up": bool(cross_up.iloc[0]) if pd.notna(cross_up.iloc[0]) else False,
                    "cross_dn": bool(cross_dn.iloc[0]) if pd.notna(cross_dn.iloc[0]) else False,
                    "cross_up2": bool(cross_up2.iloc[0]) if pd.notna(cross_up2.iloc[0]) else False,
                    "cross_dn2": bool(cross_dn2.iloc[0]) if pd.notna(cross_dn2.iloc[0]) else False,
                    "prev_state": 0,
                    "state": 0,
                    "long_entry": False,
                    "short_entry": False,
                    "long_close": False,
                    "short_close": False,
                    "position_before": 0,
                    "position_after": 0,
                }
            )

    for i in range(1, len(df)):
        prev_close = float(df["close"].iloc[i - 1])
        curr_close = float(df["close"].iloc[i])

        position_before = int(position)

        # 保有中の損益をバーごとに反映
        if position == 1 and prev_close > 0:
            equity *= curr_close / prev_close
        elif position == -1 and prev_close > 0:
            equity *= 1.0 - ((curr_close - prev_close) / prev_close)

        peak_equity = max(peak_equity, equity)
        if peak_equity > 0:
            max_drawdown = max(max_drawdown, (peak_equity - equity) / peak_equity)

        if collect_detail_outputs:
            equity_series.append(
                {
                    "index": int(i),
                    "timestamp": df["timestamp"].iloc[i].isoformat(),
                    "equity": float(equity),
                }
            )

        prev_state = state
        state = prev_state

        # Pine の state machine をそのまま移植
        if prev_state == 0:
            if bool(cross_up.iloc[i]):
                state = 1
            if bool(cross_dn.iloc[i]):
                state = 2
        elif prev_state == 1:
            if bool(cross_dn.iloc[i]) or bool(cross_up2.iloc[i]):
                state = 0
        elif prev_state == 2:
            if bool(cross_up.iloc[i]) or bool(cross_dn2.iloc[i]):
                state = 0

        b_long_entry = state == 1 and prev_state == 0
        b_short_entry = state == 2 and prev_state == 0
        b_long_close = state == 0 and prev_state == 1
        b_short_close = state == 0 and prev_state == 2

        # 期間フィルタは API 側で絞り込み済み前提。
        # ここではウォームアップ条件のみを確認する。
        allow_bar = (
            i >= willy_length
            and pd.notna(df["close"].iloc[i - willy_length])
        )
        if allow_bar:
            allow_bar_true_count += 1

        debug_row = {
            "index": int(i),
            "timestamp": df["timestamp"].iloc[i].isoformat(),
            "close": _to_float_or_none(curr_close),
            "timescale": True,
            "allow_bar": bool(allow_bar),
            "willy": _to_float_or_none(willy.iloc[i]),
            "k": _to_float_or_none(k.iloc[i]),
            "d": _to_float_or_none(d.iloc[i]),
            "atr_pips": _to_float_or_none(atr_pips.iloc[i]),
            "cross_up": bool(cross_up.iloc[i]) if pd.notna(cross_up.iloc[i]) else False,
            "cross_dn": bool(cross_dn.iloc[i]) if pd.notna(cross_dn.iloc[i]) else False,
            "cross_up2": bool(cross_up2.iloc[i]) if pd.notna(cross_up2.iloc[i]) else False,
            "cross_dn2": bool(cross_dn2.iloc[i]) if pd.notna(cross_dn2.iloc[i]) else False,
            "prev_state": int(prev_state),
            "state": int(state),
            "long_entry": bool(b_long_entry),
            "short_entry": bool(b_short_entry),
            "long_close": bool(b_long_close),
            "short_close": bool(b_short_close),
            "position_before": int(position_before),
            "position_after": None,
        }

        if not allow_bar:
            if collect_detail_outputs:
                debug_row["position_after"] = int(position)
                debug_rows.append(debug_row)
            continue

        # close
        if b_long_close and position == 1 and entry_price is not None and entry_index is not None:
            equity = compound_equity_after_side_fee(equity, fee_rate)
            pnl = equity - float(entry_equity)
            pnl_pct = (curr_close - float(entry_price)) / float(entry_price)
            realized_pnls.append(float(pnl))
            if collect_detail_outputs:
                trades.append(
                    {
                        "entry_index": int(entry_index),
                        "exit_index": int(i),
                        "side": "long",
                        "entry_price": float(entry_price),
                        "exit_price": float(curr_close),
                        "pnl": float(pnl),
                        "pnl_pct": float(pnl_pct),
                    }
                )
            position = 0
            entry_price = None
            entry_index = None
            entry_equity = None

        if b_short_close and position == -1 and entry_price is not None and entry_index is not None:
            equity = compound_equity_after_side_fee(equity, fee_rate)
            pnl = equity - float(entry_equity)
            pnl_pct = (float(entry_price) - curr_close) / float(entry_price)
            realized_pnls.append(float(pnl))
            if collect_detail_outputs:
                trades.append(
                    {
                        "entry_index": int(entry_index),
                        "exit_index": int(i),
                        "side": "short",
                        "entry_price": float(entry_price),
                        "exit_price": float(curr_close),
                        "pnl": float(pnl),
                        "pnl_pct": float(pnl_pct),
                    }
                )
            position = 0
            entry_price = None
            entry_index = None
            entry_equity = None

        # entry
        if b_long_entry:
            if position == -1 and entry_price is not None and entry_index is not None:
                equity = compound_equity_after_side_fee(equity, fee_rate)
                pnl = equity - float(entry_equity)
                pnl_pct = (float(entry_price) - curr_close) / float(entry_price)
                realized_pnls.append(float(pnl))
                if collect_detail_outputs:
                    trades.append(
                        {
                            "entry_index": int(entry_index),
                            "exit_index": int(i),
                            "side": "short",
                            "entry_price": float(entry_price),
                            "exit_price": float(curr_close),
                            "pnl": float(pnl),
                            "pnl_pct": float(pnl_pct),
                        }
                    )
            position = 1
            entry_price = curr_close
            entry_index = i
            equity = compound_equity_after_side_fee(equity, fee_rate)
            entry_equity = equity

        if b_short_entry:
            if position == 1 and entry_price is not None and entry_index is not None:
                equity = compound_equity_after_side_fee(equity, fee_rate)
                pnl = equity - float(entry_equity)
                pnl_pct = (curr_close - float(entry_price)) / float(entry_price)
                realized_pnls.append(float(pnl))
                if collect_detail_outputs:
                    trades.append(
                        {
                            "entry_index": int(entry_index),
                            "exit_index": int(i),
                            "side": "long",
                            "entry_price": float(entry_price),
                            "exit_price": float(curr_close),
                            "pnl": float(pnl),
                            "pnl_pct": float(pnl_pct),
                        }
                    )
            position = -1
            entry_price = curr_close
            entry_index = i
            equity = compound_equity_after_side_fee(equity, fee_rate)
            entry_equity = equity

        if collect_detail_outputs:
            debug_row["position_after"] = int(position)
            debug_rows.append(debug_row)

    open_position_at_end = position != 0 and entry_price is not None

    wins = [x for x in realized_pnls if x > 0]
    losses = [x for x in realized_pnls if x < 0]

    gross_profit = sum(wins) if wins else 0.0
    gross_loss = -sum(losses) if losses else 0.0
    total_trades = len(realized_pnls)
    win_rate = (len(wins) / total_trades) if total_trades > 0 else 0.0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else None

    final_equity = float(equity)

    metrics = {
        "net_profit": float(final_equity - initial_capital),
        "final_equity": final_equity,
        "max_drawdown": float(max_drawdown),
        "total_trades": int(total_trades),
        "win_rate": float(win_rate),
        "gross_profit": float(gross_profit),
        "gross_loss": float(gross_loss),
        "profit_factor": float(profit_factor) if profit_factor is not None else None,
        "open_position_at_end": bool(open_position_at_end),
        "atr_pips_last": float(atr_pips.dropna().iloc[-1]) if atr_pips.notna().any() else None,
        "mintick_used": float(mintick),
        # 互換用: strategy 内 timescale は撤去済みのため全バー true 扱い
        "timescale_true_count": int(len(df)),
        "allow_bar_true_count": int(allow_bar_true_count),
        "cross_up_true_count": int(cross_up.fillna(False).sum()),
        "cross_dn_true_count": int(cross_dn.fillna(False).sum()),
        "cross_up2_true_count": int(cross_up2.fillna(False).sum()),
        "cross_dn2_true_count": int(cross_dn2.fillna(False).sum()),
        "debug_rows_count": int(len(debug_rows)),
        **fee_metrics_meta(fee_rate, implementation="equity_per_fill_side"),
    }

    return {
        "metrics": metrics,
        "trades": trades,
        "equity_series": equity_series,
        "debug_rows": debug_rows,
    }


# loader 側の関数名差分に備えた alias
run_strategy = run_backtest
backtest = run_backtest