"""A provider that ignores transport timeouts cannot strand the session worker."""

import threading

import pytest

from src.agent.loop import AgentLoop
from src.agent.tools import ToolRegistry
from src.providers.chat import LLMResponse
from src.providers.session_context import current_llm_session_id


class BlockingProvider:
    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()
        self.calls = 0
        self.completed = 0
        self.session_ids = []

    def stream_chat(self, messages, **kwargs):
        self.calls += 1
        self.session_ids.append(current_llm_session_id())
        self.entered.set()
        self.release.wait()
        kwargs['on_text_chunk']('late provider text')
        kwargs['on_reasoning_chunk']('late provider reasoning')
        kwargs['on_waiting_chunk']()
        self.completed += 1
        if self.completed == self.calls:
            self.finished.set()
        return LLMResponse(content='late provider text')


@pytest.mark.parametrize('cancel', [False, True])
def test_blocked_provider_obeys_deadline_or_cancel_and_discards_late_callbacks(tmp_path, monkeypatch, cancel):
    monkeypatch.setattr('src.agent.tuning.LLM_TIMEOUT_SECONDS', 0 if cancel else 0.05, raising=False)
    monkeypatch.setattr('src.agent.tuning.STALL_TIMEOUT_SECONDS', 0, raising=False)
    monkeypatch.setattr('src.agent.tuning.STREAM_RETRY_DELAY_S', 0, raising=False)
    monkeypatch.setattr('src.agent.loop.RUNS_DIR', tmp_path)
    monkeypatch.setattr('src.agent.loop.SESSIONS_DIR', tmp_path / 'sessions')
    provider = BlockingProvider()
    events = []
    agent = AgentLoop(registry=ToolRegistry(), llm=provider, max_iterations=1,
                      event_callback=lambda kind, data: events.append((kind, dict(data))))
    result = []
    done = threading.Event()

    def run():
        try:
            result.append(agent.run('Hello', session_id='deadline-fixture'))
        finally:
            done.set()

    caller = threading.Thread(target=run, daemon=True)
    caller.start()
    try:
        assert provider.entered.wait(3)
        if cancel:
            agent.cancel()
        assert done.wait(1), 'A blocked provider still owns the agent/session executor'
        assert result[0]['status'] == ('cancelled' if cancel else 'failed')
        if not cancel:
            assert result[0]['error_code'] == 'provider_stream_error'
        assert provider.calls == (1 if cancel else 2)
        assert provider.session_ids == ['deadline-fixture'] * provider.calls
        before = list(events)
        provider.release.set()
        assert provider.finished.wait(1)
        assert events == before, 'Abandoned calls must not stream into the finished attempt'
    finally:
        provider.release.set()
        caller.join(2)
