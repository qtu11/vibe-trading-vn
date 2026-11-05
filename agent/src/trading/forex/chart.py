"""Validated native chart data, including the terminal's current (zero) bar."""

from datetime import datetime, timezone

from .errors import ForexError
from .models import number, utcnow
from .price_action import candle_evidence

SECONDS = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400}


def chart_snapshot(symbol, *, connection_id, timeframe="5m", limit=200, service):
    if timeframe not in SECONDS or isinstance(limit, bool) or not isinstance(limit, int) or not 30 <= limit <= 300:
        raise ForexError("INVALID_CHART_WINDOW", "Choose a supported timeframe and 30..300 candles")
    config = service.store.connection(connection_id)
    if config.connector != "mt5":
        raise ForexError("CHART_MT5_REQUIRED", "Live native chart currently requires an MT5 connection")
    raw = service.read(connection_id, "chart", symbol=symbol, timeframe=timeframe, limit=limit)["data"]
    service.current_binding(config)
    now, rows, previous = utcnow(), [], None
    for b in raw["bars"]:
        stamp = datetime.fromisoformat(b["time"].replace("Z", "+00:00"))
        values = {k: float(number(b[k], positive=True)) for k in ("open", "high", "low", "close")}
        ticks = number(b["volume"])
        if (stamp.tzinfo is None or stamp > now or (previous is not None and stamp <= previous)
                or not values["low"] <= min(values["open"], values["close"]) <= max(values["open"], values["close"]) <= values["high"]
                or ticks < 0 or ticks != int(ticks)):
            raise ForexError("INVALID_CHART_DATA", "Invalid, duplicate or unordered broker candles")
        complete = stamp.timestamp() + SECONDS[timeframe] <= now.timestamp()
        rows.append({"time": stamp.astimezone(timezone.utc).isoformat(), **values, "volume": int(ticks), "complete": complete})
        previous = stamp
    if not rows or len(rows) > limit or sum(not b["complete"] for b in rows) > 1:
        raise ForexError("INVALID_CHART_DATA", "Broker did not return a valid candle window")
    q = raw["quote"]
    bid, ask = number(q["bid"], positive=True), number(q["ask"], positive=True)
    stamp = datetime.fromisoformat(q["timestamp"].replace("Z", "+00:00"))
    if stamp.tzinfo is None or ask < bid:
        raise ForexError("INVALID_QUOTE", "Invalid native broker quote")
    age = (now - stamp).total_seconds()
    return {
        "version": 1, "source": "mt5", "symbol": symbol, "connection_id": connection_id,
        "binding_hash": config.fingerprint(), "broker_server": config.server, "environment": config.environment,
        "timeframe": timeframe, "retrieved_at": now.isoformat(), "refresh_interval_seconds": 3,
        "quote": {"bid": str(q["bid"]), "ask": str(q["ask"]), "timestamp": stamp.isoformat(),
            "is_fresh": -2 <= age <= config.limits.max_quote_age_seconds, "age_seconds": round(age, 3),
            "max_age_seconds": config.limits.max_quote_age_seconds},
        "bars": rows, "forming_bar_time": next((b["time"] for b in rows if not b["complete"]), None),
        "price_action": candle_evidence(rows), "volume_unit": "tick_count", "trading_performed": False,
    }
