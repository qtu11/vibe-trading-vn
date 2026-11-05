"""Demo execution and AI boundary checks with synthetic market/broker fixtures."""

from contextlib import contextmanager
from datetime import timedelta
import json
import threading
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from src.trading.forex.ai import AIEngine
from src.trading.forex.adapters.mt5_worker import Native, dispatch
from src.trading.forex.errors import ForexError
from src.trading.forex.models import AIStrategy, Connection, Limits, Order, broker_reference, utcnow
from src.trading.forex.policy import authorize
from src.trading.forex.risk import check
from src.trading.forex.service import ForexService
from src.trading.forex.store import Store


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBE_TRADING_HOME", str(tmp_path))
    config = Connection(
        id="demo",
        label="Demo fixture",
        connector="mt5",
        account_ref="12345",
        server="Fixture-Demo",
        terminal_path=r"C:\Fixture\terminal64.exe",
        session_mode="existing_terminal",
        execution_enabled=True,
        symbols=("EURUSDm",),
        limits=Limits(max_order_notional_usd="2000"),
    )
    store = Store()
    store.save_connection(config)

    class Vault:
        def load(self, *_):
            pytest.fail("Existing terminal mode must not read a password from the vault")

    class Broker:
        positions = []
        calls = 0

        def close(self):
            pass

        def account(self):
            return {
                "account_ref": config.account_ref,
                "environment": "demo",
                "currency": "USD",
                "equity": "10000",
                "free_margin": "9000",
                "trade_allowed": True,
                "hedging": True,
                "positions": list(self.positions),
                "orders": [],
                "position_exposure_usd": "0",
            }

        def quote(self, **_):
            return {
                "bid": "1.0800",
                "ask": "1.0801",
                "point": "0.00001",
                "price_step": "0.00001",
                "timestamp": utcnow().isoformat(),
                "tradeable": True,
            }

        def instruments(self, **_):
            return [{"symbol": "EURUSDm", "currency_base": "EUR", "currency_profit": "USD"}]

        def candles(self, **kwargs):
            step = {"5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}[kwargs["timeframe"]]
            now = utcnow().replace(microsecond=0)
            now -= timedelta(seconds=int(now.timestamp()) % step)
            return [
                {
                    "time": (now - timedelta(seconds=step * (kwargs["limit"] - i))).isoformat(),
                    "open": "1.08",
                    "high": "1.0802",
                    "low": "1.0798",
                    "close": "1.08",
                    "volume": 10,
                    "complete": True,
                }
                for i in range(kwargs["limit"])
            ]

        def prepare(self, order):
            data = {
                **self.account(),
                "quote": self.quote(),
                "min_quantity": "0.01",
                "max_quantity": "100",
                "quantity_step": "0.01",
                "notional_usd": "1080.1",
                "stop_risk_usd": "1.1",
                "estimated_margin": "10",
                "pending_orders_count": 0,
                "instrument_type": "forex",
            }
            if order.action == "close":
                p = next((p for p in self.positions if str(p["ticket"]) == order.position_ticket), {})
                data.update(
                    position_owned=store.owns_position(config, p),
                    position_ticket=str(p.get("ticket")),
                    close_side="sell",
                    position_volume=str(p.get("volume", 0)),
                )
            return data

        def submit(self, order, prepared):
            self.calls += 1
            if order.action == "close":
                self.positions = []
                return {"state": "filled", "order_id": "222"}
            self.positions = [
                {
                    "ticket": 111,
                    "identifier": 111,
                    "symbol": "EURUSDm",
                    "type": 0,
                    "volume": 0.01,
                    "magic": 2601103,
                    "comment": broker_reference(prepared["intent_id"]),
                    "price_open": 1.0801,
                    "sl": 1.079,
                    "tp": 1.083,
                }
            ]
            return {"state": "filled", "order_id": "111"}

    broker = Broker()
    monkeypatch.setattr(
        "src.trading.forex.analysis_context.get_macro_context",
        lambda **_: {"real_yield_10y": {"status": "unavailable", "reason": "Fixture", "value": None}},
    )
    service = ForexService(store, Vault(), lambda *_: broker)
    response = {
        "action": "buy",
        "confidence": 0.9,
        "rationale": "Synthetic test decision",
        "stop_loss": "1.079",
        "take_profit": "1.083",
    }
    messages = []

    def model(request):
        messages.extend(request)
        return json.dumps(response), {"provider": "fixture", "model": "fixture-model"}

    return SimpleNamespace(
        config=config,
        store=store,
        broker=broker,
        service=service,
        response=response,
        messages=messages,
        engine=AIEngine(service, model),
        strategy=AIStrategy(symbol="EURUSDm"),
        stopped=threading.Event(),
    )


def test_analysis_is_real_model_call_with_market_only_and_never_sends(setup):
    s = setup
    result = s.engine.analyze("demo", s.strategy)
    assert result["decision"]["action"] == "buy" and result["model"]["provider"] == "fixture"
    assert not s.store.executions("demo") and s.broker.calls == 0
    payload = json.loads(s.messages[1]["content"])
    assert len(payload["bars"]) == 60 and payload["managed_position"] is None
    assert set(payload["research_context"]["timeframes"]) == {"5m", "1h", "4h", "1d"}
    assert all(v["candle_count"] == 300 for v in payload["research_context"]["timeframes"].values())
    assert result["evidence"]["medium_term_price_context_ready"]
    assert not {"account_ref", "server", "equity", "balance", "password", "ticket"} & payload.keys()

    def nested_keys(value):
        if isinstance(value, dict):
            return set(value) | set().union(*(nested_keys(v) for v in value.values()))
        if isinstance(value, list):
            return set().union(*(nested_keys(v) for v in value))
        return set()

    assert not {
        "account_ref",
        "connection_id",
        "binding_hash",
        "terminal_path",
        "server",
        "equity",
        "balance",
        "password",
        "ticket",
    } & nested_keys(payload)
    s.engine.analyze("demo", s.strategy)
    assert len(s.messages) == 2  # one model call per persisted bar/position/config


def test_short_daily_history_cannot_open_even_with_high_model_confidence(setup, monkeypatch):
    s = setup
    original = s.broker.candles
    monkeypatch.setattr(
        s.broker,
        "candles",
        lambda **kwargs: original(**kwargs)[-50:] if kwargs["timeframe"] == "1d" else original(**kwargs),
    )
    result = s.engine.tick("demo", s.strategy, s.stopped)
    assert result["code"] == "AI_CONTEXT_INCOMPLETE" and result["status"] == "blocked"
    assert s.broker.calls == 0 and not s.store.executions("demo")


@pytest.mark.parametrize(
    "change",
    [
        {"action": "close", "stop_loss": None, "take_profit": None},
        {"confidence": float("nan")},
        {"confidence": 1.2},
        {"stop_loss": "1.2"},
        {"take_profit": "1.0802"},
        {"arbitrary_tool": "order_send"},
        {"action": "flatten"},
    ],
)
def test_invalid_model_outputs_are_recorded_without_sending(setup, change):
    s = setup
    s.response.update(change)
    assert s.engine.analyze("demo", s.strategy)["code"] == "AI_INVALID_DECISION"
    assert s.broker.calls == 0 and not s.store.executions("demo")


def test_demo_ai_opens_once_then_closes_exact_managed_position(setup):
    s = setup
    assert s.engine.tick("demo", s.strategy, s.stopped)["status"] == "filled"
    assert s.broker.calls == 1 and s.store.owns_position(s.config, s.broker.positions[0])
    s.response.update(action="close", stop_loss=None, take_profit=None)
    assert s.engine.tick("demo", s.strategy, s.stopped)["status"] == "filled"
    close = s.store.executions("demo")[0]["payload"]
    assert close["action"] == "close" and close["position_ticket"] == "111" and close["side"] == "sell"
    assert not s.broker.positions and s.broker.calls == 2
    assert s.engine.tick("demo", s.strategy, s.stopped)["status"] == "decision_already_recorded"
    assert s.broker.calls == 2


def test_low_confidence_and_existing_manual_positions_do_not_open(setup):
    s = setup
    s.response["confidence"] = 0.6
    assert s.engine.tick("demo", s.strategy, s.stopped)["status"] == "hold"
    s.broker.positions = [{"ticket": 555, "volume": 0.01, "symbol": "EURUSDm", "type": 0, "magic": 0}]
    s.response["confidence"] = 0.9
    assert s.engine.tick("demo", s.strategy, s.stopped)["status"] == "waiting_for_flat_account"
    assert s.broker.calls == 0


def test_stop_while_model_is_working_prevents_a_later_send(setup):
    s = setup
    original = s.engine.model

    def model(messages):
        s.stopped.set()
        return original(messages)

    s.engine.model = model
    assert s.engine.tick("demo", s.strategy, s.stopped)["status"] == "stopped"
    assert not s.store.executions("demo") and s.broker.calls == 0


def test_stop_during_broker_valuation_prevents_submitting(setup, monkeypatch):
    s = setup
    original = s.broker.prepare

    def prepare(order):
        s.stopped.set()
        return original(order)

    monkeypatch.setattr(s.broker, "prepare", prepare)
    with pytest.raises(ForexError) as exc:
        s.engine.tick("demo", s.strategy, s.stopped)
    assert exc.value.code == "RUNNER_STOPPED" and s.broker.calls == 0
    assert not s.store.active("mt5")


def test_http_ai_start_reports_external_terminal_block_without_arming(setup):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src.api.forex_routes import register_forex_routes
    from src.api.security import require_auth, require_settings_write_auth

    s = setup
    s.broker.account = lambda: {"account_ref": "12345", "environment": "demo", "positions": [], "trade_allowed": False}
    app = FastAPI()
    register_forex_routes(app, s.service)
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[require_settings_write_auth] = lambda: None
    with TestClient(app) as client:
        response = client.post("/api/forex/connections/demo/ai/start", json=s.strategy.model_dump(mode="json"))
        assert response.status_code == 400 and response.json()["detail"]["code"] == "TRADING_DISABLED"
        assert not app.state.forex_runners.tasks


def test_discovery_attaches_exact_identity_without_enabling_execution(setup, monkeypatch):
    from src.trading.forex.discovery import attach_running

    s = setup
    monkeypatch.setattr("src.trading.forex.discovery.running_terminals", lambda: [r"C:\Other\terminal64.exe"])
    monkeypatch.setattr(
        "src.trading.forex.discovery.probe_terminal",
        lambda path: {"terminal_path": path, "account_ref": "99999", "server": "Other-Demo", "environment": "demo"},
    )
    result = attach_running(s.service)
    c = result["connections"][0]
    assert c["account_ref"] == "99999" and c["session_mode"] == "existing_terminal"
    assert not c["execution_enabled"] and c["symbols"] == []
    assert s.store.connection("demo").account_ref == "12345"  # never overwrites a different identity


def test_ai_cannot_arm_or_send_on_a_real_account(setup):
    s = setup
    s.store.save_connection(s.config.model_copy(update={"environment": "live"}))
    with pytest.raises(ForexError) as exc:
        s.engine.tick("demo", s.strategy, s.stopped)
    assert exc.value.code == "AI_DEMO_ONLY" and not s.messages and s.broker.calls == 0


def test_stale_market_data_never_reaches_the_model(setup, monkeypatch):
    s = setup
    original = s.broker.quote()
    monkeypatch.setattr(
        s.broker, "quote", lambda **_: {**original, "timestamp": (utcnow() - timedelta(minutes=5)).isoformat()}
    )
    with pytest.raises(ForexError) as exc:
        s.engine.analyze("demo", s.strategy)
    assert exc.value.code == "STALE_QUOTE" and not s.messages


def test_account_binding_change_during_model_call_discards_decision(setup):
    s = setup
    original = s.engine.model

    def model(messages):
        s.store.save_connection(s.config.model_copy(update={"account_ref": "99999"}))
        return original(messages)

    s.engine.model = model
    assert s.engine.analyze("demo", s.strategy)["code"] == "BINDING_CHANGED"
    assert s.broker.calls == 0


def test_position_ownership_cannot_be_forged_with_only_a_magic_or_comment(setup):
    s = setup
    s.engine.tick("demo", s.strategy, s.stopped)
    p = s.broker.positions[0]
    assert s.store.owns_position(s.config, p)
    for changes in (
        {"ticket": 999, "identifier": 999},
        {"comment": "vfx-manual"},
        {"magic": 0},
        {"symbol": "USDJPYm"},
        {"type": 1},
    ):
        assert not s.store.owns_position(s.config, {**p, **changes})
    assert not s.store.owns_position(s.config.model_copy(update={"account_ref": "99999"}), p)


def test_native_close_targets_position_and_does_not_turn_into_opposite_entry(setup, monkeypatch):
    s = setup
    s.engine.tick("demo", s.strategy, s.stopped)
    sdk = SimpleNamespace(
        POSITION_TYPE_BUY=0, ORDER_TYPE_BUY=0, ORDER_TYPE_SELL=1, TRADE_ACTION_DEAL=1, ORDER_TIME_GTC=0
    )
    native = Native(sdk, s.config, None)
    monkeypatch.setattr(native, "account", s.broker.account)
    monkeypatch.setattr(native, "quote", lambda _: s.broker.quote())
    monkeypatch.setattr(
        native, "instrument", lambda _: SimpleNamespace(volume_min=0.01, volume_max=100, volume_step=0.01)
    )
    monkeypatch.setattr("src.trading.forex.adapters.mt5_worker._filling_mode", lambda *_a, **_k: 0)
    order = Order(
        action="close",
        position_ticket="111",
        symbol="EURUSDm",
        side="sell",
        quantity="0.01",
        request_key="close-fixture",
        expires_at=utcnow() + timedelta(minutes=1),
    )
    data = native.prepare(order)
    assert data["request"]["position"] == 111 and data["request"]["type"] == 1
    assert "sl" not in data["request"] and "tp" not in data["request"]
    assert check(s.config, order, data)["position_owned"]
    # Entry caps can no longer prevent a proven reduction; halt still can.
    capped = s.config.model_copy(update={"limits": Limits(max_orders_per_day=1, max_equity_drawdown_usd="1")})
    s.store.save_connection(capped)
    authorize(capped, order, data, s.store)
    with pytest.raises(ForexError) as exc:
        native.prepare(order.model_copy(update={"quantity": "0.02"}))
    assert exc.value.code == "POSITION_CHANGED"
    s.broker.positions[0]["magic"] = 0
    with pytest.raises(ForexError) as exc:
        native.prepare(order)
    assert exc.value.code == "POSITION_NOT_OWNED"


def test_invalid_open_and_close_contracts_are_rejected():
    common = dict(
        symbol="EURUSDm", side="buy", quantity="0.01", request_key="fixture", expires_at=utcnow() + timedelta(minutes=1)
    )
    for extra in (
        {},
        {"action": "close"},
        {"action": "close", "position_ticket": "1", "stop_loss": "1"},
        {"position_ticket": "1", "stop_loss": "1"},
    ):
        with pytest.raises(ValidationError):
            Order(**common, **extra)


def test_existing_terminal_dispatch_never_calls_password_login(setup, monkeypatch):
    s = setup
    sdk = SimpleNamespace(
        ACCOUNT_TRADE_MODE_DEMO=0,
        ACCOUNT_TRADE_MODE_REAL=2,
        account_info=lambda: SimpleNamespace(login=12345, server="Fixture-Demo", trade_mode=0),
    )

    @contextmanager
    def session(path):
        assert path == s.config.terminal_path
        yield sdk

    monkeypatch.setattr("src.trading.forex.adapters.mt5_worker.existing_session", session)
    monkeypatch.setattr(
        "src.trading.forex.adapters.mt5_worker._client._session",
        lambda *_: pytest.fail("Must not initialize with credentials"),
    )
    monkeypatch.setattr(Native, "account", lambda _: {"account_ref": "12345"})
    assert dispatch({"config": s.config.model_dump(mode="json"), "operation": "account"})["account_ref"] == "12345"
    sdk.account_info = lambda: SimpleNamespace(login=99999, server="Fixture-Demo", trade_mode=0)
    with pytest.raises(ForexError) as exc:
        dispatch({"config": s.config.model_dump(mode="json"), "operation": "account"})
    assert exc.value.code == "ACCOUNT_MISMATCH"
