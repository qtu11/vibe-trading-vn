"""Computed indicators keep their real candle source without inventing attribution."""

import json

import pytest

from src.agent.grounding import GroundingLedger

pytestmark = pytest.mark.unit
URL = "https://query1.finance.yahoo.com/v8/finance/chart/MBB.VN?interval=1d"


def _payload(url=URL, symbol="MBB.VN"):
    return {
        "ok": True, "symbol": symbol, "latest_date": "2026-11-06",
        "latest_close": 19250,
        "read_identity": {"bar_count": 200, "provenance": {
            "source": "yahoo", "source_url": url, "quote_currency": "VND",
            "retrieved_at": "2026-11-07T16:35:00+00:00", "adjustment": "split_dividend",
        }},
        "indicators": {"rsi_14": 45.4321, "sma_20": 20345.67},
    }


def _ingest(ledger, payload, call_id="technical-one"):
    ledger.ingest_tool_result(tool_name="technical_indicators", arguments={"symbol": "MBB.VN"},
                              result=json.dumps(payload), call_id=call_id, success=True)


def test_indicator_evidence_keeps_exact_candle_provenance_and_source_index(tmp_path):
    ledger = GroundingLedger(run_dir=tmp_path, user_message="Phân tích MBB.VN")
    _ingest(ledger, _payload())
    records = ledger._evidence
    assert {record.field for record in records} == {"latest_close", "indicators.rsi_14", "indicators.sma_20"}
    assert all(record.source == "yahoo" and record.source_url == URL for record in records)
    assert all(record.symbol == "MBB.VN" and record.timestamp == "2026-11-06" for record in records)
    assert all(record.retrieved_at == "2026-11-07T16:35:00+00:00" for record in records)
    assert all(record.price_basis == "split_dividend" and record.data_role == "computed_from_source_candles" for record in records)
    source = ledger.sources_index("technical-one")[0]
    assert source["url"] == URL and "computed from source candles" in source["title"]
    # The URL publishes candles, not our locally computed indicator values.
    assert 45.4321 not in ledger.sources[0].numbers
    linked = ledger.link_collected_sources("| RSI | 45.4321 | `technical_indicators` |")
    assert f"[technical_indicators — tính từ nến nguồn](<{URL}>)" in linked


def test_returned_symbol_cannot_borrow_another_instruments_source(tmp_path):
    ledger = GroundingLedger(run_dir=tmp_path, user_message="Phân tích MBB.VN")
    _ingest(ledger, _payload(symbol="FPT.VN"))
    assert not ledger._evidence and not ledger.sources_index("technical-one")
    assert ledger.link_collected_sources("technical_indicators") == "technical_indicators"


@pytest.mark.parametrize("url", [None, "", "javascript:alert(1)", "https://user:secret@example.com/data",
                                 "http://127.0.0.1/data", "http://127.1/data", "http://[::1]/data",
                                 "http://localhost/data", "https://example.com/\nunsafe", "https://example.com:bad/data"])
def test_missing_or_unsafe_url_is_never_invented_or_linked(tmp_path, url):
    ledger = GroundingLedger(run_dir=tmp_path, user_message="Phân tích MBB.VN")
    _ingest(ledger, _payload(url=url))
    assert ledger._evidence and all(record.source_url is None for record in ledger._evidence)
    assert not ledger.sources_index("technical-one")
    assert ledger.link_collected_sources("technical_indicators") == "technical_indicators"


def test_repeated_acquisitions_do_not_receive_an_ambiguous_tool_name_link(tmp_path):
    ledger = GroundingLedger(run_dir=tmp_path, user_message="Phân tích MBB.VN")
    _ingest(ledger, _payload())
    _ingest(ledger, _payload(), "technical-two")
    # Same URL is still indexed for each actual call after URL deduplication.
    assert len(ledger.sources) == 1
    assert ledger.sources_index("technical-two")[0]["url"] == URL
    assert ledger.link_collected_sources("technical_indicators") == "technical_indicators"


def test_different_acquisition_urls_are_not_merged_into_one_tool_reference(tmp_path):
    ledger = GroundingLedger(run_dir=tmp_path, user_message="Phân tích MBB.VN")
    _ingest(ledger, _payload())
    _ingest(ledger, _payload(url=URL + "&period=2"), "technical-two")
    assert len(ledger.sources) == 2
    assert ledger.link_collected_sources("technical_indicators") == "technical_indicators"


def test_tool_linking_does_not_touch_code_links_or_unrelated_words(tmp_path):
    ledger = GroundingLedger(run_dir=tmp_path, user_message="Phân tích MBB.VN")
    _ingest(ledger, _payload())
    text = ('```chart\n{"source":"technical_indicators"}\n```\n'
            '[technical_indicators](https://example.com/already)\n'
            '`use technical_indicators data`\nother_technical_indicators\n'
            'https://example.com/technical_indicators')
    assert ledger.link_collected_sources(text) == text
