"""Standalone FastAPI example. Integration: import router into existing app.

This only RENDERS a validated research result; it does not claim to run live analysis.
"""
from __future__ import annotations
import os
import secrets
from pathlib import Path
from typing import Literal
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse

from schema import ResearchReport
from renderer import export_report

router = APIRouter(prefix="/api/v1/reports", tags=["Vibe Research Export"])
OUTPUT_ROOT = Path(os.environ.get("VIBE_REPORT_OUTPUT_DIR", str(Path(__file__).parent / "outputs")))


def require_api_key(authorization: str | None = Header(default=None)):
    expected = os.environ.get("VIBE_REPORT_API_KEY")
    if not expected:
        raise HTTPException(status_code=503, detail="VIBE_REPORT_API_KEY chưa cấu hình")
    supplied = (authorization or "").removeprefix("Bearer ")
    if not secrets.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")


@router.post("/render/{fmt}", dependencies=[Depends(require_api_key)])
def render(report: ResearchReport, fmt: Literal["docx", "pdf"]):
    result = export_report(report, OUTPUT_ROOT, formats=(fmt,))
    filename = Path(result[fmt]).name
    media_type = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if fmt == "docx" else "application/pdf"
    )
    return FileResponse(result[fmt], filename=filename, media_type=media_type)


app = FastAPI(title="Vibe-Trading Report Engine (standalone sample)")
app.include_router(router)
