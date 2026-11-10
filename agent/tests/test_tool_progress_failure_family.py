"""The export repair loop must stop early instead of burning eight rounds.

The screenshot's failure was seven ``export_research_report`` calls, each with
a *different* payload, each failing at the next schema rule. The exact-call
block cannot see that (the arguments differ every round), so a family block
groups the failures by tool + error code and stops the loop after a few
repairs of the same class.
"""

from __future__ import annotations

import json

from src.agent.tool_progress import (
    FAILURE_FAMILY_BLOCK_THRESHOLD,
    ToolProgress,
)


def _failure(code: str) -> str:
    return json.dumps({"ok": False, "error_code": code, "message": "Dữ liệu báo cáo không đúng chuẩn"})


def test_repair_loop_with_different_arguments_is_caught():
    progress = ToolProgress()
    for _ in range(FAILURE_FAMILY_BLOCK_THRESHOLD):
        progress.record(
            "export_research_report",
            ("export_research_report", json.dumps({"report": {"n": _}})),
            _failure("SCHEMA_VALIDATION_FAILED"),
            success=False,
            is_readonly=False,
        )
    assert progress.blocked_family("export_research_report") == "SCHEMA_VALIDATION_FAILED"


def test_below_threshold_does_not_block():
    progress = ToolProgress()
    for index in range(FAILURE_FAMILY_BLOCK_THRESHOLD - 1):
        progress.record(
            "export_research_report",
            ("export_research_report", json.dumps({"report": {"n": index}})),
            _failure("SCHEMA_VALIDATION_FAILED"),
            success=False,
            is_readonly=False,
        )
    assert progress.blocked_family("export_research_report") is None


def test_different_error_codes_are_separate_families():
    progress = ToolProgress()
    for index in range(FAILURE_FAMILY_BLOCK_THRESHOLD):
        progress.record(
            "export_research_report",
            ("export_research_report", json.dumps({"report": {"n": index}})),
            _failure("SCHEMA_VALIDATION_FAILED"),
            success=False,
            is_readonly=False,
        )
    for index in range(2):
        progress.record(
            "export_research_report",
            ("export_research_report", json.dumps({"other": index})),
            _failure("EVIDENCE_VALIDATION_FAILED"),
            success=False,
            is_readonly=False,
        )
    # The dominant family is blocked; the count is per code, not per tool.
    assert progress.blocked_family("export_research_report") == "SCHEMA_VALIDATION_FAILED"


def test_a_successful_mutation_clears_the_family():
    progress = ToolProgress()
    for index in range(FAILURE_FAMILY_BLOCK_THRESHOLD):
        progress.record(
            "export_research_report",
            ("export_research_report", json.dumps({"report": {"n": index}})),
            _failure("SCHEMA_VALIDATION_FAILED"),
            success=False,
            is_readonly=False,
        )
    assert progress.blocked_family("export_research_report") is not None
    progress.record(
        "write_file",
        ("write_file", "{}"),
        json.dumps({"status": "ok"}),
        success=True,
        is_readonly=False,
    )
    assert progress.blocked_family("export_research_report") is None


def test_non_repairable_failures_do_not_build_a_family():
    progress = ToolProgress()
    for index in range(FAILURE_FAMILY_BLOCK_THRESHOLD + 2):
        progress.record(
            "edit_file",
            ("edit_file", json.dumps({"path": f"missing-{index}"})),
            json.dumps({"status": "error", "error": "File not found"}),
            success=False,
            is_readonly=False,
        )
    assert progress.blocked_family("edit_file") is None


def test_new_readonly_evidence_preserves_terminal_exact_failure_block():
    progress = ToolProgress()
    key = ("get_financial_statements", '{"symbol":"VIC.VN"}')
    for _ in range(2):
        progress.record(
            key[0], key, _failure("statement_source_not_configured"), success=False,
        )
    progress.record(
        "read_url", ("read_url", "{}"), '{"status":"ok","content":"new evidence"}',
        success=True,
    )
    assert progress.is_blocked(key)
    assert progress.blocked_family(key[0]) is None


def test_oscillating_validation_errors_cannot_reopen_the_repair_budget():
    progress = ToolProgress()
    issues = [{"field": field, "problem": "missing"} for field in ["a", "b"]]
    for i, errors in enumerate([issues, issues[:1], issues, issues[:1], issues]):
        progress.record(
            "export_research_report", ("export_research_report", str(i)),
            json.dumps({"ok": False, "error_code": "SCHEMA_VALIDATION_FAILED", "field_errors": errors}),
            success=False, is_readonly=False,
        )
        progress.finish_iteration()
    assert progress.blocked_family("export_research_report") == "SCHEMA_VALIDATION_FAILED"
    assert progress.stalled_iterations == 3
