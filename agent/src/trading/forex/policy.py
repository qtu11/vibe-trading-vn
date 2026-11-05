"""Use existing consent/halt enforcement with an explicit per-connection identity."""

from datetime import datetime

from src.live.daily_count import read_daily_count
from src.live.enforcement import OrderIntent, check_mandate
from src.live.halt import halt_flag_set
from src.live.mandate.model import MANDATE_SCHEMA_VERSION, InstrumentType, AssetClass
from src.live.mandate.store import load_mandate

from .errors import ForexError
from .models import number, utcnow
from .risk import check


def authorize(config, order, assessment, store, own_intent=None):
    check(config, order, assessment)
    if not config.execution_enabled:
        raise ForexError("READONLY", "Operator has not enabled execution for this connection")
    if store.connection(config.id).fingerprint() != config.fingerprint():
        raise ForexError("BINDING_CHANGED", "Connection changed; recreate the intent")
    if any(halt_flag_set(key) for key in (config.connector, config.mandate_key)):
        raise ForexError("HALTED", "Global, broker or connection trading halt is active")
    if any(row["id"] != own_intent for row in store.active(config.connector)):
        raise ForexError(
            "RECONCILIATION_REQUIRED", "Resolve the outstanding connector execution before another submission"
        )
    # A proven reduction of our demo hedge position must remain possible after
    # the entry-count/drawdown cap. Identity, halt, claim and quote checks still apply.
    if order.action == "close":
        if own_intent:
            own = store.intent(own_intent)
            if own["connection_id"] != config.id or own["state"] != "submitting":
                raise ForexError("INVALID_ATTEMPT", "Close claim does not belong to this account")
        return
    own_count = 0
    if own_intent:
        own = store.intent(own_intent)
        if own["connection_id"] != config.id or own["state"] != "submitting":
            raise ForexError("INVALID_ATTEMPT", "The execution claim does not belong to this account")
        own_count = 1
    count = max(read_daily_count(config.mandate_key), store.daily_count(config.id) - own_count)
    if count >= config.limits.max_orders_per_day:
        raise ForexError("DAILY_LIMIT", "The daily submission ceiling has been reached")
    equity = number(assessment["equity"], positive=True)
    with store.db() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT equity FROM equity_peaks WHERE connection_id=?", (config.id,)).fetchone()
        peak = max(equity, number(row[0]) if row else equity)
        db.execute(
            "INSERT INTO equity_peaks VALUES(?,?) ON CONFLICT(connection_id) DO UPDATE SET equity=excluded.equity",
            (config.id, str(peak)),
        )
    if peak - equity > number(config.limits.max_equity_drawdown_usd):
        raise ForexError("DRAWDOWN_LIMIT", "Equity drawdown from the observed connection peak exceeds the ceiling")
    if config.environment != "live":
        return
    mandate = load_mandate(config.mandate_key)
    if mandate is None or mandate.schema_version != MANDATE_SCHEMA_VERSION:
        raise ForexError(
            "MANDATE_REQUIRED", "Commit a mandate for " + config.mandate_key + " through the trusted operator UI"
        )
    if mandate.consent.broker != config.mandate_key or mandate.consent.account_ref != config.account_ref:
        raise ForexError("ACCOUNT_MISMATCH", "Live consent is bound to another account")
    expiry = datetime.fromisoformat(mandate.consent.expires_at.replace("Z", "+00:00"))
    if expiry.tzinfo is None or expiry <= utcnow():
        raise ForexError("MANDATE_EXPIRED", "The live mandate has expired")
    kind = InstrumentType.FOREX if assessment["instrument_type"] == "forex" else InstrumentType.CFD
    intent = OrderIntent(
        symbol=order.symbol.upper(),
        side=order.side,
        notional_usd=float(assessment["notional_usd"]),
        quantity=float(order.quantity),
        instrument_type=kind,
        asset_class=AssetClass.FOREX if kind == InstrumentType.FOREX else None,
    )
    gross = number(assessment["position_exposure_usd"])
    positions = [{"symbol": "__EXISTING_GROSS__", "market_value": float(gross), "side": "long"}] if gross else []
    breach = check_mandate(
        mandate,
        intent,
        positions,
        {"equity": float(equity)},
        broker=config.mandate_key,
        remote_tool="forex_submit_intent",
        daily_count=count,
    )
    if breach is not None:
        raise ForexError("MANDATE_LIMIT", "Live mandate rejected the order: " + breach.limit)
    if gross + number(assessment["notional_usd"]) > equity * number(mandate.hard_caps.max_leverage):
        raise ForexError("LEVERAGE_LIMIT", "Gross exposure exceeds leverage against current account equity")
    return mandate
