"""Sanitized multi-timeframe/macro fixtures; never send an order or use a network."""

from datetime import date, datetime, timedelta, timezone
from io import BytesIO
import json

import httpx
from openpyxl import Workbook
import pytest

from src.trading.forex import macro_context as macro
from src.trading.forex.adapters.mt5 import MT5
from src.trading.forex.analysis_context import FRAMES, research_context, summarize_frame
from src.trading.forex.errors import ForexError
from src.trading.forex.models import Connection, utcnow
from src.trading.forex.store import Store


@pytest.fixture
def context_broker(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBE_TRADING_HOME", str(tmp_path))
    config = Connection(
        id="context-fixture",
        label="Fixture",
        connector="mt5",
        account_ref="12345",
        server="Fixture-Demo",
        terminal_path=r"C:\Fixture\terminal64.exe",
        session_mode="existing_terminal",
    )
    Store().save_connection(config)
    calls, limits, failures = [], {}, {}

    def call(self, operation, **kwargs):
        calls.append((operation, kwargs))
        if operation == "instruments":
            return [{"symbol": "XAUUSDm", "currency_base": "XAU", "currency_profit": "USD"}]
        if operation == "quote":
            return {"bid": "2000.25", "ask": "2000.50", "timestamp": utcnow().isoformat()}
        if operation == "candles":
            frame = kwargs["timeframe"]
            if frame in failures:
                raise failures[frame]
            count, step = limits.get(frame, kwargs["limit"]), FRAMES[frame]
            boundary = int(utcnow().timestamp()) // step * step
            return [
                {
                    "time": datetime.fromtimestamp(boundary - (count - i) * step, timezone.utc).isoformat(),
                    "open": str(1700 + i),
                    "high": str(1702 + i),
                    "low": str(1699 + i),
                    "close": str(1701 + i),
                    "volume": 100 + i,
                    "real_volume": 0,
                    "complete": True,
                }
                for i in range(count)
            ]
        pytest.fail(f"Research attempted a non-read operation: {operation}")

    monkeypatch.setattr(MT5, "call", call)
    monkeypatch.setattr(
        "src.trading.forex.analysis_context.get_macro_context",
        lambda **_: {
            "real_yield_10y": {
                "status": "ok",
                "source": "fred",
                "unit": "percent",
                "as_of": "2026-10-30",
                "latest": {"date": "2026-10-30", "value": 2.6},
            },
            "gold_etf": {
                "status": "ok",
                "source": "spdr_gold_shares",
                "symbol": "GLD",
                "unit": "tonnes",
                "as_of": "2026-10-30",
                "latest": {"date": "2026-10-30", "tonnes": 1000.25, "share_volume": 500000},
                "changes_observations": {"1": {"estimated_net_creation_usd": 1234567.89}},
            },
            "gold_futures_volume": {"status": "unavailable", "value": None, "reason": "ConnectTimeout"},
        },
    )
    return config, calls, limits, failures


def test_default_chat_context_fetches_four_full_windows_without_trading_or_truncation(context_broker):
    from src.config.limits import TOOL_RESULT_LIMIT
    from src.tools.forex_market_tool import ForexMarketSnapshotTool

    config, calls, _, _ = context_broker
    raw = ForexMarketSnapshotTool().execute(symbol="XAUUSDm", connection_id=config.id)
    data = json.loads(raw)
    assert len(raw) <= TOOL_RESULT_LIMIT
    assert data["_meta"]["medium_term_price_context_ready"]
    assert set(data["_timeframes"]) == set(FRAMES)
    assert {args["timeframe"] for op, args in calls if op == "candles"} == set(FRAMES)
    assert all(args["limit"] == 300 for op, args in calls if op == "candles")
    assert calls[-1][0] == "quote"  # refreshed after daily downloads
    for panel in data["_timeframes"].values():
        assert panel["candle_count"] == 300 and panel["history_sufficient"]
        assert panel["indicators"]["sma_200"] == 1900.5
        assert panel["trend_alignment"] == "bullish_alignment"
        assert panel["bars_returned"] == 1 and len(panel["bars"]) == 1
        assert panel["volume"]["real_volume_status"] == "unavailable"
        assert panel["volume"]["real_volume_latest"] is None
    assert data["_meta"]["macro_unavailable"] == ["gold_futures_volume"]
    assert data["_meta"]["trading_performed"] is False


def test_short_or_missing_higher_frames_cannot_authorize_medium_term_claims(context_broker):
    config, _, limits, failures = context_broker
    limits["1d"] = 80
    failures["4h"] = ForexError("HISTORY_UNAVAILABLE", "Fixture")
    data = research_context("XAUUSDm", connection_id=config.id, include_macro=False)
    assert data["_meta"]["medium_term_price_context_ready"] is False
    assert data["_timeframes"]["1d"]["indicators"]["sma_200"] is None
    assert data["_timeframes"]["4h"]["status"] == "unavailable"
    assert data["_timeframes"]["1h"]["candle_count"] == 300
    assert data["_macro_context"] == {"status": "not_requested"}


def test_context_fits_actual_post_redaction_delivery_without_losing_frames_or_sources(context_broker, monkeypatch):
    from src.config.limits import TOOL_RESULT_LIMIT
    from src.tools.forex_market_tool import ForexMarketSnapshotTool
    from src.tools.redaction import redact_tool_result

    config, _, _, _ = context_broker
    data = research_context("XAUUSDm", connection_id=config.id)
    # The inline non-council context deliberately omits the larger candle
    # sequences, which are retained in the research API and council evidence.
    for panel in data["_timeframes"].values():
        panel.pop("price_action", None)
    initial = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    data["_meta"]["interpretation"] += "x" * (9900 - len(initial))
    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    assert len(encoded) < TOOL_RESULT_LIMIT < len(redact_tool_result(encoded))
    monkeypatch.setattr("src.tools.forex_market_tool.research_context", lambda *_a, **_k: data)
    result = ForexMarketSnapshotTool().execute(symbol="XAUUSDm", connection_id=config.id)
    delivered = redact_tool_result(result)
    assert len(delivered) <= TOOL_RESULT_LIMIT
    parsed = json.loads(delivered)
    assert set(parsed["_timeframes"]) == set(FRAMES)
    assert parsed["_macro_context"]["real_yield_10y"]["latest"]["value"] == 2.6
    assert parsed["_macro_context"]["gold_futures_volume"]["value"] is None
    assert parsed["_meta"]["compact_metadata"]


def test_identity_error_in_a_later_frame_discards_entire_context(context_broker):
    config, _, _, failures = context_broker
    failures["4h"] = ForexError("ACCOUNT_MISMATCH", "Fixture account changed")
    with pytest.raises(ForexError, match="Fixture account changed"):
        research_context("XAUUSDm", connection_id=config.id)


def test_full_bars_match_compact_summary_hash_and_do_not_fill_missing_periods(context_broker):
    config, _, _, _ = context_broker
    compact = research_context("XAUUSDm", connection_id=config.id, include_macro=False)
    full = research_context("XAUUSDm", connection_id=config.id, include_macro=False, include_bars=True)
    for frame in FRAMES:
        assert compact["_timeframes"][frame]["dataset_sha256"] == full["_timeframes"][frame]["dataset_sha256"]
        assert len(full["_timeframes"][frame]["bars"]) == 300


def test_macro_and_indicator_evidence_keep_identity_timeframe_unit_and_currency(context_broker, tmp_path):
    from src.agent.grounding import GroundingLedger
    from src.tools.symbol_search_tool import SymbolSearchTool
    from src.tools.forex_market_tool import ForexMarketSnapshotTool

    config, _, _, _ = context_broker
    ledger = GroundingLedger(run_dir=tmp_path / "run", user_message="XAUUSDm strategy")
    result = SymbolSearchTool().execute(query="XAUUSDm", connection_id=config.id)
    ledger.ingest_tool_result(
        tool_name="search_symbol", arguments={"query": "XAUUSDm"}, result=result, call_id="resolve", success=True
    )
    args = {"symbol": "XAUUSDm", "connection_id": config.id}
    ledger.ingest_tool_result(
        tool_name="get_forex_market_snapshot",
        arguments=args,
        result=ForexMarketSnapshotTool().execute(**args),
        call_id="context",
        success=True,
    )
    sma = next(r for r in ledger._evidence if r.field == "_timeframes.1d.indicators.sma_200")
    assert sma.symbol == "XAUUSDM" and sma.currency == "USD" and sma.unit == "USD" and sma.timeframe == "1d"
    yield_record = next(r for r in ledger._evidence if r.field == "_macro_context.real_yield_10y.latest.value")
    assert yield_record.source == "fred" and yield_record.timestamp == "2026-10-30"
    assert yield_record.symbol is None and yield_record.currency is None and yield_record.unit == "percent"
    shares = next(r for r in ledger._evidence if r.field == "_macro_context.gold_etf.latest.share_volume")
    assert shares.symbol == "GLD.US" and shares.currency is None and shares.unit == "shares"
    assert not any(r.field.startswith("_macro_context.gold_futures_volume") for r in ledger._evidence)
    assert ledger.validate_final_answer("XAUUSDm, MT5, USD: SMA200 D1 1900.5.").valid
    assert ledger.validate_final_answer("XAUUSDm, MT5, USD: SMA200 D1 1900.5.\nFRED DFII10 2.6% (2026-10-30).").valid
    assert not ledger.validate_final_answer("XAUUSDm, MT5.\nFRED DFII10 260%.").valid
    flow_claim = ledger.validate_final_answer(
        "XAUUSDm, MT5, USD: SMA200 D1 1900.5.\nGLD estimated net creations USD 1234567.89."
    )
    assert flow_claim.valid, flow_claim.issues
    assert not ledger.validate_final_answer("XAUUSDm, MT5, bid USD 1234567.89.").valid


def test_fred_parser_preserves_negative_yield_and_skips_gaps_and_future_dates():
    content = b"observation_date,DFII10\n2026-10-28,-0.2\n2026-10-29,.\n2026-10-30,2.6\n2027-01-01,99\n"
    rows = macro.parse_fred(content, "DFII10", date(2026, 11, 3))
    assert rows == [{"date": "2026-10-28", "value": -0.2}, {"date": "2026-10-30", "value": 2.6}]
    panel = macro._series(rows, today=date(2026, 11, 10), unit="percent", stale_days=7)
    assert panel["status"] == "stale" and panel["as_of"] == "2026-10-30"
    assert panel["changes_observations"]["1"]["change"] == 2.8


def test_dxy_parser_verifies_identity_and_excludes_in_progress_daily_bar():
    stamps = [int(datetime(2026, 11, day, 16, tzinfo=timezone.utc).timestamp()) for day in (1, 2, 3)]
    result = {
        "chart": {
            "result": [
                {
                    "meta": {"symbol": "DX-Y.NYB", "instrumentType": "INDEX"},
                    "timestamp": stamps,
                    "indicators": {"quote": [{"close": [100.5, None, 999]}]},
                }
            ]
        }
    }
    assert macro.parse_dxy(result, date(2026, 11, 3)) == [{"date": "2026-11-01", "value": 100.5}]
    result["chart"]["result"][0]["meta"]["symbol"] = "DTWEXBGS"
    with pytest.raises(ValueError, match="identity"):
        macro.parse_dxy(result, date(2026, 11, 3))


def _issuer_archive():
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "US GLD Historical Archive"
    sheet.append(
        [
            "Date",
            "Tonnes of Gold",
            "Total Ounces of Gold in the Trust",
            "Ounces of Gold per Share",
            "NAV/Share at 10:30am NYT",
            "Daily Share Volume",
        ]
    )
    sheet.append(["28-Oct-2026", "10", "10000", "0.1", "100", "500"])
    sheet.append(["29-Oct-2026", "10", "10000", "0.1", "150", "600"])
    sheet.append(["30-Oct-2026", "11", "11000", "0.1", "200", "700"])
    sheet.append(["31-Oct-2026", "US Holiday", "US Holiday", "US Holiday", "US Holiday", "US Holiday"])
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_etf_proxy_uses_changes_in_shares_not_aum_or_trading_volume(monkeypatch):
    monkeypatch.setattr(macro, "_download", lambda *_a, **_k: _issuer_archive())
    # Same gold/shares with a higher NAV is NOT an inflow.
    no_creation = macro._gld(date(2026, 10, 29))
    assert no_creation["changes_observations"]["1"]["estimated_net_creation_usd"] == 0
    panel = macro._gld(date(2026, 11, 3))
    assert panel["latest"]["tonnes"] == 11 and panel["latest"]["share_volume"] == 700
    change = panel["changes_observations"]["1"]
    assert change["holdings_change_tonnes"] == 1
    assert change["estimated_net_creation_usd"] == 2000000
    assert "ESTIMATE" in panel["flow_method"] and "GLD only" in panel["meaning"]


def test_provider_failures_are_independent_cached_and_never_become_zero(monkeypatch):
    monkeypatch.setattr(macro, "_CACHE", {})
    calls = []

    def broken(day):
        calls.append(day)
        raise httpx.ReadTimeout("Fixture")

    today = date(2026, 11, 3)
    first = macro._cached("gold_futures_volume", broken, today)
    second = macro._cached("gold_futures_volume", broken, today)
    assert first["status"] == "unavailable" and first["value"] is None
    assert second["cached"] and len(calls) == 1
    good = macro._cached("real_yield_10y", lambda _: {"status": "ok", "as_of": "2026-10-30"}, today)
    assert good["status"] == "ok"


def test_invalid_or_duplicate_candles_cannot_ground_trend():
    stamp = (utcnow() - timedelta(days=2)).isoformat()
    bar = {
        "time": stamp,
        "open": 100,
        "high": 102,
        "low": 99,
        "close": 101,
        "volume": 20,
        "real_volume": 0,
        "complete": True,
    }
    with pytest.raises(ValueError, match="Duplicate"):
        summarize_frame([bar, bar], "1d")
    with pytest.raises(ValueError, match="range"):
        summarize_frame([{**bar, "close": 150}], "1d")


def test_macro_pair_uses_one_fred_download_and_keeps_series_independent(monkeypatch):
    calls = []

    def download(url, **kwargs):
        calls.append((url, kwargs))
        return b"observation_date,DFII10,DTWEXBGS\n2026-10-29,2.63,121.5\n2026-10-30,2.6,121.6\n"

    monkeypatch.setattr(macro, "_download", download)
    result = macro._fred_pair(date(2026, 11, 3))
    assert len(calls) == 1
    assert result["series"]["real_yield_10y"]["latest"]["value"] == 2.6
    assert result["series"]["broad_usd"]["latest"]["value"] == 121.6
    assert result["series"]["broad_usd"]["unit"] == "index_2006_100"


def test_cme_parser_keeps_gc_overall_contract_volume_separate_from_other_columns():
    from reportlab.pdfgen import canvas

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(1400, 300))
    pdf.setFont("Courier", 8)
    header = (
        "Contract".ljust(45)
        + "GLOBEX".ljust(16)
        + "OPEN OUTCRY".ljust(17)
        + "PNT".ljust(14)
        + "OVERALL".ljust(18)
        + "OVERALL COMBINED TOTAL"
    )
    row = (
        "GC COMEX GOLD FUTURES".ljust(45)
        + "146826".ljust(16)
        + "".ljust(17)
        + "1562".ljust(14)
        + "148388".ljust(18)
        + "362274 + 4413"
    )
    pdf.drawString(10, 270, "Tue, Nov 03, 2026")
    pdf.drawString(10, 250, header)
    pdf.drawString(10, 230, row)
    pdf.save()
    content = buffer.getvalue()
    assert macro.parse_cme(content, date(2026, 11, 3)) == {"date": "2026-11-03", "value": 148388}
    with pytest.raises(ValueError, match="Future"):
        macro.parse_cme(content, date(2026, 11, 2))


@pytest.mark.asyncio
async def test_new_http_and_mcp_read_surfaces_use_bound_context(context_broker):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from fastmcp import Client
    from src.api.forex_routes import register_forex_routes
    from src.api.security import require_auth
    from src.trading.forex.mcp_server import build_server
    from src.trading.forex.service import ForexService

    config, _, _, _ = context_broker
    service = ForexService()
    app = FastAPI()
    register_forex_routes(app, service)
    app.dependency_overrides[require_auth] = lambda: None
    with TestClient(app) as client:
        result = client.get(
            "/api/forex/research-context",
            params={"symbol": "XAUUSDm", "connection_id": config.id, "include_macro": False},
        )
        assert result.status_code == 200
        assert result.json()["_timeframes"]["1d"]["candle_count"] == 300
    server = build_server(service, config.id)
    async with Client(server) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
        assert tools["forex_research_context"].annotations.readOnlyHint
        assert "forex_submit_intent" not in tools
        result = await client.call_tool("forex_research_context", {"symbol": "XAUUSDm", "include_macro": False})
        assert result.data["_meta"]["connection_id"] == config.id
        assert result.data["_meta"]["trading_performed"] is False
    service.close()
