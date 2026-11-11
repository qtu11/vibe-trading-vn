"""Replay the payloads that stalled the export in the screenshot.

Each fixture is a real model payload from the failed run (see
``tests/fixtures/export_stall_payloads.json``) that produced
``SCHEMA_VALIDATION_FAILED``. The normalizer must repair the shape, and the
export must then reach the *evidence* stage -- where a genuine "number not in
collected source text" rejection is correct and must stay.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from src.reporting.normalize import normalize_report_payload
from src.reporting.schema import Metric, PricePoint, Source

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "export_stall_payloads.json"


@pytest.mark.parametrize("basis,canonical", [("split", "split_adjusted"), ("split_dividend", "total_return")])
def test_market_data_basis_names_preserve_adjustment_meaning(basis, canonical):
    point = PricePoint(date="2026-11-09", close=50000, unit="VND", price_basis=basis)
    metric = Metric(key="market_price", label="Giá tham chiếu", price_basis=basis)
    source = Source(id="S1", title="Yahoo Finance", provider="Yahoo", price_basis=basis)
    assert point.price_basis == metric.price_basis == source.price_basis == canonical


def test_additive_adjustment_is_not_silently_relabelled_as_total_return():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        PricePoint(date="2026-11-09", close=50000, price_basis="split_dividend_additive")


def test_iso_timestamps_in_date_fields_are_trimmed_not_rejected():
    """``date`` fields reject timestamps; the normalizer trims the time part.

    The TCB run failed with "Datetimes provided to dates should have zero
    time" for four spots: ``data_as_of``, metric ``as_of``, source
    ``published_at`` and ``price_history[*].date``. Each one is a real date
    with a clock attached, so trimming is lossless for the contract.
    """
    payload = {
        "data_as_of": "2026-09-30T15:04:05+07:00",
        "financial_metrics": [
            {"key": "revenue", "label": "Doanh thu", "value": 1.0,
             "as_of": "2026-09-30T00:00:00"},
        ],
        "sources": [
            {"id": "S1", "title": "CafeF", "provider": "CafeF",
             "url": "https://cafef.vn/tcb.chn",
             "published_at": "2026-09-30T10:00:00+07:00"},
        ],
        "price_history": [
            {"date": "2026-09-30T00:00:00", "close": 50000, "unit": "VND",
             "price_basis": "raw"},
        ],
    }

    normalized, warnings = normalize_report_payload(payload)

    assert normalized["data_as_of"] == "2026-09-30"
    assert normalized["financial_metrics"][0]["as_of"] == "2026-09-30"
    assert normalized["sources"][0]["published_at"] == "2026-09-30"
    assert normalized["price_history"][0]["date"] == "2026-09-30"
    # The schema accepts the repaired values; this is the exact validator that
    # raised the stall, so exercising it is the regression check.
    assert TypeAdapter(date).validate_python(normalized["data_as_of"]) == date(2026, 9, 30)
    assert Metric.model_validate(normalized["financial_metrics"][0]).as_of == date(2026, 9, 30)
    assert Source.model_validate(normalized["sources"][0]).published_at == date(2026, 9, 30)
    assert PricePoint.model_validate(normalized["price_history"][0]).date == date(2026, 9, 30)
    assert len([w for w in warnings if "chỉ giữ ngày" in w]) == 4


def test_top_level_market_price_as_of_is_coerced_after_folding():
    """The folded ``market_price`` is inserted after metric normalization."""
    payload = {
        "data_as_of": "2026-09-30T00:00:00",
        "market_price": {"value": 50000, "as_of": "2026-09-30T00:00:00", "unit": "VND"},
    }

    normalized, _ = normalize_report_payload(payload)

    metric = normalized["financial_metrics"][0]
    assert metric["key"] == "market_price"
    assert metric["as_of"] == "2026-09-30"
    assert Metric.model_validate(metric).as_of == date(2026, 9, 30)


def test_plain_date_strings_are_not_changed_or_warned():
    payload = {
        "data_as_of": "2026-09-30",
        "financial_metrics": [{"key": "revenue", "label": "Doanh thu", "value": 1.0,
                               "as_of": "2026-09-30"}],
        "sources": [{"id": "S1", "title": "CafeF", "provider": "CafeF",
                     "url": "https://cafef.vn/tcb.chn", "published_at": "2026-09-30"}],
        "price_history": [{"date": "2026-09-30", "close": 50000, "unit": "VND",
                           "price_basis": "raw"}],
    }

    normalized, warnings = normalize_report_payload(payload)

    assert normalized["data_as_of"] == "2026-09-30"
    assert not [w for w in warnings if "chỉ giữ ngày" in w]


def test_financial_table_cells_keep_values_and_per_cell_sources():
    payload = {"financial_table": {
        "columns": [{"key": "v", "label": "9T2026"}, {"key": "yoy", "label": "% cùng kỳ"}],
        "rows": [{"label": "LNTT", "cells": [
            {"value": 28.9, "source_ids": ["S7"], "evidence_kind": "cited"},
            {"value": None, "source_ids": ["S8"], "evidence_kind": "cited"},
        ]}],
    }}
    normalized, warnings = normalize_report_payload(payload)
    table = normalized["financial_table"]
    assert table["columns"] == ["9T2026", "% cùng kỳ"]
    assert table["rows"][0]["values"] == ["28.9", "—"]
    assert [cell["source_ids"] for cell in table["rows"][0]["cell_evidence"]] == [["S7"], ["S8"]]
    assert "cells" in payload["financial_table"]["rows"][0]
    assert warnings


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
