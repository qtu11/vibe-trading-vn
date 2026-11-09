# Task Assignment: Worker M2 (DOM Cleaning, GFM Tables & Deduplication)

## Identity
- Role: Python Data Pipeline Engineer (M2 - WS2)
- Type: teamwork_worker
- Working directory: d:\Vibe-Trading\.agents\teamwork\worker_m2_dom_cleaner_1

## Mandatory Documents
- Read ORIGINAL_REQUEST.md: d:\Vibe-Trading\.agents\teamwork\ORIGINAL_REQUEST.md
- Read PROJECT.md: d:\Vibe-Trading\.agents\teamwork\orchestrator\PROJECT.md
- Read Explorer 1 Handoff: d:\Vibe-Trading\.agents\teamwork\explorer_ws1_ws2_search_scrape_1\handoff.md

## Mandatory Integrity Warning
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

## File Ownership
You exclusively own and MUST ONLY create/modify files in:
- `agent/src/tools/extractor/dom_cleaner.py`
- `agent/src/tools/extractor/markdown_converter.py`
- `agent/src/tools/extractor/deduplicator.py`
- `agent/src/tools/extractor/__init__.py`

## Implementation Scope
1. `agent/src/tools/extractor/dom_cleaner.py`:
   - 3-stage DOM Cleaning Pipeline:
     * Stage 1: Fast tree parsing with `lxml.html` (<3ms). Strip technical tags (`<script>`, `<style>`, `<noscript>`, `<iframe>`, `<form>`, `<input>`, `<button>`, `<svg>`, `<canvas>`). Strip CSS selectors for boilerplate: `header`, `footer`, `nav`, `aside`, `.navbar`, `.footer`, ads (`[class*="ad-"]`, `[id*="ad-"]`, `.banner`), popups/cookie notices (`[class*="cookie"]`, `[class*="consent"]`, `[class*="modal"]`), social share, related posts.
     * Stage 2: Main Content Extraction using Text-to-Tag ratio and Link Density (<0.4) across `<article>`, `<main>`, `.content`, `.detail-content`, `.fck_detail` (CafeF), `.article-body` (Vietstock).
     * Stage 3: Whitelist sanitization using Rust `nh3.clean` with permitted tags (`h1-h6, p, table, thead, tbody, tr, th, td, ul, ol, li, blockquote, strong, em, b, i, code, pre`), stripping all inline styles, scripts, and garbage classes.
2. `agent/src/tools/extractor/markdown_converter.py`:
   - High-Fidelity Table Engine:
     * Convert HTML `<table>` to standard GitHub Flavored Markdown (GFM).
     * Align textual headers left (`:---`) and numeric/percentage columns right (`---:`).
     * Support `colspan` and `rowspan` without breaking table grid layout.
     * Strict preservation of Vietnamese financial numbers (`15.200 tỷ`, `1.234,5 triệu`) and reporting periods (Q3/2024, YTD, YoY).
     * Extract metadata: title, publisher, author, published date, canonical URL.
3. `agent/src/tools/extractor/deduplicator.py`:
   - 3-tier Cross-Site Deduplication:
     * Tier 1: Canonical URL Normalization (strip UTM parameters, fbclid, session IDs, hash fragments).
     * Tier 2: Exact text SHA-256 hash.
     * Tier 3: 64-bit SimHash (tokenize 3-grams, remove Vietnamese stop words). If Hamming distance <= 3, group as near-duplicate syndicated story.
     * Syndication aggregation: Preserve primary record, attach `syndicated_sources: list[str]`.
4. `agent/src/tools/extractor/__init__.py`:
   - Expose `clean_html(html_str, url) -> CleanDocument` and `deduplicate_documents(docs: list[CleanDocument]) -> list[CleanDocument]`.

## Verification Requirement
You must write unit tests or run python verification commands using `.venv\Scripts\python` to verify your code imports cleanly and functions correctly on sample HTML fixtures. Document exact verification commands and outputs in your report.

## Deliverable
Write your completion report to:
`d:\Vibe-Trading\.agents\teamwork\worker_m2_dom_cleaner_1\handoff.md`
Update progress.md with timestamps. When done, notify orchestrator via send_message.


## 2026-11-08T14:54:51Z
From: fc6481d3-86d0-438b-b509-e00be11b4dba
Content: You are teamwork_worker.
Working directory: d:\Vibe-Trading\.agents\teamwork\worker_m2_dom_cleaner_1
You exclusively own and MUST implement:
- `agent/src/tools/extractor/dom_cleaner.py`
- `agent/src/tools/extractor/markdown_converter.py`
- `agent/src/tools/extractor/deduplicator.py`
- `agent/src/tools/extractor/__init__.py`
