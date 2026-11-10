"""The export repair loop must fix bindings, not delete the analysis.

The VIC run failed nine structured exports in a row. Reading the trace shows
why the report kept getting thinner (8 sections -> 3 -> 4):

1. A source URL mismatch was reported twice: once as ``sources.N.url`` and
   once as "Nguồn S1 chưa được thu thập" for *every* field that cited it.
   The model cleared the second class by deleting the content that cited it.
2. The repair hint literally said "bỏ hẳn mục đó" (drop the whole item).
3. Schema errors were revealed one class per retry, so each export attempt
   fixed one thing and surfaced the next.

These tests pin the mechanism that fixes all three.
"""

from __future__ import annotations

import json

from docx import Document
import pytest
from pydantic import ValidationError

from src.agent.grounding.identity import _IdentityMixin
from src.reporting.service import (
    ReportJobError,
    ReportJobService,
    _condense_validation_errors,
    _structured_validation_errors,
)
from src.reporting.tool import ExportResearchReportTool
from tests.test_report_calculation_validation import export_receipt
from tests.test_report_evidence_pipeline import _collected_page, research


def _load_fixture_payload() -> dict:
    from pathlib import Path

    fixture = Path(__file__).resolve().parent / "fixtures" / "export_stall_payloads.json"
    return json.loads(fixture.read_text(encoding="utf-8"))["iter_47"]["report"]


# ---------------------------------------------------------------------------
# 1. A URL mismatch is one repairable field, not a reason to drop the analysis
# ---------------------------------------------------------------------------


def test_url_mismatch_does_not_multiply_into_one_issue_per_citing_field(tmp_path, monkeypatch):
    """One wrong URL must not produce a wall of per-field "not collected" errors.

    This is the deletion trap. The VIC run answered one mismatch by removing
    the sections that cited the source, so the report shrank from eight
    chapters to three.
    """
    report, context = research(tmp_path)
    payload = report.model_dump(mode="json")
    payload["sources"][0]["url"] = "https://example.vn/guessed-source"
    payload["analysis_sections"] = [{
        "heading": "Cơ cấu doanh thu",
        "paragraphs": ["Doanh thu theo khối kinh doanh trong quý III."],
        "source_ids": [payload["sources"][0]["id"]],
        "evidence_kind": "cited",
    }]

    receipt, rendered = export_receipt(tmp_path, monkeypatch, payload, context)

    assert receipt["ok"] is False
    assert not rendered
    fields = {issue["field"] for issue in receipt["field_errors"]}
    # The URL is the only thing wrong; the section that cites it stays valid.
    assert fields == {"sources.0.url"}
    assert not any("chưa được công cụ thu thập" in issue["problem"] for issue in receipt["field_errors"])


def test_the_accepted_report_still_contains_the_analysis_after_a_url_repair(tmp_path, monkeypatch):
    """Repairing the URL must not require rebuilding the payload."""
    report, context = research(tmp_path)
    payload = report.model_dump(mode="json")
    payload["sources"][0]["url"] = "https://example.vn/guessed-source"
    payload["analysis_sections"] = [{
        "heading": "Cơ cấu doanh thu",
        "paragraphs": ["Doanh thu theo khối kinh doanh trong quý III."],
        "source_ids": [payload["sources"][0]["id"]],
        "evidence_kind": "cited",
    }]

    receipt, _ = export_receipt(tmp_path, monkeypatch, payload, context)
    issue = next(item for item in receipt["field_errors"] if item["field"] == "sources.0.url")
    repaired = receipt["accepted_report"]
    assert repaired["analysis_sections"], "the analysis must survive the rejection"
    repaired["sources"][0]["url"] = issue["expected_url"]
    retry, rendered = export_receipt(tmp_path, monkeypatch, repaired, context)

    assert retry["ok"] is True, retry.get("message")
    assert len(rendered) == 1
    assert rendered[0].analysis_sections, "the section must survive the repair"


# ---------------------------------------------------------------------------
# 2. The repair hint must never invite deletion
# ---------------------------------------------------------------------------


def test_the_evidence_repair_hint_forbids_deleting_analysis_sections():
    from src.reporting.tool import _REPAIR_HINTS

    hint = _REPAIR_HINTS["EVIDENCE_VALIDATION_FAILED"]
    assert "không xoá cả mục phân tích" in hint
    assert "expected_url" in hint
    assert "collected_sources" in hint
    # The old wording rewarded deletion.
    assert "bỏ hẳn mục đó" not in hint


def test_the_schema_repair_hint_forbids_deleting_sections():
    from src.reporting.tool import _REPAIR_HINTS

    hint = _REPAIR_HINTS["SCHEMA_VALIDATION_FAILED"]
    assert "không xoá mục để né lỗi schema" in hint
    assert "TẤT CẢ" in hint


# ---------------------------------------------------------------------------
# 3. One schema response must name every failure class
# ---------------------------------------------------------------------------


def test_schema_errors_name_every_class_in_one_response(tmp_path):
    """The model must see body + price_basis + heading together, not one at a time."""
    service = ReportJobService(storage_root=tmp_path)
    payload = _load_fixture_payload()
    payload["title"] = "VIC"
    payload["investment_theses"] = [{"title": "Luận điểm một", "text": "Sai trường."}]

    with pytest.raises(ReportJobError) as error:
        service.create_job(payload, formats=["docx"])

    details = error.value.details
    fields = {entry["field"] for entry in details}
    assert any("body" in field for field in fields), fields
    assert len(details) > 1, "repeated field errors must be grouped, not truncated"


def test_grouped_schema_errors_collapse_repeated_list_indices(tmp_path):
    """``investment_theses.0.body`` .. ``.3.body`` must become one group.

    The old cap of twelve raw errors was consumed by near-identical body
    errors, so the price_basis and methodology failures never surfaced.
    """
    service = ReportJobService(storage_root=tmp_path)
    payload = _load_fixture_payload()
    payload["title"] = "VIC"
    payload["investment_theses"] = [
        {"title": f"Luận điểm {index}", "text": "Sai trường."} for index in range(4)
    ]

    with pytest.raises(ReportJobError) as error:
        service.create_job(payload, formats=["docx"])

    details = error.value.details
    body_groups = [entry for entry in details if entry["field"].endswith("body")]
    assert len(body_groups) == 1, [entry["field"] for entry in details]
    assert "×4" in body_groups[0]["problem"]


def test_a_root_validator_message_names_the_payload_field(tmp_path):
    """``(root)`` is not a repair instruction; the message names the field."""
    service = ReportJobService(storage_root=tmp_path)
    payload = _load_fixture_payload()
    payload["financial_metrics"] = [{
        "key": "revenue", "label": "Doanh thu", "value": 100, "unit": "tỷ VND",
        "as_of": "2026-09-30", "evidence_kind": "derived",
    }]

    with pytest.raises(ReportJobError) as error:
        service.create_job(payload, formats=["docx"])

    fields = {entry["field"] for entry in error.value.details}
    assert "financial_metrics.revenue" in fields, fields


# ---------------------------------------------------------------------------
# 4. The repair packet must carry the pages this run actually read
# ---------------------------------------------------------------------------


def test_a_failed_export_lists_the_pages_the_run_actually_collected(tmp_path, monkeypatch):
    """A source repair must be a choice from a list, not another guess."""
    report, context = research(tmp_path)
    context = _collected_page(tmp_path, context, "Kết quả hợp nhất quý III: doanh thu 50.000 tỷ VND.")
    payload = report.model_dump(mode="json")
    payload["sources"][0]["url"] = "https://example.vn/guessed-source"

    receipt, _ = export_receipt(tmp_path, monkeypatch, payload, context)

    assert receipt["ok"] is False
    assert receipt["collected_sources"], "the model must see what it actually read"
    urls = {item["url"] for item in receipt["collected_sources"]}
    assert "https://example.vn/guessed-source" not in urls
    assert any("ir.example.vn" in url for url in urls)


# ---------------------------------------------------------------------------
# 5. A peer symbol must come with the one call that authorizes it
# ---------------------------------------------------------------------------


def test_a_peer_symbol_mismatch_names_the_resolver_call():
    """VIC.VN was locked; VHM.VN/VRE.VN came back as a bare identity error.

    The model never learned the single call that would authorize them, so the
    peer table stayed empty for the rest of the run.
    """
    hints = _IdentityMixin._venue_mismatch_hints("VHM.VN", ["VIC.VN"])
    assert hints
    assert "search_symbol('VHM.VN')" in hints[0]
    assert "different instrument" in hints[0]


def test_an_unresolved_bare_ticker_names_the_resolver_call():
    hints = _IdentityMixin._venue_mismatch_hints("MBB", ["VIC.VN"])
    assert hints
    assert "search_symbol('MBB')" in hints[0]


def test_a_second_venue_of_the_same_issuer_stays_a_venue_hint():
    hints = _IdentityMixin._venue_mismatch_hints("BLDP.US", ["BLDP.TO"])
    assert hints
    assert "second venue" in hints[0]


# ---------------------------------------------------------------------------
# 6. Chapter numbers belong to the renderer, not the payload
# ---------------------------------------------------------------------------


def test_a_numbered_heading_is_stripped_before_rendering(tmp_path):
    """``1. Kết luận`` would render as ``06 1. Kết luận``."""
    from src.reporting.normalize import normalize_report_payload

    payload = _load_fixture_payload()
    payload["analysis_sections"] = [{
        "heading": "1. Kết luận đầu tư",
        "paragraphs": ["Đoạn phân tích có nguồn."],
        "source_ids": [],
        "evidence_kind": "assumption",
        "methodology": "Bình luận phân tích",
    }]

    normalized, warnings = normalize_report_payload(payload)

    assert normalized["analysis_sections"][0]["heading"] == "Kết luận đầu tư"
    assert any("số thứ tự" in warning for warning in warnings)


def test_a_year_is_not_a_chapter_number(tmp_path):
    """``2026 - Triển vọng`` is content, not numbering."""
    from src.reporting.normalize import normalize_report_payload

    payload = _load_fixture_payload()
    payload["analysis_sections"] = [{
        "heading": "2026 - Triển vọng kinh doanh",
        "paragraphs": ["Đoạn phân tích có nguồn."],
        "source_ids": [],
        "evidence_kind": "assumption",
        "methodology": "Bình luận phân tích",
    }]

    normalized, _ = normalize_report_payload(payload)

    assert normalized["analysis_sections"][0]["heading"] == "2026 - Triển vọng kinh doanh"
