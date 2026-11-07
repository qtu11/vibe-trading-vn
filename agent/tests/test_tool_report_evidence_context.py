"""Only the invoking run may supply evidence to a report tool."""

from types import SimpleNamespace

import pytest

from src.agent.tool_context import current_grounding
from src.agent.tool_lifecycle import ToolCallLifecycle


@pytest.mark.parametrize("readonly", [False, True])
@pytest.mark.parametrize("fails", [False, True])
def test_tool_gets_own_ledger_and_restores_context_even_on_error(readonly, fails):
    ledger, parent = object(), object()
    seen = []

    def execute(name, arguments):
        seen.append(current_grounding.get())
        if fails:
            raise RuntimeError("tool failed")
        return "ok"

    loop = SimpleNamespace(
        _grounding=ledger,
        _is_tool_readonly=lambda name: readonly,
        _emit=lambda *args: None,
        registry=SimpleNamespace(execute=execute),
    )
    token = current_grounding.set(parent)
    try:
        if fails:
            with pytest.raises(RuntimeError, match="tool failed"):
                ToolCallLifecycle._invoke_tool(
                    loop, "export_research_report", {"run_id": "untrusted-other-run"}, call_id="call"
                )
        else:
            result, _ = ToolCallLifecycle._invoke_tool(loop, "export_research_report", {}, call_id="call")
            assert result == "ok"
        assert seen == [ledger]
        assert current_grounding.get() is parent
    finally:
        current_grounding.reset(token)
