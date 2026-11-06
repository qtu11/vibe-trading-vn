"""Price-implied terminal growth from the existing FCFF engine, never forecasts."""

from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal, localcontext
import hashlib
import inspect
import json
import math
from typing import Literal

from pydantic import Field, field_validator, model_validator

from src.quantlib.valuation import contracts as _contracts
from src.quantlib.valuation import dcf as _dcf
from src.tools.local_financial_statements import _timestamp
from src.tools import vietnam_dcf as _adapter
from src.tools.vietnam_dcf import DCFEvidence, VietnamDCFRequest, _Contract, _decimal, _prepare_dcf_inputs


class GrowthBracket(_Contract):
    lower: float = Field(ge=-0.99, le=1, allow_inf_nan=False)
    upper: float = Field(ge=-0.99, le=1, allow_inf_nan=False)
    basis: str = Field(min_length=1, max_length=400)

    @model_validator(mode="after")
    def ordered(self):
        if self.lower >= self.upper or not self.basis.strip():
            raise ValueError("Growth bracket must increase and have an explicit nonblank basis")
        return self


class VietnamReverseDCFRequest(_Contract):
    schema_version: Literal[1]
    dcf: VietnamDCFRequest
    target_price_vnd: str
    price_observed_at: str = Field(max_length=64)
    price_evidence: DCFEvidence
    share_basis_note: str = Field(min_length=1, max_length=400)
    growth_bracket: GrowthBracket
    tolerance_vnd_per_share: str

    @field_validator("schema_version", mode="before")
    @classmethod
    def integer_version(cls, value):
        if type(value) is not int:
            raise ValueError("schema_version must be an integer")
        return value

    @field_validator("target_price_vnd", "tolerance_vnd_per_share")
    @classmethod
    def positive_decimal(cls, value):
        value = _decimal(value)
        if Decimal(value) <= 0:
            raise ValueError("Target price and tolerance must be positive VND-per-share decimals")
        return value

    @field_validator("price_observed_at")
    @classmethod
    def observed(cls, value):
        return _timestamp(value, "price_observed_at").isoformat().replace("+00:00", "Z")

    @model_validator(mode="after")
    def coherent(self):
        if not self.share_basis_note.strip():
            raise ValueError("Price and diluted-share comparability require a nonblank basis note")
        if self.dcf.terminal_value_method != "perpetuity_growth":
            raise ValueError("Reverse growth requires a perpetuity-growth base, not an exit multiple")
        cutoff = _timestamp(self.dcf.as_of, "as_of")
        observed = _timestamp(self.price_observed_at, "price_observed_at")
        if (observed > cutoff or _timestamp(self.price_evidence.available_at, "available_at") > cutoff
                or _timestamp(self.price_evidence.published_at, "published_at") < observed):
            raise ValueError("Price evidence must follow the observed price and be available by as_of")
        return self


def build_vietnam_reverse_dcf(payload: dict) -> dict:
    try:
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, OverflowError, RecursionError):
        raise ValueError("Reverse DCF requires finite JSON data") from None
    if len(encoded.encode("utf-8")) > 64_000:
        raise ValueError("Reverse DCF exceeds the 64000-byte input budget")
    request = VietnamReverseDCFRequest.model_validate(payload)
    normalized = request.model_dump()
    inputs = _prepare_dcf_inputs(request.dcf)
    base = _dcf.run_dcf(inputs, capital_structure_basis=request.dcf.capital_structure.kind,
                        discounting_convention=request.dcf.discounting_convention,
                        terminal_value_method="perpetuity_growth",
                        gdp_growth_ceiling=request.dcf.gdp_growth_reference.value)
    wacc = base.wacc_build.wacc
    lower, upper = request.growth_bracket.lower, request.growth_bracket.upper
    if upper >= wacc or math.isclose(upper, wacc, rel_tol=0, abs_tol=1e-12):
        raise ValueError("The growth bracket must be more than 1e-12 below the fixed WACC")
    bridge = {name: inputs[name] for name in ("total_debt", "cash_and_equivalents", "minority_interest",
                                            "preferred_equity", "associate_investments", "diluted_shares")}

    def price(growth):
        value = float(_dcf.sensitivity_grid(base.fcff_bridge, wacc_values=[wacc], growth_values=[growth],
                       discounting_convention=request.dcf.discounting_convention, **bridge).iloc[0, 0])
        if not math.isfinite(value):
            raise ValueError("Reverse DCF produced a non-finite valuation")
        return value

    target, tolerance = Decimal(request.target_price_vnd), Decimal(request.tolerance_vnd_per_share)

    def residual(value):
        # Match the JSON-visible floating-point price to the full declared
        # decimal target. Rounding both to float could falsely report zero.
        with localcontext() as context:
            context.prec = 80
            return Decimal(str(value)) - target

    def converged(value):
        return residual(value).copy_abs() <= tolerance
    low_value, high_value = price(lower), price(upper)
    endpoints = [{"growth": lower, "value_per_share_vnd": low_value},
                 {"growth": upper, "value_per_share_vnd": high_value}]
    status, reason, solution, iterations = "outside_bracket", "target_outside_supplied_bracket", None, 0
    last_growth, last_value = None, None
    if base.fcff_bridge[-1].fcff == 0:
        status, reason = "non_identifiable", "zero_terminal_fcff_growth_does_not_change_price"
    elif low_value == high_value:
        status, reason = "non_identifiable", "numeric_resolution_cannot_distinguish_bracket_prices"
    elif (min(Decimal(str(low_value)), Decimal(str(high_value))) <= target <= max(Decimal(str(low_value)), Decimal(str(high_value)))
          or converged(low_value) or converged(high_value)):
        status, reason = "iteration_limit", "price_tolerance_not_met"
        for candidate, value in ((lower, low_value), (upper, high_value)):
            if converged(value):
                last_growth, last_value, solution, status, reason = candidate, value, candidate, "solved", None
                break
        if status != "solved":
            increasing = high_value > low_value
            for iterations in range(1, 129):
                middle = lower + (upper - lower) / 2
                last_growth, last_value = middle, price(middle)
                if converged(last_value):
                    solution, status, reason = middle, "solved", None
                    break
                if middle == lower or middle == upper:
                    reason = "numeric_resolution_limit"
                    break
                if (Decimal(str(last_value)) < target) == increasing:
                    lower = middle
                else:
                    upper = middle
    model_version = hashlib.sha256("".join(inspect.getsource(module) for module in
                                           (_dcf, _contracts, _adapter, inspect.getmodule(build_vietnam_reverse_dcf))).encode()).hexdigest()
    output = {
        "ok": True, "market": "vn", "methodology": "fixed_fcff_price_implied_terminal_growth",
        "symbol": request.dcf.symbol, "venue": request.dcf.venue, "as_of": request.dcf.as_of,
        "verification_status": "user_supplied_unverified", "currency": "VND", "price_unit": "VND_per_share",
        "input_sha256": hashlib.sha256(json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest(),
        "model_version": model_version, "normalized_inputs": normalized, "base_case": asdict(base),
        "target_price_vnd": request.target_price_vnd, "fixed_wacc": wacc,
        "solver": {"status": status, "reason": reason, "implied_terminal_growth": solution,
                   "iterations": iterations, "maximum_iterations": 128, "minimum_wacc_separation": 1e-12, "endpoints": endpoints,
                   "final_bracket": {"lower": lower, "upper": upper}, "last_evaluated_growth": last_growth,
                   "repriced_value_per_share_vnd": last_value,
                   "residual_vnd_per_share": None if last_value is None else format(residual(last_value), "f"),
                   "tolerance_vnd_per_share": request.tolerance_vnd_per_share},
        "historical_reconstruction": any(_timestamp(item.retrieved_at, "retrieved_at") > _timestamp(request.dcf.as_of, "as_of")
                                         for item in [*request.dcf.evidence, request.price_evidence]),
        "limitations": [
            "The implied growth solves one supplied price under fixed forecasts, WACC, tax and equity bridge; it is not a growth forecast or investment recommendation.",
            "Prices, financial evidence, share comparability and availability remain caller-declared and unverified; no source is fetched.",
            "Target price and tolerance are full VND per actual diluted share, never multiplied by the DCF money scale.",
            "Only the explicit bracket is searched; no extrapolation, probability or exit-multiple growth interpretation is supplied.",
            "The solver uses floating-point bisection and full quantlib equity bridges; numeric resolution can prevent the requested price tolerance.",
            "Convergence and the decimal-string residual compare the JSON-visible engine price with the full declared decimal target at 80-digit precision.",
            "Relative full-year periods and the original DCF assumptions remain in force; no calendar-stub, dilution or corporate-action reconciliation is inferred.",
        ],
    }
    json.dumps(output, allow_nan=False)
    return output
