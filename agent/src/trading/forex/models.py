"""Validated public contracts. Credentials never belong to tool arguments."""

from __future__ import annotations

import hashlib
import json
from pathlib import PureWindowsPath
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Identifier = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,57}$")]
Symbol = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._/+-]{0,63}$")]
RequestKey = Annotated[str, Field(pattern=r"^[A-Za-z0-9._~-]{5,128}$")]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def number(value: object, *, positive: bool = False) -> Decimal:
    if isinstance(value, bool) or len(str(value)) > 64:
        raise ValueError("Invalid decimal value")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Invalid decimal value") from exc
    if not result.is_finite() or abs(result.adjusted()) > 18:
        raise ValueError("Expected a finite, bounded decimal")
    if positive and result <= 0:
        raise ValueError("Expected a positive decimal")
    return result


def decimal_text(value: object) -> str:
    return format(number(value).normalize(), "f")


def broker_reference(intent_id: str) -> str:
    """A bounded, unique broker correlation tag, independent of caller request keys."""
    return "vfx-" + hashlib.sha256(intent_id.encode()).hexdigest()[:24]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class Limits(Contract):
    max_order_notional_usd: str = "1000"
    max_total_exposure_usd: str = "3000"
    max_stop_risk_usd: str = "10"
    max_equity_drawdown_usd: str = "50"
    max_quantity: str = "0.01"
    max_spread_points: str = "30"
    max_leverage: str = "2"
    max_deviation_points: int = Field(default=20, ge=0, le=100)
    max_quote_age_seconds: int = Field(default=10, ge=1, le=60)
    max_orders_per_day: int = Field(default=5, ge=1, le=100)

    @field_validator(
        "max_order_notional_usd",
        "max_total_exposure_usd",
        "max_stop_risk_usd",
        "max_equity_drawdown_usd",
        "max_quantity",
        "max_spread_points",
        "max_leverage",
    )
    @classmethod
    def positive(cls, value: str) -> str:
        return format(number(value, positive=True).normalize(), "f")


class Connection(Contract):
    id: Identifier
    label: str = Field(min_length=1, max_length=120)
    connector: Literal["mt5", "exness", "oanda"]
    account_ref: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9-]+$")
    environment: Literal["demo", "live"] = "demo"
    execution_enabled: bool = False
    symbols: tuple[Symbol, ...] = Field(default=(), max_length=50)
    terminal_path: str = Field(default="", max_length=500)
    session_mode: Literal["credentials", "existing_terminal"] = "credentials"
    server: str = Field(default="", max_length=120)
    gateway_url: str = Field(default="", max_length=300)
    allowed_hosts: tuple[str, ...] = Field(default=(), max_length=20)
    limits: Limits = Field(default_factory=Limits)

    @model_validator(mode="after")
    def binding(self):
        if self.connector == "mt5":
            if not self.account_ref.isdigit() or not self.server:
                raise ValueError("MT5 needs a numeric account login and explicit broker server")
            path = PureWindowsPath(self.terminal_path)
            if not path.is_absolute() or path.name.lower() != "terminal64.exe":
                raise ValueError("MT5 requires an absolute path to terminal64.exe")
        if self.connector == "exness":
            if self.environment != "live":
                raise ValueError("Exness API demo eligibility is unverified; use an MT5 demo account")
            if not self.gateway_url or not self.allowed_hosts or not self.account_ref.isdigit():
                raise ValueError("Exness requires numeric account ID, Gateway and approved hosts")
        if self.execution_enabled and not self.symbols:
            raise ValueError("Select explicit native symbols before enabling execution")
        return self

    @property
    def mandate_key(self) -> str:
        return "forex-" + self.id

    def fingerprint(self) -> str:
        return digest(self.model_dump(mode="json"))


class Order(Contract):
    action: Literal["open", "close"] = "open"
    position_ticket: str | None = Field(default=None, pattern=r"^[1-9][0-9]{0,19}$")
    symbol: Symbol
    side: Literal["buy", "sell"]
    quantity: str
    stop_loss: str | None = None
    take_profit: str | None = None
    request_key: RequestKey
    expires_at: datetime
    strategy_revision: str = Field(default="manual-v1", min_length=1, max_length=100)

    @field_validator("quantity", "stop_loss", "take_profit")
    @classmethod
    def price(cls, value: str | None) -> str | None:
        return None if value is None else format(number(value, positive=True).normalize(), "f")

    @field_validator("expires_at")
    @classmethod
    def expiry(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Expiry must include a timezone")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def action_fields(self):
        if self.action == "open" and (self.stop_loss is None or self.position_ticket is not None):
            raise ValueError("Opening requires stop_loss and cannot target a position")
        if self.action == "close" and (
            not self.position_ticket or self.stop_loss is not None or self.take_profit is not None
        ):
            raise ValueError("Closing requires a position ticket and cannot modify SL/TP")
        return self


class AIStrategy(Contract):
    symbol: Symbol
    quantity: str = "0.01"
    timeframe: Literal["5m", "15m", "1h", "4h"] = "5m"
    lookback: int = Field(default=60, ge=35, le=120)
    interval_seconds: int = Field(default=60, ge=30, le=3600)
    minimum_confidence: float = Field(default=0.75, ge=0.5, le=1, allow_inf_nan=False)

    @field_validator("quantity")
    @classmethod
    def positive(cls, value: str) -> str:
        return decimal_text(number(value, positive=True))


class Strategy(Contract):
    symbol: Symbol
    quantity: str
    timeframe: Literal["5m", "15m", "1h", "4h"] = "15m"
    fast: int = Field(default=10, ge=2, le=100)
    slow: int = Field(default=30, ge=3, le=200)
    stop_distance_points: int = Field(default=200, ge=1, le=100000)
    reward_ratio: str = "2"
    interval_seconds: int = Field(default=60, ge=15, le=3600)

    @field_validator("quantity", "reward_ratio")
    @classmethod
    def positive(cls, value: str) -> str:
        return format(number(value, positive=True).normalize(), "f")

    @model_validator(mode="after")
    def windows(self):
        if self.fast >= self.slow:
            raise ValueError("fast must be smaller than slow")
        return self


def digest(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
