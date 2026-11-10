"""Session history regressions for completed-attempt tool trails."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api_server
from src.session.events import EventBus
from src.session.models import Attempt, Message, Session
from src.session.service import SessionService
from src.session.store import SessionStore


class _DummyIndex:
    def index_session(self, session_id: str, title: str) -> None:
        del session_id, title

    def index_message(self, session_id: str, role: str, content: str) -> None:
        del session_id, role, content


def _service(tmp_path: Path, monkeypatch) -> SessionService:
    monkeypatch.setattr("src.session.service.get_shared_index", lambda: _DummyIndex())
    return SessionService(
        store=SessionStore(tmp_path / "sessions"),
        event_bus=EventBus(),
        runs_dir=tmp_path / "runs",
    )


def test_restart_keeps_tools_observed_before_service_task_shutdown(tmp_path, monkeypatch):
    import threading

    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    cancelled = threading.Event()

    class ShutdownAgent:
        def __init__(self, *, event_callback, **kwargs):
            from types import SimpleNamespace

            self.callback = event_callback
            self.memory = SimpleNamespace(run_dir=str(tmp_path / "runs" / "fpt-running"))

        def run(self, **kwargs):
            self.callback("tool_call", {"tool": "read_file", "call_id": "fpt-source", "arguments": {"path": "fpt.json"}})
            self.callback("tool_result", {"tool": "read_file", "call_id": "fpt-source", "status": "ok", "preview": "Evidence read"})
            self.callback("text_delta", {"delta": "Partial FPT analysis"})
            started.set()
            release.wait(10)
            finished.set()
            return {"status": "success", "content": "Final FPT analysis"}

        def cancel(self):
            cancelled.set()

    monkeypatch.setattr("src.tools.build_registry", lambda **kwargs: object())
    monkeypatch.setattr("src.providers.chat.ChatLLM", lambda: object())
    monkeypatch.setattr("src.memory.persistent.PersistentMemory", lambda: object())
    monkeypatch.setattr("src.agent.loop.AgentLoop", ShutdownAgent)
    monkeypatch.setattr("src.config.loader.load_runtime_agent_config", lambda overrides=None: object())
    monkeypatch.setattr("src.config.loader.sanitize_session_overrides", lambda overrides: dict(overrides))

    async def scenario():
        service = _service(tmp_path, monkeypatch)
        session = service.create_session(title="shutdown trail")
        sent = await service.send_message(session.session_id, "Analyze FPT")
        task = service._active_tasks[session.session_id]
        try:
            assert await asyncio.to_thread(started.wait, 3)
            assert service.store.get_attempt(session.session_id, sent["attempt_id"]).run_dir == str(tmp_path / "runs" / "fpt-running")
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert cancelled.is_set(), "task shutdown must cancel the underlying agent"
            assert session.session_id in service._active_loops
            assert session.session_id in service._inflight
            worker = service._agent_workers[session.session_id]
            cleanup = next(callback for callback in worker._done_callbacks
                           if callback.__name__ == "release_finished_worker")
            second = _service(tmp_path, monkeypatch)
            assert service.store.get_message_for_attempt(session.session_id, sent["attempt_id"]) is None
            from src.session.service import SessionBusyError

            with pytest.raises(SessionBusyError):
                await second.send_message(session.session_id, "Do not overlap the live worker")
        finally:
            release.set()
            assert await asyncio.to_thread(finished.wait, 3)
            for _ in range(100):
                if session.session_id not in service._inflight:
                    break
                await asyncio.sleep(0.01)
        assert session.session_id not in service._inflight
        _service(tmp_path, monkeypatch)
        reply = service.store.get_message_for_attempt(session.session_id, sent["attempt_id"])
        assert reply is not None
        assert [entry["call_id"] for entry in reply.tool_trail] == ["fpt-source"]
        assert reply.tool_trail[0]["status"] == "ok"
        # The worker and task both schedule cleanup; a delayed second callback
        # must not remove a later run's handle or release its execution claim.
        from concurrent.futures import Future

        replacement = Future()
        service._reserve_session(session.session_id)
        service._agent_workers[session.session_id] = replacement
        try:
            cleanup(worker)
            assert service._agent_workers.get(session.session_id) is replacement
            assert session.session_id in service._inflight
        finally:
            service._agent_workers.pop(session.session_id, None)
            service._release_session(session.session_id)

    asyncio.run(scenario())


def test_completed_attempt_tool_trail_round_trips_through_history_endpoint(
    tmp_path: Path,
    monkeypatch,
) -> None:
    service = _service(tmp_path, monkeypatch)
    session = Session(session_id="abcdef012345", title="tool trail")
    service.store.create_session(session)
    attempt = Attempt(
        attempt_id="attempt00001",
        session_id=session.session_id,
        prompt="Inspect AAPL",
    )
    service.store.create_attempt(attempt)
    expected_trail = [
        {
            "tool": "get_market_data",
            "status": "ok",
            "arguments": {"symbol": "AAPL"},
            "elapsed_ms": 125,
            "preview": "AAPL 195.00",
            "call_id": "call-market-1",
            "timestamp": 1_785_342_400_000,
        }
    ]

    async def _run_with_agent(*args, **kwargs):
        del args, kwargs
        return {
            "status": "success",
            "content": "AAPL is trading near 195.",
            "tool_trail": expected_trail,
        }

    monkeypatch.setattr(service, "_run_with_agent", _run_with_agent)
    asyncio.run(service._run_attempt(session, attempt))

    monkeypatch.setattr(api_server, "_get_session_service", lambda: service)
    client = TestClient(api_server.app, client=("127.0.0.1", 50000))
    response = client.get(f"/sessions/{session.session_id}/messages")

    assert response.status_code == 200
    stored = service.store.get_messages(session.session_id)[0]
    assert isinstance(stored, Message)
    assert stored.tool_trail == expected_trail
    payload = response.json()
    assert len(payload) == 1
    metadata = payload[0].pop("metadata")
    assert metadata["status"] == "completed"
    assert isinstance(metadata["elapsed_ms"], int)
    assert metadata["elapsed_ms"] >= 0
    assert payload == [
        {
            "message_id": stored.message_id,
            "session_id": session.session_id,
            "role": "assistant",
            "content": "AAPL is trading near 195.",
            "created_at": stored.created_at,
            "linked_attempt_id": attempt.attempt_id,
            "tool_trail": expected_trail,
        }
    ]


@pytest.mark.parametrize(
    ("run_status", "attempt_status"),
    [("failed", "failed"), ("cancelled", "cancelled")],
)
def test_unfinished_attempt_keeps_its_tool_trail(
    tmp_path: Path, monkeypatch, run_status: str, attempt_status: str
) -> None:
    """A failed run's steps survive a reload; they used to be saved as ``[]``.

    The history then read "failed · 0 steps" for a run that stopped on
    ``no_progress`` after eight rounds of tool calls.
    """
    service = _service(tmp_path, monkeypatch)
    session = Session(session_id="abcdef012346", title="failed trail")
    service.store.create_session(session)
    attempt = Attempt(attempt_id="attempt00002", session_id=session.session_id, prompt="Compare games")
    service.store.create_attempt(attempt)
    trail = [
        {"tool": "get_financial_statements", "status": "ok", "arguments": {"code": "002555.SZ"},
         "call_id": "call-1", "timestamp": 1_785_342_400_000},
        {"tool": "get_financial_statements", "status": "error", "arguments": {"code": "09999.HK"},
         "call_id": "call-2", "timestamp": 1_785_342_401_000},
    ]

    async def _run_with_agent(*args, **kwargs):
        del args, kwargs
        return {"status": run_status, "reason": "no_progress: stopped", "tool_trail": trail}

    monkeypatch.setattr(service, "_run_with_agent", _run_with_agent)
    asyncio.run(service._run_attempt(session, attempt))

    stored = service.store.get_messages(session.session_id)[0]
    assert stored.metadata["status"] == attempt_status
    assert stored.tool_trail == trail


def test_missing_report_format_keeps_the_verified_partial_delivery(tmp_path, monkeypatch):
    service = _service(tmp_path, monkeypatch)
    session = Session(session_id="abcdef012349", title="partial export")
    service.store.create_session(session)
    attempt = Attempt(attempt_id="attempt00009", session_id=session.session_id, prompt="Export PDF and DOCX")
    service.store.create_attempt(attempt)
    content = "Chưa hoàn tất DOCX.\n\n[research.pdf](/api/reports/" + "a" * 32 + ")"

    async def run_with_agent(*args, **kwargs):
        return {"status": "failed", "reason": "report_delivery_incomplete: docx", "content": content}

    monkeypatch.setattr(service, "_run_with_agent", run_with_agent)
    asyncio.run(service._run_attempt(session, attempt))
    stored = service.store.get_messages(session.session_id)[0]
    assert stored.metadata["status"] == "failed"
    assert content in stored.content


def test_run_with_agent_consolidates_tool_events_by_call_id(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class _DummyAgentLoop:
        def __init__(
            self,
            *,
            registry,
            llm,
            event_callback,
            max_iterations,
            persistent_memory,
        ) -> None:
            del registry, llm, max_iterations, persistent_memory
            self._event_callback = event_callback

        def run(self, *, user_message: str, history, session_id: str):
            del user_message, history, session_id
            self._event_callback(
                "tool_call",
                {
                    "tool": "get_market_data",
                    "call_id": "call-1",
                    "arguments": {"symbol": "AAPL"},
                },
            )
            self._event_callback(
                "tool_call",
                {
                    "tool": "get_market_data",
                    "call_id": "call-2",
                    "arguments": {"symbol": "MSFT"},
                },
            )
            self._event_callback(
                "tool_result",
                {
                    "tool": "get_market_data",
                    "call_id": "call-2",
                    "status": "ok",
                    "elapsed_ms": 20,
                    "preview": "MSFT",
                },
            )
            self._event_callback(
                "tool_result",
                {
                    "tool": "get_market_data",
                    "call_id": "call-1",
                    "status": "error",
                    "elapsed_ms": 10,
                    "preview": "AAPL unavailable",
                },
            )
            return {"status": "success", "content": "done"}

        def cancel(self) -> None:
            pass

    monkeypatch.setattr("src.tools.build_registry", lambda **kwargs: object())
    monkeypatch.setattr("src.providers.chat.ChatLLM", lambda: object())
    monkeypatch.setattr("src.memory.persistent.PersistentMemory", lambda: object())
    monkeypatch.setattr("src.agent.loop.AgentLoop", _DummyAgentLoop)
    monkeypatch.setattr(
        "src.config.loader.load_runtime_agent_config",
        lambda overrides=None: object(),
    )
    monkeypatch.setattr(
        "src.config.loader.sanitize_session_overrides",
        lambda overrides: dict(overrides),
    )
    service = _service(tmp_path, monkeypatch)
    attempt = Attempt(session_id="abcdef012345", prompt="compare")

    result = asyncio.run(
        service._run_with_agent(attempt, messages=[], session_config={})
    )

    assert [
        {
            key: entry[key]
            for key in (
                "tool",
                "call_id",
                "arguments",
                "status",
                "elapsed_ms",
                "preview",
            )
        }
        for entry in result["tool_trail"]
    ] == [
        {
            "tool": "get_market_data",
            "call_id": "call-1",
            "arguments": {"symbol": "AAPL"},
            "status": "error",
            "elapsed_ms": 10,
            "preview": "AAPL unavailable",
        },
        {
            "tool": "get_market_data",
            "call_id": "call-2",
            "arguments": {"symbol": "MSFT"},
            "status": "ok",
            "elapsed_ms": 20,
            "preview": "MSFT",
        },
    ]


def test_web_search_research_payload_survives_a_reload(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A reloaded session can still open the AI-search result.

    The research payload used to travel only over the live SSE stream, so a
    reloaded session rendered the search row again but offered no way to open
    it: the right-hand pane stayed empty.
    """

    class _DummyAgentLoop:
        def __init__(
            self,
            *,
            registry,
            llm,
            event_callback,
            max_iterations,
            persistent_memory,
        ) -> None:
            del registry, llm, max_iterations, persistent_memory
            self._event_callback = event_callback

        def run(self, *, user_message: str, history, session_id: str):
            del user_message, history, session_id
            self._event_callback(
                "tool_call",
                {
                    "tool": "parallel_web_search",
                    "call_id": "call-search-1",
                    "arguments": {"query": "VIC Q3 2026"},
                },
            )
            self._event_callback(
                "tool_result",
                {
                    "tool": "parallel_web_search",
                    "call_id": "call-search-1",
                    "status": "ok",
                    "elapsed_ms": 3000,
                    "preview": '{"status": "ok"}',
                    "research": {
                        "tool": "parallel_web_search",
                        "query": "VIC Q3 2026",
                        "summary_markdown": "### Tổng hợp",
                        "sources": [
                            {"url": "https://example.com/a", "title": "A"},
                            {"url": "https://example.com/b", "title": "B"},
                        ],
                    },
                },
            )
            return {"status": "success", "content": "done"}

        def cancel(self) -> None:
            pass

    monkeypatch.setattr("src.tools.build_registry", lambda **kwargs: object())
    monkeypatch.setattr("src.providers.chat.ChatLLM", lambda: object())
    monkeypatch.setattr("src.memory.persistent.PersistentMemory", lambda: object())
    monkeypatch.setattr("src.agent.loop.AgentLoop", _DummyAgentLoop)
    monkeypatch.setattr(
        "src.config.loader.load_runtime_agent_config",
        lambda overrides=None: object(),
    )
    monkeypatch.setattr(
        "src.config.loader.sanitize_session_overrides",
        lambda overrides: dict(overrides),
    )
    service = _service(tmp_path, monkeypatch)
    attempt = Attempt(session_id="abcdef012345", prompt="research")

    result = asyncio.run(
        service._run_with_agent(attempt, messages=[], session_config={})
    )

    entry = result["tool_trail"][0]
    assert entry["research"] == {
        "tool": "parallel_web_search",
        "query": "VIC Q3 2026",
        "summary_markdown": "### Tổng hợp",
        "sources": [
            {"url": "https://example.com/a", "title": "A"},
            {"url": "https://example.com/b", "title": "B"},
        ],
    }


def test_failed_tool_result_keeps_no_research_payload(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Only a successful search produced a result, so only it carries one."""

    class _DummyAgentLoop:
        def __init__(
            self,
            *,
            registry,
            llm,
            event_callback,
            max_iterations,
            persistent_memory,
        ) -> None:
            del registry, llm, max_iterations, persistent_memory
            self._event_callback = event_callback

        def run(self, *, user_message: str, history, session_id: str):
            del user_message, history, session_id
            self._event_callback(
                "tool_call",
                {
                    "tool": "parallel_web_search",
                    "call_id": "call-search-2",
                    "arguments": {"query": "VIC"},
                },
            )
            self._event_callback(
                "tool_result",
                {
                    "tool": "parallel_web_search",
                    "call_id": "call-search-2",
                    "status": "error",
                    "elapsed_ms": 10,
                    "preview": "boom",
                    "research": {
                        "tool": "parallel_web_search",
                        "query": "VIC",
                        "sources": [{"url": "https://example.com/a"}],
                    },
                },
            )
            return {"status": "success", "content": "done"}

        def cancel(self) -> None:
            pass

    monkeypatch.setattr("src.tools.build_registry", lambda **kwargs: object())
    monkeypatch.setattr("src.providers.chat.ChatLLM", lambda: object())
    monkeypatch.setattr("src.memory.persistent.PersistentMemory", lambda: object())
    monkeypatch.setattr("src.agent.loop.AgentLoop", _DummyAgentLoop)
    monkeypatch.setattr(
        "src.config.loader.load_runtime_agent_config",
        lambda overrides=None: object(),
    )
    monkeypatch.setattr(
        "src.config.loader.sanitize_session_overrides",
        lambda overrides: dict(overrides),
    )
    service = _service(tmp_path, monkeypatch)
    attempt = Attempt(session_id="abcdef012345", prompt="research")

    result = asyncio.run(
        service._run_with_agent(attempt, messages=[], session_config={})
    )

    assert "research" not in result["tool_trail"][0]
