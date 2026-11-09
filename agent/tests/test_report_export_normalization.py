"""Replay the payloads that stalled the export in the screenshot.

Each fixture is a real model payload from the failed run (see
``tests/fixtures/export_stall_payloads.json``) that produced
``SCHEMA_VALIDATION_FAILED``. The normalizer must repair the shape, and the
export must then reach the *evidence* stage -- where a genuine "number not in
collected source text" rejection is correct and must stay.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.reporting.normalize import normalize_report_payload

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "export_stall_payloads.json"


def load_payloads() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_fixture_covers_the_observed_stall_shapes():
    payloads = load_payloads()
    assert payloads, "fixture must not be empty"
    assert "iter_40" in payloads
    first = payloads["iter_40"]
    # The exact near-misses seen in the failed run.
    assert first["report"]["market"] == "Vietnam"
    assert first["report"]["price_history"]["dates"]
    assert isinstance(first["report"]["analysis_sections"][0]["paragraphs"][0], dict)
    assert first["report"]["key_stats"][0]["value"] == 234500


def test_normalizer_repairs_iter_40_shape():
    payloads = load_payloads()
    normalized, warnings = normalize_report_payload(payloads["iter_40"]["report"])

    assert normalized["market"] == "VN_EQUITY"
    # price_history becomes a list of PricePoint-shaped dicts.
    assert isinstance(normalized["price_history"], list)
    assert normalized["price_history"][0]["unit"]
    assert normalized["price_history"][0]["price_basis"]
    assert normalized["price_history"][0]["source_ids"]
    # Paragraph objects become plain strings, and their ids move to the section.
    section = normalized["analysis_sections"][0]
    assert all(isinstance(p, str) for p in section["paragraphs"])
    assert section["source_ids"]
    # Numeric key_stats become strings.
    assert isinstance(normalized["key_stats"][0]["value"], str)
    # Charts: bars unwrapped from a one-element list.
    chart = normalized["analysis_sections"][1]["charts"][0]
    assert isinstance(chart["bars"], dict)
    # Over-long charts keep only the most recent 8 periods.
    assert len(chart["categories"]) == 8
    assert len(chart["bars"]["values"]) == 8
    # Metrics gained keys, and the top-level market_price became a metric.
    metric_keys = {m["key"] for m in normalized["financial_metrics"]}
    assert "market_price" in metric_keys
    assert all("key" in m for m in normalized["valuation_metrics"])
    assert warnings


def test_normalizer_never_invents_numbers():
    payloads = load_payloads()
    original = payloads["iter_40"]["report"]
    normalized, _ = normalize_report_payload(original)

    # A metric may be *renamed* (the model declared it without a key) but never
    # created out of prose or a methodology string. Compare by label+value.
    def fingerprint(items):
        out = set()
        for item in items or []:
            if isinstance(item, dict):
                out.add((str(item.get("label", "")), str(item.get("value", ""))))
        return out

    declared = fingerprint(original.get("financial_metrics")) | fingerprint(original.get("valuation_metrics"))
    after = fingerprint(normalized["financial_metrics"]) | fingerprint(normalized["valuation_metrics"])
    # Only the top-level market_price may be added, and it must carry the very
    # value the model supplied for it.
    assert after - declared <= {("Giá thị trường tham chiếu", "234500")}

    # A number mentioned only inside a methodology string stays text: the
    # share count "7.498.740.060 cổ phiếu" must not become a metric row.
    share_rows = [
        m for m in normalized["financial_metrics"]
        if "7.498" in json.dumps(m, ensure_ascii=False)
    ]
    assert not share_rows


def test_normalizer_drops_dangling_input_keys():
    payloads = load_payloads()
    payload = {
        "market": "VN_EQUITY",
        "symbol": "AAA.VN",
        "exchange": "HOSE",
        "company_name": "AAA",
        "title": "Tên báo cáo",
        "subtitle": "Phụ đề báo cáo",
        "data_as_of": "2026-11-06",
        "overview": "Tổng quan đủ dài để hợp lệ theo schema.",
        "executive_summary": "Tóm tắt đủ dài để hợp lệ theo schema.",
        "sources": [{"id": "S1", "title": "Nguồn", "provider": "P", "url": "https://e.com/a"}],
        "financial_metrics": [{"key": "revenue", "label": "Doanh thu", "value": 10,
                               "unit": "tỷ VND", "as_of": "2026-11-06", "source_ids": ["S1"]}],
        "executive_summary_evidence": {"evidence_kind": "derived", "input_keys": ["revenue", "ghost"]},
    }
    normalized, warnings = normalize_report_payload(payload)
    assert normalized["executive_summary_evidence"]["input_keys"] == ["revenue"]
    assert any("ghost" in w for w in warnings)


def test_normalizer_keeps_unknown_source_ids_for_the_schema_to_reject():
    """An unresolvable source id is a reference error, not a shape error.

    Silently dropping it would let a report cite a source that does not
    exist -- exactly the "fake data" failure the export gate exists to
    prevent. The id must survive normalisation so the schema rejects it.
    """
    payloads = load_payloads()
    payload = {
        "market": "VN_EQUITY",
        "symbol": "AAA.VN",
        "exchange": "HOSE",
        "company_name": "AAA",
        "title": "Tên báo cáo",
        "subtitle": "Phụ đề báo cáo",
        "data_as_of": "2026-11-06",
        "overview": "Tổng quan đủ dài để hợp lệ theo schema.",
        "executive_summary": "Tóm tắt đủ dài để hợp lệ theo schema.",
        "sources": [{"id": "S1", "title": "Nguồn", "provider": "P", "url": "https://e.com/a"}],
        "financial_metrics": [{"key": "revenue", "label": "Doanh thu", "value": 10,
                               "unit": "tỷ VND", "as_of": "2026-11-06", "source_ids": ["S1"]}],
        "investment_theses": [{"title": "Luận điểm", "body": "Nội dung luận điểm đủ dài.",
                               "source_ids": ["S1", "S9"]}],
    }
    normalized, _ = normalize_report_payload(payload)
    assert normalized["investment_theses"][0]["source_ids"] == ["S1", "S9"]

    from src.reporting.schema import ResearchReport
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ResearchReport.model_validate(normalized)


def test_normalizer_does_not_mutate_input():
    payloads = load_payloads()
    original = json.loads(json.dumps(payloads["iter_40"]["report"]))
    normalize_report_payload(payloads["iter_40"]["report"])
    assert payloads["iter_40"]["report"] == original
