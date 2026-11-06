"""Bounded VN DCF scenarios using the existing valuation engine, never forecasts.

All identities, evidence and availability are caller-declared. Money alone is
scaled into VND; share counts and rates are never scaled. The sensitivity grid
uses the exact FCFF bridge from the base run and quantlib's full equity bridge.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import inspect
import json
import math
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.quantlib.valuation import contracts as _contracts
from src.quantlib.valuation import dcf as _dcf
from src.quantlib.valuation.contracts import Assumption
from src.tools.local_financial_statements import _timestamp
from src.tools.vietnam_comparables import ComparablesEvidence


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


def _decimal(value: str) -> str:
    if (len(value) > 48
            or re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?", value) is None):
        raise ValueError("Amounts must be bounded decimal strings")
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise ValueError("Amounts must be valid bounded decimals") from None
    if not number.is_finite() or number.copy_abs() > Decimal("1e24") or (number and number.copy_abs() < Decimal("1e-12")):
        raise ValueError("Amounts must have magnitude zero or 1e-12..1e24")
    with localcontext() as context:
        context.prec = 80
        return "0" if not number else format(number.normalize(), "f")


class _Justified(_Contract):
    basis: str = Field(min_length=1, max_length=400)
    source_ids: list[str] = Field(max_length=12, description="Declared evidence IDs; [] explicitly identifies an unsupported analyst scenario")

    @field_validator("basis")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("An explicit nonblank basis is required")
        return value

    @field_validator("source_ids")
    @classmethod
    def source_names(cls, values):
        if len(set(values)) != len(values) or any(re.fullmatch(r"[A-Za-z0-9_-]{1,40}", item) is None for item in values):
            raise ValueError("source_ids must contain unique bounded evidence IDs")
        return values


class DCFScalar(_Justified):
    value: float = Field(ge=-10, le=100, allow_inf_nan=False)


class DCFEvidence(ComparablesEvidence):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,40}$")


class DCFForecastYear(_Justified):
    year: int = Field(ge=1, le=10, description="Relative full forecast period, not a calendar year")
    ebit: str
    depreciation_amortization: str
    capex: str
    delta_nwc: str

    @field_validator("ebit", "depreciation_amortization", "capex", "delta_nwc")
    @classmethod
    def amount(cls, value):
        return _decimal(value)

    @model_validator(mode="after")
    def magnitudes(self):
        if Decimal(self.depreciation_amortization) < 0 or Decimal(self.capex) < 0:
            raise ValueError("D&A and capex require nonnegative magnitudes; delta_nwc is signed")
        return self


class DCFWACC(_Contract):
    risk_free_rate: DCFScalar
    beta: DCFScalar
    equity_risk_premium: DCFScalar
    pretax_cost_of_debt: DCFScalar
    tax_rate: DCFScalar
    size_premium: DCFScalar
    country_risk_premium: DCFScalar


class DCFCapitalStructure(_Justified):
    kind: Literal["target", "current"]
    target_equity_weight: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    target_debt_weight: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    market_value_of_equity: str | None = None
    market_value_of_debt: str | None = None

    @field_validator("market_value_of_equity", "market_value_of_debt")
    @classmethod
    def amount(cls, value):
        if value is not None:
            value = _decimal(value)
            if Decimal(value) < 0:
                raise ValueError("Capital-structure values require nonnegative magnitudes")
        return value

    @model_validator(mode="after")
    def complete(self):
        weights = (self.target_equity_weight, self.target_debt_weight)
        market = (self.market_value_of_equity, self.market_value_of_debt)
        if self.kind == "target":
            if None in weights or any(item is not None for item in market):
                raise ValueError("Target structure requires both weights and no current market values")
            if not math.isclose(sum(weights), 1.0, rel_tol=0, abs_tol=1e-6):
                raise ValueError("Target capital weights must sum to one")
        elif None in market or any(item is not None for item in weights):
            raise ValueError("Current structure requires both market values and no target weights")
        return self


class DCFEquityBridge(_Justified):
    snapshot_date: str
    total_debt: str
    unrestricted_cash: str
    restricted_cash: str
    minority_interest: str
    preferred_equity: str
    associate_investments: str
    diluted_shares: str = Field(description="Actual share count; amount_scale is never applied")
    share_basis_note: str = Field(min_length=1, max_length=400)
    associate_earnings_excluded_from_forecast: Literal[True]

    @field_validator("snapshot_date")
    @classmethod
    def snapshot(cls, value):
        if len(value) != 10:
            raise ValueError("snapshot_date must be YYYY-MM-DD")
        return date.fromisoformat(value).isoformat()

    @field_validator("total_debt", "unrestricted_cash", "restricted_cash", "minority_interest", "preferred_equity", "associate_investments", "diluted_shares")
    @classmethod
    def magnitude(cls, value):
        value = _decimal(value)
        if Decimal(value) < 0:
            raise ValueError("Equity-bridge fields require nonnegative magnitudes")
        return value

    @field_validator("share_basis_note")
    @classmethod
    def note(cls, value):
        if not value.strip():
            raise ValueError("A nonblank diluted-share/corporate-action note is required")
        return value

    @field_validator("associate_earnings_excluded_from_forecast", mode="before")
    @classmethod
    def no_double_count(cls, value):
        if value is not True:
            raise ValueError("Explicitly confirm associate earnings are excluded from forecast EBIT")
        return value

    @model_validator(mode="after")
    def usable(self):
        if not self.source_ids:
            raise ValueError("The equity bridge requires at least one declared evidence reference")
        if not Decimal("1") <= Decimal(self.diluted_shares) <= Decimal("1e18"):
            raise ValueError("diluted_shares must be an actual count in 1..1e18")
        return self


class DCFSensitivity(_Contract):
    wacc_values: list[float] = Field(min_length=1, max_length=9)
    growth_values: list[float] = Field(min_length=1, max_length=9)
    basis: str = Field(min_length=1, max_length=400)

    @field_validator("wacc_values", "growth_values")
    @classmethod
    def bounded_axis(cls, values):
        if any(not math.isfinite(item) or not -0.99 <= item <= 1 for item in values):
            raise ValueError("Sensitivity rates must be finite decimal fractions in -0.99..1")
        if values != sorted(set(values)):
            raise ValueError("Sensitivity axes must be strictly increasing with no duplicates")
        return values

    @field_validator("basis")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Sensitivity requires an explicit range basis")
        return value


class VietnamDCFRequest(_Contract):
    schema_version: Literal[1]
    symbol: str = Field(pattern=r"^[A-Z0-9]{1,12}\.VN$")
    venue: Literal["HOSE", "HNX", "UPCOM"]
    as_of: str = Field(max_length=64)
    currency: Literal["VND"]
    amount_scale: Literal[1, 1000, 1000000, 1000000000]
    business_model: Literal["non_financial"]
    consolidation: Literal["consolidated"]
    discounting_convention: Literal["mid_year", "year_end"]
    terminal_value_method: Literal["perpetuity_growth", "exit_multiple"]
    wacc: DCFWACC
    capital_structure: DCFCapitalStructure
    terminal_growth: DCFScalar
    exit_multiple: DCFScalar
    gdp_growth_reference: DCFScalar
    forecast: list[DCFForecastYear] = Field(min_length=1, max_length=10)
    equity_bridge: DCFEquityBridge
    sensitivity: DCFSensitivity
    evidence: list[DCFEvidence] = Field(min_length=1, max_length=12)

    @field_validator("schema_version", "amount_scale", mode="before")
    @classmethod
    def integer_literal(cls, value):
        if type(value) is not int:
            raise ValueError("Version and monetary scale must be explicit integers")
        return value

    @field_validator("as_of")
    @classmethod
    def cutoff(cls, value):
        return _timestamp(value, "as_of").isoformat().replace("+00:00", "Z")

    @model_validator(mode="after")
    def coherent(self):
        if [item.year for item in self.forecast] != list(range(1, len(self.forecast) + 1)):
            raise ValueError("Forecast periods must be contiguous and ordered from relative year 1")
        if not 0 <= self.wacc.tax_rate.value <= 1:
            raise ValueError("tax_rate must be a decimal fraction in 0..1")
        rate_inputs = [getattr(self.wacc, name) for name in DCFWACC.model_fields if name != "beta"]
        if any(not -0.99 <= item.value <= 1 for item in [*rate_inputs, self.terminal_growth, self.gdp_growth_reference]):
            raise ValueError("Rates must be decimal fractions in -0.99..1; percentages are not converted")
        if self.exit_multiple.value <= 0:
            raise ValueError("exit_multiple must be positive")
        by_id = {item.id: item for item in self.evidence}
        if len(by_id) != len(self.evidence):
            raise ValueError("Evidence IDs must be unique")
        justified = [*self.forecast, self.equity_bridge, self.capital_structure,
                     *[getattr(self.wacc, name) for name in DCFWACC.model_fields],
                     self.terminal_growth, self.exit_multiple, self.gdp_growth_reference]
        if any(source not in by_id for item in justified for source in item.source_ids):
            raise ValueError("Every source_id must reference declared evidence")
        cutoff = _timestamp(self.as_of, "as_of")
        for item in self.evidence:
            if _timestamp(item.available_at, "available_at") > cutoff:
                raise ValueError("Evidence was not declared available at as_of")
        snapshot = date.fromisoformat(self.equity_bridge.snapshot_date)
        if snapshot > cutoff.date():
            raise ValueError("The equity-bridge snapshot follows as_of")
        if any(_timestamp(by_id[name].published_at, "published_at").date() < snapshot for name in self.equity_bridge.source_ids):
            raise ValueError("Equity-bridge evidence predates its snapshot")
        return self


def _scaled_money(value: str, scale: int) -> float:
    with localcontext() as context:
        context.prec = 80
        return float(Decimal(value) * scale)


def _prepare_dcf_inputs(request: VietnamDCFRequest) -> dict:
    """Share the exact money, share and assumption bridge with reverse DCF."""
    def money(value):
        return _scaled_money(value, request.amount_scale)
    bridge = request.equity_bridge
    inputs = {name: getattr(request.wacc, name).value for name in DCFWACC.model_fields}
    for name in ("ebit", "depreciation_amortization", "capex", "delta_nwc"):
        inputs[name] = [money(getattr(year, name)) for year in request.forecast]
    for name in ("terminal_growth", "exit_multiple"):
        declared = getattr(request, name)
        inputs[name] = Assumption(name, declared.value, declared.basis,
                                  ",".join(declared.source_ids) or None)
    for name in ("total_debt", "minority_interest", "preferred_equity", "associate_investments"):
        inputs[name] = money(getattr(bridge, name))
    inputs["cash_and_equivalents"] = money(bridge.unrestricted_cash)
    inputs["diluted_shares"] = float(bridge.diluted_shares)
    structure = request.capital_structure
    if structure.kind == "target":
        inputs.update(target_equity_weight=structure.target_equity_weight,
                      target_debt_weight=structure.target_debt_weight)
    else:
        inputs.update(market_value_of_equity=money(structure.market_value_of_equity),
                      market_value_of_debt=money(structure.market_value_of_debt))
    return inputs


def build_vietnam_dcf(payload: dict) -> dict:
    """Validate one explicit scenario; compute a DCF and a separate growth grid.

    Raises ValueError/ValidationError for invalid inputs. Reads no issuer files,
    fetches no data, writes nothing, and never constructs projections implicitly.
    """
    try:
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, OverflowError, RecursionError):
        raise ValueError("DCF payload must be finite JSON data") from None
    if len(encoded.encode("utf-8")) > 64_000:
        raise ValueError("DCF payload exceeds the 64000-byte input budget")
    request = VietnamDCFRequest.model_validate(payload)
    normalized = request.model_dump()
    input_hash = hashlib.sha256(json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    inputs = _prepare_dcf_inputs(request)
    structure = request.capital_structure
    result = _dcf.run_dcf(inputs, capital_structure_basis=structure.kind,
                          discounting_convention=request.discounting_convention,
                          terminal_value_method=request.terminal_value_method,
                          gdp_growth_ceiling=request.gdp_growth_reference.value)
    fixed_bridge = {name: inputs[name] for name in ("total_debt", "cash_and_equivalents", "minority_interest",
                                                   "preferred_equity", "associate_investments", "diluted_shares")}
    grid = _dcf.sensitivity_grid(result.fcff_bridge, wacc_values=request.sensitivity.wacc_values,
                                 growth_values=request.sensitivity.growth_values,
                                 discounting_convention=request.discounting_convention, **fixed_bridge)
    cells = []
    for row, wacc in enumerate(request.sensitivity.wacc_values):
        cells.append([{"wacc": wacc, "terminal_growth": growth,
                       "value_per_share_vnd": None if growth >= wacc else float(grid.iloc[row, col]),
                       "reason": "growth_must_be_below_wacc" if growth >= wacc else None}
                      for col, growth in enumerate(request.sensitivity.growth_values)])
    model_version = hashlib.sha256((inspect.getsource(_dcf) + inspect.getsource(_contracts)
                                    + inspect.getsource(inspect.getmodule(build_vietnam_dcf))).encode()).hexdigest()
    output = {
        "ok": True, "market": "vn", "methodology": "declared_non_financial_fcff_scenario",
        "symbol": request.symbol, "venue": request.venue, "as_of": request.as_of,
        "currency": "VND", "money_output_unit": "VND", "per_share_output_unit": "VND_per_share",
        "input_amount_scale": request.amount_scale, "share_count_unit": "actual_shares",
        "input_sha256": input_hash, "model_version": model_version,
        "normalized_inputs": normalized, "base_case": asdict(result),
        "excluded_restricted_cash_vnd": _scaled_money(request.equity_bridge.restricted_cash, request.amount_scale),
        "sensitivity": {"terminal_value_method": "perpetuity_growth", "wacc_values": request.sensitivity.wacc_values,
                        "growth_values": request.sensitivity.growth_values, "basis": request.sensitivity.basis,
                        "cells": cells, "probabilities_assigned": False},
        "historical_reconstruction": any(_timestamp(item.retrieved_at, "retrieved_at") > _timestamp(request.as_of, "as_of")
                                         for item in request.evidence),
        "limitations": [
            "Identities, business-model suitability, evidence, document hashes and availability are caller-declared and unverified; no source is fetched.",
            "Forecasts and rates are analyst scenarios with explicit bases; the software supplies no growth, tax, risk-premium or valuation defaults.",
            "Relative forecast years are equal full-year intervals from valuation time; calendar stubs, actual-day discounting and interim cash flows are unsupported.",
            "Only consolidated non-financial FCFF is supported; bank/insurance capital and dividend models are unavailable.",
            "Restricted cash is reported separately and excluded from the additive cash bridge; debt, minority/preferred claims, associates and dilution remain caller-reconciled.",
            "Associate investments are added only under the caller's explicit declaration that their earnings are absent from forecast EBIT; this is not independently verified.",
            "The sensitivity is always perpetuity-growth, including when the base case selects exit-multiple; each cell reuses fixed FCFF, tax and bridge inputs and carries no probability.",
            "The result is a conditional valuation scenario, not a verified fair value, current market price or investment recommendation.",
            "Quantlib arithmetic uses floating point; input hashes identify canonical declared inputs and the model hash identifies adapter, DCF and contract source code.",
        ],
    }
    # Bounds keep ordinary scenarios finite; never serialize a numerical failure
    # as a plausible missing or zero valuation.
    try:
        json.dumps(output, allow_nan=False)
    except (ValueError, OverflowError):
        raise ValueError("DCF arithmetic produced a non-finite result") from None
    return output
