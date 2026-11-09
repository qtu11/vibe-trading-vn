"""Authenticated API routes for Vibe Report Engine document generation."""

from __future__ import annotations

from contextlib import closing
import logging
from io import BytesIO
from threading import Lock
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from src.api.security import require_auth
from src.reporting.service import ReportJobError, ReportJobService
from src.tools.report_artifacts import resolve_report_artifact

_LOG = logging.getLogger(__name__)
_PDF_PREVIEW_LOCK = Lock()


class ReportExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report: dict
    formats: list[Literal["docx", "pdf", "pptx"]] = Field(default=["docx", "pdf", "pptx"], min_length=1, max_length=3)
    run_id: Annotated[str, Field(strict=True, pattern=r"^[A-Za-z0-9_-]{1,100}$")] | None = None
    minimum_pages: Annotated[int, Field(strict=True, ge=1, le=2000)] = 24


def register_reports_routes(app: FastAPI) -> None:
    service = ReportJobService()

    @app.post("/api/reports/jobs", dependencies=[Depends(require_auth)])
    @app.post("/api/reports/export", dependencies=[Depends(require_auth)])
    def export_report_job(payload: ReportExportRequest):
        try:
            return service.create_job(
                report_data=payload.report,
                formats=payload.formats,
                run_id=payload.run_id,
                minimum_pages=payload.minimum_pages,
            )
        except ReportJobError as exc:
            status_code = 422 if exc.code in ("SCHEMA_VALIDATION_FAILED", "EVIDENCE_VALIDATION_FAILED", "INVALID_FORMAT", "MISSING_FORMATS", "INVALID_PAGE_COUNT") else 500
            raise HTTPException(status_code=status_code, detail={"code": exc.code, "message": exc.message}) from None
        except Exception as exc:
            _LOG.error("Failed to process report export: %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail={"code": "INTERNAL_ERROR", "message": "Failed to generate report"}) from None

    @app.get("/api/reports/jobs/{job_id}", dependencies=[Depends(require_auth)])
    def get_report_job(job_id: str):
        job = service.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail={"code": "JOB_NOT_FOUND", "message": "Report job not found"})
        return job

    @app.get("/api/reports/artifacts/{report_id}/job", dependencies=[Depends(require_auth)])
    def get_artifact_job(report_id: str):
        job = service.get_job_for_artifact(report_id)
        if job is None:
            raise HTTPException(status_code=404, detail={"code": "JOB_NOT_FOUND", "message": "Report job not found"})
        return job

    @app.get("/api/reports/{report_id}/preview", dependencies=[Depends(require_auth)])
    def get_preview_manifest(report_id: str):
        from pypdf import PdfReader

        artifact = resolve_report_artifact(report_id, format="pdf")
        if artifact is None:
            raise HTTPException(404, "PDF report not found")
        try:
            pages = len(PdfReader(artifact[0]).pages)
            if not 1 <= pages <= 2000:
                raise HTTPException(413, "PDF exceeds preview page limit")
            return {"pages": pages}
        except HTTPException:
            raise
        except Exception:
            _LOG.exception("Cannot read report preview %s", report_id)
            raise HTTPException(422, "PDF preview unavailable") from None

    @app.get("/api/reports/{report_id}/preview/{page_index}", dependencies=[Depends(require_auth)])
    def get_preview_page(report_id: str, page_index: Annotated[int, Field(ge=0, lt=2000)]):
        import pypdfium2 as pdfium

        artifact = resolve_report_artifact(report_id, format="pdf")
        if artifact is None:
            raise HTTPException(404, "PDF report not found")
        try:
            # PDFium is not thread safe; serialize preview requests and release native handles.
            with _PDF_PREVIEW_LOCK, pdfium.PdfDocument(str(artifact[0])) as document:
                if page_index >= len(document):
                    raise HTTPException(404, "PDF page not found")
                with closing(document[page_index]) as page:
                    width, height = page.get_size()
                    if width <= 0 or height <= 0:
                        raise ValueError("Invalid PDF page dimensions")
                    scale = min(1200 / width, 1800 / height)
                    with closing(page.render(scale=scale)) as bitmap:
                        image = bitmap.to_pil()
                        output = BytesIO()
                        image.save(output, format="PNG")
                        image.close()
            return Response(output.getvalue(), media_type="image/png", headers={"Cache-Control": "private, max-age=300"})
        except HTTPException:
            raise
        except Exception:
            _LOG.exception("Cannot render report preview %s page %s", report_id, page_index)
            raise HTTPException(422, "PDF preview unavailable") from None
