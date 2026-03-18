from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def to_jsonable(value: Any) -> Any:
    """Recursively convert values to JSON-serializable types."""
    # Basic primitives are already JSON-serializable
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    # datetime / date / pandas.Timestamp -> ISO 8601 string
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()

    # pathlib.Path -> str
    if isinstance(value, Path):
        return str(value)

    # numpy scalar types
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)

    # Mapping (dict-like)
    if isinstance(value, Mapping):
        return {str(k): to_jsonable(v) for k, v in value.items()}

    # Sequence (list / tuple) but not string/bytes
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [to_jsonable(v) for v in value]

    # Fallback: string representation
    return str(value)

