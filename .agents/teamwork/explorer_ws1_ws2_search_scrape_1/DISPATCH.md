# Task Assignment: Explorer WS1 & WS2 (Search & Scraping Engine)

## Identity
- Role: Codebase Researcher (WS1 & WS2)
- Type: teamwork_explorer
- Working directory: d:\Vibe-Trading\.agents\teamwork\explorer_ws1_ws2_search_scrape_1

## Mandatory Documents
- Read ORIGINAL_REQUEST.md: d:\Vibe-Trading\.agents\teamwork\ORIGINAL_REQUEST.md

## Scope & Objective
Survey existing search & reader tools in Vibe-Trading and design the architecture for Workstream 1 & Workstream 2:
1. Workstream 1 (Multi-Engine & Parallel Scraping Architecture):
   - Inspect `agent/src/tools/web_search_tool.py`, `agent/src/tools/web_reader_tool.py`, and related tools/configs.
   - Design concurrent multi-search across DuckDuckGo, Brave Search, Bing, Qveris, and Vietnam Financial Portals.
   - Design Async HTTPX/AioHTTP fetcher with connection pooling, DNS caching, semaphore rate limiting, and adaptive concurrency.
2. Workstream 2 (DOM Cleaning & High-Fidelity Extraction):
   - Design HTML-to-clean-Markdown extraction pipeline, boilerplate stripping (nav, footer, ads, scripts), table preservation, and cross-site deduplication.

## Deliverable
Write your findings and architectural specifications to:
`d:\Vibe-Trading\.agents\teamwork\explorer_ws1_ws2_search_scrape_1\handoff.md`


## 2026-11-08T14:41:29Z
You are teamwork_explorer.
Working directory: d:\Vibe-Trading\.agents\teamwork\explorer_ws1_ws2_search_scrape_1
You MUST read ORIGINAL_REQUEST.md before starting work:
d:\Vibe-Trading\.agents\teamwork\ORIGINAL_REQUEST.md
Also read your task dispatch:
d:\Vibe-Trading\.agents\teamwork\explorer_ws1_ws2_search_scrape_1\DISPATCH.md

Your task is to survey the current codebase in d:\Vibe-Trading and produce a comprehensive technical specification and architecture for Workstream 1 & Workstream 2:
1. Workstream 1 (Multi-Engine & Parallel Scraping Architecture):
- Inspect existing search and reader tools: `agent/src/tools/web_search_tool.py`, `agent/src/tools/web_reader_tool.py`, and other search/scraping references in `agent/` and dependencies in `pyproject.toml` / `requirements.txt`.
- Design concurrent multi-engine search: DuckDuckGo, Brave Search, Bing, Qveris, and Vietnam Financial Portals (Vietstock, CafeF, FiinGroup, etc.).
- Design async scraping engine using Async HTTPX / AioHTTP with connection pooling, DNS caching, rate limiter, adaptive concurrency control, and proxy/header rotation.
2. Workstream 2 (DOM Cleaning & High-Fidelity Extraction):
- Analyze how HTML is currently parsed and converted.
- Design high-speed DOM cleaning pipeline: stripping boilerplate, ads, nav, footer, scripts, styles.
- Clean Markdown extraction preserving tables, financial figures, dates, and metadata.
- Cross-site deduplication strategy.

Deliver your detailed report to:
d:\Vibe-Trading\.agents\teamwork\explorer_ws1_ws2_search_scrape_1\handoff.md
Update your progress.md periodically with "Last visited" timestamps.
When finished, send a message to orchestrator with your completion status and report path.
