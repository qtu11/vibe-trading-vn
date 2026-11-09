# Task Assignment: Worker M4 (Map-Reduce & Structured Synthesis Engine)

## Identity
- Role: Python Knowledge Synthesis Engineer (M4 - WS4)
- Type: teamwork_worker
- Working directory: d:\Vibe-Trading\.agents\teamwork\worker_m4_synthesis_engine_1

## Mandatory Documents
- Read ORIGINAL_REQUEST.md: d:\Vibe-Trading\.agents\teamwork\ORIGINAL_REQUEST.md
- Read PROJECT.md: d:\Vibe-Trading\.agents\teamwork\orchestrator\PROJECT.md
- Read Explorer 2 Handoff: d:\Vibe-Trading\.agents\teamwork\explorer_ws3_ws4_token_synthesis_1\handoff.md (Sections 2.2, 2.3, 4)

## Mandatory Integrity Warning
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

## File Ownership
You exclusively own and MUST ONLY create/modify files in:
- `agent/src/tools/synthesis/models.py`
- `agent/src/tools/synthesis/map_extractor.py`
- `agent/src/tools/synthesis/reduce_synthesizer.py`
- `agent/src/tools/synthesis/__init__.py`

## Implementation Scope
1. `agent/src/tools/synthesis/models.py`:
   - Data models:
     * `MetricItem(name: str, value: float | str, unit: str, period: str, as_of: str | None, raw_snippet: str)`
     * `ExtractedFactMap(source_id: str, url: str, title: str, publisher_tier: int, published_time: str | None, key_facts: list[str], metrics: list[MetricItem], tickers: list[str], quotes: list[str])`
     * `SynthesizedResearchArtifact(status: str, query: str, total_sources_scanned: int, sources: list[dict], metrics_summary: list[dict], key_takeaways: list[str], catalysts: list[str], risks_and_headwinds: list[str], contradictions: list[str], bounded_summary: str)`
2. `agent/src/tools/synthesis/map_extractor.py`:
   - `MapExtractor`: Executes parallel fact extraction across pruned chunks from multiple sources.
   - Dual Execution Modes:
     * Deterministic Rule Worker (Default / Zero-Cost / Fast): Uses financial regex patterns, metric unit extraction (`tỷ VND`, `triệu USD`, `%`, `lần`), reporting period detection (Q1-Q4, YoY), ticker detection, quote detection from HTML blockquotes/quotes, and raw snippet preservation for Grounding Gate.
     * LLM Worker mode (Optional when LLM client available): Structured JSON extraction.
3. `agent/src/tools/synthesis/reduce_synthesizer.py`:
   - `ReduceSynthesizer`:
     * Cross-source corroboration: Merges matching facts/metrics across sources, attributing multiple sources (`[S1, S2]`).
     * Conflict resolution: Prioritizes sources by `SOURCE_POLICIES` tier: Tier 1 (Audited BCTC / HOSE / HNX / SSC) > Tier 2 (Reuters / Bloomberg) > Tier 3 (FiinGroup / Vietstock) > Tier 4 (CafeF / VnEconomy).
     * Peer discrepancy handling: If two same-tier sources give different numbers, do NOT fake average; flag `contradictions` and output exact range (e.g. "1.150 tỷ [S2] đến 1.200 tỷ [S1]").
     * Executive Summary Generator: Formats a publication-grade Markdown executive summary under 400 words with inline citations `[S1]`, `[S2]`.
     * Numeric Grounding Alignment: Ensures every figure in summary matches an item in `metrics_summary` with its `raw_snippet`, passing `agent/src/agent/grounding/figures.py` with 100% pass rate.
4. `agent/src/tools/synthesis/__init__.py`:
   - Expose `synthesize_research(pruned_docs, query, tickers=None) -> SynthesizedResearchArtifact`.

## Verification Requirement
You must write unit tests in `agent/tests/test_synthesis.py` and run python verification commands using `.venv\Scripts\python` to verify your code imports cleanly and functions correctly. Document exact verification commands and outputs in your report.

## Deliverable
Write your completion report to:
`d:\Vibe-Trading\.agents\teamwork\worker_m4_synthesis_engine_1\handoff.md`
Update progress.md with timestamps. When done, notify orchestrator via send_message.


## 2026-11-08T15:22:20Z
[Message] timestamp=2026-11-08T15:22:20Z sender=fc6481d3-86d0-438b-b509-e00be11b4dba priority=MESSAGE_PRIORITY_HIGH content=You are teamwork_worker (Worker M4).
Working directory: d:\Vibe-Trading\.agents\teamwork\worker_m4_synthesis_engine_1
You MUST read ORIGINAL_REQUEST.md before starting work:
d:\Vibe-Trading\.agents\teamwork\ORIGINAL_REQUEST.md
Also read PROJECT.md:
d:\Vibe-Trading\.agents\teamwork\orchestrator\PROJECT.md
Read your task dispatch:
d:\Vibe-Trading\.agents\teamwork\worker_m4_synthesis_engine_1\DISPATCH.md
And reference Explorer 2 handoff:
d:\Vibe-Trading\.agents\teamwork\explorer_ws3_ws4_token_synthesis_1\handoff.md

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

You exclusively own and MUST implement:
- `agent/src/tools/synthesis/models.py`
- `agent/src/tools/synthesis/map_extractor.py`
- `agent/src/tools/synthesis/reduce_synthesizer.py`
- `agent/src/tools/synthesis/__init__.py`

Verify your code using `.venv\Scripts\python` and write unit tests in `agent/tests/test_synthesis.py`.
Write your completion report to `d:\Vibe-Trading\.agents\teamwork\worker_m4_synthesis_engine_1\handoff.md` and send a message when done.
