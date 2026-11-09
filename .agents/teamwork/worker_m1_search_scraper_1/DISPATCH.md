# Task Assignment: Worker M1 (Multi-Engine Search & Async Scraping Engine)

## Identity
- Role: Python Systems Engineer (M1 - WS1)
- Type: teamwork_worker
- Working directory: d:\Vibe-Trading\.agents\teamwork\worker_m1_search_scraper_1

## Mandatory Documents
- Read ORIGINAL_REQUEST.md: d:\Vibe-Trading\.agents\teamwork\ORIGINAL_REQUEST.md
- Read PROJECT.md: d:\Vibe-Trading\.agents\teamwork\orchestrator\PROJECT.md
- Read Explorer 1 Handoff: d:\Vibe-Trading\.agents\teamwork\explorer_ws1_ws2_search_scrape_1\handoff.md

## Mandatory Integrity Warning
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

## File Ownership
You exclusively own and MUST ONLY create/modify files in:
- `agent/src/tools/search/base_engine.py`
- `agent/src/tools/search/ddg_engine.py`
- `agent/src/tools/search/brave_engine.py`
- `agent/src/tools/search/bing_engine.py`
- `agent/src/tools/search/qveris_engine.py`
- `agent/src/tools/search/vietnam_portals_engine.py`
- `agent/src/tools/search/aggregator.py`
- `agent/src/tools/search/__init__.py`
- `agent/src/tools/scraper/fetcher.py`
- `agent/src/tools/scraper/dns_cache.py`
- `agent/src/tools/scraper/rate_limiter.py`
- `agent/src/tools/scraper/ssrf_guard.py`
- `agent/src/tools/scraper/__init__.py`

## Implementation Scope
1. `agent/src/tools/search/`:
   - `BaseSearchEngine`: Abstract base class with async `search(query, max_results=5) -> list[SearchResult]`.
   - `SearchResult` dataclass/Pydantic: `title, url, snippet, source, published_at`.
   - Engine implementations:
     * `DuckDuckGoEngine`: Async query via `ddgs` or async httpx search.
     * `BraveSearchEngine`: Async Brave Search API (fallback to organic scraping if no key).
     * `BingSearchEngine`: Async Bing organic search.
     * `QverisSearchEngine`: Integration with QVeris dataset discovery (`agent/src/tools/qveris_tool.py`).
     * `VietnamFinancialPortalsEngine`: Specialized search for CafeF, Vietstock, and Google News VN RSS ticker search.
   - `MultiSearchAggregator`: Concurrent dispatch via `asyncio.gather(..., return_exceptions=True)` with 3.0s timeout per engine, RRF (Reciprocal Rank Fusion, k=60) with engine weights, and Domain Diversity Gate (max 2 URLs per domain in top results).
2. `agent/src/tools/scraper/`:
   - `SSRFGuard`: Strict DNS resolution & IP check before socket dial. Block all private IPs (RFC 1918: 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16), loopback (127.0.0.1, ::1), link-local, multicast, and cloud metadata (169.254.169.254). Socket IP pinning on redirects.
   - `AsyncDNSCache`: In-memory async DNS cache with TTL (300s).
   - `AdaptiveRateLimiter`: Token bucket per host + AIMD (halve concurrency on 429/503, additive increase on success).
   - `AsyncScrapingEngine`: Uses `httpx.AsyncClient` with HTTP/2 pooling, custom transport wrapping SSRFGuard, modern browser headers and UA rotation. Methods: `scrape_url(url) -> ScrapeResult` and `scrape_urls(urls: list[str]) -> list[ScrapeResult]`.

## Verification Requirement
You must write unit tests or run python verification commands using `.venv\Scripts\python` to verify your code imports cleanly and functions correctly. Document exact verification commands and outputs in your report.

## Deliverable
Write your completion report to:
`d:\Vibe-Trading\.agents\teamwork\worker_m1_search_scraper_1\handoff.md`
Update progress.md with timestamps. When done, notify orchestrator via send_message.


## 2026-11-08T14:54:18Z
You are teamwork_worker.
Working directory: d:\Vibe-Trading\.agents\teamwork\worker_m1_search_scraper_1
You MUST read ORIGINAL_REQUEST.md before starting work:
d:\Vibe-Trading\.agents\teamwork\ORIGINAL_REQUEST.md
Also read PROJECT.md:
d:\Vibe-Trading\.agents\teamwork\orchestrator\PROJECT.md
Read your task dispatch:
d:\Vibe-Trading\.agents\teamwork\worker_m1_search_scraper_1\DISPATCH.md
And reference Explorer 1 handoff:
d:\Vibe-Trading\.agents\teamwork\explorer_ws1_ws2_search_scrape_1\handoff.md

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

You exclusively own and MUST implement:
- `agent/src/tools/search/base_engine.py`
- `agent/src/tools/search/ddg_engine.py`
- `agent/src/tools/search/brave_engine.py`
- `agent/src/tools/search/bing_engine.py`
- `agent/src/tools/search/qveris_engine.py`
- `agent/src/tools/search/vietnam_portals_engine.py`
- `agent/src/tools/search/aggregator.py`
- `agent/src/tools/search/__init__.py`
- `agent/src/tools/scraper/fetcher.py`
- `agent/src/tools/scraper/dns_cache.py`
- `agent/src/tools/scraper/rate_limiter.py`
- `agent/src/tools/scraper/ssrf_guard.py`
- `agent/src/tools/scraper/__init__.py`

Verify your code using `.venv\Scripts\python` to ensure clean imports and correct execution.
Write your completion report to `d:\Vibe-Trading\.agents\teamwork\worker_m1_search_scraper_1\handoff.md` and send a message when done.
