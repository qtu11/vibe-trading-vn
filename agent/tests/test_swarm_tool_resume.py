"""Waiting on one observed swarm must not create another or change its owner."""

import json
import threading
from datetime import datetime, timezone

import pytest

from src.agent.grounding import GroundingLedger
from src.agent.tool_context import current_grounding
from src.swarm.models import SwarmRun, SwarmTask, SwarmEvent
from src.tools.swarm_tool import SwarmTool
import src.tools.swarm_tool as tool_module


@pytest.fixture
def launched(tmp_path, monkeypatch):
    import src.swarm.runtime as runtime_module

    starts = []
    monkeypatch.setattr(tool_module, "_resolve_preset", lambda *a: ("test", None))
    monkeypatch.setattr(tool_module, "_build_variables", lambda *a: {})
    monkeypatch.setattr(tool_module, "_max_wait_seconds", lambda: 0)
    monkeypatch.setattr("src.config.load_swarm_agent_config", lambda: None)
    monkeypatch.setattr("src.swarm.store.swarm_runs_root", lambda: tmp_path / "swarm")

    def start(runtime, *args, **kwargs):
        starts.append(kwargs)
        now = datetime.now(timezone.utc).isoformat()
        run = SwarmRun(id="only-run", preset_name="test", status="running",
                       created_at=now,
                       tasks=[SwarmTask(id="facts", agent_id="reader", prompt_template="Read")])
        runtime._store.create_run(run)
        callback = kwargs.get("live_callback")
        if callback:
            for kind, data in (("task_heartbeat", {}),
                               ("worker_llm_usage", {"usage": {"input_tokens": 12, "output_tokens": 3}})):
                callback(SwarmEvent(type=kind, agent_id="reader", task_id="facts", data=data,
                                    timestamp=now))
        return run

    monkeypatch.setattr(runtime_module.SwarmRuntime, "start_run", start)
    return starts


def test_resume_uses_same_run_and_actual_receipt(tmp_path, launched):
    ledger = GroundingLedger(run_dir=tmp_path / "parent", user_message="Research")
    token = current_grounding.set(ledger)
    try:
        tool = SwarmTool()
        first = json.loads(tool.execute(prompt="Research"))
        second = json.loads(tool.execute(run_id=first["run_id"]))
        assert len(launched) == 1
        assert second["run_id"] == first["run_id"]
        assert ledger.swarm_run_receipt(first["run_id"])["status"] == "running"
        assert "Cannot change" in json.loads(tool.execute(run_id=first["run_id"], prompt="Replace"))["error"]
    finally:
        current_grounding.reset(token)


def test_resume_cannot_cross_parent_request(tmp_path, launched):
    tool = SwarmTool()
    first = json.loads(tool.execute(prompt="Research"))
    token = current_grounding.set(GroundingLedger(run_dir=tmp_path / "other", user_message="Other"))
    try:
        result = json.loads(tool.execute(run_id=first["run_id"]))
        assert result["status"] == "error"
        assert not tool.cancel_owned_run(first["run_id"])
        assert len(launched) == 1
    finally:
        current_grounding.reset(token)
    assert tool.cancel_owned_run(first["run_id"])


def test_parent_cancel_signals_owned_runtime_without_restart(launched, monkeypatch):
    tool = SwarmTool()
    first = json.loads(tool.execute(prompt="Research"))
    tool.cancel_event = threading.Event()
    tool.cancel_event.set()
    monkeypatch.setattr(tool_module, "_max_wait_seconds", lambda: 1)
    result = json.loads(tool.execute(run_id=first["run_id"]))
    assert result["status"] == "cancelled"
    assert len(launched) == 1
    assert json.loads(tool.execute(prompt="Another"))["status"] == "error"


def test_only_actual_usage_and_progress_are_forwarded(launched):
    tool = SwarmTool()
    usage, progress = [], []
    tool.usage_callback = lambda role, value: usage.append((role, value))
    tool.progress_callback = lambda kind, value: progress.append(kind)
    first = json.loads(tool.execute(prompt="Research"))
    tool.execute(run_id=first["run_id"])
    assert usage == [("reader", {"input_tokens": 12, "output_tokens": 3})]
    assert progress == ["worker_llm_usage"]


@pytest.mark.parametrize("run_id", [["only-run"], {"id": "only-run"}])
def test_invalid_resume_id_is_a_tool_error(launched, run_id):
    result = json.loads(SwarmTool().execute(run_id=run_id))
    assert result["status"] == "error"
    assert not launched
