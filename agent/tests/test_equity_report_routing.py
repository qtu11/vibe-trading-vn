"""Equity report failures cannot escape through the general PDF writer."""

import json

from pypdf import PdfReader
import pytest

from src.agent.grounding import GroundingLedger
from src.agent.tool_context import current_grounding
from src.reporting.service import ReportJobError
from src.reporting.tool import ExportResearchReportTool
from src.tools.write_file_tool import WriteFileTool


@pytest.fixture(autouse=True)
def private_output(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBE_TRADING_HOME", str(tmp_path / "runtime"))
    monkeypatch.setattr("src.tools.write_file_tool.allowed_write_roots", lambda: [tmp_path])


@pytest.mark.parametrize("content", [
    "# VIC – Báo cáo phân tích cổ phiếu\nHOSE · Tập đoàn Vingroup",
    "# Equity Research: MBB\nBusiness and valuation analysis",
    "# Stock analysis report\nRevenue and cash flows",
    "# 证券研究报告\n股票估值分析",
])
def test_equity_pdf_redirect_preserves_existing_document(tmp_path, content):
    target = tmp_path / "report.pdf"
    target.write_bytes(b"previous document")
    result = json.loads(WriteFileTool().execute(path=str(target), content=content))
    assert result["status"] == "error"
    assert result["error_code"] == "EQUITY_REPORT_REQUIRES_ENGINE"
    assert result["required_tool"] == "export_research_report"
    assert "download_url" not in result
    assert target.read_bytes() == b"previous document"


def test_failed_evidence_export_cannot_fall_back_to_generic_pdf(tmp_path, monkeypatch):
    def reject_evidence(*args, **kwargs):
        raise ReportJobError("EVIDENCE_VALIDATION_FAILED", "Source URL did not match this run")

    monkeypatch.setattr("src.reporting.service.ReportJobService.create_job", reject_evidence)
    ledger = GroundingLedger(run_dir=tmp_path / "run", user_message="Finish the document")
    token = current_grounding.set(ledger)
    try:
        failed_export = ExportResearchReportTool().execute(report={}, formats=["pdf"])
        assert json.loads(failed_export)["error_code"] == "EVIDENCE_VALIDATION_FAILED"
        ledger.ingest_tool_result(
            tool_name="export_research_report", arguments={"report": {}},
            result=failed_export, call_id="failed-export", success=False,
        )
        target = tmp_path / "new" / "output.pdf"
        result = json.loads(WriteFileTool().execute(path=str(target), content="# Finished document"))
    finally:
        current_grounding.reset(token)
    assert result["error_code"] == "EQUITY_REPORT_REQUIRES_ENGINE"
    assert "source URLs" in result["hint"]
    assert not target.parent.exists()


def test_request_routes_equity_pdf_even_with_a_generic_document_title(tmp_path):
    ledger = GroundingLedger(run_dir=tmp_path / "run", user_message="Lập báo cáo phân tích cổ phiếu VIC")
    token = current_grounding.set(ledger)
    try:
        result = json.loads(WriteFileTool().execute(path=str(tmp_path / "output.pdf"), content="# Overview"))
    finally:
        current_grounding.reset(token)
    assert result["error_code"] == "EQUITY_REPORT_REQUIRES_ENGINE"


def test_unrelated_pdf_remains_a_real_downloadable_document(tmp_path):
    target = tmp_path / "meeting.pdf"
    ledger = GroundingLedger(run_dir=tmp_path / "run", user_message="Xuất biên bản họp thành PDF")
    token = current_grounding.set(ledger)
    try:
        result = json.loads(WriteFileTool().execute(path=str(target), content="# Meeting notes\nNext meeting: Monday."))
    finally:
        current_grounding.reset(token)
    assert result["status"] == "ok", result
    assert result["download_url"].startswith("/api/reports/")
    assert len(PdfReader(target).pages) == 1
    assert "Meeting notes" in PdfReader(target).pages[0].extract_text()


def test_equity_markdown_can_still_be_saved_as_working_material(tmp_path):
    target = tmp_path / "research.md"
    content = "# Equity research\nWorking source notes."
    result = json.loads(WriteFileTool().execute(path=str(target), content=content))
    assert result["status"] == "ok"
    assert target.read_text(encoding="utf-8") == content
