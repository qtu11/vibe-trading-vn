"""Offline immutable attempt journal, migrations, API auth and MCP research-write gate."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.trading.forex.errors import ForexError
from src.trading.forex.models import Connection, digest
from src.trading.forex.service import ForexService
from src.trading.forex.store import Store
from src.trading.forex.walk_forward import WalkForwardRequest, walk_forward
from tests.test_forex_walk_forward import request_data


@pytest.fixture
def service(tmp_path):
    broker = Mock(side_effect=AssertionError("Research must never request a broker adapter"))
    return ForexService(Store(tmp_path / "forex.db"), credentials=Mock(), factory=broker)


def request(**changes):
    return WalkForwardRequest.model_validate({**request_data(), **changes})


def test_attempt_keeps_complete_input_cost_version_and_every_trial_across_restart(service):
    supplied = request(candidates=[{"fast": 2, "slow": 3}, {"fast": 20, "slow": 80}])
    run = service.run_experiment(supplied)
    assert run["status"] == "ok"
    assert run["attempt"] == 1
    assert run["request"] == supplied.model_dump(mode="json")
    assert run["request"]["round_trip_cost_bps"] == 2
    assert run["result"] == walk_forward(supplied)
    assert run["result"]["folds"][0]["trials"][1]["code"] == "NO_TRAIN_TRADES"
    assert run["input_hash"] == digest({"request": run["request"], "engine": run["engine"]})
    assert run["engine"]["registry_version"] == 1
    assert set(run["engine"]["packages"]) == {"numpy", "pydantic"}
    assert all(len(value) == 64 for value in run["engine"]["source_sha256"].values())
    assert Store(service.store.path).research_run(run["experiment_id"], run["id"]) == run
    service.factory.assert_not_called()
    service.credentials.assert_not_called()


def test_incomplete_attempt_is_retained_and_no_strategy_is_activated(service):
    run = service.run_experiment(request(candidates=[{"fast": 20, "slow": 80}]))
    assert run["status"] == "incomplete"
    assert run["result"]["out_of_sample_metrics"] is None
    assert len(run["result"]["folds"]) == 3
    assert run["result"]["folds"][0]["trials"][0]["status"] == "error"
    with service.store.db() as db:
        assert db.execute("SELECT count(*) FROM connections").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM intents").fetchone()[0] == 0
    service.factory.assert_not_called()


def test_revisions_append_attempts_and_completed_results_cannot_be_replaced(service):
    first = service.run_experiment(request())
    second = service.run_experiment(request(round_trip_cost_bps=5), first["experiment_id"])
    repeated = service.run_experiment(request(), first["experiment_id"])
    assert len({first["id"], second["id"], repeated["id"]}) == 3
    assert [first["attempt"], second["attempt"], repeated["attempt"]] == [1, 2, 3]
    assert first["input_hash"] != second["input_hash"]
    assert first["input_hash"] == repeated["input_hash"]
    with pytest.raises(ForexError, match="cannot be replaced"):
        service.store.finish_research_run(first["experiment_id"], first["id"], {"status": "error"})
    assert service.store.research_run(first["experiment_id"], first["id"]) == first
    detail = service.store.research_experiment(first["experiment_id"], limit=1, offset=1)
    assert detail["attempt_count"] == 3
    assert [item["id"] for item in detail["runs"]] == [second["id"]]
    assert service.store.research_experiments()["experiments"][0]["attempt_count"] == 3


def test_engine_exception_is_journaled_without_leaking_exception_text(service, monkeypatch):
    def fail(_):
        raise RuntimeError("secret local path C:/private/credentials.json")
    monkeypatch.setattr("src.trading.forex.walk_forward.walk_forward", fail)
    run = service.run_experiment(request())
    assert run["status"] == "error"
    assert run["result"]["code"] == "RESEARCH_EVALUATION_FAILED"
    assert run["result"]["exception_type"] == "RuntimeError"
    assert "secret" not in json.dumps(run)
    assert run["finished_at"] is not None
    assert service.store.research_run(run["experiment_id"], run["id"]) == run


def test_unfinished_attempt_remains_running_after_restart(service):
    run = service.store.start_research_run(request().model_dump(mode="json"), {"fixture_version": 1})
    restored = Store(service.store.path).research_run(run["experiment_id"], run["id"])
    assert restored["status"] == "running"
    assert restored["finished_at"] is None
    assert restored["result"] == {}


def test_concurrent_appends_have_distinct_monotonic_attempt_numbers(service):
    first = service.run_experiment(request())
    with ThreadPoolExecutor(max_workers=4) as pool:
        runs = list(pool.map(lambda _: service.run_experiment(request(), first["experiment_id"]), range(4)))
    assert sorted(item["attempt"] for item in runs) == [2, 3, 4, 5]
    assert len({item["id"] for item in runs}) == 4
    assert service.store.research_experiment(first["experiment_id"])["attempt_count"] == 5


def test_cross_experiment_run_and_unknown_experiment_are_not_resolved(service):
    first, other = service.run_experiment(request()), service.run_experiment(request())
    with pytest.raises(ForexError) as exc:
        service.store.research_run(other["experiment_id"], first["id"])
    assert exc.value.code == "RESEARCH_RUN_NOT_FOUND"
    with pytest.raises(ForexError) as exc:
        service.run_experiment(request(), "missing-experiment")
    assert exc.value.code == "EXPERIMENT_NOT_FOUND"
    assert service.store.research_experiments()["total"] == 2
    assert service.store.research_experiments(limit=1, offset=1)["experiments"][0]["id"] == first["experiment_id"]


def test_v3_upgrade_preserves_existing_execution_records_and_adds_registry(service):
    service.store.save_connection(Connection(id="practice", label="Practice", connector="oanda", account_ref="fixture"))
    with sqlite3.connect(service.store.path) as db:
        db.execute("INSERT INTO intents(id,connection_id,connector,request_key,payload_hash,binding_hash,payload,state,created_at) "
                   "VALUES('prior-intent','practice','oanda','fixture-key','fixture-hash','fixture-binding','{}','unknown','2024-01-01')")
        db.execute("DROP TABLE research_runs")
        db.execute("DROP TABLE research_experiments")
        db.execute("PRAGMA user_version=3")
    assert service.store.connection("practice").account_ref == "fixture"
    prior = service.store.intent("prior-intent")
    assert prior["state"] == "unknown"
    assert service.run_experiment(request())["status"] == "ok"
    assert service.store.intent("prior-intent") == prior
    with sqlite3.connect(service.store.path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 4
        assert db.execute("SELECT count(*) FROM connections").fetchone()[0] == 1


def test_http_registry_uses_write_auth_and_pagination_without_broker_calls(service, monkeypatch):
    from src.api.forex_routes import register_forex_routes
    from src.api.security import require_auth, require_settings_write_auth

    monkeypatch.setattr("src.api.security._configured_api_key", lambda: "fixture-app-key")
    app = FastAPI()
    register_forex_routes(app, service)
    with TestClient(app) as client:
        assert client.get("/api/forex/experiments").status_code == 401
        assert client.post("/api/forex/experiments", json=request_data()).status_code == 401
        app.dependency_overrides[require_auth] = lambda: None
        assert client.get("/api/forex/experiments").json()["total"] == 0
        assert client.post("/api/forex/experiments", json=request_data()).status_code == 401
        app.dependency_overrides[require_settings_write_auth] = lambda: None
        created = client.post("/api/forex/experiments", json=request_data())
        assert created.status_code == 200, created.text
        run = created.json()
        experiment_id = run["experiment_id"]
        base = f"/api/forex/experiments/{experiment_id}"
        assert client.get(f"{base}/runs/{run['id']}").json() == run
        assert client.post(base + "/runs", json=request_data()).json()["attempt"] == 2
        assert client.get(base + "?limit=1&offset=1").json()["runs"][0]["id"] == run["id"]
        assert client.get("/api/forex/experiments?limit=0").status_code == 422
        assert client.get(base + "?offset=-1").status_code == 422
        invalid = request_data()
        invalid["bars"][0]["complete"] = False
        assert client.post("/api/forex/experiments", json=invalid).status_code == 422
        assert client.get(base).json()["attempt_count"] == 2
    service.factory.assert_not_called()


@pytest.mark.asyncio
async def test_mcp_default_readonly_registry_and_explicit_local_write_gate(service):
    from fastmcp import Client
    from src.trading.forex.mcp_server import build_server

    service.store.save_connection(Connection(id="practice", label="Practice", connector="oanda", account_ref="fixture"))
    readonly = build_server(service, "practice")
    tools = {tool.name: tool for tool in await readonly.list_tools()}
    assert "forex_run_experiment" not in tools
    assert all(tool.annotations.readOnlyHint for tool in tools.values())
    assert tools["forex_list_experiments"].annotations.openWorldHint is False
    enabled = build_server(service, "practice", allow_research_writes=True)
    tools = {tool.name: tool for tool in await enabled.list_tools()}
    assert tools["forex_run_experiment"].annotations.readOnlyHint is False
    assert tools["forex_run_experiment"].annotations.openWorldHint is False
    assert "forex_submit_intent" not in tools
    async with Client(enabled) as client:
        created = (await client.call_tool("forex_run_experiment", {"request": request_data()})).data
        assert created["result"] == walk_forward(request())
        listing = (await client.call_tool("forex_list_experiments", {})).data
        assert listing["total"] == 1
        detail = (await client.call_tool("forex_get_experiment", {"experiment_id": created["experiment_id"]})).data
        assert detail["runs"][0]["id"] == created["id"]
        restored = (await client.call_tool("forex_get_experiment_run", {
            "experiment_id": created["experiment_id"], "run_id": created["id"],
        })).data
        assert restored == created
        error = (await client.call_tool("forex_get_experiment", {"experiment_id": "unknown"})).data
        assert error["code"] == "EXPERIMENT_NOT_FOUND"
    service.factory.assert_not_called()
