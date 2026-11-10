"""The actual agent loop must finish an attempted export before claiming delivery."""

import json
from types import SimpleNamespace

import pytest
from pypdf import PdfWriter

from src.agent.loop import AgentLoop
from src.agent.tools import ToolRegistry
from src.reporting.tool import ExportResearchReportTool
from src.tools.report_artifacts import publish_report_artifact


class ExportTool(ExportResearchReportTool):
    def __init__(self, results):
        self.results = results
        self.calls = 0

    def execute(self, **kwargs):
        result = self.results[min(self.calls, len(self.results) - 1)]
        self.calls += 1
        return json.dumps(result)


class FinishingModel:
    model_name = "offline"

    def __init__(self, repair=False, formats=None):
        self.calls = 0
        self.repair = repair
        self.formats = formats or ["pdf"]

    def stream_chat(self, messages, **kwargs):
        self.calls += 1
        export = self.calls == 1 or self.calls == 3 and self.repair
        return SimpleNamespace(
            content="" if export else "Đã hoàn thành báo cáo.",
            reasoning_content=None,
            has_tool_calls=export,
            tool_calls=[SimpleNamespace(id=f"export-{self.calls}", name="export_research_report",
                                        arguments={"report": {}, "formats": self.formats})] if export else [],
        )


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBE_TRADING_HOME", str(tmp_path / "runtime"))


@pytest.fixture
def artifact(tmp_path):
    path = tmp_path / "research.pdf"
    writer = PdfWriter()
    writer.add_blank_page(595, 842)
    writer.write(path)
    return publish_report_artifact(path)


def run_agent(tmp_path, results, *, repair=False, formats=None):
    tool = ExportTool(results)
    registry = ToolRegistry()
    registry.register(tool)
    model = FinishingModel(repair=repair, formats=formats)
    events = []
    loop = AgentLoop(registry=registry, llm=model, max_iterations=6,
                     event_callback=lambda name, data: events.append((name, data)))
    loop.memory.run_dir = str(tmp_path / "run")
    result = loop.run("Xuất báo cáo nghiên cứu thành PDF.")
    return result, tool, events


FAILURE = {"ok": False, "error_code": "EVIDENCE_VALIDATION_FAILED",
           "message": "Source URL does not match this run", "accepted_report": {}}


def test_loop_recovers_export_before_accepting_a_prose_final(tmp_path, artifact):
    result, tool, events = run_agent(tmp_path, [FAILURE, {"ok": True, "artifacts": [artifact]}], repair=True)
    assert tool.calls == 2
    assert result["status"] == "success"
    assert artifact["download_url"] in result["content"]
    assert any(name == "text_delta" and artifact["download_url"] in data["delta"] for name, data in events)


def test_export_failure_cannot_end_as_successful_delivery(tmp_path):
    result, tool, _ = run_agent(tmp_path, [FAILURE])
    assert result["status"] == "failed"
    assert result["reason"].startswith("report_delivery_incomplete")
    assert "Đã hoàn thành báo cáo" not in result["content"]
    assert "PDF" in result["content"]
    assert result["iterations"] <= 4


def test_claimed_success_with_no_registered_file_is_not_delivery(tmp_path):
    fake = {"report_id": "a" * 32, "filename": "invented.pdf", "download_url": "/api/reports/" + "a" * 32}
    result, _, _ = run_agent(tmp_path, [{"ok": True, "artifacts": [fake]}])
    assert result["status"] == "failed"
    assert fake["download_url"] not in result["content"]


def test_valid_receipt_is_delivered_even_if_model_omits_the_link(tmp_path, artifact):
    result, tool, _ = run_agent(tmp_path, [{"ok": True, "artifacts": [artifact]}])
    assert tool.calls == 1
    assert result["status"] == "success"
    assert artifact["download_url"] in result["content"]


def test_partial_export_keeps_download_but_does_not_hide_missing_format(tmp_path, artifact):
    result, _, _ = run_agent(tmp_path, [{"ok": False, "status": "partial", "artifacts": [artifact]}],
                             formats=["docx", "pdf"])
    assert result["status"] == "failed"
    assert result["reason"] == "report_delivery_incomplete: docx"
    assert "DOCX" in result["content"]
    assert artifact["download_url"] in result["content"]


def test_new_question_does_not_inherit_previous_export_requirements(tmp_path):
    registry = ToolRegistry()
    registry.register(ExportTool([FAILURE]))
    loop = AgentLoop(registry=registry, llm=FinishingModel(), max_iterations=6)
    loop.memory.run_dir = str(tmp_path / "run")
    assert loop.run("Xuất báo cáo thành PDF.")["status"] == "failed"
    result = loop.run("Giải thích phương pháp nghiên cứu.")
    assert result["status"] == "success"
    assert "report_delivery_incomplete" not in result.get("reason", "")
