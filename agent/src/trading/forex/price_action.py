"""Explicit price-action heuristics on CLOSED candles; never a calibrated forecast.

Swing pivots require two later closed bars to confirm. No current candle is
used, no missing candle is fabricated and no win probability is inferred.
"""

import math


def candle_evidence(bars, *, atr=None, sample=32):
    rows = [b for b in bars if b.get("complete", True) is True]
    if len(rows) < 25:
        return {"version": 1, "status": "insufficient", "closed_count": len(rows), "patterns": [],
                "structure": "unknown", "recent_candles": [], "volume_unit": "tick_count"}
    # Caller supplies validated chronological OHLC rows. Validate here too for
    # direct consumers, so malformed broker values never become pattern evidence.
    for b in rows:
        o, h, low, c = (float(b[k]) for k in ("open", "high", "low", "close"))
        if not all(math.isfinite(v) and v > 0 for v in (o, h, low, c)) or not low <= min(o, c) <= max(o, c) <= h:
            raise ValueError("Invalid OHLC")
    if atr is None:
        value = None
        for i, b in enumerate(rows):
            tr = float(b["high"]) - float(b["low"])
            if i:
                previous = float(rows[i - 1]["close"])
                tr = max(tr, abs(float(b["high"]) - previous), abs(float(b["low"]) - previous))
            value = tr if value is None else (value * 13 + tr) / 14
        atr = value
    atr = float(atr)
    if not math.isfinite(atr) or atr < 0:
        raise ValueError("Invalid ATR")
    def stamp(b):
        return b.get("date", b.get("time"))
    patterns = []
    for i in range(max(1, len(rows) - 8), len(rows)):
        b, p = rows[i], rows[i - 1]
        o, h, low, c = (float(b[k]) for k in ("open", "high", "low", "close"))
        po, pc = float(p["open"]), float(p["close"])
        span, body = h - low, abs(c - o)
        if span <= 0:
            continue
        upper, lower = h - max(o, c), min(o, c) - low
        found = []
        if body <= span * .1:
            found.append(("doji_shape", "neutral"))
        if .1 * span < body <= .35 * span and lower >= body * 2 and upper <= span * .15:
            found.append(("hammer_shape", "bullish_candidate"))
        if .1 * span < body <= .35 * span and upper >= body * 2 and lower <= span * .15:
            found.append(("shooting_star_shape", "bearish_candidate"))
        if pc < po and c > o and o <= pc and c >= po and body > abs(pc - po):
            found.append(("bullish_engulfing_shape", "bullish_candidate"))
        if pc > po and c < o and o >= pc and c <= po and body > abs(pc - po):
            found.append(("bearish_engulfing_shape", "bearish_candidate"))
        if h < float(p["high"]) and low > float(p["low"]):
            found.append(("inside_bar", "neutral"))
        patterns.extend({"name": name, "bias": bias, "time": stamp(b), "confirmed_bar": True}
                        for name, bias in found)

    # Confirmed fractal swings: the last two bars can never be pivots yet.
    highs, lows = [], []
    for i in range(2, len(rows) - 2):
        window = rows[i - 2:i + 3]
        h, low = float(rows[i]["high"]), float(rows[i]["low"])
        others = window[:2] + window[3:]
        if all(h > float(b["high"]) for b in others):
            highs.append({"time": stamp(rows[i]), "price": h, "confirmed_at": stamp(rows[i + 2])})
        if all(low < float(b["low"]) for b in others):
            lows.append({"time": stamp(rows[i]), "price": low, "confirmed_at": stamp(rows[i + 2])})
    tolerance = atr * .1
    structure = "unknown"
    if len(highs) >= 2 and len(lows) >= 2:
        dh, dl = highs[-1]["price"] - highs[-2]["price"], lows[-1]["price"] - lows[-2]["price"]
        structure = "higher_highs_higher_lows" if dh > tolerance and dl > tolerance else (
            "lower_highs_lower_lows" if dh < -tolerance and dl < -tolerance else "mixed_or_range")
    # Breakout references EXCLUDE the most recent closed candle.
    prior = rows[-21:-1]
    resistance, support = max(float(b["high"]) for b in prior), min(float(b["low"]) for b in prior)
    latest = float(rows[-1]["close"])
    above, below = resistance + tolerance, support - tolerance
    breakout = "close_above_range" if latest > above else "close_below_range" if latest < below else "inside_range"
    compact = [[stamp(b), *[float(b[k]) for k in ("open", "high", "low", "close")], int(b["volume"])]
               for b in rows[-sample:]]
    return {
        "version": 1, "status": "ok", "closed_count": len(rows), "as_of": stamp(rows[-1]),
        "patterns": patterns[-12:], "structure": structure, "swings_high": highs[-2:], "swings_low": lows[-2:],
        "swing_confirmation_right_bars": 2, "support_20": support, "resistance_20": resistance,
        "breakout": breakout, "bullish_close_above": round(above, 8), "bearish_close_below": round(below, 8),
        "atr_14": round(atr, 8), "recent_candle_columns": ["time_utc", "open", "high", "low", "close", "ticks"],
        "recent_candles": compact, "volume_unit": "tick_count", "forming_candle_used": False,
        "method": "price_action_v1: explicit shape rules and confirmed swing pivots; pattern candidates are not proven reversals or probabilities",
    }
