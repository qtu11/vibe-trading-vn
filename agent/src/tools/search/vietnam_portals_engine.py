"""Vietnam financial portals search engine adapter (CafeF, Vietstock, Google News VN)."""

from __future__ import annotations

import asyncio
import html
import logging
import re
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Any

import httpx
from bs4 import BeautifulSoup

from .base_engine import BaseSearchEngine, SearchResult

logger = logging.getLogger(__name__)

_GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search"
_CAFEF_SEARCH_URL = "https://cafef.vn/tim-kiem.chn"
_VIETSTOCK_SEARCH_URL = "https://vietstock.vn/tim-kiem.htm"

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_TAG_RE = re.compile(r"<[^>]+>")


def _clean_html_text(raw_html: str) -> str:
    """Strip HTML tags and unescape entities."""
    if not raw_html:
        return ""
    text = _TAG_RE.sub(" ", raw_html)
    return " ".join(html.unescape(text).split())


class VietnamFinancialPortalsEngine(BaseSearchEngine):
    """Aggregated search for Vietnamese financial portals and news."""

    def __init__(
        self,
        name: str = "vietnam_portals",
        weight: float = 1.5,
    ) -> None:
        super().__init__(name=name, weight=weight)
        self._http_client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                headers={
                    "User-Agent": _USER_AGENT,
                    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
                },
                timeout=httpx.Timeout(4.5, connect=2.5),
                follow_redirects=True,
            )
        return self._http_client

    async def _search_google_news_vn(self, query: str, max_results: int) -> list[SearchResult]:
        """Query Google News VN RSS for financial ticker or topic."""
        client = await self._get_client()
        params = {
            "q": query,
            "hl": "vi",
            "gl": "VN",
            "ceid": "VN:vi",
        }
        try:
            resp = await client.get(_GOOGLE_NEWS_RSS_URL, params=params)
            if resp.status_code != 200:
                return []

            root = ET.fromstring(resp.content)
            results: list[SearchResult] = []
            channel = root.find("channel")
            if channel is None:
                return []

            for item in channel.findall("item"):
                title_elem = item.find("title")
                link_elem = item.find("link")
                pub_elem = item.find("pubDate")
                desc_elem = item.find("description")
                source_elem = item.find("source")

                title = title_elem.text if title_elem is not None and title_elem.text else ""
                url = link_elem.text if link_elem is not None and link_elem.text else ""
                pub_date = pub_elem.text if pub_elem is not None and pub_elem.text else None
                desc = desc_elem.text if desc_elem is not None and desc_elem.text else ""
                src_name = (
                    source_elem.text
                    if source_elem is not None and source_elem.text
                    else "GoogleNewsVN"
                )

                snippet = _clean_html_text(desc)
                if title and url:
                    results.append(
                        SearchResult(
                            title=title,
                            url=url,
                            snippet=snippet,
                            source=f"google_news_vn/{src_name.lower().replace(' ', '_')}",
                            published_at=pub_date,
                            extra={"publisher": src_name},
                        )
                    )
                if len(results) >= max_results:
                    break

            return results
        except Exception as exc:
            logger.debug("Google News VN RSS search error: %s", exc)
            return []

    async def _search_cafef(self, query: str, max_results: int) -> list[SearchResult]:
        """Search CafeF financial news portal."""
        client = await self._get_client()
        params = {"keywords": query}
        try:
            resp = await client.get(_CAFEF_SEARCH_URL, params=params)
            if resp.status_code != 200:
                return []

            soup = BeautifulSoup(resp.text, "html.parser")
            results: list[SearchResult] = []

            # CafeF search items in .search_content or .tlitem or .item
            items = soup.select(".search_content .item, .tlitem, .item_news, .list_news li, .box-category-item")
            for item in items:
                title_tag = item.select_one("h3 a, h2 a, a.title, .item-title a")
                if not title_tag:
                    continue

                url = title_tag.get("href", "")
                title = title_tag.get_text(strip=True)

                if url and not url.startswith("http"):
                    url = urllib.parse.urljoin("https://cafef.vn", url)

                snippet_tag = item.select_one(".sapo, .desc, p, .item-desc")
                snippet = snippet_tag.get_text(strip=True) if snippet_tag else ""

                date_tag = item.select_one(".time, .item-time, .date")
                pub_date = date_tag.get_text(strip=True) if date_tag else None

                if url and title and "cafef.vn" in url:
                    results.append(
                        SearchResult(
                            title=title,
                            url=url,
                            snippet=snippet,
                            source="cafef",
                            published_at=pub_date,
                        )
                    )
                if len(results) >= max_results:
                    break

            return results
        except Exception as exc:
            logger.debug("CafeF search error: %s", exc)
            return []

    async def _search_vietstock(self, query: str, max_results: int) -> list[SearchResult]:
        """Search Vietstock financial portal."""
        client = await self._get_client()
        params = {"q": query}
        try:
            resp = await client.get(_VIETSTOCK_SEARCH_URL, params=params)
            if resp.status_code != 200:
                return []

            soup = BeautifulSoup(resp.text, "html.parser")
            results: list[SearchResult] = []

            items = soup.select(".channel-news-item, .news-item, .box-item")
            for item in items:
                title_tag = item.select_one("a.channel-news-title, h3 a, h2 a, a.title")
                if not title_tag:
                    continue

                url = title_tag.get("href", "")
                title = title_tag.get_text(strip=True)

                if url and not url.startswith("http"):
                    url = urllib.parse.urljoin("https://vietstock.vn", url)

                snippet_tag = item.select_one(".channel-news-des, p.des, .desc, p")
                snippet = snippet_tag.get_text(strip=True) if snippet_tag else ""

                date_tag = item.select_one(".channel-date, .date, .time")
                pub_date = date_tag.get_text(strip=True) if date_tag else None

                if url and title and "vietstock.vn" in url:
                    results.append(
                        SearchResult(
                            title=title,
                            url=url,
                            snippet=snippet,
                            source="vietstock",
                            published_at=pub_date,
                        )
                    )
                if len(results) >= max_results:
                    break

            return results
        except Exception as exc:
            logger.debug("Vietstock search error: %s", exc)
            return []

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """Concurrently search Google News VN, CafeF, and Vietstock."""
        if not query or not query.strip():
            return []

        # Run portal searches concurrently
        tasks = [
            self._search_google_news_vn(query, max_results),
            self._search_cafef(query, max_results),
            self._search_vietstock(query, max_results),
        ]
        sub_results = await asyncio.gather(*tasks, return_exceptions=True)

        combined: list[SearchResult] = []
        seen_urls: set[str] = set()

        for res in sub_results:
            if isinstance(res, list):
                for item in res:
                    norm_url = item.url.strip().lower()
                    if norm_url not in seen_urls:
                        seen_urls.add(norm_url)
                        combined.append(item)

        return combined[:max_results]

    async def close(self) -> None:
        """Close underlying HTTP client."""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None
