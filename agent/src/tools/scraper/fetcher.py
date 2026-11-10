"""Async Scraping Engine with connection pooling, SSRF invariant protection, and AIMD rate limiting."""

from __future__ import annotations

import asyncio
import logging
import random
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Sequence

import httpx

from .dns_cache import AsyncDNSCache
from .rate_limiter import AdaptiveRateLimiter
from .ssrf_guard import SSRFGuard, SSRFSafeTransport, SSRFSecurityError

logger = logging.getLogger(__name__)
_MAX_RESPONSE_BYTES = 20 * 1024 * 1024

# Modern desktop User-Agent pool
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.4; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
]


@dataclass
class ScrapeResult:
    """Standardized output model for scraped web resources (M1 -> M2 contract)."""

    url: str
    html_content: str
    status_code: int
    headers: dict[str, str] = field(default_factory=dict)
    latency_ms: float = 0.0
    resolved_ip: str = ""
    error: str | None = None
    success: bool = True
    final_url: str = ""
    content_bytes: bytes = b""
    content_type: str = ""
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert ScrapeResult to dictionary."""
        return {
            "url": self.url,
            "final_url": self.final_url or self.url,
            "status_code": self.status_code,
            "success": self.success,
            "latency_ms": round(self.latency_ms, 2),
            "resolved_ip": self.resolved_ip,
            "error": self.error,
            "content_length": len(self.html_content),
            "content_bytes": len(self.content_bytes),
            "content_type": self.content_type,
            "truncated": self.truncated,
        }


class AsyncScrapingEngine:
    """Production-grade async scraping engine with HTTP/2 pooling, SSRF invariants, and rate limiting."""

    def __init__(
        self,
        dns_cache: AsyncDNSCache | None = None,
        rate_limiter: AdaptiveRateLimiter | None = None,
        max_connections: int = 60,
        max_keepalive_connections: int = 30,
        keepalive_expiry: float = 30.0,
        http2: bool = True,
    ) -> None:
        self.dns_cache = dns_cache or AsyncDNSCache(ttl_seconds=300.0)
        self.rate_limiter = rate_limiter or AdaptiveRateLimiter()

        self._limits = httpx.Limits(
            max_connections=max_connections,
            max_keepalive_connections=max_keepalive_connections,
            keepalive_expiry=keepalive_expiry,
        )
        self._http2 = http2
        self._transport = SSRFSafeTransport(
            dns_resolver=self.dns_cache,
            verify=True,
            http2=self._http2,
            limits=self._limits,
        )
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                transport=self._transport,
                follow_redirects=True,
                max_redirects=5,
            )
        return self._client

    def _get_random_headers(self) -> dict[str, str]:
        """Generate randomized browser headers to mimic real navigation."""
        ua = random.choice(_USER_AGENTS)
        is_chrome = "Chrome" in ua
        headers = {
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
        }
        if is_chrome:
            headers["Sec-Ch-Ua"] = '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"'
            headers["Sec-Ch-Ua-Mobile"] = "?0"
            headers["Sec-Ch-Ua-Platform"] = '"Windows"' if "Windows" in ua else '"macOS"'
        return headers

    async def scrape_url(self, url: str, timeout: float = 10.0) -> ScrapeResult:
        """Scrape a single URL with SSRF invariant check, IP pinning, and rate limiting.

        Args:
            url: Target URL string.
            timeout: Maximum timeout in seconds.

        Returns:
            ScrapeResult containing status, HTML content, resolved IP, and latency.
        """
        start_time = time.monotonic()
        parsed = urllib.parse.urlsplit(url)
        host = parsed.hostname or ""

        # Pre-screen URL with SSRFGuard
        is_safe, resolved_ip, block_reason = SSRFGuard.validate_url(url)
        if not is_safe:
            return ScrapeResult(
                url=url,
                html_content="",
                status_code=403,
                latency_ms=(time.monotonic() - start_time) * 1000.0,
                resolved_ip=resolved_ip or "",
                error=f"SSRF violation: {block_reason}",
                success=False,
            )

        # Acquire rate limiter slot for host
        async with self.rate_limiter.acquire(host):
            client = await self._get_client()
            headers = self._get_random_headers()
            try:
                async with asyncio.timeout(timeout):
                    async with client.stream(
                        "GET", url, headers=headers,
                        timeout=httpx.Timeout(timeout, connect=min(timeout, 4.0)),
                    ) as resp:
                        body = bytearray()
                        truncated = False
                        async for chunk in resp.aiter_bytes():
                            if len(body) + len(chunk) > _MAX_RESPONSE_BYTES:
                                body.extend(chunk[:max(0, _MAX_RESPONSE_BYTES - len(body))])
                                truncated = True
                                break
                            body.extend(chunk)
                        content = bytes(body)
                        content_type = resp.headers.get("content-type", "text/html").split(";", 1)[0].strip().lower()
                        if content.lstrip().startswith(b"%PDF-"):
                            content_type = "application/pdf"
                        html_content = (content.decode(resp.encoding or "utf-8", errors="replace")
                                        if content_type in {"text/html", "application/xhtml+xml", "text/plain", "text/markdown"}
                                        and not truncated else "")
                latency = (time.monotonic() - start_time) * 1000.0

                # Inform rate limiter of success or failure
                self.rate_limiter.report_result(host, status_code=resp.status_code)

                # Convert headers to string dict
                res_headers = {k.lower(): v for k, v in resp.headers.items()}

                return ScrapeResult(
                    url=url,
                    final_url=str(resp.url),
                    html_content=html_content,
                    content_bytes=content,
                    content_type=content_type,
                    truncated=truncated,
                    status_code=413 if truncated else resp.status_code,
                    headers=res_headers,
                    latency_ms=latency,
                    resolved_ip=resolved_ip or "",
                    error="response_size_limit_exceeded" if truncated else (None if resp.is_success else f"HTTP {resp.status_code}"),
                    success=resp.is_success and not truncated,
                )
            except SSRFSecurityError as ssrf_err:
                latency = (time.monotonic() - start_time) * 1000.0
                return ScrapeResult(
                    url=url,
                    html_content="",
                    status_code=403,
                    latency_ms=latency,
                    resolved_ip="",
                    error=f"SSRF violation: {ssrf_err}",
                    success=False,
                )
            except (httpx.TimeoutException, TimeoutError) as timeout_err:
                latency = (time.monotonic() - start_time) * 1000.0
                self.rate_limiter.report_result(host, is_timeout=True)
                return ScrapeResult(
                    url=url,
                    html_content="",
                    status_code=408,
                    latency_ms=latency,
                    resolved_ip=resolved_ip or "",
                    error=f"Request timeout after {timeout:.1f}s: {timeout_err}",
                    success=False,
                )
            except Exception as exc:
                latency = (time.monotonic() - start_time) * 1000.0
                self.rate_limiter.report_result(host, is_timeout=False)
                return ScrapeResult(
                    url=url,
                    html_content="",
                    status_code=500,
                    latency_ms=latency,
                    resolved_ip=resolved_ip or "",
                    error=f"Scrape failed: {exc}",
                    success=False,
                )

    async def scrape_urls(
        self,
        urls: Sequence[str],
        timeout: float = 15.0,
    ) -> list[ScrapeResult]:
        """Concurrently scrape a batch of URLs with rate limiting and domain spacing.

        Args:
            urls: List of URLs to fetch.
            timeout: Timeout per URL.

        Returns:
            List of ScrapeResult items in the same order as input URLs.
        """
        if not urls:
            return []

        tasks = [self.scrape_url(u, timeout=timeout) for u in urls]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        return list(results)

    async def close(self) -> None:
        """Close underlying HTTP client and release connection pool."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
