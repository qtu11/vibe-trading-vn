"""Private, durable draft document export jobs."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from pypdf import PdfReader

from src.config.paths import get_runtime_root
from src.reporting.renderer import export_report
from src.reporting.schema import ResearchReport
from src.reporting.evidence import ReportEvidenceContext, ReportEvidenceError, validate_report_evidence
from src.tools.report_artifacts import publish_report_artifact

_LOG = logging.getLogger(__name__)

#: Cap on how many *grouped* field errors are echoed back to the model. The
#: raw dump ran past 50KB and pushed the whole export failure out of the
#: model's effective attention. Grouping by field pattern means one entry can
#: stand for every `investment_theses.*.body`, so a higher cap no longer
#: explodes into dozens of near-identical lines.
_MAX_VALIDATION_ERRORS = 24


def _condense_validation_errors(exc: ValidationError) -> str:
    """Summarise schema errors compactly, grouped by pattern.

    A long list of near-identical errors (``paragraphs.0`` .. ``paragraphs.6``
    all "Input should be a valid string") tells the model far less than one
    line naming the group and the fix.
    """
    errors = exc.errors()
    groups: dict[str, list[str]] = {}
    for err in errors:
        loc = ".".join(str(part) for part in err.get("loc", ())) or "(root)"
        # Collapse every list index, not only the last one:
        # investment_theses.0.body -> investment_theses.*.body. The old
        # tail-only collapse left four "body" groups that consumed the whole
        # error budget before the model saw the real class of failure.
        loc = ".".join("*" if part.isdigit() else part for part in loc.split("."))
        groups.setdefault(f"{loc}: {err.get('msg', '')}", []).append(loc)
    lines = []
    for summary, locs in list(groups.items())[:_MAX_VALIDATION_ERRORS]:
        count = len(locs)
        lines.append(summary if count == 1 else f"{summary} (×{count})")
    if len(groups) > _MAX_VALIDATION_ERRORS:
        lines.append(f"... và {len(groups) - _MAX_VALIDATION_ERRORS} nhóm lỗi khác")
    return "; ".join(lines)


_ROOT_FIELD_PATTERNS = (
    re.compile(r"Metric có ngày tương lai so với data_as_of:\s*([A-Za-z_][\w.]*)"),
    re.compile(r"Thiếu phương pháp/giả định:\s*([A-Za-z_][\w.]*)"),
    re.compile(r"Thiếu source_ids:\s*([A-Za-z_][\w.]*)"),
    re.compile(r"Thiếu đầu vào cho số liệu tính toán:\s*([A-Za-z_][\w.]*)"),
    re.compile(r"Thiếu URL nguồn cho\s*([A-Za-z_][\w.]*)"),
    re.compile(r"Đầu vào không tồn tại cho\s*([A-Za-z_][\w.]*)"),
    re.compile(r"Đầu vào tự tham chiếu:\s*([A-Za-z_][\w.]*)"),
    re.compile(r"Thiếu as_of cho metric:\s*([A-Za-z_][\w.]*)"),
    re.compile(r"Không đủ chứng cứ để xếp hạng:\s*([A-Za-z_][\w.]*)"),
    re.compile(r"Số liệu (?:trong văn bản )?không có trong nội dung nguồn đã thu thập:\s*([A-Za-z_][\w.]*)"),
)


def _root_error_field(message: str) -> str | None:
    """Extract the payload path a model-level validator named in its message.

    Pydantic reports a ``model_validator`` failure at ``(root)``. The message
    already contains the exact field (``Thiếu phương pháp/giả định:
    investment_theses.3``), but without parsing it the repair packet told the
    model only that "(root)" was wrong -- the same dead end the 50KB dump had.
    """
    for pattern in _ROOT_FIELD_PATTERNS:
        match = pattern.search(message)
        if match:
            return match.group(1)
    return None


def _structured_validation_errors(exc: ValidationError) -> list[dict[str, str]]:
    """Turn schema errors into grouped per-field repair instructions.

    The model can act on ``{"field": "analysis_sections.*.paragraphs",
    "problem": "...", "fix": "..."}``; it cannot act on a prose sentence
    that buried the same information inside a 12-line dump. Grouping all
    repeated indices into one entry is what lets one response name every
    failure class at once instead of revealing them one retry at a time.
    """
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    order: list[tuple[str, str]] = []
    for err in exc.errors():
        raw_loc = ".".join(str(part) for part in err.get("loc", ())) or "(root)"
        message = str(err.get("msg", ""))
        loc = ".".join("*" if part.isdigit() else part for part in raw_loc.split("."))
        if loc == "(root)":
            named = _root_error_field(message)
            if named:
                loc = named
        key = (loc, message)
        entry = grouped.get(key)
        if entry is None:
            entry = {
                "field": loc,
                "problem": message,
                "fix": _field_fix_hint(loc, message),
                "count": 0,
            }
            if raw_loc != loc:
                entry["example_field"] = raw_loc
            grouped[key] = entry
            order.append(key)
        entry["count"] += 1

    hints: list[dict[str, str]] = []
    for key in order[:_MAX_VALIDATION_ERRORS]:
        entry = dict(grouped[key])
        count = entry.pop("count", 1)
        if count > 1:
            entry["problem"] = f"{entry['problem']} (×{count} trường)"
        hints.append(entry)
    if len(order) > _MAX_VALIDATION_ERRORS:
        remaining = [grouped[key]["field"] for key in order[_MAX_VALIDATION_ERRORS:]]
        hints.append({
            "field": "(còn lại)",
            "problem": f"{len(remaining)} nhóm lỗi khác: {', '.join(remaining[:10])}",
            "fix": "Sửa tất cả nhóm còn lại trong cùng một lần gửi; đừng chỉ sửa nhóm đầu tiên rồi thử lại.",
        })
    return hints


#: Per-field repair hints for the schema errors a model actually hits. The
#: normalizer already repairs the *shape* near-misses; what reaches this
#: table is a genuine content problem, so the hint must name the content.
_FIELD_FIX_HINTS: tuple[tuple[str, str], ...] = (
    ("paragraphs", "Mỗi phần tử của paragraphs phải là một chuỗi văn bản thuần (không phải object {text, source_ids})."),
    ("bullets", "Mỗi phần tử của bullets phải là một chuỗi văn bản thuần."),
    ("source_ids", "Danh sách source_ids phải chứa các id có thật trong trường sources của báo cáo."),
    ("value", "Trường value phải là số (không phải chuỗi) hoặc null; đơn vị/scale nằm ở trường unit."),
    ("unit", "Trường unit phải là chuỗi, ví dụ 'tỷ VND', 'VND', '%'."),
    ("as_of", "Trường as_of phải là ngày ISO (YYYY-MM-DD) và không được vượt quá data_as_of."),
    ("observed_at", "Trường observed_at phải là thời điểm ISO có múi giờ."),
    ("evidence_kind", "evidence_kind phải là một trong: observed, cited, derived, assumption."),
    ("input_keys", "input_keys phải liệt kê đúng các key metric đã khai báo ở financial_metrics/valuation_metrics."),
    ("methodology", "Giá trị derived/assumption cần methodology mô tả công thức hoặc giả định."),
    ("body", "Mỗi investment_theses/risk_factors cần title và body (chuỗi) — không dùng text/description/paragraph thay cho body."),
    ("price_basis", "price_basis chỉ nhận raw, split_adjusted hoặc total_return; dùng cùng một cơ sở cho cả price_history."),
    ("heading", "heading phải là chuỗi 1–160 ký tự; không đánh số thứ tự vì renderer tự đánh số chương."),
    ("charts", "Mỗi section tối đa 2 charts; bars phải là số liệu cited/observed, số liệu tính toán dùng line_formula."),
    ("url", "Mỗi nguồn cần một url http(s) hợp lệ trỏ tới trang đã thu thập."),
    ("provider", "Mỗi nguồn cần provider (tên nhà cung cấp/nhóm bài)."),
    ("id", "Mỗi nguồn cần id duy nhất, ví dụ S1, S2."),
    ("categories", "Biểu đồ cần ít nhất 2 categories và các series phải cùng độ dài với categories."),
    ("bars", "bars phải là một object duy nhất {label, unit, decimals, values, source_ids}."),
    ("values", "values phải là mảng số, cùng độ dài với categories của biểu đồ."),
    ("key", "Mỗi metric cần key duy nhất, ví dụ revenue, eps, target_price."),
    ("data_as_of", "data_as_of phải là ngày ISO (YYYY-MM-DD)."),
    ("market", "market phải là một trong: VN_EQUITY, US_EQUITY, FOREX, CRYPTO, COMMODITY."),
    ("symbol", "symbol phải là mã có hậu tố sàn, ví dụ VIC.VN, AAPL, BTCUSDT."),
    ("exchange", "exchange phải là tên sàn, ví dụ HOSE, HNX, NASDAQ."),
    ("title", "title/subtitle phải dài từ 5 ký tự trở lên."),
    ("subtitle", "title/subtitle phải dài từ 5 ký tự trở lên."),
    ("overview", "overview và executive_summary phải dài từ 15 ký tự trở lên."),
    ("executive_summary", "overview và executive_summary phải dài từ 15 ký tự trở lên."),
    ("recommendation", "recommendation phải là một trong: MUA, THEO DÕI, BÁN, CHƯA XẾP HẠNG."),
    ("symbol", "symbol phải là mã có hậu tố sàn, ví dụ VIC.VN, AAPL, BTCUSDT."),
)


def _field_fix_hint(loc: str, message: str) -> str:
    """Best repair instruction for one schema error location."""
    if "ngày tương lai so với data_as_of" in message:
        return (
            "as_of là ngày dữ liệu/giả định đã được biết tại cutoff, không phải ngày kết thúc kỳ kế hoạch. "
            "Đối chiếu ngày công bố nguồn; giữ kỳ kế hoạch trong label/note và nêu rõ kế hoạch hay dự báo, "
            "không tự đổi ngày khi chưa có bằng chứng."
        )
    if loc == "valuation_scenarios":
        return (
            "valuation_scenarios phải là object {title, rows, source_ids/evidence_kind/methodology}; "
            "rows là mảng {case, assumptions, target_price, upside, source_ids/evidence_kind/methodology}. "
            "Dùng case thay cho name; giữ phần diễn giải implied trong assumptions/note, "
            "không biến văn xuôi thành giá mục tiêu."
        )
    if "phương pháp/giả định" in message:
        return (
            "Khai báo evidence_kind=derived hoặc assumption, methodology mô tả công thức/giả định, "
            "và input_keys trỏ tới metric đã có giá trị hoặc nguồn."
        )
    if "source_ids" in message:
        return "Gán source_ids của mục này bằng id trong sources; id phải là nguồn đã thu thập trong phiên."
    if "input_keys" in message or "Đầu vào" in message:
        return "input_keys phải trỏ đúng key metric đã khai báo; thêm metric đầu vào nếu thiếu."
    if "as_of" in message:
        return "Thêm as_of dạng YYYY-MM-DD cho metric, không muộn hơn data_as_of."
    if "URL nguồn" in message:
        return "Mỗi source_ids phải có source tương ứng với url http(s) đã thu thập."
    if "bars phải là số liệu có nguồn" in message:
        return (
            "Số liệu tính toán không được đặt trong bars; giữ bars là số liệu cited/observed "
            "và khai báo line_formula/line_numerator để máy tính đường tỷ lệ."
        )
    tail = loc.split(".")[-1]
    for key, hint in _FIELD_FIX_HINTS:
        if tail == key:
            return hint
    if "date" in message.lower():
        return "Giá trị phải là ngày ISO (YYYY-MM-DD)."
    if "string" in message.lower():
        return "Trường này phải là chuỗi văn bản."
    if "number" in message.lower() or "float" in message.lower() or "int" in message.lower():
        return "Trường này phải là số."
    return "Sửa đúng kiểu dữ liệu của trường này theo ResearchReport schema."


def _structural_depth_warnings(report: ResearchReport) -> list[str]:
    """Name the analyses that are too thin to read as a research note.

    The VIC run produced a PDF whose table of contents listed eight chapters
    and whose body held none of them, because each failed export taught the
    model to delete a section. A rendered document is a success, but an empty
    analysis is a silent failure: the user receives a file that does not look
    like research. This warning reaches the model *with* the artifact, so it
    can deepen the note instead of delivering a shell.
    """
    warnings: list[str] = []
    sections = list(report.analysis_sections) + list(report.appendix_sections)
    if not sections:
        warnings.append(
            "Báo cáo không có analysis_sections: tài liệu chỉ gồm các chương khung "
            "(tổng quan, kết quả kinh doanh, diễn biến giá, luận điểm, rủi ro, định giá) "
            "mà không có phân tích chuyên sâu. Bổ sung các chương phân tích có bằng chứng."
        )
        return warnings
    thin = [
        section.heading
        for section in sections
        if not section.paragraphs and not section.bullets and not section.charts
    ]
    if thin:
        warnings.append(
            "Các chương phân tích sau không có nội dung (paragraphs/bullets/charts): "
            + ", ".join(thin[:6])
            + ". Mỗi chương phải trả lời một câu hỏi có bằng chứng."
        )
    return warnings


class ReportJobError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: list[dict[str, Any]] | None = None,
        normalized_report: dict[str, Any] | None = None,
        normalization_warnings: list[str] | None = None,
        collected_sources: list[dict[str, Any]] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        #: Per-field repair instructions. Empty for codes that are not about
        #: the report payload (bad format list, bad page count).
        self.details = details or []
        #: The payload after shape normalisation, echoed back so the model can
        #: see what the server already accepted instead of re-deriving it.
        self.normalized_report = normalized_report
        #: What the normalizer repaired, so a retry does not re-attempt it.
        self.normalization_warnings = normalization_warnings or []
        #: Pages actually read this run; a source repair chooses from these.
        self.collected_sources = collected_sources or []


class ReportJobService:
    """Manages document export jobs and registers private artifacts."""

    def __init__(self, storage_root: Path | None = None):
        self.storage_root = storage_root or (get_runtime_root() / "report_jobs")
        self.storage_root.mkdir(parents=True, exist_ok=True)

    def _save_job(self, job: dict[str, Any]) -> None:
        target = self.storage_root / f"{job['job_id']}.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
        temporary.replace(target)

    def create_job(
        self,
        report_data: dict | ResearchReport,
        formats: list[str] | tuple[str, ...] = ("docx", "pdf", "pptx"),
        run_id: str | None = None,
        evidence_context: ReportEvidenceContext | None = None,
        minimum_pages: int = 1,
    ) -> dict[str, Any]:
        """Validate research content, render branded documents, and stage artifacts."""
        if type(minimum_pages) is not int or not 1 <= minimum_pages <= 2000:
            raise ReportJobError("INVALID_PAGE_COUNT", "minimum_pages must be an integer between 1 and 2000")
        if not isinstance(formats, (list, tuple)) or any(not isinstance(f, str) for f in formats):
            raise ReportJobError("INVALID_FORMAT", "formats must be a list of docx, pdf and/or pptx")
        fmt_list = [f.lower().strip() for f in formats]
        for f in fmt_list:
            if f not in ("docx", "pdf", "pptx"):
                raise ReportJobError("INVALID_FORMAT", f"Unsupported report format: {f}")
        if not fmt_list:
            raise ReportJobError("MISSING_FORMATS", "At least one format (docx, pdf or pptx) must be requested")
        if len(fmt_list) != len(set(fmt_list)):
            raise ReportJobError("INVALID_FORMAT", "Report formats must not contain duplicates")

        # 1. Validate structured research
        normalize_warnings: list[str] = []
        normalized_payload: dict[str, Any] | None = None
        try:
            from src.reporting.normalize import normalize_report_payload

            if isinstance(report_data, ResearchReport):
                raw_payload = report_data.model_dump(mode="python")
            elif isinstance(report_data, dict):
                raw_payload = report_data
            else:
                raw_payload = report_data
            if isinstance(raw_payload, dict):
                raw_payload, normalize_warnings = normalize_report_payload(raw_payload)
                report_data = raw_payload
                normalized_payload = raw_payload
            if isinstance(report_data, ResearchReport):
                report = ResearchReport.model_validate(
                    report_data.model_dump(mode="python")
                )
            else:
                report = ResearchReport.model_validate(report_data)
            audit = validate_report_evidence(report, evidence_context)
            report = audit.report
        except ValidationError as exc:
            msg = _condense_validation_errors(exc)
            raise ReportJobError(
                "SCHEMA_VALIDATION_FAILED",
                f"Dữ liệu báo cáo không đúng chuẩn: {msg}",
                details=_structured_validation_errors(exc),
                normalized_report=normalized_payload,
                normalization_warnings=normalize_warnings,
            ) from exc
        except ValueError as exc:
            raise ReportJobError(
                "EVIDENCE_VALIDATION_FAILED",
                str(exc),
                details=exc.details if isinstance(exc, ReportEvidenceError) else None,
                collected_sources=(
                    exc.collected_sources if isinstance(exc, ReportEvidenceError) else None
                ),
                normalized_report=normalized_payload,
                normalization_warnings=normalize_warnings,
            ) from exc
        except ReportJobError:
            raise
        except Exception as exc:
            raise ReportJobError(
                "INVALID_PAYLOAD",
                f"Lỗi nạp dữ liệu báo cáo: {exc}",
                normalized_report=normalized_payload,
                normalization_warnings=normalize_warnings,
            ) from exc

        job_id = uuid.uuid4().hex
        now_iso = datetime.now(timezone.utc).isoformat()

        structural_warnings = _structural_depth_warnings(report)

        job_record: dict[str, Any] = {
            "job_id": job_id,
            "status": "running",
            "formats": fmt_list,
            "artifacts": [],
            "error": None,
            "publication_status": report.publication_status,
            "created_at": now_iso,
            "updated_at": now_iso,
            "run_id": run_id,
            "quote_verified": audit.quote_verified,
            "warnings": [*normalize_warnings, *audit.warnings, *structural_warnings],
            "normalization_warnings": list(normalize_warnings),
            "minimum_pages": minimum_pages,
            "pdf_pages": None,
        }
        self._save_job(job_record)

        # 2. Render documents
        render_dir = self.storage_root / "staging"
        render_dir.mkdir(parents=True, exist_ok=True)
        job_staging_dir = render_dir / job_id
        job_staging_dir.mkdir(exist_ok=False)
        try:
            render_formats = [*fmt_list, "pdf"] if minimum_pages > 1 and "pdf" not in fmt_list else fmt_list
            result = export_report(report=report, root=job_staging_dir, formats=render_formats)

            artifacts = []
            job_record["artifacts"] = artifacts
            raw_warnings = result.get("warnings")
            rendered_warnings = (
                list(raw_warnings) if isinstance(raw_warnings, (list, tuple)) else []
            )
            warnings = [*normalize_warnings, *audit.warnings, *structural_warnings, *rendered_warnings]
            job_record["warnings"] = warnings
            depth_error = None
            if minimum_pages > 1:
                try:
                    pages = len(PdfReader(result["pdf"]).pages)
                    if not 1 <= pages <= 2000:
                        raise ValueError("PDF page count is outside the supported range")
                    job_record["pdf_pages"] = pages
                    if pages < minimum_pages:
                        depth_error = {"code": "INSUFFICIENT_REPORT_DEPTH", "message": f"Báo cáo có {pages} trang, yêu cầu ít nhất {minimum_pages}; cần bổ sung phân tích có bằng chứng."}
                except Exception as exc:
                    depth_error = {"code": "PAGE_COUNT_UNAVAILABLE", "message": "Chưa kiểm chứng được số trang PDF của báo cáo."}
                    _LOG.warning("Cannot verify report depth for %s: %s", job_id, exc)
                if depth_error:
                    warnings.append(depth_error["message"])
            missing: list[str] = []
            for fmt in fmt_list:
                file_path_val = result.get(fmt)
                if not file_path_val or not isinstance(file_path_val, (str, Path)):
                    missing.append(fmt)
                    continue
                file_path = Path(file_path_val)
                try:
                    artifact_meta = publish_report_artifact(file_path, format=fmt)
                except (OSError, ValueError) as exc:
                    _LOG.warning("Failed to stage %s for report %s: %s", fmt, job_id, exc)
                    missing.append(fmt)
                    warnings.append(f"Không thể lưu {fmt.upper()}: {exc}")
                else:
                    artifact_meta["job_id"] = job_id
                    artifacts.append(artifact_meta)
                    try:
                        index = self.storage_root / "artifacts"
                        index.mkdir(exist_ok=True)
                        (index / f"{artifact_meta['report_id']}.json").write_text(json.dumps({"job_id": job_id}), encoding="utf-8")
                    except OSError:
                        _LOG.warning("Could not index artifact %s; receipt lookup will scan jobs", artifact_meta["report_id"])

            if missing:
                # A requested format did not exist after rendering. Never report
                # unqualified success: the caller must see which artifact is absent.
                missing_label = ", ".join(item.upper() for item in missing)
                detail = warnings[0] if warnings else f"Không tạo được {missing_label}"
                job_record["status"] = "partial" if artifacts else "failed"
                job_record["error"] = {
                    "code": "PARTIAL_EXPORT",
                    "message": f"Thiếu định dạng {missing_label}: {detail}",
                }
            elif depth_error:
                job_record["status"] = "partial" if artifacts else "failed"
                job_record["error"] = depth_error
            else:
                job_record["status"] = "succeeded"
                job_record["error"] = None
            job_record["updated_at"] = datetime.now(timezone.utc).isoformat()
            return job_record

        except Exception as exc:
            _LOG.error("Failed to render report job %s: %s", job_id, exc, exc_info=True)
            job_record["status"] = "partial" if job_record["artifacts"] else "failed"
            job_record["error"] = {"code": "RENDER_FAILED", "message": str(exc)}
            job_record["updated_at"] = datetime.now(timezone.utc).isoformat()
            if job_record["artifacts"]:
                return job_record
            raise ReportJobError("RENDER_FAILED", f"Lỗi tạo tài liệu: {exc}") from exc
        finally:
            self._save_job(job_record)
            if job_staging_dir.exists():
                shutil.rmtree(job_staging_dir, ignore_errors=True)

    def _read_job(self, job_id: str) -> dict[str, Any] | None:
        if not isinstance(job_id, str) or len(job_id) != 32 or any(char not in "0123456789abcdef" for char in job_id):
            return None
        try:
            job = json.loads((self.storage_root / f"{job_id}.json").read_text(encoding="utf-8"))
            if isinstance(job, dict) and job.get("job_id") == job_id and isinstance(job.get("artifacts"), list):
                return job
        except (OSError, ValueError):
            pass

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        """Fetch a receipt, with legacy artifact handles resolved once."""
        return self._read_job(job_id) or self.get_job_for_artifact(job_id)

    def get_job_for_artifact(self, report_id: str) -> dict[str, Any] | None:
        if not isinstance(report_id, str) or len(report_id) != 32 or any(char not in "0123456789abcdef" for char in report_id):
            return None
        try:
            index = json.loads((self.storage_root / "artifacts" / f"{report_id}.json").read_text(encoding="utf-8"))
            # An index is a pointer to a receipt, never another artifact lookup.
            job = self._read_job(index["job_id"])
            if job and any(isinstance(a, dict) and a.get("report_id") == report_id for a in job.get("artifacts", [])):
                return job
        except (OSError, ValueError, KeyError, TypeError):
            pass
        # Older receipts predate the artifact index; keep existing chat links usable.
        for path in self.storage_root.glob("*.json"):
            if path.name.startswith("job_"):
                continue
            try:
                job = self._read_job(path.stem)
                if job and any(isinstance(a, dict) and a.get("report_id") == report_id for a in job["artifacts"]):
                    return job
            except (OSError, ValueError):
                continue

        # Fall back to resolving standalone published report artifacts (e.g. from write_file_tool / publish_pdf)
        from src.tools.report_artifacts import resolve_report_artifact

        resolved = resolve_report_artifact(report_id)
        if resolved is not None:
            file_path, media_type = resolved
            hasher = hashlib.sha256()
            with file_path.open("rb") as stream:
                while chunk := stream.read(65536):
                    hasher.update(chunk)
            sha256 = hasher.hexdigest()
            size_bytes = file_path.stat().st_size
            mtime = datetime.fromtimestamp(file_path.stat().st_mtime, tz=timezone.utc).isoformat()
            fmt = file_path.suffix.lstrip(".").lower()
            if fmt in ("pdf", "docx", "pptx"):
                artifact_meta = {
                    "job_id": report_id,
                    "report_id": report_id,
                    "download_url": f"/api/reports/{report_id}",
                    "filename": file_path.name,
                    "media_type": media_type,
                    "sha256": sha256,
                    "size_bytes": size_bytes,
                }
                synthetic_job = {
                    "job_id": report_id,
                    "status": "succeeded",
                    "formats": [fmt],
                    "artifacts": [artifact_meta],
                    "error": None,
                    "publication_status": "draft_unverified",
                    "warnings": [],
                    "created_at": mtime,
                    "updated_at": mtime,
                }
                try:
                    self._save_job(synthetic_job)
                    index_dir = self.storage_root / "artifacts"
                    index_dir.mkdir(exist_ok=True)
                    (index_dir / f"{report_id}.json").write_text(json.dumps({"job_id": report_id}), encoding="utf-8")
                except OSError:
                    pass
                return synthetic_job

        return None
