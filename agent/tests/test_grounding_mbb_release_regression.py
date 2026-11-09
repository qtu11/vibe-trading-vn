"""Public, captured MB source boundary from the failed 2026-11-07 response."""

from dataclasses import fields
import json
from pathlib import Path

import pytest

from src.agent.grounding import GroundingLedger
from src.agent.grounding.evidence import EvidenceRecord
from src.agent.grounding.figures import parse_figures_block, scan_figures
from src.agent.grounding.sources import SourceRecord

pytestmark = pytest.mark.unit


@pytest.fixture
def captured(tmp_path):
    data = json.loads((Path(__file__).parent / "fixtures/mbb_grounding_capture_20261107.json").read_text(encoding="utf8"))
    ledger = GroundingLedger(run_dir=tmp_path, user_message="Đánh giá thông tin doanh nghiệp")
    keys = {item.name for item in fields(SourceRecord)}
    ledger._sources = [SourceRecord(**{key: value for key, value in source.items() if key in keys}) for source in data["sources"]]
    ledger._source_by_id = {source.source_id: source for source in ledger._sources}
    return ledger, data


def test_captured_mb_inline_citations_preserve_supported_numbers(captured):
    ledger, data = captured
    result = ledger.validate_final_answer(data["body"])
    assert result.valid, result.issues
    assert "26,17%" in result.released_text
    assert "5.520 tỷ VND" in result.released_text
    assert "22,21%" in result.released_text


def test_captured_mixed_market_cap_does_not_break_vietnamese_declarations(captured):
    _, data = captured
    text = data["body"] + "\n\n```figures\n" + data["declarations"] + "\n```"
    block = parse_figures_block(text)
    assert not block.malformed, block.malformed
    assert any(item.value == 1_288_000 for item in block.declarations)
    assert any(item.value == 45.4 for item in block.declarations)
    assert any(item.value == 193_823.44 for item in block.declarations)
    assert any(item.text == "5.520" and item.value == 5520 for item in scan_figures(text, block))


def test_unknown_inline_number_is_rejected_and_its_claim_withdrawn(captured):
    ledger, data = captured
    text = "### Nợ xấu đã vượt kế hoạch\n\nNPL tăng lên 81,234% [S14], chắc chắn làm giảm lợi nhuận.\n\n" + data["body"]
    validation = ledger.validate_final_answer(text)
    assert not validation.valid
    released = ledger.redacted_release(text, validation)
    assert released is not None
    assert "81,234%" not in released
    assert "chắc chắn làm giảm lợi nhuận" not in released
    assert "Nợ xấu đã vượt kế hoạch" not in released
    assert "Chưa đủ dữ liệu xác minh" in released
    assert "26,17%" in released
    assert "※" in released


def test_one_malformed_row_preserves_valid_declarations(captured):
    ledger, _ = captured
    text = "CIR ở 26,17% [S40].\n\n```figures\n26,17% | cited | CIR | S40\nnot a declaration\n```"
    validation = ledger.validate_final_answer(text)
    assert not validation.valid
    released = ledger.redacted_release(text, validation)
    assert released is not None
    assert "26,17%" in released
    assert ledger.figures_removed == 0


def test_inline_citation_must_be_collected_not_an_invented_id(captured):
    ledger, _ = captured
    result = ledger.validate_final_answer("CIR 26,17% [S999].")
    assert not result.valid


def test_source_urls_are_published_without_touching_code_or_existing_links(captured):
    ledger, _ = captured
    text = "CIR 26,17% [S40]. `source [S40]`\n\n```chart\n{\"source\":\"[S40]\"}\n```\n\n[S14](https://example.com/already-linked)"
    linked = ledger.link_collected_sources(text)
    assert "[S40](<https://thongtinthitruong.mbbank.com.vn/" in linked
    assert "`source [S40]`" in linked
    assert '{"source":"[S40]"}' in linked
    assert "[S14](https://example.com/already-linked)" in linked


def test_observed_chart_metadata_survives_a_rejected_number_with_same_digits(captured):
    ledger, _ = captured
    payload = json.dumps({"range": {"returned": 53}, "bars": [{"c": 19250}]})
    ledger._trusted_chart_payloads.add(payload)
    text = "NPL 53% [S40].\n\n```chart\n" + payload + "\n```"
    validation = ledger.validate_final_answer(text)
    assert not validation.valid
    released = ledger.redacted_release(text, validation)
    assert released is not None
    assert payload in released
    assert "NPL 53%" not in released


def test_model_authored_chart_cannot_hide_unobserved_values(captured):
    ledger, _ = captured
    result = ledger.validate_final_answer('```chart\n{"range":{"returned":53},"bars":[{"c":9999999}]}\n```')
    assert any(issue["code"] == "chart_not_observed" for issue in result.issues)


def test_missing_statement_configuration_is_disclosed_before_conclusions(captured):
    ledger, data = captured
    ledger._tool_failures = [{"tool": "get_financial_statements", "message": "Configure exactly one financial_statements source for this symbol in Data Bridge"}]
    assert ledger.surface_data_gaps(data["body"]).startswith("> Thiếu dữ liệu BCTC:")
    assert ledger.surface_data_gaps(ledger.surface_data_gaps(data["body"])).count("Thiếu dữ liệu BCTC:") == 1


def test_other_issuer_statements_cannot_hide_a_missing_mb_statement(captured):
    ledger, _ = captured
    ledger.ingest_tool_result(tool_name="get_financial_statements", arguments={"code": "MBB.VN"},
                              result='{"ok":false,"error":"source unavailable"}', call_id="failed-mb", success=False)
    assert ledger._tool_failures[-1]["symbols"] == ["MBB.VN"]
    ledger._evidence.append(EvidenceRecord(call_id="fpt", tool="get_financial_statements", symbol="FPT.VN",
                            source="statements", timestamp="2026-09-30", field="revenue", value=123, status="observed"))
    assert "Thiếu dữ liệu BCTC:" in ledger.surface_data_gaps("MBB")
    ledger._evidence.append(EvidenceRecord(call_id="mbb", tool="get_financial_statements", symbol="MBB.VN",
                            source="statements", timestamp="2026-09-30", field="revenue", value=456, status="observed"))
    assert ledger.surface_data_gaps("MBB") == "MBB"


def test_unique_tool_field_ref_is_rebound_and_revalidated(captured):
    ledger, _ = captured
    ledger.ingest_tool_result(tool_name="risk_tool", arguments={}, result='{"risk":{"score":45.4}}', call_id="actual-call", success=True)
    text = "Score 45.4.\n\n```figures\n45.4 | observed | risk score | risk_tool::risk.score\n```"
    validation = ledger.validate_final_answer(text)
    assert not validation.valid
    repaired = ledger.repair_unique_field_refs(text, validation)
    assert repaired is not None and "actual-call::risk.score" in repaired
    assert ledger.revalidate(repaired).valid


def test_field_ref_repair_never_selects_among_multiple_calls(captured):
    ledger, _ = captured
    for call_id in ("first", "second"):
        ledger.ingest_tool_result(tool_name="risk_tool", arguments={}, result='{"risk":{"score":45.4}}', call_id=call_id, success=True)
    text = "Score 45.4.\n\n```figures\n45.4 | observed | risk score | risk_tool::risk.score\n```"
    validation = ledger.validate_final_answer(text)
    assert ledger.repair_unique_field_refs(text, validation) is None


def test_field_ref_repair_does_not_authorize_an_invented_number(captured):
    ledger, _ = captured
    ledger.ingest_tool_result(tool_name="risk_tool", arguments={}, result='{"risk":{"score":45.4}}', call_id="actual-call", success=True)
    text = "Score 99.9.\n\n```figures\n99.9 | observed | risk score | risk_tool::risk.score\n```"
    validation = ledger.validate_final_answer(text)
    repaired = ledger.repair_unique_field_refs(text, validation)
    assert repaired is not None
    assert not ledger.revalidate(repaired).valid


def test_unverified_research_table_rows_withdraw_dependent_interpretation(captured):
    ledger, _ = captured
    text = (
        "| Chỉ tiêu | Giá trị | Diễn giải |\n|---|---|---|\n"
        "| CIR | 26,17% [S40] | Hiệu quả vận hành |\n"
        "| NPL | 81,234% [S14] | Chờ giá test lại vùng hỗ trợ, chắc chắn phục hồi |"
    )
    validation = ledger.validate_final_answer(text)
    assert not validation.valid
    released = ledger.redacted_release(text, validation)
    assert released is not None
    assert "26,17%" in released and "Hiệu quả vận hành" in released
    assert "| NPL |" not in released
    assert "Chờ giá test lại" not in released and "chắc chắn phục hồi" not in released
    assert "Các hàng chưa đủ dữ liệu xác minh" in released
    assert "Chưa xác minh–" not in released
