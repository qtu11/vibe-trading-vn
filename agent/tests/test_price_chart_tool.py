"""Tests for the price-chart tool.

The loader is mocked at the tool boundary, so no network call is made and the
chart contract is pinned independently of provider availability.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest

from src.tools import price_chart_tool
from src.tools.price_chart_tool import PriceChartTool

pytestmark = pytest.mark.unit


def _payload(
    code: str = "FPT.VN",
    *,
    rows: int = 30,
    start_close: float = 70.0,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    bars = [
        {
            "trade_date": f"2026-09-{day:02d}",
            "open": start_close + index,
            "high": start_close + index + 1.5,
            "low": start_close + index - 1.0,
            "close": start_close + index + 0.5,
            "volume": 1_000_000 + index,
        }
        for index, day in enumerate(range(1, rows + 1))
    ]
    return {
        code: bars,
        "_provenance": {
            code: provenance
            if provenance is not None
            else {
                "source": "yahoo",
                "adjustment": "split_dividend",
                "volume_unit": "shares",
                "quote_currency": "VND",
            }
        },
    }


class TestChartContract:
    def test_success_returns_a_ready_to_paste_fence(self) -> None:
        with patch.object(
            price_chart_tool, "fetch_market_data", return_value=_payload()
        ):
            out = json.loads(PriceChartTool().execute(code="FPT.VN"))

        assert out["ok"] is True
        assert out["symbol"] == "FPT.VN"
        assert out["as_of"] == "2026-09-30"
        assert out["source"] == "yahoo"
        assert out["currency"] == "VND"
        assert out["bars"] == 30
        assert out["last_close"] == 99.5

        fence = out["fence"]
        assert fence.startswith("```chart\n")
        assert fence.endswith("\n```")
        spec = json.loads(fence.removeprefix("```chart\n").removesuffix("\n```"))
        assert spec["type"] == "candlestick"
        assert spec["adjustment"] == "split_dividend"
        assert spec["volume_unit"] == "shares"
        assert spec["venue"] == "Vietnam"
        assert spec["range"]["truncated"] is False
        assert spec["bars"][0] == {
            "t": "2026-09-01",
            "o": 70.0,
            "h": 71.5,
            "l": 69.0,
            "c": 70.5,
            "v": 1_000_000,
        }

    def test_only_the_most_recent_bars_are_kept(self) -> None:
        with patch.object(
            price_chart_tool,
            "fetch_market_data",
            return_value=_payload(rows=30),
        ):
            out = json.loads(
                PriceChartTool().execute(code="FPT.VN", max_bars=20)
            )

        assert out["bars"] == 20
        spec = json.loads(
            out["fence"].removeprefix("```chart\n").removesuffix("\n```")
        )
        assert spec["range"]["truncated"] is True
        assert spec["bars"][-1]["t"] == "2026-09-30"

    def test_max_bars_is_clamped_to_the_supported_range(self) -> None:
        with patch.object(
            price_chart_tool, "fetch_market_data", return_value=_payload()
        ):
            small = json.loads(
                PriceChartTool().execute(code="FPT.VN", max_bars=1)
            )
            huge = json.loads(
                PriceChartTool().execute(code="FPT.VN", max_bars=9999)
            )

        assert small["ok"] is True
        assert huge["bars"] <= price_chart_tool._MAX_BARS

    def test_provenance_currency_wins_over_the_suffix_guess(self) -> None:
        payload = _payload(
            provenance={
                "source": "stooq",
                "adjustment": "raw",
                "volume_unit": None,
                "quote_currency": "USD",
            }
        )
        with patch.object(
            price_chart_tool, "fetch_market_data", return_value=payload
        ):
            out = json.loads(PriceChartTool().execute(code="FPT.VN"))

        assert out["currency"] == "USD"

    def test_crypto_pair_currency_comes_from_the_quote_asset(self) -> None:
        payload = _payload(
            code="BTC-USDT",
            provenance={
                "source": "binance",
                "adjustment": "raw",
                "volume_unit": None,
                "quote_currency": None,
            },
        )
        with patch.object(
            price_chart_tool, "fetch_market_data", return_value=payload
        ):
            out = json.loads(PriceChartTool().execute(code="btc-usdt"))

        assert out["symbol"] == "BTC-USDT"
        assert out["currency"] == "USDT"

    def test_fetch_failure_is_an_error_envelope(self) -> None:
        with patch.object(
            price_chart_tool,
            "fetch_market_data",
            side_effect=RuntimeError("loader down"),
        ):
            out = json.loads(PriceChartTool().execute(code="FPT.VN"))

        assert out["ok"] is False
        assert "loader down" in out["error"]

    def test_unresolved_symbol_is_an_error_envelope(self) -> None:
        with patch.object(
            price_chart_tool,
            "fetch_market_data",
            return_value={"_unresolved": ["FPT.VN"], "_provenance": {}},
        ):
            out = json.loads(PriceChartTool().execute(code="FPT.VN"))

        assert out["ok"] is False
        assert "no OHLCV bars" in out["error"]

    def test_invalid_interval_is_rejected_before_fetching(self) -> None:
        with patch.object(price_chart_tool, "fetch_market_data") as fetch:
            out = json.loads(
                PriceChartTool().execute(code="FPT.VN", interval="5m")
            )

        assert out["ok"] is False
        assert "invalid interval" in out["error"]
        fetch.assert_not_called()

    def test_invalid_dates_are_rejected_before_fetching(self) -> None:
        with patch.object(price_chart_tool, "fetch_market_data") as fetch:
            bad_end = json.loads(
                PriceChartTool().execute(code="FPT.VN", end_date="2026/09/30")
            )
            bad_start = json.loads(
                PriceChartTool().execute(
                    code="FPT.VN", start_date="yesterday", end_date="2026-09-30"
                )
            )

        assert bad_end["ok"] is False
        assert bad_start["ok"] is False
        fetch.assert_not_called()

    def test_missing_code_is_rejected(self) -> None:
        out = json.loads(PriceChartTool().execute())

        assert out["ok"] is False
        assert "code" in out["error"]
