"""Private, durable draft document export jobs."""

from __future__ import annotations

import hashlib
import json
import logging
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
from src.reporting.evidence import ReportEvidenceContext, validate_report_evidence
from src.tools.report_artifacts import publish_report_artifact

_LOG = logging.getLogger(__name__)

class ReportJobError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


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
        try:
            if isinstance(report_data, ResearchReport):
                report = ResearchReport.model_validate(
                    report_data.model_dump(mode="python")
                )
            else:
                report = ResearchReport.model_validate(report_data)
            audit = validate_report_evidence(report, evidence_context)
            report = audit.report
        except ValidationError as exc:
            msg = "; ".join(f"{err['loc']}: {err['msg']}" for err in exc.errors())
            raise ReportJobError("SCHEMA_VALIDATION_FAILED", f"Dữ liệu báo cáo không đúng chuẩn: {msg}") from exc
        except ValueError as exc:
            raise ReportJobError("EVIDENCE_VALIDATION_FAILED", str(exc)) from exc
        except Exception as exc:
            raise ReportJobError("INVALID_PAYLOAD", f"Lỗi nạp dữ liệu báo cáo: {exc}") from exc

        job_id = uuid.uuid4().hex
        now_iso = datetime.now(timezone.utc).isoformat()

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
            "warnings": list(audit.warnings),
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
            warnings = [*audit.warnings, *rendered_warnings]
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
