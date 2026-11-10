"""The right-hand pane opens an AI-search result as its own tab.

The extractor lives in ``tool_lifecycle`` because that is where the tool
result is turned into the SSE ``tool_result`` event the frontend reads.
These tests pin the shapes the pane depends on.
"""

from __future__ import annotations

import json

from src.agent.tool_lifecycle import MAX_RESEARCH_SOURCES, _research_payload


def test_parallel_web_search_results_become_a_research_payload() -> None:
    result = json.dumps(
        {
            "primary_query": "VIC.VN HOSE phân tích cổ phiếu",
            "results": [
                {
                    "url": "https://vneconomy.vn/vn-index-tang-gan-8-diem",
                    "title": "VN-Index tăng gần 8 điểm",
                    "snippet": "VIC nâng đổ chỉ số",
                    "source": "VnEconomy",
                },
                {
                    "url": "https://example.com/vic-q3",
                },
            ],
            "summary_markdown": "## Kết luận\n- VIC tăng trần.",
        },
        ensure_ascii=False,
    )

    payload = _research_payload("parallel_web_search", result)

    assert payload is not None
    assert payload["tool"] == "parallel_web_search"
    assert payload["query"] == "VIC.VN HOSE phân tích cổ phiếu"
    assert payload["summary_markdown"].startswith("## Kết luận")
    assert len(payload["sources"]) == 2
    assert payload["sources"][0]["url"] == "https://vneconomy.vn/vn-index-tang-gan-8-diem"
    assert payload["sources"][0]["publisher"] == "VnEconomy"
    # A source with no title falls back to its URL, so the tab list is never
    # blank.
    assert payload["sources"][1]["title"] == "https://example.com/vic-q3"


def test_concurrent_scraper_sources_become_a_research_payload() -> None:
    result = json.dumps(
        {
            "query": "VIC Vingroup báo cáo tài chính",
            "sources": [
                {"url": "https://vneconomy.vn/a", "title": "A"},
                {"url": "https://vneconomy.vn/b", "title": "B"},
            ],
        },
        ensure_ascii=False,
    )

    payload = _research_payload("concurrent_scraper", result)

    assert payload is not None
    assert payload["tool"] == "concurrent_scraper"
    assert payload["query"] == "VIC Vingroup báo cáo tài chính"
    assert len(payload["sources"]) == 2


def test_a_result_without_any_usable_source_opens_no_tab() -> None:
    # Every entry lacks a URL, so there is nothing for the pane to open.
    result = json.dumps({"results": [{"title": "no url"}, {"url": "   "}]})

    assert _research_payload("parallel_web_search", result) is None


def test_a_non_json_or_empty_result_opens_no_tab() -> None:
    assert _research_payload("parallel_web_search", "not json") is None
    assert _research_payload("parallel_web_search", json.dumps([])) is None
    assert _research_payload("parallel_web_search", json.dumps({"results": []})) is None
    # A tool that returned prose rather than a payload has no sources.
    assert _research_payload("parallel_web_search", json.dumps({"answer": "text"})) is None


def test_the_source_list_is_capped_so_the_pane_stays_readable() -> None:
    sources = [{"url": f"https://example.com/{index}", "title": str(index)} for index in range(MAX_RESEARCH_SOURCES + 25)]
    result = json.dumps({"results": sources})

    payload = _research_payload("parallel_web_search", result)

    assert payload is not None
    assert len(payload["sources"]) == MAX_RESEARCH_SOURCES
