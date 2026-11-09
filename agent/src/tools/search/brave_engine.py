"""Brave Search engine adapter with API and organic scraping fallback."""

from __future__ import annotations

import logging
import os
import urllib.parse
from typing import Any

import httpx
from bs4 import BeautifulSoup

from .base_engine import BaseSearchEngine, SearchResult

logger = logging.getLogger(__name__)

_BRAVE_API_URL = "https://api.search.brave.com/res/v1/web/search"
_BRAVE_WEB_URL = "https://search.brave.com/search"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class BraveSearchEngine(BaseSearchEngine):
    """Brave Search engine using official API when available, organic scraping otherwise."""

    def __init__(
        self,
        name: str = "brave",
        weight: float = 1.2,
        api_key: str | None = None,
    ) -> None:
        super().__init__(name=name, weight=weight)
        self.api_key = (
            api_key
            or os.getenv("BRAVE_API_KEY")
            or os.getenv("VIBE_TRADING_BRAVE_API_KEY")
            or ""
        ).strip()
        self._http_client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                headers={"User-Agent": _USER_AGENT, "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7"},
                timeout=httpx.Timeout(4.0, connect=2.5),
                follow_redirects=True,
            )
        return self._http_client

    async def _search_api(self, query: str, max_results: int) -> list[SearchResult] | None:
        """Query official Brave Search API."""
        if not self.api_key:
            return None
        client = await self._get_client()
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": self.api_key,
        }
        params = {"q": query, "count": min(max_results, 20)}
        try:
            resp = await client.get(_BRAVE_API_URL, headers=headers, params=params)
            if resp.status_code != 200:
                logger.warning("Brave API returned HTTP %s: %s", resp.status_code, resp.text[:200])
                return None
            data = resp.json()
            web_results = data.get("web", {}).get("results", [])
            results: list[SearchResult] = []
            for item in web_results[:max_results]:
                title = item.get("title", "")
                url = item.get("url", "")
                snippet = item.get("description", "")
                age = item.get("page_age") or item.get("age")
                if url and title:
                    results.append(
                        SearchResult(
                            title=title,
                            url=url,
                            snippet=snippet,
                            source=self.name,
                            published_at=str(age) if age else None,
                        )
                    )
            return results
        except Exception as exc:
            logger.warning("Brave API request failed: %s", exc)
            return None

    async def _search_organic(self, query: str, max_results: int) -> list[SearchResult]:
        """Scrape Brave Search web results when API is unavailable."""
        client = await self._get_client()
        params = {"q": query, "source": "web"}
        try:
            resp = await client.get(_BRAVE_WEB_URL, params=params)
            if resp.status_code != 200:
                return []

            soup = BeautifulSoup(resp.text, "html.parser")
            results: list[SearchResult] = []

            # Brave search uses result divs with class containing snippet / title
            for container in soup.select("div.snippet[data-type='web'], div.result[data-type='web'], div[data-type='web']"):
                a_tag = container.select_one("a.title, a.h[href], a[href]")
                if not a_tag:
                    continue
                url = a_tag.get("href", "")
                if not url or url.startswith("/") or "brave.com" in url:
                    continue

                title = a_tag.get_text(strip=True)
                desc_tag = container.select_one(".snippet-description, .content, .description, p")
                snippet = desc_tag.get_text(strip=True) if desc_tag else ""

                if title and url:
                    results.append(
                        SearchResult(
                            title=title,
                            url=url,
                            snippet=snippet,
                            source=self.name,
                        )
                    )
                if len(results) >= max_results:
                    break

            return results
        except Exception as exc:
            logger.debug("Brave organic search failed: %s", exc)
            return []

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """Search via Brave API, falling back to organic web results."""
        if not query or not query.strip():
            return []

        # 1. Official API if key present
        if self.api_key:
            api_res = await self._search_api(query, max_results)
            if api_res is not None:
                return api_res

        # 2. Organic web scraping fallback
        return await self._search_organic(query, max_results)

    async def close(self) -> None:
        """Close underlying HTTP client."""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None
