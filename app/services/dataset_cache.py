from __future__ import annotations

from pathlib import Path
from typing import Tuple

import pandas as pd


_DATASET_CACHE: dict[Path, Tuple[int, pd.DataFrame]] = {}


def get_dataset_bars(path: Path) -> pd.DataFrame:
    """
    Load dataset CSV as pandas.DataFrame with simple caching.

    Cache key is (Path, st_mtime_ns). If the file is updated, it is reloaded.
    A copy of the cached DataFrame is always returned so callers can modify it safely.
    """
    current_mtime = path.stat().st_mtime_ns

    cached = _DATASET_CACHE.get(path)
    if cached is not None:
        cached_mtime, cached_df = cached
        if cached_mtime == current_mtime:
            return cached_df.copy(deep=True)

    df = pd.read_csv(path)
    _DATASET_CACHE[path] = (current_mtime, df)
    return df.copy(deep=True)

