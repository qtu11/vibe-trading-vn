"""Empirical A/B benchmark: the new pipeline against the current one.

The earlier harness compared a simulated 32.5 s baseline with an in-memory
CPU-only pipeline, so it measured nothing that happens in production. This
benchmark makes real network calls on both sides:

* **Baseline** — the flow the agent uses today: ``web_search`` (one engine
  chain) followed by one ``read_url`` call per result, each truncated to
  8,000 characters.
* **Treatment** — ``parallel_web_search`` (multi-engine, RRF) followed by
  ``concurrent_scraper`` (concurrent fetch, DOM clean, BM25 pruning,
  Map-Reduce synthesis).

Measured per side: wall-clock latency, tokens handed to the model, and how
many of the ground-truth figures survive into the final answer.

Run it with::

    .venv\\Scripts\\python agent/tests/benchmarks/web_tools/empirical_benchmark.py

The network-dependent numbers move with egress conditions; the token and
fact-retention numbers are the stable ones.
"""

from __future__ import annotations

import asyncio
import json
import os
import statistics
import sys
import time

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from typing import Any

from src.tools.optimizer import count_tokens
from src.tools.parallel_web_tools import (
    concurrent_scrape_and_synthesize_async,
    parallel_web_search_async,
)

#: A financial question with figures that a reader can check.
QUERY = "HPG ket qua kinh doanh quy 3 nam 2024 doanh thu loi nhuan"

#: The numbers a correct answer must carry.
#:
#: Taken from HPG's own Q3/2024 filing and the broker report that cites it:
#: net revenue 33,956 tỷ (rounded to 34,000 in the press), net profit after
#: tax 3,022 tỷ, gross margin 13.93%, 9-month net revenue 104,364 tỷ
#: (rounded to 105,000) and 9-month net profit 9,210 tỷ.
#:
#: The press rounds, so both spellings are accepted for a rounded figure.
GROUND_TRUTH = [
    ("34.000", "33.956", "34.100"),  # Q3/2024 net revenue, as published
    ("3.022",),                      # Q3/2024 net profit after tax
    ("13,9", "13.93", "13,8"),      # Q3/2024 gross margin
    ("105.000", "104.364", "104.500"),  # 9M/2024 net revenue
    ("9.210",),                     # 9M/2024 net profit after tax
]


def _fact_retention(text: str) -> tuple[int, list[str]]:
    """Count the ground-truth figures present in the answer text.

    A figure counts when any of its accepted spellings appears, because the
    press rounds the audited numbers. The text is checked twice: as it was
    written, and with the decimal and thousands marks swapped. The summary
    prints numbers in English style ("34,000.00") while Vietnamese sources
    write them with the dot as thousands mark ("34.000"), so a single
    spelling would miss a figure that is really there.
    """
    variants = [text, text.replace(",", "."), text.replace(".", ",")]
    present: list[str] = []
    for spellings in GROUND_TRUTH:
        if any(
            spelling in variant
            for spelling in spellings
            for variant in variants
        ):
            present.append(spellings[0])
    return len(present), present


async def run_baseline() -> dict[str, Any]:
    """The flow the agent uses today: web_search then read_url per result."""
    from src.tools.web_reader_tool import read_url
    from src.tools.web_search_tool import WebSearchTool

    started = time.perf_counter()
    search_tool = WebSearchTool()
    # The legacy flow has one search path. When every engine in it is
    # blocked, the search returns nothing, so it is tried twice before the
    # flow is called a failure. This gives the baseline its best case.
    search_payload: dict[str, Any] = {}
    for _ in range(2):
        raw = search_tool.execute(query=QUERY, max_results=5)
        search_payload = json.loads(raw)
        if search_payload.get("results"):
            break
    results = search_payload.get("results", [])

    search_ms = (time.perf_counter() - started) * 1000.0

    # One read_url per result, sequentially, exactly as the agent does.
    read_started = time.perf_counter()
    contents: list[str] = []
    read_errors: list[str] = []
    for row in results[:5]:
        url = row.get("url")
        if not url:
            continue
        try:
            payload = json.loads(read_url(url))
        except Exception as exc:  # noqa: BLE001 — a broken URL must not stop the run
            read_errors.append(f"{url}: {exc}")
            continue
        if payload.get("status") == "ok":
            contents.append(payload.get("content", ""))
        else:
            read_errors.append(f"{url}: {payload.get('error')}")
    read_ms = (time.perf_counter() - read_started) * 1000.0

    combined = "\n\n".join(contents)
    tokens = count_tokens(combined)
    found, present = _fact_retention(combined)

    return {
        "search_ms": round(search_ms, 1),
        "read_ms": round(read_ms, 1),
        "total_ms": round(search_ms + read_ms, 1),
        "results": len(results),
        "pages_attempted": len(results[:5]),
        "pages_read": len(contents),
        "read_failures": len(read_errors),
        "tokens": tokens,
        "facts_found": found,
        "facts_total": len(GROUND_TRUTH),
        "facts_present": present,
        "error": search_payload.get("error"),
    }


async def run_treatment() -> dict[str, Any]:
    """The new flow: parallel search then concurrent scrape and synthesis."""
    started = time.perf_counter()
    search = await parallel_web_search_async(query=QUERY, max_results=8)
    search_ms = (time.perf_counter() - started) * 1000.0

    urls = [r["url"] for r in search.get("results", []) if r.get("readable", True)]

    scrape_started = time.perf_counter()
    result = await concurrent_scrape_and_synthesize_async(
        urls=urls,
        query=QUERY,
        target_tickers=["HPG"],
        total_token_budget=2500,
    )
    scrape_ms = (time.perf_counter() - scrape_started) * 1000.0

    summary = result.get("summary_markdown", "")
    tokens = count_tokens(summary)
    found, present = _fact_retention(summary)

    return {
        "search_ms": round(search_ms, 1),
        "scrape_ms": round(scrape_ms, 1),
        "total_ms": round(search_ms + scrape_ms, 1),
        "results": search.get("results_count", 0),
        "readable_urls": len(urls),
        "pages_attempted": len(urls),
        "pages_read": result.get("token_stats", {}).get("documents_cleaned", 0),
        "read_failures": len(result.get("fetch_errors") or []),
        "tokens": tokens,
        "facts_found": found,
        "facts_total": len(GROUND_TRUTH),
        "facts_present": present,
        "status": result.get("status"),
        "reduction_pct": result.get("token_stats", {}).get("reduction_pct"),
    }


async def main() -> None:
    print("=" * 74)
    print("EMPIRICAL A/B BENCHMARK — baseline flow vs parallel pipeline")
    print("=" * 74)
    print(f"query: {QUERY}\n")

    baseline = await run_baseline()
    treatment = await run_treatment()

    print("--- BASELINE (web_search + N x read_url) ---")
    print(json.dumps(baseline, indent=2, ensure_ascii=False))
    print("\n--- TREATMENT (parallel_web_search + concurrent_scraper) ---")
    print(json.dumps(treatment, indent=2, ensure_ascii=False))

    print("\n" + "=" * 74)
    print("VERDICT")
    print("=" * 74)
    if baseline["total_ms"] and treatment["total_ms"]:
        ratio = baseline["total_ms"] / max(treatment["total_ms"], 1)
        print(f"latency: {baseline['total_ms']:.0f} ms -> {treatment['total_ms']:.0f} ms "
              f"({ratio:.2f}x)")
    if baseline["tokens"]:
        print(f"tokens into the model: {baseline['tokens']} -> {treatment['tokens']} "
              f"({100.0 * (1 - treatment['tokens'] / max(baseline['tokens'], 1)):.1f}% less)")
    print(f"facts kept: {baseline['facts_found']}/{baseline['facts_total']} -> "
          f"{treatment['facts_found']}/{treatment['facts_total']}")


if __name__ == "__main__":
    asyncio.run(main())
