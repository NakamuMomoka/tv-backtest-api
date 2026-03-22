import pandas as pd

from app.services.strategy_fees import apply_fee_to_return_pct, fee_metrics_meta, fee_rate_from_settings


DEFAULT_PARAMS = {
    "fast_window": 9,
    "slow_window": 21,
}


def backtest(bars: pd.DataFrame, params, settings):
    params = params or {}
    settings = settings or {}
    optimization_mode = bool(settings.get("optimization_mode"))
    collect_trades_for_validation = bool(settings.get("collect_trades_for_validation"))
    collect_detail_outputs = (not optimization_mode) or collect_trades_for_validation

    fast_window = int(params.get("fast_window", DEFAULT_PARAMS["fast_window"]))
    slow_window = int(params.get("slow_window", DEFAULT_PARAMS["slow_window"]))
    initial_capital = float(settings.get("initial_capital", 10000))
    fee_rate = fee_rate_from_settings(settings)

    if "close" not in bars.columns:
        raise ValueError("Dataset must contain 'close' column.")
    if "open" not in bars.columns:
        raise ValueError("Dataset must contain 'open' column.")

    df = bars.copy().reset_index(drop=True)

    df["fast_ma"] = df["close"].rolling(window=fast_window, min_periods=fast_window).mean()
    df["slow_ma"] = df["close"].rolling(window=slow_window, min_periods=slow_window).mean()

    # TradingView の ta.crossover / ta.crossunder 相当
    df["long_entry"] = (
        (df["fast_ma"] > df["slow_ma"])
        & (df["fast_ma"].shift(1) <= df["slow_ma"].shift(1))
    )
    df["long_exit"] = (
        (df["fast_ma"] < df["slow_ma"])
        & (df["fast_ma"].shift(1) >= df["slow_ma"].shift(1))
    )

    time_col = None
    for candidate in ("timestamp", "time", "datetime", "date"):
        if candidate in df.columns:
            time_col = candidate
            break

    equity = initial_capital
    equity_curve: list[dict[str, float]] = []
    trades: list[dict[str, float | int | None]] = []

    in_position = False
    entry_price: float | None = None
    entry_index: int | None = None
    entry_time: str | None = None

    realized_pnls: list[float] = []

    n = len(df)
    # i はシグナル判定バー、実際の約定は i+1 の open
    for i in range(n - 1):
        row = df.iloc[i]
        next_row = df.iloc[i + 1]

        if time_col is not None:
            raw_time = next_row[time_col]
            exec_time = None if pd.isna(raw_time) else str(raw_time)
        else:
            exec_time = None

        # long entry: シグナル発生バー i、約定は i+1 の open
        if not in_position and bool(row["long_entry"]):
            in_position = True
            entry_price = float(next_row["open"])
            entry_index = int(i + 1)
            entry_time = exec_time

        # long exit: シグナル発生バー i、約定は i+1 の open
        elif in_position and bool(row["long_exit"]):
            exit_price = float(next_row["open"])
            exit_index = int(i + 1)
            exit_time = exec_time

            gross_pnl = (exit_price - entry_price) / entry_price  # type: ignore[operator]
            # リターン比率モデル: ラウンドトリップで 2 * fee_rate を控除（long/short 同式）
            pnl = apply_fee_to_return_pct(float(gross_pnl), fee_rate)
            realized_pnls.append(float(pnl))
            equity *= (1.0 + pnl)  # type: ignore[operator]

            if collect_detail_outputs:
                trades.append(
                    {
                        "entry_index": int(entry_index),  # type: ignore[arg-type]
                        "exit_index": exit_index,
                        "entry_time": entry_time,
                        "exit_time": exit_time,
                        "entry_price": float(entry_price),  # type: ignore[arg-type]
                        "exit_price": float(exit_price),
                        "pnl": float(pnl),
                    },
                )

            in_position = False
            entry_price = None
            entry_index = None
            entry_time = None

    # --- ここから equity_series（含み損益反映）の計算 ---
    equity_after_trade_execution = float(equity)
    # 最適化モードでは equity_series を省略し、単発 backtest 時のみ詳細を計算する
    if collect_detail_outputs:
        # ポジション配列を trades から復元（1 = ロング保有中, 0 = ノーポジ）
        position = [0] * n
        for t in trades:
            e_idx = t.get("entry_index")
            x_idx = t.get("exit_index")
            if e_idx is None:
                continue
            e = int(e_idx)
            if x_idx is None:
                # 未決済の場合は最後までポジションを持ち続ける
                for j in range(e, n):
                    position[j] = 1
            else:
                x = int(x_idx)
                for j in range(e, min(x, n - 1) + 1):
                    position[j] = 1

        equity = initial_capital
        equity_curve = []
        if n > 0:
            equity_curve.append({"index": 0, "equity": float(equity)})

        for i in range(1, n):
            close_prev = float(df.loc[i - 1, "close"])
            close_cur = float(df.loc[i, "close"])
            if close_prev != 0:
                bar_ret = (close_cur - close_prev) / close_prev
            else:
                bar_ret = 0.0
            pos = position[i - 1]
            equity *= (1.0 + pos * bar_ret)
            equity_curve.append({"index": int(i), "equity": float(equity)})

    # 最後のバー時点でポジションが残っているかどうか
    open_position_at_end = bool(in_position)

    # max_drawdown は backtest_service 側で補完されるため、ここでは 0.0 でもよい
    max_drawdown = 0.0

    wins = [x for x in realized_pnls if x > 0]
    losses = [x for x in realized_pnls if x <= 0]

    total_trades = len(realized_pnls)
    win_rate = (len(wins) / total_trades) if total_trades > 0 else 0.0

    gross_profit = sum(wins) if wins else 0.0
    gross_loss = -sum(losses) if losses else 0.0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else None

    final_equity = float(equity_after_trade_execution)
    net_profit = float(final_equity - initial_capital)

    metrics = {
        "net_profit": net_profit,
        "final_equity": final_equity,
        "max_drawdown": float(max_drawdown),
        "total_trades": int(total_trades),
        "win_rate": float(win_rate),
        "gross_profit": float(gross_profit),
        "gross_loss": float(gross_loss),
        "profit_factor": float(profit_factor) if profit_factor is not None else None,
        "open_position_at_end": bool(open_position_at_end),
        **fee_metrics_meta(fee_rate, implementation="return_compound_roundtrip"),
    }

    return {
        "metrics": metrics,
        "trades": trades,
        "equity_series": equity_curve,
    }