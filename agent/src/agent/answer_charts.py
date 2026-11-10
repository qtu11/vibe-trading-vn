"""Attach observed chart data without asking the model to copy candle JSON."""

from __future__ import annotations

import json
from typing import Any

from src.agent.tool_results import _is_tool_success
from src.tools.price_chart_tool import _rows_of, build_chart_spec, chart_fence


def _lookup(payload: dict, code: str) -> Any:
    """Find a symbol's payload entry regardless of the requested casing.

    ``MarketDataTool`` keys its result by the symbol exactly as requested
    (``mbb.vn`` stays lowercase), while the chart spec always presents the
    canonical uppercase form. A plain ``payload.get(code)`` with an uppercased
    code therefore missed every lowercase request and rendered an "unavailable"
    chart for a symbol that had actually been fetched.
    """
    if code in payload:
        return payload[code]
    wanted = code.casefold()
    for key, value in payload.items():
        if isinstance(key, str) and key.casefold() == wanted:
            return value
    return None


#: A candlestick chart below this many bars cannot show a trend: the candles
#: become enormous blocks and the plot reads as empty space with a few slabs.
#: A later, narrower fetch (a three-bar "latest quote" window, say) must not
#: replace an already-observed rich series for the same symbol.
MIN_USEFUL_BARS = 8


def _bar_count(chart: Any) -> int:
    """Return how many candles a chart spec carries."""
    if not isinstance(chart, dict):
        return 0
    bars = chart.get("bars")
    return len(bars) if isinstance(bars, list) else 0


def prefer_richer_chart(current: Any, candidate: Any) -> Any:
    """Return whichever of two charts for one symbol carries more history.

    A run may fetch the same symbol several times: a wide daily window for the
    trend, then a narrow window for a single recent quote. The last call does
    not win, because a three-bar window replaces a ninety-bar series and the
    chat then shows three enormous candles in an empty plot.

    Rules, in order:

    1. A chart with real bars beats one without.
    2. Between two charts that both have bars, the longer series wins. Equal
       lengths keep the newer chart, so a re-fetch of the same window still
       refreshes the values.
    3. A chart too short to show a trend never displaces one that is long
       enough — it can only fill an empty slot.

    Args:
        current: The chart already held for the symbol, or ``None``.
        candidate: The chart just observed for the same symbol.

    Returns:
        The chart to keep.
    """
    current_bars = _bar_count(current)
    candidate_bars = _bar_count(candidate)
    if candidate_bars == 0:
        return current if current_bars else candidate
    if current_bars == 0:
        return candidate
    if current_bars >= MIN_USEFUL_BARS and candidate_bars < MIN_USEFUL_BARS:
        return current
    return candidate if candidate_bars >= current_bars else current


def collect_observed_charts(tool: Any, arguments: dict, result: str) -> dict[str, dict]:
    """Only first-party market tools may supply automatic answer charts."""
    from src.tools.market_data_tool import MarketDataTool
    from src.tools.price_chart_tool import PriceChartTool

    if not isinstance(tool, (MarketDataTool, PriceChartTool)):
        return {}
    try:
        payload = json.loads(result)
    except (TypeError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    success = _is_tool_success(result)
    if isinstance(tool, PriceChartTool):
        code = arguments.get("code")
        if not isinstance(code, str) or not code.strip():
            return {}
        code = code.strip().upper()
        fence = payload.get("fence")
        if success and payload.get("ok") is True and isinstance(fence, str):
            try:
                chart = json.loads(fence.removeprefix("```chart\n").removesuffix("\n```"))
            except ValueError:
                chart = None
            if isinstance(chart, dict) and chart.get("symbol") == code:
                return {code: chart}
        return {code: {"type": "candlestick", "symbol": code, "status": "unavailable", "bars": []}}

    codes = arguments.get("codes")
    if not isinstance(codes, list):
        return {}
    provenance = payload.get("_provenance")
    provenance = provenance if isinstance(provenance, dict) else {}
    charts = {}
    # shortcut: show at most three instruments per reply, add chart pagination when larger comparisons are needed.
    for code in codes[:3]:
        if not isinstance(code, str) or not code.strip():
            continue
        code = code.strip().upper()
        chart = build_chart_spec(
            code,
            _rows_of(_lookup(payload, code)) if success else [],
            provenance=provenance.get(code) or _lookup(provenance, code),
            interval=str(arguments.get("interval") or "1D"),
            source=str(arguments.get("source") or "auto"),
            requested_start=arguments.get("start_date"),
            requested_end=arguments.get("end_date"),
        )
        charts[code] = chart or {"type": "candlestick", "symbol": code, "status": "unavailable", "bars": []}
    return charts


def append_observed_charts(content: str, charts: dict[str, dict]) -> str:
    """Replace copied charts, or place observed candles after the opening paragraph."""
    from src.agent.grounding.figures import _FENCE_RE, _fenced_blocks

    insertion = None
    blocks = _fenced_blocks(content)
    chart_spans = [(start, end) for start, end, info, _body in blocks if info == "chart"]
    for opener in _FENCE_RE.finditer(content):
        if opener.group(2).strip().casefold() == "chart" and not any(start <= opener.start() < end for start, end, _, _ in blocks):
            chart_spans.append((opener.start(), len(content)))
            break
    for start, end in sorted(chart_spans, reverse=True):
        content = content[:start] + content[end:]
        insertion = start
    if not charts:
        if insertion is None:
            return content
        return content[:insertion].rstrip() + "\n\nChart unavailable: no observed market-data tool result in this run.\n\n" + content[insertion:].lstrip()
    first_break = content.find("\n\n")
    insertion = first_break if first_break >= 0 else len(content)
    fences = "\n\n".join(chart_fence(chart) for chart in list(charts.values())[:3])
    return content[:insertion].rstrip() + "\n\n" + fences + "\n\n" + content[insertion:].lstrip()
