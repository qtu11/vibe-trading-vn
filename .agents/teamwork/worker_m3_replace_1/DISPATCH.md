# Task Assignment: Replacement Worker M3 (Semantic Chunking & BM25 Pruning Verification)

## Identity
- Role: Python NLP & Token Optimization Engineer (M3 Replacement)
- Type: teamwork_worker
- Working directory: d:\Vibe-Trading\.agents\teamwork\worker_m3_replace_1

## Context & State
Predecessor Worker M3 has already completely written:
- `agent/src/tools/optimizer/chunker.py` (566 lines)
- `agent/src/tools/optimizer/bm25_scorer.py` (319 lines)
- `agent/src/tools/optimizer/budgeter.py` (160 lines)
- `agent/src/tools/optimizer/__init__.py` (251 lines)

## Mandatory Documents
- Read ORIGINAL_REQUEST.md: d:\Vibe-Trading\.agents\teamwork\ORIGINAL_REQUEST.md
- Read PROJECT.md: d:\Vibe-Trading\.agents\teamwork\orchestrator\PROJECT.md

## Mandatory Integrity Warning
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

## Scope of Work
1. Inspect the existing code in `agent/src/tools/optimizer/`.
2. Write and execute a comprehensive verification test script using `.venv\Scripts\python` to verify:
   - Heading-based hierarchical chunking (H1-H4) and atomic table replication.
   - Sentence splitting on natural boundaries without breaking decimals (`15.4%`, `3.5 tỷ`).
   - BM25-FSB scoring with ticker bonus (+3.0), period bonus (+2.5), metric bonus (+2.0), table bonus (+1.5), boilerplate penalty (-5.0).
   - Adaptive budgeting and narrative order preservation (re-sorting chunks by original index).
   - Quantitative measurement of token pruning ratio (must achieve 75% - 90% reduction).
3. If any bug or edge case is found, fix it in `agent/src/tools/optimizer/`.
4. Write your full handoff report to:
`d:\Vibe-Trading\.agents\teamwork\worker_m3_replace_1\handoff.md`
5. Send completion message to orchestrator.
