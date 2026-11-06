"""Typed, market-agnostic contract between AI research and the document renderer."""
from __future__ import annotations
from datetime import date, datetime
from enum import Enum
from typing import Literal
from pydantic import BaseModel, Field, HttpUrl, model_validator


class Market(str, Enum):
    VN_EQUITY = "VN_EQUITY"
    FOREX = "FOREX"
    CRYPTO = "CRYPTO"


class Recommendation(str, Enum):
    BUY = "MUA"
    HOLD = "THEO DÕI"
    SELL = "BÁN"
    NOT_RATED = "CHƯA XẾP HẠNG"


class Source(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=3, max_length=350)
    provider: str = Field(min_length=2, max_length=100)
    url: HttpUrl | None = None
    published_at: date | None = None
    retrieved_at: datetime | None = None
    status: Literal["verified", "user_supplied", "unverified", "simulated"] = "unverified"
    snapshot_id: str | None = None


class Metric(BaseModel):
    key: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=150)
    value: float | None = None
    unit: str = Field(default="", max_length=35)
    as_of: date | None = None
    source_ids: list[str] = Field(default_factory=list)
    decimals: int = Field(default=2, ge=0, le=4)


class Claim(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=1400)
    source_ids: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low", "not_assessed"] = "not_assessed"


class PricePoint(BaseModel):
    date: date
    close: float = Field(gt=0)
    volume: float | None = Field(default=None, ge=0)


class ResearchReport(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    market: Market
    symbol: str = Field(min_length=1, max_length=30)
    exchange: str = Field(min_length=1, max_length=25)
    company_name: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=5, max_length=250)
    subtitle: str = Field(min_length=5, max_length=250)
    data_as_of: date
    recommendation: Recommendation = Recommendation.NOT_RATED
    investment_horizon: str = Field(default="6-12 tháng", max_length=60)
    overview: str = Field(min_length=15, max_length=3500)
    executive_summary: str = Field(min_length=15, max_length=3500)
    financial_metrics: list[Metric] = Field(default_factory=list)
    valuation_metrics: list[Metric] = Field(default_factory=list)
    investment_theses: list[Claim] = Field(default_factory=list)
    risk_factors: list[Claim] = Field(default_factory=list)
    price_history: list[PricePoint] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    methodology: str = Field(default="Phân tích cơ bản, định lượng và kiểm tra nguồn dữ liệu.", max_length=1500)
    # Only test fixtures may use simulated sources / values.
    demo: bool = False

    @model_validator(mode="after")
    def validate_evidence(self):
        ids = [x.id for x in self.sources]
        if len(ids) != len(set(ids)):
            raise ValueError("Trùng source.id")
        referenced = {
            sid
            for item in [*self.financial_metrics, *self.valuation_metrics, *self.investment_theses, *self.risk_factors]
            for sid in item.source_ids
        }
        missing = referenced - set(ids)
        if missing:
            raise ValueError(f"Thiếu nguồn dữ liệu: {sorted(missing)}")
        if self.price_history:
            dates = [p.date for p in self.price_history]
            if dates != sorted(dates) or len(dates) != len(set(dates)):
                raise ValueError("price_history phải sắp xếp thời gian và không trùng ngày")
            if max(dates) > self.data_as_of:
                raise ValueError("Giá tương lai so với data_as_of")
        if not self.demo:
            if not self.sources or any(s.status != "verified" for s in self.sources):
                raise ValueError("Chế độ production chỉ nhận nguồn đã được xác minh")
            for item in [*self.financial_metrics, *self.valuation_metrics, *self.investment_theses, *self.risk_factors]:
                if not item.source_ids:
                    raise ValueError(f"Thiếu source_ids: {getattr(item, 'key', getattr(item, 'title', '?'))}")
            for m in self.financial_metrics + self.valuation_metrics:
                if m.value is not None and m.as_of is None:
                    raise ValueError(f"Thiếu as_of cho metric: {m.key}")
            if self.recommendation != Recommendation.NOT_RATED:
                important = {m.key: m for m in [*self.financial_metrics, *self.valuation_metrics]}
                # Recommendation cannot be published without market price AND documented valuation.
                for field in ("market_price", "target_price"):
                    if field not in important or important[field].value is None or not important[field].source_ids:
                        raise ValueError(f"Không đủ chứng cứ để xếp hạng: {field}")
        return self
