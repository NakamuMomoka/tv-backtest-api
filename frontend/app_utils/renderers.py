from __future__ import annotations

from typing import Any

import streamlit as st


def render_backtest_summary(run: dict[str, Any] | None, result: dict[str, Any] | None) -> None:
    if not run:
        return

    metrics = result.get("metrics", {}) if isinstance(result, dict) else {}
    net_profit = metrics.get("net_profit")
    trades = metrics.get("total_trades") or metrics.get("trades")
    win_rate = metrics.get("win_rate")

    st.markdown(
        f"""
**Backtest Summary**  
- Run ID: `{run.get("id")}`  
- Status: `{run.get("status")}`  
- Dataset ID: `{run.get("dataset_id")}`  
- Strategy ID: `{run.get("strategy_id")}`  
- Net Profit: `{net_profit}`  
- Trades: `{trades}`  
- Win Rate: `{win_rate}`
""",
    )


def render_optimization_summary(run: dict[str, Any] | None, result: dict[str, Any] | None) -> None:
    if not run:
        return

    st.markdown(
        f"""
**Optimization Summary**  
- Run ID: `{run.get("id")}`  
- Status: `{run.get("status")}`  
- Dataset ID: `{run.get("dataset_id")}`  
- Strategy ID: `{run.get("strategy_id")}`  
- search_mode: `{run.get("search_mode")}`  
- requested_trials: `{run.get("requested_trials")}`  
- executed_trials: `{run.get("executed_trials")}`  
- best_score: `{run.get("best_score")}`
""",
    )

