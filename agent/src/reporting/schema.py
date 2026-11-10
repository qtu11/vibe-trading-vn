"""Typed, market-agnostic contract between AI research and the document renderer.

The AI supplies *content*: values, labels, periods, commentary. The renderer owns
*design*: colour, type scale, column geometry, charts. Every field added for the
research-desk layout is optional, so a minimal report still renders and a rich
one gains the metric deltas, highlight grid and multi-period table that
institutional Vietnamese reports lead with.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
import math
import re
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, Field, HttpUrl, ValidationError, field_validator, model_validator


EvidenceKind = Literal["observed", "cited", "derived", "assumption"]
PriceBasis = Annotated[
    Literal["raw", "split_adjusted", "total_return"],
    BeforeValidator(lambda value: {"split": "split_adjusted", "split_dividend": "total_return"}.get(value, value)
                    if isinstance(value, str) else value),
]


class DatumEvidence(BaseModel):
    """Attribution for a value, or an explicitly labelled analytical input."""

    source_ids: list[str] = Field(default_factory=list)
    evidence_kind: EvidenceKind = "cited"
    input_keys: list[str] = Field(default_factory=list)
    methodology: str = Field(default="", max_length=1500)


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
    symbol: str | None = Field(default=None, max_length=30)
    exchange: str | None = Field(default=None, max_length=25)
    unit: str | None = Field(default=None, max_length=35)
    observed_at: datetime | None = None
    price_basis: PriceBasis | None = None

    @field_validator("url")
    @classmethod
    def public_reference(cls, value):
        if value is not None and (value.username or value.password):
            raise ValueError("Nguồn URL không được chứa thông tin đăng nhập")
        return value


class Metric(DatumEvidence):
    key: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=150)
    value: float | None = Field(default=None, allow_inf_nan=False)
    unit: str = Field(default="", max_length=35)
    as_of: date | None = None
    observed_at: datetime | None = None
    price_basis: PriceBasis | None = None
    decimals: int = Field(default=2, ge=0, le=4)
    #: Period-over-period movement, printed beside the value on a metric card
    #: ("−20,1% YoY"). ``None`` prints no delta at all rather than a zero.
    change: float | None = Field(default=None, allow_inf_nan=False)
    change_unit: str = Field(default="%", max_length=10)
    change_period: str = Field(default="YoY", max_length=20)
    #: ``auto`` colours a rise green and a fall red; override when a rise is bad
    #: (cost, leverage, NPL ratio).
    change_tone: Literal["auto", "positive", "negative", "neutral"] = "auto"
    #: Ask the renderer to place this metric in the lead card band. When no
    #: metric is featured, the band takes the first five with values.
    featured: bool = False
    #: Short qualifier under the value ("giá 50.400 đ", "so với quý 2").
    note: str = Field(default="", max_length=120)


class Claim(DatumEvidence):
    """A thesis or risk: a headline claim backed by cited sources."""

    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=1400)
    confidence: Literal["high", "medium", "low", "not_assessed"] = "not_assessed"


class KeyStat(DatumEvidence):
    """One large number in the highlight grid ("ĐIỂM NHẤN")."""

    label: str = Field(min_length=1, max_length=90)
    value: str = Field(min_length=1, max_length=40)
    note: str = Field(default="", max_length=160)
    tone: Literal["positive", "negative", "neutral"] = "neutral"


class PeriodPoint(DatumEvidence):
    """One bar in a quarterly results chart."""

    period: str = Field(min_length=1, max_length=20)
    value: float = Field(allow_inf_nan=False)
    unit: str = Field(default="", max_length=35)
    note: str = Field(default="", max_length=80)
    #: The series' latest point is drawn in the signal colour by default; set
    #: this to highlight a different bar (a peak, a trough, a forecast).
    highlight: bool = False


class FinancialRow(DatumEvidence):
    label: str = Field(min_length=1, max_length=120)
    values: list[str] = Field(default_factory=list)
    cell_evidence: list[DatumEvidence] = Field(default_factory=list)
    #: 0 = head row, 1 = sub-line of the row above, 2 = deep sub-line.
    indent: int = Field(default=0, ge=0, le=2)
    note: str = Field(default="", max_length=400)
    emphasis: bool = False


class FinancialTable(DatumEvidence):
    """A multi-period summary table, the spine of a Vietnamese equity note."""

    title: str = Field(default="Tóm tắt kết quả kinh doanh", max_length=150)
    subtitle: str = Field(default="", max_length=200)
    #: Column headings *after* the label column ("Q3.2025", "% YoY", ...).
    columns: list[str] = Field(default_factory=list, max_length=12)
    rows: list[FinancialRow] = Field(default_factory=list)
    note: str = Field(default="", max_length=400)

    @model_validator(mode="after")
    def validate_width(self):
        width = len(self.columns)
        for row in self.rows:
            if len(row.values) > width:
                raise ValueError(f"Hàng '{row.label}' có nhiều giá trị hơn số cột")
            if row.cell_evidence and len(row.cell_evidence) != len(row.values):
                raise ValueError(f"Hàng '{row.label}' cần chứng cứ cho từng ô")
        return self


class Analyst(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    title: str = Field(default="Chuyên viên phân tích", max_length=120)
    email: str = Field(default="", max_length=160)
    phone: str = Field(default="", max_length=60)


class RatingBand(BaseModel):
    """One row of the published rating scale."""

    label: str = Field(min_length=1, max_length=40)
    rule: str = Field(min_length=1, max_length=160)


class ChartSeries(DatumEvidence):
    """One numeric series of a section chart.

    Cited/observed values are matched number by number against the source
    text collected by tools in this run (see ``reporting.evidence``). There is
    no free-form "derived" series: calculated lines come from ``line_formula``
    and are computed by the server, never typed in by the model.
    """

    label: str = Field(min_length=1, max_length=80)
    values: list[float] = Field(default_factory=list, max_length=8)
    unit: str = Field(default="", max_length=35)
    decimals: int = Field(default=0, ge=0, le=4)

    @field_validator("values")
    @classmethod
    def finite_values(cls, values):
        if any(not math.isfinite(value) for value in values):
            raise ValueError("Chuỗi biểu đồ không được chứa NaN/Inf")
        return values


ChartFormula = Literal["ratio_to_bars_pct", "share_of_total_pct"]


class SectionChart(BaseModel):
    """A bar (+ optional line) chart whose every point is source-bound or server-computed."""

    title: str = Field(min_length=1, max_length=140)
    caption: str = Field(default="", max_length=180)
    categories: list[str] = Field(min_length=2, max_length=8)
    bars: ChartSeries
    #: Cited line, or only ``label`` when ``line_formula`` computes the values.
    line: ChartSeries | None = None
    #: ``ratio_to_bars_pct``: line = line_numerator / bars x 100 (e.g. margin).
    #: ``share_of_total_pct``: line = bars / bars[line_base_index] (or sum) x 100.
    line_formula: ChartFormula | None = None
    line_numerator: ChartSeries | None = None
    line_base_index: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_points(self):
        count = len(self.categories)
        if len(set(self.categories)) != count:
            raise ValueError(f"Biểu đồ '{self.title}' trùng nhãn danh mục")
        cited = {"observed", "cited"}
        series = [("bars", self.bars), ("line_numerator", self.line_numerator)]
        if self.line_formula is None:
            series.append(("line", self.line))
        for name, item in series:
            if item is None:
                continue
            if len(item.values) != count:
                raise ValueError(f"Biểu đồ '{self.title}': {name} cần đúng {count} giá trị")
            if item.evidence_kind not in cited:
                raise ValueError(
                    f"Biểu đồ '{self.title}': {name} phải là số liệu có nguồn (cited/observed); "
                    "số liệu tính toán dùng line_formula"
                )
        if self.line_formula is None:
            if self.line_numerator is not None or self.line_base_index is not None:
                raise ValueError(f"Biểu đồ '{self.title}': line_numerator/line_base_index cần line_formula")
            return self

        bars = self.bars.values
        if self.line_formula == "ratio_to_bars_pct":
            if self.line_numerator is None:
                raise ValueError(f"Biểu đồ '{self.title}': ratio_to_bars_pct cần line_numerator")
            if self.line_numerator.unit.strip().casefold() != self.bars.unit.strip().casefold():
                raise ValueError(f"Biểu đồ '{self.title}': tử số và cột phải cùng đơn vị")
            if any(value == 0 for value in bars):
                raise ValueError(f"Biểu đồ '{self.title}': mẫu số bằng 0")
            computed = [n / d * 100 for n, d in zip(self.line_numerator.values, bars)]
            inputs = [self.bars, self.line_numerator]
            method = f"{self.line_numerator.label} / {self.bars.label} x 100"
        else:
            if self.line_numerator is not None:
                raise ValueError(f"Biểu đồ '{self.title}': share_of_total_pct không dùng line_numerator")
            if self.line_base_index is not None and self.line_base_index >= count:
                raise ValueError(f"Biểu đồ '{self.title}': line_base_index ngoài phạm vi")
            base = bars[self.line_base_index] if self.line_base_index is not None else sum(bars)
            if base == 0:
                raise ValueError(f"Biểu đồ '{self.title}': tổng/mẫu số bằng 0")
            computed = [value / base * 100 for value in bars]
            inputs = [self.bars]
            anchor = self.categories[self.line_base_index] if self.line_base_index is not None else "tổng"
            method = f"{self.bars.label} / {anchor} x 100"

        decimals = self.line.decimals if self.line is not None else 1
        rounded = [round(value, decimals) for value in computed]
        if self.line is not None and self.line.values:
            # A model-typed line is accepted only when it equals the recomputation.
            tolerance = 0.5 * 10 ** -decimals + 1e-9
            if len(self.line.values) != count or any(
                not math.isclose(given, value, rel_tol=0, abs_tol=tolerance)
                for given, value in zip(self.line.values, computed)
            ):
                raise ValueError(f"Biểu đồ '{self.title}': đường tỷ lệ không khớp công thức {self.line_formula}")
        self.line = ChartSeries(
            label=self.line.label if self.line is not None else "Tỷ lệ (%)",
            values=rounded,
            unit="%",
            decimals=decimals,
            evidence_kind="derived",
            source_ids=list(dict.fromkeys(sid for item in inputs for sid in item.source_ids)),
            methodology=f"Máy chủ tính: {method}",
        )
        return self


class NarrativeSection(DatumEvidence):
    """A free-form but structured section for deep analysis (SWOT, industry, ...)."""

    heading: str = Field(min_length=1, max_length=160)
    subtitle: str = Field(default="", max_length=220)
    paragraphs: list[str] = Field(default_factory=list)
    bullets: list[str] = Field(default_factory=list)
    page_break_before: bool = False
    #: Up to two charts built only from numbers collected for this report.
    charts: list[SectionChart] = Field(default_factory=list, max_length=2)


class PeerRow(DatumEvidence):
    company: str = Field(min_length=1, max_length=120)
    ticker: str = Field(default="", max_length=20)
    values: list[str] = Field(default_factory=list)
    cell_evidence: list[DatumEvidence] = Field(default_factory=list)
    note: str = Field(default="", max_length=200)


class ComparisonTable(DatumEvidence):
    title: str = Field(min_length=1, max_length=180)
    subtitle: str = Field(default="", max_length=220)
    columns: list[str] = Field(default_factory=list, max_length=14)
    rows: list[PeerRow] = Field(default_factory=list)
    note: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def validate_width(self):
        width = len(self.columns)
        for row in self.rows:
            if len(row.values) > width:
                raise ValueError(f"Hàng '{row.company}' có nhiều giá trị hơn số cột")
            if row.cell_evidence and len(row.cell_evidence) != len(row.values):
                raise ValueError(f"Hàng '{row.company}' cần chứng cứ cho từng ô")
        return self


class ScenarioRow(DatumEvidence):
    case: str = Field(min_length=1, max_length=80)
    target_price: str = Field(default="", max_length=60)
    upside: str = Field(default="", max_length=60)
    assumptions: str = Field(default="", max_length=400)
    tone: Literal["positive", "negative", "neutral", "base"] = "neutral"


class SensitivityTable(DatumEvidence):
    title: str = Field(default="Phân tích độ nhạy", max_length=180)
    subtitle: str = Field(default="", max_length=220)
    rows: list[ScenarioRow] = Field(default_factory=list)
    note: str = Field(default="", max_length=500)


class Catalyst(DatumEvidence):
    horizon: str = Field(default="", max_length=40)
    title: str = Field(min_length=1, max_length=180)
    detail: str = Field(default="", max_length=500)
    probability: str = Field(default="", max_length=40)
    impact: str = Field(default="", max_length=40)
    tone: Literal["positive", "negative", "neutral"] = "neutral"


class PricePoint(DatumEvidence):
    date: date
    close: float = Field(gt=0, allow_inf_nan=False)
    volume: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    unit: str = Field(default="", max_length=35)
    price_basis: PriceBasis | None = None


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
    overview_evidence: DatumEvidence = Field(default_factory=DatumEvidence)
    executive_summary_evidence: DatumEvidence = Field(default_factory=DatumEvidence)
    financial_metrics: list[Metric] = Field(default_factory=list)
    valuation_metrics: list[Metric] = Field(default_factory=list)
    investment_theses: list[Claim] = Field(default_factory=list)
    risk_factors: list[Claim] = Field(default_factory=list)
    price_history: list[PricePoint] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    methodology: str = Field(
        default="Phân tích cơ bản, định lượng và kiểm tra nguồn dữ liệu.", max_length=1500
    )
    #: Only test fixtures may use simulated sources / values.
    demo: bool = False
    #: System-determined publication state: AI cannot claim certified status unilaterally.
    publication_status: Literal["draft_unverified", "certified", "simulated_demo"] = (
        "draft_unverified"
    )

    # ---- research-desk layout (all optional) ----------------------------
    sector: str = Field(default="", max_length=80)
    #: Kicker above the title ("Cập nhật KQKD · 04/11/2026").
    report_type: str = Field(default="Báo cáo phân tích", max_length=80)
    key_stats: list[KeyStat] = Field(default_factory=list, max_length=8)
    forecast_stats: list[KeyStat] = Field(default_factory=list, max_length=8)
    financial_table: FinancialTable | None = None
    quarterly_results: list[PeriodPoint] = Field(default_factory=list, max_length=16)
    analyst: Analyst | None = None
    rating_scale: list[RatingBand] = Field(default_factory=list, max_length=6)
    #: Deep-analysis sections; each rendered in order. Use for industry context,
    #: segment analysis, competitive moat, governance, ESG, technical view, etc.
    analysis_sections: list[NarrativeSection] = Field(default_factory=list)
    peer_comparison: ComparisonTable | None = None
    valuation_scenarios: SensitivityTable | None = None
    catalysts: list[Catalyst] = Field(default_factory=list)
    appendix_sections: list[NarrativeSection] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def reject_redacted_content(cls, data):
        # Missing evidence must be repaired upstream, never erased in an export.
        pending = [data]
        while pending:
            value = pending.pop()
            if isinstance(value, str) and re.search(r"(?:omitted|đã lược|略)\s*※", value, re.IGNORECASE):
                raise ValueError("Báo cáo còn số liệu bị lược do thiếu bằng chứng; bổ sung nguồn hoặc ghi rõ dữ liệu chưa có")
            if isinstance(value, dict):
                pending.extend(value.values())
            elif isinstance(value, BaseModel):
                pending.append(value.model_dump(mode="python"))
            elif isinstance(value, (list, tuple)):
                pending.extend(value)
        return data

    @model_validator(mode="after")
    def validate_evidence(self):
        ids = [x.id for x in self.sources]
        if len(ids) != len(set(ids)):
            raise ValueError("Trùng source.id")

        items = list(iter_report_evidence(self))
        referenced = {
            sid
            for _, item in items
            for sid in item.source_ids
        }
        missing = referenced - set(ids)
        if missing:
            raise ValueError(f"Thiếu nguồn dữ liệu: {sorted(missing)}")

        metrics = [*self.financial_metrics, *self.valuation_metrics]
        keys = [m.key for m in metrics]
        if len(keys) != len(set(keys)):
            raise ValueError("Trùng metric.key trong báo cáo")
        for field in ("financial_metrics", "valuation_metrics"):
            for metric in getattr(self, field):
                if metric.as_of is not None and metric.as_of > self.data_as_of:
                    raise ValueError(f"Metric có ngày tương lai so với data_as_of: {field}.{metric.key}.as_of")
                if metric.key in ("market_price", "target_price") and metric.value is not None and metric.value <= 0:
                    raise ValueError(f"Giá phải lớn hơn 0: {metric.key}")
        important = {m.key: m for m in metrics}
        market_price, target_price, upside = (important.get(key) for key in ("market_price", "target_price", "upside"))
        if market_price and target_price and market_price.value is not None and target_price.value is not None:
            if market_price.unit != target_price.unit:
                raise ValueError("market_price và target_price phải cùng đơn vị")
            if upside and upside.value is not None:
                expected = (target_price.value / market_price.value - 1) * 100
                if upside.unit != "%" or not math.isclose(upside.value, expected, rel_tol=0, abs_tol=0.5 * 10 ** -upside.decimals):
                    raise ValueError("upside không khớp market_price và target_price")

        if self.price_history:
            dates = [p.date for p in self.price_history]
            if dates != sorted(dates) or len(dates) != len(set(dates)):
                raise ValueError("price_history phải sắp xếp thời gian và không trùng ngày")
            if max(dates) > self.data_as_of:
                raise ValueError("Giá tương lai so với data_as_of")
            if len({(point.unit, point.price_basis) for point in self.price_history}) != 1:
                raise ValueError("Chuỗi giá phải cùng đơn vị và cơ sở điều chỉnh")

        periods = [p.period for p in self.quarterly_results]
        if len(periods) != len(set(periods)):
            raise ValueError("quarterly_results trùng kỳ")
        if len({point.unit for point in self.quarterly_results}) > 1:
            raise ValueError("Biểu đồ kết quả theo kỳ phải cùng đơn vị")

        if self.demo:
            self.publication_status = "simulated_demo"
        else:
            self.publication_status = "draft_unverified"
            if not self.sources:
                raise ValueError("Báo cáo cần có ít nhất một nguồn dữ liệu có cơ sở")
            if any(s.status == "simulated" for s in self.sources):
                raise ValueError("Chế độ production chỉ nhận nguồn đã được xác minh, không nhận nguồn simulated")
            sources = {source.id: source for source in self.sources}
            for source in self.sources:
                # A JSON label is not a server-observed content snapshot.
                if source.status == "verified":
                    source.status = "unverified"
            problems = []
            for path, item in items:
                must_cite = item.evidence_kind in {"observed", "cited"}
                if must_cite and not item.source_ids:
                    problems.append(f"Thiếu source_ids: {path}")
                if item.evidence_kind in {"derived", "assumption"} and not item.methodology.strip():
                    problems.append(f"Thiếu phương pháp/giả định: {path}")
                if item.evidence_kind == "derived" and not (item.input_keys or item.source_ids):
                    problems.append(f"Thiếu đầu vào cho số liệu tính toán: {path}")
                for sid in item.source_ids:
                    if sources[sid].url is None:
                        problems.append(f"Thiếu URL nguồn cho {path}: {sid}")
                unknown_inputs = set(item.input_keys) - set(keys)
                if unknown_inputs:
                    problems.append(f"Đầu vào không tồn tại cho {path}: {sorted(unknown_inputs)}")
                if path.startswith(("financial_metrics.", "valuation_metrics.")):
                    key = path.split(".", 1)[1]
                    if key in item.input_keys:
                        problems.append(f"Đầu vào tự tham chiếu: {key}")
                for dep_key in item.input_keys:
                    if dep_key in unknown_inputs:
                        continue
                    dep = important[dep_key]
                    if dep.value is None and not dep.source_ids and not dep.input_keys:
                        problems.append(f"Đầu vào '{dep_key}' của {path} chưa có giá trị hoặc nguồn")

            for m in self.financial_metrics + self.valuation_metrics:
                if m.value is not None and m.as_of is None:
                    raise ValueError(f"Thiếu as_of cho metric: {m.key}")

            for point in self.price_history:
                if not point.unit or point.price_basis is None:
                    raise ValueError("price_history cần đơn vị và cơ sở điều chỉnh giá")

            if self.recommendation != Recommendation.NOT_RATED:
                for field in ("market_price", "target_price"):
                    if field not in important or important[field].value is None:
                        raise ValueError(f"Không đủ chứng cứ để xếp hạng: {field}")

            if problems:
                raise ValidationError.from_exception_data(type(self).__name__, [
                    {"type": "value_error", "loc": (), "ctx": {"error": ValueError(problem)}}
                    for problem in problems
                ])

            # Derived inputs form an acyclic graph, otherwise they prove nothing.
            def visit(key, active, complete):
                if key in active:
                    raise ValueError(f"Vòng lặp đầu vào tính toán: {key}")
                if key in complete:
                    return
                for dependency in important[key].input_keys:
                    visit(dependency, active | {key}, complete)
                complete.add(key)

            complete = set()
            for key in important:
                visit(key, set(), complete)

        return self


def iter_report_evidence(report: ResearchReport):
    """All rendered data surfaces; table cells may override whole-row attribution."""
    yield "overview", report.overview_evidence
    yield "executive_summary", report.executive_summary_evidence
    for name in ("financial_metrics", "valuation_metrics", "investment_theses", "risk_factors",
                 "key_stats", "forecast_stats", "quarterly_results", "price_history",
                 "analysis_sections", "appendix_sections", "catalysts"):
        for index, item in enumerate(getattr(report, name)):
            yield f"{name}.{getattr(item, 'key', index)}", item
    for name in ("analysis_sections", "appendix_sections"):
        for index, section in enumerate(getattr(report, name)):
            for chart_index, chart in enumerate(section.charts):
                prefix = f"{name}.{index}.charts.{chart_index}"
                for part in ("bars", "line_numerator", "line"):
                    series = getattr(chart, part)
                    if series is not None:
                        yield f"{prefix}.{part}", series
    for name in ("financial_table", "peer_comparison", "valuation_scenarios"):
        table = getattr(report, name)
        if table is None:
            continue
        if table.note or table.subtitle:
            yield name, table
        for index, row in enumerate(table.rows):
            cells = getattr(row, "cell_evidence", [])
            if cells:
                for column, evidence in enumerate(cells):
                    yield f"{name}.rows.{index}.values.{column}", evidence
                if row.note:
                    yield f"{name}.rows.{index}.note", row
            else:
                yield f"{name}.rows.{index}", row
