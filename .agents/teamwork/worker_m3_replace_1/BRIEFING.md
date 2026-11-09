# BRIEFING — 2026-11-08T15:15:00Z

## Mission
Verify, test, and validate semantic chunking, BM25-FSB scoring, and adaptive token budgeting in `agent/src/tools/optimizer/` achieving 75-90% token reduction without losing key tables and numbers.

## 🔒 My Identity
- Archetype: teamwork_worker
- Roles: implementer, qa, specialist
- Working directory: d:\Vibe-Trading\.agents\teamwork\worker_m3_replace_1
- Original parent: fc6481d3-86d0-438b-b509-e00be11b4dba
- Milestone: M3 (Semantic Chunking, BM25-FSB & Token Pruning)

## 🔒 Key Constraints
- Genuine implementation: DO NOT hardcode test results or create dummy/facade implementations.
- Verification command must use `.venv\Scripts\python` on Windows.
- Heading-based hierarchical chunking (H1-H4), atomic table preservation with replicated headers.
- Sentence boundary splitting without breaking decimals (e.g. 15.4%, 3.5 tỷ).
- BM25-FSB scoring with ticker bonus (+3.0), period bonus (+2.5), metric bonus (+2.0), table bonus (+1.5), boilerplate penalty (-5.0).
- Adaptive budgeting and narrative order preservation (re-sorting chunks by original index).
- Quantitative measurement: 75-90% token pruning ratio on sample financial articles without losing key tables and numbers.
- Deliver handoff report to `d:\Vibe-Trading\.agents\teamwork\worker_m3_replace_1\handoff.md`.
- Communicate to caller `fc6481d3-86d0-438b-b509-e00be11b4dba` via `send_message`.
- Response language: Vietnamese. Address boss: "chủ tịch", "boss", or "anh Tú". No emojis or icons.

## Current Parent
- Conversation ID: fc6481d3-86d0-438b-b509-e00be11b4dba
- Updated: not yet

## Task Summary
- **What to build/verify**: Semantic chunker, BM25-FSB scorer, adaptive budgeter in `agent/src/tools/optimizer/`.
- **Success criteria**: All tests pass, genuine verification with 75-90% token pruning, key facts/tables preserved.
- **Interface contracts**: M2->M3 (`CleanDocument`), M3->M4 (`PrunedDocument`).
- **Code layout**: `agent/src/tools/optimizer/` (`chunker.py`, `bm25_scorer.py`, `budgeter.py`, `__init__.py`).

## Change Tracker
- **Files modified**: None yet
- **Build status**: Untested
- **Pending issues**: None

## Quality Status
- **Build/test result**: Untested
- **Lint status**: Untested
- **Tests added/modified**: Pending test suite creation

## Key Decisions Made
- Inspect existing codebase first before adding or editing any code.

## Artifact Index
- DISPATCH.md — Task assignment
- BRIEFING.md — Persistent state
- progress.md — Liveness heartbeat
- handoff.md — 5-component handoff report
