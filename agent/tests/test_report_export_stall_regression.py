"""Regression tests for the export-stall loop seen in the screenshot.

The failed run reported::

    Execution failed: no_progress: I stopped because 8 tool rounds in a row
    produced no new information: export_research_report failed
    [SCHEMA_VALIDATION_FAILED] x7, edit_file failed (File not found:
    report.json) x1

Three defects combined to produce it:

1. ``minimum_pages`` defaulted to 24. A report that rendered a valid 12-page
   DOCX was reported as a *failed* export, so the model retried instead of
   delivering the file it already had.
2. A failed export returned a bare error code. The model had no way to learn
   which field to fix and re-derived the whole payload every round.
3. The model, unable to export, fell back to writing the report JSON to a
   file with ``edit_file report.json`` -- a path that can never produce the
   branded document and failed too.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.reporting.service import ReportJobError, ReportJobService
from src.reporting.tool import ExportResearchReportTool

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "export_stall_payloads.json"


def load_payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["iter_47"]["report"]


def test_export_defaults_to_no_depth_gate():
    """The tool must not demand 24 pages nobody asked for.

    A depth gate nobody asked for is a gate that always fails: the export
    then reports a working document as a failure and the model retries.
    """
    assert ExportResearchReportTool.parameters["properties"]["minimum_pages"]["default"] == 1


def test_export_that_underfills_depth_is_still_a_success(tmp_path, monkeypatch):
    """A rendered document is a success even when the depth gate is not met.

    The gate reports how deep the analysis is. It does not say whether the
    export happened.
    """
    service = ReportJobService(storage_root=tmp_path)
    sample = load_payload()
    job = service.create_job(sample, formats=["docx"], minimum_pages=400)

    # The service still records the shortfall...
    assert job["status"] == "partial"
    assert job["error"]["code"] == "INSUFFICIENT_REPORT_DEPTH"
    # ...but the document itself exists and is downloadable.
    assert job["artifacts"]
    assert job["artifacts"][0]["filename"].endswith(".docx")


def test_tool_reports_delivered_artifacts_as_ok(tmp_path, monkeypatch):
    """The receipt must not say ``ok: false`` for a document that exists.

    This is the exact trap that produced the eight-round loop: the export
    produced a valid DOCX, the receipt said the export failed, and the model
    burned a reasoning round per retry.
    """
    monkeypatch.setattr(
        "src.reporting.tool.ReportJobService",
        lambda *args, **kwargs: ReportJobService(storage_root=tmp_path),
    )
    tool = ExportResearchReportTool()
    receipt = json.loads(tool.execute(report=load_payload(), formats=["docx"]))

    assert receipt["ok"] is True
    assert receipt["artifacts"]
    assert receipt["download_links"][0]["url"].startswith("/api/reports/")


def test_tool_marks_depth_shortfall_without_hiding_the_document(tmp_path, monkeypatch):
    """A depth shortfall is reported as a note, not as a failure."""
    monkeypatch.setattr(
        "src.reporting.tool.ReportJobService",
        lambda *args, **kwargs: ReportJobService(storage_root=tmp_path),
    )
    tool = ExportResearchReportTool()
    receipt = json.loads(
        tool.execute(report=load_payload(), formats=["docx"], minimum_pages=400)
    )

    assert receipt["ok"] is True
    assert receipt["artifacts"]
    assert receipt["depth_shortfall"]["pdf_pages"] < 400
    assert receipt["depth_shortfall"]["requested_minimum_pages"] == 400


def test_failed_export_names_the_fields_to_fix(tmp_path):
    """A schema failure must say *where* to look, not only that it failed.

    The model repaired the same payload seven times without knowing which
    field was still wrong.
    """
    service = ReportJobService(storage_root=tmp_path)
    payload = load_payload()
    # Break one field in a way the normalizer cannot repair: a title that is
    # too short fails the schema's own minimum-length rule.
    payload["title"] = "VIC"

    with pytest.raises(ReportJobError) as exc_info:
        service.create_job(payload, formats=["docx"])

    error = exc_info.value
    assert error.code == "SCHEMA_VALIDATION_FAILED"
    assert error.details, "the failure must name the fields to fix"
    fields = {entry["field"] for entry in error.details}
    assert any("title" in field for field in fields)
    assert all(entry["fix"] for entry in error.details)


def test_failed_export_echoes_the_accepted_payload(tmp_path):
    """The retry must be a diff, not a rewrite from scratch.

    ``accepted_report`` hands back the normalised payload, so the model can
    see exactly what the server already accepted.
    """
    service = ReportJobService(storage_root=tmp_path)
    payload = load_payload()
    payload["title"] = "VIC"

    with pytest.raises(ReportJobError) as exc_info:
        service.create_job(payload, formats=["docx"])

    error = exc_info.value
    assert error.normalized_report is not None
    assert error.normalization_warnings, "the model must know what was auto-repaired"


def test_failure_receipt_forbids_the_file_fallback(tmp_path, monkeypatch):
    """The receipt must close the ``edit_file report.json`` dead end.

    Unable to export, the model wrote the report JSON to a file. That is
    never the deliverable, and it failed too, costing another round.
    """
    monkeypatch.setattr(
        "src.reporting.tool.ReportJobService",
        lambda *args, **kwargs: ReportJobService(storage_root=tmp_path),
    )
    tool = ExportResearchReportTool()
    payload = load_payload()
    payload["title"] = "VIC"

    receipt = json.loads(tool.execute(report=payload, formats=["docx"]))

    assert receipt["ok"] is False
    assert receipt["error_code"] == "SCHEMA_VALIDATION_FAILED"
    assert "do_not" in receipt
    assert "write_file" in receipt["do_not"]
    assert "field_errors" in receipt
    assert "accepted_report" in receipt


def test_every_recorded_stall_payload_now_exports(tmp_path):
    """All seven payloads from the failed run must reach a rendered document.

    They are the real payloads the model produced, so they are the ground
    truth for what the normalizer has to absorb.
    """
    payloads = json.loads(FIXTURE.read_text(encoding="utf-8"))
    service = ReportJobService(storage_root=tmp_path)

    for key, blob in payloads.items():
        job = service.create_job(blob["report"], formats=["docx"], minimum_pages=1)
        assert job["status"] == "succeeded", f"{key} did not export: {job.get('error')}"
        assert job["artifacts"], f"{key} produced no artifact"
