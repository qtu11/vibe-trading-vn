"""Invalid swarm plans must fail before persistence or worker startup."""

from unittest.mock import Mock

import pytest

import src.swarm.runtime as runtime_module
from src.swarm.models import SwarmAgentSpec, SwarmRun, SwarmTask
from src.swarm.store import SwarmStore
from src.swarm.task_store import topological_layers, validate_dag


def _task(task_id: str, *, depends_on=(), input_from=None, agent_id="analyst"):
    return SwarmTask(
        id=task_id,
        agent_id=agent_id,
        prompt_template="Research",
        depends_on=list(depends_on),
        input_from=input_from or {},
    )


def _agent(agent_id="analyst"):
    return SwarmAgentSpec(id=agent_id, role="Analyst", system_prompt="Research")


@pytest.mark.parametrize(
    ("tasks", "message"),
    [
        ([_task("a"), _task("a")], "Duplicate task id: a"),
        ([_task(" ")], "Task id must not be empty"),
        ([_task("a", depends_on=["missing"])], "depends on unknown task 'missing'"),
        ([_task("a", input_from={"source": "missing"})], "references unknown task 'missing'"),
        ([_task("a", input_from={"source": "a"})], "not upstream in the DAG"),
        ([_task("a"), _task("b", input_from={"source": "a"})], "not upstream in the DAG"),
        ([_task("a", depends_on=["b"]), _task("b", depends_on=["a"])], "Cycle detected"),
    ],
)
def test_rejects_invalid_graph(tasks, message):
    with pytest.raises(ValueError, match=message):
        validate_dag(tasks)


@pytest.mark.parametrize(
    ("agents", "agent_id", "message"),
    [
        ([_agent(), _agent()], "analyst", "Duplicate agent id: analyst"),
        ([_agent(" ")], "analyst", "Agent id must not be empty"),
        ([_agent()], "missing", "references unknown agent 'missing'"),
        ([], "analyst", "references unknown agent 'analyst'"),
    ],
)
def test_rejects_invalid_agent_identity(agents, agent_id, message):
    with pytest.raises(ValueError, match=message):
        validate_dag([_task("a", agent_id=agent_id)], agents)


def test_accepts_direct_and_transitive_inputs_in_a_diamond():
    tasks = [
        _task("a"),
        _task("b", depends_on=["a"]),
        _task("c", depends_on=["a"]),
        _task(
            "d", depends_on=["b", "c"],
            input_from={"original": "a", "review": "c"},
        ),
    ]
    validate_dag(tasks, [_agent()])
    assert topological_layers(tasks) == [["a"], ["b", "c"], ["d"]]


@pytest.mark.parametrize(
    ("tasks", "agents"),
    [
        ([_task("a"), _task("a")], [_agent()]),
        ([_task("a")], [_agent(), _agent()]),
        ([_task("a", agent_id="missing")], [_agent()]),
        ([_task("a", depends_on=["missing"])], [_agent()]),
        ([_task("a", input_from={"source": "missing"})], [_agent()]),
        ([_task("a"), _task("b", input_from={"source": "a"})], [_agent()]),
    ],
)
def test_runtime_rejects_invalid_plan_before_any_side_effect(monkeypatch, tasks, agents):
    run = SwarmRun(
        id="invalid", preset_name="invalid", created_at="2026-11-05T00:00:00Z",
        tasks=tasks, agents=agents,
    )
    monkeypatch.setattr(runtime_module, "build_run_from_preset", lambda *_: run)
    dotenv = Mock()
    thread = Mock()
    monkeypatch.setattr(runtime_module, "_ensure_dotenv", dotenv)
    monkeypatch.setattr(runtime_module.threading, "Thread", thread)
    store = Mock(spec=SwarmStore)
    runtime = runtime_module.SwarmRuntime(store)

    with pytest.raises(ValueError):
        runtime.start_run("invalid", {})

    assert store.method_calls == []
    assert runtime._cancel_events == {}
    assert runtime._live_callbacks == {}
    dotenv.assert_not_called()
    thread.assert_not_called()
