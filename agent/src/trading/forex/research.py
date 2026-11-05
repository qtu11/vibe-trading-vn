"""Read-only bridge from research chat to the Forex connection store.

Native symbols never fall through to a different Yahoo instrument. This module
has no execution, credential mutation, account login or runner controls.
"""

from datetime import datetime, timezone
import re

from .errors import ForexError
from .models import number, utcnow
from .service import ForexService

_NATIVE_PAIR = re.compile(
    r"^(?![A-Za-z0-9]+(?:USDT|USDC|BUSD|TUSD|FDUSD)$)(?:XAU|XAG|XPT|XPD|EUR|USD|GBP|AUD|NZD|CAD|CHF|JPY|CNH|SGD|BTC|ETH)"
    r"(?:USD|EUR|GBP|JPY|CHF|CAD|AUD|NZD|CNH|SGD)[A-Za-z0-9._+-]{1,12}$",
    re.I,
)
INTERVALS = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "1H": "1h", "4H": "4h", "1D": "1d"}


def search_native(query, *, connection_id=None, limit=10, service=None):
    owned = service is None
    service = service or ForexService()
    try:
        configs = [c for c in service.store.connections() if c.connector == "mt5"]
        if connection_id:
            configs = [c for c in configs if c.id == connection_id]
            if not configs:
                raise ForexError("CONNECTION_NOT_FOUND", "Choose an existing MT5 connection in Forex")
        eligible = bool(
            connection_id
            or (_NATIVE_PAIR.fullmatch(query) and not query.upper().endswith(".FX"))
            or any(query.casefold() in {s.casefold() for s in c.symbols} for c in configs)
        )
        if not configs or not eligible:
            return None
        candidates, issues = [], []
        for config in configs:
            try:
                rows = service.read(config.id, "instruments", query=query, limit=300)["data"]
                for row in rows:
                    native = row.get("symbol", "")
                    if native.casefold() != query.casefold():
                        continue
                    candidates.append(
                        {
                            "symbol": native,
                            "native_symbol": native,
                            "name": row.get("description", native),
                            "market": "forex",
                            "type": "forex"
                            if row.get("currency_base")
                            in {"USD", "EUR", "GBP", "JPY", "AUD", "NZD", "CHF", "CAD", "CNH", "SGD"}
                            else "cfd",
                            "currency": row.get("currency_profit"),
                            "venue": "MT5",
                            "exchange": config.server,
                            "source": "mt5",
                            "connection_id": config.id,
                            "binding_hash": config.fingerprint(),
                            "environment": config.environment,
                        }
                    )
            except ForexError as exc:
                issues.append({"connection_id": config.id, "code": exc.code, "error": str(exc)})
        return {
            "ok": True,
            "market": "multi",
            "source": "symbol_search",
            "data": {
                "query": query,
                "count": len(candidates),
                "candidates": candidates[:limit],
                "sources": {"mt5": "ok" if candidates or not issues else "No verified matching MT5 session"},
                "connection_issues": issues,
                "required_action": "Use get_forex_market_snapshot with the returned connection_id and exact native_symbol; do not replace it with GC=F or XAUUSD=X.",
            },
        }
    finally:
        if owned:
            service.close()


def snapshot(symbol, *, connection_id=None, timeframe="5m", limit=60, service=None):
    if timeframe not in set(INTERVALS.values()):
        raise ForexError("INVALID_TIMEFRAME", "Use 1m, 5m, 15m, 30m, 1h, 4h or 1d")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 300:
        raise ForexError("INVALID_LIMIT", "Use a candle limit between 1 and 300")
    owned = service is None
    service = service or ForexService()
    try:
        resolved = search_native(symbol, connection_id=connection_id, limit=300, service=service)
        rows = resolved["data"]["candidates"] if resolved else []
        if len(rows) != 1:
            raise ForexError(
                "CONNECTION_AMBIGUOUS" if rows else "NATIVE_SYMBOL_UNAVAILABLE",
                "Select one verified MT5 connection and use its exact native symbol; no public-market substitution is allowed",
            )
        candidate = rows[0]
        identifier, native = candidate["connection_id"], candidate["native_symbol"]
        config = service.store.connection(identifier)
        if config.fingerprint() != candidate["binding_hash"]:
            raise ForexError("BINDING_CHANGED", "Forex connection changed after native symbol resolution")
        quote = service.read(identifier, "quote", symbol=native)["data"]
        bars = service.read(identifier, "candles", symbol=native, timeframe=timeframe, limit=limit)["data"]
        service.current_binding(config)
        bid, ask = number(quote["bid"], positive=True), number(quote["ask"], positive=True)
        if ask < bid:
            raise ForexError("INVALID_QUOTE", "Broker ask is below bid")
        stamp = datetime.fromisoformat(quote["timestamp"].replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ForexError("QUOTE_TIME_UNKNOWN", "Broker quote must include its timezone")
        age = (utcnow() - stamp).total_seconds()
        currency = candidate.get("currency")
        data = [
            {
                "date": b["time"],
                **{k: float(number(b[k], positive=True)) for k in ("open", "high", "low", "close")},
                "volume": int(b["volume"]),
                "real_volume": b.get("real_volume"),
            }
            for b in bars
            if b.get("complete") is True
        ]
        provenance = {
            "source": "mt5",
            "native_symbol": native,
            "connection_id": identifier,
            "binding_hash": config.fingerprint(),
            "venue": "MT5",
            "broker_server": config.server,
            "quote_currency": currency,
            "environment": config.environment,
            "adjustment": "raw",
            "volume_unit": "tick_count",
            "timeframe": timeframe,
            "fallback_used": False,
        }
        return {
            native: data,
            "_provenance": {native: provenance},
            "_broker_quotes": {
                native: {
                    "bid": float(bid),
                    "ask": float(ask),
                    "spread": float(ask - bid),
                    "timestamp": stamp.astimezone(timezone.utc).isoformat(),
                    "source": "mt5",
                    "quote_age_seconds": round(age, 3),
                    "is_fresh": -2 <= age <= config.limits.max_quote_age_seconds,
                }
            },
            "_meta": {
                "connection_id": identifier,
                "native_symbol": native,
                "source": "mt5",
                "as_of": utcnow().isoformat(),
                "candle_count": len(data),
                "timeframe": timeframe,
                "quote_semantics": "Bid/ask are broker ticks. OHLC rows are completed candles; last candle close is not the current executable quote.",
                "trading_performed": False,
            },
        }
    finally:
        if owned:
            service.close()


def native_market_data(codes, *, source, interval, start_date, end_date, max_rows, connection_id=None):
    """Intercept only verified native MT5 requests; public symbols keep their loaders."""
    candidates = [code for code in codes if _NATIVE_PAIR.fullmatch(code) and not code.upper().endswith(".FX")]
    if source not in ("auto", "mt5"):
        if candidates:
            raise ForexError(
                "NATIVE_SOURCE_REQUIRED",
                "Native broker symbols require the saved MT5 connection; use get_forex_market_snapshot",
            )
        return None
    if not candidates and not connection_id:
        return None
    if len(candidates) != len(codes) and not connection_id:
        raise ForexError("MIXED_NATIVE_SOURCES", "Fetch native MT5 instruments separately from public-market symbols")
    if interval not in INTERVALS:
        raise ForexError("INVALID_TIMEFRAME", "Native MT5 research supports 1m/5m/15m/30m/1H/4H/1D")
    result = {"_provenance": {}, "_broker_quotes": {}}
    for code in codes:
        panel = snapshot(
            code, connection_id=connection_id, timeframe=INTERVALS[interval], limit=min(max_rows or 300, 300)
        )
        native = panel["_meta"]["native_symbol"]
        result[code] = [r for r in panel[native] if start_date <= r["date"][:10] <= end_date]
        result["_provenance"][code] = panel["_provenance"][native]
        # A current quote is deliberately kept separate from a historical date range.
        result["_broker_quotes"][code] = panel["_broker_quotes"][native]
        if not result[code]:
            result.setdefault("_unresolved", []).append(code)
        result.setdefault("_coverage", {})[code] = {
            "max_rows": 300,
            "rows": len(result[code]),
            "latest_window_only": True,
        }
    return result
