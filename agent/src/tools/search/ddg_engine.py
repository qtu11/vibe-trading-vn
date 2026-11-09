"""DuckDuckGo search engine adapter."""

from __future__ import annotations

import asyncio
import logging
import urllib.parse
from typing import Any

import httpx

try:
    from ddgs import DDGS
except ImportError:
    try:
        from duckduckgo_search import DDGS  # type: ignore[no-redef]
    except ImportError:
        DDGS = None  # type: ignore[assignment, misc]

from .base_engine import BaseSearchEngine, SearchResult

logger = logging.getLogger(__name__)

_DEFAULT_BACKENDS = "duckduckgo, google, bing, brave, mojeek, yahoo"
_DDG_HTML_URL = "https://html.duckduckgo.com/html/"
_DDG_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class DuckDuckGoEngine(BaseSearchEngine):
    """DuckDuckGo engine with multi-backend fallback and HTML backup."""

    def __init__(
        self,
        name: str = "duckduckgo",
        weight: float = 1.0,
        backends: str = _DEFAULT_BACKENDS,
    ) -> None:
        super().__init__(name=name, weight=weight)
        self.backends = backends
        self._http_client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                headers={"User-Agent": _DDG_USER_AGENT},
                timeout=httpx.Timeout(5.0, connect=3.0),
                follow_redirects=True,
            )
        return self._http_client

    def _sync_ddgs_search(self, query: str, max_results: int) -> list[dict[str, Any]]:
        """Synchronous DDGS call intended to run in a thread."""
        if DDGS is None:
            return []
        try:
            with DDGS() as client:
                try:
                    return list(client.text(query, max_results=max_results, backend=self.backends))
                except TypeError:
                    return list(client.text(query, max_results=max_results))
        except Exception as exc:
            logger.debug("DDGS sync search failed for '%s': %s", query, exc)
            return []

    async def _html_fallback_search(self, query: str, max_results: int) -> list[SearchResult]:
        """Fallback to DuckDuckGo HTML endpoint using httpx if DDGS fails."""
        try:
            client = await self._get_client()
            resp = await client.post(_DDG_HTML_URL, data={"q": query, "b": ""})
            if resp.status_code != 200:
                return []

            from bs4 import BeautifulSoup

            soup = BeautifulSoup(resp.text, "html.parser")
            results: list[SearchResult] = []

            for result_elem in soup.select(".result"):
                link_elem = result_elem.select_one(".result__a")
                if not link_elem:
                    continue
                raw_url = link_elem.get("href", "")
                # DuckDuckGo wraps URLs in /l/?uddg=...
                if "uddg=" in raw_url:
                    parsed = urllib.parse.urlparse(raw_url)
                    qs = urllib.parse.parse_qs(parsed.query)
                    if "uddg" in qs:
                        raw_url = qs["uddg"][0]
                elif raw_url.startswith("//"):
                    raw_url = "https:" + raw_url

                title = link_elem.get_text(strip=True)
                snippet_elem = result_elem.select_one(".result__snippet")
                snippet = snippet_elem.get_text(strip=True) if snippet_elem else ""

                if raw_url and title:
                    results.append(
                        SearchResult(
                            title=title,
                            url=raw_url,
                            snippet=snippet,
                            source=self.name,
                        )
                    )
                if len(results) >= max_results:
                    break

            return results
        except Exception as exc:
            logger.debug("DuckDuckGo HTML fallback failed: %s", exc)
            return []

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """Execute async search via DDGS or fallback to HTML."""
        if not query or not query.strip():
            return []

        # 1. Try DDGS via thread pool to avoid blocking the loop
        raw_items = await asyncio.to_thread(self._sync_ddgs_search, query, max_results)
        results: list[SearchResult] = []

        if raw_items:
            for item in raw_items:
                title = item.get("title") or ""
                url = item.get("href") or item.get("url") or ""
                snippet = item.get("body") or item.get("snippet") or ""
                if url and title:
                    results.append(
                        SearchResult(
                            title=title,
                            url=url,
                            snippet=snippet,
                            source=self.name,
                        )
                    )
            if results:
                return results[:max_results]

        # 2. If DDGS returned nothing or threw error, try HTML fallback
        return await self._html_fallback_search(query, max_results)

    async def close(self) -> None:
        """Close underlying HTTP client."""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None
