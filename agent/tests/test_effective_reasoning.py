from types import SimpleNamespace

import pytest

from src.providers.chat import effective_reasoning_effort


@pytest.mark.parametrize("adapter,expected", [
    (SimpleNamespace(reasoning_effort="high"), "high"),
    (SimpleNamespace(reasoning={"effort":"xhigh"}), "xhigh"),
    (SimpleNamespace(extra_body={"reasoning":{"effort":"medium"}}), "medium"),
    (SimpleNamespace(reasoning_effort=None), ""),
    (SimpleNamespace(extra_body={"reasoning":"provider-managed"}), ""),
])
def test_runtime_reports_only_effort_actually_set_on_adapter(adapter, expected):
    assert effective_reasoning_effort(adapter) == expected


def test_codex_omitted_none_is_not_reported_as_an_applied_effort():
    from src.providers.openai_codex import DEFAULT_CODEX_URL, OpenAICodexLLM

    adapter = OpenAICodexLLM(model="gpt-6-sol", reasoning_effort="none", codex_url=DEFAULT_CODEX_URL)
    assert effective_reasoning_effort(adapter) == ""
    assert "reasoning" not in adapter._body([{"role": "user", "content": "Hi"}], stream=False)


def test_cli_ignored_level_is_not_reported_as_an_applied_effort():
    from src.providers.claude_cli import ClaudeCliLLM

    assert effective_reasoning_effort(ClaudeCliLLM(reasoning_effort="none")) == ""
    assert effective_reasoning_effort(ClaudeCliLLM(reasoning_effort="xhigh")) == "xhigh"
