"""Deterministic forex preflight; execution prices never use research fallbacks."""

from datetime import datetime, timezone
from .errors import ForexError
from .models import Connection, Order, number, utcnow


def check(config: Connection, order: Order, data: dict) -> dict:
    def require(condition, code, message):
        if not condition:
            raise ForexError(code, message)

    require(order.expires_at > utcnow(), "INTENT_EXPIRED", "The intent has expired")
    require(
        order.symbol in config.symbols, "SYMBOL_NOT_ALLOWED", "Select this native symbol in the connection allowlist"
    )
    require(str(data.get("account_ref")) == config.account_ref, "ACCOUNT_MISMATCH", "The broker account changed")
    require(
        data.get("environment") == config.environment, "ENVIRONMENT_MISMATCH", "The broker environment does not match"
    )
    require(
        data.get("currency") == "USD",
        "UNSUPPORTED_ACCOUNT_CURRENCY",
        "Execution currently requires a USD account; other currencies remain readable",
    )
    require(data.get("trade_allowed") is True, "TRADING_DISABLED", "Broker or terminal trading permission is disabled")
    quote = data.get("quote")
    require(isinstance(quote, dict), "INVALID_QUOTE", "Broker quote must be an object")
    try:
        stamp = datetime.fromisoformat(str(quote.get("timestamp", "")).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError("Missing timezone")
        stamp = stamp.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        raise ForexError("QUOTE_TIME_UNKNOWN", "Broker quote has no valid timestamp") from None
    age = (utcnow() - stamp).total_seconds()
    require(-2 <= age <= config.limits.max_quote_age_seconds, "STALE_QUOTE", "A fresh broker quote is required")
    try:
        bid, ask, point = (number(quote[k], positive=True) for k in ("bid", "ask", "point"))
    except (KeyError, TypeError, ValueError):
        raise ForexError("INVALID_QUOTE", "Broker bid, ask and point must be finite positive numbers") from None
    require(ask >= bid, "INVALID_QUOTE", "Broker ask is below bid")
    require(quote.get("tradeable") is True, "MARKET_CLOSED", "The instrument is not currently tradeable")
    require(
        (ask - bid) / point <= number(config.limits.max_spread_points),
        "SPREAD_LIMIT",
        "Spread exceeds the configured point limit",
    )
    qty, minimum, maximum, step = (
        number(v, positive=True)
        for v in (order.quantity, data["min_quantity"], data["max_quantity"], data["quantity_step"])
    )
    require(
        minimum <= qty <= maximum and (qty - minimum) % step == 0,
        "INVALID_VOLUME_STEP",
        "Quantity does not match broker minimum, maximum or step",
    )
    if order.action == "close":
        require(
            config.connector == "mt5" and config.environment == "demo",
            "CLOSE_UNSUPPORTED",
            "Closing requires an MT5 demo connection",
        )
        require(data.get("position_owned") is True, "POSITION_NOT_OWNED", "Only journal-owned positions may be closed")
        require(
            str(data.get("position_ticket")) == order.position_ticket
            and data.get("close_side") == order.side
            and qty <= number(data.get("position_volume", "0")),
            "POSITION_CHANGED",
            "Position ticket, side or remaining volume changed",
        )
        return {k: v for k, v in data.items() if k != "request"}
    require(
        data.get("pending_orders_count") == 0,
        "PENDING_ORDERS",
        "Resolve existing pending entry orders before adding exposure",
    )
    require(qty <= number(config.limits.max_quantity), "QUANTITY_LIMIT", "Quantity exceeds the configured ceiling")
    stop = number(order.stop_loss, positive=True)
    price_step = number(data.get("price_step", point), positive=True)
    require((stop / price_step) % 1 == 0, "INVALID_STOP_PRECISION", "Stop price does not align to the broker tick size")
    require(
        stop < bid if order.side == "buy" else stop > ask,
        "INVALID_STOP",
        "Stop must be beyond the exit-side broker price",
    )
    if order.take_profit is not None:
        take = number(order.take_profit, positive=True)
        require(
            (take / price_step) % 1 == 0, "INVALID_TAKE_PROFIT_PRECISION", "Take-profit does not align to tick size"
        )
        require(
            take > ask if order.side == "buy" else take < bid, "INVALID_TAKE_PROFIT", "Take-profit is on the wrong side"
        )
    notional, loss, margin = (
        number(data[k], positive=True) for k in ("notional_usd", "stop_risk_usd", "estimated_margin")
    )
    require(
        notional <= number(config.limits.max_order_notional_usd),
        "NOTIONAL_LIMIT",
        "Order notional exceeds the configured ceiling",
    )
    require(
        loss <= number(config.limits.max_stop_risk_usd),
        "STOP_RISK_LIMIT",
        "Estimated stop risk exceeds the configured ceiling",
    )
    require(
        data.get("position_exposure_usd") is not None,
        "EXPOSURE_UNAVAILABLE",
        "Existing positions cannot be valued in USD",
    )
    gross = number(data["position_exposure_usd"])
    require(gross >= 0, "EXPOSURE_UNAVAILABLE", "Gross exposure must be non-negative")
    require(
        gross + notional <= number(config.limits.max_total_exposure_usd),
        "EXPOSURE_LIMIT",
        "Gross exposure would exceed the configured ceiling",
    )
    require(
        gross + notional <= number(data["equity"], positive=True) * number(config.limits.max_leverage),
        "LEVERAGE_LIMIT",
        "Gross exposure exceeds the configured leverage against account equity",
    )
    require(margin <= number(data["free_margin"]), "INSUFFICIENT_MARGIN", "Insufficient free margin")
    return {k: v for k, v in data.items() if k != "request"}
