"""Private JSON/stdin worker. Never register these native operations as tools."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from contextlib import ExitStack, contextmanager
from pathlib import Path
import hashlib
import json
import sys
from time import monotonic, sleep

from src.live.daily_count import DailyOrderLockUnavailable, daily_order_lock
from src.trading.connectors.mt5 import _client
from src.trading.connectors.mt5.orders import _filling_mode
from src.trading.connectors.mt5.symbols import classify_mt5_symbol
from ..errors import ForexError
from ..models import Connection, Order, broker_reference, decimal_text, number, utcnow
from ..risk import check

INTERVALS = {
    "1m": ("TIMEFRAME_M1", 60),
    "5m": ("TIMEFRAME_M5", 300),
    "15m": ("TIMEFRAME_M15", 900),
    "30m": ("TIMEFRAME_M30", 1800),
    "1h": ("TIMEFRAME_H1", 3600),
    "4h": ("TIMEFRAME_H4", 14400),
    "1d": ("TIMEFRAME_D1", 86400),
}


@contextmanager
def terminal_read_lock(key):
    """Queue only lock acquisition for reads; never retry a native operation.

    The shared order-admission lock stays non-blocking. Waiting happens before
    SDK attach/identity checks and is bounded below the chart request timeout.
    Exceptions from the acquired session propagate without another attempt.
    """
    deadline = monotonic() + 10
    with ExitStack() as held:
        while True:
            try:
                held.enter_context(daily_order_lock(key))
                break
            except DailyOrderLockUnavailable:
                if monotonic() >= deadline:
                    raise ForexError("MT5_BUSY", "MT5 terminal is busy; retry this read later") from None
                sleep(.05)
        yield


class Native:
    def __init__(self, sdk, config, native_config):
        self.mt5, self.config, self.native_config = sdk, config, native_config

    def rows(self, value):
        if value is None:
            raise ForexError("MT5_READ_UNAVAILABLE", "MT5 returned no account/order data")
        return [row._asdict() for row in value]

    def identity(self):
        account = self.mt5.account_info()
        if account is None or str(account.login) != self.config.account_ref or account.server != self.config.server:
            raise ForexError("ACCOUNT_MISMATCH", "MT5 login or broker server changed")
        expected = (
            self.mt5.ACCOUNT_TRADE_MODE_DEMO if self.config.environment == "demo" else self.mt5.ACCOUNT_TRADE_MODE_REAL
        )
        if account.trade_mode != expected:
            raise ForexError("ENVIRONMENT_MISMATCH", "MT5 demo/live identity does not match")
        return account

    def account(self):
        a = self.identity()
        terminal = self.mt5.terminal_info()
        positions = self.rows(self.mt5.positions_get())
        orders = self.rows(self.mt5.orders_get())
        exposure = Decimal(0)
        for row in positions:
            try:
                value = self.usd_notional(row["symbol"], row["volume"])
            except ForexError:
                exposure = None
                break
            exposure += value
        return {
            "account_ref": str(a.login),
            "server": a.server,
            "environment": self.config.environment,
            "currency": a.currency,
            "balance": decimal_text(a.balance),
            "equity": decimal_text(a.equity),
            "free_margin": decimal_text(a.margin_free),
            "trade_allowed": bool(
                terminal
                and terminal.connected
                and terminal.trade_allowed
                and not terminal.tradeapi_disabled
                and a.trade_allowed
                and a.trade_expert
            ),
            "terminal_connected": bool(terminal and terminal.connected),
            "terminal_trade_allowed": bool(terminal and terminal.trade_allowed),
            "external_api_disabled": bool(terminal and terminal.tradeapi_disabled),
            "account_trade_allowed": bool(a.trade_allowed and a.trade_expert),
            "hedging": getattr(a, "margin_mode", None) == getattr(self.mt5, "ACCOUNT_MARGIN_MODE_RETAIL_HEDGING", 2),
            "positions": positions,
            "orders": orders,
            "position_exposure_usd": None if exposure is None else decimal_text(exposure),
        }

    def usd_notional(self, symbol, lots):
        """Conservative gross USD value using fresh native broker conversions."""
        info = self.instrument(symbol)
        units = number(lots, positive=True) * number(info.trade_contract_size, positive=True)
        base, profit = info.currency_base, info.currency_profit
        if base == "USD":
            return units

        def prices(name):
            quote = self.quote(name)
            stamp = datetime.fromisoformat(quote["timestamp"].replace("Z", "+00:00"))
            age = (utcnow() - stamp).total_seconds()
            if not -2 <= age <= self.config.limits.max_quote_age_seconds:
                raise ForexError("STALE_CONVERSION", "A fresh MT5 quote is required for USD exposure valuation")
            bid, ask = number(quote["bid"], positive=True), number(quote["ask"], positive=True)
            if ask < bid:
                raise ForexError("INVALID_QUOTE", "Invalid broker conversion quote")
            return bid, ask

        if profit == "USD":
            return units * max(prices(symbol))
        prefix = base + profit
        if not symbol.startswith(prefix):
            raise ForexError("CONVERSION_UNAVAILABLE", "Cannot infer an unambiguous native USD conversion instrument")
        suffix = symbol[len(prefix) :]
        for name, expected_base, expected_profit in (
            (base + "USD" + suffix, base, "USD"),
            ("USD" + base + suffix, "USD", base),
        ):
            conversion = self.mt5.symbol_info(name)
            if (
                conversion
                and conversion.currency_base == expected_base
                and conversion.currency_profit == expected_profit
            ):
                bid, ask = prices(name)
                return units * ask if expected_profit == "USD" else units / bid
        raise ForexError("CONVERSION_UNAVAILABLE", "The broker offers no matching native USD conversion instrument")

    def instrument(self, symbol):
        info = self.mt5.symbol_info(symbol)
        if info is None or info.name != symbol:
            raise ForexError("SYMBOL_NOT_FOUND", "Use an exact native MT5 symbol from the instrument catalog")
        if not info.visible and not self.mt5.symbol_select(symbol, True):
            raise ForexError("SYMBOL_UNAVAILABLE", "MT5 could not select the instrument")
        return info

    def instruments(self, query="", limit=50):
        rows = self.mt5.symbols_get()
        if rows is None:
            raise ForexError("CATALOG_UNAVAILABLE", "MT5 instrument catalog is unavailable")
        return [
            {
                "symbol": r.name,
                "description": r.description,
                "point": r.point,
                "volume_min": r.volume_min,
                "volume_max": r.volume_max,
                "volume_step": r.volume_step,
                "contract_size": r.trade_contract_size,
                "currency_base": r.currency_base,
                "currency_profit": r.currency_profit,
                "source": "mt5",
            }
            for r in rows
            if query.lower() in r.name.lower()
        ][:limit]

    def quote(self, symbol):
        info = self.instrument(symbol)
        tick = self.mt5.symbol_info_tick(symbol)
        if tick is None:
            raise ForexError("QUOTE_UNAVAILABLE", "MT5 tick is unavailable")
        stamp = getattr(tick, "time_msc", 0) / 1000 or tick.time
        return {
            "symbol": symbol,
            "bid": decimal_text(tick.bid),
            "ask": decimal_text(tick.ask),
            "timestamp": datetime.fromtimestamp(stamp, timezone.utc).isoformat(),
            "point": decimal_text(info.point),
            "price_step": decimal_text(getattr(info, "trade_tick_size", 0) or info.point),
            "minimum_stop_distance": decimal_text(number(info.trade_stops_level) * number(info.point)),
            "tradeable": info.trade_mode == self.mt5.SYMBOL_TRADE_MODE_FULL,
            "source": "mt5",
        }

    def candles(self, symbol, timeframe, limit):
        return self._rates(symbol, timeframe, limit, start_pos=1)

    def chart(self, symbol, timeframe, limit):
        bars = self._rates(symbol, timeframe, limit, start_pos=0)
        quote = self.quote(symbol)
        self.identity()
        return {"bars": bars, "quote": quote}

    def _rates(self, symbol, timeframe, limit, *, start_pos):
        self.instrument(symbol)
        native, seconds = INTERVALS[timeframe]
        rates = self.mt5.copy_rates_from_pos(symbol, getattr(self.mt5, native), start_pos, limit)
        if rates is None:
            raise ForexError("HISTORY_UNAVAILABLE", "MT5 bars are unavailable")
        return [
            {
                "time": datetime.fromtimestamp(int(r["time"]), timezone.utc).isoformat(),
                **{key: decimal_text(r[key]) for key in ("open", "high", "low")},
                "close": decimal_text(r["close"]),
                "volume": int(r["tick_volume"]),
                "real_volume": int(r["real_volume"]),
                "volume_type": "tick_count",
                "complete": datetime.fromtimestamp(int(r["time"]), timezone.utc) + timedelta(seconds=seconds)
                <= utcnow(),
                "source": "mt5",
            }
            for r in rates
        ]

    def prepare(self, order):
        if order.action == "close":
            return self.prepare_close(order)
        a, q, info = self.account(), self.quote(order.symbol), self.instrument(order.symbol)
        side = self.mt5.ORDER_TYPE_BUY if order.side == "buy" else self.mt5.ORDER_TYPE_SELL
        qty = float(number(order.quantity, positive=True))
        price = float(q["ask"] if order.side == "buy" else q["bid"])
        loss = self.mt5.order_calc_profit(side, order.symbol, qty, price, float(order.stop_loss))
        margin = self.mt5.order_calc_margin(side, order.symbol, qty, price)
        notional = self.usd_notional(order.symbol, order.quantity)
        if loss is None or margin is None or notional is None:
            raise ForexError("VALUATION_UNAVAILABLE", "MT5 order valuation or margin estimate is unavailable")
        minimum_stop = number(info.trade_stops_level) * number(info.point)
        exit_price = number(q["bid"] if order.side == "buy" else q["ask"])
        if abs(exit_price - number(order.stop_loss)) < minimum_stop:
            raise ForexError("INVALID_STOPS", "Stop is closer than the broker minimum distance")
        request = {
            "action": self.mt5.TRADE_ACTION_DEAL,
            "symbol": order.symbol,
            "volume": qty,
            "type": side,
            "price": price,
            "sl": float(order.stop_loss),
            "deviation": self.config.limits.max_deviation_points,
            "magic": 2601103,
            "comment": order.request_key[:31],
            "type_filling": _filling_mode(self.mt5, info, pending=False),
            "type_time": self.mt5.ORDER_TIME_GTC,
        }
        if order.take_profit:
            request["tp"] = float(order.take_profit)
        return {
            **a,
            "quote": q,
            "quantity_unit": "lots",
            "instrument_type": classify_mt5_symbol(order.symbol)[0].value,
            "price_step": decimal_text(getattr(info, "trade_tick_size", 0) or info.point),
            "min_quantity": decimal_text(info.volume_min),
            "max_quantity": decimal_text(info.volume_max),
            "quantity_step": decimal_text(info.volume_step),
            "notional_usd": decimal_text(notional),
            "stop_risk_usd": decimal_text(abs(loss)),
            "estimated_margin": decimal_text(margin),
            "pending_orders_count": len(a["orders"]),
            "account_flat": not a["positions"] and not a["orders"],
            "request": request,
        }

    def prepare_close(self, order):
        from ..store import Store

        if self.config.environment != "demo":
            raise ForexError("CLOSE_UNSUPPORTED", "Automatic position closing is demo-only")
        a = self.account()
        if not a["hedging"]:
            raise ForexError("HEDGING_REQUIRED", "Use a demo hedge account to isolate managed positions")
        rows = [p for p in a["positions"] if str(p["ticket"]) == order.position_ticket]
        if len(rows) != 1 or rows[0]["symbol"] != order.symbol:
            raise ForexError("POSITION_CHANGED", "Position no longer exists on this account/symbol")
        position = rows[0]
        if not Store().owns_position(self.config, position):
            raise ForexError(
                "POSITION_NOT_OWNED", "Position does not belong to a filled entry in this connection journal"
            )
        close_side = "sell" if position["type"] == self.mt5.POSITION_TYPE_BUY else "buy"
        if order.side != close_side or number(order.quantity) > number(position["volume"]):
            raise ForexError("POSITION_CHANGED", "Close direction or remaining position volume changed")
        info, q = self.instrument(order.symbol), self.quote(order.symbol)
        return {
            **a,
            "quote": q,
            "position_owned": True,
            "position_ticket": order.position_ticket,
            "close_side": close_side,
            "position_volume": decimal_text(position["volume"]),
            "min_quantity": decimal_text(info.volume_min),
            "max_quantity": decimal_text(info.volume_max),
            "quantity_step": decimal_text(info.volume_step),
            "quantity_unit": "lots",
            "request": {
                "action": self.mt5.TRADE_ACTION_DEAL,
                "position": int(order.position_ticket),
                "symbol": order.symbol,
                "volume": float(order.quantity),
                "type": self.mt5.ORDER_TYPE_SELL if close_side == "sell" else self.mt5.ORDER_TYPE_BUY,
                "price": float(q["bid"] if close_side == "sell" else q["ask"]),
                "deviation": self.config.limits.max_deviation_points,
                "magic": 2601103,
                "type_filling": _filling_mode(self.mt5, info, pending=False),
                "type_time": self.mt5.ORDER_TIME_GTC,
            },
        }

    def submit(self, order, intent_id=None):
        data = self.prepare(order)
        check(self.config, order, data)
        # Re-read consent/halt in the worker after subprocess startup too.
        from ..policy import authorize
        from ..store import Store

        authorize(self.config, order, data, Store(), own_intent=intent_id)
        if order.strategy_revision.startswith("ai-") and order.action == "open" and not data.get("account_flat"):
            raise ForexError("POSITION_CHANGED", "AI entries require a flat account immediately before sending")
        if intent_id:
            data["request"]["comment"] = broker_reference(intent_id)
        result = self.mt5.order_check(data["request"])
        if result is None or result.retcode not in (0, self.mt5.TRADE_RETCODE_DONE):
            raise ForexError("BROKER_REJECTED", "MT5 order_check rejected the protected order")
        self.identity()
        response = self.mt5.order_send(data["request"])
        if response is None:
            return {"state": "unknown", "reason": "MT5 returned no order receipt"}
        code = response.retcode
        if code in (10012, 10031):
            return {"state": "unknown", "retcode": code}
        states = {10009: "filled", 10010: "partial", 10008: "working"}
        return {
            "state": states.get(code, "rejected"),
            "retcode": code,
            "order_id": str(response.order),
            "deal_id": str(response.deal),
            "filled_quantity": decimal_text(response.volume),
            "filled_price": decimal_text(response.price),
        }

    def reconcile(self, receipt):
        self.identity()
        ticket = receipt.get("order_id")
        if not ticket or not str(ticket).isdigit():
            tag, stamp = receipt.get("client_order_id"), receipt.get("submitted_at")
            if not tag or not stamp:
                return {**receipt, "state": "unknown"}
            start = datetime.fromisoformat(stamp.replace("Z", "+00:00")) - timedelta(minutes=1)
            pending = self.mt5.orders_get()
            history = self.mt5.history_orders_get(start, utcnow())
            if pending is None or history is None:
                return {**receipt, "state": "unknown"}
            matches = {
                row.ticket: row
                for row in [*pending, *history]
                if row.comment == tag and row.magic == 2601103 and row.symbol == receipt.get("symbol")
            }
            if len(matches) != 1:
                return {
                    **receipt,
                    "state": "unknown",
                    "reason": "No unique broker history match for the persisted correlation tag",
                }
            ticket = next(iter(matches))
            receipt = {**receipt, "order_id": str(ticket)}
        pending = self.mt5.orders_get(ticket=int(ticket))
        if pending:
            return {**receipt, "state": "working"}
        rows = self.mt5.history_orders_get(ticket=int(ticket))
        if not rows:
            return {**receipt, "state": "unknown"}
        mapping = {
            self.mt5.ORDER_STATE_FILLED: "filled",
            self.mt5.ORDER_STATE_CANCELED: "cancelled",
            self.mt5.ORDER_STATE_REJECTED: "rejected",
            self.mt5.ORDER_STATE_EXPIRED: "cancelled",
        }
        return {**receipt, "state": mapping.get(rows[-1].state, "unknown")}


@contextmanager
def existing_session(path):
    """Attach by explicit executable only; never call login or change saved credentials."""
    import MetaTrader5 as mt5

    if not Path(path).is_absolute() or Path(path).name.lower() != "terminal64.exe" or not Path(path).is_file():
        raise ForexError("MT5_UNAVAILABLE", "Expected an installed terminal64.exe")
    if not mt5.initialize(path, timeout=10000):
        raise ForexError("MT5_UNAVAILABLE", "Cannot attach to the running MT5 session")
    try:
        yield mt5
    finally:
        mt5.shutdown()


def probe(path):
    with existing_session(path) as mt5:
        a, terminal = mt5.account_info(), mt5.terminal_info()
        if a is None or terminal is None or not terminal.connected:
            raise ForexError("MT5_UNAVAILABLE", "This terminal has no connected broker account")
        if a.trade_mode not in (mt5.ACCOUNT_TRADE_MODE_DEMO, mt5.ACCOUNT_TRADE_MODE_REAL):
            raise ForexError("ENVIRONMENT_MISMATCH", "Contest/unknown account types are unsupported")
        return {
            "terminal_path": path,
            "account_ref": str(a.login),
            "server": a.server,
            "environment": "demo" if a.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO else "live",
            "currency": a.currency,
            "terminal_trade_allowed": bool(terminal.trade_allowed),
            "external_api_disabled": bool(terminal.tradeapi_disabled),
        }


def dispatch(payload):
    if payload["operation"] == "probe":
        path = payload["terminal_path"]
        key = "mt5-terminal-" + hashlib.sha256(path.casefold().encode()).hexdigest()[:20]
        with terminal_read_lock(key):
            return probe(path)
    config = Connection.model_validate(payload["config"])
    native = _client.MT5Config(
        login=int(config.account_ref),
        password=payload.get("credentials", {}).get("password", ""),
        server=config.server,
        terminal_path=config.terminal_path,
        profile="paper" if config.environment == "demo" else "live",
    )
    terminal_key = "mt5-terminal-" + hashlib.sha256(config.terminal_path.casefold().encode()).hexdigest()[:20]
    session = (
        existing_session(config.terminal_path)
        if config.session_mode == "existing_terminal"
        else _client._session(native)
    )
    op = payload["operation"]
    lock = terminal_read_lock(terminal_key) if op in {"account", "instruments", "quote", "candles", "chart"} else daily_order_lock(terminal_key)
    with lock, session as mt5:
        client = Native(mt5, config, native)
        client.identity()
        op, args = payload["operation"], payload.get("arguments", {})
        if op in ("prepare", "submit"):
            args["order"] = Order.model_validate(args["order"])
        allowed = {"account", "instruments", "quote", "candles", "chart", "prepare", "submit", "reconcile"}
        if op not in allowed:
            raise ForexError("UNSUPPORTED_OPERATION", "Unsupported MT5 worker operation")
        return getattr(client, op)(**args)


def main():
    try:
        payload = json.loads(sys.stdin.read(128 * 1024))
        result = {"status": "ok", "data": dispatch(payload)}
    except ForexError as exc:
        result = exc.payload()
    except Exception:
        result = {
            "status": "error",
            "code": "MT5_UNAVAILABLE",
            "error": "MT5 operation failed; verify the optional MetaTrader5 package, terminal and account configuration",
        }
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
