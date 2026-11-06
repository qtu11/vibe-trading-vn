from datetime import timedelta
import os
from pathlib import Path
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.forex_routes import register_forex_routes
from src.api.security import require_auth, require_settings_write_auth
from src.trading.forex.mcp_server import build_server
from src.trading.forex.models import Connection
from src.trading.forex.service import ForexService
from src.trading.forex.store import Store


class Vault:
    def load(self, *_):
        return {}

    def save(self, *_):
        pass


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBE_TRADING_HOME", str(tmp_path))
    store = Store(tmp_path / "forex" / "execution.db")
    store.save_connection(Connection(id="practice", label="Practice", connector="oanda", account_ref="101-001"))
    return ForexService(store, Vault())


@pytest.mark.asyncio
async def test_mcp_default_schema_and_structured_missing_credentials(service):
    server = build_server(service, "practice")
    tools = await server.list_tools()
    names = {tool.name for tool in tools}
    assert "forex_get_quote" in names and "forex_submit_intent" not in names
    assert all(tool.annotations.readOnlyHint for tool in tools)
    from fastmcp import Client

    async with Client(server) as client:
        result = await client.call_tool("forex_get_quote", {"symbol": "EUR_USD"})
    assert result.data["code"] == "CREDENTIALS_UNAVAILABLE"


@pytest.mark.asyncio
async def test_mcp_detects_changed_connection_binding(service):
    from fastmcp import Client

    server = build_server(service, "practice")
    config = service.store.connection("practice")
    service.store.save_connection(config.model_copy(update={"account_ref": "101-002"}))
    async with Client(server) as client:
        result = await client.call_tool("forex_get_account", {})
    assert result.data["code"] == "BINDING_CHANGED"


@pytest.mark.asyncio
@pytest.mark.parametrize("execution", [False, True])
async def test_actual_stdio_handshake_and_account_bound_schema(tmp_path, monkeypatch, execution):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from src.trading.forex.models import Order, utcnow

    monkeypatch.setenv("VIBE_TRADING_HOME", str(tmp_path))
    store = Store()
    store.save_connection(
        Connection(
            id="stdio-fixture",
            label="Fixture",
            connector="oanda",
            account_ref="101-000-fixture",
            execution_enabled=True,
            symbols=("EUR_USD",),
        )
    )
    args = [str(Path(__file__).parents[1] / "forex_mcp_server.py"), "--connection-id", "stdio-fixture"]
    if execution:
        args.append("--allow-execution")
    params = StdioServerParameters(command=sys.executable, args=args, env={**os.environ, "PYTHONUTF8": "1"})
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as client:
            await client.initialize()
            tools = (await client.list_tools()).tools
            names = {tool.name for tool in tools}
            assert len(names) == (17 if execution else 14)
            assert ("forex_submit_intent" in names) == execution
            assert all(
                "api_key" not in str(tool.inputSchema) and "password" not in str(tool.inputSchema) for tool in tools
            )
            if execution:
                order = Order(
                    symbol="EUR_USD",
                    side="buy",
                    quantity="1",
                    stop_loss="1.05",
                    request_key="stdio-fixture-key",
                    expires_at=utcnow() + timedelta(minutes=1),
                )
                result = await client.call_tool("forex_create_intent", {"order": order.model_dump(mode="json")})
                assert not result.isError
                assert store.executions("stdio-fixture")[0]["state"] == "prepared"


def test_http_routes_auth_config_and_halt_resume(service):
    app = FastAPI()
    register_forex_routes(app, service)
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[require_settings_write_auth] = lambda: None
    with TestClient(app) as client:
        assert client.get("/api/forex/connections").json()["connections"][0]["id"] == "practice"
        mcp = client.get("/api/forex/connections/practice/mcp-config").json()["mcpServers"]["forex-practice"]
        assert mcp["command"] == sys.executable and mcp["args"][-1] == "practice"
        assert "--allow-execution" not in mcp["args"]
        payload = client.get("/api/forex/connections").json()["connections"][0]
        assert "token" not in str(payload)
        assert client.post("/api/forex/connections/practice/halt").status_code == 200
        assert client.get("/api/forex/connections").json()["connections"][0]["halted"]
        assert client.post("/api/forex/connections/practice/resume").status_code == 200
        assert not client.get("/api/forex/connections").json()["connections"][0]["halted"]
        response = client.post("/api/forex/connections/practice/credentials", json={"private_key": "fixture-secret"})
        assert response.status_code == 400 and "fixture-secret" not in response.text
        assert client.post("/api/forex/connections/practice/verify").status_code == 400
        assert (
            client.post(
                "/api/forex/connections/practice/runner/start", json={"symbol": "EUR_USD", "quantity": "1"}
            ).status_code
            == 400
        )


def test_forex_http_requires_auth_and_rejects_cross_site_writes(service, monkeypatch):
    monkeypatch.setattr("src.api.security._configured_api_key", lambda: "fixture-app-key")
    app = FastAPI()
    register_forex_routes(app, service)
    with TestClient(app) as client:
        assert client.get("/api/forex/connections").status_code == 401
        auth = {"Authorization": "Bearer fixture-app-key"}
        assert client.get("/api/forex/connections", headers=auth).status_code == 200
        denied = client.post(
            "/api/forex/connections/practice/halt",
            json={},
            headers={**auth, "Origin": "https://untrusted.invalid", "Sec-Fetch-Site": "cross-site"},
        )
        assert denied.status_code == 403
        assert not service.connections()[0]["halted"]


def test_resuming_connection_never_clears_global_or_broker_halt(service):
    from src.live.halt import halt_flag_set, trip_halt

    app = FastAPI()
    register_forex_routes(app, service)
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[require_settings_write_auth] = lambda: None
    trip_halt("file", "Test global halt")
    trip_halt("file", "Test broker halt", broker="oanda")
    with TestClient(app) as client:
        assert client.post("/api/forex/connections/practice/resume", json={}).status_code == 200
        assert halt_flag_set() and service.connections()[0]["broker_halted"]
        assert client.post("/api/forex/connections/practice/resume-broker", json={}).status_code == 200
        assert halt_flag_set() and not service.connections()[0]["broker_halted"]


def test_live_forex_proposal_uses_existing_commit_writer_and_exact_account(service, monkeypatch):
    from src.live.mandate.commit import commit_mandate
    from src.live.mandate.model import AssetClass, InstrumentType

    cfg = service.store.connection("practice").model_copy(update={"environment": "live"})
    service.store.save_connection(cfg)
    monkeypatch.setattr(service, "verify", lambda _: {"account": {"currency": "USD", "equity": "10000"}})
    app = FastAPI()
    register_forex_routes(app, service)
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[require_settings_write_auth] = lambda: None
    with TestClient(app) as client:
        response = client.post("/api/forex/connections/practice/mandate-proposal", json={})
        assert response.status_code == 200, response.text
        proposal = response.json()
        assert proposal["account_ref"] == cfg.account_ref
    commit_mandate(
        proposal["proposal_id"], 1, None, True, broker=cfg.mandate_key, account_ref=cfg.account_ref, lifetime_days=1
    )
    from src.live.mandate.store import load_mandate

    mandate = load_mandate(cfg.mandate_key)
    assert mandate.consent.account_ref == cfg.account_ref
    assert InstrumentType.FOREX in mandate.hard_caps.allowed_instruments
    assert AssetClass.FOREX in mandate.universe.asset_classes
    assert mandate.universe.min_market_cap_usd is None
    assert mandate.universe.min_avg_daily_volume_usd is None
    from src.live.enforcement import OrderIntent, check_mandate

    assert (
        check_mandate(
            mandate,
            OrderIntent(
                symbol="EUR_USD",
                side="buy",
                notional_usd=100,
                quantity=100,
                instrument_type=InstrumentType.FOREX,
                asset_class=AssetClass.FOREX,
            ),
            [],
            {"equity": 10000},
            broker=cfg.mandate_key,
            remote_tool="forex_submit_intent",
            daily_count=0,
        )
        is None
    )
