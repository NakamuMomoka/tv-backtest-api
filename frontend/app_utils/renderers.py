from __future__ import annotations

import json
from typing import Any

import streamlit as st


def render_backtest_summary(run: dict[str, Any] | None, result: dict[str, Any] | None) -> None:
    if not run:
        return

    metrics = result.get("metrics", {}) if isinstance(result, dict) else {}
    net_profit = metrics.get("net_profit")
    trades = metrics.get("total_trades") or metrics.get("trades")
    win_rate = metrics.get("win_rate")
    fee_rate_used = metrics.get("fee_rate_used")
    if not isinstance(fee_rate_used, (int, float)):
        try:
            raw_settings = run.get("settings_json")
            settings = json.loads(raw_settings) if isinstance(raw_settings, str) and raw_settings else {}
            fee_rate_used = settings.get("fee_rate")
        except Exception:
            fee_rate_used = None

    fee_text = "-"
    if isinstance(fee_rate_used, (int, float)):
        fee_text = f"{float(fee_rate_used) * 100:.4f}% / side (fee_rate={float(fee_rate_used):.6f})"

    st.markdown(
        f"""
**Backtest Summary**  
- Run ID: `{run.get("id")}`  
- Status: `{run.get("status")}`  
- Dataset ID: `{run.get("dataset_id")}`  
- Strategy ID: `{run.get("strategy_id")}`  
- Fee: `{fee_text}`  
- Net Profit: `{net_profit}`  
- Trades: `{trades}`  
- Win Rate: `{win_rate}`
""",
    )


def render_optimization_summary(run: dict[str, Any] | None, result: dict[str, Any] | None) -> None:
    if not run:
        return

    fee_text = "-"
    try:
        raw_settings = run.get("settings_json")
        settings = json.loads(raw_settings) if isinstance(raw_settings, str) and raw_settings else {}
        fee_rate = settings.get("fee_rate")
        if isinstance(fee_rate, (int, float)):
            fee_text = f"{float(fee_rate) * 100:.4f}% / side (fee_rate={float(fee_rate):.6f})"
    except Exception:
        pass

    st.markdown(
        f"""
**Optimization Summary**  
- Run ID: `{run.get("id")}`  
- Status: `{run.get("status")}`  
- Dataset ID: `{run.get("dataset_id")}`  
- Strategy ID: `{run.get("strategy_id")}`  
- Fee: `{fee_text}`  
- search_mode: `{run.get("search_mode")}`  
- requested_trials: `{run.get("requested_trials")}`  
- executed_trials: `{run.get("executed_trials")}`  
- best_score: `{run.get("best_score")}`
""",
    )

