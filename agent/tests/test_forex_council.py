"""Synthetic, read-only council contracts; no broker/LLM credentials or network."""

from copy import deepcopy
from datetime import timedelta
import json
from types import SimpleNamespace

import pytest

from src.trading.forex.council import TradePlan, candidates, council_answer, model_summary, run_council
from src.trading.forex.errors import ForexError
from src.trading.forex.models import Connection, number, utcnow


@pytest.fixture
def council():
    config = Connection(id="council-fixture", label="Fixture", connector="mt5", account_ref="12345",
        server="Fixture-Demo", terminal_path=r"C:\Fixture\terminal64.exe", session_mode="existing_terminal")
    quote = {"bid": "2000", "ask": "2000.2", "price_step": "0.05", "point": "0.01",
             "minimum_stop_distance": "0.15", "tradeable": True, "timestamp": utcnow().isoformat()}
    frame = {"status": "ok", "history_sufficient": True, "is_recent": True, "candle_count": 300,
             "first_bar": "2026-10-01T00:00:00+00:00", "last_bar": utcnow().isoformat(),
             "dataset_sha256": "b" * 64, "trend_alignment": "bullish_alignment",
             "indicators": {"atr_14": 4, "range_low_20": 1989, "range_high_20": 2005}}
    data = {"_meta": {"native_symbol": "XAUUSDm", "connection_id": config.id,
                     "medium_term_price_context_ready": True, "incomplete_timeframes": []},
            "_provenance": {"XAUUSDm": {"binding_hash": config.fingerprint(), "quote_currency": "USD"}},
            "_timeframes": {f: deepcopy(frame) for f in ("5m", "1h", "4h", "1d")},
            "_macro_context": {"dxy": {"status": "unavailable"}}}
    calls, reads = [], []

    def read(identifier, operation, **kwargs):
        assert identifier == config.id and operation == "quote", "Council must not execute writes"
        reads.append(operation)
        return {"data": deepcopy(quote)}

    service = SimpleNamespace(store=SimpleNamespace(connection=lambda _: config), read=read,
                              current_binding=lambda _: None)

    def model(messages, role):
        payload = json.loads(messages[-1]["content"])
        calls.append((role, payload))
        assert "12345" not in messages[-1]["content"]
        assert "terminal64" not in messages[-1]["content"]
        assert "binding_hash" not in messages[-1]["content"]
        assert "connection_id" not in messages[-1]["content"]
        refs = ["timeframes.1h"]
        if role == "risk":
            assert {"technical", "macro", "bull", "bear"} == set(payload["reports"])
            refs = ["report.bull", "report.bear"]
        if role == "manager":
            assert "risk" in payload["reports"]
            refs = ["report.risk"]
        mode = payload["requested_entry_mode"] if payload["requested_entry_mode"] != "auto" else "market"
        return json.dumps({"stance": "buy", "entry_mode": mode, "summary": "Luận điểm theo bằng chứng.",
            "counterargument": "Chờ nếu cấu trúc thay đổi.", "evidence_refs": refs, "veto": False}), {
                "provider": "fixture", "model": "fixture-model"}

    return data, quote, service, model, calls, reads


@pytest.mark.parametrize("mode", ["market", "limit", "auto"])
def test_six_real_calls_share_evidence_and_critic_consumes_opposing_reports(council, mode):
    data, quote, service, model, calls, reads = council
    plan = run_council(data, service, model=model, entry_mode=mode)
    assert len(calls) == 6 and reads == ["quote", "quote"]
    assert all(c[1]["market"] == calls[0][1]["market"] for c in calls)
    assert plan["status"] == "ready" and plan["recommendation"] == "buy"
    assert plan["unique_models"] == 1 and plan["trading_performed"] is False
    buy, sell = plan["scenarios"]
    assert buy["order_type"] == ("market" if mode == "auto" else mode)
    assert sell["order_type"] == "limit"  # alternative is not a simultaneous entry
    for s in plan["scenarios"]:
        for price in (s["entry"], s["stop_loss"], s["take_profit"]):
            assert number(price) % number(quote["price_step"]) == 0
        assert number(s["reward_risk"]) >= 2
    if mode == "limit":
        assert number(buy["entry"]) < number(quote["bid"])
    assert number(sell["entry"]) > number(quote["ask"])
    assert TradePlan.model_validate(plan).recommendation == "buy"


def test_every_role_usage_is_counted_and_parent_conversation_reaches_role_threads(council):
    from src.providers.session_context import bind_llm_session_id, current_llm_session_id, reset_llm_session_id

    data, _, service, model, *_ = council
    events = []
    def measured(messages, role):
        assert current_llm_session_id() == "context-fixture"
        text, info = model(messages, role)
        return text, {**info, "usage_metadata": {"input_tokens": 100, "output_tokens": 20,
            "total_tokens": 120, "input_token_details": {"cache_read": 60}}}
    token = bind_llm_session_id("context-fixture")
    try:
        plan = run_council(data, service, model=measured, usage_callback=lambda role, usage: events.append(role))
    finally:
        reset_llm_session_id(token)
    assert len(events) == 6 and plan["llm_usage"]["reported_calls"] == 6
    assert plan["llm_usage"]["totals"]["input_tokens"] == 600
    assert plan["llm_usage"]["totals"]["cache_read_tokens"] == 360
    assert plan["llm_usage"]["missing_calls"] == 0 and len(plan["reports"]) == 6


def test_invalid_role_output_still_has_usage_and_missing_usage_is_not_zero(council):
    data, _, service, model, *_ = council
    def invalid(messages, role):
        text, info = model(messages, role)
        return ("bad json" if role == "macro" else text), {**info, "usage_metadata": {"input_tokens": 100, "output_tokens": 20}}
    plan = run_council(data, service, model=invalid)
    assert plan["llm_usage"]["reported_calls"] == 2 and plan["llm_usage"]["totals"]["input_tokens"] == 200
    assert plan["status"] != "ready"
    missing = run_council(data, service, model=model)["llm_usage"]
    assert missing["totals"] is None and missing["missing_calls"] == 6


@pytest.mark.parametrize("failure", ["veto", "wait", "bad_refs", "missing_debate", "exception", "bad_json"])
def test_critic_failure_and_veto_cannot_be_overridden(council, failure):
    data, _, service, model, *_ = council

    def faulty(messages, role):
        if role != "risk":
            return model(messages, role)
        if failure == "exception":
            raise RuntimeError("Do not expose a provider request")
        if failure == "bad_json":
            return "not json", {"provider": "fixture", "model": "fixture-model"}
        text, info = model(messages, role)
        report = json.loads(text)
        if failure == "veto":
            report["veto"] = True
        elif failure == "wait":
            report["stance"] = "wait"
        else:
            report["evidence_refs"] = ["invented.news" if failure == "bad_refs" else "timeframes.1h"]
        return json.dumps(report), info

    plan = run_council(data, service, model=faulty)
    assert plan["status"] != "ready" and plan["recommendation"] == "wait"
    assert plan["reasons"] and plan["trading_performed"] is False
    if failure in {"bad_refs", "missing_debate", "bad_json", "exception"}:
        expected = {"bad_refs": "INVALID_EVIDENCE_REFS", "missing_debate": "INVALID_EVIDENCE_REFS",
                    "bad_json": "INVALID_JSON", "exception": "MODEL_REQUEST_FAILED"}[failure]
        assert plan["failures"] == [{"role": "risk", "code": expected}]


@pytest.mark.parametrize("failure", ["missing_step", "missing_stops", "old_quote", "incomplete_frame", "spread"])
def test_invalid_data_blocks_before_any_llm_call(council, failure):
    data, quote, service, model, calls, _ = council
    if failure == "missing_step":
        quote.pop("price_step")
    elif failure == "missing_stops":
        quote.pop("minimum_stop_distance")
    elif failure == "old_quote":
        quote["timestamp"] = (utcnow() - timedelta(minutes=5)).isoformat()
    elif failure == "incomplete_frame":
        data["_meta"]["incomplete_timeframes"] = ["1d"]
    else:
        quote["ask"] = "2002"
    plan = run_council(data, service, model=model)
    assert calls == [] and plan["status"] == "blocked" and plan["recommendation"] == "wait"
    assert not plan["scenarios"]


def test_price_drift_during_debate_requires_new_analysis(council):
    data, quote, service, model, *_ = council

    def moved(messages, role):
        result = model(messages, role)
        if role == "manager":
            quote.update(bid="2010", ask="2010.2")
        return result

    plan = run_council(data, service, model=moved)
    assert plan["status"] == "wait" and "PRICE_MOVED_REANALYZE" in plan["reasons"]


def test_manager_cannot_upgrade_risk_limit_to_immediate_market(council):
    data, _, service, model, *_ = council
    def limited(messages, role):
        text, info = model(messages, role)
        report = json.loads(text)
        if role == "risk":
            report["entry_mode"] = "limit"
        return json.dumps(report), info
    plan = run_council(data, service, model=limited)
    assert plan["recommendation"] == "wait" and "ENTRY_TIMING_NOT_APPROVED" in plan["reasons"]


@pytest.mark.parametrize("invalid", [False, True])
def test_ai_receives_actual_closed_candles_and_requires_a_typed_forecast(council, invalid):
    from src.trading.forex.price_action import candle_evidence
    from tests.test_forex_chart import bars

    data, _, service, model, *_ = council
    pa = candle_evidence(bars())
    for panel in data["_timeframes"].values():
        panel["price_action"] = deepcopy(pa)

    def forecasts(messages, role):
        payload = json.loads(messages[-1]["content"])
        view = payload["market"]["timeframes"]["5m"]["price_action"]
        if role == "technical":
            assert view["recent_candles"] == pa["recent_candles"]
        else:
            assert "recent_candles" not in view
            assert view["patterns"] == pa["patterns"]
        text, identity = model(messages, role)
        output = json.loads(text)
        if role in {"technical", "manager"} and not invalid:
            output["forecast"] = {"direction": "down", "timeframe": "5m", "horizon_bars": 6,
                                  "rationale": "Cấu trúc có điều kiện.", "invalidation": "Vô hiệu nếu giá đóng vượt vùng kháng cự."}
            output["evidence_refs"].append("timeframes.5m.price_action")
        return json.dumps(output), identity

    plan = run_council(data, service, model=forecasts)
    if invalid:
        assert plan["recommendation"] == "wait" and plan["failures"][0]["code"] == "INVALID_REPORT_SCHEMA"
    else:
        assert len(plan["reports"]) == 6 and not plan["failures"]
        assert plan["reports"][-1]["forecast"]["direction"] == "down"
        assert plan["evidence"]["timeframes"]["5m"]["price_action"]["forming_candle_used"] is False


def test_binding_change_during_debate_is_fatal(council):
    data, _, service, model, *_ = council

    def changed(messages, role):
        result = model(messages, role)
        if role == "manager":
            def reject(_):
                raise ForexError("BINDING_CHANGED", "Changed")
            service.current_binding = reject
        return result

    with pytest.raises(ForexError, match="Changed"):
        run_council(data, service, model=changed)


def test_plan_rejects_forged_ready_state_and_bad_limit_geometry(council):
    data, quote, service, model, *_ = council
    plan = run_council(data, service, model=model)
    forged = deepcopy(plan)
    forged["reports"][4]["veto"] = True
    with pytest.raises(ValueError):
        TradePlan.model_validate(forged)
    forged = deepcopy(plan)
    forged["scenarios"][1]["entry"] = "1999"
    with pytest.raises(ValueError):
        TradePlan.model_validate(forged)
    quote["price_step"] = "0"
    with pytest.raises(ValueError):
        candidates(data, quote)


def test_reply_cards_are_persisted_and_streamed_identically(council, tmp_path, monkeypatch):
    import asyncio
    from src.session.events import EventBus
    from src.session.models import Attempt, Session
    from src.session.service import SessionService
    from src.session.store import SessionStore

    data, _, broker, model, *_ = council
    plan = run_council(data, broker, model=model)
    index = SimpleNamespace(index_session=lambda *a: None, index_message=lambda *a: None)
    monkeypatch.setattr("src.session.service.get_shared_index", lambda: index)
    store, bus = SessionStore(tmp_path / "sessions"), EventBus()
    service = SessionService(store=store, event_bus=bus, runs_dir=tmp_path / "runs")
    session = Session(title="Council fixture")
    store.create_session(session)

    async def result(*args, **kwargs):
        return {"status": "success", "content": "Council completed.", "forex_trade_plan": plan}

    monkeypatch.setattr(service, "_run_with_agent", result)
    asyncio.run(service._run_attempt(session, Attempt(session_id=session.session_id, prompt="analyze")))
    assert store.get_messages(session.session_id)[-1].metadata["forex_trade_plan"] == plan
    assert bus.replay(session.session_id, replay_all=True)[-1].data["forex_trade_plan"] == plan


def test_council_release_is_number_free_and_still_passes_grounding(council, tmp_path):
    from src.agent.grounding.ledger import GroundingLedger

    data, _, broker, model, *_ = council
    plan = run_council(data, broker, model=model)
    text = council_answer(plan)
    assert not any(c.isdigit() for c in text)
    ledger = GroundingLedger(run_dir=tmp_path, user_message="Phân tích XAUUSDm")
    ledger.ingest_tool_result(tool_name="search_symbol", arguments={"query": "XAUUSDm"},
        result=json.dumps({"ok": True, "source": "symbol_search", "data": {"query": "XAUUSDm",
            "candidates": [{"symbol": "XAUUSDm", "native_symbol": "XAUUSDm", "market": "forex",
                "type": "cfd", "currency": "USD", "venue": "MT5", "source": "mt5",
                "connection_id": "council-fixture"}]}}), call_id="resolve", success=True)
    assert ledger.validate_final_answer(text).valid


def test_model_projection_keeps_full_plan_untouched_and_does_not_spool(council):
    from src.config.limits import TOOL_RESULT_LIMIT
    from src.tools.redaction import redact_tool_result

    data, quote, broker, model, *_ = council
    plan = run_council(data, broker, model=model)
    data["_trade_plan"] = plan
    data["_broker_quotes"] = {"XAUUSDm": quote}
    original = deepcopy(data)
    summary = model_summary(data)
    assert len(redact_tool_result(summary)) < TOOL_RESULT_LIMIT
    assert data == original
    projection = json.loads(summary)
    assert projection["_trade_plan"]["reports"][0] == {"role": "technical", "stance": "buy", "veto": False}


def test_readonly_http_plan_contract(council, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src.api.forex_routes import register_forex_routes
    from src.api.security import require_auth

    data, _, broker, model, *_ = council
    plan = run_council(data, broker, model=model)
    calls = []
    def fake(symbol, **kwargs):
        calls.append((symbol, kwargs))
        return plan
    monkeypatch.setattr("src.trading.forex.council.research_plan", fake)
    app = FastAPI()
    app.dependency_overrides[require_auth] = lambda: None
    register_forex_routes(app, broker)
    with TestClient(app) as client:
        result = client.post("/api/forex/research-plan", json={"symbol": "XAUUSDm", "connection_id": "council-fixture"})
        assert result.status_code == 200 and result.json() == plan
        assert client.post("/api/forex/research-plan", json={"symbol": "XAUUSDm", "connection_id": "council-fixture", "entry_mode": "stop"}).status_code == 422
    assert calls[0][0] == "XAUUSDm" and calls[0][1]["service"] is broker


@pytest.mark.asyncio
async def test_mcp_plan_is_readonly_and_pinned_to_process_account(council, monkeypatch):
    from fastmcp import Client
    from src.trading.forex.mcp_server import build_server

    data, _, broker, model, *_ = council
    plan = run_council(data, broker, model=model)
    calls = []
    def fake(symbol, **kwargs):
        calls.append((symbol, kwargs))
        return plan
    monkeypatch.setattr("src.trading.forex.council.research_plan", fake)
    server = build_server(broker, "council-fixture")
    tools = {t.name: t for t in await server.list_tools()}
    assert tools["forex_research_plan"].annotations.readOnlyHint
    assert "connection_id" not in tools["forex_research_plan"].parameters["properties"]
    assert "forex_submit_intent" not in tools
    async with Client(server) as client:
        result = await client.call_tool("forex_research_plan", {"symbol": "XAUUSDm", "entry_mode": "limit"})
        assert result.data == plan
    assert calls[0][1]["connection_id"] == "council-fixture"


@pytest.mark.parametrize("first_party", [True, False])
def test_agent_loop_releases_reviewed_cards_without_another_writer_and_rejects_lookalikes(council, tmp_path, first_party):
    from src.agent.loop import AgentLoop
    from src.agent.tools import BaseTool, ToolRegistry
    from src.providers.chat import LLMResponse, ToolCallRequest
    from src.tools.forex_market_tool import ForexMarketSnapshotTool

    data, quote, broker, model, *_ = council
    plan = run_council(data, broker, model=model)
    data["_trade_plan"] = plan
    data["_meta"]["context_version"] = 2
    data["_provenance"]["XAUUSDm"].update(source="mt5", environment="demo", native_symbol="XAUUSDm")
    data["_broker_quotes"] = {"XAUUSDm": {"bid": float(quote["bid"]), "ask": float(quote["ask"]),
        "spread": 0.2, "timestamp": quote["timestamp"], "source": "mt5", "is_fresh": True}}
    resolved = {"ok": True, "source": "symbol_search", "data": {"query": "XAUUSDm", "candidates": [
        {"symbol": "XAUUSDm", "native_symbol": "XAUUSDm", "market": "forex", "type": "cfd",
         "currency": "USD", "venue": "MT5", "source": "mt5", "connection_id": "council-fixture"}]}}

    class ResultTool(BaseTool):
        def __init__(self, name, result):
            self.name, self.result = name, result
        def execute(self, **kwargs):
            return json.dumps(self.result)

    registry = ToolRegistry()
    registry.register(ResultTool("search_symbol", resolved))
    tool = ForexMarketSnapshotTool() if first_party else ResultTool("get_forex_market_snapshot", data)
    tool.execute = lambda **kwargs: json.dumps(data)
    registry.register(tool)

    class Model:
        def __init__(self):
            self.calls = 0
        def stream_chat(self, messages, on_text_chunk=None, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return LLMResponse(tool_calls=[ToolCallRequest(id="resolve", name="search_symbol", arguments={"query": "XAUUSDm"})])
            if self.calls == 2:
                return LLMResponse(tool_calls=[ToolCallRequest(id="plan", name="get_forex_market_snapshot",
                    arguments={"symbol": "XAUUSDm", "connection_id": "council-fixture", "trade_plan": True})])
            text = "Chưa có kết quả nghiên cứu được xác thực."
            if on_text_chunk:
                on_text_chunk(text)
            return LLMResponse(content=text)

    writer = Model()
    loop = AgentLoop(registry=registry, llm=writer, max_iterations=4)
    loop.memory.run_dir = str(tmp_path)
    result = loop.run("Phân tích chiến lược XAUUSDm")
    assert result["status"] == "success", result
    if first_party:
        assert writer.calls == 2  # resolver and tool selection; no duplicate final writer
        assert result["forex_trade_plan"] == plan
        assert (tmp_path / "artifacts" / "forex_trade_plan.json").exists()
        evidence = json.loads((tmp_path / "artifacts" / "grounding_evidence.json").read_text(encoding="utf-8"))
        assert evidence["validations"][-1]["valid"] is True
    else:
        assert writer.calls == 3 and "forex_trade_plan" not in result
