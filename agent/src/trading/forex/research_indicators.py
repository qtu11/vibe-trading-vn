"""Causal offline indicators, sharing the existing SMA-seeded Wilder average."""

import pandas as pd

from src.shadow_account.indicators import _wilder_average


def atr_series(rows: list[dict], period: int) -> pd.Series:
    """Validated OHLC -> Wilder ATR, seeded by the first period true ranges.

    The first true range is high-low; later ranges include the preceding close.
    NaN marks warmup only. Caller supplies validated chronological closed bars.
    """
    if type(period) is not int or period < 1:
        raise ValueError("ATR period must be a positive integer")
    high = pd.Series([row["high"] for row in rows], dtype=float)
    low = pd.Series([row["low"] for row in rows], dtype=float)
    close = pd.Series([row["close"] for row in rows], dtype=float)
    ranges = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    return _wilder_average(ranges, period)
