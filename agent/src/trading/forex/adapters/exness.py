"""Exness Trader API adapter: discovery, signing, ticks and async receipts."""

from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import re
import threading
import time
from urllib.parse import quote as urlquote

import httpx
from websockets.sync.client import connect

from .exness_auth import private_key, sign
from ..errors import ForexError
from ..models import Connection, Order, broker_reference, decimal_text, number, utcnow

INTERVALS = {"5m": ("M5", 300), "15m": ("M15", 900), "1h": ("H1", 3600), "4h": ("H4", 14400)}


class Exness:
    def __init__(self, config: Connection, credentials: dict, client: httpx.Client | None = None, ws_factory=None):
        self.config = config
        if not credentials.get("api_key") or not credentials.get("private_key"):
            raise ForexError(
                "CREDENTIALS_UNAVAILABLE", "Save the Exness API key and Ed25519 private key in the OS vault"
            )
        self.key, self.api_key = private_key(credentials["private_key"]), credentials["api_key"]
        self.client = client or httpx.Client(timeout=15, follow_redirects=False, trust_env=False)
        self.ws_factory = ws_factory or connect
        self.ap = None
        self.limits = None
        self.requests = defaultdict(deque)
        self.rate_lock = threading.Lock()
        self._base(config.gateway_url)

    def close(self):
        self.client.close()

    def _base(self, value: str) -> str:
        u = httpx.URL(value)
        if (
            u.scheme != "https"
            or u.host not in self.config.allowed_hosts
            or not u.host.endswith((".exness.com", ".exness-api.com"))
            or u.username
            or u.password
            or u.query
            or u.fragment
            or u.path not in ("", "/")
            or u.port not in (None, 443)
        ):
            raise ForexError("UNAPPROVED_HOST", "Exness host is outside the saved HTTPS host allowlist")
        return str(u).rstrip("/")

    def _throttle(self, method: str, path: str):
        if self.limits is None:
            return
        rest = self.limits.get("rest", {})
        candidates = [("global", rest.get("global_account_rate"))]
        matching = None
        for item in rest.get("methods", []):
            pattern = re.sub(r"\{[^}]+\}", "[^/]+", item.get("path", ""))
            if item.get("http_method", "").upper() == method and re.fullmatch(pattern, path.split("?")[0]):
                matching = item.get("rate_limit")
                candidates.append((method + pattern, matching))
        if method != "GET" and not matching:
            raise ForexError("LIMITS_UNAVAILABLE", "Current Exness operation rate limits are unavailable")
        with self.rate_lock:
            now = time.monotonic()
            checked = []
            for name, rule in candidates:
                if not rule:
                    continue
                window, maximum = int(rule["window_seconds"]), int(rule["limit"])
                queue = self.requests[name]
                while queue and queue[0] <= now - window:
                    queue.popleft()
                if len(queue) >= maximum:
                    raise ForexError("RATE_LIMIT", "Wait for the configured Exness request window before trying again")
                checked.append(queue)
            for queue in checked:
                queue.append(now)

    def _request(self, base: str, method: str, path: str, *, params=None, payload=None, request_key="") -> dict:
        self._throttle(method, path)
        body = b"" if payload is None else json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
        request = self.client.build_request(
            method, self._base(base) + path, params=params, content=body, headers={"Content-Type": "application/json"}
        )
        request.headers.update(sign(request, self.api_key, self.key, request_key))
        response = self.client.send(request, follow_redirects=False)
        if response.status_code in (400, 401, 403, 404, 405, 410, 413, 415, 422, 429):
            raise ForexError(
                "BROKER_REJECTED",
                f"Exness rejected the request (HTTP {response.status_code}); check permissions, limits and signed request configuration",
            )
        response.raise_for_status()
        return response.json()

    def call(self, method: str, path: str, **kwargs) -> dict:
        if self.ap is None:
            data = self._request(
                self.config.gateway_url,
                "GET",
                "/v1/trading/access-point",
                params={"account_id": self.config.account_ref},
            )
            if str(data.get("account_id")) != self.config.account_ref:
                raise ForexError("ACCOUNT_MISMATCH", "Exness discovery returned another account")
            self.ap = self._base(data["access_point"])
        if self.limits is None:
            self.limits = self._request(self.ap, "GET", self.path("configuration", "limits"))["limits"]
        return self._request(self.ap, method, path, **kwargs)

    def path(self, domain: str, resource: str) -> str:
        return f"/v1/{domain}/accounts/{self.config.account_ref}/{resource}"

    def account(self) -> dict:
        data = self.call("GET", self.path("configuration", "account"))
        if not isinstance(data, dict):
            raise ForexError("VALUATION_UNAVAILABLE", "Exness account response is malformed")
        if str(data.get("account_id")) != self.config.account_ref:
            raise ForexError("ACCOUNT_MISMATCH", "Exness returned another account")
        state = self.call("GET", self.path("trading", "snapshot"))
        try:
            settings, money = data["settings"], state["account_state"]
            currency = settings["currency"]
            if not isinstance(currency, str) or not currency:
                raise ValueError("Missing account currency")
            for key in ("balance", "equity", "used_margin"):
                number(money[key])
            free_margin = decimal_text(number(money["equity"]) - number(money["used_margin"]))
            positions, orders = state["positions"], state["orders"]
            if any(not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows) for rows in (positions, orders)):
                raise ValueError("Invalid position or order collection")
        except (KeyError, TypeError, ValueError):
            raise ForexError("VALUATION_UNAVAILABLE", "Exness account balances, positions or pending orders are malformed") from None
        return {
            "account_ref": self.config.account_ref,
            "environment": "live",
            "currency": settings["currency"],
            "balance": money["balance"],
            "equity": money["equity"],
            "free_margin": free_margin,
            "trade_allowed": settings.get("account_status") == "active" and settings.get("trade_mode") == "full",
            "positions": positions,
            "orders": orders,
        }

    def instruments(self, query: str = "", limit: int = 50) -> list[dict]:
        data = self.call("GET", self.path("configuration", "instruments"))
        names = data.get("instruments", [])
        result = []
        for item in names:
            name = item if isinstance(item, str) else item.get("instrument")
            if name and query.lower() in name.lower():
                result.append({"instrument": name, "source": "exness"})
        return result[:limit]

    def conditions(self, symbol: str) -> dict:
        data = self.call("GET", self.path("configuration", "instruments/" + urlquote(symbol, safe="") + "/conditions"))
        if not isinstance(data, dict):
            raise ForexError("VALUATION_UNAVAILABLE", "Exness instrument conditions are malformed")
        if data.get("instrument") != symbol:
            raise ForexError("SYMBOL_NOT_FOUND", "Exness did not return the exact requested instrument")
        return data

    def quote(self, symbol: str) -> dict:
        info = self.conditions(symbol)
        try:
            precision = number(info["point_digits"])
            if precision % 1 or not 0 <= precision <= 18:
                raise ValueError("Invalid point precision")
        except (KeyError, TypeError, ValueError):
            raise ForexError("VALUATION_UNAVAILABLE", "Exness instrument has invalid point precision") from None
        path = self.path("server-events", "ws/ticks")
        request = httpx.Request("GET", self.ap + path)
        headers = sign(request, self.api_key, self.key)
        uri = "wss://" + httpx.URL(self.ap).host + path
        with self.ws_factory(
            uri, additional_headers=headers, open_timeout=10, close_timeout=2, max_size=1024 * 1024, proxy=None
        ) as socket:
            socket.send(json.dumps({"id": "quote", "subscribe": {"event": "ticks", "instruments": [symbol]}}))
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                raw = socket.recv(timeout=max(0.1, deadline - time.monotonic()))
                try:
                    data = json.loads(raw)
                except (TypeError, ValueError):
                    raise ForexError("INVALID_QUOTE", "Exness tick message is not valid JSON") from None
                if not isinstance(data, dict):
                    raise ForexError("INVALID_QUOTE", "Exness tick message must be an object")
                tick = data.get("tick", data)
                if not isinstance(tick, dict):
                    raise ForexError("INVALID_QUOTE", "Exness tick must be an object")
                if tick.get("instrument") == symbol:
                    try:
                        bid, ask = number(tick["bid"], positive=True), number(tick["ask"], positive=True)
                        if ask < bid:
                            raise ValueError("Crossed quote")
                    except (KeyError, TypeError, ValueError):
                        raise ForexError("INVALID_QUOTE", "Exness bid and ask must be valid positive prices") from None
                    try:
                        stamp = datetime.fromisoformat(tick["timestamp"].replace("Z", "+00:00"))
                        if stamp.tzinfo is None:
                            raise ValueError("Missing timezone")
                        stamp.astimezone(timezone.utc)
                    except (KeyError, AttributeError, TypeError, ValueError, OverflowError):
                        raise ForexError("QUOTE_TIME_UNKNOWN", "Exness tick has no valid timestamp") from None
                    return {
                        "symbol": symbol,
                        "bid": decimal_text(tick["bid"]),
                        "ask": decimal_text(tick["ask"]),
                        "timestamp": tick["timestamp"],
                        "point": format(Decimal(10) ** -int(precision), "f"),
                        "tradeable": info.get("trade_mode") == "full",
                        "source": "exness",
                    }
        raise ForexError("QUOTE_UNAVAILABLE", "Exness did not return a matching tick")

    def candles(self, symbol: str, timeframe: str, limit: int) -> list[dict]:
        native, seconds = INTERVALS[timeframe]
        # Positive count starts at `from`; align the window so it reaches the
        # current bar instead of leaving several stale bars at the end.
        opened = int(utcnow().timestamp()) // seconds * seconds
        start = datetime.fromtimestamp(opened - seconds * (limit - 1), timezone.utc)
        data = self.call(
            "GET",
            self.path("market-data", "candles"),
            params={
                "instrument": symbol,
                "timeframe": native,
                "from": start.isoformat(),
                "count": limit,
                "price_type": "bid",
            },
        )
        result = []
        for row in data.get("candles", []):
            stamp = datetime.fromisoformat(row["time"].replace("Z", "+00:00"))
            result.append(
                {
                    "time": row["time"],
                    "close": decimal_text(row["close"]),
                    **{key: decimal_text(row[key]) for key in ("open", "high", "low") if key in row},
                    "complete": stamp + timedelta(seconds=seconds) <= utcnow(),
                    "source": "exness",
                    "price_type": "bid",
                }
            )
        return result

    def prepare(self, order: Order) -> dict:
        account, info, q = self.account(), self.conditions(order.symbol), self.quote(order.symbol)
        required = ("contract_size", "volume_min", "volume_max", "volume_step", "margin_percent")
        if any(info.get(key) is None for key in required):
            raise ForexError(
                "VALUATION_UNAVAILABLE", "Exness instrument conditions lack required contract, volume or margin fields"
            )
        if info.get("quote_currency") != "USD":
            raise ForexError(
                "CONVERSION_UNAVAILABLE",
                "Exness execution currently requires a USD-quoted instrument; all available instruments remain readable",
            )
        if info.get("exec_mode") not in ("market", "instant"):
            raise ForexError("EXECUTION_MODE_UNSUPPORTED", "Unsupported Exness execution mode")
        try:
            contract = number(info["contract_size"], positive=True)
            for field in ("volume_min", "volume_max", "volume_step", "margin_percent"):
                number(info[field], positive=True)
            if not isinstance(info.get("category", ""), str):
                raise ValueError("Invalid category")
        except (KeyError, TypeError, ValueError):
            raise ForexError("VALUATION_UNAVAILABLE", "Exness instrument has invalid contract, volume or margin fields") from None
        qty = number(order.quantity, positive=True)
        price = number(q["ask"] if order.side == "buy" else q["bid"])
        exposure = Decimal(0)
        for pos in account["positions"]:
            try:
                native = pos["instrument"]
                if not isinstance(native, str) or not native:
                    raise ValueError("Invalid position instrument")
                volume = number(pos["volume"], positive=True)
            except (KeyError, TypeError, ValueError):
                raise ForexError("EXPOSURE_UNAVAILABLE", "An Exness position has invalid instrument or volume") from None
            condition = self.conditions(native)
            if condition.get("quote_currency") != "USD":
                raise ForexError("CONVERSION_UNAVAILABLE", "An existing position cannot be valued in USD")
            if condition.get("contract_size") is None:
                raise ForexError("VALUATION_UNAVAILABLE", "An existing Exness position lacks a contract size")
            try:
                position_contract = number(condition["contract_size"], positive=True)
            except (KeyError, TypeError, ValueError):
                raise ForexError("VALUATION_UNAVAILABLE", "An Exness position has invalid contract size") from None
            tick = self.quote(native)
            stamp = datetime.fromisoformat(tick["timestamp"].replace("Z", "+00:00"))
            if not -2 <= (utcnow() - stamp).total_seconds() <= self.config.limits.max_quote_age_seconds:
                raise ForexError("STALE_CONVERSION", "A fresh broker price is required for every open Exness position")
            exposure += (
                volume
                * position_contract
                * max(number(tick["bid"]), number(tick["ask"]))
            )
        payload = {
            "instrument": order.symbol,
            "side": order.side,
            "volume": order.quantity,
            "stop_loss_price": order.stop_loss,
        }
        if order.take_profit:
            payload["take_profit_price"] = order.take_profit
        if info["exec_mode"] == "instant":
            payload["price"] = decimal_text(price)
            payload["deviation"] = str(self.config.limits.max_deviation_points)
        notional = qty * contract * number(q["ask"], positive=True)
        try:
            valuation = {
                "notional_usd": decimal_text(notional),
                "stop_risk_usd": decimal_text(qty * contract * abs(price - number(order.stop_loss))),
                "estimated_margin": decimal_text(notional * number(info["margin_percent"], positive=True) / 100),
                "position_exposure_usd": decimal_text(exposure),
            }
        except ValueError:
            raise ForexError("VALUATION_UNAVAILABLE", "Exness valuation exceeds supported numeric bounds") from None
        return {
            **account,
            **valuation,
            "quote": q,
            "instrument_type": "forex" if info.get("category", "").lower() == "forex" else "cfd",
            "quantity_unit": "native_contracts",
            "min_quantity": info["volume_min"],
            "max_quantity": info["volume_max"],
            "quantity_step": info["volume_step"],
            "pending_orders_count": len([o for o in account["orders"] if o.get("order_type") != "sltp"]),
            "request": payload,
        }

    def submit(self, order: Order, prepared: dict) -> dict:
        key = broker_reference(prepared["intent_id"]) if prepared.get("intent_id") else order.request_key
        result = self.call("POST", self.path("trading", "positions"), payload=prepared["request"], request_key=key)
        correlated = result.get("client_request_id") == key and bool(result.get("operation_id"))
        return {
            "state": "accepted" if correlated else "unknown",
            "operation_id": result.get("operation_id"),
            "client_request_id": result.get("client_request_id"),
        }

    def reconcile(self, receipt: dict) -> dict:
        if not receipt.get("operation_id"):
            return {**receipt, "state": "unknown"}
        result = self.call("GET", self.path("trading", "operations/" + urlquote(str(receipt["operation_id"]), safe="")))
        expected = receipt.get("client_order_id") or receipt.get("client_request_id")
        if expected and result.get("client_request_id") != expected:
            raise ForexError(
                "CORRELATION_MISMATCH", "Exness operation does not match this intent's persisted client request ID"
            )
        state = {"pending": "accepted", "confirmed": "confirmed", "rejected": "rejected", "failed": "rejected"}.get(
            result.get("status"), "unknown"
        )
        return {
            **receipt,
            "state": state,
            "broker_status": result.get("status"),
            "error_code": result.get("error_code"),
        }
