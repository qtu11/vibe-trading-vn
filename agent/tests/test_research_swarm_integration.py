"""Exercise the automatic route, real preset/runtime and observed worker handoff."""

import json
import threading
from pathlib import Path

from src.agent.loop import AgentLoop
from src.agent.tools import BaseTool, ToolRegistry
from src.providers.chat import LLMResponse, ToolCallRequest
from src.tools.read_file_tool import ReadFileTool
from src.tools.swarm_tool import SwarmTool
import src.swarm.worker as worker
import src.swarm.runtime as runtime_module
import src.tools.swarm_tool as tool_module


def test_real_research_team_reads_shared_sources_and_resumes_one_run(tmp_path, monkeypatch):
    from src.tools.source_documents import persist_document, document_result

    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    monkeypatch.setattr("src.swarm.store.swarm_runs_root", lambda: tmp_path / "swarm")
    monkeypatch.setattr("src.config.load_swarm_agent_config", lambda: None)
    monkeypatch.setattr(runtime_module.SwarmRuntime, "_prefetch_grounding_data", lambda *a: None)
    monkeypatch.setattr(tool_module, "_POLL_INTERVAL_SECONDS", 0.01)
    release = threading.Event()
    waits, started, order, source_ids = [], [], [], []

    def wait_budget():
        waits.append(True)
        if len(waits) < 4:
            return 0
        release.set()
        return 5

    monkeypatch.setattr(tool_module, "_max_wait_seconds", wait_budget)
    # Four windows: the initial call plus three resumes, beyond the old fixed
    # two-resume budget. The computed window count is covered separately.
    monkeypatch.setattr("src.agent.loop.review_wait_windows", lambda: 4)
    original_start = runtime_module.SwarmRuntime.start_run

    def start(runtime, *args, **kwargs):
        run = original_start(runtime, *args, **kwargs)
        started.append(run.id)
        return run

    monkeypatch.setattr(runtime_module.SwarmRuntime, "start_run", start)

    class FilingRead(BaseTool):
        name = "read_url"

        def execute(self, **kwargs):
            text = "Primary filing: the business faces transition risks and uncertain demand."
            document = persist_document(source="https://issuer.example/filing", content_type="text/plain",
                                        content_bytes=text.encode(), full_text=text,
                                        coverage={"extraction_complete": True}, run_dir=kwargs["run_dir"])
            return json.dumps(document_result({"status": "ok", "url": document["source"],
                                               "source_document": document}, text_field="content"))

    def registry(*args, **kwargs):
        tools = ToolRegistry()
        tools.register(FilingRead())
        tools.register(ReadFileTool())
        return tools

    monkeypatch.setattr(worker, "build_swarm_registry", registry)

    class WorkerModel:
        model_name = "offline-worker"

        def __init__(self, **kwargs):
            self.calls = 0

        def stream_chat(self, messages, **kwargs):
            self.calls += 1
            system = messages[0]["content"]
            role = system.split("\n")[2]
            if self.calls == 1:
                order.append(role)
                if role == "Source analyst":
                    assert release.wait(3), "The next wait window must resume this run"
                    call = ToolCallRequest(id="actual-read", name="read_url", arguments={})
                else:
                    observations = json.loads(system.rsplit("\n", 1)[-1])
                    source_ids.append(observations[0]["source_ids"])
                    document = observations[0]["source_documents"][0]
                    call = ToolCallRequest(id="actual-read", name="read_file",
                                           arguments={"path": document["full_text_path"], "max_chars": 7000})
                return LLMResponse(tool_calls=[call])
            if role == "Source analyst":
                result = next(message for message in messages if message["role"] == "tool")
                source_ids.append([row["id"] for row in json.loads(result["content"])["_sources"]])
            return LLMResponse(content="The filing supports transition risk analysis; demand remains uncertain. [S1]")

        def close(self):
            pass

    monkeypatch.setattr(worker, "ChatLLM", WorkerModel)

    class ParentModel:
        model_name = "offline-parent"

        def stream_chat(self, messages, **kwargs):
            receipt = loop._grounding.swarm_run_receipts()[0]
            assert receipt["status"] == "completed"
            assert all(task["data_tool_calls"] > 0 for task in receipt["tasks"])
            payload = json.loads(next(message["content"] for message in reversed(messages)
                                      if message["role"] == "tool" and message.get("name") == "run_swarm"))
            assert payload["_sources"][0]["id"] == "S1"
            assert payload["_sources"][0]["url"] == "https://issuer.example/filing"
            document = payload["source_documents"][0]
            assert Path(document["full_text_path"]).is_relative_to(loop._grounding.run_dir)
            assert payload["evidence_parts"]
            for path in [document["full_text_path"], *payload["evidence_parts"]]:
                observed = json.loads(ReadFileTool().execute(path=path, run_dir=str(loop._grounding.run_dir)))
                assert "transition risks" in observed["content"]
            assert "source_documents" not in receipt
            order.append("parent")
            return LLMResponse(content="The filing identifies transition risk and uncertainty in demand. [S1]")

    tools = ToolRegistry()
    tools.register(SwarmTool())
    loop = AgentLoop(registry=tools, llm=ParentModel(), max_iterations=2)
    loop.memory.run_dir = str(tmp_path / "parent")
    result = loop.run("Deep research climate transition risks using primary web sources")
    assert result["status"] == "success", result.get("reason")
    assert order == ["Source analyst", "Domain analyst", "Critical reviewer", "Research editor", "parent"]
    assert len(started) == 1 and len(waits) == 4
    assert result["research_workflow"]["review_run_id"] == started[0]
    assert source_ids == [["S1"]] * 4
    assert [row.url for row in loop._grounding.sources] == ["https://issuer.example/filing"]
