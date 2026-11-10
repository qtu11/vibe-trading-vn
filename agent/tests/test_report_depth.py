"""Measured document pages must agree with the requested delivery depth."""

import json
from pathlib import Path

from docx import Document
from pydantic import ValidationError
from pypdf import PdfWriter
import pytest

from src.api.reports_routes import ReportExportRequest
from src.reporting.service import ReportJobError, ReportJobService
from src.reporting.tool import ExportResearchReportTool


def report():
    return json.loads((Path(__file__).parents[1] / "vibe_report_engine/examples/demo_report.json").read_text(encoding="utf-8"))


def renderer(pages, observed):
    def render(report, root, formats):
        observed.extend(formats)
        docx = root / "fixture.docx"
        Document().save(docx)
        output = {"docx": str(docx), "warnings": []}
        if pages is not None:
            pdf = root / "fixture.pdf"
            with PdfWriter() as writer:
                for _ in range(pages):
                    writer.add_blank_page(595, 842)
                writer.write(pdf)
            output["pdf"] = str(pdf)
        return output
    return render


@pytest.mark.parametrize("pages,status", [(23, "partial"), (24, "succeeded")])
def test_actual_pdf_depth_controls_status_without_hiding_available_docx(tmp_path, monkeypatch, pages, status):
    formats = []
    monkeypatch.setattr("src.reporting.service.export_report", renderer(pages, formats))
    service = ReportJobService(tmp_path)
    job = service.create_job(report(), formats=["docx"], minimum_pages=24)
    assert formats == ["docx", "pdf"]
    assert job["status"] == status
    assert job["minimum_pages"] == 24 and job["pdf_pages"] == pages
    assert [item["filename"] for item in job["artifacts"]] == ["fixture.docx"]
    assert service.get_job_for_artifact(job["artifacts"][0]["report_id"]) == job
    if pages < 24:
        assert job["error"]["code"] == "INSUFFICIENT_REPORT_DEPTH"
    else:
        assert job["error"] is None


def test_missing_page_count_cannot_report_success(tmp_path, monkeypatch):
    monkeypatch.setattr("src.reporting.service.export_report", renderer(None, []))
    job = ReportJobService(tmp_path).create_job(report(), formats=["docx"], minimum_pages=24)
    assert job["status"] == "partial" and len(job["artifacts"]) == 1
    assert job["pdf_pages"] is None and job["error"]["code"] == "PAGE_COUNT_UNAVAILABLE"


@pytest.mark.parametrize("minimum", [True, "24", 0, -1, 2001])
def test_invalid_page_requirement_is_rejected_before_rendering(tmp_path, minimum):
    with pytest.raises(ReportJobError) as error:
        ReportJobService(tmp_path).create_job(report(), minimum_pages=minimum)
    assert error.value.code == "INVALID_PAGE_COUNT"


def test_deep_report_tool_reports_shortfall_without_hiding_the_docx(monkeypatch):
    """A short document is delivered, not refused.

    The tool used to default to 24 pages and report ``ok: false`` whenever a
    report fell short. That told the model the export had failed, so it
    retried -- eight reasoning rounds burned to produce a file that already
    existed. The depth gate reports depth; it does not decide whether the
    export happened.
    """
    monkeypatch.setattr("src.reporting.service.export_report", renderer(23, []))
    receipt = json.loads(
        ExportResearchReportTool().execute(report(), formats=["docx"], minimum_pages=24)
    )
    assert receipt["pdf_pages"] == 23
    assert receipt["ok"] is True
    assert receipt["status"] == "partial"
    assert receipt["error"]["code"] == "INSUFFICIENT_REPORT_DEPTH"
    assert receipt["download_links"]
    assert receipt["depth_shortfall"]["pdf_pages"] == 23


def test_export_tool_without_a_depth_gate_does_not_measure_pages(monkeypatch):
    """No gate requested means no page count and no shortfall note."""
    monkeypatch.setattr("src.reporting.service.export_report", renderer(23, []))
    receipt = json.loads(ExportResearchReportTool().execute(report(), formats=["docx"]))
    assert receipt["ok"] is True
    assert receipt["status"] == "succeeded"
    assert receipt["pdf_pages"] is None
    assert "depth_shortfall" not in receipt


def test_export_api_defaults_to_one_page_and_rejects_non_integer_requirements():
    assert ReportExportRequest(report={}).minimum_pages == 1
    assert ReportExportRequest(report={}, minimum_pages=24).minimum_pages == 24
    for value in (True, "24", 0, 2001):
        with pytest.raises(ValidationError):
            ReportExportRequest(report={}, minimum_pages=value)
