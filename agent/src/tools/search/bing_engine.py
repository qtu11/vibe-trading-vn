"""Bing search engine adapter supporting organic search and Azure Bing API."""

from __future__ import annotations

import logging
import os
import urllib.parse
from typing import Any

import httpx
from bs4 import BeautifulSoup

from .base_engine import BaseSearchEngine, SearchResult

logger = logging.getLogger(__name__)

_BING_WEB_URL = "https://www.bing.com/search"
_BING_CN_URL = "https://cn.bing.com/search"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _decode_b64url(value: str) -> str:
    """Base64url-decode a value, restoring the stripped padding."""
    import base64

    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")


def _decode_b64(value: str) -> str:
    """Base64-decode a value, restoring the stripped padding."""
    import base64

    padded = value + "=" * (-len(value) % 4)
    return base64.b64decode(padded).decode("utf-8", errors="replace")


class BingSearchEngine(BaseSearchEngine):
    """Bing organic and API search adapter."""

    def __init__(
        self,
        name: str = "bing",
        weight: float = 1.0,
        api_key: str | None = None,
        use_cn_fallback: bool = True,
    ) -> None:
        super().__init__(name=name, weight=weight)
        self.api_key = (
            api_key
            or os.getenv("BING_API_KEY")
            or os.getenv("AZURE_BING_API_KEY")
            or ""
        ).strip()
        self.use_cn_fallback = use_cn_fallback
        self._http_client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                headers={
                    "User-Agent": _USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
                },
                timeout=httpx.Timeout(4.5, connect=2.5),
                follow_redirects=True,
            )
        return self._http_client

    def _parse_bing_html(self, html_text: str, max_results: int) -> list[SearchResult]:
        soup = BeautifulSoup(html_text, "html.parser")
        results: list[SearchResult] = []

        # Standard Bing search result items
        items = soup.select("li.b_algo")
        for item in items:
            title_tag = item.select_one("h2 a")
            if not title_tag:
                continue

            url = title_tag.get("href", "")
            title = title_tag.get_text(strip=True)

            url = self._unwrap_redirect(url)

            # Skip Bing internal or ad links
            if (
                not url
                or url.startswith("/")
                or "bing.com" in url
                or "microsoft.com/rewards" in url
            ):
                continue

            snippet_tag = item.select_one(".b_caption p, .b_snippet, .b_algoSlug, p")
            snippet = snippet_tag.get_text(strip=True) if snippet_tag else ""

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

    @staticmethod
    def _unwrap_redirect(url: str) -> str:
        """Recover the publisher URL from a Bing click-tracking redirect.

        Bing wraps every organic link as
        ``https://www.bing.com/ck/a?...&u=a1<percent-encoded-url>``. The
        wrapper is a real URL that contains "bing.com", so filtering on the
        host alone drops every result. The publisher URL is in the ``u``
        parameter, base64 (sometimes URL-safe) encoded with a leading "a1".
        """
        if not url or "bing.com/ck/" not in url:
            return url
        try:
            parsed = urllib.parse.urlsplit(url)
            params = urllib.parse.parse_qs(parsed.query)
        except ValueError:
            return url
        encoded = (params.get("u") or params.get("r") or [None])[0]
        if not encoded:
            return url
        if encoded.startswith("a1"):
            encoded = encoded[2:]
        # The value may still be percent-encoded.
        encoded = urllib.parse.unquote(encoded)
        if not encoded:
            return url
        for decoder in (_decode_b64url, _decode_b64):
            try:
                candidate = decoder(encoded)
            except Exception:
                continue
            if candidate.startswith(("http://", "https://")):
                return candidate
        return url

    async def _search_organic(self, url: str, query: str, max_results: int) -> list[SearchResult]:
        client = await self._get_client()
        params = {"q": query}
        try:
            resp = await client.get(url, params=params)
            if resp.status_code != 200:
                logger.debug("Bing endpoint %s returned HTTP %d", url, resp.status_code)
                return []
            return self._parse_bing_html(resp.text, max_results)
        except Exception as exc:
            logger.debug("Bing organic search at %s failed: %s", url, exc)
            return []

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """Execute Bing search via standard or CN endpoint."""
        if not query or not query.strip():
            return []

        # 1. Standard Bing organic search
        results = await self._search_organic(_BING_WEB_URL, query, max_results)
        if results:
            return results

        # 2. Fallback to cn.bing.com if enabled and standard Bing yielded no results
        if self.use_cn_fallback:
            cn_results = await self._search_organic(_BING_CN_URL, query, max_results)
            if cn_results:
                return cn_results

        return []

    async def close(self) -> None:
        """Close underlying HTTP client."""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None
