"""Shared closed, contiguous mid-bar contract for offline Forex research."""

from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .models import Contract, Symbol, number, utcnow
from .runner import INTERVAL_SECONDS

BAR_INTERVAL_SECONDS = {**INTERVAL_SECONDS, "1m": 60, "30m": 1800, "1d": 86400}


class ResearchBar(Contract):
    time: datetime
    open: float = Field(ge=1e-12, le=1e12, allow_inf_nan=False)
    high: float = Field(ge=1e-12, le=1e12, allow_inf_nan=False)
    low: float = Field(ge=1e-12, le=1e12, allow_inf_nan=False)
    close: float = Field(ge=1e-12, le=1e12, allow_inf_nan=False)
    complete: Literal[True]

    @field_validator("open", "high", "low", "close", mode="before")
    @classmethod
    def price(cls, value):
        return float(number(value, positive=True))

    @field_validator("time", mode="before")
    @classmethod
    def timestamp_type(cls, value):
        if not isinstance(value, (str, datetime)):
            raise ValueError("Bar time must be an ISO timestamp with a timezone")
        return value

    @field_validator("time")
    @classmethod
    def timestamp(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Bar time must include a timezone")
        try:
            return value.astimezone(timezone.utc)
        except (ValueError, OverflowError) as exc:
            raise ValueError("Bar timestamp is outside the supported UTC range") from exc

    @field_validator("complete", mode="before")
    @classmethod
    def completed(cls, value):
        if value is not True:
            raise ValueError("Only explicitly complete bars are accepted")
        return value

    @model_validator(mode="after")
    def ohlc(self):
        if not self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high:
            raise ValueError("OHLC must satisfy low <= open/close <= high")
        return self


class ClosedBarDataset(Contract):
    source: str = Field(min_length=1, max_length=120)
    symbol: Symbol
    timeframe: Literal["1m", "5m", "15m", "30m", "1h", "4h", "1d"]
    price_basis: Literal["mid"]
    dataset_revision: str = Field(min_length=1, max_length=120)
    bars: tuple[ResearchBar, ...] = Field(min_length=32, max_length=2000)

    @model_validator(mode="after")
    def chronology(self):
        interval = timedelta(seconds=BAR_INTERVAL_SECONDS[self.timeframe])
        if any(right.time - left.time != interval for left, right in zip(self.bars, self.bars[1:])):
            raise ValueError("Bars must be ordered, unique and contiguous for the declared timeframe")
        try:
            if self.bars[-1].time + interval > utcnow():
                raise ValueError("The final bar must have closed already")
        except OverflowError as exc:
            raise ValueError("Bar close timestamp is outside the supported UTC range") from exc
        return self
