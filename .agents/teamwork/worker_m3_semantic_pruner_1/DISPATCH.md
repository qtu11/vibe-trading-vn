# Task Assignment: Worker M3 (Semantic Chunking & BM25-FSB Pruner)

## Identity
- Role: Python NLP & Token Optimization Engineer (M3 - WS3)
- Type: teamwork_worker
- Working directory: d:\Vibe-Trading\.agents\teamwork\worker_m3_semantic_pruner_1

## Mandatory Documents
- Read ORIGINAL_REQUEST.md: d:\Vibe-Trading\.agents\teamwork\ORIGINAL_REQUEST.md
- Read PROJECT.md: d:\Vibe-Trading\.agents\teamwork\orchestrator\PROJECT.md
- Read Explorer 2 Handoff: d:\Vibe-Trading\.agents\teamwork\explorer_ws3_ws4_token_synthesis_1\handoff.md

## Mandatory Integrity Warning
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

## File Ownership
You exclusively own and MUST ONLY create/modify files in:
- `agent/src/tools/optimizer/chunker.py`
- `agent/src/tools/optimizer/bm25_scorer.py`
- `agent/src/tools/optimizer/budgeter.py`
- `agent/src/tools/optimizer/__init__.py`

## Implementation Scope
1. `agent/src/tools/optimizer/chunker.py`:
   - Structural & Semantic Chunking:
     * Hierarchy: Split on H1-H4 Markdown headings, attach breadcrumb prefix (`[Section: H1 > H2]`).
     * Atomic elements: Financial tables MUST NOT be split across rows; if table > max_chunk_tokens, replicate header row in every subsequent sub-chunk. Code blocks and quotes preserved atomically.
     * Sentence splitting: Natural language boundaries using `(?<=[.!?])\s+(?=[A-ZÀ-Ỹ0-9])` without breaking numbers (`15.4%`, `3.5 tỷ`), tickers, or abbreviations (`TP. HCM`, `Co., Ltd.`).
     * Sliding window: Target chunk size $350 \pm 50$ tokens with 15% overlap ($~50$ tokens) ending at sentence/paragraph boundary.
2. `agent/src/tools/optimizer/bm25_scorer.py`:
   - BM25-FSB (Financial Salience Boosting) Engine:
     * Pure Python BM25 Okapi core ($k_1=1.5, b=0.75$, smoothed IDF).
     * Bilingual financial tokenizer (`(?u)\b[A-Z0-9_\-\.\%]{2,}\b|[\w\d]+` preserving ticker case `VIC`, `VNM`, `HPG`, `NVDA`, `AAPL`). Financial compound n-grams (`doanh thu thuần`, `lợi nhuận sau thuế`, `biên gộp`, `net income`, `operating cash flow`, `eps`, `p/e`).
     * Financial Salience Bonuses:
       - Exact ticker match in query: +3.0 pts
       - Fiscal period match (Q3/2024, 9T2024, YoY): +2.5 pts
       - Quantitative metric density (numbers with units): +2.0 pts
       - Audited table bonus: +1.5 pts
     * Boilerplate penalty: -5.0 pts for privacy policy, terms, ads, copyright text. Chunks with score <= 0 discarded.
3. `agent/src/tools/optimizer/budgeter.py`:
   - Adaptive Token Budgeting:
     * Calculate dynamic budget $B_{tool} = \min(B_{max}, \max(B_{min}, \text{Headroom} \times \alpha \times C_{query}))$. $B_{min}=600$, $B_{max}=2500$, $\alpha=0.05$.
     * Sort chunks by `FinalScore` descending -> accumulate up to $B_{tool}$ -> **REORDER BY ORIGINAL DOCUMENT INDEX** (Narrative Order Preservation) so LLM reads facts in their natural logical flow.
     * Attach chunk metadata: `[Source S1 | Chunk 3 | Section: ...]`.
4. `agent/src/tools/optimizer/__init__.py`:
   - Expose `prune_document(doc: CleanDocument, query: str, tickers: list[str] = None, budget: int = None) -> PrunedDocument` and batch function `prune_documents(...)`.

## Verification Requirement
You must write unit tests or run python verification commands using `.venv\Scripts\python` to verify your code imports cleanly and demonstrates 75-90% token reduction on realistic text without dropping financial tables. Document exact verification commands and outputs in your report.

## Deliverable
Write your completion report to:
`d:\Vibe-Trading\.agents\teamwork\worker_m3_semantic_pruner_1\handoff.md`
Update progress.md with timestamps. When done, notify orchestrator via send_message.

## 2026-11-08T14:55:02Z
You are teamwork_worker.
Working directory: d:\Vibe-Trading\.agents\teamwork\worker_m3_semantic_pruner_1
You MUST read ORIGINAL_REQUEST.md before starting work:
d:\Vibe-Trading\.agents\teamwork\ORIGINAL_REQUEST.md
Also read PROJECT.md:
d:\Vibe-Trading\.agents\teamwork\orchestrator\PROJECT.md
Read your task dispatch:
d:\Vibe-Trading\.agents\teamwork\worker_m3_semantic_pruner_1\DISPATCH.md
And reference Explorer 2 handoff:
d:\Vibe-Trading\.agents\teamwork\explorer_ws3_ws4_token_synthesis_1\handoff.md

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

You exclusively own and MUST implement:
- `agent/src/tools/optimizer/chunker.py`
- `agent/src/tools/optimizer/bm25_scorer.py`
- `agent/src/tools/optimizer/budgeter.py`
- `agent/src/tools/optimizer/__init__.py`

Verify your code using `.venv\Scripts\python` to ensure clean imports and correct execution.
Write your completion report to `d:\Vibe-Trading\.agents\teamwork\worker_m3_semantic_pruner_1\handoff.md` and send a message when done.
