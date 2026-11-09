# Project: Vibe-Trading Parallel Multi-Web Search & Concurrent Scraper Engine (Token-Optimized)

## Architecture
- WS1 (Multi-Engine & Parallel Scraping): Async HTTPX/AioHTTP with HTTP/2 connection pooling, in-memory async DNS cache (TTL 300s), IP pinning against SSRF & DNS rebinding, AIMD host-bucket rate limiter, multi-engine parallel search (DuckDuckGo, Brave, Bing, QVeris, Vietnam Financial Portals) with RRF re-ranking and domain diversity.
- WS2 (DOM Cleaning & High-Fidelity Extraction): 3-stage cleaning pipeline using `lxml` and Rust `nh3` sanitizer, boilerplate & ads removal, text density scoring, table-to-GFM converter preserving financial figures/dates/Vietnamese currency formats, and 3-tier deduplication (URL normalization, exact SHA-256, 64-bit SimHash).
- WS3 (Semantic Token Optimization & Adaptive Context Pruning): Hierarchical structural chunking (H1-H4 headings, atomic financial tables with replicated headers, sentence boundary splitting with 15% sliding window overlap), BM25-FSB (Financial Salience Boosting) algorithm with bilingual financial tokenizer, ticker/period/metric bonuses, and dynamic adaptive token budgeting based on AgentLoop context headroom (75-90% token pruning).
- WS4 (Map-Reduce & Structured Synthesis Engine): 2-stage aggregation pipeline with parallel Map extraction (LLM & deterministic rule workers) and Reduce synthesis with `SOURCE_POLICIES` publisher tier priority (Tier 1 > 2 > 3 > 4), discrepancy reporting, standardized JSON schema (`SynthesizedResearchArtifact`), publication-grade Markdown executive summaries, and numeric grounding gate compliance.
- WS5 (Empirical Benchmark Harness & Tool Integration): 4-pillar benchmark harness (latency distribution p50-p99, token pruning efficiency validation, concurrent throughput RPS & stress, Key Fact Retention Score - KFRS), test matrix (mock responses, network resilience, SSRF invariants), and backward-compatible dual-mode tool contracts (`ParallelWebSearchTool`, `ConcurrentScraperTool`) integrated with AgentLoop, MCP server, and FastAPI.

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | MultiSearchAggregator & Adapters | DuckDuckGo, Brave Search, Bing, QVeris, Vietnam Financial Portals (CafeF, Vietstock, Google News VN) | M1 | Survey |
| 2 | RRF Re-Ranking & Domain Diversity | Reciprocal Rank Fusion ($k=60$) with engine weights and max 2 results per domain | M1 | Survey |
| 3 | AsyncScrapingEngine & Connection Pool | Async HTTPX/AioHTTP, HTTP/2 multiplexing, max 60 connections, 30s keep-alive | M1 | Survey |
| 4 | SSRF & DNS Rebinding Invariant Guard | Pre-dial DNS resolution, RFC 1918/link-local/metadata blocking, socket IP pinning | M1 | Survey |
| 5 | Adaptive Rate Limiter & Concurrency | Host-bucket token bucket, AIMD backoff on 429/503, header/proxy rotation | M1 | Survey |
| 6 | 3-Stage DOM Cleaning Pipeline | Fast `lxml` tag stripping, boilerplate/ad elimination, Rust `nh3` whitelist sanitization | M2 | Survey |
| 7 | High-Fidelity Table & Markdown Engine | GFM financial tables with alignment, Vietnamese number/date formatting, metadata | M2 | Survey |
| 8 | 3-Tier Cross-Site Deduplicator | URL normalization, SHA-256 exact hash, 64-bit SimHash near-duplicate grouping | M2 | Survey |
| 9 | Structural & Semantic Chunker | H1-H4 hierarchy, atomic table preservation with header replication, 15% sliding window overlap | M3 | Survey |
| 10 | BM25-FSB Scoring Engine | BM25 Okapi + bilingual financial tokenizer + ticker/period/metric boost - boilerplate penalty | M3 | Survey |
| 11 | Adaptive Token Budgeter | Dynamic headroom allocation ($B_{tool} \in [600, 2500]$ tokens) preventing context overflow | M3 | Survey |
| 12 | Parallel Map Extraction Worker | Parallel fact, metric, ticker, and quote extraction (LLM & deterministic rule workers) | M4 | Survey |
| 13 | Reduce Synthesis & Tier Resolver | Multi-source corroboration, conflict resolution by `SOURCE_POLICIES` Tier 1-4 | M4 | Survey |
| 14 | Standardized JSON & Markdown Artifact | `SynthesizedResearchArtifact` schema and executive Markdown report (<400 words, [S1], [S2]) | M4 | Survey |
| 15 | Grounding Ledger & Numeric Alignment | Seamless integration with `figures.py` and `sources.py`, eliminating `(omitted※)` errors | M4 | Survey |
| 16 | Empirical Benchmark Harness | Latency (p50/p90/p99), token pruning ratio (75-90%), concurrent RPS, RAM RSS | M5 | Survey |
| 17 | Key Fact Retention Score (KFRS) | Evaluation of Hard Fact Recall (HFR $\ge 0.95$) and Relevance Salience | M5 | Survey |
| 18 | Unified Tool Interfaces & Contracts | `ParallelWebSearchTool` & `ConcurrentScraperTool` dual-mode compatibility with AgentLoop/MCP/FastAPI | M5 | Survey |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Multi-Engine Search & Async Scraping Engine | WS1: Search adapters, Aggregator, AsyncScrapingEngine, SSRF Guard, Rate Limiter | none | DONE |
| M2 | DOM Cleaning, High-Fidelity Markdown & Deduplication | WS2: `lxml` + `nh3` pipeline, GFM financial tables, SimHash 3-tier deduplicator | M1 | DONE |
| M3 | Semantic Chunking, BM25-FSB & Token Pruning | WS3: Structural chunking, BM25-FSB scorer, dynamic token budgeter (75-90% pruning) | M2 | IN_PROGRESS |
| M4 | Map-Reduce Synthesis & Grounding Integration | WS4: Map workers, Reduce conflict resolver, JSON/Markdown artifact, Grounding Gate | M3 | PLANNED |
| M5 | Tool Integration & Empirical Benchmark Harness | WS5: Dual-mode tool contracts, MCP/FastAPI endpoints, Benchmark harness, KFRS, unit test suite | M1, M2, M3, M4 | PLANNED |

## Interface Contracts
### M1 -> M2 (Scraper to Cleaner)
- `ScrapeResult`: `url: str, html_content: str, status_code: int, headers: dict, latency_ms: float, resolved_ip: str`

### M2 -> M3 (Cleaner to Semantic Chunker)
- `CleanDocument`: `url: str, canonical_url: str, title: str, clean_markdown: str, metadata: dict, syndicated_sources: list[str], simhash: int`

### M3 -> M4 (Pruner to Map-Reduce Synthesizer)
- `PrunedDocument`: `url: str, title: str, source_id: str, publisher_tier: int, selected_chunks: list[Chunk], original_token_count: int, pruned_token_count: int, pruning_ratio: float`

### M4 -> M5 (Synthesizer to Tool Interface & AgentLoop)
- `SynthesizedResearchArtifact`: Standardized Pydantic model containing `query`, `sources`, `metrics_summary`, `key_takeaways`, `catalysts`, `risks_and_headwinds`, `contradictions`, and bounded executive summary Markdown string.

## Code Layout
- Search Adapters: `agent/src/tools/search/` (`base_engine.py`, `ddg_engine.py`, `brave_engine.py`, `bing_engine.py`, `qveris_engine.py`, `vietnam_portals_engine.py`, `aggregator.py`)
- Async Scraper: `agent/src/tools/scraper/` (`fetcher.py`, `dns_cache.py`, `rate_limiter.py`, `ssrf_guard.py`)
- DOM Extractor: `agent/src/tools/extractor/` (`dom_cleaner.py`, `markdown_converter.py`, `deduplicator.py`)
- Semantic Token Pruner: `agent/src/tools/optimizer/` (`chunker.py`, `bm25_scorer.py`, `budgeter.py`)
- Map-Reduce Synthesis: `agent/src/tools/synthesis/` (`map_extractor.py`, `reduce_synthesizer.py`, `models.py`)
- Tool Contracts: `agent/src/tools/parallel_web_tools.py` (`ParallelWebSearchTool`, `ConcurrentScraperTool`)
- Benchmark Harness: `agent/tests/benchmarks/web_tools/` (`benchmark_harness.py`, `test_latency_tokens.py`, `kfrs_evaluator.py`)
- Unit & Mock Tests: `agent/tests/test_parallel_web_tools.py`
