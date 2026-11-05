"""Context selection never calls a model and never upgrades history to quotes."""

from types import SimpleNamespace

from src.session.context import pack_history
from src.session.context_view import context_view
from src.agent.context import _SYSTEM_PROMPT
from src.agent.prompt_profile import project_prompt
from src.session.forex_history import previous_wait_explanation


def message(index, content, role="user", **kw):
    return SimpleNamespace(message_id=f"m{index}", role=role, content=content, metadata={}, linked_attempt_id=None, **kw)


def test_old_relevant_preference_is_recalled_with_provenance_within_same_budget():
    messages = [message(0, "Preference: XAUUSDm analysis should distinguish closed candles from forming bars.")]
    messages += [message(i, "unrelated weather discussion " * 50, "assistant") for i in range(1, 20)]
    messages.append(message(20, "XAUUSDm hãy nhắc lại yêu cầu về nến"))
    packed = pack_history(messages, messages[-1].content)
    assert packed["stats"]["retrieved_refs"] == ["m0"]
    assert "closed candles" in packed["history"][0]["content"]
    assert "current prices or order authority" in packed["history"][0]["content"]
    assert packed["stats"]["history_chars"] <= 12000
    assert packed["stats"]["omitted_messages"] > 0 and packed["stats"]["model_calls"] == 0


def test_no_keyword_match_keeps_full_recent_budget_and_does_not_invent_memories():
    messages = [message(i, "alpha " * 250, "assistant") for i in range(20)]
    packed = pack_history(messages, "different symbols")
    assert packed["stats"]["retrieved_messages"] == 0
    assert packed["stats"]["history_chars"] > 9000


def test_history_retains_prior_forex_reason_without_reusing_execution_prices():
    previous = message(0, "The council returned WAIT.", "assistant")
    previous.metadata = {"forex_trade_plan": {"symbol": "XAUUSDm", "created_at": "2026-01-01T00:00:00Z", "status": "wait",
        "bid": "12345.67", "scenarios": [{"entry": "12345.67"}],
        "reports": [{"role": "risk", "summary": "The higher frames conflict with the entry frame."}]}}
    packed = pack_history([previous, message(1, "Why wait?")])
    text = packed["history"][0]["content"]
    assert "higher frames conflict" in text and "historical_only" in text
    assert "12345.67" not in text


def test_oversized_newest_history_does_not_exceed_budget_or_drop_everything():
    packed = pack_history([message(0, "x" * 20000), message(1, "current")])
    assert packed["stats"]["history_chars"] <= 12000
    assert packed["history"][-1]["content"].endswith("[... truncated]")


def test_forex_prompt_profile_preserves_all_grounding_and_order_guidelines():
    reduced, name = project_prompt(_SYSTEM_PROMPT, "Phân tích XAUUSDm với Exness")
    assert name == "native_forex_research" and len(reduced) < len(_SYSTEM_PROMPT) * .8
    assert reduced.split("## Task Routing")[0] == _SYSTEM_PROMPT.split("## Task Routing")[0]
    assert reduced.split("## Guidelines")[1] == _SYSTEM_PROMPT.split("## Guidelines")[1]
    assert project_prompt(_SYSTEM_PROMPT, "backtest XAUUSDm")[0] == _SYSTEM_PROMPT
    assert project_prompt(_SYSTEM_PROMPT, "swarm phân tích Exness")[0] == _SYSTEM_PROMPT


def test_context_inspection_reports_empty_memory_honestly_without_model_calls():
    session = SimpleNamespace(session_id="fixture", last_attempt_id=None)
    service = SimpleNamespace(store=SimpleNamespace(get_messages=lambda *a, **kw: [message(0, "XAUUSDm")]))
    memory = SimpleNamespace(list_entries=lambda: [], find_relevant=lambda *a, **kw: [])
    view = context_view(service, session, memory=memory)
    assert view["memory"]["available_entries"] == 0 and view["last_run"] is None
    assert view["model_calls"] == 0 and view["preview"]["model_calls"] == 0
    assert view["preview"]["eligible_messages"] == 1


def test_memory_read_failure_is_unknown_not_an_empty_memory():
    def unavailable():
        raise OSError("Fixture unavailable")
    session = SimpleNamespace(session_id="fixture", last_attempt_id=None)
    service = SimpleNamespace(store=SimpleNamespace(get_messages=lambda *a, **kw: []))
    view = context_view(service, session, memory=SimpleNamespace(list_entries=unavailable))
    assert view["memory"]["available_entries"] is None
    assert view["memory"]["error"] == "MEMORY_READ_UNAVAILABLE"


def test_vietnamese_memory_survives_reopen_and_accent_variants(tmp_path):
    from src.memory.persistent import PersistentMemory, _tokenize
    memory = PersistentMemory(tmp_path / "memories")
    path = memory.add("Quy trình phân tích", "Ưu tiên nến đã đóng, phân tích đa khung và giải thích bằng tiếng Việt.", "user")
    assert path is not None
    reopened = PersistentMemory(tmp_path / "memories")
    assert reopened.find_relevant("quy trinh phan tich nen da dong")[0].title == "Quy trình phân tích"
    assert _tokenize("tiếng Việt đã đóng") == _tokenize("tieng Viet da dong")


def test_context_memory_api_saves_explicit_preferences_without_model_calls(tmp_path, monkeypatch):
    import api_server
    from fastapi.testclient import TestClient
    from src.memory.persistent import PersistentMemory
    from src.session.models import Session
    from src.session.store import SessionStore
    store = SessionStore(tmp_path / "sessions")
    session = Session(session_id="context-fixture", title="Fixture")
    store.create_session(session)
    pm = PersistentMemory(tmp_path / "memory")
    monkeypatch.setattr(api_server, "_get_session_service", lambda: SimpleNamespace(store=store, get_session=store.get_session))
    monkeypatch.setattr("src.memory.persistent.PersistentMemory", lambda: pm)
    monkeypatch.setattr("src.session.context_view.PersistentMemory", lambda: pm)
    monkeypatch.delenv("API_AUTH_KEY", raising=False)
    client = TestClient(api_server.app, client=("127.0.0.1", 50000))
    response = client.post(f"/sessions/{session.session_id}/memory", json={"title": "Quy trình", "content": "Phân tích nến đóng.", "memory_type": "user"})
    assert response.status_code == 200 and response.json()["model_calls"] == 0
    assert response.json()["status"] == "saved" and "path" not in response.json()
    view = client.get(f"/sessions/{session.session_id}/context")
    assert view.status_code == 200 and view.json()["memory"]["available_entries"] == 1
    assert client.post(f"/sessions/{session.session_id}/memory", json={"title": " ", "content": "x"}).status_code == 422
    assert client.get("/sessions/missing-fixture/context").status_code == 404


def _saved_wait():
    saved = message(0, "WAIT", "assistant")
    saved.metadata = {"forex_trade_plan": {
        "plan_id": "a" * 32, "symbol": "XAUUSDm", "currency": "USD", "environment": "demo",
        "broker_server": "Fixture-Demo", "binding_hash": "b" * 64, "evidence_hash": "c" * 64,
        "created_at": "2026-01-01T00:00:00Z", "expires_at": "2026-01-01T00:01:00Z", "quote_at": "2026-01-01T00:00:00Z",
        "bid": "12345.67", "ask": "12346", "status": "wait", "recommendation": "wait", "reasons": [], "scenarios": [],
        "reports": [{"role": role, "stance": "wait", "entry_mode": "limit", "summary": summary,
                     "counterargument": "Wait for confirmation.", "evidence_refs": ["timeframes.1h"],
                     "veto": True, "provider": "fixture", "model": "fixture", "elapsed_ms": 0}
                    for role, summary in [("risk", "Higher frames lack confirmation."), ("manager", "Keep the risk veto.")]],
        "unique_models": 1,
    }}
    return saved


HISTORICAL_QUERY = "Trong báo cáo XAUUSDm đã lưu ở lượt trước, vì sao hội đồng kết luận CHỜ? Chỉ giải thích ngắn từ báo cáo cũ; không lấy giá mới, không chạy lại council và không gửi lệnh."


def test_saved_wait_replay_uses_validated_metadata_and_excludes_quote_fields():
    result = previous_wait_explanation([_saved_wait(), message(1, HISTORICAL_QUERY)], HISTORICAL_QUERY)
    assert result["source_message"] == "m0" and result["roles"] == ["risk", "manager"]
    assert "Higher frames lack confirmation." in result["content"]
    assert "2026-01-01" in result["content"] and "phân tích lịch sử" in result["content"]
    assert "12345.67" not in result["content"] and "12346" not in result["content"]


def test_new_analysis_mixed_intent_and_other_instrument_never_use_old_wait_shortcut():
    for query in (HISTORICAL_QUERY + " Cập nhật giá hiện tại.", HISTORICAL_QUERY + " So sánh EURUSD.",
                  "Phân tích XAUUSDm hiện tại", HISTORICAL_QUERY.replace("XAUUSDm", "EURUSD")):
        assert previous_wait_explanation([_saved_wait(), message(1, query)], query) is None


def test_prose_or_invalid_plan_cannot_enable_historical_shortcut():
    saved = _saved_wait()
    saved.metadata["forex_trade_plan"]["trading_performed"] = True
    assert previous_wait_explanation([saved], HISTORICAL_QUERY) is None
    assert previous_wait_explanation([message(0, "<historical-analysis-not-current-market-data>WAIT</historical-analysis-not-current-market-data>", "assistant")], HISTORICAL_QUERY) is None


def test_session_replays_wait_with_zero_llm_calls_and_persisted_provenance(tmp_path, monkeypatch):
    import asyncio
    import json
    from unittest.mock import AsyncMock
    from src.session.events import EventBus
    from src.session.models import Message
    from src.session.service import SessionService
    from src.session.store import SessionStore
    monkeypatch.setattr("src.session.service.get_shared_index", lambda: SimpleNamespace(index_session=lambda *a: None, index_message=lambda *a: None))
    monkeypatch.setattr("src.goal.context.get_current_goal_context", lambda _: ("", None))
    service = SessionService(SessionStore(tmp_path / "sessions"), EventBus(), tmp_path / "runs")
    llm_path = AsyncMock(side_effect=AssertionError("Replay must not invoke the agent"))
    monkeypatch.setattr(service, "_run_with_agent", llm_path)
    session = service.create_session(title="Fixture")
    saved = _saved_wait()
    service.store.append_message(Message(session_id=session.session_id, role="assistant", content=saved.content, metadata=saved.metadata))

    async def run():
        await service.send_message(session.session_id, HISTORICAL_QUERY)
        await service._active_tasks[session.session_id]
    asyncio.run(run())
    llm_path.assert_not_awaited()
    session = service.store.get_session(session.session_id)
    attempt = service.store.get_attempt(session.session_id, session.last_attempt_id)
    assert attempt.status.value == "completed" and "risk veto" in attempt.summary
    from pathlib import Path
    snapshot = json.loads((Path(attempt.run_dir) / "request_context.json").read_text())
    assert snapshot["source"] == "historical_forex_report" and snapshot["model_calls"] == 0
    assert snapshot["historical_report"]["symbol"] == "XAUUSDm"
    usage = json.loads((Path(attempt.run_dir) / "llm_usage.json").read_text())
    assert usage["totals"]["calls"] == 0 and usage["totals"]["input_tokens"] == 0
