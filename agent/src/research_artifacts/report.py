"""Deterministic Markdown projection of one already-saved research revision.

No engine, source, clock, database, model or filesystem is accessed here. The
complete supplied revision is retained as JSON, including request/result and
the review history returned by the store. This is a local draft export, not a
publication, independent verification or AI-authored financial narrative.
"""

from __future__ import annotations

import html
import json
import re
import unicodedata
from urllib.parse import quote, urlsplit


MAX_REPORT_BYTES = 262144
REPORT_FORMAT_VERSION = 1
_KINDS = {"vietnam", "vietnam_comparables", "vietnam_dcf", "vietnam_reverse_dcf", "crypto_basis"}
_UNKNOWN = "Chưa có / null"


class ReportExportError(ValueError):
    """Safe, stable error translated by the authenticated HTTP boundary."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _object(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _list(value: object) -> list:
    return value if isinstance(value, list) else []


def _text(value: object) -> str:
    if value is None:
        return _UNKNOWN
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    elif isinstance(value, bool):
        value = "true" if value else "false"
    else:
        value = str(value)
    # Remove block/table boundaries and make hidden direction/control changes
    # visible. Unicode letters and Vietnamese combining marks remain readable.
    value = value.replace("\r\n", "\n").replace("\r", "\n").replace("\n", " ↵ ").replace("\t", " ")
    value = "".join(f"\\u{ord(char):04x}" if unicodedata.category(char) in {"Cc", "Cf", "Cs"} else char for char in value)
    value = html.escape(value, quote=False)
    return re.sub(r"([\\`*_{}\[\]()#+.!|>~:-])", r"\\\1", value)


def _source_link(value: object) -> str:
    if not isinstance(value, str):
        return _text(value)
    try:
        parsed = urlsplit(value)
        _ = parsed.port
        allowed = (parsed.scheme in {"http", "https"} and parsed.hostname
                   and parsed.username is None and parsed.password is None
                   and "\\" not in value
                   and not any(char.isspace() or unicodedata.category(char) in {"Cc", "Cf", "Cs"} for char in value))
    except ValueError:
        allowed = False
    if not allowed:
        return _text(value) + " (không tạo liên kết)"
    # Parentheses/angle brackets/quotes/backticks must not terminate a Markdown
    # destination. Original declared text is retained in the label and JSON.
    target = quote(value, safe=":/?#[]@!$&+,;=%")
    return f"[{_text(value)}]({target})"


def _table(headers: tuple[str, ...], rows: list[tuple]) -> list[str]:
    return ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |",
            *("| " + " | ".join(_text(value) for value in row) + " |" for row in rows), ""]


def _kv(values: dict, *, unit: str | None = None) -> list[str]:
    return _table(("Trường", "Giá trị", "Đơn vị"), [(key, value, unit or "—") for key, value in values.items()])


def _paging(result: dict) -> list[str]:
    paging = _object(result.get("paging"))
    if not paging:
        return []
    lines = ["### Phạm vi trang đã lưu", "",
             "Chỉ xuất trang của revision này. Không tải các trang còn lại hoặc suy ra đã lưu toàn bộ lịch sử/peer set.", ""]
    if paging.get("complete") is not True:
        lines += ["**CẢNH BÁO: trang chưa bao phủ toàn bộ tập kết quả (`complete` khác true).**", ""]
    lines += _kv(paging)
    if "aggregate_scope" in result:
        lines += ["Phạm vi aggregate được engine ghi: " + _text(result["aggregate_scope"]), ""]
    return lines


def _vn(revision: dict) -> list[str]:
    result, request = revision["result"], revision["request"]
    code = request.get("code")
    company = _object(_object(result.get("data")).get(code if isinstance(code, str) else None))
    lines = ["## Chỉ tiêu BCTC trên trang đã lưu", "",
             "Giá trị và quan hệ input/evidence được chép từ kết quả đã lưu; không tính lại tỷ số. Tỷ số theo kỳ, không tự annualize.", ""]
    lines += _kv({"Request code": code, **{key: company.get(key) for key in ("as_of", "consolidation", "source_file_sha256")}})
    periods = _list(company.get("periods"))
    if not periods:
        lines += ["Không có kỳ BCTC trong trang này; không suy diễn giá trị bằng zero.", ""]
    for index, raw in enumerate(periods):
        period = _object(raw)
        lines += ["### Kỳ " + _text(period.get("period_start")) + " → " + _text(period.get("period_end")), ""]
        inputs = _object(period.get("inputs"))
        recorded_metrics = _object(period.get("metrics"))

        def references(name, seen):
            if not isinstance(name, str) or name in seen:
                return set()
            if name in inputs:
                return {str(ref) for ref in _list(_object(inputs[name]).get("evidence"))}
            return set().union(*(references(item, seen | {name}) for item in _list(_object(recorded_metrics.get(name)).get("inputs"))))

        metrics = []
        for name, raw_metric in recorded_metrics.items():
            metric = _object(raw_metric)
            names = _list(metric.get("inputs"))
            refs = sorted(set().union(*(references(key, set()) for key in names)))
            metrics.append((name, metric.get("value"), metric.get("unit"), metric.get("reason"), names, refs))
        lines += _table(("Chỉ tiêu", "Giá trị", "Đơn vị", "Lý do", "Inputs đã ghi", "Evidence IDs của inputs"), metrics)
        lines += ["Evidence IDs chỉ có ý nghĩa trong kỳ này; xem nguồn với ngữ cảnh `result.periods[" + str(index) + "]` bên dưới.", ""]
        lines += _kv(_object(period.get("checks")))
    return lines + _paging(result)


def _comparables(revision: dict) -> list[str]:
    result = revision["result"]
    lines = ["## So sánh định giá cùng kỳ khai báo", "",
             "P/E và P/B là multiples từ input caller; giá theo quantile peer là kịch bản có điều kiện, không phải forecast hay fair value được xác nhận.", ""]
    lines += _kv({key: result.get(key) for key in ("period_start", "period_end", "consolidation", "price_observed_at", "price_age_seconds", "sector_mismatches")})
    companies = [("target", _object(result.get("target"))), *[("peer", _object(item)) for item in _list(result.get("peers"))]]
    lines += _table(("Vai trò", "Symbol", "Giá VND/cp", "EPS VND/cp", "Lý do EPS", "BVPS VND/cp", "Lý do BVPS", "P/E", "P/B", "Exclusions"), [
        (role, company.get("symbol"), company.get("price_vnd"), _object(company.get("eps_vnd")).get("value"),
         _object(company.get("eps_vnd")).get("reason"), _object(company.get("bvps_vnd")).get("value"),
         _object(company.get("bvps_vnd")).get("reason"), _object(company.get("multiples")).get("pe"),
         _object(company.get("multiples")).get("pb"), company.get("exclusions")) for role, company in companies])
    lines += ["### Phân phối toàn bộ peer set được engine ghi", ""]
    lines += _table(("Multiple", "Count", "Min", "P25", "Median", "P75", "Max", "Exclusions", "Warning"), [
        (name, row.get("count"), row.get("minimum"), row.get("p25"), row.get("median"), row.get("p75"), row.get("maximum"), row.get("excluded"), row.get("warning"))
        for name, value in _object(result.get("distribution")).items() for row in [_object(value)]])
    lines += ["### Giá kịch bản của target", ""]
    lines += _table(("Multiple", "Đơn vị", "Input", "Giá theo quantile", "Lý do"), [
        (name, row.get("unit"), row.get("target_input"), row.get("prices"), row.get("reason"))
        for name, value in _object(_object(result.get("target")).get("scenarios")).items() for row in [_object(value)]])
    lines += ["PATMI/weighted shares cho EPS; parent common equity/book-snapshot shares cho BVPS. Share basis, peer/sector selection và nguồn vẫn do caller khai báo; xem đầy đủ request/JSON.", ""]
    return lines + _paging(result)


def _dcf(revision: dict, *, reverse: bool = False) -> list[str]:
    result, request = revision["result"], revision["request"]
    inputs = _object(request.get("dcf")) if reverse else request
    base = _object(result.get("base_case"))
    lines = ["## Kịch bản FCFF và equity bridge đã lưu", "",
             "Chỉ đọc kết quả engine của revision. Không chạy lại DCF, đổi forecast/WACC/share basis hoặc tạo xác suất cho kịch bản.", ""]
    lines += _kv({key: inputs.get(key) for key in ("symbol", "venue", "as_of", "amount_scale", "discounting_convention", "terminal_value_method")})
    lines += _table(("Chỉ tiêu", "Giá trị", "Đơn vị"), [
        (name, base.get(name), "VND/cổ phiếu thực" if name == "value_per_share" else "VND")
        for name in ("enterprise_value", "equity_value", "value_per_share", "pv_of_explicit_fcff")])
    lines += ["### Giả định và bridge được caller khai báo", ""]
    lines += _table(("Giả định", "Giá trị", "Basis", "Source IDs"), [
        ("wacc." + name, item.get("value"), item.get("basis"), item.get("source_ids"))
        for name, raw in _object(inputs.get("wacc")).items() for item in [_object(raw)]])
    lines += _table(("Giả định terminal", "Giá trị", "Basis", "Source IDs"), [
        (name, _object(inputs.get(name)).get("value"), _object(inputs.get(name)).get("basis"), _object(inputs.get(name)).get("source_ids"))
        for name in ("terminal_growth", "exit_multiple", "gdp_growth_reference")])
    lines += _kv({"WACC engine": _object(base.get("wacc_build")).get("wacc"),
                  "Capital structure khai báo": inputs.get("capital_structure"),
                  "Equity bridge khai báo": inputs.get("equity_bridge"),
                  "Net debt bridge engine": base.get("net_debt_bridge"),
                  "Restricted cash bị loại (VND)": result.get("excluded_restricted_cash_vnd") if not reverse else "Xem dcf.equity_bridge.restricted_cash; không suy ra giá trị đã scale"})
    lines += _table(("Forecast year", "EBIT", "D&A", "Capex", "Delta NWC", "Basis", "Source IDs"), [
        (row.get("year"), row.get("ebit"), row.get("depreciation_amortization"), row.get("capex"), row.get("delta_nwc"), row.get("basis"), row.get("source_ids"))
        for raw in _list(inputs.get("forecast")) for row in [_object(raw)]])
    lines += ["Forecast/bridge tiền theo `amount_scale` đã khai báo; kết quả EV/equity là VND đầy đủ. Diluted shares, target và tolerance VND/cổ phiếu không nhân scale. Restricted cash không cộng vào unrestricted cash; debt/minority/preferred/associates giữ nguyên bridge đã ghi.", ""]
    if reverse:
        solver = _object(result.get("solver"))
        lines += ["## Reverse DCF: trạng thái nghiệm đã lưu", "",
                  "Chỉ status `solved` mới có nghiệm. Implied growth là tăng trưởng cần thiết trong bracket với forecast/WACC/bridge cố định; không phải dự báo.", ""]
        lines += _kv({"Target VND/cp": request.get("target_price_vnd"), "Giá quan sát": request.get("price_observed_at"),
                      "Share basis": request.get("share_basis_note"), "Bracket khai báo": request.get("growth_bracket"),
                      "WACC cố định": result.get("fixed_wacc"), **solver})
        if solver.get("status") != "solved":
            lines += ["**KHÔNG CÓ NGHIỆM ĐƯỢC XÁC NHẬN ĐẠT TOLERANCE trong revision này.** Null không được thay bằng zero, endpoint hoặc điểm thử cuối.", ""]
        lines += ["Residual giữ chuỗi Decimal của chênh lệch giá JSON so với target; bisection/định giá vẫn là floating point. Không nới tolerance khi xuất.", ""]
    else:
        sensitivity = _object(result.get("sensitivity"))
        lines += ["### Sensitivity đã lưu", "",
                  "Grid dùng perpetuity growth, kể cả khi base case chọn exit multiple. Mỗi cell giữ nguyên FCFF/tax/equity bridge; không gán xác suất.", ""]
        lines += _table(("WACC", "Terminal growth", "VND/cp", "Lý do"), [
            (cell.get("wacc"), cell.get("terminal_growth"), cell.get("value_per_share_vnd"), cell.get("reason"))
            for raw_row in _list(sensitivity.get("cells")) for raw in _list(raw_row) for cell in [_object(raw)]])
    return lines


def _basis(revision: dict) -> list[str]:
    result = revision["result"]
    lines = ["## Basis dated futures trên quote đã lưu", "",
             "Gross quoted basis, không phải executable yield hoặc carry PnL. Biên bid/ask chưa tính depth/fills, phí, financing/borrow, capital/margin/settlement/venue risk. Perpetual không được gán expiry.", ""]
    lines += _kv({key: result.get(key) for key in ("base", "quote", "as_of", "price_unit", "day_count", "annualization", "summary", "spot", "policy")})
    lines += _table(("Venue / instrument", "Expiry", "Seconds", "Status", "Reasons", "Mid basis (fraction)", "Annualized (fraction/year)", "Lower", "Upper"), [
        (str(row.get("venue")) + " / " + str(row.get("instrument_id")), row.get("expiry"), row.get("seconds_to_expiry"), row.get("status"), row.get("reason_codes"),
         row.get("basis_fraction"), row.get("annualized_basis"), row.get("annualized_lower_basis"), row.get("annualized_upper_basis"))
        for raw in _list(result.get("rows")) for row in [_object(raw)]])
    lines += ["Tỷ lệ ở dạng fraction: 0.02 nghĩa là 2%. Giữ backwardation âm, zero và null/reason của dòng rejected. Annualization gần expiry có thể rất lớn; đọc cùng thời gian còn lại. Không dùng quote hiện tại thay cho snapshot.", ""]
    return lines + _paging(result)


def _sources(revision: dict) -> list[str]:
    kind, request, result = revision["kind"], revision["request"], revision["result"]
    records = []
    if kind == "vietnam":
        company = _object(_object(result.get("data")).get(request.get("code")))
        records = [(f"result.periods[{i}].evidence[{j}]", _object(source))
                   for i, period in enumerate(_list(company.get("periods"))) for j, source in enumerate(_list(_object(period).get("evidence")))]
    elif kind == "vietnam_comparables":
        supplied = _object(request.get("payload"))
        companies = [("target", _object(supplied.get("target"))), *[(f"peers[{i}]", _object(item)) for i, item in enumerate(_list(supplied.get("peers")))]]
        records = [("request.payload." + name + "." + field, _object(company.get(field)))
                   for name, company in companies for field in ("financial_evidence", "price_evidence")]
    elif kind in {"vietnam_dcf", "vietnam_reverse_dcf"}:
        supplied = _object(request.get("dcf")) if kind == "vietnam_reverse_dcf" else request
        records = [(f"request.evidence[{i}]" if kind == "vietnam_dcf" else f"request.dcf.evidence[{i}]", _object(source))
                   for i, source in enumerate(_list(supplied.get("evidence")))]
        if kind == "vietnam_reverse_dcf":
            records.append(("request.price_evidence", _object(request.get("price_evidence"))))
    else:
        records = [("request.spot", _object(request.get("spot"))), *[(f"request.futures[{i}]", _object(item)) for i, item in enumerate(_list(request.get("futures")))]]
    lines = ["## Nguồn và locator được khai báo", "",
             "Các tham chiếu dưới đây được giữ từ revision, chưa truy cập hoặc xác minh. ID/hash/locator là khai báo; không phải chữ ký xác thực. Nguồn không có ID giữ null, không tự tạo một external citation ID.", ""]
    if not records:
        return lines + ["Revision không chứa nguồn tại các field mà loại báo cáo này hỗ trợ; xem JSON đầy đủ. Không suy diễn đã xác minh nguồn.", ""]
    headers = ("Ngữ cảnh", "ID", "URL / source ref", "Locator / instrument", "Revision / document hash", "Published / event", "Available", "Retrieved")
    lines += ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for context, source in records:
        values = [context, source.get("id"), None, source.get("locator", source.get("instrument_id")),
                  {key: source.get(key) for key in ("revision", "document_sha256") if key in source},
                  source.get("published_at", source.get("event_time")), source.get("available_at"), source.get("retrieved_at")]
        cells = [_text(value) for value in values]
        cells[2] = _source_link(source.get("source_url", source.get("source_ref")))
        lines.append("| " + " | ".join(cells) + " |")
    return lines + [""]


def _render_revision_markdown(revision: dict) -> str:
    """Render one saved revision without mutation; fail rather than truncate.

    The authenticated caller must load/integrity-check the revision first. This
    function is not a signature verifier or a replacement for store validation.
    """
    required_dicts = ("request", "result", "scope", "hashes", "producer")
    if (not isinstance(revision, dict) or not isinstance(revision.get("kind"), str) or revision["kind"] not in _KINDS
            or not all(isinstance(revision.get(key), dict) for key in required_dicts)
            or not all(isinstance(revision.get(key), str) for key in ("revision_id", "created_at", "content_scope"))
            or revision.get("verification_status") != "user_supplied_unverified"
            or revision["result"].get("ok") is not True):
        raise ReportExportError("INVALID_REPORT_REVISION", "A supported saved, unverified research revision is required")
    try:
        compact = json.dumps(revision, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
        if len(compact.encode("utf-8")) > MAX_REPORT_BYTES:
            raise ReportExportError("REPORT_TOO_LARGE", "Complete research export exceeds 256 KiB; no partial report was returned")
        attachment = json.dumps(revision, ensure_ascii=True, sort_keys=True, indent=2, allow_nan=False)
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        if isinstance(exc, ReportExportError):
            raise
        raise ReportExportError("INVALID_REPORT_REVISION", "Research export requires bounded finite JSON") from None
    # JSON escapes preserve original string values after parsing, including HTML
    # and Markdown attacks. Dynamic fencing prevents code-block termination.
    attachment = attachment.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    fence = "`" * max(3, 1 + max((len(run) for run in re.findall(r"`+", attachment)), default=0))
    request, result = revision["request"], revision["result"]
    cutoff = result.get("as_of", _object(request.get("dcf")).get("as_of", request.get("as_of")))
    lines = ["# Bản xuất nghiên cứu từ revision đã lưu", "",
             "**BẢN NHÁP ĐỊNH LƯỢNG — NGUỒN CHƯA XÁC MINH — CHƯA PUBLISH/GỬI ĐI.**", "",
             "Đây là bản trình bày xác định của snapshot đã lưu, không phải bài viết bằng AI, khuyến nghị đầu tư hay xác nhận tính đúng của bằng chứng. Không fetch, tính lại, cập nhật timestamp hoặc nâng trạng thái verified khi xuất.", "",
             "## Identity và phạm vi snapshot", ""]
    lines += _kv({"Report format version": REPORT_FORMAT_VERSION, "Revision ID": revision["revision_id"], "Kind": revision["kind"],
                  "Created at (recorded)": revision["created_at"], "Data cutoff khai báo": cutoff,
                  "Parent revision": revision.get("parent_revision_id"), "Content scope": revision["content_scope"],
                  "Scope": revision["scope"], "Verification status": revision["verification_status"],
                  "Review state (self-reported)": revision.get("review_state"),
                  "Historical reconstruction (recorded)": result.get("historical_reconstruction")})
    kind = revision["kind"]
    if kind == "vietnam": lines += _vn(revision)
    elif kind == "vietnam_comparables": lines += _comparables(revision)
    elif kind in {"vietnam_dcf", "vietnam_reverse_dcf"}: lines += _dcf(revision, reverse=kind == "vietnam_reverse_dcf")
    else: lines += _basis(revision)
    lines += _sources(revision)
    lines += ["## Hash và producer của revision", "",
              "Hash nhận diện nội dung/code đã ghi, không chứng minh nguồn thật, quyền phân phối hoặc đầy đủ môi trường thực thi.", ""]
    lines += _kv(revision["hashes"])
    lines += _kv(revision["producer"])
    lines += ["## Review đã được trả về trong snapshot", "",
              "Reviewer là nhãn người thao tác tự khai. Acknowledged/changes_requested không phải independent verification hoặc publish approval.", ""]
    reviews = _list(revision.get("review_history"))
    if reviews:
        lines += _table(("Review ID", "Created", "Decision", "Reviewer", "Identity basis", "Ghi chú", "Verification"), [
            (row.get("review_id"), row.get("created_at"), row.get("decision"), row.get("reviewer"), row.get("reviewer_identity"), row.get("note"), row.get("verification_status"))
            for raw in reviews for row in [_object(raw)]])
    else:
        lines += ["Không có review được trả về trong snapshot này.", ""]
    lines += ["## Giới hạn đã ghi", ""]
    for label, values in (("Revision", revision.get("limitations")), ("Engine", result.get("limitations"))):
        for value in _list(values):
            lines.append("- " + label + ": " + _text(value))
    lines += ["", "Không tự redaction, kiểm rights, resolution của citation hoặc gửi nội dung cho bên ngoài. Tệp chứa toàn bộ input/result/review trả về; người dùng tự đánh giá dữ liệu trước khi chia sẻ.", "",
              "## Phụ lục JSON đầy đủ của snapshot", "",
              "JSON dưới đây giữ toàn bộ request, result và metadata/review được caller cung cấp từ store. Escape Unicode/HTML chỉ bảo vệ trình bày; parse JSON khôi phục giá trị gốc. Không có file attachment bên ngoài hay đường dẫn nguồn được tạo thêm.", "",
              fence + "json", attachment, fence, ""]
    output = "\n".join(lines)
    if len(output.encode("utf-8")) > MAX_REPORT_BYTES:
        raise ReportExportError("REPORT_TOO_LARGE", "Complete research export exceeds 256 KiB; no partial report was returned")
    return output


def render_revision_markdown(revision: dict) -> str:
    """Render a complete saved snapshot or return a stable, non-disclosing error.

    Caller owns store integrity/authentication and download filename handling.
    No clock, external source, producer engine or persistent state is accessed.
    """
    try:
        return _render_revision_markdown(revision)
    except ReportExportError:
        raise
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError):
        raise ReportExportError("INVALID_REPORT_REVISION", "Research revision has unsupported report fields") from None
