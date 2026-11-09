"""End-to-end check: the stalled payloads must reach the evidence stage.

Before the fix, every one of the seven stalled payloads failed at
``SCHEMA_VALIDATION_FAILED`` (shape errors) before any number was ever
checked. The shape repair moves them forward; the *evidence* stage must still
reject a figure that is absent from the collected source text, because that
rejection is the whole point of the gate.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.reporting.schema import ResearchReport
from src.reporting.service import ReportJobError, ReportJobService

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "export_stall_payloads.json"


def load_payloads() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", ["iter_40", "iter_41", "iter_42", "iter_43", "iter_45", "iter_46", "iter_47"])
def test_stalled_payload_passes_schema_validation(name, tmp_path):
    """Every stalled payload must clear the *shape* contract after repair."""
    payloads = load_payloads()
    report = payloads[name]["report"]
    service = ReportJobService(storage_root=tmp_path)
    try:
        service.create_job(report, formats=["docx"], minimum_pages=1)
    except ReportJobError as exc:
        # The shape errors are gone; only evidence-stage rejections remain.
        assert exc.code != "SCHEMA_VALIDATION_FAILED", (
            f"{name} still fails schema validation: {exc.message}"
        )
        assert exc.code in {"EVIDENCE_VALIDATION_FAILED", "INVALID_PAYLOAD"}, exc.code


def test_evidence_stage_still_rejects_unbacked_numbers(tmp_path):
    """A figure absent from the collected source text must still be refused."""
    from src.agent.grounding.sources import SourceRecord
    from src.reporting.evidence import ReportEvidenceContext, validate_report_evidence

    report = ResearchReport.model_validate({
        "market": "VN_EQUITY",
        "symbol": "AAA.VN",
        "exchange": "HOSE",
        "company_name": "AAA",
        "title": "Tên báo cáo kiểm thử",
        "subtitle": "Phụ đề báo cáo kiểm thử",
        "data_as_of": "2026-11-06",
        "overview": "Tổng quan đủ dài để hợp lệ theo schema báo cáo.",
        "executive_summary": "Tóm tắt đủ dài để hợp lệ theo schema báo cáo.",
        "overview_evidence": {"evidence_kind": "cited", "source_ids": ["S1"]},
        "executive_summary_evidence": {"evidence_kind": "cited", "source_ids": ["S1"]},
        "sources": [{"id": "S1", "title": "Nguồn thu thập", "provider": "Test Provider", "url": "https://e.com/a"}],
        "financial_metrics": [{
            "key": "revenue", "label": "Doanh thu", "value": 1234.5,
            "unit": "tỷ VND", "as_of": "2026-11-06", "source_ids": ["S1"],
        }],
    })
    record = SourceRecord(
        source_id="S1", call_id="c1", tool="web_search", url="https://e.com/a",
        domain="e.com", title="Nguồn thu thập", publisher="Test Provider", tier=1,
        market=("VN_EQUITY",), published_at=None, retrieved_at="2026-11-06T08:00:00Z",
        language="vi", excerpt="Doanh thu 10 tỷ và 20 tỷ.", quotes=(),
        numbers=(10.0, 20.0),
        text_sha256="a" * 64, content_chars=120, cite_allowed=True,
    )
    context = ReportEvidenceContext(sources=(record,))
    with pytest.raises(ValueError):
        validate_report_evidence(report, context)
