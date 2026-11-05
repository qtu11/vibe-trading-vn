"""Broker-native current quotes and completed candles for research chat."""

import json
from contextlib import closing

from src.agent.tools import BaseTool
from src.config.limits import TOOL_RESULT_LIMIT
from src.tools.redaction import redact_tool_result
from src.trading.forex.errors import ForexError
from src.trading.forex.research import snapshot
from src.trading.forex.analysis_context import research_context


class ForexMarketSnapshotTool(BaseTool):
    name = "get_forex_market_snapshot"
    description = (
        "Read REAL broker bid/ask and completed candles from the saved Forex MT5 connection. "
        "For native symbols such as XAUUSDm, first search_symbol, then pass the returned "
        "connection_id and native symbol unchanged. Read-only, no trading. Includes UTC "
        "quote time, freshness, broker/server, currency and demo/live provenance. Never "
        "replace a requested native instrument with GC=F or a Yahoo quote. By default, "
        "fetches 300 completed bars EACH on M5/H1/H4/D1, locally computed trend/RSI/ATR/ranges, "
        "plus dated DXY, TIPS real yield, Fed broad USD, GLD holdings/estimated creations "
        "and CME futures volume when available. Compact summaries use every fetched bar. "
        "Daily macro is separate context, never the execution quote; report missing/stale sources. "
        "Set analysis_context=false only for an explicitly quote-only/single-timeframe request."
        " For a trading strategy, BUY/SELL recommendation, entry or TP/SL request, set "
        "trade_plan=true: six real read-only model roles analyze, debate and risk-review "
        "this evidence, then code validates two BUY/SELL scenarios for chat cards. "
        "This is a bounded council using the configured model, not an order or backtest."
    )
    parameters = {
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "maxLength": 64},
            "connection_id": {"type": "string", "maxLength": 58},
            "timeframe": {"type": "string", "enum": ["1m", "5m", "15m", "30m", "1h", "4h", "1d"], "default": "5m"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 300, "default": 60},
            "analysis_context": {
                "type": "boolean",
                "default": True,
                "description": "Default true for strategy/trend analysis: 300 M5/H1/H4/D1 bars and macro context. timeframe/limit apply only when false.",
            },
            "include_macro": {"type": "boolean", "default": True},
            "trade_plan": {"type": "boolean", "default": False,
                "description": "Required for native Forex strategy/advice/entry/TP/SL requests. Adds actual six-role research council and two structured cards; no orders."},
            "entry_mode": {"type": "string", "enum": ["auto", "market", "limit"], "default": "auto"},
            "forecast_timeframe": {"type": "string", "enum": ["5m", "1h", "4h", "1d"], "default": "5m"},
        },
        "required": ["symbol", "connection_id"],
    }
    repeatable = True
    is_readonly = True
    replay_after_compaction = True

    def execute(self, **kwargs):
        try:
            if kwargs.get("analysis_context", True) or kwargs.get("trade_plan", False):
                from src.trading.forex.service import ForexService

                # Keep one service/binding through evidence collection and council.
                with closing(ForexService()) as service:
                    data = research_context(
                        kwargs.get("symbol", ""),
                        connection_id=kwargs.get("connection_id"),
                        include_macro=kwargs.get("include_macro", True),
                        service=service,
                    )
                    if kwargs.get("trade_plan", False):
                        from src.trading.forex.council import run_council

                        data["_trade_plan"] = run_council(data, service,
                            entry_mode=kwargs.get("entry_mode", "auto"),
                            forecast_timeframe=kwargs.get("forecast_timeframe", "5m"),
                            usage_callback=getattr(self, "usage_callback", None),
                            cancel_event=getattr(self, "cancel_event", None))
                    else:
                        # Preserve the established inline quote/context budget.
                        # Full candle evidence is available in the research API
                        # and is passed internally to the dedicated council.
                        for row in data.get("_timeframes", {}).values():
                            row.pop("price_action", None)
            else:
                data = snapshot(
                    kwargs.get("symbol", ""),
                    connection_id=kwargs.get("connection_id"),
                    timeframe=kwargs.get("timeframe", "5m"),
                    limit=kwargs.get("limit", 60),
                )
            encoded = json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            if (
                len(redact_tool_result(encoded)) > TOOL_RESULT_LIMIT
                and data.get("_meta", {}).get("context_version") == 2
            ):
                # Keep every timeframe, figure, unit and observation date.
                # Redundant explanatory text has already been given in schema
                # and system guidance; full metadata remains on the read API.
                for panel in data.get("_macro_context", {}).values():
                    if isinstance(panel, dict):
                        panel.pop("definition_url", None)
                data["_meta"].pop("interpretation", None)
                data["_meta"]["compact_metadata"] = True
                encoded = json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            return encoded
        except ForexError as exc:
            return json.dumps(exc.payload(), ensure_ascii=False)
        except (TypeError, ValueError):
            return json.dumps(
                {
                    "status": "error",
                    "code": "INVALID_BROKER_DATA",
                    "error": "Broker returned invalid native quote/history",
                }
            )
        except Exception:
            return json.dumps(
                {
                    "status": "error",
                    "code": "MT5_UNAVAILABLE",
                    "error": "Cannot read the saved MT5 session; verify it in Forex",
                }
            )
