"""Unified High-Performance Parallel Search and Concurrent Scraper Tools.

Module: M5 / Workstream 5 (Benchmark Harness & Unified Tool Contracts)
Combines:
1. MultiSearchAggregator (Parallel multi-engine search: DDG, Brave, Bing, QVeris, VN portals with RRF)
2. AsyncScrapingEngine (Concurrent HTTP/2 fetcher with SSRF IP Pinning & DNS Cache)
3. 3-Stage DOM Cleaning & GFM Markdown Table Conversion (lxml, nh3)
4. 3-Tier Deduplication (Canonical URL, SHA-256, 64-bit SimHash Hamming <= 3)
5. Semantic Token Optimization (Structural chunking, BM25-FSB, Adaptive Budgeter)
6. Map-Reduce Structured Synthesis & Grounding Matrix ([S1], [S2] citations)
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextvars
import json
import logging
from pathlib import Path
import re
import time
from typing import Any, Optional, Sequence
from urllib.parse import urlparse

from src.agent.tools import BaseTool
from src.security.scanner import with_security_warnings

# Module internal imports
from src.tools.search import (
    MultiSearchAggregator,
    SearchResult,
    DuckDuckGoEngine,
    BraveSearchEngine,
    BingSearchEngine,
    VietnamFinancialPortalsEngine,
    QverisSearchEngine,
)
from src.tools.scraper import AsyncScrapingEngine, ScrapeResult
from src.tools.scraper.rate_limiter import AdaptiveRateLimiter
from src.tools.extractor import clean_html, deduplicate_documents, CleanDocument
from src.tools.optimizer import prune_documents, PrunedDocument, count_tokens
from src.tools.synthesis import synthesize_research, SynthesizedResearchArtifact
from src.tools.scraper.reader_fallback import fetch_rendered_markdown_batch_detailed
from src.tools.scraper.url_resolver import is_unreadable_wrapper

logger = logging.getLogger(__name__)


def _run_async_safely(coro: Any) -> Any:
    """Execute coroutine safely whether or not an event loop is currently running."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(contextvars.copy_context().run, asyncio.run, coro).result()
    else:
        return asyncio.run(coro)


def _extract_domain(url: str) -> str:
    try:
        netloc = urlparse(url).netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc or url
    except Exception:
        return url


def _apply_domain_diversity(
    rows: Sequence[SearchResult],
    max_per_domain: int = 2,
    limit: int = 10,
) -> list[SearchResult]:
    domain_counts: dict[str, int] = {}
    selected: list[SearchResult] = []
    for r in rows:
        dom = _extract_domain(r.url)
        count = domain_counts.get(dom, 0)
        if count < max_per_domain:
            domain_counts[dom] = count + 1
            selected.append(r)
            if len(selected) >= limit:
                break
    return selected


async def parallel_web_search_async(
    query: str,
    max_results: int = 10,
    queries: Optional[list[str]] = None,
    category: str = "finance",
    per_engine_timeout: float = 8.0,
    global_deadline: float = 9.0,
) -> dict[str, Any]:
    """Execute parallel multi-engine and multi-query search.

    Args:
        query: Primary search query.
        max_results: Maximum unified results to return.
        queries: Optional list of additional queries to run concurrently.
        category: Search category ('finance', 'news', 'general').
        per_engine_timeout: Timeout in seconds per engine. Must leave room for
            the engine's own fallback chain (DuckDuckGo tries several
            backends before its HTML fallback), so it is set above the
            three-and-a-half seconds that used to cut DuckDuckGo off.
        global_deadline: Absolute deadline for the aggregator.

    Returns:
        Structured dictionary containing ranked results, metadata, and sources.
    """
    start_time = time.perf_counter()

    # Configure default engine fleet; `category` steers the mix so a news
    # question leans on portals/wires while a general question does not
    # over-boost VN finance portals.
    if category == "news":
        engines = [
            VietnamFinancialPortalsEngine(weight=1.8),
            DuckDuckGoEngine(weight=1.0),
            BraveSearchEngine(weight=1.2),
            BingSearchEngine(weight=1.1),
            QverisSearchEngine(weight=1.0),
        ]
        max_per_domain = 3
    elif category == "general":
        engines = [
            DuckDuckGoEngine(weight=1.2),
            BraveSearchEngine(weight=1.2),
            BingSearchEngine(weight=1.1),
            VietnamFinancialPortalsEngine(weight=1.0),
            QverisSearchEngine(weight=1.0),
        ]
        max_per_domain = 2
    else:  # finance (default)
        engines = [
            VietnamFinancialPortalsEngine(weight=1.6),
            DuckDuckGoEngine(weight=1.0),
            BraveSearchEngine(weight=1.2),
            BingSearchEngine(weight=1.0),
            QverisSearchEngine(weight=1.3),
        ]
        max_per_domain = 2

    aggregator = MultiSearchAggregator(
        engines=engines,
        per_engine_timeout=per_engine_timeout,
        global_deadline=global_deadline,
        rrf_k=60,
        max_per_domain=max_per_domain,
    )

    all_queries = [query]
    if queries:
        for q in queries:
            if q.strip() and q.strip() not in all_queries:
                all_queries.append(q.strip())

    try:
        if len(all_queries) == 1:
            raw_results = await aggregator.search(all_queries[0], max_results=max_results)
            results = _apply_domain_diversity(raw_results, max_per_domain=max_per_domain, limit=max_results)
        else:
            # Parallel query dispatch with shared global deadline
            tasks = [asyncio.create_task(aggregator.search(q, max_results=max_results)) for q in all_queries]
            done, pending = await asyncio.wait(tasks, timeout=global_deadline)
            for p in pending:
                p.cancel()
            combined_map: dict[str, SearchResult] = {}
            for t in done:
                try:
                    r_list = t.result()
                    if isinstance(r_list, list):
                        for r in r_list:
                            if r.url not in combined_map or r.score > combined_map[r.url].score:
                                combined_map[r.url] = r
                except Exception:
                    pass
            ranked = sorted(combined_map.values(), key=lambda x: x.score, reverse=True)
            results = _apply_domain_diversity(ranked, max_per_domain=max_per_domain, limit=max_results)
    finally:
        await aggregator.close()

    elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)

    formatted_results = []
    for r in results:
        requires_resolution = is_unreadable_wrapper(r.url)
        formatted_results.append(
            {
                "title": r.title,
                "url": r.url,
                "snippet": r.snippet,
                "source": r.source,
                "score": round(r.score, 4),
                "published_date": getattr(r, "published_at", None),
                # ``readable`` is false for a redirect wrapper (Google News):
                # no plain fetch can read it. ``requires_resolution`` says the
                # link is still usable -- read_url resolves it to the publisher
                # before fetching, and the citation keeps the feed URL.
                "readable": not requires_resolution,
                "requires_resolution": requires_resolution,
            }
        )

    payload = {
        "status": "ok",
        "primary_query": query,
        "all_queries": all_queries,
        "results_count": len(formatted_results),
        "latency_ms": elapsed_ms,
        "results": formatted_results,
    }
    return with_security_warnings(payload, fields=("results.*.title", "results.*.snippet"))


async def concurrent_scrape_and_synthesize_async(
    urls: Sequence[str],
    query: str = "",
    target_tickers: Optional[list[str]] = None,
    total_token_budget: int = 2500,
    synthesize: bool = True,
    concurrency_limit: int = 10,
    per_host_limit: int = 3,
    request_timeout: float = 6.0,
    run_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Full-pipeline concurrent fetcher, cleaner, pruner, and synthesizer.

    1. Concurrent Scrape with SSRF Guard & HTTP/2 Pooling
    2. 3-Stage DOM Cleaning & Table Conversion
    3. 3-Tier Cross-Site Deduplication
    4. BM25-FSB Semantic Token Optimization
    5. Map-Reduce Cross-Source Reconciliation & Grounding

    Returns:
        Structured response dictionary.
    """
    start_time = time.perf_counter()
    from src.tools.source_documents import persist_document
    from src.tools.doc_reader_tool import read_pdf_bytes

    if not urls:
        return {
            "status": "empty",
            "results_count": 0,
            "documents": [],
            "summary_markdown": "",
            "error": "No URLs were provided to scrape.",
            "token_stats": {"raw_tokens": 0, "pruned_tokens": 0, "reduction_pct": 0.0},
            "latency_ms": 0.0,
        }

    # Step 1: Async Concurrent Scraping
    # Wrapper URLs (Google News) point at a publisher page that only resolves
    # through a handshake; fetching one here burns a request and returns a
    # shell. They are skipped and reported so the caller can read them with
    # read_url -- which resolves the wrapper first -- instead of this tool.
    skipped_wrappers: list[str] = []
    fetchable_urls: list[str] = []
    for url in urls:
        if is_unreadable_wrapper(url):
            skipped_wrappers.append(url)
        else:
            fetchable_urls.append(url)

    scraper = AsyncScrapingEngine(
        max_connections=concurrency_limit,
        rate_limiter=AdaptiveRateLimiter(
            global_max_concurrency=max(4, concurrency_limit),
            default_host_concurrency=max(1, min(per_host_limit, 6)),
            max_host_concurrency=max(1, min(per_host_limit, 6)),
        ),
    )
    try:
        scrape_results: list[ScrapeResult] = await scraper.scrape_urls(
            fetchable_urls, timeout=request_timeout
        )
    finally:
        await scraper.close()

    # Step 2: 3-Stage DOM Cleaning & Markdown Extraction
    cleaned_docs: list[CleanDocument] = []
    source_documents: dict[str, dict[str, Any]] = {}
    raw_total_tokens = 0
    # URLs whose direct fetch produced no usable prose (client-rendered SPA
    # shells). These get one reader-service retry below.
    needs_reader: list[str] = []

    for res in scrape_results:
        html = getattr(res, "html_content", "") or getattr(res, "html", "")
        content_type = (getattr(res, "content_type", "") or res.headers.get("content-type", "text/html")).split(";", 1)[0].lower()
        content = getattr(res, "content_bytes", b"") or html.encode("utf-8")
        coverage = {"status": "blocked", "extraction_complete": False, "complete": False, "method": "direct_html",
                    "reason": res.error or "no_usable_text", "truncated": getattr(res, "truncated", False)}
        if not res.success:
            source_documents[res.url] = {"url": res.url, **persist_document(
                source=res.final_url or res.url, content_type=content_type, content_bytes=content,
                coverage=coverage, run_dir=run_dir, requested_url=res.url,
            )}
            continue
        if content_type == "application/pdf" or content.lstrip().startswith(b"%PDF-"):
            try:
                parsed = await asyncio.to_thread(
                    read_pdf_bytes, content, source=res.final_url or res.url, run_dir=run_dir,
                    requested_url=res.url, deliver=False,
                )
            except Exception as exc:
                parsed = {"status": "error", "error": type(exc).__name__}
            document = parsed.get("source_document") or persist_document(
                source=res.final_url or res.url, content_type="application/pdf", content_bytes=content,
                coverage={**coverage, "method": "pdf", "reason": parsed.get("error", "pdf_unreadable")},
                run_dir=run_dir, requested_url=res.url,
            )
            document = {"url": res.url, **document}
            source_documents[res.url] = document
            text_path = document.get("full_text_path") or document.get("text_path") or parsed.get("full_text_path")
            full_text = Path(text_path).read_text(encoding="utf-8") if text_path else parsed.get("text", "")
            if full_text.strip():
                raw_total_tokens += count_tokens(full_text)
                cleaned_docs.append(CleanDocument(url=res.url, title=parsed.get("file", res.url), clean_markdown=full_text))
            continue
        if content_type not in {"text/html", "application/xhtml+xml", "text/plain", "text/markdown"}:
            coverage["reason"] = "unsupported_content_type"
            source_documents[res.url] = {"url": res.url, **persist_document(
                source=res.final_url or res.url, content_type=content_type, content_bytes=content,
                coverage=coverage, run_dir=run_dir, requested_url=res.url,
            )}
            continue
        try:
            clean_res = (CleanDocument(url=res.url, title=res.url, clean_markdown=html)
                         if content_type in {"text/plain", "text/markdown"} else clean_html(html, url=res.url))
        except Exception as exc:
            source_documents[res.url] = {"url": res.url, **persist_document(
                source=res.final_url or res.url, content_type=content_type, content_bytes=content,
                coverage={**coverage, "reason": f"extraction_failed:{type(exc).__name__}"},
                run_dir=run_dir, requested_url=res.url,
            )}
            continue
        text = clean_res.clean_markdown
        # shortcut: short hydration shells need the rendered reader; site-specific extractors are needed when that reader still returns a shell.
        dynamic_shell = len(text.strip()) < 1200 and bool(re.search(
            r"__NEXT_DATA__|__next_f|id\s*=\s*['\"](?:root|app|__next)['\"]|enable javascript|loading\.\.\.", html, re.IGNORECASE,
        ))
        needs_rendering = not text.strip() or dynamic_shell
        coverage = {"extraction_complete": not needs_rendering,
                    "method": "direct_html", "reason": "dynamic_or_empty_shell" if needs_rendering else "",
                    "truncated": False, "scope": "fetched_body_main_content"}
        source_documents[res.url] = {"url": res.url, **persist_document(
            source=res.final_url or res.url, content_type=content_type, content_bytes=content,
            full_text=text, coverage=coverage, run_dir=run_dir, requested_url=res.url,
        )}
        if needs_rendering:
            needs_reader.append(res.url)
        else:
            raw_total_tokens += count_tokens(text)
            cleaned_docs.append(clean_res)

    # Step 2b: Reader-service fallback for client-rendered pages.
    # A direct fetch of a JS single-page app returns 200 with a script-only
    # shell; without this retry those pages contribute nothing and the whole
    # summary comes back empty.
    reader_used = 0
    reader_failures: list[dict[str, str]] = []
    if needs_reader:
        rendered = await fetch_rendered_markdown_batch_detailed(needs_reader)
        for url in needs_reader:
            markdown, reason = rendered.get(url, ("", "rendered_reader_failed"))
            if not markdown.strip():
                reader_failures.append({"url": url, "reason": reason or "unknown"})
                continue
            original = source_documents[url]
            document = persist_document(
                source=original.get("source") or url, requested_url=url,
                content_type="text/markdown", content_bytes=markdown.encode("utf-8"),
                full_text=markdown, coverage={"extraction_complete": not bool(reason),
                    "method": "rendered_reader", "reason": reason,
                    "truncated": reason == "response_size_limit_exceeded", "scope": "rendered_body_main_content"}, run_dir=run_dir,
            )
            source_documents[url] = {"url": url, **document, "original_snapshot": original}
            raw_total_tokens += count_tokens(markdown)
            cleaned_docs.append(
                CleanDocument(
                    url=url,
                    title=markdown.split("\n", 1)[0].strip()[:200],
                    clean_markdown=markdown,
                )
            )
            reader_used += 1

    for url in urls:
        if url not in source_documents:
            source_documents[url] = {"url": url, "coverage": {"status": "blocked", "complete": False,
                "extraction_complete": False, "text_delivery_complete": False,
                "reason": "redirect_wrapper" if url in skipped_wrappers else "no_fetch_result"}}
    for requested_url, document in source_documents.items():
        document["final_url"] = document.get("source") or requested_url
        document["url"] = requested_url
        document["full_text_path"] = document.get("full_text_path") or document.get("text_path")
        if (document.get("coverage") or {}).get("complete") is not True:
            # This tool delivers excerpts, not the full text. Citing the URL
            # without a read_url pass leaves an incomplete source and the
            # research release gate refuses the report; say what to do next
            # instead of letting the model assume the excerpt was the read.
            document["read_url_required"] = True
            document["next_step"] = (
                "Gọi read_url cho URL này và đọc hết các chunk (next_offset) "
                "trước khi trích dẫn, hoặc bỏ nguồn và các số liệu dựa trên nó."
            )
    extraction_count = sum((document.get("coverage") or {}).get("extraction_complete") is True for document in source_documents.values())
    complete_count = sum((document.get("coverage") or {}).get("complete") is True for document in source_documents.values())
    delivery_count = sum((document.get("coverage") or {}).get("text_delivery_complete") is True for document in source_documents.values())
    coverage = {"status": "complete" if complete_count == len(source_documents) else ("partial" if cleaned_docs else "blocked"),
                "extraction_complete": extraction_count == len(source_documents),
                "text_delivery_complete": delivery_count == len(source_documents), "complete": complete_count == len(source_documents),
                "documents_requested": len(source_documents), "documents_extracted": extraction_count,
                "documents_complete": complete_count, "documents_incomplete": len(source_documents) - complete_count}

    # Step 3: 3-Tier Deduplication
    deduped_docs: list[CleanDocument] = deduplicate_documents(cleaned_docs)

    # Step 4: Semantic Token Pruning & Budgeting
    active_query = query or ("Thông tin tài chính doanh nghiệp " + " ".join(target_tickers or []))
    pruned_docs: list[PrunedDocument] = prune_documents(
        # pyrefly: ignore[bad-argument-type]
        docs=deduped_docs,
        query=active_query,
        tickers=target_tickers,
        total_budget=total_token_budget,
    )

    pruned_total_tokens = sum(d.pruned_token_count for d in pruned_docs)
    reduction_pct = (
        round(((raw_total_tokens - pruned_total_tokens) / raw_total_tokens) * 100.0, 2)
        if raw_total_tokens > 0
        else 0.0
    )

    token_stats = {
        "raw_tokens": raw_total_tokens,
        "pruned_tokens": pruned_total_tokens,
        "reduction_pct": reduction_pct,
        "documents_requested": len(urls),
        "documents_fetched": len(scrape_results),
        "documents_cleaned": len(cleaned_docs),
        "documents_deduplicated": len(deduped_docs),
        "reader_fallback_used": reader_used,
        "wrapper_urls_skipped": len(skipped_wrappers),
    }

    # Per-URL fetch outcome, so the agent can tell "page had no content" apart
    # from "page was never reachable" instead of seeing an empty summary.
    fetch_errors = [
        {
            "url": r.url,
            "status_code": r.status_code,
            "error": r.error,
        }
        for r in scrape_results
        if not r.success
    ]

    # Step 5: Map-Reduce Synthesis & Grounding
    artifact: Optional[SynthesizedResearchArtifact] = None
    summary_markdown = ""

    if synthesize and pruned_docs:
        artifact = await synthesize_research(
            docs=pruned_docs,
            query=active_query,
            target_tickers=target_tickers,
            token_stats=token_stats,
        )
        summary_markdown = artifact.to_compact_markdown()
    else:
        # Fallback raw concatenated markdown with source tags
        summary_parts = []
        for d in pruned_docs:
            summary_parts.append(f"### [{d.source_id}] {d.title} ({d.url})\n\n{d.combined_markdown}")
        summary_markdown = "\n\n---\n\n".join(summary_parts)

    elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
    token_stats["latency_ms"] = elapsed_ms

    payload = {
        "status": "ok" if coverage["extraction_complete"] else "partial",
        "query": active_query,
        "coverage": coverage,
        "source_documents": list(source_documents.values()),
        "summary_is_excerpt": True,
        "summary_markdown": summary_markdown,
        "token_stats": token_stats,
        "sources": [
            {
                "source_id": d.source_id,
                "title": d.title,
                "url": d.url,
                "tier": d.publisher_tier,
                "chunks_count": len(d.selected_chunks),
                "tokens": d.pruned_token_count,
                "excerpt": d.combined_markdown[:400],
                "source_document": source_documents.get(d.url),
            }
            for d in pruned_docs
        ],
        "reconciled_metrics": [m.model_dump() for m in artifact.reconciled_metrics] if artifact else [],
        "structured_artifact": artifact.model_dump() if artifact else None,
    }
    if fetch_errors:
        payload["fetch_errors"] = fetch_errors
    if reader_failures:
        payload["reader_fallback_failures"] = reader_failures
    if skipped_wrappers:
        payload["skipped_wrapper_urls"] = skipped_wrappers
    if not pruned_docs:
        # No usable content: say so plainly instead of returning an empty
        # summary that reads like a successful, content-free answer.
        payload["status"] = "empty"
        parts = [
            "No usable text was extracted from the requested URLs.",
            f"{len(fetch_errors)} of {len(scrape_results)} fetches failed",
        ]
        if skipped_wrappers:
            parts.append(
                f"{len(skipped_wrappers)} URLs were redirect wrappers and were "
                "skipped here; read them with read_url, which resolves the "
                "wrapper to the publisher before fetching"
            )
        if reader_failures:
            parts.append(
                f"{len(reader_failures)} pages had no server-rendered text and "
                "the reader service could not render them either"
            )
        payload["error"] = ". ".join(parts) + "."

    return with_security_warnings(payload, fields=("summary_markdown", "sources.*.title"))


class ParallelWebSearchTool(BaseTool):
    """Multi-Engine Parallel Web Search Tool with RRF Ranking."""

    name: str = "parallel_web_search"
    description: str = (
        "Tìm kiếm thông tin web song song trên nhiều công cụ (DuckDuckGo, Brave, Bing, QVeris, và các cổng thông tin tài chính Việt Nam: CafeF, Vietstock). "
        "Hỗ trợ phân tán nhiều truy vấn cùng một lúc, tự động loại bỏ liên kết trùng lặp trên cùng một domain (Domain Diversity Gate) "
        "và xếp hạng theo chuẩn thuật toán Reciprocal Rank Fusion (RRF). "
        "Mỗi kết quả có 'readable' (fetch trực tiếp được) và 'requires_resolution' "
        "(link Google News cần phân giải); link requires_resolution vẫn đọc được "
        "bằng read_url vì read_url tự phân giải wrapper sang trang gốc trước khi fetch."
    )
    repeatable: bool = True
    is_readonly: bool = True
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Truy vấn tìm kiếm chính (ví dụ: 'kết quả kinh doanh HPG quý 3 năm 2024').",
            },
            "queries": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Tùy chọn: Danh sách các truy vấn mở rộng để tìm kiếm song song đồng thời.",
            },
            "max_results": {
                "type": "integer",
                "description": "Số lượng kết quả tối đa cần trả về (mặc định: 8, tối đa: 20).",
                "default": 8,
            },
            "category": {
                "type": "string",
                "description": "Phân loại tìm kiếm ('finance', 'news', 'general'). Mặc định 'finance'.",
                "default": "finance",
            },
        },
        "required": ["query"],
    }

    def execute(self, **kwargs: Any) -> str:
        query = str(kwargs.get("query", "")).strip()
        if not query:
            return json.dumps({"status": "error", "error": "Query cannot be empty."}, ensure_ascii=False)

        max_results = min(20, max(1, int(kwargs.get("max_results", 8))))
        queries = kwargs.get("queries")
        category = str(kwargs.get("category", "finance"))

        try:
            result = _run_async_safely(
                parallel_web_search_async(
                    query=query,
                    max_results=max_results,
                    queries=queries if isinstance(queries, list) else None,
                    category=category,
                )
            )
            return json.dumps(result, ensure_ascii=False)
        except Exception as exc:
            logger.exception("parallel_web_search failed: %s", exc)
            return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)


class ConcurrentScraperTool(BaseTool):
    """High-Throughput Concurrent Scraper & Token Optimizer Tool."""

    name: str = "concurrent_scraper"
    description: str = (
        "Cào và đọc đồng thời nhiều trang web cùng lúc (5 - 15 URLs), trang bị lớp bảo mật chống tấn công SSRF & DNS Rebinding bằng Socket IP Pinning, "
        "lọc sạch quảng cáo, menu và mã độc bằng Rust nh3, chuyển đổi bảng BCTC sang Markdown GFM chuẩn xác, "
        "lưu bản gốc và toàn bộ văn bản sạch trước khi chọn trích đoạn BM25-FSB; trả source_documents và coverage cho phần đọc thiếu hoặc bị chặn, "
        "và tự động tổng hợp số liệu Map-Reduce kèm đối chiếu chéo và trích dẫn chuẩn [S1], [S2]."
    )
    repeatable: bool = True
    is_readonly: bool = True
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "urls": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Danh sách các URL cần cào và phân tích song song đồng thời.",
            },
            "url": {
                "type": "string",
                "description": "Tương thích ngược: URL đơn lẻ cần đọc.",
            },
            "query": {
                "type": "string",
                "description": "Truy vấn nghiên cứu định hướng cắt tỉa token và trích xuất chỉ tiêu tài chính.",
            },
            "target_tickers": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Danh sách mã cổ phiếu mục tiêu (ví dụ: ['HPG', 'VNM']).",
            },
            "token_budget": {
                "type": "integer",
                "description": "Ngân sách token tối đa phân bổ cho toàn bộ tài liệu (mặc định: 2500 tokens).",
                "default": 2500,
            },
            "synthesize": {
                "type": "boolean",
                "description": "Có chạy động cơ tổng hợp Map-Reduce và tạo bảng ma trận đối chiếu số liệu hay không (mặc định: True).",
                "default": True,
            },
            "concurrency_limit": {
                "type": "integer",
                "description": "Tổng số kết nối đồng thời tối đa khi cào (mặc định: 10).",
                "default": 10,
            },
            "per_host_limit": {
                "type": "integer",
                "description": "Số kết nối đồng thời tối đa trên mỗi host (mặc định: 3, chống rate-limit).",
                "default": 3,
            },
            "request_timeout": {
                "type": "number",
                "description": "Timeout (giây) cho mỗi URL khi cào (mặc định: 6.0).",
                "default": 6.0,
            },
        },
    }

    def execute(self, **kwargs: Any) -> str:
        # Support both 'urls' array and legacy 'url' string
        raw_urls = kwargs.get("urls")
        if not raw_urls and "url" in kwargs:
            raw_urls = [kwargs["url"]]

        if not raw_urls or not isinstance(raw_urls, list):
            return json.dumps({"status": "error", "error": "No valid URLs provided to scrape."}, ensure_ascii=False)

        clean_urls = [str(u).strip() for u in raw_urls if str(u).strip()]
        if not clean_urls:
            return json.dumps({"status": "error", "error": "URL list is empty."}, ensure_ascii=False)

        query = str(kwargs.get("query", "")).strip()
        target_tickers = kwargs.get("target_tickers")
        token_budget = int(kwargs.get("token_budget", 2500))
        synthesize = bool(kwargs.get("synthesize", True))
        concurrency_limit = max(1, min(30, int(kwargs.get("concurrency_limit", 10))))
        per_host_limit = max(1, min(6, int(kwargs.get("per_host_limit", 3))))
        request_timeout = max(1.0, min(30.0, float(kwargs.get("request_timeout", 6.0))))

        try:
            result = _run_async_safely(
                concurrent_scrape_and_synthesize_async(
                    urls=clean_urls,
                    query=query,
                    target_tickers=target_tickers if isinstance(target_tickers, list) else None,
                    total_token_budget=token_budget,
                    synthesize=synthesize,
                    concurrency_limit=concurrency_limit,
                    per_host_limit=per_host_limit,
                    request_timeout=request_timeout,
                    run_dir=kwargs.get("run_dir"),
                )
            )
            return json.dumps(result, ensure_ascii=False)
        except Exception as exc:
            logger.exception("concurrent_scraper failed: %s", exc)
            return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)
