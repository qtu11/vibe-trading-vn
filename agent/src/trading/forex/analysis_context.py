"""Multi-timeframe research evidence from one verified native MT5 binding."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import math

from .errors import ForexError
from .macro_context import get_macro_context
from .models import number, utcnow
from .price_action import candle_evidence
from .research import snapshot
from .service import ForexService

FRAMES = {"5m": 300, "1h": 3600, "4h": 14400, "1d": 86400}
HISTORY_BARS = 300


def _normalize_bars(rows, timeframe):
    seconds = FRAMES[timeframe]
    cleaned = []
    for row in rows:
        if row.get("complete") is not True:
            continue
        stamp = datetime.fromisoformat(row["time"].replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError("Candle time has no timezone")
        if stamp.timestamp() + seconds > utcnow().timestamp() + 2:
            continue
        values = {k: float(number(row[k], positive=True)) for k in ("open", "high", "low", "close")}
        if values["high"] < max(values.values()) or values["low"] > min(values.values()):
            raise ValueError("Invalid candle range")
        ticks = number(row["volume"])
        real = row.get("real_volume")
        real = None if real is None else number(real)
        if ticks < 0 or ticks != int(ticks) or (real is not None and (real < 0 or real != int(real))):
            raise ValueError("Invalid volume")
        cleaned.append(
            {
                "date": stamp.astimezone(timezone.utc).isoformat(),
                **values,
                "volume": int(ticks),
                "real_volume": None if real is None else int(real),
            }
        )
    cleaned.sort(key=lambda b: b["date"])
    if len({b["date"] for b in cleaned}) != len(cleaned):
        raise ValueError("Duplicate candle timestamps")
    return cleaned


def summarize_frame(rows, timeframe, *, include_bars=False):
    import pandas as pd
    from src.tools.technical_indicator_tool import _compute_ema, _compute_rsi, _compute_sma

    bars = _normalize_bars(rows, timeframe)
    if not bars:
        return {
            "status": "unavailable",
            "candle_count": 0,
            "history_sufficient": False,
            "reason": "No completed broker bars",
        }
    close = pd.Series([b["close"] for b in bars], dtype=float)
    high = pd.Series([b["high"] for b in bars], dtype=float)
    low = pd.Series([b["low"] for b in bars], dtype=float)
    tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    indicators = {
        "ema_20": _compute_ema(close, 20),
        "sma_50": _compute_sma(close, 50),
        "sma_200": _compute_sma(close, 200),
        "rsi_14": _compute_rsi(close),
        "atr_14": float(tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean().iloc[-1])
        if len(bars) >= 14
        else None,
        "range_high_20": float(high.iloc[-20:].max()) if len(bars) >= 20 else None,
        "range_low_20": float(low.iloc[-20:].min()) if len(bars) >= 20 else None,
    }
    indicators = {k: round(v, 8) if v is not None and math.isfinite(v) else None for k, v in indicators.items()}
    sma50, sma200 = indicators["sma_50"], indicators["sma_200"]
    trend = "insufficient_history"
    if sma50 is not None and sma200 is not None:
        trend = (
            "bullish_alignment"
            if close.iloc[-1] > sma50 > sma200
            else ("bearish_alignment" if close.iloc[-1] < sma50 < sma200 else "mixed_alignment")
        )
    first = datetime.fromisoformat(bars[0]["date"])
    last = datetime.fromisoformat(bars[-1]["date"])
    age = max(0, (utcnow() - last).total_seconds() - FRAMES[timeframe])
    recent = age <= 3 * FRAMES[timeframe]
    real_positive = any((b["real_volume"] or 0) > 0 for b in bars)
    sufficient = len(bars) >= 200
    return {
        "status": "ok" if sufficient and recent else "partial",
        "requested_count": HISTORY_BARS,
        "candle_count": len(bars),
        "first_bar": bars[0]["date"],
        "last_bar": bars[-1]["date"],
        "span_days": round((last - first).total_seconds() / 86400, 3),
        "last_close_age_seconds": round(age, 1),
        "is_recent": recent,
        "history_sufficient": sufficient,
        "full_requested_window": len(bars) >= HISTORY_BARS,
        "dataset_sha256": hashlib.sha256(json.dumps(bars, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "indicators": indicators,
        "trend_alignment": trend,
        "volume": {
            "unit": "tick_count",
            "latest": bars[-1]["volume"],
            "real_volume_status": "broker_reported_only" if real_positive else "unavailable",
            "real_volume_latest": bars[-1]["real_volume"] if real_positive else None,
            "global_spot_volume": False,
        },
        "bars": bars if include_bars else bars[-1:],
        "bars_returned": len(bars) if include_bars else 1,
        "summary_uses_all_fetched_bars": True,
        "price_action": candle_evidence(bars, atr=indicators["atr_14"]),
    }


def research_context(symbol, *, connection_id, include_macro=True, include_bars=False, service=None):
    """Fetch 300 closed M5/H1/H4/D1 bars, compute locally, then refresh the quote.

    Compact output carries one last bar per frame and source-computed summaries.
    The optional full response returns every bar used, with the same hash.
    Missing macro/history is partial evidence, never a fabricated observation.
    """
    owned = service is None
    service = service or ForexService()
    try:
        # Keep exact identity checks and single-frame consumers in snapshot().
        base = snapshot(symbol, connection_id=connection_id, timeframe="5m", limit=HISTORY_BARS, service=service)
        native = base["_meta"]["native_symbol"]
        config = service.store.connection(connection_id)
        if config.fingerprint() != base["_provenance"][native]["binding_hash"]:
            raise ForexError("BINDING_CHANGED", "Connection changed during research acquisition")
        # Public sources overlap independent, sequential MT5 reads. Never run
        # several native workers against the same terminal concurrently.
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="macro-context") as pool:
            macro_future = (
                pool.submit(get_macro_context, gold=native.upper().startswith("XAU")) if include_macro else None
            )
            frames = {}
            raw_m5 = [{"time": b["date"], **b, "complete": True} for b in base[native]]
            for timeframe in FRAMES:
                try:
                    rows = (
                        raw_m5
                        if timeframe == "5m"
                        else service.read(
                            connection_id, "candles", symbol=native, timeframe=timeframe, limit=HISTORY_BARS
                        )["data"]
                    )
                    service.current_binding(config)
                    frames[timeframe] = summarize_frame(rows, timeframe, include_bars=include_bars)
                except ForexError as exc:
                    if exc.code in {"BINDING_CHANGED", "ACCOUNT_MISMATCH", "ENVIRONMENT_MISMATCH"}:
                        raise
                    frames[timeframe] = {"status": "unavailable", "reason": exc.code, "history_sufficient": False}
                except (KeyError, TypeError, ValueError):
                    frames[timeframe] = {
                        "status": "unavailable",
                        "reason": "INVALID_HISTORY",
                        "history_sufficient": False,
                    }
            macro = macro_future.result() if macro_future else {"status": "not_requested"}
        # Slow daily sources must not make a once-fresh executable quote stale.
        quote = service.read(connection_id, "quote", symbol=native)["data"]
        service.current_binding(config)
        stamp = datetime.fromisoformat(quote["timestamp"].replace("Z", "+00:00"))
        bid, ask = number(quote["bid"], positive=True), number(quote["ask"], positive=True)
        if stamp.tzinfo is None or ask < bid:
            raise ForexError("INVALID_QUOTE", "Invalid timestamp/bid/ask from broker")
        age = (utcnow() - stamp).total_seconds()
        base["_broker_quotes"][native] = {
            "bid": float(bid),
            "ask": float(ask),
            "spread": float(ask - bid),
            "timestamp": stamp.astimezone(timezone.utc).isoformat(),
            "source": "mt5",
            "quote_age_seconds": round(age, 3),
            "is_fresh": -2 <= age <= config.limits.max_quote_age_seconds,
        }
        base[native] = frames["5m"].get("bars", [])
        base["_timeframes"] = frames
        base["_macro_context"] = macro
        missing = [
            f for f, value in frames.items() if not value.get("history_sufficient") or not value.get("is_recent")
        ]
        base["_meta"].update(
            {
                "context_version": 2,
                "as_of": utcnow().isoformat(),
                "candle_count": frames["5m"].get("candle_count", 0),
                "history_bars_requested_per_frame": HISTORY_BARS,
                "medium_term_price_context_ready": not any(f in missing for f in ("1h", "4h", "1d")),
                "incomplete_timeframes": missing,
                "macro_unavailable": [
                    k for k, v in macro.items() if isinstance(v, dict) and v.get("status") == "unavailable"
                ],
                "macro_stale": [k for k, v in macro.items() if isinstance(v, dict) and v.get("status") == "stale"],
                "interpretation": "Use M5 for timing, H1/H4/D1 for trend context. Alignment is computed evidence, not a forecast. Macro series have independent observation dates and units; unavailable/stale inputs limit confidence. MT5 tick_count is not global traded volume.",
            }
        )
        return base
    finally:
        if owned:
            service.close()
