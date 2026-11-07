"""Regression probes for citation authority and dated financial tables."""
from __future__ import annotations

import json
import math
from dataclasses import replace

import pytest

from src.agent.grounding import GroundingLedger
from src.agent.grounding.sources import value_in_source


def _source(gate, text, call="article"):
    gate.ingest_tool_result(
        tool_name="read_url", arguments={"url": f"https://example.test/{call}"},
        result=json.dumps({"status": "ok", "url": f"https://example.test/{call}", "content": text}),
        call_id=call, success=True,
    )
    return gate.sources[-1]


def _statements(gate, facts, *, period="2026-09-30"):
    gate.ingest_tool_result(
        tool_name="get_financial_statements", arguments={"code": "TCB.VN"},
        result=json.dumps({"ok": True, "market": "vn", "source": "local_financial_statements",
            "data": {"TCB.VN": {"periods": [{"period_end": period, "facts": facts}]}}}),
        call_id="financials", success=True,
    )


@pytest.mark.parametrize("claim", ["28.9 tỷ", "28.9 nghìn tỷ"])
def test_citation_magnitude_cannot_match_a_raw_mantissa(tmp_path, claim):
    gate = GroundingLedger(run_dir=tmp_path, user_message="Research TCB.VN")
    _source(gate, "TCB.VN revenue was 28.9 million VND.")
    draft = f"TCB.VN revenue: {claim} VND [S1].\n\n```figures\n{claim} VND | cited | [S1] | S1\n```"
    assert not gate.validate_final_answer(draft).valid


@pytest.mark.parametrize("candidate,claim", [("0.001", -0.001), ("0", 0.004), ("0.001", 0.004)])
def test_source_tolerance_does_not_erase_small_values_or_signs(tmp_path, candidate, claim):
    gate = GroundingLedger(run_dir=tmp_path, user_message="Research")
    source = _source(gate, f"The reported value is {candidate}.")
    assert not value_in_source(source, claim)


def test_scaled_source_overflow_cannot_support_every_finite_claim(tmp_path):
    gate = GroundingLedger(run_dir=tmp_path, user_message="Research")
    source = _source(gate, "Reported revenue: " + "1" + "0" * 307 + " tỷ VND.")
    assert all(math.isfinite(value) for value in source.numbers)
    assert not value_in_source(source, 7.4)
    assert not value_in_source(replace(source, numbers=(float("inf"),)), 7.4)
    assert not value_in_source(source, 1e308, scale=1e12)


def test_only_the_visible_source_can_support_a_cited_number(tmp_path):
    gate = GroundingLedger(run_dir=tmp_path, user_message="Research TCB.VN")
    _source(gate, "TCB.VN reported 28.9 tỷ VND.", "correct")
    _source(gate, "TCB.VN reported 7.4 tỷ VND.", "unrelated")
    draft = ("TCB.VN revenue was 28.9 tỷ VND [S2].\n\n```figures\n"
             "28.9 tỷ VND | cited | [S1] [S2] | S1 S2\n```")
    validation = gate.validate_final_answer(draft)
    assert not validation.valid
    assert any(issue.get("reason") == "citation_not_visible" for issue in validation.issues)
    repaired = gate.repair_citation_visibility(draft, validation)
    assert repaired and "[S1]" in repaired.split("```figures")[0]
    assert gate.revalidate(repaired).valid


@pytest.mark.parametrize("period", ["2025", "Q3/2025", "2025-09-30"])
def test_financial_table_year_cannot_borrow_a_later_period(tmp_path, period):
    gate = GroundingLedger(run_dir=tmp_path, user_message="Phân tích TCB.VN")
    _statements(gate, {"revenue": {"value": "39859", "unit": "VND", "scale": 10**9}})
    draft = f"TCB.VN\n| Chỉ tiêu (tỷ VND) | {period} |\n|---|---|\n| Doanh thu | 39859 |"
    assert not gate.validate_final_answer(draft).valid


def test_financial_table_year_releases_the_matching_period(tmp_path):
    gate = GroundingLedger(run_dir=tmp_path, user_message="Phân tích TCB.VN")
    _statements(gate, {"revenue": {"value": "39859", "unit": "VND", "scale": 10**9}})
    draft = "TCB.VN\n| Chỉ tiêu (tỷ VND) | 2026 |\n|---|---|\n| Doanh thu | 39859 |"
    assert gate.validate_final_answer(draft).valid


def test_fundamentals_only_report_keeps_valid_amount_beneath_its_title(tmp_path):
    gate = GroundingLedger(run_dir=tmp_path, user_message="Phân tích TCB.VN")
    _statements(gate, {"revenue": {"value": "39859", "unit": "VND", "scale": 10**9}})
    result = gate.validate_final_answer("TCB.VN\n\nDoanh thu: 39,859 tỷ VND.")
    assert result.valid, result.issues
    assert "39,859 tỷ VND" in result.released_text


@pytest.mark.parametrize("written", ["3.54 tỷ cổ phiếu", "3540 triệu cổ phiếu", "3540000 nghìn cổ phiếu"])
def test_statement_share_count_releases_at_its_written_scale_with_exact_ref(tmp_path, written):
    gate = GroundingLedger(run_dir=tmp_path, user_message="Phân tích TCB.VN")
    _statements(gate, {"shares": {"value": "3540000000", "unit": "shares", "scale": 1}})
    draft = (f"TCB.VN: {written}.\n\n```figures\n"
             f"{written} | observed | issued shares | financials::data.TCB.VN.periods[0].facts.shares.value\n```")
    result = gate.validate_final_answer(draft)
    assert result.valid, result.issues
    assert written in result.released_text


@pytest.mark.parametrize("written", ["3.54 triệu cổ phiếu", "3.54 tỷ VND", "-3.54 tỷ cổ phiếu"])
def test_statement_shares_keep_scale_currency_and_sign_boundaries(tmp_path, written):
    gate = GroundingLedger(run_dir=tmp_path, user_message="Phân tích TCB.VN")
    _statements(gate, {"shares": {"value": "3540000000", "unit": "shares", "scale": 1}})
    draft = (f"TCB.VN: {written}.\n\n```figures\n"
             f"{written} | observed | issued shares | financials::data.TCB.VN.periods[0].facts.shares.value\n```")
    assert not gate.validate_final_answer(draft).valid


@pytest.mark.parametrize("value", ["39.859", "-3985.9", "0.39859"])
def test_typed_ratios_never_reenter_the_legacy_percent_pool(tmp_path, value):
    gate = GroundingLedger(run_dir=tmp_path, user_message="Phân tích TCB.VN")
    _statements(gate, {"roe": {"value": "39.859", "unit": "ratio", "scale": 1}})
    # Legacy SEC rows expose named metric leaves as well as typed evidence.
    gate.ingest_tool_result(
        tool_name="get_financial_statements", arguments={"code": "TCB.VN"},
        result=json.dumps({"ok": True, "market": "us", "source": "sec_edgar",
            "data": {"TCB.VN": {"periods": [{"REPORT_DATE": "2026-09-30", "roe": 39.859, "_units": {"roe": "pure"}}]}}}),
        call_id="legacy", success=True,
    )
    result = gate.validate_final_answer(f"TCB.VN: ROE {value}%.")
    assert not result.valid

