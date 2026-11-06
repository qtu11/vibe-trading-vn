"""Bounded, caller-declared dated-futures basis; no exchange access or carry PnL.

The annualisation is simple ACT/365F. Decimal arithmetic preserves signed basis
and quote units, while the existing fixed-income day-count primitive supplies
the UTC calendar-day component. The intraday component is added explicitly.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import json
import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.quantlib.fixedincome import year_fraction


_YEAR_SECONDS = Decimal(365 * 86400)
_TOKEN = r"^[A-Z0-9]{1,20}$"
_IDENTITY = r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,79}$"


def _timestamp(value: str) -> str:
    if (len(value) > 40 or re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})", value) is None):
        raise ValueError("Timestamps require an explicit timezone and ISO seconds")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (ValueError, OverflowError):
        raise ValueError("Timestamp is outside the supported range") from None
    if not 1900 <= parsed.year <= 2200:
        raise ValueError("Timestamp year must be within 1900..2200")
    return parsed.isoformat().replace("+00:00", "Z")


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _decimal(value: str) -> str:
    if len(value) > 48 or re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]{1,3})?", value) is None:
        raise ValueError("Prices must be positive bounded decimal strings")
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise ValueError("Prices must be valid decimals") from None
    if not number.is_finite() or not Decimal("1e-12") <= number <= Decimal("1e24"):
        raise ValueError("Prices must be within 1e-12..1e24")
    return _out(number)


def _out(value: Decimal) -> str:
    # The enclosing operation uses 48-digit precision. Never leak JSON floats,
    # NaN or -0, and never change a signed backwardation into a magnitude.
    rendered = format(value, "f")
    return "0" if not value else rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


def _seconds(delta) -> Decimal:
    return Decimal(delta.days * 86400 + delta.seconds) + Decimal(delta.microseconds) / Decimal(1000000)


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class BasisQuote(_Contract):
    venue: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,39}$")
    instrument_id: str = Field(pattern=_IDENTITY)
    base: str = Field(pattern=_TOKEN)
    quote: str = Field(pattern=_TOKEN)
    bid: str
    ask: str
    event_time: str
    available_at: str
    source_ref: str = Field(min_length=1, max_length=240)

    @field_validator("bid", "ask")
    @classmethod
    def price(cls, value):
        return _decimal(value)

    @field_validator("event_time", "available_at")
    @classmethod
    def time(cls, value):
        return _timestamp(value)

    @field_validator("source_ref")
    @classmethod
    def reference(cls, value):
        if (re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}", value)
                and value.partition(":")[0].lower() not in {"http", "https", "javascript", "data", "file", "vbscript"}):
            return value
        try:
            parsed = urlsplit(value)
            _ = parsed.port
            valid = (parsed.scheme in {"http", "https"} and parsed.hostname
                     and parsed.username is None and parsed.password is None
                     and not any(ord(char) <= 32 or ord(char) == 127 for char in value))
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("source_ref requires a bounded HTTP(S) URL without credentials, or an evidence ID")
        return value

    @model_validator(mode="after")
    def spread(self):
        if Decimal(self.ask) < Decimal(self.bid):
            raise ValueError("ask must be greater than or equal to bid")
        return self


class BasisSpot(BasisQuote):
    kind: Literal["spot"]


class BasisFuture(BasisQuote):
    kind: Literal["dated_future", "perpetual"]
    settle: str = Field(pattern=_TOKEN)
    linear: bool
    expiry: str | None

    @field_validator("expiry")
    @classmethod
    def expiry_time(cls, value):
        return _timestamp(value) if value is not None else None


class BasisPolicy(_Contract):
    max_quote_age_seconds: int = Field(ge=0, le=604800)
    max_pair_skew_seconds: int = Field(ge=0, le=86400)


class CryptoBasisRequest(_Contract):
    as_of: str
    base: str = Field(pattern=_TOKEN)
    quote: str = Field(pattern=_TOKEN)
    spot: BasisSpot
    futures: list[BasisFuture] = Field(min_length=1, max_length=12)
    policy: BasisPolicy

    @field_validator("as_of")
    @classmethod
    def time(cls, value):
        return _timestamp(value)

    @model_validator(mode="after")
    def identities(self):
        identities = [(row.venue, row.instrument_id) for row in self.futures]
        if len(identities) != len(set(identities)):
            raise ValueError("Futures venue/instrument identities must be unique")
        if self.base == self.quote:
            raise ValueError("base and quote must identify different assets")
        return self


def _time_reasons(quote: BasisQuote, as_of: datetime, policy: BasisPolicy, prefix: str) -> list[str]:
    event, available = _time(quote.event_time), _time(quote.available_at)
    reasons = []
    if event > as_of:
        reasons.append(prefix + "_event_after_cutoff")
    if available > as_of:
        reasons.append(prefix + "_unavailable_at_cutoff")
    if available < event:
        reasons.append(prefix + "_availability_before_event")
    if _seconds(as_of - event) > policy.max_quote_age_seconds:
        reasons.append(prefix + "_stale")
    return reasons


def _years(as_of: datetime, expiry: datetime) -> Decimal:
    # The canonical primitive is date-based. Add exact UTC intraday remainder;
    # do not pass datetimes to it, because timedelta.days truncates fractions.
    days = Decimal(str(year_fraction(as_of.date(), expiry.date(), "ACT/365F")))
    exact_days = Decimal((expiry.date() - as_of.date()).days) / Decimal(365)
    if abs(days - exact_days) > Decimal("1e-12"):
        raise ValueError("Canonical ACT/365F day-count invariant failed")
    start_midnight = as_of.replace(hour=0, minute=0, second=0, microsecond=0)
    end_midnight = expiry.replace(hour=0, minute=0, second=0, microsecond=0)
    # Decimal day count avoids retaining the primitive's binary float rounding.
    return exact_days + (_seconds(expiry - end_midnight) - _seconds(as_of - start_midnight)) / _YEAR_SECONDS


def build_crypto_basis(payload: dict) -> dict:
    """Validate shape, reject incompatible rows, and return a full <=12-row curve.

    This pure function fetches nothing and accepts no source paths, executable
    code or client-computed results. Historical availability is a declaration.
    """
    if not isinstance(payload, dict):
        raise ValueError("A Crypto basis JSON object is required")
    try:
        raw = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        byte_length = len(raw.encode("utf-8"))
    except (ValueError, TypeError, OverflowError, RecursionError):
        raise ValueError("Request must contain finite JSON values") from None
    if byte_length > 64000:
        raise ValueError("Crypto basis request exceeds 64000 bytes")
    request = CryptoBasisRequest.model_validate(payload)
    normalized = request.model_dump()
    canonical = json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    as_of, spot = _time(request.as_of), request.spot
    spot_reasons = _time_reasons(spot, as_of, request.policy, "spot")
    if (spot.base, spot.quote) != (request.base, request.quote):
        spot_reasons.append("spot_identity_mismatch")
    rows = []
    with localcontext() as context:
        context.prec = 48
        spot_mid = (Decimal(spot.bid) + Decimal(spot.ask)) / 2
        for index, future in enumerate(request.futures):
            reasons = [*spot_reasons, *_time_reasons(future, as_of, request.policy, "future")]
            if future.kind != "dated_future":
                reasons.append("perpetual_has_no_dated_basis")
            if not future.linear:
                reasons.append("nonlinear_contract_unsupported")
            if (future.base, future.quote, future.settle) != (request.base, request.quote, request.quote):
                reasons.append("future_identity_mismatch")
            if (future.venue, future.instrument_id) == (spot.venue, spot.instrument_id):
                reasons.append("spot_future_identity_conflict")
            expiry = _time(future.expiry) if future.expiry else None
            if expiry is None:
                reasons.append("expiry_missing")
            elif expiry <= as_of:
                reasons.append("expiry_not_after_cutoff")
            skew = abs(_seconds(_time(future.event_time) - _time(spot.event_time)))
            if skew > request.policy.max_pair_skew_seconds:
                reasons.append("quote_pair_skew_exceeded")
            row = {
                **future.model_dump(), "input_index": index,
                "status": "rejected" if reasons else "accepted", "reason_codes": reasons,
                "quote_age_seconds": _out(_seconds(as_of - _time(future.event_time))),
                "quote_skew_seconds": _out(skew),
                "seconds_to_expiry": None, "years_to_expiry": None,
                "mid_price": None, "basis_quote_per_base": None,
                "basis_fraction": None, "lower_basis_fraction": None, "upper_basis_fraction": None,
                "annualized_basis": None, "annualized_lower_basis": None, "annualized_upper_basis": None,
            }
            if not reasons:
                years = _years(as_of, expiry)
                future_mid = (Decimal(future.bid) + Decimal(future.ask)) / 2
                basis = future_mid / spot_mid - 1
                lower, upper = Decimal(future.bid) / Decimal(spot.ask) - 1, Decimal(future.ask) / Decimal(spot.bid) - 1
                row.update(seconds_to_expiry=_out(_seconds(expiry - as_of)), years_to_expiry=_out(years),
                           mid_price=_out(future_mid), basis_quote_per_base=_out(future_mid - spot_mid),
                           basis_fraction=_out(basis), lower_basis_fraction=_out(lower), upper_basis_fraction=_out(upper),
                           annualized_basis=_out(basis / years), annualized_lower_basis=_out(lower / years),
                           annualized_upper_basis=_out(upper / years))
            rows.append(row)
        rows.sort(key=lambda row: (row["expiry"] is None,
                                  _time(row["expiry"]) if row["expiry"] else datetime.max.replace(tzinfo=timezone.utc),
                                  row["venue"], row["instrument_id"]))
        result = {
            "ok": True, "market": "crypto", "schema_version": 1,
            "methodology": "caller_supplied_dated_futures_basis_v1",
            "base": request.base, "quote": request.quote, "as_of": request.as_of,
            "input_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            "verification_status": "user_supplied_unverified",
            "price_unit": f"{request.quote}/{request.base}", "day_count": "ACT/365F",
            "annualization": "simple basis / exact UTC years-to-expiry; rates are fractions, not percentages",
            "spot": {**spot.model_dump(), "mid_price": _out(spot_mid),
                     "quote_age_seconds": _out(_seconds(as_of - _time(spot.event_time)))},
            "policy": request.policy.model_dump(), "rows": rows,
            "summary": {"total": len(rows), "accepted": sum(row["status"] == "accepted" for row in rows),
                        "rejected": sum(row["status"] == "rejected" for row in rows)},
            "provenance": {"source_refs": sorted({spot.source_ref, *(row.source_ref for row in request.futures)}),
                           "source_verification": "Caller-declared identity, timestamps and references; no source was fetched or verified"},
            "limitations": [
                "Quoted gross price comparison, not an executable yield, trade recommendation, funding forecast or PnL ledger",
                "Bid/ask bounds exclude depth, fills, fees, financing, borrow, capital, margin, settlement and venue/custody risk",
                "No perpetual expiry is inferred; only matching linear quote-settled dated contracts can be accepted",
                "Availability and historical instrument identity are caller-declared, not independently reconstructed",
                "Near-expiry annualization can be very large; retain remaining seconds and unannualized basis",
                "Different venues may have different settlement/index methodology; matching ticker/currency does not verify fungibility",
            ],
        }
    if len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > 64000:
        raise ValueError("Crypto basis result exceeds 64000 bytes")
    return result
