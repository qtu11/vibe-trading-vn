"""Bind report citations to server-collected snapshots, never to JSON trust labels."""

from __future__ import annotations

from dataclasses import dataclass, field
import ast
from datetime import datetime, timedelta, timezone
import math
import re
from typing import TYPE_CHECKING

from src.agent.grounding.sources import SourceRecord, canonical_url, numeric_candidates
from src.reporting.schema import DatumEvidence, Recommendation, ResearchReport, iter_report_evidence

if TYPE_CHECKING:
    from src.agent.grounding.ledger import GroundingLedger


@dataclass(frozen=True)
class TrustedQuote:
    source_id: str
    symbol: str
    exchange: str
    value: float
    unit: str
    observed_at: datetime
    price_basis: str
    source_url: str
    retrieved_at: datetime


@dataclass(frozen=True)
class ReportEvidenceContext:
    sources: tuple[SourceRecord, ...] = ()
    quotes: tuple[TrustedQuote, ...] = ()
    as_of: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class ReportEvidenceAudit:
    report: ResearchReport
    quote_verified: bool
    warnings: tuple[str, ...]


def from_grounding_ledger(ledger: GroundingLedger, *, as_of: datetime | None = None) -> ReportEvidenceContext:
    """Copy this run's successful tool observations; report JSON cannot supply them."""
    quotes = []
    # The ledger exposes sources publicly; numeric intake currently has no accessor.
    for record in tuple(ledger._evidence):
        if (record.tool != "get_market_data" or record.field != "quote_observation.value"
                or record.status != "observed" or record.value is None or not record.source_url
                or not record.source_id or not record.timestamp or not record.retrieved_at
                or not record.price_basis or not record.symbol or not record.venue or not record.unit):
            continue
        quotes.append(TrustedQuote(
            source_id=record.source_id, symbol=record.symbol, exchange=record.venue,
            value=float(record.value), unit=record.unit,
            observed_at=datetime.fromisoformat(record.timestamp.replace("Z", "+00:00")),
            price_basis=record.price_basis, source_url=record.source_url,
            retrieved_at=datetime.fromisoformat(record.retrieved_at.replace("Z", "+00:00")),
        ))
    return ReportEvidenceContext(sources=ledger.sources, quotes=tuple(quotes),
                                 as_of=as_of or datetime.now(timezone.utc))


def _unit(unit: str) -> tuple[str, float]:
    """Convert only explicitly declared display scales, never infer from magnitude."""
    text = unit.strip()
    scale = 1.0
    for prefix, factor in (("nghìn ", 1e3), ("ngàn ", 1e3), ("triệu ", 1e6), ("tỷ ", 1e9)):
        if text.casefold().startswith(prefix):
            text, scale = text[len(prefix):], factor
            break
    for suffix in ("/cp", "/share", "_per_share"):
        if text.endswith(suffix):
            text = text[:-len(suffix)]
            break
    return text.upper(), scale


def _same_symbol(report: ResearchReport, symbol: str) -> bool:
    expected, actual = report.symbol.upper(), symbol.upper()
    if expected == actual:
        return True
    # Bare local tickers are unambiguous only inside the report's declared market.
    return report.market.value == "VN_EQUITY" and actual == f"{expected}.VN"


_CELL_VALUE_PATH_RE = re.compile(
    r"^(financial_table|peer_comparison|valuation_scenarios)\.rows\.(\d+)\.values\.(\d+)$"
)


def _values(report: ResearchReport, path: str, item: DatumEvidence):
    if path in {"overview", "executive_summary"}:
        return [getattr(report, path)]
    cell_match = _CELL_VALUE_PATH_RE.match(path)
    if cell_match:
        name, row, column = cell_match.groups()
        return [getattr(report, name).rows[int(row)].values[int(column)]]
    if path.endswith(".note"):
        return [item.note]
    fields = ("value", "change", "close", "volume", "body", "paragraphs", "bullets",
              "values", "note", "target_price", "upside", "assumptions", "detail", "probability", "impact")
    result = []
    for name in fields:
        value = getattr(item, name, None)
        if isinstance(value, list):
            result.extend(value)
        elif value is not None:
            result.append(value)
    return result


def _record_rank(record: SourceRecord) -> tuple[int, int, int]:
    valid = int(bool(record.text_sha256 and record.content_chars and record.cite_allowed))
    return (valid, len(record.numbers), record.content_chars)


def _supports_numbers(report, path, item, records):
    candidates = [number for record in records for number in record.numbers]
    for value in _values(report, path, item):
        if isinstance(value, (float, int)):
            raw = float(value)
            _, scale = _unit(getattr(item, "unit", ""))
            base_tol = 0.5 * 10 ** -getattr(item, "decimals", 6)
            checks = [(raw * scale, base_tol * scale)]
            if scale != 1.0 and not path.endswith(".market_price"):
                # Financial tables often declare "Đơn vị: Tỷ đồng" once in the table
                # header rather than repeating "tỷ" after every cell value.
                checks.append((raw, base_tol))
            if not any(
                math.isclose(target, candidate, rel_tol=1e-9, abs_tol=tol)
                for target, tol in checks
                for candidate in candidates
            ):
                raise ValueError(f"Số liệu không có trong nội dung nguồn đã thu thập: {path} ({value})")
        elif isinstance(value, str):
            # Reuse the source parser's locale/scale readings for each numeric token.
            matches = list(re.finditer(r"(?<![\w])[-+]?\d(?:[\d.,\u00a0]*\d)?", value))
            for index, match in enumerate(matches):
                end = min(match.end() + 18, matches[index + 1].start() if index + 1 < len(matches) else len(value))
                readings = numeric_candidates(value[match.start():end])
                if readings and not any(math.isclose(number, candidate, rel_tol=0.00001, abs_tol=0.005)
                                        for number in readings for candidate in candidates):
                    raise ValueError(f"Số liệu trong văn bản không có trong nguồn đã thu thập: {path} ({match.group()})")


def _validate_rating_target(target, metrics):
    """A rated calculated target must recompute from its declared metric inputs."""
    from src.agent.grounding.policies import _evaluate_formula

    checked = set()

    def metric_dimension(metric):
        unit, _ = _unit(metric.unit)
        if unit in {"%", "X", "1", "LẦN"}:
            return {}
        if not re.fullmatch(r"[A-Z][A-Z0-9]*(?:/[A-Z][A-Z0-9]*)?", unit):
            raise ValueError(f"Đơn vị định giá chưa được khai báo rõ hoặc chưa hỗ trợ: {metric.key}")
        numerator, _, denominator = unit.partition("/")
        result = {numerator: 1}
        if denominator:
            result[denominator] = result.get(denominator, 0) - 1
        return {name: power for name, power in result.items() if power}

    def formula_dimension(node):
        if isinstance(node, ast.Name):
            return metric_dimension(metrics[node.id])
        if isinstance(node, ast.Constant):
            return {}
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            return formula_dimension(node.operand)
        if isinstance(node, ast.BinOp):
            left, right = formula_dimension(node.left), formula_dimension(node.right)
            if isinstance(node.op, (ast.Add, ast.Sub)):
                if left != right:
                    raise ValueError("Công thức định giá cộng/trừ các đầu vào khác đơn vị")
                return left
            if isinstance(node.op, (ast.Mult, ast.Div)):
                result = dict(left)
                for name, power in right.items():
                    result[name] = result.get(name, 0) + power * (1 if isinstance(node.op, ast.Mult) else -1)
                return {name: power for name, power in result.items() if power}
        raise ValueError("Công thức định giá có phép toán chưa hỗ trợ")

    def calculate(metric):
        unit, scale = _unit(metric.unit)
        if metric.value is None:
            raise ValueError(f"Đầu vào định giá chưa có giá trị: {metric.key}")
        canonical = metric.value * scale / (100 if unit == "%" else 1)
        if metric.evidence_kind != "derived" or metric.key in checked:
            return canonical
        expression = metric.methodology.replace("×", "*").replace("÷", "/").replace("−", "-")
        try:
            tree = ast.parse(expression, mode="eval")
        except (SyntaxError, ValueError, RecursionError) as exc:
            raise ValueError("Giá mục tiêu tính toán cần công thức theo input_keys trước khi xếp hạng") from exc
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        if not names or names != set(metric.input_keys):
            raise ValueError("Công thức định giá phải dùng đúng các input_keys đã khai báo")
        if any(isinstance(node, ast.Constant) and (isinstance(node.value, bool) or node.value not in (0, 1))
               for node in ast.walk(tree)):
            raise ValueError("Hệ số định giá phải là metric giả định có giải thích, không phải hằng số ẩn")
        values = {name: calculate(metrics[name]) for name in names}
        if formula_dimension(tree.body) != metric_dimension(metric):
            raise ValueError(f"Đơn vị kết quả định giá không khớp công thức: {metric.key}")
        for name in sorted(names, key=len, reverse=True):
            expression = re.sub(r"\b" + re.escape(name) + r"\b", lambda _match, value=values[name]: repr(value), expression)
        evaluated = _evaluate_formula(expression)
        if evaluated is None or not math.isclose(evaluated[0], canonical,
                rel_tol=0, abs_tol=0.5 * 10 ** -metric.decimals * scale / (100 if unit == "%" else 1)):
            raise ValueError(f"Giá trị định giá không khớp công thức: {metric.key}")
        checked.add(metric.key)
        return canonical

    if target.evidence_kind == "assumption":
        raise ValueError("Giá mục tiêu giả định chưa được tính toán; không thể xuất khuyến nghị mua/bán")
    calculate(target)


def validate_report_evidence(
    report: ResearchReport, context: ReportEvidenceContext | None = None,
) -> ReportEvidenceAudit:
    """Keep unverifiable research as an unrated draft; reject contradictory snapshots."""
    if report.demo:
        return ReportEvidenceAudit(report, False, ("Dữ liệu giả lập; không dùng để giao dịch.",))
    warnings = []
    sources = {source.id: source for source in report.sources}
    if context is None:
        if report.recommendation != Recommendation.NOT_RATED:
            raise ValueError("Chưa có bằng chứng công cụ trong phiên; không thể xuất khuyến nghị mua/bán")
        for source in report.sources:
            source.status = "user_supplied" if source.status == "user_supplied" else "unverified"
        report.publication_status = "draft_unverified"
        report.recommendation = Recommendation.NOT_RATED
        for metric in report.financial_metrics + report.valuation_metrics:
            if metric.key == "market_price":
                metric.label = "Giá tham chiếu chưa xác minh"
        return ReportEvidenceAudit(report, False, ("Chưa có bằng chứng công cụ trong phiên; tài liệu chưa được xếp hạng.",))

    snapshots: dict[str, SourceRecord] = {}
    for record in context.sources:
        url_key = canonical_url(record.url)
        if not url_key:
            continue
        existing = snapshots.get(url_key)
        if existing is None or _record_rank(record) >= _record_rank(existing):
            snapshots[url_key] = record
    by_id = {record.source_id: record for record in context.sources}
    bound = {}
    for source in report.sources:
        source.status = "user_supplied" if source.status == "user_supplied" else "unverified"
        source_url = canonical_url(str(source.url or ""))
        by_url = snapshots.get(source_url) if source_url else None
        record = by_id.get(source.id)
        if record and canonical_url(record.url) != source_url:
            if by_url is None:
                raise ValueError(f"URL không khớp nội dung nguồn đã thu thập: {source.id}")
            record = by_url
        else:
            record = record or by_url
        if record and record.text_sha256 and record.content_chars and record.cite_allowed:
            bound[source.id] = record
    unbound = set()
    for path, item in iter_report_evidence(report):
        if item.evidence_kind in {"observed", "cited"}:
            if not all(sid in bound for sid in item.source_ids):
                unbound.update(set(item.source_ids) - bound.keys())
                item.evidence_kind = "cited"
            else:
                _supports_numbers(report, path, item, [bound[sid] for sid in item.source_ids])
    if unbound:
        raise ValueError("Nguồn chưa được công cụ thu thập trong phiên: " + ", ".join(sorted(unbound)))

    metrics = {metric.key: metric for metric in [*report.financial_metrics, *report.valuation_metrics]}
    price = metrics.get("market_price")
    quote_verified = False
    if context and price and price.value is not None:
        if context.as_of.tzinfo is None:
            raise ValueError("Thời điểm kiểm chứng phải có múi giờ")
        references = {canonical_url(str(sources[sid].url or "")) for sid in price.source_ids}
        quotes = [quote for quote in context.quotes if canonical_url(quote.source_url) in references]
        if quotes:
            same_instrument = [quote for quote in quotes if _same_symbol(report, quote.symbol)
                               and quote.exchange.upper() == report.exchange.upper()]
            if not same_instrument:
                raise ValueError("Mã hoặc sàn của giá không khớp quan sát từ nhà cung cấp")
            quote = max(same_instrument, key=lambda item: item.observed_at)
            unit, scale = _unit(price.unit)
            quote_unit, quote_scale = _unit(quote.unit)
            if unit != quote_unit or not math.isclose(price.value * scale, quote.value * quote_scale, rel_tol=1e-9, abs_tol=0.000001):
                raise ValueError("Giá/đơn vị không khớp quan sát nguồn; không được đoán hệ số nghìn")
            if price.price_basis is not None and price.price_basis != quote.price_basis:
                raise ValueError("Cơ sở điều chỉnh giá/corporate action không khớp quan sát nguồn")
            if price.as_of != quote.observed_at.date():
                raise ValueError("Ngày giá không khớp thời điểm quan sát nguồn")
            if price.observed_at is not None and price.observed_at != quote.observed_at:
                raise ValueError("Thời điểm giá không khớp quan sát nguồn")
            if quote.observed_at > context.as_of or quote.retrieved_at > context.as_of:
                raise ValueError("Nguồn giá chưa tồn tại tại thời điểm kiểm chứng")
            # shortcut: 72 calendar hours covers an ordinary weekend; exchange-calendar freshness can replace this for long holidays.
            if context.as_of - quote.observed_at <= timedelta(hours=72):
                quote_verified = True
                price.evidence_kind = "observed"
                price.observed_at = quote.observed_at
                price.price_basis = quote.price_basis
                for sid in price.source_ids:
                    source = sources[sid]
                    if source.symbol and not _same_symbol(report, source.symbol):
                        raise ValueError("Mã trong nguồn giá không khớp báo cáo")
                    if source.exchange and source.exchange.upper() != report.exchange.upper():
                        raise ValueError("Sàn trong nguồn giá không khớp báo cáo")
                    source.symbol, source.exchange = quote.symbol, quote.exchange
                    source.unit, source.observed_at, source.price_basis = quote.unit, quote.observed_at, quote.price_basis
                    source.retrieved_at = quote.retrieved_at
            else:
                warnings.append("Giá đã quá 72 giờ; cần quan sát mới trước khi xếp hạng.")

    target = metrics.get("target_price")
    if quote_verified and target and target.price_basis != price.price_basis:
        warnings.append("Giá mục tiêu chưa cùng cơ sở cổ phiếu/corporate action với giá tham chiếu.")
    basis_matched = bool(target and price and target.price_basis == price.price_basis)
    if not quote_verified:
        warnings.append("Chưa xác minh được giá theo mã, sàn, đơn vị, thời điểm và cơ sở điều chỉnh; chưa xếp hạng.")
        if price:
            price.label = "Giá tham chiếu chưa xác minh"
    if not quote_verified or not basis_matched:
        if report.recommendation != Recommendation.NOT_RATED:
            raise ValueError("Chưa đủ giá, nguồn và cơ sở điều chỉnh để xuất khuyến nghị mua/bán")
        report.recommendation = Recommendation.NOT_RATED
    if report.recommendation != Recommendation.NOT_RATED:
        _validate_rating_target(target, metrics)
    report.publication_status = "draft_unverified"
    return ReportEvidenceAudit(report, quote_verified, tuple(warnings))
