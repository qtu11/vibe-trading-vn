"""Research progress follows evidence rather than echoed or local cache metadata.

Offline fixtures mirror first-party web_search and read_url envelopes. The
same answer under another query/backend or local cache age adds no source.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.agent.tool_progress import ToolProgress


def _search(progress: ToolProgress, query: str, results: list[dict], backend: str = "fixture") -> bool:
    progress.record(
        "web_search",
        ("web_search", json.dumps({"query": query}, sort_keys=True)),
        json.dumps({"status": "ok", "query": query, "backends": backend, "results": results}),
        success=True,
        is_readonly=True,
    )
    return progress.finish_iteration()


@pytest.mark.parametrize("results", [[], [{
    "title": "Synthetic annual report",
    "url": "https://example.test/annual-report",
    "snippet": "Revenue is unavailable in this synthetic search fixture.",
}]])
def test_rephrased_web_search_without_new_hits_consumes_stall_budget(results: list[dict]) -> None:
    progress = ToolProgress()
    assert _search(progress, "first query", results) is False
    for index in range(1, 8):
        assert _search(progress, f"rephrased query {index}", results, f"route-{index}") is False
    assert _search(progress, "eighth rephrasing", results, "another-route") is True
    assert progress.stalled_iterations == 8


def test_genuinely_changed_web_search_evidence_resets_stall_chain() -> None:
    progress = ToolProgress()
    original = [{"title": "Annual report", "url": "https://example.test/annual", "snippet": "Year 2025"}]
    assert _search(progress, "annual", original) is False
    assert _search(progress, "annual alternative wording", original) is False
    assert progress.stalled_iterations == 1

    updated = original + [{"title": "Quarterly report", "url": "https://example.test/quarter", "snippet": "Q1 2026"}]
    assert _search(progress, "quarter", updated) is False
    assert progress.stalled_iterations == 0


def test_changed_excerpt_from_the_same_document_is_new_evidence() -> None:
    progress = ToolProgress()
    original = [{"title": "Company filing", "url": "https://example.test/filing", "snippet": "Revenue: unavailable"}]
    assert _search(progress, "revenue", original) is False
    assert _search(progress, "revenue reworded", original) is False
    assert progress.stalled_iterations == 1

    updated = [{"title": "Company filing", "url": "https://example.test/filing", "snippet": "Revenue: revised disclosure"}]
    assert _search(progress, "revenue", updated) is False
    assert progress.stalled_iterations == 0


def test_other_tool_source_metadata_is_not_globally_discarded() -> None:
    progress = ToolProgress()
    for index in range(3):
        progress.record(
            "dated_source_query", ("dated_source_query", "{}"),
            json.dumps({"status": "ok", "query": f"period-{index}", "backends": f"source-{index}", "results": []}),
            success=True, is_readonly=True,
        )
        assert progress.finish_iteration() is False
        assert progress.stalled_iterations == 0


def _page(progress: ToolProgress, **changes: object) -> bool:
    payload = {
        "status": "ok", "url": "https://example.test/annual-report", "title": "Annual report",
        "content": "Synthetic report: no real financial data.", "length": 45,
        **changes,
    }
    progress.record("read_url", ("read_url", '{"url":"https://example.test/annual-report"}'),
                    json.dumps(payload), success=True, is_readonly=True)
    return progress.finish_iteration()


def test_same_page_with_changing_local_cache_age_consumes_stall_budget() -> None:
    progress = ToolProgress()
    assert _page(progress) is False
    for age in range(1, 8):
        assert _page(progress, memory_cached=True, cache_age_seconds=age) is False
    assert _page(progress, memory_cached=True, cache_age_seconds=8) is True
    assert progress.stalled_iterations == 8


def test_changed_page_content_at_the_same_url_is_new_evidence() -> None:
    progress = ToolProgress()
    assert _page(progress) is False
    assert _page(progress, memory_cached=True, cache_age_seconds=1) is False
    assert progress.stalled_iterations == 1
    assert _page(progress, content="Synthetic revised disclosure.", memory_cached=True, cache_age_seconds=2) is False
    assert progress.stalled_iterations == 0


def test_upstream_cache_disclosure_is_not_discarded_with_local_cache_age() -> None:
    progress = ToolProgress()
    assert _page(progress, cached=True) is False
    assert _page(progress, cached=True, memory_cached=True, cache_age_seconds=1) is False
    assert progress.stalled_iterations == 1
    assert _page(progress, cached=False, memory_cached=True, cache_age_seconds=2) is False
    assert progress.stalled_iterations == 0


def test_page_publication_timestamp_remains_part_of_source_evidence() -> None:
    progress = ToolProgress()
    assert _page(progress, published_at="2026-10-01T00:00:00Z") is False
    assert _page(progress, published_at="2026-10-01T00:00:00Z", memory_cached=True, cache_age_seconds=1) is False
    assert progress.stalled_iterations == 1
    assert _page(progress, published_at="2026-11-01T00:00:00Z", memory_cached=True, cache_age_seconds=2) is False
    assert progress.stalled_iterations == 0


def test_loop_stops_reworded_successful_empty_searches_offline(tmp_path: Path, monkeypatch) -> None:
    from src.agent.loop import AgentLoop
    from src.agent.tools import ToolRegistry
    from src.tools.web_search_tool import WebSearchTool

    calls: list[str] = []
    tool = WebSearchTool()

    def execute(**kwargs: object) -> str:
        query = str(kwargs["query"])
        calls.append(query)
        return json.dumps({"status": "ok", "query": query, "backends": "offline", "results": []})

    class OfflineSearchLLM:
        model_name = "offline-regression"
        count = 0

        def stream_chat(self, messages: list[dict], **kwargs: object) -> SimpleNamespace:
            self.count += 1
            return SimpleNamespace(
                content="", reasoning_content=None, has_tool_calls=True,
                tool_calls=[SimpleNamespace(id=f"search-{self.count}", name="web_search",
                                            arguments={"query": f"synthetic rephrasing {self.count}"})],
            )

    monkeypatch.setattr(tool, "execute", execute)
    registry = ToolRegistry()
    registry.register(tool)
    loop = AgentLoop(registry=registry, llm=OfflineSearchLLM(), max_iterations=24)
    run_dir = tmp_path / "offline-run"
    run_dir.mkdir()
    loop.memory.run_dir = str(run_dir)

    result = loop.run("Find a public document without making any external calls in this fixture.")

    assert result["status"] == "failed"
    assert result["iterations"] == 9  # First envelope is new; eight repeats consume the budget.
    assert len(calls) == 9
    assert "no_progress" in result["reason"]
    assert "web_search" in result["content"]
