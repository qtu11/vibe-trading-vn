"""Authenticated API routes for Vibe Report Engine document generation."""

from __future__ import annotations

import logging
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from src.api.security import require_auth
from src.reporting.service import ReportJobError, ReportJobService

_LOG = logging.getLogger(__name__)


class ReportExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report: dict
    formats: list[Literal["docx", "pdf", "pptx"]] = Field(default=["docx", "pdf", "pptx"], min_length=1, max_length=3)
    run_id: Annotated[str, Field(strict=True, pattern=r"^[A-Za-z0-9_-]{1,100}$")] | None = None


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
            )
        except ReportJobError as exc:
            status_code = 422 if exc.code in ("SCHEMA_VALIDATION_FAILED", "INVALID_FORMAT", "MISSING_FORMATS") else 500
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
