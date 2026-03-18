from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


DEFAULT_PARAMS: dict[str, Any] = {
    "Startyear": 2017,
    "Startmonth": 1,
    "Startday": 1,
    "Starthour": 0,
    "Endyear": 2020,
    "Endmonth": 1,
    "Endday": 1,
    "Endhour": 0,
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


def run_backtest(
    bars: pd.DataFrame,
    params: dict[str, Any] | None = None,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    AssistPass strategy (Pine v3) port to Python.

    前提:
    - open/high/low/close が必要
    - time または timestamp があれば期間フィルタに使用
    - 売買執行はシグナルバー終値ベース
    """

    params = {**DEFAULT_PARAMS, **(params or {})}
    settings = settings or {}

    df = bars.copy().reset_index(drop=True)

    required = {"open", "high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    if "Volume" in df.columns:
        df["volume"] = pd.to_numeric(df["Volume"], errors="coerce")
    elif "volume" in df.columns:
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
    else:
        df["volume"] = np.nan

    df["timestamp"] = _timestamp_series(df)

    start_ts = pd.Timestamp(
        year=int(params["Startyear"]),
        month=int(params["Startmonth"]),
        day=int(params["Startday"]),
        hour=int(params["Starthour"]),
        minute=0,
        tz="UTC",
    )
    end_ts = pd.Timestamp(
        year=int(params["Endyear"]),
        month=int(params["Endmonth"]),
        day=int(params["Endday"]),
        hour=int(params["Endhour"]),
        minute=0,
        tz="UTC",
    )
    df["timescale"] = (df["timestamp"] > start_ts) & (df["timestamp"] < end_ts)

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

    # RSI
    rsi1 = _rsi(df["close"], length_rsi)

    # Williams %R を Pine 式そのままで変換
    willy_upper = df["high"].rolling(willy_length, min_periods=willy_length).max()
    willy_lower = df["low"].rolling(willy_length, min_periods=willy_length).min()
    willy_span = (willy_upper - willy_lower).replace(0.0, np.nan)
    willy = 100.0 * (df["close"] - willy_upper) / willy_span + 100.0

    # Stoch RSI
    k_raw = _stoch(rsi1, length_stoch)
    k = _sma(k_raw, smooth_k)
    d = _sma(k, smooth_d)

    # ATR
    atr = _atr(df, len_atr)
    atr_pips = atr / pip

    # Cross conditions
    cross_up = (k > d) & _crossover(willy, willy_low) & (atr_pips < lenvoly)
    cross_up2 = _crossunder(k, d)
    cross_dn = (k < d) & _crossunder(willy, willy_up) & (atr_pips < lenvoly)
    cross_dn2 = _crossover(k, d)

    # Backtest settings
    initial_capital = float(settings.get("initial_capital", 1_000_000.0))
    equity = initial_capital
    peak_equity = equity
    max_drawdown = 0.0

    position = 0  # 1 long, -1 short, 0 flat
    entry_price: float | None = None
    entry_index: int | None = None
    entry_equity: float | None = None
    state = 0

    trades: list[dict[str, Any]] = []
    equity_series: list[dict[str, Any]] = []

    if len(df) > 0:
        equity_series.append(
            {
                "index": 0,
                "timestamp": df["timestamp"].iloc[0].isoformat(),
                "equity": float(equity),
            }
        )

    for i in range(1, len(df)):
        prev_close = float(df["close"].iloc[i - 1])
        curr_close = float(df["close"].iloc[i])

        # 保有中の損益をバーごとに反映
        if position == 1 and prev_close > 0:
            equity *= curr_close / prev_close
        elif position == -1 and prev_close > 0:
            equity *= 1.0 - ((curr_close - prev_close) / prev_close)

        peak_equity = max(peak_equity, equity)
        if peak_equity > 0:
            max_drawdown = max(max_drawdown, (peak_equity - equity) / peak_equity)

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

        allow_bar = (
            i >= willy_length
            and bool(df["timescale"].iloc[i])
            and pd.notna(df["close"].iloc[i - willy_length])
        )
        if not allow_bar:
            continue

        # close
        if b_long_close and position == 1 and entry_price is not None and entry_index is not None:
            pnl = equity - float(entry_equity)
            pnl_pct = (curr_close - float(entry_price)) / float(entry_price)
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
            pnl = equity - float(entry_equity)
            pnl_pct = (float(entry_price) - curr_close) / float(entry_price)
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
                pnl = equity - float(entry_equity)
                pnl_pct = (float(entry_price) - curr_close) / float(entry_price)
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
            entry_equity = equity

        if b_short_entry:
            if position == 1 and entry_price is not None and entry_index is not None:
                pnl = equity - float(entry_equity)
                pnl_pct = (curr_close - float(entry_price)) / float(entry_price)
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
            entry_equity = equity

    open_position_at_end = position != 0 and entry_price is not None

    realized_pnls = [float(t.get("pnl", 0.0)) for t in trades]
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
    }

    return {
        "metrics": metrics,
        "trades": trades,
        "equity_series": equity_series,
    }


# loader 側の関数名差分に備えた alias
run_strategy = run_backtest
backtest = run_backtest