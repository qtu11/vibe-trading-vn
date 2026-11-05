from contextlib import contextmanager
import json

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption

from src.trading.forex.adapters.exness import Exness
from src.trading.forex.adapters.oanda import Oanda
from src.trading.forex.models import Connection, Order, utcnow
from datetime import timedelta
from src.trading.forex.errors import ForexError


def test_exness_discovery_empty_get_header_and_ack_not_fill():
    key = Ed25519PrivateKey.generate()
    cfg = Connection(
        id="exness",
        label="Exness",
        connector="exness",
        account_ref="123456",
        environment="live",
        gateway_url="https://gateway.exness.com",
        allowed_hosts=("gateway.exness.com", "ap-fixture.exness.com"),
    )
    calls = []

    def respond(req):
        calls.append(req)
        assert "EXN-IDEMPOTENCY-KEY" in req.headers
        if req.method == "GET":
            assert req.headers["EXN-IDEMPOTENCY-KEY"] == ""
        if req.url.path == "/v1/trading/access-point":
            return httpx.Response(200, json={"account_id": "123456", "access_point": "https://ap-fixture.exness.com"})
        if req.url.path.endswith("/limits"):
            return httpx.Response(
                200,
                json={
                    "limits": {
                        "rest": {
                            "global_account_rate": {"limit": 1000, "window_seconds": 1},
                            "methods": [
                                {
                                    "path": "/v1/trading/accounts/{account_id}/positions",
                                    "http_method": "POST",
                                    "rate_limit": {"limit": 1000, "window_seconds": 1},
                                }
                            ],
                        }
                    }
                },
            )
        if req.method == "POST":
            assert req.headers["EXN-IDEMPOTENCY-KEY"] == "fixture-123"
            assert json.loads(req.content)["stop_loss_price"] == "1.05"
            return httpx.Response(
                200, json={"status": "accepted", "operation_id": "321", "client_request_id": "fixture-123"}
            )
        if "/operations/" in req.url.path:
            return httpx.Response(
                200, json={"status": "confirmed", "operation_id": "321", "client_request_id": "fixture-123"}
            )
        if req.url.path.endswith("/conditions"):
            return httpx.Response(200, json={"instrument": "EURUSD", "point_digits": 5, "trade_mode": "full"})
        raise AssertionError(req.url.path)

    class Socket:
        def send(self, data):
            assert json.loads(data)["subscribe"]["event"] == "ticks"

        def recv(self, **_):
            return json.dumps({"instrument": "EURUSD", "bid": 1.08, "ask": 1.0801, "timestamp": utcnow().isoformat()})

    @contextmanager
    def socket(*args, **kwargs):
        assert args[0].startswith("wss://ap-fixture.exness.com/")
        assert kwargs["additional_headers"]["EXN-IDEMPOTENCY-KEY"] == ""
        yield Socket()

    client = Exness(
        cfg,
        {
            "api_key": "fixture-public",
            "private_key": key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode(),
        },
        httpx.Client(transport=httpx.MockTransport(respond)),
        socket,
    )
    assert client.quote("EURUSD")["ask"] == "1.0801"
    request = Order(
        symbol="EURUSD",
        side="buy",
        quantity="0.01",
        stop_loss="1.05",
        request_key="fixture-123",
        expires_at=utcnow() + timedelta(minutes=1),
    )
    receipt = client.submit(
        request, {"request": {"instrument": "EURUSD", "side": "buy", "volume": "0.01", "stop_loss_price": "1.05"}}
    )
    assert receipt["state"] == "accepted"
    assert client.reconcile(receipt)["state"] == "confirmed"
    assert len([r for r in calls if r.url.path == "/v1/trading/access-point"]) == 1


def test_oanda_practice_host_and_protected_payload():
    cfg = Connection(id="oanda", label="Practice", connector="oanda", account_ref="101-001")

    def respond(req):
        assert req.url.host == "api-fxpractice.oanda.com"
        path = req.url.path
        if path.endswith("/summary"):
            return httpx.Response(
                200,
                json={
                    "account": {
                        "id": "101-001",
                        "currency": "USD",
                        "NAV": "10000",
                        "balance": "10000",
                        "marginAvailable": "9000",
                        "positionValue": "0",
                    }
                },
            )
        if path.endswith("/openTrades"):
            return httpx.Response(200, json={"trades": []})
        if path.endswith("/pendingOrders"):
            return httpx.Response(200, json={"orders": []})
        if path.endswith("/instruments"):
            return httpx.Response(
                200,
                json={
                    "instruments": [
                        {
                            "name": "EUR_USD",
                            "type": "CURRENCY",
                            "displayPrecision": 5,
                            "minimumTradeSize": "1",
                            "maximumOrderUnits": "100000",
                            "tradeUnitsPrecision": 0,
                            "marginRate": "0.03",
                        }
                    ]
                },
            )
        if path.endswith("/pricing"):
            return httpx.Response(
                200,
                json={
                    "prices": [
                        {
                            "instrument": "EUR_USD",
                            "time": utcnow().isoformat(),
                            "bids": [{"price": "1.08"}],
                            "asks": [{"price": "1.0801"}],
                            "tradeable": True,
                        }
                    ]
                },
            )
        if path.endswith("/orders"):
            payload = json.loads(req.content)["order"]
            assert payload["stopLossOnFill"]["price"] == "1.05" and payload["units"] == "100"
            return httpx.Response(
                201, json={"orderFillTransaction": {"id": "2", "orderID": "1", "units": "100", "price": "1.0801"}}
            )
        raise AssertionError(path)

    client = Oanda(cfg, {"token": "fixture-not-a-real-token"}, httpx.Client(transport=httpx.MockTransport(respond)))
    order = Order(
        symbol="EUR_USD",
        side="buy",
        quantity="100",
        stop_loss="1.05",
        request_key="fixture-123",
        expires_at=utcnow() + timedelta(minutes=1),
    )
    prepared = client.prepare(order)
    assert prepared["notional_usd"] == "108.01" and prepared["quantity_unit"] == "units"
    assert client.submit(order, prepared)["state"] == "filled"


def test_oanda_lost_ack_looks_up_client_reference_without_resubmitting():
    calls = []

    def respond(req):
        calls.append(req)
        assert req.method == "GET" and req.url.path.endswith("/orders/@vfx-fixture")
        return httpx.Response(
            200,
            json={
                "order": {
                    "id": "123",
                    "state": "FILLED",
                    "instrument": "EUR_USD",
                    "clientExtensions": {"id": "vfx-fixture"},
                }
            },
        )

    cfg = Connection(id="oanda", label="Practice", connector="oanda", account_ref="101-001")
    client = Oanda(cfg, {"token": "fixture"}, httpx.Client(transport=httpx.MockTransport(respond)))
    assert client.reconcile({"state": "unknown", "client_order_id": "vfx-fixture"})["state"] == "filled"
    assert len(calls) == 1


def test_oanda_gross_exposure_counts_both_sides_of_hedged_trades(monkeypatch):
    cfg = Connection(id="oanda", label="Practice", connector="oanda", account_ref="101-001")
    client = Oanda(cfg, {"token": "fixture"})
    monkeypatch.setattr(
        client,
        "account",
        lambda: {
            "currency": "USD",
            "positions": [
                {"instrument": "EUR_USD", "currentUnits": "100"},
                {"instrument": "EUR_USD", "currentUnits": "-100"},
            ],
            "orders": [],
            "position_exposure_usd": "0",
        },
    )
    quote = {"bid": "1.08", "ask": "1.0801"}
    monkeypatch.setattr(client, "quote", lambda _: quote)
    monkeypatch.setattr(
        client,
        "instrument",
        lambda _: {
            "type": "CURRENCY",
            "minimumTradeSize": "1",
            "maximumOrderUnits": "100000",
            "tradeUnitsPrecision": 0,
            "marginRate": "0.03",
        },
    )
    monkeypatch.setattr(
        client,
        "request",
        lambda *_, **kwargs: {
            "prices": [
                {
                    "instrument": "EUR_USD",
                    "time": utcnow().isoformat(),
                    "bids": [{"price": "1.08"}],
                    "asks": [{"price": "1.0801"}],
                }
            ]
        },
    )
    order = Order(
        symbol="EUR_USD",
        side="sell",
        quantity="100",
        stop_loss="1.09",
        request_key="fixture-key",
        expires_at=utcnow() + timedelta(minutes=1),
    )
    data = client.prepare(order)
    assert data["position_exposure_usd"] == "216.02"  # zero net units is not zero gross risk
    assert data["notional_usd"] == "108.01"  # both buy and sell use the conservative ask valuation
    client.close()


def test_exness_recovery_refuses_wrong_client_correlation(monkeypatch):
    client = Exness.__new__(Exness)
    client.config = Connection(
        id="exness",
        label="Exness",
        connector="exness",
        account_ref="123456",
        environment="live",
        gateway_url="https://gateway.exness.com",
        allowed_hosts=("gateway.exness.com",),
    )
    monkeypatch.setattr(
        client,
        "call",
        lambda *_: {"operation_id": "123", "client_request_id": "some-other-intent", "status": "confirmed"},
    )
    with pytest.raises(ForexError) as exc:
        client.reconcile({"operation_id": "123", "client_order_id": "vfx-fixture"})
    assert exc.value.code == "CORRELATION_MISMATCH"


def test_exness_candle_window_reaches_latest_period(monkeypatch):
    client = Exness.__new__(Exness)
    captured = {}
    client.config = Connection(
        id="exness",
        label="Exness",
        connector="exness",
        account_ref="123456",
        environment="live",
        gateway_url="https://gateway.exness.com",
        allowed_hosts=("gateway.exness.com",),
    )

    def call(*_, **kwargs):
        captured.update(kwargs["params"])
        return {"candles": []}

    monkeypatch.setattr(client, "call", call)
    client.candles("EURUSD", "15m", 32)
    from datetime import datetime

    start = datetime.fromisoformat(captured["from"])
    latest = start + timedelta(minutes=15 * (captured["count"] - 1))
    assert timedelta(0) <= utcnow() - latest < timedelta(minutes=15)


@pytest.mark.parametrize("status", [408, 409, 500, 502])
def test_ambiguous_http_failure_is_not_a_definitive_rejection(status):
    cfg = Connection(id="oanda", label="Practice", connector="oanda", account_ref="101-001")
    client = Oanda(
        cfg, {"token": "fixture"}, httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(status)))
    )
    with pytest.raises(httpx.HTTPStatusError):
        client.request("POST", client.prefix + "/orders", json={"order": {}})


@pytest.fixture
def oanda_response():
    return {
        "account": {"id": "101-001", "currency": "USD", "NAV": "10000", "balance": "10000", "marginAvailable": "9000"},
        "trades": [],
        "orders": [],
        "instruments": [{"name": "EUR_USD", "type": "CURRENCY", "displayPrecision": 5, "minimumTradeSize": "1",
                         "maximumOrderUnits": "100000", "tradeUnitsPrecision": 0, "marginRate": "0.03"}],
        "prices": [{"instrument": "EUR_USD", "time": utcnow().isoformat(), "bids": [{"price": "1.08"}],
                    "asks": [{"price": "1.0801"}], "tradeable": True}],
    }


def oanda_fixture_client(data):
    config = Connection(id="oanda", label="Practice", connector="oanda", account_ref="101-001")
    return Oanda(config, {"token": "fixture"}, httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=data))))


@pytest.mark.parametrize("field,value,code", [
    ("bids", [], "INVALID_QUOTE"),
    ("asks", [{"price": "NaN"}], "INVALID_QUOTE"),
    ("asks", [{"price": "1.07"}], "INVALID_QUOTE"),
    ("time", "not-a-time", "QUOTE_TIME_UNKNOWN"),
    ("time", "2026-11-05T12:00:00", "QUOTE_TIME_UNKNOWN"),
    ("time", "0001-01-01T00:00:00+01:00", "QUOTE_TIME_UNKNOWN"),
])
def test_oanda_raw_quote_validation(oanda_response, field, value, code):
    oanda_response["prices"][0][field] = value
    client = oanda_fixture_client(oanda_response)
    try:
        with pytest.raises(ForexError) as exc:
            client.quote("EUR_USD")
        assert exc.value.code == code
    finally:
        client.close()


@pytest.mark.parametrize("field,value", [("displayPrecision", "5.5"), ("displayPrecision", 999999), ("marginRate", "NaN"), ("tradeUnitsPrecision", "bad")])
def test_oanda_prepare_rejects_invalid_instrument_data(oanda_response, field, value):
    oanda_response["instruments"][0][field] = value
    client = oanda_fixture_client(oanda_response)
    order = Order(symbol="EUR_USD", side="buy", quantity="100", stop_loss="1.05", request_key="fixture-123", expires_at=utcnow() + timedelta(minutes=1))
    try:
        with pytest.raises(ForexError) as exc:
            client.prepare(order)
        assert exc.value.code == "VALUATION_UNAVAILABLE"
    finally:
        client.close()


@pytest.mark.parametrize("field,value", [("trades", None), ("orders", [None]), ("account", {"id": "101-001", "currency": "USD"})])
def test_oanda_account_rejects_malformed_raw_data(oanda_response, field, value):
    oanda_response[field] = value
    client = oanda_fixture_client(oanda_response)
    try:
        with pytest.raises(ForexError) as exc:
            client.account()
        assert exc.value.code == "VALUATION_UNAVAILABLE"
    finally:
        client.close()


@pytest.fixture
def exness_client():
    client = Exness.__new__(Exness)
    client.config = Connection(id="exness", label="Exness", connector="exness", account_ref="123456", environment="live",
                               gateway_url="https://gateway.exness.com", allowed_hosts=("gateway.exness.com",))
    client.ap = "https://gateway.exness.com"
    client.key = Ed25519PrivateKey.generate()
    client.api_key = "fixture"
    return client


@pytest.mark.parametrize("tick,code", [
    ({"bid": "bad", "ask": "1.0801"}, "INVALID_QUOTE"),
    ({"bid": "1.08", "ask": "NaN"}, "INVALID_QUOTE"),
    ({"bid": "1.08"}, "INVALID_QUOTE"),
    ({"bid": "1.08", "ask": "1.07"}, "INVALID_QUOTE"),
    ({"bid": "1.08", "ask": "1.0801", "timestamp": "not-a-time"}, "QUOTE_TIME_UNKNOWN"),
    ({"bid": "1.08", "ask": "1.0801", "timestamp": "2026-11-05T12:00:00"}, "QUOTE_TIME_UNKNOWN"),
])
def test_exness_raw_tick_validation(monkeypatch, exness_client, tick, code):
    monkeypatch.setattr(exness_client, "conditions", lambda _: {"point_digits": 5, "trade_mode": "full"})
    payload = {"instrument": "EURUSD", "timestamp": utcnow().isoformat(), **tick}

    class Socket:
        def send(self, _):
            pass

        def recv(self, **_):
            return json.dumps({"tick": payload})

    @contextmanager
    def socket(*_, **__):
        yield Socket()

    exness_client.ws_factory = socket
    with pytest.raises(ForexError) as exc:
        exness_client.quote("EURUSD")
    assert exc.value.code == code


@pytest.mark.parametrize("money,positions,orders", [
    ({"balance": "100", "equity": "NaN", "used_margin": "0"}, [], []),
    ({"balance": "100", "equity": "100", "used_margin": "0"}, None, []),
    ({"balance": "100", "equity": "100", "used_margin": "0"}, [], [None]),
])
def test_exness_account_rejects_malformed_raw_data(monkeypatch, exness_client, money, positions, orders):
    data = {"account_id": "123456", "settings": {"currency": "USD", "account_status": "active", "trade_mode": "full"},
            "account_state": money, "positions": positions, "orders": orders}
    monkeypatch.setattr(exness_client, "call", lambda *_: data)
    with pytest.raises(ForexError) as exc:
        exness_client.account()
    assert exc.value.code == "VALUATION_UNAVAILABLE"


@pytest.mark.parametrize("trade,code", [
    ({"instrument": "EUR_USD", "currentUnits": "NaN"}, "EXPOSURE_UNAVAILABLE"),
    ({"currentUnits": "10"}, "EXPOSURE_UNAVAILABLE"),
    ({"instrument": "EUR_USD", "currentUnits": True}, "EXPOSURE_UNAVAILABLE"),
])
def test_oanda_prepare_rejects_malformed_open_trade(oanda_response, trade, code):
    oanda_response["trades"] = [trade]
    client = oanda_fixture_client(oanda_response)
    order = Order(symbol="EUR_USD", side="buy", quantity="100", stop_loss="1.05", request_key="fixture-123", expires_at=utcnow() + timedelta(minutes=1))
    try:
        with pytest.raises(ForexError) as exc:
            client.prepare(order)
        assert exc.value.code == code
    finally:
        client.close()


@pytest.mark.parametrize("changes,code", [
    ({"time": "not-a-time"}, "QUOTE_TIME_UNKNOWN"),
    ({"bids": []}, "INVALID_QUOTE"),
    ({"time": (utcnow() - timedelta(minutes=5)).isoformat()}, "STALE_CONVERSION"),
])
def test_oanda_prepare_validates_separate_position_pricing(oanda_response, changes, code):
    oanda_response["trades"] = [{"instrument": "EUR_USD", "currentUnits": "10"}]
    config = Connection(id="oanda", label="Practice", connector="oanda", account_ref="101-001")

    def respond(req):
        if req.url.params.get("includeHomeConversions") == "true":
            return httpx.Response(200, json={"prices": [{**oanda_response["prices"][0], **changes}]})
        return httpx.Response(200, json=oanda_response)

    client = Oanda(config, {"token": "fixture"}, httpx.Client(transport=httpx.MockTransport(respond)))
    order = Order(symbol="EUR_USD", side="buy", quantity="100", stop_loss="1.05", request_key="fixture-123", expires_at=utcnow() + timedelta(minutes=1))
    try:
        with pytest.raises(ForexError) as exc:
            client.prepare(order)
        assert exc.value.code == code
    finally:
        client.close()


@pytest.mark.parametrize("conversion", [None, [None], [{"currency": "JPY", "accountGain": "bad", "accountLoss": "0.006"}]])
def test_oanda_prepare_rejects_malformed_home_conversion(oanda_response, conversion):
    oanda_response["instruments"][0]["name"] = "USD_JPY"
    oanda_response["prices"][0]["instrument"] = "USD_JPY"
    oanda_response["homeConversions"] = conversion
    client = oanda_fixture_client(oanda_response)
    order = Order(symbol="USD_JPY", side="buy", quantity="100", stop_loss="1.05", request_key="fixture-123", expires_at=utcnow() + timedelta(minutes=1))
    try:
        with pytest.raises(ForexError) as exc:
            client.prepare(order)
        assert exc.value.code == "CONVERSION_UNAVAILABLE"
    finally:
        client.close()


@pytest.fixture
def exness_prepare_data(monkeypatch, exness_client):
    data = {
        "account_id": "123456",
        "settings": {"currency": "USD", "account_status": "active", "trade_mode": "full"},
        "account_state": {"balance": "10000", "equity": "10000", "used_margin": "0"},
        "positions": [], "orders": [],
        "contract_size": "100000", "volume_min": "0.01", "volume_max": "100", "volume_step": "0.01",
        "margin_percent": "1", "quote_currency": "USD", "category": "forex", "exec_mode": "market",
        "point_digits": 5, "trade_mode": "full",
        "position_time": utcnow().isoformat(),
    }

    def call(_, path):
        if path.endswith("/conditions"):
            return {**data, "instrument": path.split("/")[-2]}
        return data

    class Socket:
        def send(self, raw):
            self.symbol = json.loads(raw)["subscribe"]["instruments"][0]

        def recv(self, **_):
            return json.dumps({"instrument": self.symbol, "bid": "1.08", "ask": "1.0801",
                               "timestamp": utcnow().isoformat() if self.symbol == "EURUSD" else data["position_time"]})

    @contextmanager
    def socket(*_, **__):
        yield Socket()

    monkeypatch.setattr(exness_client, "call", call)
    exness_client.ws_factory = socket
    return data


@pytest.mark.parametrize("field,value", [("contract_size", "NaN"), ("contract_size", True), ("margin_percent", "bad"), ("volume_step", 0), ("point_digits", 1000000)])
def test_exness_prepare_rejects_invalid_raw_instrument(exness_client, exness_prepare_data, field, value):
    exness_prepare_data[field] = value
    order = Order(symbol="EURUSD", side="buy", quantity="0.01", stop_loss="1.05", request_key="fixture-123", expires_at=utcnow() + timedelta(minutes=1))
    with pytest.raises(ForexError) as exc:
        exness_client.prepare(order)
    assert exc.value.code == "VALUATION_UNAVAILABLE"


@pytest.mark.parametrize("changes,code", [
    ({"positions": [{"instrument": "XAUUSD", "volume": "bad"}]}, "EXPOSURE_UNAVAILABLE"),
    ({"positions": [{"volume": "0.01"}]}, "EXPOSURE_UNAVAILABLE"),
    ({"positions": [{"instrument": "XAUUSD", "volume": "0.01"}], "position_time": "not-a-time"}, "QUOTE_TIME_UNKNOWN"),
    ({"positions": [{"instrument": "XAUUSD", "volume": "0.01"}], "position_time": (utcnow() - timedelta(minutes=5)).isoformat()}, "STALE_CONVERSION"),
])
def test_exness_prepare_validates_existing_positions(exness_client, exness_prepare_data, changes, code):
    exness_prepare_data.update(changes)
    order = Order(symbol="EURUSD", side="buy", quantity="0.01", stop_loss="1.05", request_key="fixture-123", expires_at=utcnow() + timedelta(minutes=1))
    with pytest.raises(ForexError) as exc:
        exness_client.prepare(order)
    assert exc.value.code == code


def test_exness_prepare_values_fresh_positions(exness_client, exness_prepare_data):
    exness_prepare_data["positions"] = [{"instrument": "XAUUSD", "volume": "0.01"}]
    order = Order(symbol="EURUSD", side="buy", quantity="0.01", stop_loss="1.05", request_key="fixture-123", expires_at=utcnow() + timedelta(minutes=1))
    assessment = exness_client.prepare(order)
    assert assessment["position_exposure_usd"] == "1080.1"
    assert assessment["notional_usd"] == "1080.1"


@pytest.mark.parametrize("connector", ["oanda", "exness"])
def test_prepare_rejects_derived_valuation_outside_bounds(connector, oanda_response, exness_client, exness_prepare_data):
    symbol = "EUR_USD" if connector == "oanda" else "EURUSD"
    order = Order(symbol=symbol, side="buy", quantity="1000000000000000000", stop_loss="1.05", request_key="fixture-123", expires_at=utcnow() + timedelta(minutes=1))
    oanda_response["prices"][0]["asks"][0]["price"] = "1000000000000000000"
    client = oanda_fixture_client(oanda_response) if connector == "oanda" else exness_client
    try:
        with pytest.raises(ForexError) as exc:
            client.prepare(order)
        assert exc.value.code == "VALUATION_UNAVAILABLE"
    finally:
        if connector == "oanda":
            client.close()
