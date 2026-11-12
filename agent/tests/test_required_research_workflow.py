"""Deep research must execute source-backed review before answer/export."""

import json
from types import SimpleNamespace

import pytest

from src.agent.loop import AgentLoop
from src.agent.tool_context import current_grounding
from src.agent.tools import BaseTool, ToolRegistry
from src.tools.swarm_tool import SwarmTool


class AnswerModel:
    model_name = "offline"

    def __init__(self, order):
        self.order = order

    def stream_chat(self, messages, **kwargs):
        self.order.append("answer")
        return SimpleNamespace(content="Nghiên cứu đã hoàn tất theo bằng chứng đã thu thập." + (" [S1]" if "review" in self.order else ""),
                               has_tool_calls=False, tool_calls=[], reasoning_content=None)


class ReviewTool(SwarmTool):
    def __init__(self, order, *, completed=True, data_reads=1):
        super().__init__()
        self.order = order
        self.completed = completed
        self.data_reads = data_reads

    def execute(self, **kwargs):
        self.order.append("review")
        ledger = current_grounding.get()
        ledger.ingest_tool_result(tool_name="read_url", arguments={"url": "https://example.com/filing"},
                                 result=json.dumps({"status": "ok", "url": "https://example.com/filing",
                                                    "content": "Primary filing describing the operating business and risks."}),
                                 call_id="observed-reader", success=True)
        from src.tools.source_documents import persist_document, record_source_delivery
        text = "Primary filing describing the operating business and risks."
        document = persist_document(source="https://example.com/filing", content_type="text/plain",
                                    content_bytes=text.encode(), full_text=text,
                                    coverage={"extraction_complete": True}, run_dir=ledger.run_dir)
        record_source_delivery(document, offset=0, returned_chars=len(text))
        receipt = {"run_id": "offline-review", "preset": kwargs["preset_name"],
                   "status": "completed" if self.completed else "failed", "tasks": [
                       {"agent_id": role, "status": "completed", "iterations": 1, "data_tool_calls": self.data_reads}
                       for role in ("source_analyst", "domain_analyst", "critical_reviewer", "research_editor")
                   ]}
        ledger.record_swarm_run("offline-review", receipt)
        return json.dumps(receipt)


def run(tmp_path, registry, order, prompt="Nghiên cứu chuyên sâu tác động của biến đổi khí hậu từ các nguồn web"):
    loop = AgentLoop(registry=registry, llm=AnswerModel(order), max_iterations=3)
    loop.memory.run_dir = str(tmp_path / "run")
    return loop.run(prompt)


def test_deep_research_runs_real_review_tool_before_parent_answer(tmp_path):
    order = []
    registry = ToolRegistry()
    registry.register(ReviewTool(order))
    result = run(tmp_path, registry, order)
    assert order[:2] == ["review", "answer"]
    assert result["status"] == "success"
    assert result["research_workflow"]["review_run_id"] == "offline-review"


def test_failed_review_cannot_release_a_completed_research_answer(tmp_path):
    order = []
    registry = ToolRegistry()
    registry.register(ReviewTool(order, completed=False))
    result = run(tmp_path, registry, order)
    assert order == ["review"]
    assert result["status"] == "failed"
    assert result["reason"].startswith("research_workflow_incomplete:")


def test_missing_review_tool_is_explicit_and_never_calls_parent_model(tmp_path):
    order = []
    result = run(tmp_path, ToolRegistry(), order)
    assert result["status"] == "failed"
    assert order == []
    assert "run_swarm" in result["reason"]


def test_simple_lookup_does_not_launch_a_research_team(tmp_path):
    order = []
    registry = ToolRegistry()
    registry.register(ReviewTool(order))
    run(tmp_path, registry, order, prompt="Giải thích thuật ngữ thị trường")
    assert "review" not in order


def test_model_named_tool_cannot_forge_a_review_receipt(tmp_path):
    class Impostor(BaseTool):
        name = "run_swarm"

        def execute(self, **kwargs):
            return json.dumps({"status": "completed", "preset": "deep_research_review"})

    registry = ToolRegistry()
    registry.register(Impostor())
    order = []
    result = run(tmp_path, registry, order)
    assert result["status"] == "failed"
    assert order == []


def test_four_reports_without_actual_data_reads_are_incomplete(tmp_path):
    registry = ToolRegistry()
    order = []
    registry.register(ReviewTool(order, data_reads=0))
    result = run(tmp_path, registry, order)
    assert order == ["review"]
    assert result["status"] == "failed"


def test_exhausted_goal_budget_cannot_start_the_research_team(tmp_path, monkeypatch):
    monkeypatch.setattr("src.agent.loop.get_current_goal_context", lambda _: ("Budgeted goal", "goal-id"))
    monkeypatch.setattr("src.goal.GoalStore", lambda: SimpleNamespace(
        get_goal_snapshot=lambda _: {"goal": {"token_budget": 1, "tokens_used": 1}}))
    order = []
    registry = ToolRegistry()
    registry.register(ReviewTool(order))
    loop = AgentLoop(registry=registry, llm=AnswerModel(order), max_iterations=2)
    loop.memory.run_dir = str(tmp_path / "run")
    result = loop.run("Deep research climate transition", session_id="budget-test")
    assert order == []
    assert result["reason"].startswith("goal_token_budget_exhausted:")


def test_requested_file_cannot_be_forgotten_before_any_export_attempt(tmp_path):
    registry = ToolRegistry()
    order = []
    registry.register(ReviewTool(order))
    result = run(tmp_path, registry, order, prompt="Nghiên cứu chuyên sâu thị trường và xuất file DOCX")
    assert result["status"] == "failed"
    assert result["reason"].startswith("report_delivery_incomplete:")


@pytest.mark.parametrize("prompt, required", [
    ("nghiên cứu phân tích TCB trên sàn HOSE, xuất file báo cáo dưới dạng docx", True),
    ("nghiên cứu phân tích tcb trên sàn hose, xuất file báo cáo dưới dạng docx", True),
    ("Phân tích TCB.VN và xuất báo cáo DOCX", True),
    ("Research TCB on HOSE and export an analysis report as DOCX", True),
    ("Research TCB stock and cite the filings", True),
    ("Research the company culture and summarize it", False),
    ("Giá TCB trên HOSE hôm nay?", False),
    ("Tóm tắt PDF kết quả TCB trên HOSE", False),
    ("Phân tích và báo cáo cổ phiếu TCB trên HOSE", True),
    ("Analyze the valuation of the company", True),
    ("Deep research climate transition risk", True),
    ("Giá cổ phiếu TCB hiện tại?", False),
    ("Tóm tắt PDF tại https://example.com/report.pdf", False),
    ("Chuyển file PDF sang DOCX", False),
    ("Nghiên cứu sâu source code và sửa lỗi", False),
])
def test_research_route_is_scoped_to_analysis(prompt, required):
    from src.agent.research_workflow import requires_research_review
    assert requires_research_review(prompt) is required


@pytest.mark.parametrize("prompt, expected", [
    ("Read the PDF report at https://example.com/report.pdf", set()),
    ("Phân tích báo cáo tại https://example.com/report.pdf", set()),
    ("Phân tích và xuất file DOCX và PDF", {"docx", "pdf"}),
    ("Create a PDF research report", {"pdf"}),
])
def test_file_delivery_tracks_requested_outputs_not_input_links(prompt, expected):
    from src.agent.research_workflow import requested_export_formats
    assert requested_export_formats(prompt) == expected


def test_export_refuses_missing_review_before_rendering(tmp_path, monkeypatch):
    from src.agent.grounding import GroundingLedger
    from src.reporting.service import ReportJobService
    from src.reporting.tool import ExportResearchReportTool

    ledger = GroundingLedger(run_dir=tmp_path, user_message="Phân tích cổ phiếu TCB và xuất báo cáo DOCX")
    monkeypatch.setattr(ReportJobService, "create_job", lambda *a, **k: pytest.fail("Premature rendering"))
    token = current_grounding.set(ledger)
    try:
        result = json.loads(ExportResearchReportTool().execute(report={"sources": []}, formats=["docx"]))
    finally:
        current_grounding.reset(token)
    assert result["error"]["code"] == "RESEARCH_REVIEW_INCOMPLETE"


def test_generic_completion_without_sources_cannot_release_deep_research(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    from src.agent.research_workflow import research_release_error
    from src.agent.grounding import GroundingLedger
    bound = GroundingLedger(run_dir=tmp_path / "guard", user_message="Deep research climate risks")
    token = current_grounding.set(bound)
    try:
        ReviewTool([]).execute(preset_name="deep_research_review")
    finally:
        current_grounding.reset(token)
    assert research_release_error(bound, content="Everything is complete.")["code"] == "SOURCE_CITATIONS_REQUIRED"


def test_review_preset_has_serial_roles_and_no_recursive_export():
    from src.swarm.presets import inspect_preset, load_preset
    from src.agent.research_workflow import REVIEW_PRESET, REVIEW_ROLES
    data = load_preset(REVIEW_PRESET)
    assert [row["id"] for row in data["agents"]] == list(REVIEW_ROLES)
    assert inspect_preset(REVIEW_PRESET)["valid"] is True
    assert len(inspect_preset(REVIEW_PRESET)["layers"]) == 4
    assert all(not ({"run_swarm", "export_research_report", "bash"} & set(row["tools"])) for row in data["agents"])


def test_review_roles_have_enough_wall_clock_for_evidence_review():
    """Review/editing roles must not be tighter than the analyst stages.

    A 900s reviewer timed out mid-analysis while the analysts had 1200s, so
    the review preset now gives every evidence-reading role the same full
    budget; the worker's wall-clock wrap-up protects the tail of that budget.
    """
    from src.swarm.presets import load_preset
    from src.agent.research_workflow import REVIEW_PRESET

    data = load_preset(REVIEW_PRESET)
    timeouts = {row["id"]: row["timeout_seconds"] for row in data["agents"]}
    assert timeouts["source_analyst"] >= 1200
    assert timeouts["domain_analyst"] >= 1200
    assert timeouts["critical_reviewer"] >= timeouts["domain_analyst"]
    assert timeouts["research_editor"] >= 1200


def test_review_wait_windows_cover_all_role_budgets():
    """The parent must not abandon a review the runtime still considers live.

    Each task may consume ``timeout * (retries + 1)`` plus capped retry
    backoff and the runtime's 60s layer buffer. ``SWARM_TIMEOUT`` is only the
    per-call wait window, so the resume count has to cover their sum.
    """
    from src.agent.research_workflow import REVIEW_PRESET, review_wait_windows
    from src.config.accessor import get_env_config
    from src.swarm.presets import load_preset

    data = load_preset(REVIEW_PRESET)
    agents = {row["id"]: row for row in data["agents"]}
    swarm = get_env_config().swarm
    total = sum(
        agents[task["agent_id"]]["timeout_seconds"]
        * (agents[task["agent_id"]]["max_retries"] + 1)
        + agents[task["agent_id"]]["max_retries"] * swarm.swarm_worker_retry_max_delay_s
        + 60
        for task in data["tasks"]
    )
    windows = review_wait_windows()
    assert windows >= 2
    assert windows * swarm.swarm_timeout >= total


def test_review_wait_windows_fall_back_when_preset_is_missing(monkeypatch):
    import src.agent.research_workflow as research_workflow

    def missing(_name):
        raise FileNotFoundError("preset disappeared")

    monkeypatch.setattr("src.swarm.presets.load_preset", missing)
    assert research_workflow.review_wait_windows() == 3
