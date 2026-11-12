"""Wall-clock wrap-up behavior for swarm workers.

The iteration cap alone is not sufficient: a reviewer that keeps reading
evidence can spend its entire timeout before reaching the last-iteration
forced-answer path, then return an empty timeout. These tests pin the
deadline-aware behavior: a nudge once 70% of the time budget is gone, and a
tool-less final call before the deadline.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.providers.chat import LLMResponse, ToolCallRequest
from src.swarm.models import SwarmAgentSpec, SwarmTask, WorkerResult
import src.swarm.worker as worker_mod
from src.swarm.worker import run_worker

FINAL_TEXT = (
    "# TCB — Independent review\n\n"
    "The analysis overstates the net-interest-margin recovery. 2025 fee income "
    "grew 9.1% while operating costs grew 12.4%, so the cost-income ratio rose "
    "from 31.2% to 33.0%. The 26,000 VND target assumes a 2.1x P/B multiple that "
    "the observed ROE of 17.3% does not support. Unresolved gap: the Q4 sector "
    "NPL disclosure was not available, so the credit-cost forecast (0.9%) is "
    "not verified and the thesis must not be treated as confirmed."
)

_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "read_url",
        "description": "Read a source URL",
        "parameters": {"type": "object", "properties": {}},
    },
}


class _EvidenceTool:
    """Tool stub classified as a read-only evidence source."""

    name = "read_url"
    is_readonly = True


class _Registry:
    """Registry stub exposing one evidence tool and recording dispatches."""

    def __init__(self) -> None:
        self.executed: list[str] = []

    def get_definitions(self) -> list[dict]:
        return [_TOOL_DEF]

    def get(self, name: str):
        return _EvidenceTool()

    def execute(self, name: str, args: dict) -> str:
        self.executed.append(name)
        return (
            '{"status": "ok", "url": "https://example.com/filing", '
            '"content": "Primary filing evidence."}'
        )


class _ScriptedLLM:
    """Scripted ChatLLM recording tools/messages for each call."""

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)
        self.calls = 0
        self.tool_defs: list[object] = []
        self.messages: list[list[dict]] = []

    def __call__(self, *args, **kwargs) -> "_ScriptedLLM":
        return self

    def close(self) -> None:
        """No-op: the stub owns no HTTP client."""

    def stream_chat(
        self, messages, tools=None, on_text_chunk=None, timeout=None,
        on_waiting_chunk=None,
    ) -> LLMResponse:
        self.calls += 1
        self.tool_defs.append(tools)
        self.messages.append([dict(message) for message in messages])
        return self._responses.pop(0)


class _FakeClock:
    """Monotonic clock returning scripted readings, repeating the last one."""

    def __init__(self, readings: list[float]) -> None:
        self._readings = list(readings)
        self._index = 0

    def monotonic(self) -> float:
        value = self._readings[min(self._index, len(self._readings) - 1)]
        self._index += 1
        return value

    def sleep(self, _seconds: float) -> None:
        """No-op: retry delays are irrelevant to these tests."""


def _run(
    monkeypatch,
    tmp_path: Path,
    llm: _ScriptedLLM,
    *,
    clock_readings: list[float],
    timeout_seconds: int = 100,
    max_iterations: int = 5,
    agent_tools: list[str] | None = None,
) -> tuple[WorkerResult, _Registry, list]:
    registry = _Registry()
    agent = SwarmAgentSpec(
        id="critical_reviewer",
        role="Critical reviewer",
        system_prompt="Challenge the analysis.",
        tools=agent_tools or ["read_url"],
        skills=[],
        max_iterations=max_iterations,
        timeout_seconds=timeout_seconds,
    )
    task = SwarmTask(id="critique", agent_id="critical_reviewer", prompt_template="Review it.")
    events: list = []
    monkeypatch.setattr(worker_mod, "time", SimpleNamespace(
        monotonic=_FakeClock(clock_readings).monotonic,
        sleep=lambda _seconds: None,
    ))
    with (
        patch.object(worker_mod, "build_swarm_registry", lambda *a, **k: registry),
        patch.object(worker_mod, "ChatLLM", llm),
    ):
        result = run_worker(
            agent_spec=agent,
            task=task,
            upstream_summaries={},
            user_vars={},
            run_dir=tmp_path,
            event_callback=events.append,
        )
    return result, registry, events


def _evidence_call() -> LLMResponse:
    return LLMResponse(
        content="I will verify the filing.",
        tool_calls=[ToolCallRequest(id="c1", name="read_url", arguments={"url": "https://example.com/filing"})],
        finish_reason="tool_calls",
    )


def test_wall_clock_final_phase_forces_a_tool_less_answer(monkeypatch, tmp_path):
    """At 90% of the budget the LLM is called without tools and still completes."""
    llm = _ScriptedLLM([_evidence_call(), LLMResponse(content=FINAL_TEXT)])
    # t0, iteration-0 top, stream budget, tool start, tool elapsed, iteration-1 top
    readings = [0.0, 0.0, 0.0, 0.0, 0.0, 90.0]

    result, registry, events = _run(monkeypatch, tmp_path, llm, clock_readings=readings)

    assert result.status == "completed", result.error
    assert result.summary == FINAL_TEXT
    assert llm.calls == 2
    assert llm.tool_defs[0] is not None
    assert llm.tool_defs[1] is None
    assert registry.executed == ["read_url"]
    assert any("Stop calling tools" in str(m.get("content", "")) for m in llm.messages[1])
    assert [event.type for event in events].count("worker_time_wrap_up") == 1


def test_wall_clock_does_not_force_before_the_final_phase(monkeypatch, tmp_path):
    """At 50% of the budget tools remain available and no nudge is injected."""
    llm = _ScriptedLLM([_evidence_call(), LLMResponse(content=FINAL_TEXT)])
    readings = [0.0, 0.0, 0.0, 0.0, 0.0, 50.0]

    result, _registry, events = _run(monkeypatch, tmp_path, llm, clock_readings=readings)

    assert result.status == "completed", result.error
    assert llm.tool_defs[1] is not None
    assert not any("[SYSTEM] About" in str(m.get("content", "")) for m in llm.messages[1])
    assert not any(event.type == "worker_time_wrap_up" for event in events)


def test_final_phase_ignores_stray_tool_calls(monkeypatch, tmp_path):
    """A provider that returns tool calls despite tools=None gets no new round."""
    llm = _ScriptedLLM([
        _evidence_call(),
        LLMResponse(
            content=FINAL_TEXT,
            tool_calls=[ToolCallRequest(id="c2", name="read_url", arguments={"url": "https://example.com/more"})],
            finish_reason="tool_calls",
        ),
    ])
    readings = [0.0, 0.0, 0.0, 0.0, 0.0, 90.0]

    result, registry, _events = _run(monkeypatch, tmp_path, llm, clock_readings=readings)

    assert result.status == "completed", result.error
    assert result.summary == FINAL_TEXT
    assert registry.executed == ["read_url"]


def test_final_phase_nudge_follows_the_early_nudge(monkeypatch, tmp_path):
    """The 70% nudge must not suppress the stronger 80% final-answer nudge."""
    llm = _ScriptedLLM([
        _evidence_call(),
        _evidence_call(),
        LLMResponse(content=FINAL_TEXT),
    ])
    # iteration 0 at 0s, iteration 1 at 75% (early nudge), iteration 2 at 90%
    # (final phase). max_iterations=5, so neither turn is the iteration cap.
    readings = [0.0, 0.0, 0.0, 0.0, 0.0, 75.0, 75.0, 75.0, 75.0, 90.0]

    result, registry, events = _run(monkeypatch, tmp_path, llm, clock_readings=readings)

    assert result.status == "completed", result.error
    assert result.summary == FINAL_TEXT
    nudges = [event for event in events if event.type == "worker_time_wrap_up"]
    assert [event.data["final"] for event in nudges] == [False, True]
    assert llm.tool_defs[1] is not None
    assert llm.tool_defs[2] is None
    final_messages = [str(m.get("content", "")) for m in llm.messages[2]]
    assert any("About 25s remain" in text for text in final_messages)
    assert any("Stop calling tools" in text for text in final_messages)
    assert registry.executed == ["read_url", "read_url"]


def test_iteration_nudge_is_suppressed_in_the_wall_clock_final_phase(monkeypatch, tmp_path):
    """The iteration nudge must not ask for write_file when tools are disabled.

    max_iterations=5 puts the 80%-of-iterations nudge on the last iteration;
    reaching that same iteration in the wall-clock final phase would otherwise
    append "write report.md" immediately before a tool-less LLM call.
    """
    llm = _ScriptedLLM([
        _evidence_call(),
        _evidence_call(),
        _evidence_call(),
        _evidence_call(),
        LLMResponse(content=FINAL_TEXT),
    ])
    readings = [0.0] * 17 + [90.0]

    result, _registry, _events = _run(
        monkeypatch,
        tmp_path,
        llm,
        clock_readings=readings,
        agent_tools=["read_url", "write_file"],
    )

    assert result.status == "completed", result.error
    assert llm.tool_defs[4] is None
    final_messages = [str(m.get("content", "")) for m in llm.messages[4]]
    assert not any("iterations remaining" in text for text in final_messages)
    assert any("Stop calling tools" in text for text in final_messages)


def test_final_phase_without_text_is_incomplete_not_completed(monkeypatch, tmp_path):
    """A forced final call with no substantive text must not fake completion."""
    llm = _ScriptedLLM([
        LLMResponse(
            content="I will verify the filing.",
            tool_calls=[ToolCallRequest(id="c1", name="read_url", arguments={"url": "https://example.com/filing"})],
            finish_reason="tool_calls",
        ),
        LLMResponse(
            content="",
            tool_calls=[ToolCallRequest(id="c2", name="read_url", arguments={"url": "https://example.com/more"})],
            finish_reason="tool_calls",
        ),
    ])
    readings = [0.0, 0.0, 0.0, 0.0, 0.0, 90.0]

    result, registry, _events = _run(monkeypatch, tmp_path, llm, clock_readings=readings)

    assert result.status == "incomplete"
    assert result.summary == ""
    assert "empty deliverable" in (result.error or "")
    assert registry.executed == ["read_url"]
