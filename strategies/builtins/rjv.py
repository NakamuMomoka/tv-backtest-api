import pandas as pd
import numpy as np

from app.services.strategy_fees import (
    apply_fee_to_return_pct,
    fee_metrics_meta,
    fee_rate_from_settings,
    per_side_return_fee,
)


DEFAULT_PARAMS = {
    "COG_PERIOD": 28,
    "COG_LENGTH": 21,
    "COG_DEV": 1.3,
    "VCOG_PERIOD": 13,
    "VCOG_LENGTH": 6,
    "VCOG_DEV": 0.8,
    "DOTEN": True,
}


def cog(series: pd.Series, length: int) -> pd.Series:
    """
    TradingView ta.cog() 近似。
    rolling().apply() に渡る x は [最古 ... 最新] なので反転して、
    [最新 ... 最古] に対して重みを掛ける。
    """

    def _cog_window(x: np.ndarray) -> float:
        if len(x) != length:
            return np.nan

        x_rev = x[::-1]  # [最新 ... 最古]
        denom = float(np.sum(x_rev))
        if denom == 0.0:
            return np.nan

        idx = np.arange(0, length, dtype=float)  # 0=最新, length-1=最古
        return float(-np.sum(idx * x_rev) / denom)

    return series.rolling(length).apply(_cog_window, raw=True)


def _iter_candidate_series(df: pd.DataFrame, name: str) -> list[pd.Series]:
    if name not in df.columns:
        return []

    col = df[name]
    if isinstance(col, pd.DataFrame):
        return [col.iloc[:, i] for i in range(col.shape[1])]

    return [col]


def _pick_best_numeric_column(
    df: pd.DataFrame,
    candidates: list[str],
    *,
    prefer_variance: bool = False,
) -> pd.Series | None:
    scored: list[tuple[tuple[int, int, float, int, int], pd.Series]] = []
    seen_order = 0

    for name in candidates:
        for col in _iter_candidate_series(df, name):
            numeric = pd.to_numeric(col, errors="coerce")
            non_null = int(numeric.notna().sum())
            if non_null == 0:
                seen_order += 1
                continue

            std = float(numeric.std()) if non_null > 1 else 0.0
            nunique = int(numeric.nunique(dropna=True))

            variance_flag = 1 if (std > 0.0 and nunique > 1) else 0
            if not prefer_variance:
                variance_flag = 0

            score = (
                variance_flag,
                non_null,
                std,
                nunique,
                -seen_order,
            )
            scored.append((score, numeric))
            seen_order += 1

    if not scored:
        return None

    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1]


def _pick_first_existing_text_column(df: pd.DataFrame, candidates: list[str]) -> pd.Series | None:
    for name in candidates:
        if name in df.columns:
            col = df[name]
            if isinstance(col, pd.DataFrame):
                return col.iloc[:, 0]
            return col
    return None


def _normalize_bar_columns(bars: pd.DataFrame) -> pd.DataFrame:
    df = bars.copy()
    out = df.copy()

    price_aliases = {
        "open": ["open", "Open", "OPEN"],
        "high": ["high", "High", "HIGH"],
        "low": ["low", "Low", "LOW"],
        "close": ["close", "Close", "CLOSE"],
    }

    for canonical, aliases in price_aliases.items():
        series = _pick_best_numeric_column(df, aliases, prefer_variance=False)
        if series is not None:
            out[canonical] = series

    volume_aliases = ["Volume", "volume", "VOLUME", "vol", "Vol"]
    volume_series = _pick_best_numeric_column(df, volume_aliases, prefer_variance=True)
    if volume_series is None:
        volume_series = _pick_best_numeric_column(df, volume_aliases, prefer_variance=False)
    if volume_series is not None:
        out["volume"] = volume_series

    time_aliases = ["timestamp", "time", "datetime", "date", "Time", "Date"]
    time_series = _pick_first_existing_text_column(df, time_aliases)
    if time_series is not None:
        out["time"] = time_series

    return out


def backtest(bars: pd.DataFrame, params, settings):
    params = params or {}
    settings = settings or {}
    optimization_mode = bool(settings.get("optimization_mode"))
    collect_trades_for_validation = bool(settings.get("collect_trades_for_validation"))
    collect_detail_outputs = (not optimization_mode) or collect_trades_for_validation

    bars = _normalize_bar_columns(bars)

    required_cols = ["open", "high", "low", "close", "volume"]
    missing = [c for c in required_cols if c not in bars.columns]
    if missing:
        raise ValueError(f"Dataset must contain columns: {', '.join(missing)}")

    COG_PERIOD = int(params.get("COG_PERIOD", DEFAULT_PARAMS["COG_PERIOD"]))
    COG_LENGTH = int(params.get("COG_LENGTH", DEFAULT_PARAMS["COG_LENGTH"]))
    COG_DEV = float(params.get("COG_DEV", DEFAULT_PARAMS["COG_DEV"]))

    VCOG_PERIOD = int(params.get("VCOG_PERIOD", DEFAULT_PARAMS["VCOG_PERIOD"]))
    VCOG_LENGTH = int(params.get("VCOG_LENGTH", DEFAULT_PARAMS["VCOG_LENGTH"]))
    VCOG_DEV = float(params.get("VCOG_DEV", DEFAULT_PARAMS["VCOG_DEV"]))

    DOTEN = bool(params.get("DOTEN", DEFAULT_PARAMS["DOTEN"]))
    initial_capital = float(settings.get("initial_capital", 10000))
    fee_rate = fee_rate_from_settings(settings)

    # optimization_mode=True では trial 間で DataFrame を再利用する（copy/reset_index を削減）
    df = bars if optimization_mode else bars.copy().reset_index(drop=True)

    for col in ["open", "high", "low", "close", "volume"]:
        col_value = df[col]
        if isinstance(col_value, pd.DataFrame):
            # まれに MultiIndex 等で DataFrame が混入するケースに対応
            col_value = col_value.iloc[:, 0]
            df[col] = pd.to_numeric(col_value, errors="coerce")
        else:
            # optimization_mode では dtype が既に数値なら to_numeric をスキップする
            if (not optimization_mode) or (not pd.api.types.is_numeric_dtype(col_value)):
                df[col] = pd.to_numeric(col_value, errors="coerce")

    df["hlc3"] = (df["high"] + df["low"] + df["close"]) / 3

    # ---- TradingView strategy 版に合わせた indicator ----
    df["cog"] = cog(df["hlc3"], COG_PERIOD)
    df["change"] = df["cog"].diff()
    df["sd"] = df["change"].abs().rolling(COG_LENGTH).std(ddof=0)

    df["vcog"] = cog(df["volume"], VCOG_PERIOD)
    df["vchange"] = df["vcog"].diff()
    df["vsd"] = df["vchange"].abs().rolling(VCOG_LENGTH).std(ddof=0)

    state = 0
    position = 0  # 0 flat, 1 long, -1 short
    equity = initial_capital

    # TV の trade list に近い形で、建ったポジション単位で管理する
    active_trade: dict | None = None

    trades: list[dict[str, float | int | str | None]] = []
    realized_pnls: list[float] = []  # optimization_mode=True でも metrics 用に必ず保持
    equity_curve: list[dict[str, float | int]] = []
    debug_rows: list[dict[str, object]] = []

    time_col = None
    for candidate in ("timestamp", "time", "datetime", "date"):
        if candidate in df.columns:
            time_col = candidate
            break

    go_price_true_count = 0
    go_volume_true_count = 0
    both_go_true_count = 0
    long_go_count = 0
    short_go_count = 0
    long_entry_count = 0
    short_entry_count = 0
    doten_long_count = 0
    doten_short_count = 0
    long_close_count = 0
    short_close_count = 0

    n = len(df)

    def bar_time_to_str(v):
        if pd.isna(v):
            return None
        return str(v)

    def open_new_trade(
        side: str,
        entry_price: float,
        entry_index: int,
        entry_time: str | None,
        signal_type: str,
    ) -> dict:
        return {
            "side": side,
            "entry_price": float(entry_price),
            "entry_index": int(entry_index),
            "entry_time": entry_time,
            "entry_signal_type": signal_type,
        }

    def finalize_active_trade(
        active: dict,
        exit_price: float,
        exit_index: int,
        exit_time: str | None,
        exit_signal_type: str,
    ) -> dict:
        entry_price = float(active["entry_price"])
        side = str(active["side"])

        if side == "long":
            gross = (exit_price - entry_price) / entry_price
        else:
            gross = (entry_price - exit_price) / entry_price
        pnl = apply_fee_to_return_pct(float(gross), fee_rate)

        return {
            "side": side,
            "entry_price": entry_price,
            "exit_price": float(exit_price),
            "pnl": float(pnl),
            "entry_index": int(active["entry_index"]),
            "exit_index": int(exit_index),
            "entry_time": active.get("entry_time"),
            "exit_time": exit_time,
            "entry_signal_type": active.get("entry_signal_type"),
            "exit_signal_type": exit_signal_type,
        }

    for i in range(n - 1):
        row = df.iloc[i]
        next_row = df.iloc[i + 1]

        change = row["change"]
        vchange = row["vchange"]
        sd = row["sd"]
        vsd = row["vsd"]

        long_go = False
        short_go = False
        long_stop = False
        short_stop = False

        abs_change = abs(change) if not pd.isna(change) else np.nan
        abs_vchange = abs(vchange) if not pd.isna(vchange) else np.nan
        sd_threshold = sd * COG_DEV if not pd.isna(sd) else np.nan
        vsd_threshold = vsd * VCOG_DEV if not pd.isna(vsd) else np.nan

        go_condition_price = False
        go_condition_volume = False

        if not pd.isna(sd_threshold) and not pd.isna(abs_change):
            go_condition_price = abs_change >= sd_threshold
        if not pd.isna(vsd_threshold) and not pd.isna(abs_vchange):
            go_condition_volume = abs_vchange >= vsd_threshold

        if go_condition_price:
            go_price_true_count += 1
        if go_condition_volume:
            go_volume_true_count += 1
        if go_condition_price and go_condition_volume:
            both_go_true_count += 1

        if go_condition_price and go_condition_volume:
            long_go = change >= 0
            short_go = not long_go
        else:
            if not DOTEN:
                long_stop = True
                short_stop = True

        if long_go:
            long_go_count += 1
        if short_go:
            short_go_count += 1

        prev = state

        # Pine v5 strategy 本文どおり
        if prev == 0:
            if long_go:
                state = 1
            if short_go:
                state = 2

        if prev == 1:
            if short_go:
                state = 2
            else:
                if long_stop:
                    state = 0

        if prev == 2:
            if long_go:
                state = 1
            else:
                if short_stop:
                    state = 0

        long_entry = (state == 1 and prev == 0)
        short_entry = (state == 2 and prev == 0)
        doten_short = (state == 2 and prev == 1)
        doten_long = (state == 1 and prev == 2)
        long_close = (state == 0 and prev == 1)
        short_close = (state == 0 and prev == 2)

        if long_entry:
            long_entry_count += 1
        if short_entry:
            short_entry_count += 1
        if doten_short:
            doten_short_count += 1
        if doten_long:
            doten_long_count += 1
        if long_close:
            long_close_count += 1
        if short_close:
            short_close_count += 1

        # strategy() は signal bar の次バー open 約定
        fill_price = float(next_row["open"])
        fill_index = i + 1
        fill_time = bar_time_to_str(next_row[time_col]) if time_col is not None else None

        ts_value = bar_time_to_str(row[time_col]) if time_col is not None else None

        if collect_detail_outputs:
            debug_rows.append(
                {
                    "index": int(i),
                    "time": ts_value,
                    "cog_price_value": float(row["hlc3"]) if not pd.isna(row["hlc3"]) else None,
                    "cog": float(row["cog"]) if not pd.isna(row["cog"]) else None,
                    "change": float(change) if not pd.isna(change) else None,
                    "sd": float(sd) if not pd.isna(sd) else None,
                    "vcog": float(row["vcog"]) if not pd.isna(row["vcog"]) else None,
                    "vchange": float(vchange) if not pd.isna(vchange) else None,
                    "vsd": float(vsd) if not pd.isna(vsd) else None,
                    "abs_change": float(abs_change) if not pd.isna(abs_change) else None,
                    "sd_threshold": float(sd_threshold) if not pd.isna(sd_threshold) else None,
                    "abs_vchange": float(abs_vchange) if not pd.isna(abs_vchange) else None,
                    "vsd_threshold": float(vsd_threshold) if not pd.isna(vsd_threshold) else None,
                    "go_condition_price": bool(go_condition_price),
                    "go_condition_volume": bool(go_condition_volume),
                    "long_go": bool(long_go),
                    "short_go": bool(short_go),
                    "long_stop": bool(long_stop),
                    "short_stop": bool(short_stop),
                    "prev_state": int(prev),
                    "next_state": int(state),
                    "long_entry": bool(long_entry),
                    "short_entry": bool(short_entry),
                    "doten_long": bool(doten_long),
                    "doten_short": bool(doten_short),
                    "long_close": bool(long_close),
                    "short_close": bool(short_close),
                }
            )

        # ---- TV 風に「ポジション区間」を trades にする ----
        if position == 1:
            if doten_short:
                if active_trade is not None:
                    side = str(active_trade["side"])
                    entry_price = float(active_trade["entry_price"])
                    gross = (
                        (fill_price - entry_price) / entry_price
                        if side == "long"
                        else (entry_price - fill_price) / entry_price
                    )
                    pnl = apply_fee_to_return_pct(float(gross), fee_rate)
                    realized_pnls.append(float(pnl))
                    equity *= 1.0 + float(pnl)
                    if collect_detail_outputs:
                        closed = finalize_active_trade(
                            active_trade,
                            exit_price=fill_price,
                            exit_index=fill_index,
                            exit_time=fill_time,
                            exit_signal_type="doten_short",
                        )
                        trades.append(closed)

                active_trade = open_new_trade(
                    side="short",
                    entry_price=fill_price,
                    entry_index=fill_index,
                    entry_time=fill_time,
                    signal_type="doten_short",
                )
                position = -1

            elif long_close:
                if active_trade is not None:
                    side = str(active_trade["side"])
                    entry_price = float(active_trade["entry_price"])
                    gross = (
                        (fill_price - entry_price) / entry_price
                        if side == "long"
                        else (entry_price - fill_price) / entry_price
                    )
                    pnl = apply_fee_to_return_pct(float(gross), fee_rate)
                    realized_pnls.append(float(pnl))
                    equity *= 1.0 + float(pnl)
                    if collect_detail_outputs:
                        closed = finalize_active_trade(
                            active_trade,
                            exit_price=fill_price,
                            exit_index=fill_index,
                            exit_time=fill_time,
                            exit_signal_type="long_close",
                        )
                        trades.append(closed)

                active_trade = None
                position = 0

        elif position == -1:
            if doten_long:
                if active_trade is not None:
                    side = str(active_trade["side"])
                    entry_price = float(active_trade["entry_price"])
                    gross = (
                        (fill_price - entry_price) / entry_price
                        if side == "long"
                        else (entry_price - fill_price) / entry_price
                    )
                    pnl = apply_fee_to_return_pct(float(gross), fee_rate)
                    realized_pnls.append(float(pnl))
                    equity *= 1.0 + float(pnl)
                    if collect_detail_outputs:
                        closed = finalize_active_trade(
                            active_trade,
                            exit_price=fill_price,
                            exit_index=fill_index,
                            exit_time=fill_time,
                            exit_signal_type="doten_long",
                        )
                        trades.append(closed)

                active_trade = open_new_trade(
                    side="long",
                    entry_price=fill_price,
                    entry_index=fill_index,
                    entry_time=fill_time,
                    signal_type="doten_long",
                )
                position = 1

            elif short_close:
                if active_trade is not None:
                    side = str(active_trade["side"])
                    entry_price = float(active_trade["entry_price"])
                    gross = (
                        (fill_price - entry_price) / entry_price
                        if side == "long"
                        else (entry_price - fill_price) / entry_price
                    )
                    pnl = apply_fee_to_return_pct(float(gross), fee_rate)
                    realized_pnls.append(float(pnl))
                    equity *= 1.0 + float(pnl)
                    if collect_detail_outputs:
                        closed = finalize_active_trade(
                            active_trade,
                            exit_price=fill_price,
                            exit_index=fill_index,
                            exit_time=fill_time,
                            exit_signal_type="short_close",
                        )
                        trades.append(closed)

                active_trade = None
                position = 0

        else:
            if long_entry:
                active_trade = open_new_trade(
                    side="long",
                    entry_price=fill_price,
                    entry_index=fill_index,
                    entry_time=fill_time,
                    signal_type="long_entry",
                )
                position = 1

            elif short_entry:
                active_trade = open_new_trade(
                    side="short",
                    entry_price=fill_price,
                    entry_index=fill_index,
                    entry_time=fill_time,
                    signal_type="short_entry",
                )
                position = -1

        if collect_detail_outputs:
            equity_curve.append({"index": int(i), "equity": float(equity)})

    # 未決済ポジションを TV の一覧に近い形で返す
    open_trade = None
    if collect_detail_outputs and active_trade is not None:
        last_row = df.iloc[-1]
        mark_price = float(last_row["close"]) if not pd.isna(last_row["close"]) else float(active_trade["entry_price"])
        side = str(active_trade["side"])
        entry_price = float(active_trade["entry_price"])

        if side == "long":
            open_pnl = (mark_price - entry_price) / entry_price
        else:
            open_pnl = (entry_price - mark_price) / entry_price
        # 未決済は entry 側手数料のみ反映（exit は未確定）
        open_pnl -= per_side_return_fee(fee_rate)

        open_trade = {
            "side": side,
            "entry_price": entry_price,
            "current_price": mark_price,
            "pnl": float(open_pnl),
            "entry_index": int(active_trade["entry_index"]),
            "entry_time": active_trade.get("entry_time"),
            "entry_signal_type": active_trade.get("entry_signal_type"),
            "status": "open",
        }

    # realize-based metrics（trades dict を作らなくても realized_pnls で計算）
    wins = [x for x in realized_pnls if x > 0]
    losses = [x for x in realized_pnls if x <= 0]

    total_trades = len(realized_pnls)
    win_rate = (len(wins) / total_trades) if total_trades > 0 else 0.0

    gross_profit = sum(wins) if wins else 0.0
    gross_loss = -sum(losses) if losses else 0.0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else None

    final_equity = float(equity)
    net_profit = float(final_equity - initial_capital)

    metrics = {
        "net_profit": net_profit,
        "final_equity": final_equity,
        "total_trades": int(total_trades),
        "total_trades_including_open": int(total_trades + (1 if open_trade is not None else 0)),
        "win_rate": float(win_rate),
        "gross_profit": float(gross_profit),
        "gross_loss": float(gross_loss),
        "profit_factor": float(profit_factor) if profit_factor is not None else None,
        "go_price_true_count": int(go_price_true_count),
        "go_volume_true_count": int(go_volume_true_count),
        "both_go_true_count": int(both_go_true_count),
        "long_go_count": int(long_go_count),
        "short_go_count": int(short_go_count),
        "long_entry_count": int(long_entry_count),
        "short_entry_count": int(short_entry_count),
        "doten_long_count": int(doten_long_count),
        "doten_short_count": int(doten_short_count),
        "long_close_count": int(long_close_count),
        "short_close_count": int(short_close_count),
        **fee_metrics_meta(fee_rate, implementation="return_compound_roundtrip"),
    }

    try:
        vol = pd.to_numeric(df["volume"], errors="coerce")
        vol_std = float(vol.std())
        if vol_std == 0.0:
            metrics["volume_warning"] = "volume column appears constant (std == 0)."
        metrics["volume_std"] = vol_std
        metrics["volume_non_null"] = int(vol.notna().sum())
        metrics["volume_unique"] = int(vol.nunique(dropna=True))
    except Exception:
        pass

    return {
        "metrics": metrics,
        "trades": trades,
        "open_trade": open_trade,
        "equity_series": equity_curve,
        "debug_rows": debug_rows,
    }