"""Offline Binance USD-M diff-depth replay; no socket, recorder or checksum claim.

Protocol: https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/websocket-market-streams/How-to-manage-a-local-order-book-correctly
Checked 2026-11-05: bridge U <= snapshot lastUpdateId <= u, then pu == prior u.
"""
from __future__ import annotations

import math
from collections import Counter
from decimal import Decimal, InvalidOperation
from typing import Any

PROTOCOL = "binance_usdm_depth_v1"
MAX_EVENTS = 200
MAX_EVENT_LEVELS = 1000
MAX_BOOK_LEVELS = 5000


def _update_id(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < 2**63:
        raise ValueError("update IDs must be nonnegative signed-64-bit integers")
    return value


def _levels(value: Any, *, snapshot: bool) -> dict[Decimal, Decimal]:
    if not isinstance(value, list) or len(value) > MAX_EVENT_LEVELS:
        raise ValueError(f"each side must be an array of at most {MAX_EVENT_LEVELS} levels")
    result: dict[Decimal, Decimal] = {}
    for row in value:
        if not isinstance(row, (list, tuple)) or len(row) != 2:
            raise ValueError("each level must contain exactly price and absolute quantity")
        numbers = []
        for item in row:
            if isinstance(item, bool) or not isinstance(item, (str, int, float)):
                raise ValueError("price and quantity must be finite decimal numbers")
            text = str(item)
            if len(text) > 64:
                raise ValueError("decimal fields cannot exceed 64 characters")
            try:
                number = Decimal(text)
            except InvalidOperation:
                raise ValueError("price and quantity must be finite decimal numbers") from None
            if not number.is_finite() or not math.isfinite(float(number)):
                raise ValueError("price and quantity must be finite decimal numbers")
            if number != 0 and float(number) == 0:
                raise ValueError("price and quantity must be representable without underflow")
            numbers.append(number)
        price, quantity = numbers
        if price <= 0 or quantity < 0 or (snapshot and quantity == 0):
            raise ValueError("price must be positive; only delta quantity may be zero")
        if price in result:
            raise ValueError("duplicate prices within one side are ambiguous")
        result[price] = quantity
    return result


def _validate_book(bids: dict, asks: dict) -> None:
    if not bids or not asks:
        raise ValueError("both sides must remain nonempty")
    if len(bids) > MAX_BOOK_LEVELS or len(asks) > MAX_BOOK_LEVELS:
        raise ValueError(f"retained book exceeds {MAX_BOOK_LEVELS} levels per side")
    if max(bids) >= min(asks):
        raise ValueError("crossed or locked book")
    for side in (bids, asks):
        notional = sum((p * q for p, q in side.items()), Decimal(0))
        if not math.isfinite(float(notional)):
            raise ValueError("book notional overflows supported arithmetic")


def replay_binance_usdm(replay: Any, symbol: str) -> tuple[dict | None, dict]:
    """Return final synchronized ccxt-shaped book and bounded diagnostic trace.

    Input order is receive order. Invalid events discard the active book until a
    new snapshot, which must itself bridge before any features become available.
    """
    if not isinstance(replay, dict) or set(replay) != {"protocol", "events"}:
        raise ValueError("replay requires only protocol and events")
    if replay["protocol"] != PROTOCOL:
        raise ValueError(f"replay protocol must be {PROTOCOL}")
    events = replay["events"]
    if not isinstance(events, list) or not 1 <= len(events) <= MAX_EVENTS:
        raise ValueError(f"replay requires 1..{MAX_EVENTS} events")

    state = "NEEDS_SNAPSHOT"
    bids: dict[Decimal, Decimal] = {}
    asks: dict[Decimal, Decimal] = {}
    last_id: int | None = None
    timestamp: int | None = None
    seen: dict[int, tuple] = {}
    trace = []
    generation = 0
    for index, event in enumerate(events):
        result = {"index": index, "status": "INVALID"}
        try:
            if not isinstance(event, dict):
                raise ValueError("event must be an object")
            kind = event.get("type")
            if kind not in ("snapshot", "delta"):
                raise ValueError("event type must be snapshot or delta")
            if kind == "delta" and state in ("NEEDS_SNAPSHOT", "INVALID"):
                result.update(status="BLOCKED_UNTIL_SNAPSHOT", state=state,
                              last_update_id=last_id, generation=generation)
                trace.append(result)
                continue
            allowed = (
                {"type", "lastUpdateId", "bids", "asks", "E", "T", "s"}
                if kind == "snapshot"
                else {"type", "e", "U", "u", "pu", "b", "a", "E", "T", "s"}
            )
            if set(event) - allowed:
                raise ValueError("unexpected event fields; use unwrapped Binance depth payloads")
            if "s" in event and event["s"] != symbol:
                raise ValueError("event symbol differs from requested Binance instrument")
            event_time = event.get("E")
            if event_time is not None:
                event_time = _update_id(event_time)
                if event_time > 253402300799000:
                    raise ValueError("event timestamp is outside supported UTC range")
            if "T" in event:
                _update_id(event["T"])

            if kind == "snapshot":
                next_id = _update_id(event.get("lastUpdateId"))
                if last_id is not None and next_id < last_id:
                    raise ValueError("snapshot update ID is older than the last accepted update")
                next_bids = _levels(event.get("bids"), snapshot=True)
                next_asks = _levels(event.get("asks"), snapshot=True)
                _validate_book(next_bids, next_asks)
                bids, asks = next_bids, next_asks
                last_id, timestamp = next_id, event_time
                state = "AWAITING_BRIDGE"
                seen.clear()
                generation += 1
                result["status"] = "SNAPSHOT_ACCEPTED"
            else:
                if event.get("e") != "depthUpdate" or event.get("s") != symbol:
                    raise ValueError("delta must be depthUpdate for the requested Binance symbol")
                first = _update_id(event.get("U"))
                final = _update_id(event.get("u"))
                previous = _update_id(event.get("pu"))
                if first > final or previous >= final:
                    raise ValueError("delta update range or previous update ID is invalid")
                changes_b = _levels(event.get("b"), snapshot=False)
                changes_a = _levels(event.get("a"), snapshot=False)
                identity = (first, previous, changes_b, changes_a)
                if final in seen:
                    if seen[final] != identity:
                        raise ValueError("conflicting duplicate update ID")
                    result["status"] = "DUPLICATE_IGNORED"
                elif final < last_id or (state == "SYNCHRONIZED" and final == last_id):
                    result["status"] = "STALE_IGNORED"
                else:
                    if state == "AWAITING_BRIDGE":
                        if not first <= last_id <= final:
                            raise ValueError("missing snapshot bridge: require U <= lastUpdateId <= u")
                    elif previous != last_id:
                        raise ValueError("sequence gap: pu differs from prior accepted u")
                    next_bids, next_asks = dict(bids), dict(asks)
                    for side, changes in ((next_bids, changes_b), (next_asks, changes_a)):
                        for price, quantity in changes.items():
                            if quantity == 0:
                                side.pop(price, None)
                            else:
                                side[price] = quantity
                    _validate_book(next_bids, next_asks)
                    bids, asks = next_bids, next_asks
                    last_id, timestamp = final, event_time
                    seen[final] = identity
                    state = "SYNCHRONIZED"
                    result["status"] = "DELTA_APPLIED"
        except ValueError as exc:
            state = "INVALID"
            bids, asks = {}, {}
            timestamp = None
            result["error"] = str(exc)
        result["state"] = state
        result["last_update_id"] = last_id
        result["generation"] = generation
        trace.append(result)

    diagnostics = {
        "protocol": PROTOCOL,
        "product": "binance_usdm_futures",
        "state": state,
        "valid": state == "SYNCHRONIZED",
        "requires_snapshot": state in ("INVALID", "NEEDS_SNAPSHOT"),
        "last_update_id": last_id,
        "events": trace[-20:],
        "events_total": len(trace),
        "events_omitted": max(len(trace) - 20, 0),
        "status_counts": dict(Counter(event["status"] for event in trace)),
        "last_error": next((event["error"] for event in reversed(trace) if "error" in event), None),
        "coverage": "supplied snapshot and received deltas only; unknown levels are not inferred",
        "provenance": "caller_supplied_unverified",
    }
    if state != "SYNCHRONIZED":
        return None, diagnostics
    book = {
        "bids": [(float(p), float(q)) for p, q in sorted(bids.items(), reverse=True)],
        "asks": [(float(p), float(q)) for p, q in sorted(asks.items())],
        "timestamp": timestamp,
        "nonce": last_id,
    }
    return book, diagnostics

