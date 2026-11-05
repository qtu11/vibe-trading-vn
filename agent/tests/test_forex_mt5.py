"""Native SDK behavior with a fake broker; never attaches to a real terminal."""

from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.trading.forex.adapters.mt5 import MT5
from src.trading.forex.adapters.mt5_worker import Native
from src.trading.forex.errors import ForexError
from src.trading.forex.models import Connection, Order, broker_reference, utcnow


@pytest.fixture
def native():
    config = Connection(
        id="mt5-fixture",
        label="MT5",
        connector="mt5",
        account_ref="12345",
        server="Fixture-Demo",
        terminal_path=r"C:\Fixture\terminal64.exe",
        symbols=("EURUSDm",),
        execution_enabled=True,
    )
    sdk = SimpleNamespace(
        ACCOUNT_TRADE_MODE_DEMO=0,
        ACCOUNT_TRADE_MODE_REAL=2,
        TRADE_RETCODE_DONE=10009,
        ORDER_STATE_FILLED=4,
        ORDER_STATE_CANCELED=2,
        ORDER_STATE_REJECTED=5,
        ORDER_STATE_EXPIRED=6,
    )
    sdk.account = SimpleNamespace(login=12345, server="Fixture-Demo", trade_mode=0)
    sdk.account_info = lambda: sdk.account
    client = Native(sdk, config, None)
    return client, sdk, config


def test_mt5_account_server_and_demo_identity_are_rechecked(native):
    client, sdk, _ = native
    assert client.identity().login == 12345
    for field, value, code in [
        ("server", "Different", "ACCOUNT_MISMATCH"),
        ("login", 99999, "ACCOUNT_MISMATCH"),
        ("trade_mode", 2, "ENVIRONMENT_MISMATCH"),
    ]:
        old = getattr(sdk.account, field)
        setattr(sdk.account, field, value)
        with pytest.raises(ForexError) as exc:
            client.identity()
        assert exc.value.code == code
        setattr(sdk.account, field, old)


@pytest.mark.parametrize(
    "retcode,state",
    [
        (10009, "filled"),
        (10010, "partial"),
        (10008, "working"),
        (10012, "unknown"),
        (10031, "unknown"),
        (10016, "rejected"),
    ],
)
def test_mt5_single_send_protection_and_receipt_states(native, monkeypatch, retcode, state):
    client, sdk, cfg = native
    calls = []
    order = Order(
        symbol="EURUSDm",
        side="buy",
        quantity="0.01",
        stop_loss="1.079",
        request_key="fixture-key",
        expires_at=utcnow() + timedelta(minutes=1),
    )
    data = {
        "account_ref": cfg.account_ref,
        "environment": "demo",
        "currency": "USD",
        "trade_allowed": True,
        "pending_orders_count": 0,
        "quote": {
            "bid": "1.08",
            "ask": "1.0801",
            "point": "0.00001",
            "tradeable": True,
            "timestamp": utcnow().isoformat(),
        },
        "min_quantity": "0.01",
        "max_quantity": "100",
        "quantity_step": "0.01",
        "notional_usd": "1000",
        "stop_risk_usd": "1.1",
        "estimated_margin": "10",
        "position_exposure_usd": "0",
        "equity": "10000",
        "free_margin": "9000",
        "request": {"sl": 1.079, "deviation": 20},
    }
    monkeypatch.setattr(client, "prepare", lambda _: data)
    monkeypatch.setattr(
        "src.trading.forex.policy.authorize", lambda *_, **kwargs: calls.append(("authorize", kwargs["own_intent"]))
    )
    sdk.order_check = lambda req: SimpleNamespace(retcode=0)

    def send(req):
        calls.append(("send", dict(req)))
        return SimpleNamespace(retcode=retcode, order=123, deal=456, volume=0.01, price=1.0801)

    sdk.order_send = send
    result = client.submit(order, "fx_fixture")
    assert result["state"] == state
    assert calls[0] == ("authorize", "fx_fixture")
    assert [row[0] for row in calls].count("send") == 1
    assert calls[-1][1]["sl"] == 1.079 and calls[-1][1]["comment"] == broker_reference("fx_fixture")


def test_mt5_unknown_can_reconcile_only_unique_broker_history_tag(native):
    client, sdk, _ = native
    tag = broker_reference("fx_fixture")
    row = SimpleNamespace(ticket=123, comment=tag, magic=2601103, symbol="EURUSDm", state=sdk.ORDER_STATE_FILLED)
    sdk.orders_get = lambda **_: ()
    sdk.history_orders_get = lambda *args, **kwargs: (row,)
    receipt = {"state": "unknown", "client_order_id": tag, "symbol": "EURUSDm", "submitted_at": utcnow().isoformat()}
    result = client.reconcile(receipt)
    assert result["state"] == "filled" and result["order_id"] == "123"
    row.comment = "unrelated"
    assert client.reconcile(receipt)["state"] == "unknown"


def test_mt5_fresh_suffix_bound_usd_conversions_are_conservative(native, monkeypatch):
    client, sdk, _ = native
    symbols = {
        name: SimpleNamespace(name=name, currency_base=base, currency_profit=profit, trade_contract_size=100000)
        for name, base, profit in [("EURUSDm", "EUR", "USD"), ("EURJPYm", "EUR", "JPY"), ("USDJPYm", "USD", "JPY")]
    }
    monkeypatch.setattr(client, "instrument", lambda name: symbols[name])
    sdk.symbol_info = lambda name: symbols.get(name)
    stamp = utcnow().isoformat()
    monkeypatch.setattr(client, "quote", lambda name: {"bid": "1.08", "ask": "1.0801", "timestamp": stamp})
    assert client.usd_notional("EURUSDm", "0.01") == Decimal("1080.1")
    assert client.usd_notional("EURJPYm", "0.01") == Decimal("1080.1")
    assert client.usd_notional("USDJPYm", "0.01") == Decimal("1000")
    stamp = (utcnow() - timedelta(minutes=2)).isoformat()
    with pytest.raises(ForexError, match="fresh MT5 quote"):
        client.usd_notional("EURJPYm", "0.01")


def test_mt5_worker_does_not_put_credentials_in_process_arguments(native, monkeypatch):
    _, _, cfg = native
    captured = {}

    def run(args, **kwargs):
        captured.update(args=args, **kwargs)
        return SimpleNamespace(stdout='{"status":"ok","data":{"account_ref":"12345"}}')

    monkeypatch.setattr("src.trading.forex.adapters.mt5.subprocess.run", run)
    adapter = MT5(cfg, {"password": "fixture-private"})
    assert adapter.account()["account_ref"] == "12345"
    assert "fixture-private" not in str(captured["args"])
    assert "fixture-private" in captured["input"]
    assert captured["capture_output"] and captured["timeout"] == 40
