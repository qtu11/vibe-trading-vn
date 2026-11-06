"""Build a renderable price chart from observed OHLCV bars.

The chart is deliberately a *presentation* artifact, not a second source of
truth: every bar comes from :func:`src.market_data.fetch_market_data`, the
same loader path ``get_market_data`` uses, and the tool states the provider,
the adjustment caliber and the last bar date in the spec.

The result carries a ready-to-paste ``chart`` fenced block. The answer scanner
treats a language-tagged fence as code, so the JSON inside it is never mistaken
for a prose numeric claim, while the numbers a reader sees still trace back to
the observed fetch. The frontend renders the fence with ECharts and falls back
to a plain code block when the JSON is incomplete.
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta, timezone
from typing import Any

from src.agent.tools import BaseTool
from src.market_data import fetch_market_data

# Chart resolutions a daily-bar loader can serve without resampling surprises.
_INTERVAL_ENUM = ("1D", "1W", "1M")

# A chat chart is a context window, not a data export. 60 bars is roughly a
# quarter of daily sessions and keeps the fenced block well inside the tool
# result budget (TOOL_RESULT_LIMIT is 10,000 characters).
_DEFAULT_BARS = 60
_MAX_BARS = 100
_DEFAULT_LOOKBACK_DAYS = 420

_DATE_KEYS = ("trade_date", "date", "datetime", "timestamp", "time", "index")

_SUFFIX_CURRENCY = {
    "VN": "VND",
    "SH": "CNY",
    "SZ": "CNY",
    "BJ": "CNY",
    "SS": "CNY",
    "HK": "HKD",
    "US": "USD",
    "SA": "BRL",
    "TO": "CAD",
    "V": "CAD",
    "T": "JPY",
    "KS": "KRW",
    "KQ": "KRW",
    "NS": "INR",
    "BO": "INR",
    "TW": "TWD",
    "TWO": "TWD",
    "L": "GBP",
    "DE": "EUR",
    "PA": "EUR",
    "AS": "EUR",
    "MI": "EUR",
    "MC": "EUR",
    "SW": "CHF",
    "AX": "AUD",
}

_SUFFIX_VENUE = {
    "VN": "Vietnam",
    "SH": "Shanghai",
    "SS": "Shanghai",
    "SZ": "Shenzhen",
    "BJ": "Beijing",
    "HK": "Hong Kong",
    "US": "United States",
    "SA": "B3",
    "TO": "Toronto",
    "V": "TSX Venture",
    "T": "Tokyo",
    "KS": "KOSPI",
    "KQ": "KOSDAQ",
    "NS": "NSE",
    "BO": "BSE",
    "TW": "Taiwan",
    "TWO": "TPEx",
    "L": "London",
    "DE": "Xetra",
    "PA": "Euronext Paris",
    "AS": "Euronext Amsterdam",
    "MI": "Borsa Italiana",
    "MC": "BME",
    "SW": "SIX",
    "AX": "ASX",
}

_CRYPTO_QUOTES = ("USDT", "USDC", "USD", "BTC", "ETH", "EUR")


def _error(message: str) -> str:
    return json.dumps({"ok": False, "error": message}, ensure_ascii=False)


def _suffix(code: str) -> str:
    return code.rpartition(".")[2].upper() if "." in code else ""


def _currency_for(code: str, provenance: dict[str, Any]) -> str | None:
    """Read the served quote currency, falling back to the listing suffix."""
    quote = provenance.get("quote_currency")
    if isinstance(quote, str) and quote.strip():
        return quote.strip().upper()
    upper = code.upper()
    for separator in ("-", "/"):
        if separator in upper:
            tail = upper.rsplit(separator, 1)[1]
            if tail in _CRYPTO_QUOTES:
                return tail
    return _SUFFIX_CURRENCY.get(_suffix(code))


def _venue_for(code: str) -> str | None:
    return _SUFFIX_VENUE.get(_suffix(code))


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _round(value: float | None, places: int = 6) -> float | None:
    return None if value is None else round(value, places)


def _bar_time(row: dict[str, Any]) -> str | None:
    """Return a bar's date/time as text, accepting every loader index name."""
    for key in _DATE_KEYS:
        value = row.get(key)
        if value is None or isinstance(value, bool):
            continue
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        text = str(value).strip()
        if text:
            return text
    return None


def _rows_of(payload: Any) -> list[dict[str, Any]]:
    """Normalize ``fetch_market_data``'s list-or-truncated-dict shape."""
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            return [row for row in data if isinstance(row, dict)]
    return []


def _bars(rows: list[dict[str, Any]], keep: int) -> tuple[list[dict[str, Any]], bool]:
    """Build compact bars from the most recent ``keep`` rows."""
    bars: list[dict[str, Any]] = []
    for row in rows:
        close = _as_float(row.get("close"))
        if close is None:
            continue
        stamp = _bar_time(row)
        if not stamp:
            continue
        bar: dict[str, Any] = {
            "t": stamp,
            "o": _round(_as_float(row.get("open"))),
            "h": _round(_as_float(row.get("high"))),
            "l": _round(_as_float(row.get("low"))),
            "c": _round(close),
        }
        volume = _as_float(row.get("volume"))
        if volume is not None:
            bar["v"] = int(round(volume))
        bars.append(bar)
    truncated = len(bars) > keep
    return bars[-keep:], truncated


def _valid_iso_date(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) != 10:
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return None


def build_chart_spec(
    code: str,
    rows: list[dict[str, Any]],
    *,
    provenance: dict[str, Any] | None = None,
    interval: str = "1D",
    max_bars: int = _DEFAULT_BARS,
    source: str = "auto",
    requested_start: str | None = None,
    requested_end: str | None = None,
) -> dict[str, Any] | None:
    """Build a compact candlestick spec from observed rows.

    This is the shared presentation builder for ``build_price_chart`` and
    ``run_research_council``. It does not fetch anything: the caller owns the
    loader call, so a council chart and a standalone chart for the same window
    cannot disagree about the bars.

    Args:
        code: Canonical symbol the rows belong to.
        rows: Loader rows carrying any of the recognized date keys plus OHLCV.
        provenance: The symbol's ``_provenance`` entry, if the loader supplied one.
        interval: Bar interval label.
        max_bars: Most recent bars to keep.
        source: Requested source, used only when provenance has no served source.
        requested_start: Requested window start date, for the range record.
        requested_end: Requested window end date, for the range record.

    Returns:
        A JSON-ready chart spec, or ``None`` when the rows hold no dated close.
    """
    bars, truncated = _bars(rows, max_bars)
    if not bars:
        return None
    symbol_provenance = provenance if isinstance(provenance, dict) else {}
    last = bars[-1]
    return {
        "type": "candlestick",
        "symbol": code,
        "venue": _venue_for(code),
        "currency": _currency_for(code, symbol_provenance),
        "interval": interval,
        "source": symbol_provenance.get("source") or source,
        "adjustment": symbol_provenance.get("adjustment"),
        "volume_unit": symbol_provenance.get("volume_unit"),
        "as_of": last["t"],
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "bars": bars,
        "range": {
            "requested_start": requested_start,
            "requested_end": requested_end,
            "first_bar": bars[0]["t"],
            "last_bar": last["t"],
            "returned": len(bars),
            "truncated": truncated,
        },
    }


def chart_fence(chart: dict[str, Any]) -> str:
    """Wrap a chart spec in the exact fenced block the frontend renders."""
    return "```chart\n" + json.dumps(
        chart, ensure_ascii=False, separators=(",", ":")
    ) + "\n```"


class PriceChartTool(BaseTool):
    """Build a candlestick chart spec from observed market data."""

    name = "build_price_chart"
    description = (
        "Build a renderable candlestick chart for one listed security from the "
        "same observed OHLCV loaders get_market_data uses. Returns a ready-to-"
        "paste 'chart' fenced block under 'fence' plus the last close and the "
        "data-effective date. Put the fence verbatim in the answer where the "
        "chart should appear; the JSON inside is code, so its numbers are not "
        "prose claims. The spec also records the provider, the adjustment "
        "caliber and the volume unit, because price levels from different "
        "calibers are not comparable. Use get_market_data instead when you "
        "need the rows themselves."
    )
    parameters = {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": (
                    "Symbol such as 'FPT.VN', 'AAPL.US', '600519.SH', "
                    "'00700.HK' or 'BTC-USDT'."
                ),
            },
            "start_date": {
                "type": "string",
                "description": (
                    "First bar date in YYYY-MM-DD. Defaults to about 14 months "
                    "before end_date so the chart has a year of context."
                ),
            },
            "end_date": {
                "type": "string",
                "description": "Last bar date in YYYY-MM-DD. Defaults to today.",
            },
            "interval": {
                "type": "string",
                "enum": list(_INTERVAL_ENUM),
                "description": "Bar size. Default '1D'.",
                "default": "1D",
            },
            "source": {
                "type": "string",
                "description": (
                    "Loader name, or 'auto' (default) to detect it from the "
                    "symbol the way get_market_data does."
                ),
                "default": "auto",
            },
            "max_bars": {
                "type": "integer",
                "description": (
                    f"Most recent bars to draw (20-{_MAX_BARS}). Default "
                    f"{_DEFAULT_BARS}; older bars are dropped."
                ),
                "default": _DEFAULT_BARS,
            },
        },
        "required": ["code"],
    }

    def execute(self, **kwargs: Any) -> str:
        """Fetch bars and render a compact chart specification.

        Args:
            **kwargs: ``code`` (required), optional ``start_date``,
                ``end_date``, ``interval``, ``source`` and ``max_bars``.

        Returns:
            A JSON envelope. On success it carries ``fence`` (the exact
            ```` ```chart ```` block to paste), ``symbol``, ``as_of``,
            ``source``, ``currency``, ``bars`` and ``last_close``. On failure:
            ``{"ok": false, "error": "..."}``.
        """
        raw_code = kwargs.get("code")
        if not isinstance(raw_code, str) or not raw_code.strip():
            return _error("missing required parameter: code")
        code = raw_code.strip().upper()

        interval = str(kwargs.get("interval") or "1D").strip()
        if interval not in _INTERVAL_ENUM:
            return _error(
                f"invalid interval: {interval!r}; expected one of "
                f"{', '.join(_INTERVAL_ENUM)}"
            )

        raw_source = kwargs.get("source")
        source = str(raw_source).strip() if raw_source else "auto"

        try:
            max_bars = int(kwargs.get("max_bars", _DEFAULT_BARS))
        except (TypeError, ValueError, OverflowError):
            max_bars = _DEFAULT_BARS
        max_bars = min(max(max_bars, 20), _MAX_BARS)

        end_text = kwargs.get("end_date")
        end = _valid_iso_date(end_text) if end_text else date.today().isoformat()
        if end is None:
            return _error(f"invalid end_date: {end_text!r}; expected YYYY-MM-DD")
        start_text = kwargs.get("start_date")
        if start_text:
            start = _valid_iso_date(start_text)
            if start is None:
                return _error(
                    f"invalid start_date: {start_text!r}; expected YYYY-MM-DD"
                )
        else:
            start = (
                date.fromisoformat(end) - timedelta(days=_DEFAULT_LOOKBACK_DAYS)
            ).isoformat()
        if start > end:
            return _error("start_date must not be after end_date")

        try:
            payload = fetch_market_data(
                codes=[code],
                start_date=start,
                end_date=end,
                source=source,
                interval=interval,
                max_rows=0,
                include_provenance=True,
            )
        except Exception as exc:  # noqa: BLE001 - surface any loader failure
            return _error(f"market data fetch failed for {code}: {exc}")

        if not isinstance(payload, dict):
            return _error(f"market data fetch returned no payload for {code}")
        rows = _rows_of(payload.get(code))
        if not rows:
            unresolved = payload.get("_unresolved")
            detail = f" ({', '.join(map(str, unresolved))})" if unresolved else ""
            return _error(f"no OHLCV bars for {code}{detail}")

        provenance = payload.get("_provenance")
        provenance = provenance if isinstance(provenance, dict) else {}
        chart = build_chart_spec(
            code,
            rows,
            provenance=provenance.get(code),
            interval=interval,
            max_bars=max_bars,
            source=source,
            requested_start=start,
            requested_end=end,
        )
        if chart is None:
            return _error(f"no dated OHLCV bars for {code}")

        last = chart["bars"][-1]
        fence = chart_fence(chart)
        return json.dumps(
            {
                "ok": True,
                "symbol": code,
                "as_of": last["t"],
                "source": chart["source"],
                "currency": chart["currency"],
                "bars": len(chart["bars"]),
                "last_close": last["c"],
                "fence": fence,
            },
            ensure_ascii=False,
        )
