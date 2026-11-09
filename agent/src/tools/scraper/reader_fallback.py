"""Reader-API fallback for pages whose body is rendered client-side.

A direct fetch of a JavaScript single-page application (Google News, most
newsroom dashboards) returns HTTP 200 with a script-only shell: no ``<p>``, no
``<article>``, nothing a reader can use. The scraper then reports a
successful fetch with zero usable text, which silently empties the whole
research pipeline.

This module re-fetches such a page through a reader service that executes the
page and returns rendered text. It is only used when the direct fetch yields
no prose, so the common case (server-rendered HTML) still costs one request.

The target URL is sent to the third-party reader service, so the same rules as
``src.tools.web_reader_tool`` apply: never pass credentials, tokens, or
private addresses. Hostnames are screened before the request is made.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

#: Prefix of the reader service. The full target URL is appended to it.
_READER_PREFIX = "https://r.jina.ai/"
_READER_TIMEOUT = 15.0
_MAX_READER_BYTES = 2 * 1024 * 1024

#: Hostnames that are never forwarded to a third-party reader service.
_BLOCKED_HOSTNAMES = {"localhost", "metadata.google.internal"}


def _is_safe_public_host(hostname: str) -> bool:
    """Return whether a hostname may be forwarded to the reader service.

    Only literal IP addresses can be judged here without a DNS round-trip; the
    reader service performs the fetch on its own side, so a hostname that
    resolves to a private address is screened by the reader's own network
    policy, not by this check.
    """
    host = hostname.strip().lower().rstrip(".")
    if not host or host in _BLOCKED_HOSTNAMES or host.endswith(".local"):
        return False
    return True


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
    import urllib.parse

    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        return None
    if parsed.scheme.lower() not in {"http", "https"}:
        return None
    hostname = parsed.hostname or ""
    if not _is_safe_public_host(hostname):
        logger.warning("Reader fallback refused for unsafe host %r", hostname)
        return None

    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(timeout, connect=8.0))
    try:
        resp = await client.get(
            f"{_READER_PREFIX}{url}",
            headers={"Accept": "text/markdown"},
        )
        if resp.status_code != 200:
            logger.warning("Reader fallback returned HTTP %s for %s", resp.status_code, url)
            return None
        raw = resp.content[:_MAX_READER_BYTES].decode("utf-8", errors="replace")
        _, body = _strip_reader_header(raw)
        if not body.strip():
            return None
        return body
    except Exception as exc:  # noqa: BLE001 - fallback must never break the pipeline
        logger.warning("Reader fallback failed for %s: %s", url, exc)
        return None
    finally:
        if owns_client and client is not None:
            await client.aclose()


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
    return {url: body for url, (body, _reason) in results.items() if body}


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
    url: str, *, timeout: float = _READER_TIMEOUT
) -> tuple[str, str]:
    """Fetch one rendered page, returning ``(body, reason)``.

    ``reason`` is empty on success and names the failure otherwise.
    """
    import urllib.parse

    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        return "", "malformed_url"
    if parsed.scheme.lower() not in {"http", "https"}:
        return "", "unsupported_scheme"
    hostname = parsed.hostname or ""
    if not _is_safe_public_host(hostname):
        logger.warning("Reader fallback refused for unsafe host %r", hostname)
        return "", "unsafe_host"

    client = httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(timeout, connect=8.0))
    try:
        resp = await client.get(
            f"{_READER_PREFIX}{url}",
            headers={"Accept": "text/markdown"},
        )
        if resp.status_code != 200:
            logger.warning(
                "Reader fallback returned HTTP %s for %s", resp.status_code, url
            )
            return "", f"http_{resp.status_code}"
        raw = resp.content[:_MAX_READER_BYTES].decode("utf-8", errors="replace")
        _, body = _strip_reader_header(raw)
        if not body.strip():
            return "", "empty_body"
        return body, ""
    except httpx.TimeoutException:
        logger.warning("Reader fallback timed out for %s", url)
        return "", "timeout"
    except Exception as exc:  # noqa: BLE001 - fallback must never break the pipeline
        logger.warning("Reader fallback failed for %s: %s", url, exc)
        return "", type(exc).__name__
    finally:
        await client.aclose()


__all__ = [
    "fetch_rendered_markdown",
    "fetch_rendered_markdown_batch",
    "fetch_rendered_markdown_batch_detailed",
]
