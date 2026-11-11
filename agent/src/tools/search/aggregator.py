"""MultiSearchAggregator with concurrent dispatch, RRF re-ranking, and Domain Diversity Gate."""

from __future__ import annotations

import asyncio
import logging
import re
import urllib.parse
from collections import defaultdict
from typing import Any, Sequence

from .base_engine import BaseSearchEngine, SearchResult
from .bing_engine import BingSearchEngine
from .brave_engine import BraveSearchEngine
from .ddg_engine import DuckDuckGoEngine
from .qveris_engine import QverisSearchEngine
from .vietnam_portals_engine import VietnamFinancialPortalsEngine

try:  # The scraper package owns the wrapper-URL rules; keep this optional.
    from src.tools.scraper.url_resolver import is_unreadable_wrapper
except Exception:  # noqa: BLE001 - search must work without the scraper package
    def is_unreadable_wrapper(url: str) -> bool:
        """Fallback used when the scraper package is unavailable."""
        return "news.google.com/rss/articles/" in url

logger = logging.getLogger(__name__)

# Heuristic patterns for Vietnamese stock tickers and financial terminology
_VN_TICKER_RE = re.compile(r"\b[A-Z]{3}\b")
_VN_FINANCIAL_WORDS = {
    "cổ phiếu", "chứng khoán", "lợi nhuận", "doanh thu", "bctc", "tài chính",
    "cổ tức", "vnindex", "vn-index", "hnx", "hose", "upcom", "vốn hóa",
    "đhcđ", "báo cáo tài chính", "eps", "p/e", "p/b", "tăng trưởng"
}


def _is_vietnam_financial_query(query: str) -> bool:
    """Detect if query is targeted at Vietnam equity markets."""
    q_lower = query.lower()
    for word in _VN_FINANCIAL_WORDS:
        if word in q_lower:
            return True
    # Check for 3-letter stock ticker uppercase or in context
    if _VN_TICKER_RE.search(query):
        return True
    return False


def _extract_domain(url: str) -> str:
    """Extract normalized domain from URL for diversity gating."""
    try:
        parsed = urllib.parse.urlsplit(url)
        netloc = parsed.netloc.lower()
        if ":" in netloc:
            netloc = netloc.split(":")[0]
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc or "unknown"
    except Exception:
        return "unknown"


def _normalize_url(url: str) -> str:
    """Normalize URL by stripping tracking parameters, trailing slashes, and fragments."""
    try:
        parsed = urllib.parse.urlsplit(url)
        # Drop UTM, fbclid, ref, and other tracking query parameters
        qs = urllib.parse.parse_qsl(parsed.query)
        clean_qs = [
            (k, v) for k, v in qs
            if not k.startswith("utm_") and k not in {"fbclid", "gclid", "ref", "spm"}
        ]
        clean_query = urllib.parse.urlencode(clean_qs)
        path = parsed.path.rstrip("/")
        normalized = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc.lower(), path, clean_query, ""))
        return normalized or url
    except Exception:
        return url


class MultiSearchAggregator:
    """Orchestrates parallel multi-engine search with RRF and diversity filtering."""

    def __init__(
        self,
        engines: Sequence[BaseSearchEngine] | None = None,
        per_engine_timeout: float = 3.0,
        global_deadline: float = 4.5,
        rrf_k: int = 60,
        max_per_domain: int = 2,
    ) -> None:
        self.engines: list[BaseSearchEngine] = list(engines) if engines is not None else [
            DuckDuckGoEngine(weight=1.0),
            BraveSearchEngine(weight=1.2),
            BingSearchEngine(weight=1.0),
            QverisSearchEngine(weight=1.1),
            VietnamFinancialPortalsEngine(weight=1.5),
        ]
        self.per_engine_timeout = per_engine_timeout
        self.global_deadline = global_deadline
        self.rrf_k = rrf_k
        self.max_per_domain = max_per_domain

    async def _search_engine_with_timeout(
        self,
        engine: BaseSearchEngine,
        query: str,
        max_results: int,
    ) -> tuple[BaseSearchEngine, list[SearchResult]]:
        """Run search on a single engine with bounded timeout."""
        try:
            results = await asyncio.wait_for(
                engine.search(query, max_results=max_results),
                timeout=self.per_engine_timeout,
            )
            return engine, results
        except asyncio.TimeoutError:
            logger.warning("Engine %s timed out after %.1fs", engine.name, self.per_engine_timeout)
            return engine, []
        except Exception as exc:
            logger.warning("Engine %s failed: %s", engine.name, exc)
            return engine, []

    async def search(
        self,
        query: str,
        max_results: int = 5,
        engine_subset: list[str] | None = None,
    ) -> list[SearchResult]:
        """Concurrently search across all active engines and fuse rankings using RRF.

        Args:
            query: User search query.
            max_results: Total aggregated top results to return.
            engine_subset: Optional list of engine names to restrict search to.

        Returns:
            Ranked list of SearchResult items adhering to domain diversity.
        """
        if not query or not query.strip():
            return []

        clean_query = query.strip()
        is_vn_financial = _is_vietnam_financial_query(clean_query)

        # Filter engines if engine_subset is specified
        target_engines = self.engines
        if engine_subset:
            subset_set = {e.lower() for e in engine_subset}
            target_engines = [e for e in self.engines if e.name.lower() in subset_set]
            if not target_engines:
                target_engines = self.engines

        # Prepare concurrent coroutines
        fetch_tasks = [
            asyncio.ensure_future(
                self._search_engine_with_timeout(engine, clean_query, max_results=max_results * 2)
            )
            for engine in target_engines
        ]

        # ``asyncio.wait`` returns the tasks that finished, so a deadline
        # keeps the answers of the fast engines. Cancelling the whole gather
        # would throw them away, which is what made a single slow engine
        # erase every result.
        done, pending = await asyncio.wait(
            fetch_tasks, timeout=self.global_deadline, return_when=asyncio.ALL_COMPLETED
        )
        if pending:
            logger.warning(
                "Global search aggregation deadline %.1fs reached; kept %d of %d engines",
                self.global_deadline,
                len(done),
                len(fetch_tasks),
            )
            for task in pending:
                task.cancel()

        completed_batches: list[Any] = []
        for task in done:
            if task.cancelled():
                continue
            item = task.exception()
            if item is None:
                completed_batches.append(task.result())
            else:
                completed_batches.append(item)

        # Map document -> RRF score & representative SearchResult
        rrf_scores: dict[str, float] = defaultdict(float)
        canonical_docs: dict[str, SearchResult] = {}
        sources_per_doc: dict[str, set[str]] = defaultdict(set)

        for item in completed_batches:
            if isinstance(item, Exception) or not isinstance(item, tuple):
                continue
            engine, engine_results = item
            if not engine_results:
                continue

            # Compute dynamic weight
            weight = engine.weight
            if is_vn_financial and engine.name in {"vietnam_portals", "cafef", "vietstock"}:
                weight *= 1.4

            for rank_0, doc in enumerate(engine_results):
                rank = rank_0 + 1
                norm_url = _normalize_url(doc.url)
                if not norm_url:
                    continue

                # Reciprocal Rank Fusion formula: W_e / (k + rank)
                score_increment = weight / (self.rrf_k + rank)
                rrf_scores[norm_url] += score_increment
                sources_per_doc[norm_url].add(doc.source)

                # Keep the richest snippet and title
                if norm_url not in canonical_docs:
                    canonical_docs[norm_url] = doc
                else:
                    existing = canonical_docs[norm_url]
                    if len(doc.snippet) > len(existing.snippet):
                        canonical_docs[norm_url].snippet = doc.snippet
                    if not existing.published_at and doc.published_at:
                        canonical_docs[norm_url].published_at = doc.published_at

        if not rrf_scores:
            return []

        # Sort documents by total RRF score descending
        sorted_urls = sorted(rrf_scores.keys(), key=lambda u: rrf_scores[u], reverse=True)

        # Domain Diversity Gate: max N results per domain
        final_results: list[SearchResult] = []
        domain_counts: dict[str, int] = defaultdict(int)

        for url in sorted_urls:
            domain = _extract_domain(url)
            if domain_counts[domain] >= self.max_per_domain:
                continue

            doc = canonical_docs[url]
            doc.score = rrf_scores[url]
            # Record aggregated sources in extra
            doc.extra["aggregated_sources"] = list(sources_per_doc[url])
            doc.extra["domain"] = domain
            # A Google News link points at a publisher page that no plain
            # fetch can read. Marking it lets the caller know read_url resolves
            # the wrapper first; it is not a reason to drop the link.
            doc.extra["is_wrapper"] = is_unreadable_wrapper(url)

            domain_counts[domain] += 1
            final_results.append(doc)

            if len(final_results) >= max_results:
                break

        return final_results

    async def close(self) -> None:
        """Close all child engines and release network resources."""
        await asyncio.gather(
            *[engine.close() for engine in self.engines],
            return_exceptions=True,
        )
