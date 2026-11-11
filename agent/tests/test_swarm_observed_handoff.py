"""Real runtime/worker boundaries retain observed sources without trusting prose."""

import copy
import json
import threading
import time
from pathlib import Path

import pytest

from src.agent.grounding import GroundingLedger
from src.agent.tool_context import current_grounding
from src.agent.tools import BaseTool, ToolRegistry
from src.providers.chat import LLMResponse, ToolCallRequest
from src.swarm.models import SwarmAgentSpec, SwarmRun, SwarmTask
from src.swarm.store import SwarmStore
import src.swarm.runtime as runtime_module
import src.swarm.worker as worker
from src.tools.read_file_tool import ReadFileTool


class FilingRead(BaseTool):
    name = "read_url"

    def execute(self, **kwargs):
        return json.dumps({"status": "ok", "url": "https://issuer.example/filing",
                           "title": "Issuer filing", "content": "Revenue was 120 VND in FY2025."})


class ReportWrite(BaseTool):
    name = "write_file"
    is_readonly = False

    def execute(self, **kwargs):
        Path(kwargs["run_dir"], "report.md").write_text("A completed equity analysis.", encoding="utf-8")
        return '{"status":"ok","bytes_written":28}'


def _script(monkeypatch, seen, *, only_write=False):
    registry = ToolRegistry()
    registry.register(FilingRead())
    registry.register(ReportWrite())
    registry.register(ReadFileTool())
    monkeypatch.setattr(worker, "build_swarm_registry", lambda *a, **k: registry)

    class Model:
        def __init__(self, model_name=None):
            self.model_name = model_name
            self.calls = 0

        def stream_chat(self, messages, **kwargs):
            seen.setdefault(self.model_name, []).append(copy.deepcopy(messages))
            self.calls += 1
            if self.model_name == "analyst" and self.calls == 1:
                name = "write_file" if only_write else "read_url"
                return LLMResponse(tool_calls=[ToolCallRequest(id="same-call", name=name, arguments={})])
            return LLMResponse(content="The filing supports the business analysis. The target remains an assumption, not a verified fact. [S999] https://model-only.example/fake")

        def close(self):
            pass

    monkeypatch.setattr(worker, "ChatLLM", Model)


def _runtime(tmp_path, monkeypatch, *, downstream=True):
    store = SwarmStore(base_dir=tmp_path / "swarm")
    runtime = runtime_module.SwarmRuntime(store=store)
    agents = [SwarmAgentSpec(id="analyst", role="Analyst", system_prompt="Read evidence.",
                            model_name="analyst", tools=["read_url", "write_file", "read_file"], max_retries=0)]
    tasks = [SwarmTask(id="facts", agent_id="analyst", prompt_template="Read the filing.")]
    if downstream:
        agents.append(SwarmAgentSpec(id="editor", role="Editor", system_prompt="Review {upstream_context}",
                                     model_name="editor", tools=["read_file"], max_retries=0))
        tasks.append(SwarmTask(id="review", agent_id="editor", prompt_template="Review the evidence.",
                               depends_on=["facts"], input_from={"facts": "facts"}))
    run = SwarmRun(id="observed-run", preset_name="offline", created_at="2026-11-10T00:00:00Z",
                  agents=agents, tasks=tasks)
    monkeypatch.setattr(runtime_module, "build_run_from_preset", lambda *a: run)
    monkeypatch.setattr(runtime, "_prefetch_grounding_data", lambda *a: None)
    return store, runtime, run


def test_runtime_threads_handoff_actual_sources_and_readable_copies(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    seen = {}
    _script(monkeypatch, seen)
    store, runtime, run = _runtime(tmp_path, monkeypatch)
    ledger = GroundingLedger(run_dir=tmp_path / "parent", user_message="Review TCB.VN")
    token = current_grounding.set(ledger)
    try:
        runtime.start_run("offline", {})
    finally:
        current_grounding.reset(token)
    deadline = time.monotonic() + 5
    while store.load_run(run.id).status.value in {"pending", "running"}:
        assert time.monotonic() < deadline
        time.sleep(0.01)
    assert store.load_run(run.id).status.value == "completed"
    receipt = ledger.swarm_run_receipt(run.id)
    assert receipt["tasks"][0]["data_tool_calls"] == 1
    assert [s.url for s in ledger.sources] == ["https://issuer.example/filing"]
    source_id = ledger.sources[0].source_id
    first_result = next(m for m in seen["analyst"][1] if m["role"] == "tool")
    assert json.loads(first_result["content"])["_sources"][0]["id"] == source_id
    prompt = seen["editor"][0][0]["content"]
    assert source_id in prompt and "shared-observations" in prompt
    own = store.run_dir(run.id) / "artifacts" / "editor" / "review"
    copied = list(own.glob("shared-observations/*/*.txt"))
    assert copied
    read = json.loads(ReadFileTool().execute(path=str(copied[0]), run_dir=str(own)))
    assert "Revenue was 120 VND" in read["content"]
    assert list((ledger.run_dir / "artifacts" / "swarm-observations").rglob("*.txt"))
    assert all(s.url != "https://model-only.example/fake" for s in ledger.sources)


def test_writing_report_does_not_count_as_a_data_read(tmp_path, monkeypatch):
    _script(monkeypatch, {}, only_write=True)
    _, _, run = _runtime(tmp_path, monkeypatch, downstream=False)
    result = worker.run_worker(agent_spec=run.agents[0], task=run.tasks[0],
                               upstream_summaries={}, user_vars={}, run_dir=tmp_path)
    assert result.status == "incomplete"
    assert "data" in result.error


@pytest.mark.parametrize("iterations,expected", [(1, "incomplete"), (2, "completed")])
def test_source_read_requires_a_following_model_analysis(tmp_path, monkeypatch, iterations, expected):
    _script(monkeypatch, {})

    class Model:
        model_name = "offline"

        def __init__(self, **kwargs):
            self.calls = 0

        def stream_chat(self, messages, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return LLMResponse(content="The business has meaningful operating risks and uncertain demand.",
                                   tool_calls=[ToolCallRequest(id="filing", name="read_url", arguments={})])
            return LLMResponse(content="The observed filing supports the operating analysis; demand remains an assumption.")

        def close(self):
            pass

    monkeypatch.setattr(worker, "ChatLLM", Model)
    _, _, run = _runtime(tmp_path, monkeypatch, downstream=False)
    run.agents[0].max_iterations = iterations
    result = worker.run_worker(agent_spec=run.agents[0], task=run.tasks[0],
                               upstream_summaries={}, user_vars={}, run_dir=tmp_path)
    assert result.status == expected
    assert result.data_tool_calls == 1
    if expected == "incomplete":
        assert "analy" in result.error


@pytest.mark.parametrize("name,payload", [
    ("parallel_web_search", {"results": [{"url": "https://issuer.example", "snippet": "Revenue 100"}]}),
    ("web_search", {"results": ["Revenue 100"]}),
    ("search_symbol", {"symbol": "TCB.VN"}),
    ("get_stock_news", {"news": [{"url": "https://issuer.example/article", "summary": "Revenue 100"}]}),
    ("get_research_reports", {"reports": [{"title": "Research", "url": "https://issuer.example/report.pdf"}]}),
    ("technical_indicators", {"rsi": 50}),
    ("financial_rigor", {"result": 120}),
    ("read_url", {"status": "ok", "url": "https://issuer.example"}),
    ("read_document", {"status": "ok", "file": "filing.pdf", "text": ""}),
])
def test_discovery_calculation_or_empty_reader_is_not_a_data_read(name, payload):
    tool = FilingRead()
    tool.name = name
    assert not worker._has_data_observation(tool, json.dumps(payload))


def test_concurrent_observations_get_unique_source_ids_and_valid_artifact(tmp_path):
    ledger = GroundingLedger(run_dir=tmp_path, user_message="Review the sources")
    barrier = threading.Barrier(8)

    def observe(index):
        barrier.wait()
        ledger.ingest_tool_result(tool_name="read_url", arguments={}, call_id=f"reader-{index}",
                                  success=True, result=json.dumps({"status": "ok", "url": f"https://issuer.example/{index}",
                                                                  "content": f"Revenue {index + 100} VND"}))

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(observe, range(8)))
    assert len({s.source_id for s in ledger.sources}) == 8
    saved = json.loads((tmp_path / "artifacts" / "grounding_evidence.json").read_text(encoding="utf-8"))
    assert len(saved["sources"]) == 8


def test_shared_text_chunks_credit_delivery_and_reject_offloaded_or_changed_copy(tmp_path, monkeypatch):
    from src.swarm.observations import SwarmObservations
    from src.tools.source_documents import persist_document, current_document_coverage

    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    ledger = GroundingLedger(run_dir=tmp_path / "parent", user_message="Review filing")
    token = current_grounding.set(ledger)
    try:
        workspace = tmp_path / "reader"
        run_dir = tmp_path / "swarm"
        run_dir.mkdir()
        document = persist_document(source="https://issuer.example/full", content_type="text/plain",
                                    content_bytes=b"original source", full_text="Revenue 100 VND\n" * 1600,
                                    run_dir=workspace)
        observations = SwarmObservations(ledger, run_dir, "shared-chunks")
        observations.record(tool_name="read_url", arguments={}, result=json.dumps({
            "status": "ok", "url": document["source"], "source_document": document,
            "content": "Revenue 100 VND",
        }), call_id="first", agent_id="reader", task_id="facts", artifact_dir=workspace)
        editor = tmp_path / "editor"
        prompt = observations.prepare(editor)
        copied = json.loads(prompt[prompt.index("["):])[0]["source_documents"][0]
        path = copied["full_text_path"]
        tool = ReadFileTool()
        too_large = tool.execute(path=path, run_dir=str(editor), max_chars=20000)
        assert not observations.trusted_read({"path": path}, too_large)
        assert not current_document_coverage(document)["text_delivery_complete"]
        offset = 0
        while offset is not None:
            result = tool.execute(path=path, run_dir=str(editor), offset=offset, max_chars=7000)
            assert observations.trusted_read({"path": path}, result)
            offset = json.loads(result)["next_offset"]
        assert current_document_coverage(document)["complete"]
        Path(path).write_text("model replacement", encoding="utf-8")
        assert not observations.trusted_read({"path": path}, tool.execute(path=path, run_dir=str(editor)))
    finally:
        current_grounding.reset(token)


def test_shared_result_parts_still_fit_the_actual_read_file_envelope(tmp_path, monkeypatch):
    from src.agent.result_artifacts import save_result_parts, TOOL_RESULT_LIMIT

    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    paths = save_result_parts("source content " * 2000, tmp_path / "parts", tmp_path)
    for path in paths:
        result = ReadFileTool().execute(path=path, run_dir=str(tmp_path))
        assert len(result) <= TOOL_RESULT_LIMIT


def test_search_result_part_cannot_be_laundered_into_a_data_read(tmp_path, monkeypatch):
    from src.swarm.observations import SwarmObservations, current_observations

    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    ledger = GroundingLedger(run_dir=tmp_path / "parent", user_message="Research issuer")
    run_dir = tmp_path / "swarm"
    run_dir.mkdir()
    observations = SwarmObservations(ledger, run_dir, "search-only")
    token = current_grounding.set(ledger)
    observed_token = current_observations.set(observations)
    try:
        observations.record(tool_name="web_search", arguments={}, result=json.dumps({
            "status": "ok", "results": [{"url": "https://issuer.example", "snippet": "Revenue 100"}],
        }), call_id="discovery", agent_id="searcher", task_id="discovery", artifact_dir=tmp_path)
        tools = ToolRegistry()
        tools.register(ReadFileTool())
        monkeypatch.setattr(worker, "build_swarm_registry", lambda *a, **k: tools)

        class Model:
            model_name = "offline"

            def __init__(self, **kwargs):
                self.calls = 0

            def stream_chat(self, messages, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    copied = json.loads(messages[0]["content"].rsplit("\n", 1)[-1])
                    return LLMResponse(tool_calls=[ToolCallRequest(
                        id="read-discovery", name="read_file", arguments={"path": copied[0]["parts"][0]})])
                return LLMResponse(content="The business has operating risks and uncertain demand. [S1]")

            def close(self):
                pass

        monkeypatch.setattr(worker, "ChatLLM", Model)
        result = worker.run_worker(agent_spec=SwarmAgentSpec(
            id="analyst", role="Analyst", system_prompt="Read the issuer source.",
            tools=["web_search", "read_file"], max_iterations=3,
        ), task=SwarmTask(id="facts", agent_id="analyst", prompt_template="Research"),
                                  upstream_summaries={}, user_vars={}, run_dir=run_dir)
        assert result.status == "incomplete"
        assert result.data_tool_calls == 0
    finally:
        current_observations.reset(observed_token)
        current_grounding.reset(token)

