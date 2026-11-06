"""Public Binance USD-M perpetual OI and realized funding research via CCXT.

Linear OI amount is already base quantity in Binance's CCXT parser; multiplying
it by contractSize again would change its units. Funding cash estimates use only
the markPrice attached to the historical settlement, never today's mark price.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any

from backtest.loaders.ccxt_loader import _CCXT_TIMEOUT_MS, _ccxt_proxy_config
from src.agent.tools import BaseTool
from src.config.limits import TOOL_RESULT_LIMIT
from src.tools.orderbook_depth_tool import _coerce_int
from src.tools.crypto_derivatives_archive import ArchiveError, configured_archive, timestamp

_PERIODS = ("5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d")
_DOC = "https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data"


def _fetch_history(symbol: str, metric: str, period: str, limit: int) -> tuple[dict, list]:
    import ccxt

    config: dict[str, Any] = {"enableRateLimit": True, "timeout": _CCXT_TIMEOUT_MS}
    proxies = _ccxt_proxy_config()
    if proxies:
        config["proxies"] = proxies
    exchange = ccxt.binanceusdm(config)
    exchange.load_markets()
    market = exchange.market(symbol)
    _validate_market(market, symbol)
    if metric == "open_interest":
        rows = exchange.fetch_open_interest_history(symbol, period, limit=limit)
    else:
        # A single bounded response; explicit capture mode can retain it for
        # local replay, but this fetch does not paginate provider history.
        rows = exchange.fetch_funding_rate_history(symbol, limit=limit)
    return market, rows


def _number(value: Any, label: str, *, nonnegative: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError(f"{label} must be a finite number")
    try:
        number = float(value)
    except (ValueError, OverflowError):
        raise ValueError(f"{label} must be a finite number") from None
    if not math.isfinite(number) or (nonnegative and number < 0):
        raise ValueError(f"{label} must be finite" + (" and nonnegative" if nonnegative else ""))
    return number


def _validate_market(market: Any, symbol: str) -> None:
    base = symbol.split("/")[0]
    if not isinstance(market, dict) or any((
        market.get("symbol") != symbol,
        market.get("base") != base,
        market.get("quote") != "USDT",
        market.get("settle") != "USDT",
        market.get("swap") is not True,
        market.get("linear") is not True,
        market.get("inverse") is not False,
        market.get("expiry") is not None,
    )):
        raise ValueError("market metadata must identify the requested USDT-settled linear perpetual")
    if _number(market.get("contractSize"), "contractSize", nonnegative=True) <= 0:
        raise ValueError("contractSize must be positive")


def _iso(timestamp_ms: Any) -> str:
    timestamp = _number(timestamp_ms, "event timestamp", nonnegative=True)
    if not timestamp.is_integer():
        raise ValueError("event timestamp must be integer milliseconds")
    try:
        return datetime.fromtimestamp(timestamp / 1000, timezone.utc).isoformat().replace("+00:00", "Z")
    except (ValueError, OverflowError, OSError):
        raise ValueError("event timestamp is out of range") from None


def _observations(rows: Any, symbol: str, metric: str, limit: int, retrieved_ms: int) -> list[dict]:
    if not isinstance(rows, list) or len(rows) > limit:
        raise ValueError("history must be a bounded list")
    observations: dict[tuple[int, str | None], dict] = {}
    for raw in rows:
        if not isinstance(raw, dict) or raw.get("symbol") != symbol:
            raise ValueError("history row has missing or mismatched symbol")
        event_time = _iso(raw.get("timestamp"))
        timestamp = int(float(raw["timestamp"]))
        if timestamp > retrieved_ms:
            raise ValueError("history row is in the future; expected realized observations")
        row: dict[str, Any] = {"event_time": event_time, "timestamp_ms": timestamp}
        rate_type = None
        if metric == "open_interest":
            quantity = _number(raw.get("openInterestAmount"), "openInterestAmount", nonnegative=True)
            value = _number(raw.get("openInterestValue"), "openInterestValue", nonnegative=True)
            if (quantity == 0) != (value == 0):
                raise ValueError("OI quantity and quote value must be zero together")
            row.update(amount_base=quantity, value_quote=value,
                       implied_price_quote_per_base=value / quantity if quantity else None)
        else:
            rate = _number(raw.get("fundingRate"), "fundingRate")
            info = raw.get("info")
            if not isinstance(info, dict):
                raise ValueError("funding row must retain raw historical info")
            if info.get("symbol") != symbol.replace("/", "").split(":")[0]:
                raise ValueError("raw funding symbol does not match requested market")
            if _iso(info.get("fundingTime")) != event_time:
                raise ValueError("raw funding event timestamp does not match")
            rate_type = info.get("rateType")
            if rate_type not in (None, "Regular", "Special"):
                raise ValueError("raw funding rateType must be Regular, Special or absent")
            mark_raw = info.get("markPrice")
            mark = None if mark_raw is None or mark_raw == "" else _number(mark_raw, "historical markPrice", nonnegative=True)
            if mark is not None and mark <= 0:
                raise ValueError("historical markPrice must be positive")
            row.update(rate=rate, rate_type=rate_type, historical_mark_price=mark,
                       long_cash_per_base_quote=-rate * mark if mark is not None else None,
                       short_cash_per_base_quote=rate * mark if mark is not None else None)
        identity = (timestamp, rate_type)
        if identity in observations and observations[identity] != row:
            raise ValueError("conflicting observations at the same event identity")
        observations[identity] = row
    return sorted(observations.values(), key=lambda row: (row["timestamp_ms"], row.get("rate_type") or ""))


def _summary(rows: list[dict], metric: str) -> dict:
    first, last = rows[0], rows[-1]
    if metric == "open_interest":
        q0, q1 = first["amount_base"], last["amount_base"]
        p0, p1 = first["implied_price_quote_per_base"], last["implied_price_quote_per_base"]
        decomposition = None
        if p0 is not None and p1 is not None:
            quantity = (q1 - q0) * (p0 / 2 + p1 / 2)
            price = (p1 - p0) * (q0 / 2 + q1 / 2)
            decomposition = {
                "quantity_component_quote": quantity,
                "implied_price_component_quote": price,
                "rounding_residual_quote": last["value_quote"] - first["value_quote"] - quantity - price,
                "method": "delta_Q * mean(P) + delta_P * mean(Q); P=OI_value/OI_amount",
                "interpretation": "algebraic endpoint decomposition; not causal attribution or observed mark prices",
            }
        return {"first_amount_base": q0, "last_amount_base": q1,
                "change_amount_base": q1 - q0,
                "min_amount_base": min(row["amount_base"] for row in rows),
                "max_amount_base": max(row["amount_base"] for row in rows),
                "first_value_quote": first["value_quote"], "last_value_quote": last["value_quote"],
                "min_value_quote": min(row["value_quote"] for row in rows),
                "max_value_quote": max(row["value_quote"] for row in rows),
                "change_value_quote": last["value_quote"] - first["value_quote"],
                "value_change_decomposition": decomposition}
    rates = [row["rate"] for row in rows]
    marked = [row for row in rows if row["historical_mark_price"] is not None]
    return {
        "realized_events": len(rows), "rate_sum": math.fsum(rates),
        "events_by_rate_type": {kind: sum(row["rate_type"] == (None if kind == "unknown" else kind) for row in rows) for kind in ("Regular", "Special", "unknown")},
        "rate_min": min(rates), "rate_max": max(rates),
        "events_with_historical_mark": len(marked),
        "long_cash_per_base_quote": math.fsum(row["long_cash_per_base_quote"] for row in marked) if len(marked) == len(rows) else None,
        "short_cash_per_base_quote": math.fsum(row["short_cash_per_base_quote"] for row in marked) if len(marked) == len(rows) else None,
        "cash_assumption": "one base unit held at every returned settlement; excludes fees and changing position size",
        "rate_sum_interpretation": "sum of returned settlement rates, not annualized yield or compounded return",
    }


def _error(code: str, message: str) -> str:
    return json.dumps({"ok": False, "error_code": code, "error": message})


def _report(symbol: str, metric: str, period: str, limit: int, rows: list[dict],
            market: dict, returned_records: int, retrieved_at: str) -> dict:
    gaps = sorted({(b["timestamp_ms"] - a["timestamp_ms"]) / 1000 for a, b in zip(rows, rows[1:]) if b["timestamp_ms"] > a["timestamp_ms"]})
    endpoint = "open-interest-statistics" if metric == "open_interest" else "get-funding-rate-history"
    return {
        "ok": True, "market": "crypto", "source": "ccxt_binanceusdm_public",
        "symbol": symbol, "metric": metric,
        "period": period if metric == "open_interest" else None,
        "units": {"amount_base": market["base"], "value_quote": "USDT", "price": "USDT per base", "funding_rate": "fraction per actual settlement"},
        "contract": {"linear": True, "settle": "USDT", "contract_size_base": market["contractSize"], "oi_amount_already_base": True},
        "provenance": {
            "retrieved_at": retrieved_at,
            "event_time_source": "exchange", "historical_available_at": None,
            "historical_availability": "unknown; this response is not a point-in-time archive",
            "reference": _DOC + "#" + endpoint,
            "normalized_observations_sha256": hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest(),
        },
        "coverage": {
            "requested_limit": limit, "returned_records": returned_records, "unique_records": len(rows),
            "start": rows[0]["event_time"], "end": rows[-1]["event_time"],
            "observed_intervals_seconds": gaps,
            "completeness": "unknown; observed gaps do not prove a settlement schedule or complete history",
            "provider_window": "recent history only; OI endpoint limited to latest month" if metric == "open_interest" else "bounded latest realized settlements",
        },
        "summary": _summary(rows, metric), "observations": rows[-10:],
        "display": {"sampled": len(rows) > 10, "shown_records": min(len(rows), 10), "selection": "latest 10; summary and hash cover all unique returned observations"},
    }


def _archive_report(archive, symbol: str, metric: str, period: str, limit: int, as_of: str) -> str:
    history = archive.query(symbol=symbol, metric=metric, period=period if metric == "open_interest" else None,
                            as_of=as_of, limit=limit)
    rows = history["observations"]
    if not rows:
        return _error("NO_DATA", "No observations were locally recorded by this cutoff; history was not backfilled")
    result = _report(symbol, metric, period, limit, rows,
                     {"base": symbol.removesuffix("-USDT-PERP"), "contractSize": None}, len(rows), None)
    result["source"] = "local_crypto_derivatives_archive"
    result["contract"]["contract_size_source"] = "capture-specific metadata; normalized OI is already base quantity"
    normalized = [{key: value for key, value in row.items() if key != "archive_evidence"} for row in rows]
    result["provenance"].update(
        as_of=history["as_of"],
        historical_availability="exchange historical availability unknown; as_of uses actual local recording time",
        availability_basis="recorded_at <= as_of; capture time is not historical exchange publication time",
        normalized_observations_sha256=hashlib.sha256(json.dumps(normalized, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest(),
    )
    result["coverage"].update(
        provider_window="locally captured history only; no provider request or forward fill",
        older_observations_omitted=history["limited"],
    )
    result["archive"] = {key: history[key] for key in ("snapshot_sha256", "revised_observations", "selected_capture_count", "verified_supporting_capture_count")}
    result["archive"]["revision_policy"] = "latest locally recorded revision per event identity; conflicting latest-time ties fail closed"
    payload = json.dumps(result, ensure_ascii=False, allow_nan=False)
    if len(payload) > TOOL_RESULT_LIMIT:
        return _error("RESULT_TOO_LARGE", "Archive result exceeds output limit; reduce requested limit")
    return payload


class CryptoDerivativesTool(BaseTool):
    name = "crypto_derivatives"
    # Capture writes. Treat the whole agent tool conservatively so it is never
    # scheduled as a parallel read or mirrored onto a read-only MCP surface.
    is_readonly = False
    description = (
        "Read public Binance USD-M linear perpetual open-interest or realized funding history. "
        "Use explicit BASE-USDT-PERP symbols. Reports actual coverage, units and availability limits; "
        "OI value changes are decomposed algebraically, never interpreted as directional positioning. "
        "Funding is not forecast, annualized, or assumed to settle every eight hours. "
        "Default mode=live is read-only. Explicit capture persists a bounded fetch in an administrator-configured "
        "local archive. Archive mode is offline and requires as_of; local recording time never proves historical exchange availability."
    )
    repeatable = True
    parameters = {
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "description": "Explicit linear perpetual, e.g. BTC-USDT-PERP"},
            "metric": {"type": "string", "enum": ["open_interest", "funding"], "default": "open_interest"},
            "period": {"type": "string", "enum": list(_PERIODS), "default": "1h", "description": "OI sampling period; ignored for realized funding events"},
            "limit": {"type": "integer", "minimum": 2, "maximum": 100, "default": 30},
            "mode": {"type": "string", "enum": ["live", "capture", "archive"], "default": "live"},
            "as_of": {"type": "string", "description": "ISO timestamp with timezone; required only for offline archive mode"},
        },
        "required": ["symbol"],
    }

    def execute(self, **kwargs: Any) -> str:
        raw_symbol = kwargs.get("symbol")
        symbol = raw_symbol.strip().upper() if isinstance(raw_symbol, str) else ""
        if re.fullmatch(r"[A-Z0-9]{1,30}-USDT-PERP", symbol) is None:
            return _error("INVALID_ARGUMENT", "symbol must be explicit BASE-USDT-PERP, e.g. BTC-USDT-PERP")
        metric, period = kwargs.get("metric", "open_interest"), kwargs.get("period", "1h")
        limit = _coerce_int(kwargs.get("limit", 30))
        if metric not in ("open_interest", "funding") or period not in _PERIODS:
            return _error("INVALID_ARGUMENT", "unsupported metric or period")
        if limit is None or not 2 <= limit <= 100:
            return _error("INVALID_ARGUMENT", "limit must be an integer between 2 and 100")
        mode, as_of = kwargs.get("mode", "live"), kwargs.get("as_of")
        if mode not in ("live", "capture", "archive") or (mode != "archive" and as_of is not None):
            return _error("INVALID_ARGUMENT", "mode must be live, capture or archive; as_of applies only to archive")
        archive = None
        try:
            if mode == "archive":
                timestamp(as_of)
            if mode != "live":
                archive = configured_archive()
            if mode == "archive":
                return _archive_report(archive, symbol, metric, period, limit, as_of)
        except ArchiveError as exc:
            return _error(exc.code, str(exc))
        except (OSError, sqlite3.Error, ValueError, TypeError, OverflowError, RecursionError):
            return _error("ARCHIVE_UNAVAILABLE", "Derivative archive cannot be read; no history was inferred")
        ccxt_symbol = symbol.removesuffix("-USDT-PERP") + "/USDT:USDT"
        try:
            market, raw_rows = _fetch_history(ccxt_symbol, metric, period, limit)
        except ValueError as exc:
            return _error("INVALID_PROVIDER_DATA", str(exc))
        except Exception:
            return _error("PROVIDER_ERROR", "Binance USD-M public history request failed; no data was inferred")
        retrieved_at = datetime.now(timezone.utc)
        try:
            _validate_market(market, ccxt_symbol)
            rows = _observations(raw_rows, ccxt_symbol, metric, limit, int(retrieved_at.timestamp() * 1000))
            if not rows:
                return _error("NO_DATA", "provider returned no historical observations")
            result = _report(symbol, metric, period, limit, rows, market, len(raw_rows), retrieved_at.isoformat().replace("+00:00", "Z"))
            payload = json.dumps(result, ensure_ascii=False, allow_nan=False)
        except (ValueError, TypeError, OverflowError) as exc:
            return _error("INVALID_PROVIDER_DATA", str(exc))
        if len(payload) > TOOL_RESULT_LIMIT:
            return _error("RESULT_TOO_LARGE", "bounded result exceeds tool output limit; reduce requested limit")
        if mode == "capture":
            # Reserve a bounded manifest receipt before writing. A successful
            # commit must not be hidden behind a subsequent output overflow.
            if len(payload) + 1024 > TOOL_RESULT_LIMIT:
                return _error("RESULT_TOO_LARGE", "Capture receipt would exceed output limit; reduce requested limit before saving")
            try:
                result["archive"] = archive.append(symbol=symbol, metric=metric,
                    period=period if metric == "open_interest" else None, market=market,
                    raw_rows=raw_rows, observations=rows, retrieved_at=result["provenance"]["retrieved_at"])
                result["provenance"].update(
                    local_recorded_at=result["archive"]["recorded_at"],
                    historical_availability="exchange historical availability unknown; capture records actual local recording time",
                )
            except ArchiveError as exc:
                return _error(exc.code, str(exc))
            except (OSError, sqlite3.Error, ValueError, TypeError, OverflowError, RecursionError):
                return _error("ARCHIVE_UNAVAILABLE", "Capture could not be saved; no archive receipt was issued")
            payload = json.dumps(result, ensure_ascii=False, allow_nan=False)
        return payload
