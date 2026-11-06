"""Public-history fixtures; these tests never contact an exchange."""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

import pytest

from src.config.limits import TOOL_RESULT_LIMIT
from src.tools import crypto_derivatives_tool as mod

_T0 = 1_700_000_000_000
_SYMBOL = "BTC/USDT:USDT"
_MARKET = {"symbol": _SYMBOL, "base": "BTC", "quote": "USDT", "settle": "USDT",
           "swap": True, "linear": True, "inverse": False, "expiry": None, "contractSize": 1}


def _oi(quantity: Any = 10, value: Any = 1000, timestamp: int = _T0) -> dict:
    return {"symbol": _SYMBOL, "timestamp": timestamp,
            "openInterestAmount": quantity, "openInterestValue": value}


def _funding(rate: Any = "0.001", mark: Any = "100", timestamp: int = _T0) -> dict:
    return {"symbol": _SYMBOL, "timestamp": timestamp, "fundingRate": rate,
            "info": {"symbol": "BTCUSDT", "fundingTime": timestamp, "markPrice": mark}}


def _install(monkeypatch, rows, market=None):
    calls = []

    def fetch(*args):
        calls.append(args)
        return copy.deepcopy(_MARKET if market is None else market), copy.deepcopy(rows)

    monkeypatch.setattr(mod, "_fetch_history", fetch)
    return calls


def _run(**kwargs):
    return json.loads(mod.CryptoDerivativesTool().execute(symbol="BTC-USDT-PERP", **kwargs))


def test_oi_units_and_symmetric_value_decomposition(monkeypatch):
    # Q: 10 -> 12, P: 100 -> 150. dV=800; quantity=250, price=550.
    calls = _install(monkeypatch, [_oi(12, 1800, _T0 + 3_600_000), _oi()])
    result = _run()
    assert result["ok"] is True
    assert calls == [(_SYMBOL, "open_interest", "1h", 30)]
    assert result["units"]["amount_base"] == "BTC"
    assert result["observations"][0]["amount_base"] == 10
    assert result["summary"]["change_value_quote"] == 800
    decomposition = result["summary"]["value_change_decomposition"]
    assert decomposition["quantity_component_quote"] == 250
    assert decomposition["implied_price_component_quote"] == 550
    assert decomposition["rounding_residual_quote"] == 0
    assert "not causal" in decomposition["interpretation"]
    assert result["coverage"]["observed_intervals_seconds"] == [3600]
    assert result["provenance"]["historical_available_at"] is None
    assert result["provenance"]["retrieved_at"].endswith("Z")


def test_amount_is_already_base_not_multiplied_by_contract_size(monkeypatch):
    market = dict(_MARKET, contractSize=0.001)
    _install(monkeypatch, [_oi(1, 50_000)], market)
    result = _run()
    assert result["observations"][0]["amount_base"] == 1
    assert result["observations"][0]["value_quote"] == 50_000
    assert result["contract"]["oi_amount_already_base"] is True


@pytest.mark.parametrize("q1,p1", [(10, 150), (12, 100), (8, 80), (8, 150)])
def test_value_decomposition_identity_without_directional_claim(monkeypatch, q1, p1):
    _install(monkeypatch, [_oi(), _oi(q1, q1 * p1, _T0 + 1)])
    summary = _run()["summary"]
    parts = summary["value_change_decomposition"]
    assert parts["quantity_component_quote"] + parts["implied_price_component_quote"] == pytest.approx(summary["change_value_quote"])


def test_zero_oi_stays_zero_but_price_and_decomposition_unknown(monkeypatch):
    _install(monkeypatch, [_oi(0, 0), _oi(1, 100, _T0 + 1)])
    result = _run()
    assert result["ok"] is True
    assert result["observations"][0]["implied_price_quote_per_base"] is None
    assert result["summary"]["value_change_decomposition"] is None


def test_funding_actual_cadence_and_historical_mark_cash(monkeypatch):
    # No assumed 8h schedule: rates at 0h, 4h, 5h and settlement-specific prices.
    calls = _install(monkeypatch, [_funding("0.001", "100"),
                                  _funding("-0.002", "200", _T0 + 14_400_000),
                                  _funding("0", "300", _T0 + 18_000_000)])
    result = _run(metric="funding", period="4h")
    assert result["ok"] is True
    assert calls == [(_SYMBOL, "funding", "4h", 30)]
    assert result["period"] is None
    assert result["coverage"]["observed_intervals_seconds"] == [3600, 14400]
    assert result["summary"]["rate_sum"] == pytest.approx(-0.001)
    assert result["summary"]["long_cash_per_base_quote"] == pytest.approx(0.3)
    assert result["summary"]["short_cash_per_base_quote"] == pytest.approx(-0.3)
    assert result["observations"][0]["long_cash_per_base_quote"] == pytest.approx(-0.1)


def test_distinct_funding_types_at_same_time_are_not_coalesced(monkeypatch):
    regular, special, unknown = _funding(), _funding("-0.002"), _funding(timestamp=_T0 + 3_600_000)
    regular["info"]["rateType"] = "Regular"
    special["info"]["rateType"] = "Special"
    _install(monkeypatch, [special, regular, unknown, copy.deepcopy(regular)])
    result = _run(metric="funding")
    assert result["ok"] is True
    assert result["coverage"]["unique_records"] == 3
    assert result["coverage"]["returned_records"] == 4
    assert result["coverage"]["observed_intervals_seconds"] == [3600]
    assert [row["rate_type"] for row in result["observations"]] == ["Regular", "Special", None]
    assert result["summary"]["events_by_rate_type"] == {"Regular": 1, "Special": 1, "unknown": 1}
    assert result["summary"]["realized_events"] == 3
    assert result["summary"]["rate_sum"] == pytest.approx(0)
    assert result["summary"]["long_cash_per_base_quote"] == pytest.approx(0)


def test_conflicting_funding_within_same_type_and_time_rejected(monkeypatch):
    first, other = _funding(), _funding("0.002")
    first["info"]["rateType"] = other["info"]["rateType"] = "Regular"
    _install(monkeypatch, [first, other])
    assert _run(metric="funding")["error_code"] == "INVALID_PROVIDER_DATA"


@pytest.mark.parametrize("rate_type", ["", "regular", "Forecast", 0, True, []])
def test_unknown_funding_type_is_rejected_without_assuming_regular(monkeypatch, rate_type):
    row = _funding()
    row["info"]["rateType"] = rate_type
    _install(monkeypatch, [row])
    assert _run(metric="funding")["error_code"] == "INVALID_PROVIDER_DATA"


@pytest.mark.parametrize("missing", [None, ""])
def test_missing_historical_mark_is_unknown_not_current_price(monkeypatch, missing):
    _install(monkeypatch, [_funding(mark=missing), _funding(timestamp=_T0 + 1)])
    result = _run(metric="funding")
    assert result["ok"] is True
    assert result["observations"][0]["long_cash_per_base_quote"] is None
    assert result["summary"]["events_with_historical_mark"] == 1
    assert result["summary"]["long_cash_per_base_quote"] is None
    assert result["summary"]["short_cash_per_base_quote"] is None


@pytest.mark.parametrize("metric", ["open_interest", "funding"])
def test_summary_hash_all_rows_but_display_latest_ten(monkeypatch, metric):
    factory = _oi if metric == "open_interest" else _funding
    rows = [factory(timestamp=_T0 + i * 3_600_000) for i in range(100)]
    _install(monkeypatch, rows)
    text = mod.CryptoDerivativesTool().execute(symbol="BTC-USDT-PERP", metric=metric, limit=100)
    result = json.loads(text)
    assert result["ok"] is True
    assert len(text) < TOOL_RESULT_LIMIT
    assert result["coverage"]["unique_records"] == 100
    assert len(result["observations"]) == 10
    assert result["observations"][0]["timestamp_ms"] == _T0 + 90 * 3_600_000
    assert result["display"]["sampled"] is True
    normalized = mod._observations(rows, _SYMBOL, metric, 100, _T0 + 101 * 3_600_000)
    digest = hashlib.sha256(json.dumps(normalized, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    assert result["provenance"]["normalized_observations_sha256"] == digest
    if metric == "funding":
        assert result["summary"]["realized_events"] == 100
        assert result["summary"]["rate_sum"] == pytest.approx(0.1)


@pytest.mark.parametrize("symbol", ["BTC-USDT", "BTC/USDT:USDT", "BTC-USD-PERP", "BTCUSDT", None, 1, "X-USD-USDT-PERP", "币-USDT-PERP"])
def test_explicit_symbol_required_before_network(monkeypatch, symbol):
    calls = _install(monkeypatch, [_oi()])
    result = json.loads(mod.CryptoDerivativesTool().execute(symbol=symbol))
    assert result["error_code"] == "INVALID_ARGUMENT"
    assert not calls


@pytest.mark.parametrize("kwargs", [{"limit": True}, {"limit": 1}, {"limit": 101}, {"limit": "inf"},
                                    {"limit": 2.5}, {"metric": "liquidations"}, {"period": "1m"}])
def test_bad_arguments_do_not_fetch(monkeypatch, kwargs):
    calls = _install(monkeypatch, [_oi()])
    assert _run(**kwargs)["error_code"] == "INVALID_ARGUMENT"
    assert not calls


@pytest.mark.parametrize("patch", [{"linear": False}, {"inverse": True}, {"settle": "USDC"}, {"swap": False},
                                   {"symbol": "BTC/USDT"}, {"contractSize": None}, {"contractSize": 0},
                                   {"contractSize": True}, {"contractSize": "nan"}, {"expiry": _T0}])
def test_unverified_or_wrong_contract_metadata_rejected(monkeypatch, patch):
    _install(monkeypatch, [_oi()], dict(_MARKET, **patch))
    assert _run()["error_code"] == "INVALID_PROVIDER_DATA"


@pytest.mark.parametrize("patch", [{"openInterestAmount": None}, {"openInterestAmount": True},
                                   {"openInterestAmount": -1}, {"openInterestValue": "NaN"},
                                   {"openInterestAmount": 0, "openInterestValue": 1},
                                   {"openInterestAmount": 1, "openInterestValue": 0},
                                   {"timestamp": None}, {"timestamp": True}, {"timestamp": 1e99},
                                   {"timestamp": 1.5}, {"symbol": "ETH/USDT:USDT"}])
def test_invalid_oi_row_is_explicit_error(monkeypatch, patch):
    _install(monkeypatch, [dict(_oi(), **patch)])
    assert _run()["error_code"] == "INVALID_PROVIDER_DATA"


@pytest.mark.parametrize("patch", [{"fundingRate": None}, {"fundingRate": "inf"}, {"info": {}},
                                   {"info": {"symbol": "ETHUSDT", "fundingTime": _T0}},
                                   {"info": {"symbol": "BTCUSDT", "fundingTime": _T0 + 1}},
                                   {"info": {"symbol": "BTCUSDT", "fundingTime": _T0, "markPrice": -1}}])
def test_invalid_funding_is_not_silently_dropped(monkeypatch, patch):
    _install(monkeypatch, [dict(_funding(), **patch)])
    assert _run(metric="funding")["error_code"] == "INVALID_PROVIDER_DATA"


def test_empty_and_failed_provider_are_distinct(monkeypatch):
    _install(monkeypatch, [])
    assert _run()["error_code"] == "NO_DATA"

    def fail(*args):
        raise RuntimeError("sensitive provider body")

    monkeypatch.setattr(mod, "_fetch_history", fail)
    text = mod.CryptoDerivativesTool().execute(symbol="BTC-USDT-PERP")
    assert json.loads(text)["error_code"] == "PROVIDER_ERROR"
    assert "sensitive" not in text


def test_duplicate_rows_are_deduped_conflicts_rejected(monkeypatch):
    _install(monkeypatch, [_oi(), _oi()])
    result = _run()
    assert result["coverage"]["returned_records"] == 2
    assert result["coverage"]["unique_records"] == 1
    _install(monkeypatch, [_oi(), _oi(value=1001)])
    assert _run()["error_code"] == "INVALID_PROVIDER_DATA"


def test_future_event_rejected_as_not_realized(monkeypatch):
    _install(monkeypatch, [_oi(timestamp=4_102_444_800_000)])
    assert _run()["error_code"] == "INVALID_PROVIDER_DATA"


@pytest.mark.parametrize("metric", ["open_interest", "funding"])
def test_ccxt_boundary_uses_only_public_metadata_and_history(monkeypatch, metric):
    import ccxt

    calls = []

    class PublicOnly:
        def __init__(self, config):
            assert "apiKey" not in config and "secret" not in config
            assert config["timeout"] > 0
            calls.append("new")

        def load_markets(self):
            calls.append("markets")

        def market(self, symbol):
            assert symbol == _SYMBOL
            calls.append("metadata")
            return _MARKET

        def fetch_open_interest_history(self, symbol, period, *, limit):
            assert (symbol, period, limit) == (_SYMBOL, "1h", 30)
            calls.append("oi")
            return [_oi()]

        def fetch_funding_rate_history(self, symbol, *, limit):
            assert (symbol, limit) == (_SYMBOL, 30)
            calls.append("funding")
            return [_funding()]

    monkeypatch.setattr(ccxt, "binanceusdm", PublicOnly)
    monkeypatch.setattr(mod, "_ccxt_proxy_config", lambda: {})
    result = _run(metric=metric)
    assert result["ok"] is True
    assert calls == ["new", "markets", "metadata", "oi" if metric == "open_interest" else "funding"]


def test_bad_metadata_blocks_history_request(monkeypatch):
    import ccxt

    class WrongMarket:
        def __init__(self, config):
            pass

        def load_markets(self):
            pass

        def market(self, symbol):
            return dict(_MARKET, linear=False)

    monkeypatch.setattr(ccxt, "binanceusdm", WrongMarket)
    monkeypatch.setattr(mod, "_ccxt_proxy_config", lambda: {})
    assert _run()["error_code"] == "INVALID_PROVIDER_DATA"


def test_schema_and_readonly_contract():
    tool = mod.CryptoDerivativesTool()
    schema = tool.to_openai_schema()["function"]
    assert schema["name"] == "crypto_derivatives"
    assert schema["parameters"]["required"] == ["symbol"]
    assert schema["parameters"]["properties"]["metric"]["enum"] == ["open_interest", "funding"]
    assert tool.is_readonly is False  # capture mode must not join parallel read batches
    assert tool.repeatable is True


@pytest.mark.asyncio
async def test_real_mcp_session_reaches_tool_and_preserves_funding_event_types(monkeypatch):
    import mcp_server
    from fastmcp import Client
    from src.agent.tools import ToolRegistry

    regular, special = _funding(), _funding("-0.002")
    regular["info"]["rateType"] = "Regular"
    special["info"]["rateType"] = "Special"
    calls = _install(monkeypatch, [regular, special])
    registry = ToolRegistry()
    registry.register(mod.CryptoDerivativesTool())
    monkeypatch.setattr(mcp_server, "_registry", registry)
    async with Client(mcp_server.mcp) as client:
        response = await client.call_tool("crypto_derivatives", {
            "symbol": "BTC-USDT-PERP", "metric": "funding", "period": "4h", "limit": 10,
        })
    result = json.loads(response.content[0].text)
    assert result["ok"] is True
    assert calls == [(_SYMBOL, "funding", "4h", 10)]
    assert result["summary"]["realized_events"] == 2
    assert result["summary"]["events_by_rate_type"] == {"Regular": 1, "Special": 1, "unknown": 0}
    assert result["summary"]["long_cash_per_base_quote"] == pytest.approx(.1)
    assert [row["rate_type"] for row in result["observations"]] == ["Regular", "Special"]
