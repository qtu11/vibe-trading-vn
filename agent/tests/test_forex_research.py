"""Chat must consume the same pinned MT5 session as the Forex page."""

from datetime import timedelta
import json

import pytest

from src.trading.forex.adapters.mt5 import MT5
from src.trading.forex.errors import ForexError
from src.trading.forex.models import Connection, utcnow
from src.trading.forex.store import Store
from src.tools.symbol_search_tool import SymbolSearchTool


@pytest.fixture
def broker(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBE_TRADING_HOME", str(tmp_path))
    config = Connection(
        id="demo-research",
        label="Research fixture",
        connector="mt5",
        account_ref="12345",
        server="Fixture-Demo",
        terminal_path=r"C:\Fixture\terminal64.exe",
        session_mode="existing_terminal",
        symbols=("XAUUSDm",),
    )
    store = Store()
    store.save_connection(config)
    calls = []

    def call(self, operation, **kwargs):
        calls.append((self.config.id, operation, kwargs))
        if self.config.account_ref != "12345":
            raise ForexError("ACCOUNT_MISMATCH", "Fixture terminal account changed")
        if operation == "instruments":
            return [
                {
                    "symbol": "XAUUSDm",
                    "description": "Gold vs US Dollar",
                    "currency_base": "XAU",
                    "currency_profit": "USD",
                    "point": 0.001,
                    "source": "mt5",
                }
            ]
        if operation == "quote":
            assert kwargs["symbol"] == "XAUUSDm"  # never uppercase a native symbol sent to the broker
            return {
                "symbol": "XAUUSDm",
                "bid": "3912.501",
                "ask": "3912.741",
                "point": "0.001",
                "timestamp": utcnow().isoformat(),
                "source": "mt5",
                "tradeable": True,
            }
        if operation == "candles":
            stamp = utcnow().replace(second=0, microsecond=0) - timedelta(minutes=5)
            return [
                {
                    "time": stamp.isoformat(),
                    "open": "3913",
                    "high": "3914",
                    "low": "3911",
                    "close": "3912",
                    "volume": 123,
                    "complete": True,
                    "source": "mt5",
                }
            ]
        pytest.fail("Research tools must never request an execution operation")

    monkeypatch.setattr(MT5, "call", call)
    monkeypatch.setattr("src.tools.symbol_search_tool._search_selected_connector", lambda *_: ([], None, None))
    monkeypatch.setattr("src.tools.symbol_search_tool._search_eastmoney", lambda *_a, **_k: ([], "ok"))
    monkeypatch.setattr("src.tools.symbol_search_tool._search_yahoo", lambda *_a, **_k: ([], "ok"))
    return config, store, calls


def test_chat_resolves_saved_forex_when_legacy_selected_profile_is_unrelated(broker):
    result = json.loads(SymbolSearchTool().execute(query="XAUUSDm"))
    rows = result["data"]["candidates"]
    assert len(rows) == 1 and rows[0]["symbol"] == "XAUUSDm"
    assert rows[0]["connection_id"] == "demo-research" and rows[0]["source"] == "mt5"


def test_native_mt5_symbol_is_an_exact_grounding_identity():
    from src.agent.grounding.identity import _scan_symbols

    assert "XAUUSDM" in _scan_symbols("giá xauusdm hiện tại")


def test_snapshot_preserves_native_case_and_distinguishes_ticks_from_candles(broker):
    from src.tools.forex_market_tool import ForexMarketSnapshotTool

    _, _, calls = broker
    data = json.loads(ForexMarketSnapshotTool().execute(symbol="XAUUSDM", connection_id="demo-research", analysis_context=False))
    assert data["_broker_quotes"]["XAUUSDm"]["bid"] == 3912.501
    assert data["XAUUSDm"][-1]["close"] == 3912
    assert data["_provenance"]["XAUUSDm"]["quote_currency"] == "USD"
    assert data["_provenance"]["XAUUSDm"]["volume_unit"] == "tick_count"
    assert all(op in {"instruments", "quote", "candles"} for _, op, _ in calls)


def test_stale_account_is_skipped_but_an_explicit_stale_binding_never_switches(broker):
    from src.trading.forex.research import snapshot

    config, store, _ = broker
    store.save_connection(config.model_copy(update={"id": "old-session", "account_ref": "99999"}))
    resolved = json.loads(SymbolSearchTool().execute(query="XAUUSDm"))
    assert resolved["data"]["count"] == 1
    assert resolved["data"]["connection_issues"][0]["code"] == "ACCOUNT_MISMATCH"
    with pytest.raises(ForexError):
        snapshot("XAUUSDm", connection_id="old-session")


def test_two_native_connections_require_explicit_disambiguation(broker, tmp_path):
    from src.trading.forex.research import snapshot
    from src.agent.grounding import GroundingLedger

    config, store, _ = broker
    store.save_connection(config.model_copy(update={"id": "second-session"}))
    result = SymbolSearchTool().execute(query="XAUUSDm")
    ledger = GroundingLedger(run_dir=tmp_path / "run", user_message="giá XAUUSDm hiện tại")
    ledger.ingest_tool_result(
        tool_name="search_symbol", arguments={"query": "XAUUSDm"}, result=result, call_id="resolve", success=True
    )
    assert ledger.identity_status == "ambiguous"
    with pytest.raises(ForexError) as exc:
        snapshot("XAUUSDm")
    assert exc.value.code == "CONNECTION_AMBIGUOUS"
    assert snapshot("XAUUSDm", connection_id=config.id)["_meta"]["connection_id"] == config.id


def test_grounding_consumes_native_quote_source_currency_timestamp_and_rejects_invention(broker, tmp_path):
    from src.agent.grounding import GroundingLedger
    from src.tools.forex_market_tool import ForexMarketSnapshotTool

    ledger = GroundingLedger(run_dir=tmp_path / "run", user_message="giá XAUUSDm hiện tại")
    result = SymbolSearchTool().execute(query="XAUUSDm")
    ledger.ingest_tool_result(
        tool_name="search_symbol", arguments={"query": "XAUUSDm"}, result=result, call_id="resolve", success=True
    )
    assert ledger.identity_status == "locked"
    args = {"symbol": "XAUUSDm", "connection_id": "demo-research", "analysis_context": False}
    assert ledger.authorize_tool_call(
        "get_forex_market_snapshot", args, batch_authorized_symbols=ledger.authorized_symbols, call_id="tick"
    ).allowed
    data = ForexMarketSnapshotTool().execute(**args)
    ledger.ingest_tool_result(
        tool_name="get_forex_market_snapshot", arguments=args, result=data, call_id="tick", success=True
    )
    observed = [r for r in ledger._price_records() if r.field in {"bid", "ask"}]
    assert len(observed) == 2
    assert all(r.symbol == "XAUUSDM" and r.source == "mt5" and r.currency == "USD" and r.timestamp for r in observed)
    good = ledger.validate_final_answer("XAUUSDm (MT5, USD), bid 3912.501 và ask 3912.741.")
    assert good.valid, good.issues
    bad = ledger.validate_final_answer("XAUUSDm (MT5), bid USD 9999.123.")
    assert not bad.valid
    assert any(issue["code"] == "numeric_claim_conflict" for issue in bad.issues)


def test_generic_market_tool_routes_native_codes_to_mt5_without_web_fallback(broker):
    from src.tools.market_data_tool import MarketDataTool

    today = utcnow().date().isoformat()
    data = json.loads(MarketDataTool().execute(codes=["XAUUSDM"], start_date=today, end_date=today, interval="5m"))
    assert data["XAUUSDM"][0]["close"] == 3912
    assert data["_provenance"]["XAUUSDM"]["source"] == "mt5"
    wrong = json.loads(MarketDataTool().execute(codes=["XAUUSDm"], start_date=today, end_date=today, source="yahoo"))
    assert wrong["code"] == "NATIVE_SOURCE_REQUIRED"


def test_snapshot_reports_stale_ticks_without_claiming_freshness(broker, monkeypatch):
    from src.trading.forex.research import snapshot

    original = MT5.call

    def call(self, op, **kwargs):
        data = original(self, op, **kwargs)
        if op == "quote":
            data["timestamp"] = (utcnow() - timedelta(minutes=10)).isoformat()
        return data

    monkeypatch.setattr(MT5, "call", call)
    result = snapshot("XAUUSDm", connection_id="demo-research")
    assert result["_broker_quotes"]["XAUUSDm"]["is_fresh"] is False


def test_technical_indicators_share_native_broker_history_instead_of_public_loader(broker, monkeypatch):
    from src.tools.technical_indicator_tool import TechnicalIndicatorTool

    monkeypatch.setattr(
        "src.tools.technical_indicator_tool.fetch_market_data",
        lambda **_: pytest.fail("Native indicator data must come from MT5"),
    )
    result = json.loads(
        TechnicalIndicatorTool().execute(symbol="XAUUSDm", interval="5m", lookback=60, connection_id="demo-research")
    )
    assert result["ok"] and result["latest_close"] == 3912
    assert result["read_identity"]["provenance"]["source"] == "mt5"
    assert result["read_identity"]["provenance"]["native_symbol"] == "XAUUSDm"
