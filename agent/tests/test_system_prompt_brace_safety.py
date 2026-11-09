"""The system prompt must survive literal braces in its own text.

The prompt is assembled with ``str.format``. A JSON shape example written as
``{date, close, unit}`` is read as a placeholder, and the resulting
``KeyError`` fires while the prompt is being built -- before the run starts.
The user sees a failed turn with no research in it and no way to tell that a
brace in an instruction broke it.

The fix keeps the known placeholders working and leaves unknown brace text
as written, so no example can take a run down.
"""

from __future__ import annotations

import pytest

from src.agent.context import (
    _SYSTEM_PROMPT,
    ContextBuilder,
    _format_prompt_template,
)
from src.agent.memory import WorkspaceMemory
from src.agent.tools import ToolRegistry

pytestmark = pytest.mark.unit


def test_known_placeholders_are_still_substituted():
    rendered = _format_prompt_template(
        "a={alpha} b={beta}", alpha="A", beta="B"
    )
    assert rendered == "a=A b=B"


def test_unknown_braces_are_left_as_written():
    rendered = _format_prompt_template(
        "shape is {date, close, unit} and {alpha}",
        alpha="A",
    )
    assert "{date, close, unit}" in rendered
    assert "A" in rendered


def test_a_broken_brace_never_raises():
    """A stray brace must not crash prompt assembly."""
    for template in (
        "unbalanced {",
        "unbalanced }",
        "{{double}}",
        "}{",
    ):
        rendered = _format_prompt_template(template, alpha="A")
        assert isinstance(rendered, str)


def test_the_real_system_prompt_builds():
    """The shipped prompt is the one that matters."""
    prompt = ContextBuilder(ToolRegistry(), WorkspaceMemory()).build_system_prompt("anything")
    assert "Output Principles" in prompt
    assert "{tool_descriptions}" not in prompt


def test_the_shipped_prompt_contains_no_unsubstituted_placeholders():
    """Every placeholder the prompt declares must be filled in."""
    prompt = ContextBuilder(ToolRegistry(), WorkspaceMemory()).build_system_prompt("anything")
    for placeholder in (
        "{tool_descriptions}",
        "{tool_count}",
        "{skill_count}",
        "{data_source_count}",
        "{skill_descriptions}",
        "{memory_section}",
        "{strategy_discovery_routing}",
    ):
        assert placeholder not in prompt, f"{placeholder} was never substituted"


def test_prompt_text_never_contains_literal_brace_examples():
    """Guard the template against the crash coming back.

    The template is formatted with ``str.format``; any literal brace in it is
    a placeholder. A JSON example has to be written with doubled braces, or
    written without them at all.
    """
    import re

    # Find every brace expression in the template and check it is one of the
    # declared placeholders. Doubled braces ("{{" / "}}") are escaped and
    # render as a literal brace, so they are skipped.
    declared = {
        "tool_descriptions",
        "tool_count",
        "skill_count",
        "data_source_count",
        "skill_descriptions",
        "memory_section",
        "strategy_discovery_routing",
    }
    for match in re.finditer(r"(?<!\{)\{([^{}]*)\}(?!\})", _SYSTEM_PROMPT):
        name = match.group(1)
        assert name in declared, f"literal brace in the prompt template: {{{name}}}"
