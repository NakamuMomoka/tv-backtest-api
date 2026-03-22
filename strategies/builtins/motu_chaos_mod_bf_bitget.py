from __future__ import annotations

from typing import Any

import math
import numpy as np
import pandas as pd

from app.services.strategy_fees import fee_metrics_meta, fee_rate_from_settings, per_side_notional_fee


DEFAULT_PARAMS: dict[str, Any] = {
    "Startyear": 2017,
    "Startmonth": 1,
    "Startday": 1,
    "Starthour": 0,
    "Endyear": 2020,
    "Endmonth": 1,
    "Endday": 1,
    "Endhour": 0,
    "mom1Period": 19,
    "mom1MaPeriod": 6,
    "mom1MaMethod": 0,
    "mom2Period": 13,
    "mom2MaPeriod": 26,
    "mom2MaMethod": 0,
    "momSrcCol": "high",
    "hull1Period": 123,
    "hull2Period": 12,
    "hullSrcCol": "high",
    "baseQty": 1.0,
    # backend 側で期間絞り込み済みなら False にできる
    "use_test_period": True,
}


def _timestamp_series(df: pd.DataFrame) -> pd.Series:
    if "timestamp" in df.columns:
        ts = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
        if ts.notna().any():
            return ts

    if "time" in df.columns:
        s = df["time"]
        if pd.api.types.is_numeric_dtype(s):
            non_na = s.dropna()
            first = float(non_na.iloc[0]) if len(non_na) > 0 else 0.0
            unit = "s" if first < 10_000_000_000 else "ms"
            ts = pd.to_datetime(s, unit=unit, errors="coerce", utc=True)
        else:
            ts = pd.to_datetime(s, errors="coerce", utc=True)
        if ts.notna().any():
            return ts

    return pd.to_datetime(pd.RangeIndex(len(df)), unit="s", utc=True)


def _to_float_or_none(v: Any) -> float | None:
    try:
        if pd.isna(v):
            return None
    except Exception:
        pass
    try:
        return float(v)
    except Exception:
        return None


def _sma(series: pd.Series, length: int) -> pd.Series:
    return series.rolling(length, min_periods=length).mean()


def _ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=max(length, 1), adjust=False, min_periods=length).mean()


def _wma(series: pd.Series, length: int) -> pd.Series:
    length = max(int(length), 1)
    weights = np.arange(1, length + 1, dtype=float)

    def _calc(x: np.ndarray) -> float:
        return float(np.dot(x, weights) / weights.sum())

    return series.rolling(length, min_periods=length).apply(_calc, raw=True)


def _momentum(src: pd.Series, length: int) -> pd.Series:
    return src - src.shift(length)


def _ma_func(period: int, method: int, src: pd.Series) -> pd.Series:
    if method == 0:
        return _sma(src, period)
    if method == 1:
        return _ema(src, period)
    if method == 2:
        # Pine: ta.ema(src, period * 2 - 1)
        return _ema(src, period * 2 - 1)
    if method == 3:
        return _wma(src, period)
    return pd.Series(np.nan, index=src.index, dtype=float)


def _hull_func(period: int, src: pd.Series) -> pd.Series:
    period = max(int(period), 1)
    half = max(1, int(round(period / 2.0)))
    sqrt_len = max(1, int(math.floor(math.sqrt(period))))
    wma_half = _wma(src, half)
    wma_full = _wma(src, period)
    raw = 2.0 * wma_half - wma_full
    return _wma(raw, sqrt_len)


def _crossover(a: pd.Series, b: pd.Series) -> pd.Series:
    return ((a > b) & (a.shift(1) <= b.shift(1))).fillna(False)


def _crossunder(a: pd.Series, b: pd.Series) -> pd.Series:
    return ((a < b) & (a.shift(1) >= b.shift(1))).fillna(False)


def _equity_from_position(
    initial_capital: float,
    realized_pnl: float,
    position: int,
    entry_price: float | None,
    curr_close: float,
    qty: float,
) -> float:
    open_pnl = 0.0
    if position == 1 and entry_price is not None:
        open_pnl = (curr_close - entry_price) * qty
    elif position == -1 and entry_price is not None:
        open_pnl = (entry_price - curr_close) * qty
    return float(initial_capital + realized_pnl + open_pnl)


def run_backtest(
    bars: pd.DataFrame,
    params: dict[str, Any] | None = None,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Pine:
      strategy("strategyMotuChaosMod_bF_Bitget",
          pyramiding=0,
          process_orders_on_close=true,
          default_qty_type=strategy.fixed,
          default_qty_value=1)

    Python port:
    - バー終値約定
    - 固定数量損益
    - doten 反転あり
    - testPeriod() 実装あり
    """

    params = {**DEFAULT_PARAMS, **(params or {})}
    settings = settings or {}
    optimization_mode = bool(settings.get("optimization_mode"))
    collect_trades_for_validation = bool(settings.get("collect_trades_for_validation"))
    collect_detail_outputs = (not optimization_mode) or collect_trades_for_validation

    # optimization_mode=True では trial 間で DataFrame を再利用する（copy/reset_index を削減）
    df = bars if optimization_mode else bars.copy().reset_index(drop=True)

    required = {"open", "high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    for col in ["open", "high", "low", "close"]:
        if (not optimization_mode) or (not pd.api.types.is_numeric_dtype(df[col])):
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if (
        "timestamp" not in df.columns
        or not pd.api.types.is_datetime64_any_dtype(df["timestamp"])
    ):
        df["timestamp"] = _timestamp_series(df)

    mom_src_col = str(params.get("momSrcCol", "high"))
    hull_src_col = str(params.get("hullSrcCol", "high"))
    if mom_src_col not in df.columns:
        raise ValueError(f"momSrcCol not found: {mom_src_col}")
    if hull_src_col not in df.columns:
        raise ValueError(f"hullSrcCol not found: {hull_src_col}")

    mom_src = pd.to_numeric(df[mom_src_col], errors="coerce")
    hull_src = pd.to_numeric(df[hull_src_col], errors="coerce")

    mom1_period = int(params["mom1Period"])
    mom1_ma_period = int(params["mom1MaPeriod"])
    mom1_ma_method = int(params["mom1MaMethod"])

    mom2_period = int(params["mom2Period"])
    mom2_ma_period = int(params["mom2MaPeriod"])
    mom2_ma_method = int(params["mom2MaMethod"])

    hull1_period = int(params["hull1Period"])
    hull2_period = int(params["hull2Period"])

    base_qty = float(params["baseQty"])
    use_test_period = bool(params.get("use_test_period", True))

    if use_test_period:
        start_ts = pd.Timestamp(
            year=int(params["Startyear"]),
            month=int(params["Startmonth"]),
            day=int(params["Startday"]),
            hour=int(params.get("Starthour", 0)),
            minute=0,
            tz="UTC",
        )
        end_ts = pd.Timestamp(
            year=int(params["Endyear"]),
            month=int(params["Endmonth"]),
            day=int(params["Endday"]),
            hour=int(params.get("Endhour", 0)),
            minute=0,
            tz="UTC",
        )
        # Pine: time >= ts and time <= te
        df["test_period"] = (df["timestamp"] >= start_ts) & (df["timestamp"] <= end_ts)
    else:
        df["test_period"] = True

    # main
    mom0 = _ma_func(mom1_ma_period, mom1_ma_method, _momentum(mom_src, mom1_period))
    mom1 = _ma_func(mom2_ma_period, mom2_ma_method, _momentum(mom_src, mom2_period))

    hullma = _hull_func(hull1_period, hull_src)
    hullma2 = _hull_func(hull2_period, hull_src)

    long_go = _crossover(mom0, mom1)
    short_go = _crossunder(mom0, mom1)

    long_stop = ((~long_go) & _crossunder(hullma, hullma2)).fillna(False)
    short_stop = ((~short_go) & _crossover(hullma, hullma2)).fillna(False)

    initial_capital = float(settings.get("initial_capital", 1_000_000.0))
    fee_rate = fee_rate_from_settings(settings)

    # state machine
    state = 0
    position = 0  # 1 long / -1 short / 0 flat

    entry_price: float | None = None
    entry_index: int | None = None
    entry_timestamp: str | None = None

    realized_pnl_total = 0.0
    realized_pnls: list[float] = []  # optimization_mode=True でも metrics 用に保持
    peak_equity = initial_capital
    equity = initial_capital
    max_drawdown_amount = 0.0
    max_drawdown_ratio = 0.0

    trades: list[dict[str, Any]] = []
    equity_series: list[dict[str, Any]] = []
    debug_rows: list[dict[str, Any]] = []

    for i in range(len(df)):
        curr_close = float(df["close"].iloc[i])
        ts_iso = df["timestamp"].iloc[i].isoformat()
        side_fee = per_side_notional_fee(curr_close, base_qty, fee_rate)

        prev_state = state
        state = prev_state

        lg = bool(long_go.iloc[i]) if pd.notna(long_go.iloc[i]) else False
        sg = bool(short_go.iloc[i]) if pd.notna(short_go.iloc[i]) else False
        ls = bool(long_stop.iloc[i]) if pd.notna(long_stop.iloc[i]) else False
        ss = bool(short_stop.iloc[i]) if pd.notna(short_stop.iloc[i]) else False

        if prev_state == 0:
            if lg:
                state = 1
            if sg:
                state = 2

        elif prev_state == 1:
            if sg:
                state = 2
            else:
                if ls:
                    state = 0

        elif prev_state == 2:
            if lg:
                state = 1
            else:
                if ss:
                    state = 0

        long_entry = state == 1 and prev_state == 0
        short_entry = state == 2 and prev_state == 0
        doten_long = state == 1 and prev_state == 2
        doten_short = state == 2 and prev_state == 1
        long_close = state == 0 and prev_state == 1
        short_close = state == 0 and prev_state == 2

        position_before = position

        allow_bar = bool(df["test_period"].iloc[i])

        if allow_bar:
            # 1 -> 0
            if long_close and position > 0 and entry_price is not None and entry_index is not None:
                pnl = ((curr_close - entry_price) * base_qty) - side_fee
                realized_pnl_total += pnl
                realized_pnls.append(float(pnl))
                if collect_detail_outputs:
                    trades.append(
                        {
                            "entry_index": int(entry_index),
                            "exit_index": int(i),
                            "entry_timestamp": entry_timestamp,
                            "exit_timestamp": ts_iso,
                            "side": "long",
                            "qty": float(base_qty),
                            "entry_price": float(entry_price),
                            "exit_price": float(curr_close),
                            "pnl": float(pnl),
                            "pnl_pct": float((curr_close - entry_price) / entry_price)
                            if entry_price != 0
                            else None,
                            "comment": "CLOSE_LONG",
                        }
                    )
                position = 0
                entry_price = None
                entry_index = None
                entry_timestamp = None

            # 2 -> 0
            if short_close and position < 0 and entry_price is not None and entry_index is not None:
                pnl = ((entry_price - curr_close) * base_qty) - side_fee
                realized_pnl_total += pnl
                realized_pnls.append(float(pnl))
                if collect_detail_outputs:
                    trades.append(
                        {
                            "entry_index": int(entry_index),
                            "exit_index": int(i),
                            "entry_timestamp": entry_timestamp,
                            "exit_timestamp": ts_iso,
                            "side": "short",
                            "qty": float(base_qty),
                            "entry_price": float(entry_price),
                            "exit_price": float(curr_close),
                            "pnl": float(pnl),
                            "pnl_pct": float((entry_price - curr_close) / entry_price)
                            if entry_price != 0
                            else None,
                            "comment": "CLOSE_SHORT",
                        }
                    )
                position = 0
                entry_price = None
                entry_index = None
                entry_timestamp = None

            # 0 -> 1
            if long_entry and position == 0:
                position = 1
                entry_price = curr_close
                entry_index = i
                entry_timestamp = ts_iso
                realized_pnl_total -= side_fee

            # 0 -> 2
            if short_entry and position == 0:
                position = -1
                entry_price = curr_close
                entry_index = i
                entry_timestamp = ts_iso
                realized_pnl_total -= side_fee

            # 2 -> 1
            if doten_long:
                if position < 0 and entry_price is not None and entry_index is not None:
                    pnl = ((entry_price - curr_close) * base_qty) - side_fee
                    realized_pnl_total += pnl
                    realized_pnls.append(float(pnl))
                    if collect_detail_outputs:
                        trades.append(
                            {
                                "entry_index": int(entry_index),
                                "exit_index": int(i),
                                "entry_timestamp": entry_timestamp,
                                "exit_timestamp": ts_iso,
                                "side": "short",
                                "qty": float(base_qty),
                                "entry_price": float(entry_price),
                                "exit_price": float(curr_close),
                                "pnl": float(pnl),
                                "pnl_pct": float((entry_price - curr_close) / entry_price)
                                if entry_price != 0
                                else None,
                                "comment": "LONG2",
                            }
                        )
                position = 1
                entry_price = curr_close
                entry_index = i
                entry_timestamp = ts_iso
                realized_pnl_total -= side_fee

            # 1 -> 2
            if doten_short:
                if position > 0 and entry_price is not None and entry_index is not None:
                    pnl = ((curr_close - entry_price) * base_qty) - side_fee
                    realized_pnl_total += pnl
                    realized_pnls.append(float(pnl))
                    if collect_detail_outputs:
                        trades.append(
                            {
                                "entry_index": int(entry_index),
                                "exit_index": int(i),
                                "entry_timestamp": entry_timestamp,
                                "exit_timestamp": ts_iso,
                                "side": "long",
                                "qty": float(base_qty),
                                "entry_price": float(entry_price),
                                "exit_price": float(curr_close),
                                "pnl": float(pnl),
                                "pnl_pct": float((curr_close - entry_price) / entry_price)
                                if entry_price != 0
                                else None,
                                "comment": "SHORT2",
                            }
                        )
                position = -1
                entry_price = curr_close
                entry_index = i
                entry_timestamp = ts_iso
                realized_pnl_total -= side_fee

        equity = _equity_from_position(
            initial_capital=initial_capital,
            realized_pnl=realized_pnl_total,
            position=position,
            entry_price=entry_price,
            curr_close=curr_close,
            qty=base_qty,
        )

        peak_equity = max(peak_equity, equity)
        dd_amount = peak_equity - equity
        dd_ratio = (dd_amount / peak_equity) if peak_equity > 0 else 0.0
        max_drawdown_amount = max(max_drawdown_amount, dd_amount)
        max_drawdown_ratio = max(max_drawdown_ratio, dd_ratio)

        if collect_detail_outputs:
            equity_series.append(
                {
                    "index": int(i),
                    "timestamp": ts_iso,
                    "equity": float(equity),
                }
            )

            debug_rows.append(
                {
                    "index": int(i),
                    "timestamp": ts_iso,
                    "close": float(curr_close),
                    "test_period": bool(df["test_period"].iloc[i]),
                    "allow_bar": bool(allow_bar),
                    "mom0": _to_float_or_none(mom0.iloc[i]),
                    "mom1": _to_float_or_none(mom1.iloc[i]),
                    "hullma": _to_float_or_none(hullma.iloc[i]),
                    "hullma2": _to_float_or_none(hullma2.iloc[i]),
                    "long_go": bool(lg),
                    "short_go": bool(sg),
                    "long_stop": bool(ls),
                    "short_stop": bool(ss),
                    "prev_state": int(prev_state),
                    "state": int(state),
                    "long_entry": bool(long_entry),
                    "short_entry": bool(short_entry),
                    "doten_long": bool(doten_long),
                    "doten_short": bool(doten_short),
                    "long_close": bool(long_close),
                    "short_close": bool(short_close),
                    "position_before": int(position_before),
                    "position_after": int(position),
                    "equity": float(equity),
                }
            )

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
        "final_equity": float(final_equity),
        # TV 比較向けに金額DDを主で返す
        "max_drawdown": float(max_drawdown_amount),
        "max_drawdown_pct": float(max_drawdown_ratio),
        "total_trades": int(total_trades),
        "win_rate": float(win_rate),
        "win_rate_percent": float(win_rate * 100.0),
        "gross_profit": float(gross_profit),
        "gross_loss": float(gross_loss),
        "profit_factor": float(profit_factor) if profit_factor is not None else None,
        "open_position_at_end": bool(open_position_at_end),
        "test_period_true_count": int(df["test_period"].sum()),
        "long_go_true_count": int(long_go.sum()),
        "short_go_true_count": int(short_go.sum()),
        "long_stop_true_count": int(long_stop.sum()),
        "short_stop_true_count": int(short_stop.sum()),
        "debug_rows_count": int(len(debug_rows)),
        **fee_metrics_meta(fee_rate, implementation="absolute_notional_per_fill"),
    }

    return {
        "metrics": metrics,
        "trades": trades,
        "equity_series": equity_series,
        "debug_rows": debug_rows,
    }


# loader 側の別名対策
run_strategy = run_backtest
backtest = run_backtest