"""Comprehensive tests for Vibe Report Engine service, renderer, tool and artifacts."""

import json
from pathlib import Path
import pytest

from src.reporting.brand import resolve_brand_logo
from src.reporting.service import ReportJobError, ReportJobService
from src.reporting.tool import ExportResearchReportTool
from src.tools.report_artifacts import resolve_report_artifact

SAMPLE_PATH = Path(__file__).resolve().parents[1] / "vibe_report_engine" / "examples" / "demo_report.json"


def load_sample_report() -> dict:
    return json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))


def test_brand_logo_resolution():
    logo = resolve_brand_logo()
    assert logo is not None
    assert logo.is_file()


def test_report_service_creation(tmp_path):
    sample = load_sample_report()
    service = ReportJobService(storage_root=tmp_path)
    job = service.create_job(sample, formats=["docx", "pdf"])

    assert job["status"] == "succeeded"
    assert job["publication_status"] == "simulated_demo"
    assert len(job["artifacts"]) == 2

    # Check artifacts
    docx_art = next(a for a in job["artifacts"] if a["filename"].endswith(".docx"))
    pdf_art = next(a for a in job["artifacts"] if a["filename"].endswith(".pdf"))

    assert docx_art["size_bytes"] > 20000
    assert len(docx_art["sha256"]) == 64
    assert pdf_art["size_bytes"] > 20000
    assert len(pdf_art["sha256"]) == 64

    # Verify resolution from report_artifacts storage
    resolved_docx = resolve_report_artifact(docx_art["report_id"])
    assert resolved_docx is not None
    assert resolved_docx[0].is_file()
    assert resolved_docx[1] == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    resolved_pdf = resolve_report_artifact(pdf_art["report_id"])
    assert resolved_pdf is not None
    assert resolved_pdf[0].is_file()
    assert resolved_pdf[1] == "application/pdf"


def test_report_service_validation_rejection(tmp_path):
    sample = load_sample_report()
    sample["investment_theses"][0]["source_ids"] = ["NON_EXISTENT_SOURCE"]
    service = ReportJobService(storage_root=tmp_path)

    with pytest.raises(ReportJobError) as exc_info:
        service.create_job(sample)
    assert exc_info.value.code == "SCHEMA_VALIDATION_FAILED"


def test_export_research_report_tool(tmp_path):
    sample = load_sample_report()
    tool = ExportResearchReportTool()
    output_str = tool.execute(sample, formats=["docx", "pdf"])
    receipt = json.loads(output_str)

    assert receipt["ok"] is True
    assert "job_id" in receipt
    assert len(receipt["artifacts"]) == 2
    assert "report_artifact" in receipt["fence"]
    assert receipt["job_id"] in receipt["fence"]
