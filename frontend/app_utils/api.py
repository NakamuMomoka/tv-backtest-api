from __future__ import annotations

from typing import Any, Tuple

import requests
import streamlit as st


def init_session_state() -> None:
    """Initialize common session_state keys."""
    for key in ("last_backtest_id", "last_optimization_id", "last_wf_id"):
        st.session_state.setdefault(key, None)
    st.session_state.setdefault("base_url", "http://localhost:8000")


def get_base_url() -> str:
    """Get API base URL from session_state."""
    return st.session_state.get("base_url", "http://localhost:8000")


def fetch(
    method: str,
    path: str,
    **kwargs: Any,
) -> Tuple[int, Any]:
    """Low-level HTTP helper that supports json/params/files/data など任意の kwargs.

    戻り値は (status_code, body) で、body は JSON パース成功時は Python オブジェクト、
    失敗時はテキストのまま返します。
    """
    base = get_base_url().rstrip("/")
    url = f"{base}{path}"
    try:
        resp = requests.request(method, url, timeout=60, **kwargs)
    except Exception as exc:  # noqa: BLE001
        return 0, f"Request error: {exc}"

    try:
        return resp.status_code, resp.json()
    except Exception:  # noqa: BLE001
        return resp.status_code, resp.text


def fetch_json(
    method: str,
    path: str,
    *,
    json: dict | None = None,
    params: dict | None = None,
) -> Tuple[int, Any]:
    """JSON API 用の薄い wrapper（既存 UI との互換用）。"""
    return fetch(method, path, json=json, params=params)


def load_datasets() -> list[dict]:
    status, data = fetch_json("GET", "/datasets")
    return data if status == 200 and isinstance(data, list) else []


def load_strategies() -> list[dict]:
    status, data = fetch_json("GET", "/strategies")
    return data if status == 200 and isinstance(data, list) else []

