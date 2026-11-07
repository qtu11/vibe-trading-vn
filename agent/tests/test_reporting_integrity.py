"""Regression checks for evidence, artifact status and durable report receipts."""

import json
from pathlib import Path

from pydantic import ValidationError
import pytest

from src.reporting.schema import NarrativeSection, ResearchReport
from src.reporting.service import ReportJobError, ReportJobService
from src.reporting.tool import ExportResearchReportTool


def sample():
    path = Path(__file__).parents[1] / "vibe_report_engine/examples/demo_report.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("marker", ["(omitted※)", "（略※）", "(đã lược※)", "OMITTED ※"])
def test_redactions_are_rejected_instead_of_silently_erased(marker, tmp_path):
    payload = sample()
    payload["analysis_sections"] = [{"heading": "Chất lượng dữ liệu", "bullets": [f"Doanh thu {marker}"]}]
    with pytest.raises(ReportJobError, match="thiếu bằng chứng") as error:
        ReportJobService(tmp_path).create_job(payload)
    assert error.value.code == "SCHEMA_VALIDATION_FAILED"
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("location,field", [("financial_metrics", "value"), ("financial_metrics", "change"),
                                          ("price_history", "close"), ("price_history", "volume")])
@pytest.mark.parametrize("number", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_financial_inputs_rejected(location, field, number):
    payload = sample()
    payload[location][0][field] = number
    with pytest.raises(ValidationError):
        ResearchReport.model_validate(payload)


def test_duplicate_metric_keys_cannot_override_price_or_target():
    payload = sample()
    payload["valuation_metrics"].append(payload["financial_metrics"][0].copy())
    with pytest.raises(ValidationError, match="Trùng metric.key"):
        ResearchReport.model_validate(payload)


def test_upside_must_match_prices_and_units():
    payload = sample()
    payload["valuation_metrics"][1]["value"] = 200
    with pytest.raises(ValidationError, match="upside không khớp"):
        ResearchReport.model_validate(payload)
    payload = sample()
    payload["valuation_metrics"][0]["unit"] = "VND/cp"
    with pytest.raises(ValidationError, match="cùng đơn vị"):
        ResearchReport.model_validate(payload)


def test_large_upside_does_not_gain_a_larger_rounding_tolerance():
    payload = sample()
    payload["financial_metrics"][0]["value"] = 1
    payload["valuation_metrics"][0]["value"] = 1e9
    payload["valuation_metrics"][1].update(value=(1e9 - 1) * 100 + 50, decimals=4)
    with pytest.raises(ValidationError, match="upside không khớp"):
        ResearchReport.model_validate(payload)


def test_metric_date_cannot_exceed_report_cutoff():
    payload = sample()
    payload["financial_metrics"][0]["as_of"] = "2099-01-01"
    with pytest.raises(ValidationError, match="ngày tương lai"):
        ResearchReport.model_validate(payload)


def test_nested_typed_sections_cannot_bypass_redaction_check():
    payload = sample()
    payload["analysis_sections"] = [NarrativeSection(heading="Chất lượng dữ liệu", bullets=["Revenue (omitted※)"])]
    with pytest.raises(ValidationError, match="thiếu bằng chứng"):
        ResearchReport.model_validate(payload)


def test_model_cannot_self_certify_publication():
    payload = sample()
    payload["demo"] = False
    payload["publication_status"] = "certified"
    for source in payload["sources"]:
        source["status"] = "user_supplied"
        source["url"] = f"https://example.test/research/{source['id']}"
    payload["overview_evidence"] = {"source_ids": ["SIM02"]}
    payload["executive_summary_evidence"] = {"source_ids": ["SIM02"]}
    for point in payload["price_history"]:
        point["source_ids"] = ["SIM01"]
        point.update(unit="VND", price_basis="raw")
    assert ResearchReport.model_validate(payload).publication_status == "draft_unverified"


def fake_renderer(report, root, formats):
    directory = root / "renderer-owned-directory"
    directory.mkdir()
    path = directory / "research.docx"
    path.write_bytes(b"PK\x03\x04test-renderer-output")
    return {"docx": str(path), "warnings": ["PDF unavailable"] if "pdf" in formats else []}


def test_partial_export_survives_service_restart_and_cleans_staging(tmp_path, monkeypatch):
    monkeypatch.setattr("src.reporting.service.export_report", fake_renderer)
    job = ReportJobService(tmp_path).create_job(sample())
    assert job["status"] == "partial"
    assert job["error"]["code"] == "PARTIAL_EXPORT"
    assert job["publication_status"] == "simulated_demo"
    assert len(job["artifacts"]) == 1
    assert list((tmp_path / "staging").iterdir()) == []
    assert ReportJobService(tmp_path).get_job(job["job_id"]) == job
    assert ReportJobService(tmp_path / "other-root").get_job(job["job_id"]) is None


def test_render_failure_receipt_is_persisted_and_staging_cleaned(tmp_path, monkeypatch):
    def broken_renderer(**kwargs):
        (kwargs["root"] / "incomplete").write_text("partial", encoding="utf-8")
        raise RuntimeError("conversion failed")

    monkeypatch.setattr("src.reporting.service.export_report", broken_renderer)
    with pytest.raises(ReportJobError, match="conversion failed"):
        ReportJobService(tmp_path).create_job(sample())
    job_path = next(tmp_path.glob("*.json"))
    job = ReportJobService(tmp_path).get_job(job_path.stem)
    assert job["status"] == "failed"
    assert list((tmp_path / "staging").iterdir()) == []


def test_legitimate_footnote_survives_export(tmp_path, monkeypatch):
    payload = sample()
    payload["executive_summary"] += "\n※ Giá tham chiếu thuộc ngày cũ, cần cập nhật."
    seen = []

    def capture(**kwargs):
        seen.append(kwargs["report"].executive_summary)
        return fake_renderer(**kwargs)

    monkeypatch.setattr("src.reporting.service.export_report", capture)
    ReportJobService(tmp_path).create_job(payload, formats=["docx"])
    assert "※ Giá tham chiếu thuộc ngày cũ" in seen[0]


@pytest.mark.parametrize("formats", [[], ["pdf", "PDF"], [None], "pdf"])
def test_invalid_format_requests_fail_before_render(tmp_path, formats):
    with pytest.raises(ReportJobError):
        ReportJobService(tmp_path).create_job(sample(), formats=formats)


def test_tool_does_not_claim_success_when_pdf_missing(monkeypatch):
    monkeypatch.setattr("src.reporting.service.export_report", fake_renderer)
    receipt = json.loads(ExportResearchReportTool().execute(sample()))
    assert receipt["ok"] is False
    assert receipt["status"] == "partial"
    assert receipt["error"]["code"] == "PARTIAL_EXPORT"
    assert len(receipt["artifacts"]) == 1


def test_tool_does_not_replace_empty_format_request_with_defaults():
    receipt = json.loads(ExportResearchReportTool().execute(sample(), formats=[]))
    assert receipt["ok"] is False
    assert receipt["error_code"] == "MISSING_FORMATS"


def test_artifact_lookup_survives_restart_and_missing_legacy_index(tmp_path, monkeypatch):
    monkeypatch.setattr("src.reporting.service.export_report", fake_renderer)
    service = ReportJobService(tmp_path)
    job = service.create_job(sample(), formats=["docx"])
    report_id = job["artifacts"][0]["report_id"]
    assert ReportJobService(tmp_path).get_job_for_artifact(report_id) == job
    (tmp_path / "artifacts" / f"{report_id}.json").unlink()
    assert ReportJobService(tmp_path).get_job_for_artifact(report_id) == job
    assert service.get_job_for_artifact("../" + report_id) is None


def test_auxiliary_index_failure_does_not_hide_a_completed_export(tmp_path, monkeypatch):
    monkeypatch.setattr("src.reporting.service.export_report", fake_renderer)
    (tmp_path / "artifacts").write_text("legacy file blocks index directory", encoding="utf-8")
    service = ReportJobService(tmp_path)
    job = service.create_job(sample(), formats=["docx"])
    assert job["status"] == "succeeded" and job["error"] is None
    assert service.get_job_for_artifact(job["artifacts"][0]["report_id"]) == job


@pytest.mark.parametrize("error_type", [ValueError, OSError, RuntimeError])
def test_publishing_one_format_failure_preserves_already_available_download(tmp_path, monkeypatch, error_type):
    from src.tools.report_artifacts import publish_report_artifact

    def renderer(**kwargs):
        outputs = fake_renderer(**kwargs)
        pdf = Path(outputs["docx"]).with_suffix(".pdf")
        pdf.write_bytes(b"%PDF-1.7\nmock-output")
        return {**outputs, "pdf": str(pdf)}

    def publisher(path, format):
        if format == "pdf":
            raise error_type("PDF staging failed")
        return publish_report_artifact(path, format)

    monkeypatch.setattr("src.reporting.service.export_report", renderer)
    monkeypatch.setattr("src.reporting.service.publish_report_artifact", publisher)
    job = ReportJobService(tmp_path).create_job(sample())
    assert job["status"] == "partial"
    assert job["artifacts"][0]["filename"].endswith(".docx")
    assert job["error"] is not None
    assert ReportJobService(tmp_path).get_job(job["job_id"]) == job
    assert list((tmp_path / "staging").iterdir()) == []
