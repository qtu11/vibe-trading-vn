from datetime import timedelta
from types import SimpleNamespace

import pytest

from src.live.mandate.model import Mandate, HardCaps, UniverseConstraint, ConsentMeta, InstrumentType, AssetClass
from src.trading.forex.models import Connection, Limits, Order, utcnow
from src.trading.forex.store import Store
from src.trading.forex.service import ForexService
from src.trading.forex.errors import ForexError


class Vault:
    def load(self, *_):
        return {"token": "fixture-not-a-credential"}


class Broker:
    def __init__(self, cfg):
        self.cfg, self.calls, self.failure, self.response = cfg, 0, None, {"state": "filled", "order_id": "123"}
        self.override = {}

    def close(self):
        pass

    def prepare(self, order):
        return {
            "account_ref": self.cfg.account_ref,
            "environment": self.cfg.environment,
            "currency": "USD",
            "trade_allowed": True,
            "equity": "10000",
            "free_margin": "9000",
            "position_exposure_usd": "0",
            "pending_orders_count": 0,
            "instrument_type": "forex",
            "min_quantity": "1",
            "max_quantity": "100000",
            "quantity_step": "1",
            "quote": {
                "bid": "1.08000",
                "ask": "1.08010",
                "point": "0.00001",
                "timestamp": utcnow().isoformat(),
                "tradeable": True,
            },
            "notional_usd": "108.01",
            "stop_risk_usd": "3.01",
            "estimated_margin": "4",
            **self.override,
        }

    def submit(self, *_):
        self.calls += 1
        if self.failure:
            raise self.failure
        return self.response

    def reconcile(self, receipt):
        return {**receipt, "state": "confirmed"}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBE_TRADING_HOME", str(tmp_path))
    cfg = Connection(
        id="demo",
        label="Demo",
        connector="oanda",
        account_ref="101-001",
        execution_enabled=True,
        symbols=("EUR_USD",),
        limits=Limits(max_quantity="1000"),
    )
    store = Store(tmp_path / "forex" / "execution.db")
    store.save_connection(cfg)
    broker = Broker(cfg)
    svc = ForexService(store, Vault(), lambda *_: broker)
    order = Order(
        symbol="EUR_USD",
        side="buy",
        quantity="100",
        stop_loss="1.05",
        request_key="case-1",
        expires_at=utcnow() + timedelta(minutes=2),
    )
    return SimpleNamespace(cfg=cfg, store=store, broker=broker, service=svc, order=order)


def test_submit_once_and_receipt_is_persistent(setup):
    s = setup
    row = s.service.create_intent(s.cfg.id, s.order)
    assert s.service.submit(s.cfg.id, row["id"])["state"] == "filled"
    assert s.service.submit(s.cfg.id, row["id"])["state"] == "filled"
    assert s.broker.calls == 1
    assert Store(s.store.path).intent(row["id"])["result"]["order_id"] == "123"


def test_late_broker_read_is_discarded_when_connection_changes(setup):
    s = setup

    def quote(**_):
        s.store.save_connection(s.cfg.model_copy(update={"account_ref": "101-002"}))
        return {"bid": "1.08", "ask": "1.0801"}

    s.broker.quote = quote
    with pytest.raises(ForexError) as exc:
        s.service.read(s.cfg.id, "quote", symbol="EUR_USD")
    assert exc.value.code == "BINDING_CHANGED"


@pytest.mark.parametrize(
    "change,code",
    [
        ({"account_ref": "another"}, "ACCOUNT_MISMATCH"),
        ({"currency": "EUR"}, "UNSUPPORTED_ACCOUNT_CURRENCY"),
        ({"pending_orders_count": 1}, "PENDING_ORDERS"),
        ({"stop_risk_usd": "100"}, "STOP_RISK_LIMIT"),
        ({"trade_allowed": False}, "TRADING_DISABLED"),
        ({"position_exposure_usd": "2999"}, "EXPOSURE_LIMIT"),
    ],
)
def test_preflight_blocks_before_send(setup, change, code):
    s = setup
    s.broker.override = change
    row = s.service.create_intent(s.cfg.id, s.order)
    with pytest.raises(ForexError) as exc:
        s.service.submit(s.cfg.id, row["id"])
    assert exc.value.code == code
    assert s.broker.calls == 0 and s.store.intent(row["id"])["state"] == "prepared"


def test_unknown_survives_restart_and_repeat_never_resends(setup):
    s = setup
    s.broker.failure = TimeoutError("no receipt")
    row = s.service.create_intent(s.cfg.id, s.order)
    assert s.service.submit(s.cfg.id, row["id"])["state"] == "unknown"
    assert s.service.submit(s.cfg.id, row["id"])["state"] == "unknown"
    assert s.broker.calls == 1 and s.service.connections()[0]["halted"]


def test_ack_is_not_a_fill_and_can_be_reconciled(setup):
    s = setup
    s.broker.response = {"state": "accepted", "operation_id": "op1"}
    row = s.service.create_intent(s.cfg.id, s.order)
    assert s.service.submit(s.cfg.id, row["id"])["state"] == "accepted"
    assert s.service.execution(s.cfg.id, row["id"], reconcile=True)["state"] == "confirmed"
    assert s.broker.calls == 1


def test_store_failure_after_send_retains_barrier(setup, monkeypatch):
    s = setup
    row = s.service.create_intent(s.cfg.id, s.order)
    monkeypatch.setattr(s.store, "finish", lambda *_: (_ for _ in ()).throw(OSError("disk unavailable")))
    with pytest.raises(ForexError, match="may have completed"):
        s.service.submit(s.cfg.id, row["id"])
    assert s.store.intent(row["id"])["state"] == "submitting"
    assert s.service.submit(s.cfg.id, row["id"])["state"] == "submitting"
    assert s.broker.calls == 1


def test_changed_binding_and_other_connection_do_not_send(setup):
    s = setup
    row = s.service.create_intent(s.cfg.id, s.order)
    with pytest.raises(ForexError, match="execution history"):
        s.store.save_connection(s.cfg.model_copy(update={"account_ref": "101-002"}))
    s.store.save_connection(s.cfg.model_copy(update={"label": "Updated settings"}))
    with pytest.raises(ForexError, match="changed"):
        s.service.submit(s.cfg.id, row["id"])
    with pytest.raises(ForexError, match="another connection"):
        s.service.submit("other", row["id"])
    assert not s.broker.calls


def test_live_requires_consent_bound_to_exact_account(setup, monkeypatch):
    s = setup
    cfg = s.cfg.model_copy(update={"environment": "live"})
    s.store.save_connection(cfg)
    s.broker.cfg = cfg
    row = s.service.create_intent(cfg.id, s.order)
    with pytest.raises(ForexError) as exc:
        s.service.submit(cfg.id, row["id"])
    assert exc.value.code == "MANDATE_REQUIRED" and not s.broker.calls
    mandate = Mandate(
        1,
        HardCaps(10000, 1000, 3000, 2, (InstrumentType.FOREX,), 5),
        UniverseConstraint((AssetClass.FOREX,), None, None, ()),
        ConsentMeta(
            utcnow().isoformat(), "fixture", cfg.mandate_key, "different", (utcnow() + timedelta(days=1)).isoformat()
        ),
    )
    monkeypatch.setattr("src.trading.forex.policy.load_mandate", lambda *_: mandate)
    with pytest.raises(ForexError) as exc:
        s.service.submit(cfg.id, row["id"])
    assert exc.value.code == "ACCOUNT_MISMATCH"
    from dataclasses import replace

    mandate = replace(mandate, consent=replace(mandate.consent, account_ref=cfg.account_ref))
    result = s.service.submit(cfg.id, row["id"])
    assert result["state"] == "filled" and result["result"]["audit_id"]
    import json
    from src.live.audit import audit_ledger_path

    records = [json.loads(line) for line in audit_ledger_path().read_text(encoding="utf-8").splitlines()]
    assert records[-1]["server"] == cfg.mandate_key and records[-1]["outcome"] == "filled"
    assert "fixture-not-a-credential" not in json.dumps(records)


def test_pending_claim_keeps_broker_correlation_after_crash(setup, monkeypatch):
    s = setup
    row = s.service.create_intent(s.cfg.id, s.order)
    monkeypatch.setattr(s.store, "finish", lambda *_: (_ for _ in ()).throw(OSError("disk unavailable")))
    with pytest.raises(ForexError):
        s.service.submit(s.cfg.id, row["id"])
    saved = Store(s.store.path).intent(row["id"])
    assert saved["binding"]["account_ref"] == s.cfg.account_ref
    assert saved["result"]["client_order_id"].startswith("vfx-")
    assert saved["result"]["symbol"] == s.order.symbol and saved["result"]["submitted_at"]


def test_halt_between_claim_and_send_is_rechecked(setup, monkeypatch):
    from src.live.halt import trip_halt

    s = setup
    row = s.service.create_intent(s.cfg.id, s.order)
    original = s.store.claim

    def claim(identifier):
        value = original(identifier)
        trip_halt("file", "Test race", broker=s.cfg.connector)
        return value

    monkeypatch.setattr(s.store, "claim", claim)
    result = s.service.submit(s.cfg.id, row["id"])
    assert result["state"] == "rejected" and result["result"]["code"] == "HALTED"
    assert not s.broker.calls


@pytest.mark.parametrize(
    "field,value,code",
    [
        (
            "quote",
            {
                "bid": "1.08",
                "ask": "1.0801",
                "point": "0.00001",
                "timestamp": (utcnow() - timedelta(minutes=2)).isoformat(),
                "tradeable": True,
            },
            "STALE_QUOTE",
        ),
        ("notional_usd", "1001", "NOTIONAL_LIMIT"),
        ("free_margin", "1", "INSUFFICIENT_MARGIN"),
        ("equity", "30", "LEVERAGE_LIMIT"),
        ("quantity_step", "2", "INVALID_VOLUME_STEP"),
    ],
)
def test_additional_limits_are_enforced_before_send(setup, field, value, code):
    s = setup
    s.broker.override = {field: value}
    row = s.service.create_intent(s.cfg.id, s.order)
    with pytest.raises(ForexError) as exc:
        s.service.submit(s.cfg.id, row["id"])
    assert exc.value.code == code and not s.broker.calls


@pytest.mark.parametrize(
    "quote,code",
    [
        (None, "INVALID_QUOTE"),
        ([], "INVALID_QUOTE"),
        ({}, "QUOTE_TIME_UNKNOWN"),
        ({"timestamp": "not-a-time"}, "QUOTE_TIME_UNKNOWN"),
        ({"timestamp": "2026-11-05T12:00:00"}, "QUOTE_TIME_UNKNOWN"),
        ({"timestamp": "0001-01-01T00:00:00+01:00"}, "QUOTE_TIME_UNKNOWN"),
        ({"bid": "1.08", "ask": "NaN", "point": "0.00001"}, "INVALID_QUOTE"),
        ({"bid": "1.08", "ask": "1.0801"}, "INVALID_QUOTE"),
        ({"bid": True, "ask": "1.0801", "point": "0.00001"}, "INVALID_QUOTE"),
        ({"bid": "1.08", "ask": "1.0801", "point": "0"}, "INVALID_QUOTE"),
    ],
)
def test_malformed_broker_quote_is_a_structured_preflight_rejection(setup, quote, code):
    s = setup
    if isinstance(quote, dict) and "bid" in quote:
        quote = {"timestamp": utcnow().isoformat(), "tradeable": True, **quote}
    s.broker.override = {"quote": quote}
    row = s.service.create_intent(s.cfg.id, s.order)

    with pytest.raises(ForexError) as exc:
        s.service.submit(s.cfg.id, row["id"])

    assert exc.value.code == code
    assert s.broker.calls == 0
    assert s.store.intent(row["id"])["state"] == "prepared"


def test_daily_cap_and_observed_drawdown_persist(setup):
    s = setup
    s.store.save_connection(
        s.cfg.model_copy(update={"limits": s.cfg.limits.model_copy(update={"max_orders_per_day": 1})})
    )
    row = s.service.create_intent(s.cfg.id, s.order)
    s.service.submit(s.cfg.id, row["id"])
    second = s.service.create_intent(s.cfg.id, s.order.model_copy(update={"request_key": "case-2"}))
    with pytest.raises(ForexError) as exc:
        s.service.submit(s.cfg.id, second["id"])
    assert exc.value.code == "DAILY_LIMIT" and s.broker.calls == 1
    cfg = s.store.connection(s.cfg.id)
    s.store.save_connection(cfg.model_copy(update={"limits": cfg.limits.model_copy(update={"max_orders_per_day": 3})}))
    third = s.service.create_intent(s.cfg.id, s.order.model_copy(update={"request_key": "case-3"}))
    s.broker.override = {"equity": "9949"}
    with pytest.raises(ForexError) as exc:
        s.service.submit(s.cfg.id, third["id"])
    assert exc.value.code == "DRAWDOWN_LIMIT" and s.broker.calls == 1


def test_exness_lost_ack_recovery_requires_broker_proven_reference(setup, monkeypatch):
    from src.trading.forex.adapters.exness import Exness

    s = setup
    cfg = Connection(
        id="exness",
        label="Exness",
        connector="exness",
        account_ref="123456",
        environment="live",
        gateway_url="https://gateway.exness.com",
        allowed_hosts=("gateway.exness.com",),
        symbols=("EURUSD",),
    )
    s.store.save_connection(cfg)
    row = s.store.create_intent(cfg, s.order.model_copy(update={"symbol": "EURUSD"}))
    s.store.claim(row["id"])
    context = s.store.intent(row["id"])["result"]
    s.store.finish(row["id"], "unknown", context)
    client = Exness.__new__(Exness)
    client.config = cfg
    monkeypatch.setattr(
        client,
        "call",
        lambda method, path: {
            "status": "confirmed",
            "client_request_id": context["client_order_id"] if path.endswith("/correct-op") else "wrong-intent",
        },
    )
    service = ForexService(s.store, Vault(), lambda *_: client)
    with pytest.raises(ForexError) as exc:
        service.recover_exness_reference(cfg.id, row["id"], "wrong-op")
    assert exc.value.code == "CORRELATION_MISMATCH" and s.store.intent(row["id"])["state"] == "unknown"
    assert service.recover_exness_reference(cfg.id, row["id"], "correct-op")["state"] == "confirmed"
