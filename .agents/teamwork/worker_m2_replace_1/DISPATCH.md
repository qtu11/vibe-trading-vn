# Task Assignment: Replacement Worker M2 (DOM Cleaning & Deduplication Verification)

## Identity
- Role: Python Data Pipeline Engineer (M2 Replacement)
- Type: teamwork_worker
- Working directory: d:\Vibe-Trading\.agents\teamwork\worker_m2_replace_1

## Context & State
Predecessor Worker M2 has already completely written:
- `agent/src/tools/extractor/dom_cleaner.py`
- `agent/src/tools/extractor/markdown_converter.py`
- `agent/src/tools/extractor/deduplicator.py`
- `agent/src/tools/extractor/__init__.py`
- `d:\Vibe-Trading\.agents\teamwork\worker_m2_dom_cleaner_1\test_extractor_suite.py`

## Mandatory Documents
- Read ORIGINAL_REQUEST.md: d:\Vibe-Trading\.agents\teamwork\ORIGINAL_REQUEST.md
- Read PROJECT.md: d:\Vibe-Trading\.agents\teamwork\orchestrator\PROJECT.md

## Mandatory Integrity Warning
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

## Scope of Work
1. Inspect the existing code in `agent/src/tools/extractor/`. If any fixes are needed, apply them cleanly.
2. Run the verification test suite using `.venv\Scripts\python .agents/teamwork/worker_m2_dom_cleaner_1/test_extractor_suite.py` or write additional unit tests.
3. Verify:
   - DOM cleaning strips ads, nav, footer, boilerplate, and scripts.
   - GFM tables align numbers right and text left, preserving Vietnamese numbers (15.200 tỷ, +21,7%).
   - Deduplication normalizes URLs and calculates 64-bit SimHash.
4. Write your full handoff report to:
`d:\Vibe-Trading\.agents\teamwork\worker_m2_replace_1\handoff.md`
5. Send completion message to orchestrator.


## 2026-11-08T15:11:46Z
[Message] timestamp=2026-11-08T15:11:46Z sender=fc6481d3-86d0-438b-b509-e00be11b4dba priority=MESSAGE_PRIORITY_HIGH content=You are teamwork_worker (Replacement for M2).
Working directory: d:\Vibe-Trading\.agents\teamwork\worker_m2_replace_1
You MUST read ORIGINAL_REQUEST.md before starting work:
d:\Vibe-Trading\.agents\teamwork\ORIGINAL_REQUEST.md
Also read PROJECT.md:
d:\Vibe-Trading\.agents\teamwork\orchestrator\PROJECT.md
Read your task dispatch:
d:\Vibe-Trading\.agents\teamwork\worker_m2_replace_1\DISPATCH.md

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Context:
Your predecessor already wrote:
- `agent/src/tools/extractor/dom_cleaner.py`
- `agent/src/tools/extractor/markdown_converter.py`
- `agent/src/tools/extractor/deduplicator.py`
- `agent/src/tools/extractor/__init__.py`
- `d:\Vibe-Trading\.agents\teamwork\worker_m2_dom_cleaner_1\test_extractor_suite.py`

Your task:
1. Verify the code in `agent/src/tools/extractor/`.
2. Run tests via `.venv\Scripts\python` on `.agents/teamwork/worker_m2_dom_cleaner_1/test_extractor_suite.py`.
3. If any bug or edge case is found, fix it in `agent/src/tools/extractor/`.
4. Deliver your handoff report to:
`d:\Vibe-Trading\.agents\teamwork\worker_m2_replace_1\handoff.md`
And send a completion message to orchestrator.
