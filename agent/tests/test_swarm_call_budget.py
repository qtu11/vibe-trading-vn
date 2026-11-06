"""Offline logical-call admission, retry accounting, and public caller contracts."""

import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest

import src.swarm.runtime as runtime_module
import src.swarm.worker as worker_module
from src.providers.chat import LLMResponse, ProviderStreamError
from src.swarm.budget import SwarmBudgetExceeded, SwarmCallBudget
from src.swarm.models import SwarmAgentSpec, SwarmRun, SwarmTask
from src.swarm.store import SwarmStore


USAGE = {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12}
REPORT = (
    "# Findings\nThe supplied research evidence supports a cautious conclusion. "
    "The source is recorded and its publication time is available for review. "
    "Risk remains elevated because the secondary evidence has not been verified. "
    "Recommendation: obtain independent confirmation before interpreting the result. "
    "No live market observation or external transaction was performed."
)


def _run(run_id="budget", **kwargs):
    return SwarmRun(
        id=run_id, preset_name="test", created_at="2026-11-05T00:00:00Z",
        agents=[SwarmAgentSpec(id="analyst", role="Synthesis", system_prompt="Research", max_retries=2)],
        tasks=[SwarmTask(id="a", agent_id="analyst", prompt_template="Summarize.")],
        **kwargs,
    )


def _budget(tmp_path, *, limit=1):
    run = _run(max_llm_calls=limit, status="running")
    store = SwarmStore(tmp_path / "runs")
    store.create_run(run)
    events = []
    return SwarmCallBudget(run, store, lambda *args: events.append(args)), events


@pytest.mark.parametrize("value", [True, False, "2", 2.0, 0, -1, [], {}])
def test_invalid_cap_fails_before_persistence(monkeypatch, value):
    monkeypatch.setattr(runtime_module, "build_run_from_preset", lambda *_: _run())
    dotenv = Mock()
    monkeypatch.setattr(runtime_module, "_ensure_dotenv", dotenv)
    store = Mock(spec=SwarmStore)
    with pytest.raises(ValueError, match="max_llm_calls"):
        runtime_module.SwarmRuntime(store).start_run("test", {}, max_llm_calls=value)
    assert store.method_calls == []
    dotenv.assert_not_called()


def test_legacy_counts_are_unknown_and_new_run_initializes_zero(monkeypatch, tmp_path):
    assert _run().llm_calls_started is None
    assert _run().llm_calls_unknown_usage is None
    monkeypatch.setattr(runtime_module, "build_run_from_preset", lambda *_: _run())
    monkeypatch.setattr(runtime_module, "_ensure_dotenv", lambda: None)
    monkeypatch.setattr(runtime_module.threading, "Thread", Mock())
    store = SwarmStore(tmp_path / "runs")
    run = runtime_module.SwarmRuntime(store).start_run("test", {}, max_llm_calls=3)
    assert run.llm_calls_started == run.llm_calls_unknown_usage == 0
    assert store.load_run(run.id).max_llm_calls == 3


def test_parallel_reservations_never_dispatch_beyond_cap_and_keep_unknown(tmp_path):
    budget, events = _budget(tmp_path, limit=3)

    def reserve(_):
        try:
            return budget.reserve("analyst", "a", 0)
        except SwarmBudgetExceeded:
            return None

    with ThreadPoolExecutor(max_workers=12) as pool:
        admitted = [value for value in pool.map(reserve, range(24)) if value is not None]
    assert sorted(admitted) == [1, 2, 3]
    persisted = budget.store.load_run(budget.run.id)
    assert persisted.llm_calls_started == persisted.llm_calls_unknown_usage == 3
    assert persisted.budget_stop_reason == "max_llm_calls_reached"
    budget.record(1, USAGE, "failed", "analyst", "a")
    budget.record(2, None, "returned", "analyst", "a")
    assert budget.store.load_run(budget.run.id).llm_calls_unknown_usage == 2
    assert events[-1][-1]["usage_source"] == "unknown"


def test_persistence_failure_prevents_provider_dispatch(tmp_path):
    budget, _ = _budget(tmp_path)
    budget.store.update_run = Mock(side_effect=OSError("disk unavailable"))
    with pytest.raises(OSError, match="disk unavailable"):
        budget.reserve("analyst", "a", 0)
    assert budget.run.llm_calls_unknown_usage == 1


class _Registry:
    def get_definitions(self):
        return []

    def get(self, name):
        return None


class _LLM:
    model_name = "offline-fixture"

    def __init__(self, result, cancel_event=None):
        self.result = result
        self.calls = 0
        self.cancel_event = cancel_event

    def stream_chat(self, *args, **kwargs):
        self.calls += 1
        if self.cancel_event is not None:
            self.cancel_event.set()
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    def close(self):
        pass


def _worker(monkeypatch, tmp_path, result, *, cancel_event=None):
    budget, events = _budget(tmp_path)
    llm = _LLM(result, cancel_event)
    monkeypatch.setattr(worker_module, "build_swarm_registry", lambda *args, **kwargs: _Registry())
    monkeypatch.setattr(worker_module, "ChatLLM", lambda **kwargs: llm)
    monkeypatch.setattr(worker_module, "_STREAM_RETRY_DELAY_S", 0)
    run = budget.run
    output = worker_module.run_worker(
        run.agents[0], run.tasks[0], {}, {}, tmp_path / "worker",
        cancel_event=cancel_event, call_budget=budget,
    )
    return output, budget, llm, events


@pytest.mark.parametrize("usage", [None, USAGE])
def test_stream_retry_consumes_reservation_and_budget_stop_is_terminal(monkeypatch, tmp_path, usage):
    error = ProviderStreamError(provider="fixture", model="offline", original=ConnectionError("fixture"), usage_metadata=usage)
    result, budget, llm, _ = _worker(monkeypatch, tmp_path, error)
    assert llm.calls == 1
    assert result.status == "budget_limit"
    assert "max_llm_calls_reached" in result.error
    assert budget.run.llm_calls_unknown_usage == (1 if usage is None else 0)
    assert result.input_tokens > 0


def test_generic_failure_retains_unknown_usage(monkeypatch, tmp_path):
    result, budget, llm, _ = _worker(monkeypatch, tmp_path, ValueError("fixture"))
    assert llm.calls == 1
    assert result.status == "failed"
    assert budget.run.llm_calls_started == budget.run.llm_calls_unknown_usage == 1
    assert result.token_source == "estimated"


def test_cancelled_successful_stream_retains_provider_usage(monkeypatch, tmp_path):
    result, budget, llm, _ = _worker(
        monkeypatch, tmp_path, LLMResponse(content=REPORT, usage_metadata=USAGE), cancel_event=threading.Event(),
    )
    assert result.status == "cancelled"
    assert llm.calls == 1
    assert result.input_tokens == 10
    assert budget.run.llm_calls_unknown_usage == 0


def test_worker_retries_share_the_same_call_allowance(monkeypatch, tmp_path):
    budget, _ = _budget(tmp_path, limit=2)
    llm = _LLM(ValueError("offline failure"))
    monkeypatch.setattr(worker_module, "build_swarm_registry", lambda *args, **kwargs: _Registry())
    monkeypatch.setattr(worker_module, "ChatLLM", lambda **kwargs: llm)
    monkeypatch.setattr(runtime_module, "_worker_retry_delay_s", lambda _: 0)
    runtime = runtime_module.SwarmRuntime(budget.store)
    run = budget.run
    result = runtime._run_worker_with_retries(
        run.agents[0], run.tasks[0], {}, {}, tmp_path / "worker", None, run.id,
        call_budget=budget,
    )
    assert result.status == "budget_limit"
    assert llm.calls == budget.run.llm_calls_started == budget.run.llm_calls_unknown_usage == 2
    assert result.input_tokens > 0


def test_runtime_shares_cap_across_dag_layers_and_never_retries_budget_stop(monkeypatch, tmp_path):
    run = _run(max_llm_calls=1)
    run.tasks.append(SwarmTask(id="b", agent_id="analyst", prompt_template="Review.", depends_on=["a"]))
    store = SwarmStore(tmp_path / "runs")
    store.create_run(run)
    llm = _LLM(LLMResponse(content=REPORT, usage_metadata=USAGE))
    monkeypatch.setattr(worker_module, "build_swarm_registry", lambda *args, **kwargs: _Registry())
    monkeypatch.setattr(worker_module, "ChatLLM", lambda **kwargs: llm)
    runtime = runtime_module.SwarmRuntime(store)
    runtime._execute_run(run, threading.Event())
    persisted = store.load_run(run.id)
    assert persisted.status == "failed"
    assert [task.status for task in persisted.tasks] == ["completed", "failed"]
    assert persisted.llm_calls_started == llm.calls == 1
    assert persisted.llm_calls_unknown_usage == 0
    assert persisted.total_input_tokens == 10
    assert "max_llm_calls_reached" in persisted.tasks[1].error
    assert not any(event.type == "task_retry" for event in store.read_events(run.id))


def test_mcp_start_forwards_cap_and_projects_usage(monkeypatch, tmp_path):
    import mcp_server
    store = SwarmStore(tmp_path / "runs")
    run = _run(max_llm_calls=4, llm_calls_started=2, llm_calls_unknown_usage=1)
    store.create_run(run)
    captured = {}

    def start(self, *args, **kwargs):
        captured.update(kwargs)
        return run

    monkeypatch.setattr("src.config.load_swarm_agent_config", lambda: None)
    monkeypatch.setattr(runtime_module.SwarmRuntime, "start_run", start)
    monkeypatch.setattr("src.swarm.store.swarm_runs_root", lambda: store.base_dir)
    payload = json.loads(asyncio.run(mcp_server.run_swarm("test", {}, start_only=True, max_llm_calls=4)))
    assert captured["max_llm_calls"] == 4
    assert payload["max_llm_calls"] == 4
    assert payload["llm_calls_started"] == 2
    assert payload["llm_calls_unknown_usage"] == 1


@pytest.mark.parametrize("resume", [False, True])
def test_mcp_retry_retains_cap_with_fresh_run(monkeypatch, tmp_path, resume):
    import mcp_server

    store = SwarmStore(tmp_path / "runs")
    original = _run(status="failed", max_llm_calls=4, llm_calls_started=4, llm_calls_unknown_usage=2)
    store.create_run(original)
    captured = {}

    def start(self, *args, **kwargs):
        captured.update(kwargs)
        fresh = _run("fresh", max_llm_calls=kwargs["max_llm_calls"], llm_calls_started=0, llm_calls_unknown_usage=0)
        self._store.create_run(fresh)
        return fresh

    monkeypatch.setattr(mcp_server, "_get_swarm_store", lambda: store)
    monkeypatch.setattr(runtime_module.SwarmRuntime, "start_run", start)
    json.loads(mcp_server.retry_run(original.id, resume=resume))
    assert captured["max_llm_calls"] == 4
    assert store.load_run(original.id).llm_calls_started == 4


@pytest.mark.parametrize("value", [True, "2", 2.0, 0, -1])
def test_http_rejects_coerced_or_invalid_cap_before_storage(monkeypatch, tmp_path, value):
    import api_server
    import src.api.swarm_routes as routes
    from fastapi.testclient import TestClient

    store = SwarmStore(tmp_path / "runs")
    runtime = runtime_module.SwarmRuntime(store)
    monkeypatch.setattr(routes, "_swarm_runtime", runtime)
    monkeypatch.setattr(runtime_module, "build_run_from_preset", lambda *_: _run())
    monkeypatch.setattr(api_server, "_API_KEY", "")
    monkeypatch.delenv("API_AUTH_KEY", raising=False)
    client = TestClient(api_server.app, client=("127.0.0.1", 50000))
    response = client.post("/swarm/runs", json={"preset_name": "test", "user_vars": {}, "max_llm_calls": value})
    assert response.status_code == 400
    assert "max_llm_calls" in response.json()["detail"]
    assert not store.base_dir.exists()


def test_agent_tool_forwards_cap_and_exposes_unknown_usage(monkeypatch, tmp_path):
    import src.tools.swarm_tool as tool_module

    run = _run(status="completed", max_llm_calls=3, llm_calls_started=2, llm_calls_unknown_usage=1)
    captured = {}

    def start(self, *args, **kwargs):
        captured.update(kwargs)
        self._store.create_run(run)
        return run

    monkeypatch.setattr(tool_module, "_resolve_preset", lambda *args: ("test", None))
    monkeypatch.setattr(tool_module, "_build_variables", lambda *args: {})
    monkeypatch.setattr(tool_module, "_max_wait_seconds", lambda: 0)
    monkeypatch.setattr("src.config.load_swarm_agent_config", lambda: None)
    monkeypatch.setattr("src.swarm.store.swarm_runs_root", lambda: tmp_path / "runs")
    monkeypatch.setattr(runtime_module.SwarmRuntime, "start_run", start)
    result = json.loads(tool_module.SwarmTool().execute(prompt="Research", max_llm_calls=3))
    assert captured["max_llm_calls"] == 3
    assert result["max_llm_calls"] == 3
    assert result["llm_calls_unknown_usage"] == 1


@pytest.mark.parametrize("resume", [False, True])
def test_http_retry_preserves_cap_and_read_projection(monkeypatch, tmp_path, resume):
    import api_server
    import src.api.swarm_routes as routes
    from fastapi.testclient import TestClient

    store = SwarmStore(tmp_path / "runs")
    original = _run(status="failed", max_llm_calls=3, llm_calls_started=3, llm_calls_unknown_usage=1)
    store.create_run(original)
    captured = {}
    runtime = runtime_module.SwarmRuntime(store)

    def start(*args, **kwargs):
        captured.update(kwargs)
        fresh = _run("fresh", max_llm_calls=3, llm_calls_started=0, llm_calls_unknown_usage=0)
        store.create_run(fresh)
        return fresh

    monkeypatch.setattr(runtime, "start_run", start)
    monkeypatch.setattr(routes, "_swarm_runtime", runtime)
    monkeypatch.setattr(api_server, "_API_KEY", "")
    monkeypatch.delenv("API_AUTH_KEY", raising=False)
    client = TestClient(api_server.app, client=("127.0.0.1", 50000))
    response = client.post(f"/swarm/runs/budget/retry?resume={str(resume).lower()}")
    assert response.status_code == 200
    assert captured["max_llm_calls"] == 3
    payload = client.get("/swarm/runs/budget").json()
    assert payload["max_llm_calls"] == payload["llm_calls_started"] == 3
    assert payload["llm_calls_unknown_usage"] == 1
