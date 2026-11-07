"""Actual loader paths retain separate raw quotes and adjusted, dated bars."""

import json
from datetime import datetime, timezone

import pytest

from backtest.loaders import base, yahoo_client, yahoo_loader
from src.market_data import fetch_market_data


def _payload(symbol="FPT.VN", currency="VND", price=50800, stamp=1793951109):
    return {"chart": {"error": None, "result": [{
        "meta": {"symbol": symbol, "currency": currency, "fullExchangeName": "HOSE",
                 "regularMarketPrice": price, "regularMarketTime": stamp},
        "timestamp": [1793930400],
        "indicators": {"quote": [{"open": [51400], "high": [51800],
            "low": [50800], "close": [50800], "volume": [12162200]}],
            "adjclose": [{"adjclose": [25400]}]},
    }]}}


@pytest.mark.parametrize("symbol,price", [("FPT.VN", 50800), ("VCB.VN", 53600), ("HPG.VN", 21200)])
def test_raw_quote_is_not_the_adjusted_bar_and_has_a_dated_url(monkeypatch, symbol, price):
    monkeypatch.setattr(base, "loader_cache_enabled", lambda: False)
    monkeypatch.setattr(yahoo_client, "throttled_get_json", lambda *a, **k: _payload(symbol, price=price))
    output = fetch_market_data(codes=[symbol], start_date="2026-11-06", end_date="2026-11-07",
        source="yahoo", loader_resolver=lambda _: yahoo_loader.DataLoader, include_provenance=True)
    provenance = output["_provenance"][symbol]
    quote = provenance["quote_observation"]
    assert output[symbol][0]["close"] == 25400
    assert quote["value"] == price and quote["unit"] == "VND" and quote["scale"] == 1
    assert quote["symbol"] == symbol and quote["exchange"] == "HOSE"
    assert quote["price_basis"] == "raw" and quote["data_role"] == "last_trade"
    assert quote["observed_at"] == "2026-11-06T07:45:09+00:00"
    assert quote["source_url"].startswith(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?")
    assert "period1=" in quote["source_url"] and "period2=" in quote["source_url"]
    assert quote["source_url"] == provenance["source_url"]
    assert datetime.fromisoformat(quote["retrieved_at"]).tzinfo is not None
    assert provenance["last_bar_date"] == "2026-11-06T00:00:00"
    assert provenance["data_kind"] == "historical_bars"
    assert provenance["price_unit"] == "VND"


@pytest.mark.parametrize("price,stamp", [(None, 1793951109), (50800, None),
    (float("nan"), 1793951109), (50800, 10**20), (True, 1793951109)])
def test_missing_or_invalid_snapshot_never_becomes_a_quote(monkeypatch, price, stamp):
    monkeypatch.setattr(yahoo_client, "throttled_get_json", lambda *a, **k: _payload(price=price, stamp=stamp))
    metadata = {}
    yahoo_client.get_chart("FPT.VN", range_="5d", metadata=metadata)
    assert "quote_observation" not in metadata


def test_provider_identity_mismatch_is_rejected(monkeypatch):
    monkeypatch.setattr(yahoo_client, "throttled_get_json", lambda *a, **k: _payload("VCB.VN"))
    with pytest.raises(ValueError, match="identity mismatch"):
        yahoo_client.get_chart("FPT.VN", range_="5d", metadata={})


@pytest.mark.parametrize("currency", ["", "USD", "1000 VND"])
def test_vietnam_loader_requires_explicit_native_vnd(monkeypatch, currency):
    monkeypatch.setattr(yahoo_client, "throttled_get_json", lambda *a, **k: _payload(currency=currency))
    with pytest.raises(ValueError, match="must be quoted in VND"):
        yahoo_loader.DataLoader()._fetch_one("FPT.VN", "2026-11-06", "2026-11-07", "1D")


def test_cached_snapshot_keeps_original_retrieval_time(tmp_path, monkeypatch):
    monkeypatch.setattr(base, "loader_cache_enabled", lambda: True)
    monkeypatch.setattr(base, "loader_cache_root", lambda: tmp_path)
    calls = []
    def fetch(*a, **k):
        calls.append(1)
        return _payload(stamp=int(datetime(2024, 1, 2, tzinfo=timezone.utc).timestamp()))
    monkeypatch.setattr(yahoo_client, "throttled_get_json", fetch)
    loader = yahoo_loader.DataLoader()
    first = loader.fetch(["FPT.VN"], "2026-11-06", "2026-11-06")["FPT.VN"]
    second = loader.fetch(["FPT.VN"], "2026-11-06", "2026-11-06")["FPT.VN"]
    assert calls == [1]
    assert first.attrs["quote_observation"] == second.attrs["quote_observation"]
    assert first.attrs["retrieved_at"] == second.attrs["retrieved_at"]
    assert json.loads(second.attrs["quote_observation"])["observed_at"].startswith("2024-01-02")
