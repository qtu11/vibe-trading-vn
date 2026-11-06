"""Pure, declared point-in-time VN equity comparables over caller-supplied data."""

from __future__ import annotations

from calendar import monthrange
from dataclasses import asdict
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import json
import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.quantlib.valuation.comps import equity_multiple_set, multiple_distribution
from src.tools.local_financial_statements import _timestamp


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ComparablesEvidence(_Contract):
    source_url: str = Field(min_length=1, max_length=512)
    document_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    locator: str = Field(min_length=1, max_length=256)
    published_at: str
    available_at: str
    retrieved_at: str

    @field_validator("source_url")
    @classmethod
    def http_reference(cls, value):
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("source_url must be an HTTP(S) evidence reference without credentials")
        return value

    @field_validator("locator")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("locator must be nonblank")
        return value

    @field_validator("published_at", "available_at", "retrieved_at")
    @classmethod
    def timestamp(cls, value):
        return _timestamp(value, "evidence timestamp").isoformat().replace("+00:00", "Z")

    @model_validator(mode="after")
    def ordered(self):
        if not (_timestamp(self.published_at, "published_at") <= _timestamp(self.available_at, "available_at")
                <= _timestamp(self.retrieved_at, "retrieved_at")):
            raise ValueError("Evidence requires published_at <= available_at <= retrieved_at")
        return self


class ComparablesCompany(_Contract):
    symbol: str = Field(pattern=r"^[A-Z0-9]{1,12}\.VN$")
    venue: Literal["HOSE", "HNX", "UPCOM"]
    sector: str = Field(min_length=1, max_length=80)
    selection_basis: str = Field(min_length=1, max_length=256)
    price_observed_at: str
    share_basis: str = Field(min_length=1, max_length=80)
    share_basis_note: str = Field(min_length=1, max_length=256,
                                 description="Explain price/EPS/BVPS corporate-action comparability and any intervening share changes")
    price_vnd: str | None = Field(description="Raw observed VND per common share, decimal string or null")
    patmi_vnd: str | None = Field(description="Full annual VND earnings attributable to common parent holders on the declared basis; no implicit scale")
    weighted_average_shares: str | None = Field(description="Annual weighted-average common shares on the price-equivalent declared basis")
    parent_equity_vnd: str | None = Field(description="Full VND common equity attributable to parent at period_end, excluding noncontrolling/preferred claims")
    current_common_shares: str | None = Field(description="Common shares matching that period_end book-equity snapshot on the declared price-equivalent basis; not an unmatched later issuance count")
    financial_evidence: ComparablesEvidence
    price_evidence: ComparablesEvidence

    @field_validator("sector", "selection_basis", "share_basis", "share_basis_note")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Company labels and basis notes must be nonblank")
        return value

    @field_validator("price_observed_at")
    @classmethod
    def timestamp(cls, value):
        return _timestamp(value, "price_observed_at").isoformat().replace("+00:00", "Z")

    @field_validator("price_vnd", "patmi_vnd", "weighted_average_shares", "parent_equity_vnd", "current_common_shares")
    @classmethod
    def bounded_decimal(cls, value):
        if value is None:
            return None
        if len(value) > 48 or re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?", value) is None:
            raise ValueError("Financial values must be bounded decimal strings or null")
        try:
            number = Decimal(value)
            if not number.is_finite() or abs(number) > Decimal("1e24") or (number and abs(number) < Decimal("1e-12")):
                raise ValueError("Financial values must have magnitude 0 or 1e-12..1e24")
        except InvalidOperation:
            raise ValueError("Invalid financial decimal") from None
        return value

    @model_validator(mode="after")
    def price_chronology(self):
        if _timestamp(self.price_observed_at, "price_observed_at") > _timestamp(self.price_evidence.published_at, "published_at"):
            raise ValueError("Price observation cannot follow its evidence publication")
        return self


class VietnamComparablesRequest(_Contract):
    schema_version: Literal[1]
    as_of: str
    period_start: str
    period_end: str
    consolidation: Literal["consolidated", "separate"]
    target: ComparablesCompany
    peers: list[ComparablesCompany] = Field(min_length=1, max_length=12)

    @field_validator("schema_version", mode="before")
    @classmethod
    def version_integer(cls, value):
        if type(value) is not int:
            raise ValueError("schema_version must be integer 1")
        return value

    @field_validator("as_of")
    @classmethod
    def cutoff(cls, value):
        return _timestamp(value, "as_of").isoformat().replace("+00:00", "Z")

    @field_validator("period_start", "period_end")
    @classmethod
    def calendar_date(cls, value):
        if len(value) != 10:
            raise ValueError("Period dates must be YYYY-MM-DD")
        return date.fromisoformat(value).isoformat()

    @model_validator(mode="after")
    def comparable(self):
        start, end = date.fromisoformat(self.period_start), date.fromisoformat(self.period_end)
        months = (end.year - start.year) * 12 + end.month - start.month + 1
        if start > end or months != 12 or start.day != 1 or end.day != monthrange(end.year, end.month)[1]:
            raise ValueError("Comparables require one common annual period of twelve complete calendar months")
        companies = [self.target, *self.peers]
        names = [company.symbol for company in companies]
        if len(names) != len(set(names)):
            raise ValueError("Target and peer symbols must be unique")
        for company in companies:
            if company.price_observed_at != self.target.price_observed_at:
                raise ValueError("All prices must share the same observation instant")
            if _timestamp(company.price_observed_at, "price_observed_at") > _timestamp(self.as_of, "as_of"):
                raise ValueError("Price observation follows as_of")
            if end > _timestamp(company.price_observed_at, "price_observed_at").date():
                raise ValueError("Annual period ends after the price observation")
            if company.share_basis != self.target.share_basis:
                raise ValueError("All companies must declare the same per-share adjustment convention")
            for evidence in (company.financial_evidence, company.price_evidence):
                if _timestamp(evidence.available_at, "available_at") > _timestamp(self.as_of, "as_of"):
                    raise ValueError("Evidence was not declared available at as_of")
            if end > _timestamp(company.financial_evidence.published_at, "published_at").date():
                raise ValueError("Financial evidence predates the economic period end")
        return self


def _per_share(numerator: str | None, shares: str | None) -> dict:
    if numerator is None or shares is None:
        return {"value": None, "reason": "missing_input"}
    with localcontext() as context:
        context.prec = 40
        count = Decimal(shares)
        if count <= 0:
            return {"value": None, "reason": "share_count_must_be_positive"}
        value = Decimal(numerator) / count
        return {"value": float(value), "reason": None if value > 0 else "non_positive_per_share_denominator"}


def _company_result(company: ComparablesCompany) -> tuple[dict, object]:
    eps = _per_share(company.patmi_vnd, company.weighted_average_shares)
    bvps = _per_share(company.parent_equity_vnd, company.current_common_shares)
    multiple = equity_multiple_set(
        company.symbol, price_per_share=float(company.price_vnd) if company.price_vnd is not None else None,
        eps=eps["value"], book_value_per_share=bvps["value"],
    )
    return dict(company.model_dump(), eps_vnd=eps, bvps_vnd=bvps,
                multiples={"pe": multiple.pe, "pb": multiple.pb},
                exclusions=[asdict(item) for item in multiple.exclusions]), multiple


def build_vietnam_comparables(payload: dict) -> dict:
    """Validate an evidence-bound annual comp set and compute price scenarios.

    No file, network, issuer lookup, recommendation, or automatic peer choice.
    The canonical input hash covers all companies, including excluded peers.
    """
    try:
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, OverflowError, RecursionError):
        raise ValueError("Comparables payload must be finite JSON data") from None
    if len(encoded.encode("utf-8")) > 64_000:
        raise ValueError("Comparables payload exceeds the 64000-byte input budget")
    request = VietnamComparablesRequest.model_validate(payload)
    normalized = request.model_dump()
    input_hash = hashlib.sha256(json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    target, _ = _company_result(request.target)
    peers = [_company_result(company) for company in request.peers]
    distributions, scenarios = {}, {}
    for name, field in (("pe", "eps_vnd"), ("pb", "bvps_vnd")):
        distribution = multiple_distribution(name, [multiple for _, multiple in peers])
        # MappingProxyType is deliberately immutable in quantlib; serialize its data explicitly.
        distributions[name] = {
            "included": dict(distribution.included), "excluded": [asdict(item) for item in distribution.excluded],
            "count": len(distribution.included), "warning": distribution.warning,
            **{key: getattr(distribution, key) for key in ("minimum", "p25", "median", "p75", "maximum")},
        }
        value = target[field]["value"]
        reason = target[field]["reason"]
        if distribution.median is None:
            reason = reason or "no_eligible_peers"
        scenarios[name] = {
            "unit": "VND_per_share", "target_input": field, "reason": reason,
            "prices": {key: getattr(distribution, key) * value for key in ("minimum", "p25", "median", "p75", "maximum")}
                      if reason is None else None,
        }
    target["scenarios"] = scenarios
    companies = [request.target, *request.peers]
    return {
        "ok": True, "market": "vn", "methodology": "declared_annual_equity_comparables",
        "as_of": request.as_of, "period_start": request.period_start, "period_end": request.period_end,
        "consolidation": request.consolidation, "input_sha256": input_hash,
        "price_observed_at": request.target.price_observed_at,
        "price_age_seconds": (_timestamp(request.as_of, "as_of") - _timestamp(request.target.price_observed_at, "price_observed_at")).total_seconds(),
        "historical_reconstruction": any(_timestamp(e.retrieved_at, "retrieved_at") > _timestamp(request.as_of, "as_of")
                                         for c in companies for e in (c.financial_evidence, c.price_evidence)),
        "distribution": distributions, "target": target, "peers": [row for row, _ in peers],
        "sector_mismatches": [c.symbol for c in request.peers if c.sector != request.target.sector],
        "limitations": [
            "All issuer identities, figures, peer selection, sector labels, source hashes and availability are caller-declared and unverified.",
            "Price and each company's per-share inputs must be on the declared corporate-action basis; no split/rights adjustment is inferred.",
            "One shared annual economic period and consolidation scope are declared for every company; no TTM, forecast or calendarisation is inferred.",
            "PATMI / weighted-average common shares is the supplied basic earnings basis; book-snapshot common shares are used only for BVPS.",
            "The current_common_shares field must match the supplied period-end equity snapshot; intervening issuances require an explicitly reconciled basis, not an unmatched newer share count.",
            "Supplied PATMI must already belong to common shareholders on the declared basis; preferred-dividend and basic/diluted reconciliations are not inferred.",
            "Peer quantiles produce conditional price scenarios, not a forecast, fair-value certification or recommendation; no historical percentile is computed.",
            "Floating-point quantiles follow quantlib's linear interpolation; peer count and exclusions are reported without liquidity or industry suitability verification.",
            "P/B is an observed equity multiple; justified P/B, bank capital, ROE and cost-of-equity models are unavailable.",
        ],
    }
