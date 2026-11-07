"""Offline financial report regressions: typed values, dimensions and release."""
from __future__ import annotations

import json

import pytest

from src.agent.grounding import GroundingLedger


def ledger(tmp_path, facts=None, *, scale=10**9, symbol="TCB.VN", period="2026-09-30"):
    gate = GroundingLedger(run_dir=tmp_path, user_message=f"Phân tích {symbol}")
    gate.ingest_tool_result(tool_name="get_market_data", arguments={"codes": [symbol]},
        result=json.dumps({symbol: [{"trade_date": "2026-11-06", "close": 21950, "high": 22100,
            "low": 21400}], "_provenance": {symbol: {"source": "yahoo", "quote_currency": "VND"}}}),
        call_id="quote", success=True)
    gate.ingest_tool_result(tool_name="get_financial_statements", arguments={"code": symbol},
        result=json.dumps({"ok": True, "market": "vn", "source": "local_financial_statements",
            "data": {symbol: {"verification_status": "user_supplied_unverified", "periods": [{
                "period_end": period, "document_sha256": "9" * 64, "revision": "123456",
                "facts": facts if facts is not None else {
                    "toi": {"value": "39859", "unit": "VND", "scale": scale},
                    "casa": {"value": "0.45", "unit": "ratio", "scale": 1},
                    "npl": {"value": "1.3", "unit": "percent", "scale": 1},
                    "loss": {"value": "-5.25", "unit": "VND", "scale": 10**6},
                    "zero": {"value": "0", "unit": "VND", "scale": 1},
                }}]}}}), call_id="financials", success=True)
    return gate


def answer(value, field="toi", *, symbol="TCB.VN", period=None):
    body = f"| Chỉ tiêu | {period} |\n|---|---|\n| TOI | {value} |" if period else f"Giá trị: {value}."
    return (f"{symbol} (yahoo, VND).\n{body}\n\n```figures\n"
            f"{value} | observed | reported fact | financials::data.{symbol}.periods[0].facts.{field}.value\n```")


@pytest.mark.parametrize("value,field", [
    ("39,859 tỷ VND", "toi"), ("39859000 triệu đồng", "toi"),
    ("39859000000 nghìn VND", "toi"), ("39859000000000 ₫", "toi"),
    ("45%", "casa"), ("0.45", "casa"), ("1.3%", "npl"),
    ("-5.25 triệu VND", "loss"), ("0 VND", "zero"),
])
def test_typed_statement_values_release_unchanged(tmp_path, value, field):
    gate = ledger(tmp_path)
    draft = answer(value, field)
    result = gate.validate_final_answer(draft)
    assert result.valid, result.issues
    assert value in result.released_text
    assert "omitted" not in result.released_text


@pytest.mark.parametrize("value,field", [
    ("39859 VND", "toi"), ("39859 triệu VND", "toi"), ("39859 tỷ USD", "toi"),
    ("0.45%", "casa"), ("4500%", "casa"), ("45 VND", "casa"),
    ("1.3 VND", "npl"), ("5.25 triệu VND", "loss"), ("39859%", "toi"),
])
def test_wrong_units_scales_signs_do_not_borrow_financial_authority(tmp_path, value, field):
    result = ledger(tmp_path).validate_final_answer(answer(value, field))
    assert not result.valid


def test_scaled_header_and_quarter_keep_valid_table(tmp_path):
    gate = ledger(tmp_path)
    draft = "TCB.VN (yahoo, VND).\n| Chỉ tiêu (tỷ VND) | Q3/2026 |\n|---|---|\n| TOI | 39859 |"
    result = gate.validate_final_answer(draft)
    assert result.valid, result.issues
    assert result.released_text == draft


@pytest.mark.parametrize("period", ["2026-06-30", "Q2/2026"])
def test_financial_header_cannot_borrow_another_period(tmp_path, period):
    gate = ledger(tmp_path)
    assert not gate.validate_final_answer(answer("39,859 tỷ VND", period=period)).valid


def test_header_scale_must_not_match_a_raw_unscaled_fact(tmp_path):
    gate = ledger(tmp_path, scale=1)
    draft = "TCB.VN (yahoo, VND).\n| Chỉ tiêu (tỷ VND) | Q3/2026 |\n|---|---|\n| TOI | 39859 |"
    assert not gate.validate_final_answer(draft).valid


@pytest.mark.parametrize("raw", [None, True, "NaN", "Infinity", "1e999999999", "1e-999999999", "39,859", "text 42"])
def test_invalid_or_underflow_values_do_not_become_evidence(tmp_path, raw):
    gate = ledger(tmp_path, {"bad": {"value": raw, "unit": "VND", "scale": 1}})
    assert not [r for r in gate._evidence if r.call_id == "financials"]


def test_null_reason_and_metadata_are_not_evidence(tmp_path):
    gate = ledger(tmp_path, {"bad": {"value": "45", "unit": "ratio", "scale": 1, "reason": "missing"}})
    assert not [r for r in gate._evidence if r.call_id == "financials"]


def test_wrong_call_and_other_company_cannot_borrow_the_same_number(tmp_path):
    gate = ledger(tmp_path)
    assert not gate.validate_final_answer(answer("39,859 tỷ VND").replace("financials::", "unknown::")).valid
    assert not gate.validate_final_answer(answer("39,859 tỷ VND", symbol="VNM.VN")).valid


def test_web_article_is_cited_evidence_only(tmp_path):
    gate = ledger(tmp_path)
    gate.ingest_tool_result(tool_name="read_url", arguments={"url": "https://example.com/research"},
        result=json.dumps({"status": "ok", "url": "https://example.com/research", "content": "TCB revenue 987.65 billion VND."}),
        call_id="article", success=True)
    assert not gate.validate_final_answer(answer("987.65 tỷ VND")).valid


def test_missing_financial_fact_does_not_refetch_existing_quotes(tmp_path):
    gate = ledger(tmp_path)
    validation = gate.validate_final_answer("TCB.VN (yahoo, VND). Chỉ tiêu thiếu: 98.765%.")
    assert not validation.valid
    assert gate.recovery_action(validation) is None


def test_legacy_sec_units_are_preserved_without_inferring_listing_currency(tmp_path):
    gate = GroundingLedger(run_dir=tmp_path, user_message="Analyze AAPL.US")
    gate.ingest_tool_result(tool_name="get_financial_statements", arguments={"code": "AAPL.US"},
        result=json.dumps({"ok": True, "market": "us", "source": "sec_edgar", "data": {"AAPL.US": {"periods": [{
            "REPORT_DATE": "2026-09-30", "fy": 2026, "Revenue": 123456.7, "_units": {"Revenue": "USD"}}]}}}),
        call_id="sec", success=True)
    records = [r for r in gate._evidence if r.call_id == "sec"]
    assert len(records) == 1
    assert records[0].value == 123456.7 and records[0].unit == records[0].currency == "USD"


def test_unknown_reporting_currency_cannot_become_money(tmp_path):
    gate = GroundingLedger(run_dir=tmp_path, user_message="Analyze VOD.L")
    gate.ingest_tool_result(tool_name="get_financial_statements", arguments={"code": "VOD.L"},
        result=json.dumps({"ok": True, "market": "uk", "source": "yahoo", "data": {"VOD.L": {"periods": [{
            "REPORT_DATE": "2026-03-31", "Revenue": 123456.7}]}}}), call_id="uk", success=True)
    record = next(r for r in gate._evidence if r.call_id == "uk")
    assert record.currency is None and record.unit is None


def test_production_local_statement_tool_decimal_strings_reach_final_release(tmp_path, monkeypatch):
    from backtest.loaders import local_loader
    from src.tools.financial_statements_tool import FinancialStatementsTool

    row = {
        "statement": "income", "period": "quarter", "period_start": "2026-07-01",
        "period_end": "2026-09-30", "period_basis": "standalone", "consolidation": "consolidated",
        "published_at": "2026-10-29T10:00:00+07:00", "retrieved_at": "2026-11-06T10:00:00+07:00",
        "source_url": "https://example.test/synthetic-statement", "document_sha256": "a" * 64,
        "locator": "Synthetic fixture p.1", "revision": "fixture-1",
        "facts": {"toi": {"value": "39859", "unit": "VND", "scale": 10**9}},
    }
    source = tmp_path / "financials.json"
    source.write_text(json.dumps({"schema_version": 1, "symbol": "TCB.VN", "venue": "HOSE", "records": [row]}), encoding="utf-8")
    monkeypatch.setattr(local_loader, "_load_config", lambda: {
        "financial_statements": [{"symbol": "TCB.VN", "path": str(source)}]})
    output = FinancialStatementsTool().execute(code="TCB.VN", statement="income", period="quarter",
                                                as_of="2026-11-07T00:00:00Z")
    assert json.loads(output)["ok"] is True, output
    gate = ledger(tmp_path)
    gate.ingest_tool_result(tool_name="get_financial_statements", arguments={"code": "TCB.VN"},
                           result=output, call_id="actual-tool", success=True)
    result = gate.validate_final_answer(answer("39,859 tỷ đồng").replace("financials::", "actual-tool::"))
    assert result.valid, result.issues
    assert "39,859 tỷ đồng" in result.released_text


def test_redaction_keeps_valid_financial_amount_and_removes_only_unsupported_claim(tmp_path):
    gate = ledger(tmp_path)
    draft = answer("39,859 tỷ VND").replace("\n\n```figures", "\nChỉ tiêu thiếu: 98.765%.\n\n```figures")
    validation = gate.validate_final_answer(draft)
    assert not validation.valid
    released = gate.redacted_release(draft, validation)
    assert released is not None
    assert "39,859 tỷ VND" in released
    assert "98.765%" not in released


@pytest.mark.parametrize("scale", [0, -1, 1.5, "1000", True, 10**13])
def test_invalid_scale_does_not_mint_financial_evidence(tmp_path, scale):
    gate = ledger(tmp_path, {"bad": {"value": "45", "unit": "VND", "scale": scale}})
    assert not [r for r in gate._evidence if r.call_id == "financials"]


def test_vietnam_source_appendix_table_and_headings_pass_grounding(tmp_path):
    gate = GroundingLedger(run_dir=tmp_path, user_message="Phân tích cổ phiếu TCB")
    gate.ingest_tool_result(
        tool_name="get_market_data",
        arguments={"codes": ["TCB.VN"]},
        result=json.dumps({
            "TCB.VN": [{"trade_date": "2026-11-06", "open": 29533, "close": 21650, "high": 21850, "low": 15, "volume": 11339600}],
            "_provenance": {"TCB.VN": {"source": "yahoo", "quote_currency": "VND"}},
        }),
        call_id="quote",
        success=True,
    )
    gate.ingest_tool_result(
        tool_name="read_url",
        arguments={"url": "https://techcombank.com.vn/kqkd-q3-2026"},
        result=json.dumps({
            "status": "ok",
            "url": "https://techcombank.com.vn/kqkd-q3-2026",
            "title": "Thông cáo KQKD Q3/2026 Techcombank",
            "content": (
                "Tổng thu nhập hoạt động (TOI) đạt 45,2 nghìn tỷ đồng; LNTT đạt 28,9 nghìn tỷ đồng. "
                "Mảng IB đạt 2.800 tỷ đồng, giảm 17,5% so với cùng kỳ. Tỷ lệ CAR đạt 15%."
            ),
        }),
        call_id="tcb_pr",
        success=True,
    )
    source_id = gate.sources[0].source_id
    draft = (
        "TCB.VN (yahoo, VND).\n"
        "### 3.1 Hiệu suất giá\n"
        "C 21.650 · KL 11.339.600. Giá mục tiêu cao nhất 29.533, từ 15 chuyên gia.\n\n"
        "### 5.2 Lũy kế 9 tháng 2026\n"
        "| Mã | Nguồn | Nội dung |\n"
        "|---|---|---|\n"
        f"| {source_id} | Techcombank | TOI 45.200; LNTT 28.900; IB 2.800 (−17,5%); CAR 15% |\n\n"
        "```figures\n"
        "21.650 | observed | close | quote\n"
        "11.339.600 | observed | volume | quote\n"
        "29.533 | observed | target high | quote\n"
        "15 | observed | analyst count | quote\n"
        f"45.200 | cited | TOI 45.2 nghin ty [{source_id}] | tcb_pr\n"
        f"28.900 | cited | LNTT 28.9 nghin ty [{source_id}] | tcb_pr\n"
        f"2.800 | cited | IB 9M [{source_id}] | tcb_pr\n"
        f"−17,5% | cited | IB YoY [{source_id}] | tcb_pr\n"
        f"15% | cited | CAR [{source_id}] | tcb_pr\n"
        "```"
    )
    res = gate.validate_final_answer(draft)
    assert res.valid, res.issues
    assert "(omitted※)" not in res.released_text
    assert "45.200" in res.released_text
    assert "−17,5%" in res.released_text
    assert "15%" in res.released_text
