"""Bind report citations to server-collected snapshots, never to JSON trust labels."""

from __future__ import annotations

from dataclasses import dataclass, field
import ast
from datetime import datetime, timedelta, timezone
import math
import re
from typing import Any, TYPE_CHECKING

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


class ReportEvidenceError(ValueError):
    """Evidence rejection with the exact payload fields the agent can repair."""

    def __init__(
        self,
        message: str,
        details: list[dict[str, Any]],
        collected_sources: list[dict[str, Any]] | None = None,
    ):
        super().__init__(message)
        self.details = details
        #: The URLs this run actually read, so a source repair is a choice from
        #: a list rather than another guess. Without it the model saw "URL
        #: không khớp" and invented a replacement URL, failing again.
        self.collected_sources = collected_sources or []


def _collected_catalog(context: ReportEvidenceContext, *, limit: int = 40) -> list[dict[str, Any]]:
    """Compact list of pages this run can cite, keyed by the id the tool used."""
    catalog: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in context.sources:
        url = canonical_url(record.url)
        if not url or url in seen:
            continue
        seen.add(url)
        catalog.append({
            "source_id": record.source_id,
            "url": url,
            "title": (record.title or "")[:120],
            "publisher": (record.publisher or "")[:80],
            "content_chars": record.content_chars,
            "cite_allowed": bool(record.cite_allowed),
            "retrieved_at": record.retrieved_at,
        })
        if len(catalog) >= limit:
            break
    return catalog


#: How many unsupported numbers one response names before summarising the rest.
#: The point is to repair every class at once, not to dump 200 paragraph hits.
_MAX_NUMBER_ISSUES = 16


def _evidence_issue_summary(issues: list[dict[str, Any]]) -> str:
    problems = [str(issue.get("problem") or "") for issue in issues if issue.get("problem")]
    head = "; ".join(problems[:6])
    if len(problems) > 6:
        head += f"; … và {len(problems) - 6} lỗi bằng chứng khác"
    return head or "Báo cáo chưa khớp bằng chứng đã thu thập"


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


def _supports_numbers(report, path, item, records) -> list[dict[str, Any]]:
    """Return every number in ``item`` that its collected sources do not say.

    Returning all failures instead of raising on the first one is what stops
    the serial repair loop: the VIC run fixed one invented figure per export
    attempt because each attempt revealed only the next one.
    """
    issues: list[dict[str, Any]] = []
    candidates = [number for record in records for number in record.numbers]
    source_ids = list(item.source_ids)
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
                issues.append({
                    "field": path,
                    "problem": f"Số liệu không có trong nội dung nguồn đã thu thập: {path} ({value})",
                    "value": value,
                    "source_ids": source_ids,
                    "fix": (
                        "Chỉ dùng số đã đọc trong nguồn của mục này; nếu đây là số tính toán, "
                        "đổi evidence_kind thành derived và khai báo methodology/input_keys thay vì cited."
                    ),
                })
        elif isinstance(value, str):
            # Reuse the source parser's locale/scale readings for each numeric token.
            matches = list(re.finditer(r"(?<![\w])[-+]?\d(?:[\d.,\u00a0]*\d)?", value))
            for index, match in enumerate(matches):
                end = min(match.end() + 18, matches[index + 1].start() if index + 1 < len(matches) else len(value))
                readings = numeric_candidates(value[match.start():end])
                if readings and not any(math.isclose(number, candidate, rel_tol=0.00001, abs_tol=0.005)
                                        for number in readings for candidate in candidates):
                    issues.append({
                        "field": path,
                        "problem": f"Số liệu trong văn bản không có trong nguồn đã thu thập: {path} ({match.group()})",
                        "text": match.group(),
                        "source_ids": source_ids,
                        "fix": (
                            "Sửa câu chữ để chỉ nêu số có trong nguồn đã thu thập, hoặc thu thập thêm "
                            "nguồn chứa số đó; không giữ số ước tính dưới nhãn cited."
                        ),
                    })
    return issues


def _validate_rating_target(target, metrics, *, require_formula=True):
    """Recompute declared metric formulas; rated targets cannot use prose alone."""
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
            if not require_formula:
                return canonical
            raise ValueError("Giá mục tiêu tính toán cần công thức theo input_keys trước khi xếp hạng") from exc
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        if not names:
            # The methodology hard-codes its operands ("236.319,4 - 43.167,1")
            # instead of naming the input metrics. Nothing can be recomputed
            # from it, so it is a description, not a formula.
            if require_formula:
                raise ValueError("Giá mục tiêu tính toán cần công thức theo input_keys trước khi xếp hạng")
            return canonical
        if not names.intersection(metrics):
            # A method label such as DCF/SOTP names no declared metric.
            if require_formula:
                raise ValueError("Công thức định giá phải dùng đúng các input_keys đã khai báo")
            return canonical
        if names != set(metric.input_keys):
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
            issue = {
                "metric_key": metric.key,
                "formula": metric.methodology,
                "inputs": {name: {"value": metrics[name].value, "unit": metrics[name].unit,
                                  "as_of": metrics[name].as_of.isoformat() if metrics[name].as_of else None}
                           for name in sorted(names)},
            }
            if evaluated is not None:
                issue["expected_value"] = evaluated[0] / scale * (100 if unit == "%" else 1)
            raise ReportEvidenceError(f"Giá trị tính toán không khớp công thức: {metric.key}", [issue])
        checked.add(metric.key)
        return canonical

    if target.evidence_kind == "assumption":
        raise ValueError("Giá mục tiêu giả định chưa được tính toán; không thể xuất khuyến nghị mua/bán")
    calculate(target)
    return target.evidence_kind != "derived" or target.key in checked


def validate_report_evidence(
    report: ResearchReport, context: ReportEvidenceContext | None = None,
) -> ReportEvidenceAudit:
    """Keep unverifiable research as an unrated draft; reject contradictory snapshots."""
    if report.demo:
        return ReportEvidenceAudit(report, False, ("Dữ liệu giả lập; không dùng để giao dịch.",))
    warnings = []
    sources = {source.id: source for source in report.sources}
    metrics = {metric.key: metric for metric in [*report.financial_metrics, *report.valuation_metrics]}
    metric_paths = {metric.key: f"{field}.{index}" for field in ("financial_metrics", "valuation_metrics")
                    for index, metric in enumerate(getattr(report, field))}
    calculation_issues = []
    for metric in metrics.values():
        if metric.evidence_kind != "derived" or metric.value is None:
            continue
        try:
            checked = _validate_rating_target(metric, metrics, require_formula=(
                metric.key == "target_price" and report.recommendation != Recommendation.NOT_RATED
            ))
        except ValueError as exc:
            details = getattr(exc, "details", [{"metric_key": metric.key}])
            for issue in details:
                issue["field"] = f"{metric_paths[issue.pop('metric_key', metric.key)]}.value"
                issue["problem"] = str(exc)
                issue["fix"] = "Đối chiếu kỳ/đơn vị các input_keys và sửa value hoặc methodology theo công thức; không đổi nhãn bằng chứng để bỏ kiểm tra."
            calculation_issues.extend(details)
            continue
        if not checked:
            warnings.append(f"{metric_paths[metric.key]}: methodology còn là mô tả; chưa kiểm chứng được phép tính. Khai báo công thức theo input_keys để máy kiểm tra.")
    if context is None:
        if calculation_issues:
            raise ReportEvidenceError("; ".join(issue["problem"] for issue in calculation_issues), calculation_issues)
        if report.recommendation != Recommendation.NOT_RATED:
            raise ValueError("Chưa có bằng chứng công cụ trong phiên; không thể xuất khuyến nghị mua/bán")
        for source in report.sources:
            source.status = "user_supplied" if source.status == "user_supplied" else "unverified"
        report.publication_status = "draft_unverified"
        report.recommendation = Recommendation.NOT_RATED
        for metric in report.financial_metrics + report.valuation_metrics:
            if metric.key == "market_price":
                metric.label = "Giá tham chiếu chưa xác minh"
        return ReportEvidenceAudit(report, False, (*warnings, "Chưa có bằng chứng công cụ trong phiên; tài liệu chưa được xếp hạng."))

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
    source_issues = []
    for index, source in enumerate(report.sources):
        source.status = "user_supplied" if source.status == "user_supplied" else "unverified"
        source_url = canonical_url(str(source.url or ""))
        by_url = snapshots.get(source_url) if source_url else None
        record = by_id.get(source.id)
        if record and canonical_url(record.url) != source_url:
            if by_url is None:
                message = f"URL không khớp nội dung nguồn đã thu thập: {source.id}"
                source_issues.append({
                    "field": f"sources.{index}.url", "problem": message,
                    "source_id": source.id, "expected_url": canonical_url(record.url),
                    "fix": "Đối chiếu nội dung đã đọc: nếu đây là cùng nguồn, dùng đúng expected_url; nếu là nguồn khác, thu thập URL đó và gán source_id phù hợp. Không đoán URL hoặc đổi status thành verified.",
                })
                # The collected page for this id is still the evidence behind
                # every item that cites it. Binding it by id keeps the report's
                # content verifiable while the URL field stays repairable.
                # Reporting it as an unbound source instead produced one
                # "Nguồn S1 chưa được thu thập" issue per referencing field,
                # which the model resolved by deleting the analysis rather
                # than by correcting the URL.
            else:
                record = by_url
        else:
            record = record or by_url
        if record and record.text_sha256 and record.content_chars and record.cite_allowed:
            bound[source.id] = record
    catalog = _collected_catalog(context)
    declared_ids = {source.id for source in report.sources}
    unbound_fields: dict[str, list[str]] = {}
    number_issues: list[dict[str, Any]] = []
    for path, item in iter_report_evidence(report):
        if item.evidence_kind not in {"observed", "cited"}:
            continue
        missing = [sid for sid in item.source_ids if sid not in bound]
        if missing:
            for sid in missing:
                unbound_fields.setdefault(sid, []).append(path)
            item.evidence_kind = "cited"
        else:
            number_issues.extend(
                _supports_numbers(report, path, item, [bound[sid] for sid in item.source_ids])
            )
    unbound_issues: list[dict[str, Any]] = []
    for sid in sorted(unbound_fields):
        fields = unbound_fields[sid]
        if sid in declared_ids:
            problem = f"Nguồn {sid} đã khai báo nhưng chưa được công cụ thu thập trong phiên"
            fix = (
                "Đọc URL của nguồn này bằng read_url/read_document trong phiên rồi giữ nguyên id, "
                "hoặc thay source_ids bằng id trong collected_sources. Không đổi status thành verified."
            )
        else:
            problem = f"source_ids tham chiếu id không tồn tại: {sid}"
            fix = (
                "Dùng đúng id trong collected_sources hoặc khai báo nguồn mới với URL đã đọc; "
                "không tạo id cho nguồn chưa thu thập."
            )
        unbound_issues.append({
            "field": fields[0],
            "problem": problem,
            "source_id": sid,
            "referenced_by": fields[:8],
            "fix": fix,
        })
    if len(number_issues) > _MAX_NUMBER_ISSUES:
        extra = len(number_issues) - _MAX_NUMBER_ISSUES
        number_issues = number_issues[:_MAX_NUMBER_ISSUES]
        number_issues.append({
            "field": "nhiều mục",
            "problem": f"Còn {extra} số liệu khác không có trong nguồn đã thu thập",
            "fix": "Rà lại toàn bộ số trong accepted_report và sửa tất cả cùng một lần gửi.",
        })
    issues = [*calculation_issues, *source_issues, *unbound_issues, *number_issues]
    if issues:
        raise ReportEvidenceError(
            _evidence_issue_summary(issues), issues, collected_sources=catalog,
        )

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
