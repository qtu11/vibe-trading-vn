"""Reader-API fallback for pages whose body is rendered client-side.

A direct fetch of a JavaScript single-page application (Google News, most
newsroom dashboards) returns HTTP 200 with a script-only shell: no ``<p>``, no
``<article>``, nothing a reader can use. The scraper then reports a
successful fetch with zero usable text, which silently empties the whole
research pipeline.

This module re-fetches empty or short hydration shells through a reader
service. The common server-rendered page still costs one request.

The target URL is sent to the third-party reader service, so the same rules as
``src.tools.web_reader_tool`` apply: never pass credentials, tokens, or
private addresses. Hostnames are screened before the request is made.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import httpx

from .ssrf_guard import SSRFGuard, SSRFSafeTransport

logger = logging.getLogger(__name__)

#: Prefix of the reader service. The full target URL is appended to it.
_READER_PREFIX = "https://r.jina.ai/"
_READER_TIMEOUT = 15.0
_MAX_READER_BYTES = 2 * 1024 * 1024

#: Header lines the reader service prepends to the payload.
_HEADER_PREFIXES = (
    "Title:",
    "URL Source:",
    "Final URL:",
    "Published Time:",
    "Warning:",
    "Markdown Content:",
)


def _strip_reader_header(text: str) -> tuple[str, str]:
    """Split a reader response into (title, body).

    The reader prefixes the payload with ``Title:`` / ``URL Source:`` /
    ``Markdown Content:`` lines. The body starts at the first line that is
    not one of those headers.
    """
    title = ""
    body_lines: list[str] = []
    in_header = True
    for line in text.split("\n"):
        if in_header:
            stripped = line.strip()
            if not stripped:
                body_lines.append(line)
                continue
            if stripped.startswith("Title:"):
                title = stripped[6:].strip()
                continue
            if stripped.startswith(_HEADER_PREFIXES):
                continue
            # First non-header content line: the body starts here.
            in_header = False
        body_lines.append(line)
    return title, "\n".join(body_lines).strip()


async def fetch_rendered_markdown(
    url: str,
    *,
    timeout: float = _READER_TIMEOUT,
    client: Optional[httpx.AsyncClient] = None,
) -> Optional[str]:
    """Fetch a client-rendered page as Markdown through a reader service.

    Args:
        url: Target URL. Screened for a safe public hostname first.
        timeout: Request timeout in seconds.
        client: Optional existing HTTP client to reuse. When provided, the
            client is NOT closed by this function.

    Returns:
        The rendered Markdown body, or ``None`` when the reader service is
        unavailable, times out, or returns nothing usable.
    """
    body, reason = await _fetch_rendered_markdown_detailed(url, timeout=timeout, client=client)
    return body if body and not reason else None


async def fetch_rendered_markdown_batch(
    urls: list[str],
    *,
    timeout: float = _READER_TIMEOUT,
    concurrency: int = 4,
) -> dict[str, str]:
    """Fetch several client-rendered pages concurrently.

    Returns:
        Mapping of URL to rendered Markdown, containing only the URLs that
        produced usable text.
    """
    results = await fetch_rendered_markdown_batch_detailed(
        urls, timeout=timeout, concurrency=concurrency
    )
    return {url: body for url, (body, reason) in results.items() if body and not reason}


async def fetch_rendered_markdown_batch_detailed(
    urls: list[str],
    *,
    timeout: float = _READER_TIMEOUT,
    concurrency: int = 4,
) -> dict[str, tuple[str, str]]:
    """Fetch several client-rendered pages concurrently, with reasons.

    Returns:
        Mapping of URL to ``(body, reason)``. ``body`` is empty when the
        fallback failed; ``reason`` then says why ("http_403", "timeout",
        "unsafe_host", "empty_body", ...).
    """
    if not urls:
        return {}
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def one(url: str) -> tuple[str, tuple[str, str]]:
        async with semaphore:
            body, reason = await _fetch_rendered_markdown_detailed(url, timeout=timeout)
            return url, (body, reason)

    results = await asyncio.gather(*(one(u) for u in urls), return_exceptions=True)
    out: dict[str, tuple[str, str]] = {}
    for item in results:
        if isinstance(item, Exception):
            continue
        url, payload = item
        out[url] = payload
    return out


async def _fetch_rendered_markdown_detailed(
    url: str, *, timeout: float = _READER_TIMEOUT, client: Optional[httpx.AsyncClient] = None,
) -> tuple[str, str]:
    """Fetch one rendered page, returning ``(body, reason)``.

    ``reason`` is empty on success and names the failure otherwise.
    """
    import urllib.parse

    try:
        if len(url) > 4096 or any(ord(char) < 32 or ord(char) == 127 for char in url) or "\\" in url:
            return "", "unsafe_url"
        parsed = urllib.parse.urlsplit(url)
        parsed.port
    except ValueError:
        return "", "malformed_url"
    if parsed.scheme.lower() not in {"http", "https"}:
        return "", "unsupported_scheme"
    if parsed.username or parsed.password:
        return "", "unsafe_url"
    hostname = parsed.hostname or ""
    if not hostname or hostname.rstrip(".").lower().endswith((".local", ".localhost")):
        return "", "unsafe_host"
    safe, _, _ = await asyncio.to_thread(SSRFGuard.validate_url, url)
    if not safe:
        return "", "unsafe_host"

    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(
            transport=SSRFSafeTransport(), follow_redirects=True, max_redirects=5,
            timeout=httpx.Timeout(timeout, connect=min(timeout, 8.0)),
        )
    try:
        async with asyncio.timeout(timeout):
            async with client.stream("GET", f"{_READER_PREFIX}{url}", headers={"Accept": "text/markdown"}) as resp:
                if resp.status_code != 200:
                    return "", f"http_{resp.status_code}"
                content_type = resp.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                if content_type not in {"text/plain", "text/markdown", "text/x-markdown"}:
                    return "", "unsupported_content_type"
                raw = bytearray()
                reason = ""
                async for chunk in resp.aiter_bytes():
                    if len(raw) + len(chunk) > _MAX_READER_BYTES:
                        raw.extend(chunk[:max(0, _MAX_READER_BYTES - len(raw))])
                        reason = "response_size_limit_exceeded"
                        break
                    raw.extend(chunk)
        _, body = _strip_reader_header(bytes(raw).decode("utf-8", errors="replace"))
        if not body.strip():
            return "", reason or "empty_body"
        return body, reason
    except (httpx.TimeoutException, TimeoutError):
        return "", "timeout"
    except Exception as exc:  # noqa: BLE001 - fallback must never break the pipeline
        logger.warning("Reader fallback failed: %s", type(exc).__name__)
        return "", type(exc).__name__
    finally:
        if owns_client:
            await client.aclose()


__all__ = [
    "fetch_rendered_markdown",
    "fetch_rendered_markdown_batch",
    "fetch_rendered_markdown_batch_detailed",
]
