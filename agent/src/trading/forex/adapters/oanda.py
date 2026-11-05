"""OANDA v20 REST adapter. Practice/live hosts are fixed by the saved binding."""

from decimal import Decimal
from datetime import datetime, timezone
from urllib.parse import quote as urlquote

import httpx

from ..errors import ForexError
from ..models import Connection, Order, number, decimal_text, broker_reference, utcnow

INTERVALS = {"5m": ("M5", 300), "15m": ("M15", 900), "1h": ("H1", 3600), "4h": ("H4", 14400)}


class Oanda:
    def __init__(self, config: Connection, credentials: dict, client: httpx.Client | None = None):
        self.config = config
        if not credentials.get("token"):
            raise ForexError("CREDENTIALS_UNAVAILABLE", "Save the OANDA personal access token in the OS vault")
        self.client = client or httpx.Client(timeout=15, follow_redirects=False, trust_env=False)
        self.base = (
            "https://api-fxpractice.oanda.com" if config.environment == "demo" else "https://api-fxtrade.oanda.com"
        )
        self.headers = {"Authorization": "Bearer " + credentials["token"]}
        self.prefix = f"/v3/accounts/{urlquote(config.account_ref, safe='')}"

    def close(self):
        self.client.close()

    def request(self, method: str, path: str, **kwargs) -> dict:
        response = self.client.request(method, self.base + path, headers=self.headers, **kwargs)
        if response.status_code in (400, 401, 403, 404, 405, 410, 413, 415, 422, 429):
            raise ForexError(
                "BROKER_REJECTED",
                f"OANDA rejected the request (HTTP {response.status_code}); verify permissions and instrument limits",
            )
        response.raise_for_status()
        return response.json()

    def account(self) -> dict:
        data = self.request("GET", self.prefix + "/summary")
        try:
            a = data["account"]
            identity, currency = a["id"], a["currency"]
            for key in ("NAV", "balance", "marginAvailable"):
                number(a[key])
            if not isinstance(currency, str) or not currency:
                raise ValueError("Missing account currency")
        except (KeyError, TypeError, ValueError):
            raise ForexError("VALUATION_UNAVAILABLE", "OANDA account has invalid identity, currency or balances") from None
        if str(identity) != self.config.account_ref:
            raise ForexError("ACCOUNT_MISMATCH", "OANDA returned another account")
        trades = self.request("GET", self.prefix + "/openTrades")
        pending = self.request("GET", self.prefix + "/pendingOrders")
        try:
            positions, orders = trades["trades"], pending["orders"]
            if any(not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows) for rows in (positions, orders)):
                raise ValueError("Invalid position or order collection")
        except (KeyError, TypeError, ValueError):
            raise ForexError("VALUATION_UNAVAILABLE", "OANDA account positions or pending orders are malformed") from None
        return {
            "account_ref": str(a["id"]),
            "environment": self.config.environment,
            "currency": a["currency"],
            "equity": a["NAV"],
            "balance": a["balance"],
            "free_margin": a["marginAvailable"],
            "trade_allowed": a.get("alias") is not None or a.get("id") is not None,
            "positions": positions,
            "orders": orders,
            "position_exposure_usd": "0" if not positions else None,
            "broker_position_value": a.get("positionValue"),
        }

    def instruments(self, query: str = "", limit: int = 50) -> list[dict]:
        rows = self.request("GET", self.prefix + "/instruments")["instruments"]
        return [row for row in rows if query.lower() in row["name"].lower()][:limit]

    def quote(self, symbol: str) -> dict:
        data = self.request("GET", self.prefix + "/pricing", params={"instruments": symbol})
        if not isinstance(data, dict) or not isinstance(data.get("prices"), list) or any(not isinstance(row, dict) for row in data["prices"]):
            raise ForexError("INVALID_QUOTE", "OANDA pricing must contain a list of quotes")
        rows = data["prices"]
        if len(rows) != 1 or rows[0].get("instrument") != symbol:
            raise ForexError("QUOTE_UNAVAILABLE", "OANDA returned no unambiguous quote")
        p = rows[0]
        info = self.instrument(symbol)
        try:
            precision = number(info["displayPrecision"])
            if precision % 1 or not 0 <= precision <= 18:
                raise ValueError("Invalid display precision")
        except (KeyError, TypeError, ValueError):
            raise ForexError("VALUATION_UNAVAILABLE", "OANDA instrument has invalid display precision") from None
        try:
            bid, ask = number(p["bids"][0]["price"], positive=True), number(p["asks"][0]["price"], positive=True)
            if ask < bid:
                raise ValueError("Crossed quote")
        except (KeyError, IndexError, TypeError, ValueError):
            raise ForexError("INVALID_QUOTE", "OANDA bid and ask must be valid positive prices") from None
        try:
            stamp = datetime.fromisoformat(p["time"].replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                raise ValueError("Missing timezone")
            stamp.astimezone(timezone.utc)
        except (KeyError, AttributeError, TypeError, ValueError, OverflowError):
            raise ForexError("QUOTE_TIME_UNKNOWN", "OANDA quote has no valid timestamp") from None
        return {
            "symbol": symbol,
            "bid": p["bids"][0]["price"],
            "ask": p["asks"][0]["price"],
            "timestamp": p["time"],
            "point": format(Decimal(10) ** -int(precision), "f"),
            "tradeable": p.get("tradeable") is True or p.get("status") == "tradeable",
            "source": "oanda",
        }

    def instrument(self, symbol: str) -> dict:
        data = self.request("GET", self.prefix + "/instruments", params={"instruments": symbol})
        if not isinstance(data, dict) or not isinstance(data.get("instruments"), list) or any(not isinstance(row, dict) for row in data["instruments"]):
            raise ForexError("VALUATION_UNAVAILABLE", "OANDA instrument response is malformed")
        rows = data["instruments"]
        matches = [row for row in rows if row.get("name") == symbol]
        if len(matches) != 1:
            raise ForexError("SYMBOL_NOT_FOUND", "Use an exact native OANDA instrument name")
        return matches[0]

    def candles(self, symbol: str, timeframe: str, limit: int) -> list[dict]:
        granularity, _ = INTERVALS[timeframe]
        data = self.request(
            "GET",
            self.prefix + f"/instruments/{urlquote(symbol, safe='')}/candles",
            params={"granularity": granularity, "count": limit, "price": "M"},
        )
        return [
            {
                "time": c["time"],
                "close": c["mid"]["c"],
                "complete": c["complete"],
                **{
                    key: c["mid"][native]
                    for key, native in (("open", "o"), ("high", "h"), ("low", "l"))
                    if native in c["mid"]
                },
                "volume": c.get("volume"),
                "volume_type": "price_updates",
                "source": "oanda",
            }
            for c in data.get("candles", [])
        ]

    def prepare(self, order: Order) -> dict:
        account, q = self.account(), self.quote(order.symbol)
        if account["currency"] != "USD":
            raise ForexError("UNSUPPORTED_ACCOUNT_CURRENCY", "OANDA execution currently requires a USD account")
        info = self.instrument(order.symbol)
        try:
            for key in ("minimumTradeSize", "maximumOrderUnits", "marginRate"):
                number(info[key], positive=True)
            precision = number(info["tradeUnitsPrecision"])
            if precision % 1 or not 0 <= precision <= 18:
                raise ValueError("Invalid quantity precision")
        except (KeyError, TypeError, ValueError):
            raise ForexError("VALUATION_UNAVAILABLE", "OANDA instrument has invalid volume or margin fields") from None
        price = number(q["ask"] if order.side == "buy" else q["bid"])
        qty = number(order.quantity, positive=True)
        # Pricing conversions belong to the same OANDA account, not Yahoo.
        try:
            instruments = sorted({order.symbol, *(trade["instrument"] for trade in account["positions"])})
            if any(not isinstance(symbol, str) or not symbol for symbol in instruments):
                raise ValueError("Invalid position instrument")
            for trade in account["positions"]:
                number(trade["currentUnits"])
        except (KeyError, TypeError, ValueError):
            raise ForexError("EXPOSURE_UNAVAILABLE", "An open OANDA trade has invalid instrument or units") from None
        pricing = self.request(
            "GET",
            self.prefix + "/pricing",
            params={"instruments": ",".join(instruments), "includeHomeConversions": "true"},
        )
        if not isinstance(pricing, dict):
            raise ForexError("EXPOSURE_UNAVAILABLE", "OANDA valuation pricing is malformed")

        def conversion_rate(symbol):
            currency = symbol.split("_")[-1]
            if currency == "USD":
                return Decimal(1)
            try:
                rows = pricing.get("homeConversions", [])
                if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                    raise ValueError("Invalid conversion collection")
                matches = [row for row in rows if row.get("currency") == currency]
                if len(matches) == 1:
                    return max(number(matches[0]["accountGain"], positive=True), number(matches[0]["accountLoss"], positive=True))
            except (KeyError, TypeError, ValueError):
                raise ForexError("CONVERSION_UNAVAILABLE", "OANDA quote-currency conversion is malformed") from None
            raise ForexError("CONVERSION_UNAVAILABLE", "OANDA quote-currency to USD conversion is unavailable")

        conversion = conversion_rate(order.symbol)
        notional = qty * number(q["ask"], positive=True) * conversion
        gross = Decimal(0)
        try:
            rows = pricing.get("prices", [])
            if not isinstance(rows, list):
                raise ValueError("Invalid valuation quotes")
            prices = {row["instrument"]: row for row in rows}
            if len(prices) != len(rows):
                raise ValueError("Ambiguous valuation quotes")
        except (KeyError, TypeError, ValueError):
            raise ForexError("EXPOSURE_UNAVAILABLE", "OANDA position valuation quotes are malformed or ambiguous") from None
        for trade in account["positions"]:
            native = trade["instrument"]
            row = prices.get(native)
            if not row:
                raise ForexError("EXPOSURE_UNAVAILABLE", "An open OANDA trade lacks a broker valuation quote")
            try:
                stamp = datetime.fromisoformat(row["time"].replace("Z", "+00:00"))
                if stamp.tzinfo is None:
                    raise ValueError("Missing timezone")
                stamp = stamp.astimezone(timezone.utc)
            except (KeyError, AttributeError, TypeError, ValueError, OverflowError):
                raise ForexError("QUOTE_TIME_UNKNOWN", "An OANDA valuation quote has no valid timestamp") from None
            if (
                not -2 <= (utcnow() - stamp).total_seconds() <= self.config.limits.max_quote_age_seconds
            ):
                raise ForexError("STALE_CONVERSION", "A fresh broker price is required for every open OANDA trade")
            try:
                bid = number(row["bids"][0]["price"], positive=True)
                ask = number(row["asks"][0]["price"], positive=True)
            except (KeyError, IndexError, TypeError, ValueError):
                raise ForexError("INVALID_QUOTE", "OANDA position valuation quote has invalid bid or ask") from None
            if ask < bid:
                raise ForexError("INVALID_QUOTE", "OANDA position valuation quote is invalid")
            gross += abs(number(trade["currentUnits"])) * ask * conversion_rate(native)
        pending = [
            r
            for r in account["orders"]
            if r.get("type") not in ("STOP_LOSS", "TAKE_PROFIT", "TRAILING_STOP_LOSS", "GUARANTEED_STOP_LOSS")
        ]
        signed = qty if order.side == "buy" else -qty
        request = {
            "order": {
                "type": "MARKET",
                "instrument": order.symbol,
                "units": decimal_text(signed),
                "timeInForce": "FOK",
                "positionFill": "DEFAULT",
                "clientExtensions": {"id": order.request_key},
                "stopLossOnFill": {"price": order.stop_loss},
            }
        }
        if order.take_profit:
            request["order"]["takeProfitOnFill"] = {"price": order.take_profit}
        try:
            valuation = {
                "notional_usd": decimal_text(notional),
                "stop_risk_usd": decimal_text(qty * abs(price - number(order.stop_loss)) * conversion),
                "estimated_margin": decimal_text(notional * number(info["marginRate"], positive=True)),
                "position_exposure_usd": decimal_text(gross),
            }
        except ValueError:
            raise ForexError("VALUATION_UNAVAILABLE", "OANDA valuation exceeds supported numeric bounds") from None
        return {
            **account,
            **valuation,
            "quote": q,
            "quantity_unit": "units",
            "instrument_type": "forex" if info.get("type") == "CURRENCY" else "cfd",
            "min_quantity": info["minimumTradeSize"],
            "max_quantity": info["maximumOrderUnits"],
            "quantity_step": format(Decimal(10) ** -int(precision), "f"),
            "pending_orders_count": len(pending),
            "request": request,
        }

    def submit(self, order: Order, prepared: dict) -> dict:
        request = {"order": {**prepared["request"]["order"]}}
        if prepared.get("intent_id"):
            request["order"]["clientExtensions"] = {"id": broker_reference(prepared["intent_id"])}
        result = self.request("POST", self.prefix + "/orders", json=request)
        if fill := result.get("orderFillTransaction"):
            return {
                "state": "filled",
                "order_id": str(fill["orderID"]),
                "deal_id": str(fill["id"]),
                "filled_quantity": fill["units"],
                "filled_price": fill["price"],
            }
        if cancel := result.get("orderCancelTransaction"):
            return {
                "state": "rejected",
                "reason": cancel.get("reason", "cancelled"),
                "order_id": str(cancel["orderID"]),
            }
        create = result.get("orderCreateTransaction", {})
        return {"state": "accepted", "order_id": str(create["id"]) if "id" in create else None}

    def reconcile(self, receipt: dict) -> dict:
        identifier = receipt.get("order_id") or (
            "@" + receipt["client_order_id"] if receipt.get("client_order_id") else None
        )
        if not identifier:
            return {**receipt, "state": "unknown"}
        row = self.request("GET", self.prefix + "/orders/" + urlquote(identifier, safe=""))["order"]
        expected = receipt.get("client_order_id")
        if expected and (
            row.get("clientExtensions", {}).get("id") != expected
            or (receipt.get("symbol") and row.get("instrument") != receipt["symbol"])
        ):
            raise ForexError(
                "CORRELATION_MISMATCH", "OANDA order does not match this intent's persisted client ID and instrument"
            )
        mapping = {"PENDING": "working", "FILLED": "filled", "CANCELLED": "cancelled", "TRIGGERED": "accepted"}
        return {
            **receipt,
            "state": mapping.get(row["state"], "unknown"),
            "order_id": str(row.get("id", identifier)),
            "broker_state": row["state"],
        }
