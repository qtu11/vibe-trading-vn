"""Resolve redirect-style URLs to their final destination.

Some search backends return a wrapper URL instead of the publisher's URL.
Google News is the common case: its RSS feed links point at
``news.google.com/rss/articles/CBMi...``, an opaque path that redirects to the
real article only after a JavaScript handshake.

Feeding such a URL to a reader service returns HTTP 403, so the article is
unreadable even though the search found it. Resolving the wrapper first turns
the link back into a normal publisher URL that any fetcher can read.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

#: Hosts whose links are wrappers around a publisher URL.
_WRAPPER_HOSTS = {"news.google.com"}

#: Google News article ids are base64url blobs. A real publisher URL is
#: recognised by its scheme.
_URL_IN_TEXT_RE = re.compile(r"https?://[^\s\"'<>\\]+")

_TIMEOUT = 10.0
_MAX_BODY_BYTES = 512 * 1024


def _is_wrapper(url: str) -> bool:
    """Return whether the URL points at a redirect wrapper."""
    try:
        import urllib.parse

        parsed = urllib.parse.urlsplit(url)
        host = (parsed.hostname or "").lower()
    except ValueError:
        return False
    if host not in _WRAPPER_HOSTS:
        return False
    # Only the article path is a wrapper. The host also serves plain pages
    # (``news.google.com/``) that a fetch can read.
    return parsed.path.startswith("/rss/articles/")


async def resolve_url(
    url: str,
    *,
    client: Optional[httpx.AsyncClient] = None,
    timeout: float = _TIMEOUT,
) -> str:
    """Resolve a wrapper URL to the publisher URL.

    Args:
        url: Candidate URL. Non-wrapper URLs are returned unchanged.
        client: Optional HTTP client to reuse. Not closed by this function.
        timeout: Request timeout in seconds.

    Returns:
        The resolved publisher URL, or the original URL when resolution is
        not possible.
    """
    if not _is_wrapper(url):
        return url

    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(timeout, connect=6.0),
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                )
            },
        )
    try:
        resp = await client.get(url)
        body = resp.content[:_MAX_BODY_BYTES].decode("utf-8", errors="replace")
        # The handshake page embeds the publisher URL in its markup. Pick the
        # first http(s) URL that is not a Google property.
        for candidate in _URL_IN_TEXT_RE.findall(body):
            if "google." in candidate.lower() or "gstatic." in candidate.lower():
                continue
            if "news.google" in candidate.lower():
                continue
            return candidate.rstrip('"\'.,)')
        # No embedded URL: fall back to the redirect target if it left Google.
        final = str(resp.url)
        if "news.google" not in final.lower():
            return final
        return url
    except Exception as exc:  # noqa: BLE001 - resolution must never break the pipeline
        logger.warning("Could not resolve wrapper URL %s: %s", url[:80], exc)
        return url
    finally:
        if owns_client and client is not None:
            await client.aclose()


async def resolve_urls(
    urls: list[str],
    *,
    concurrency: int = 5,
    timeout: float = _TIMEOUT,
) -> dict[str, str]:
    """Resolve several wrapper URLs concurrently.

    Returns:
        Mapping of original URL to resolved URL. URLs that are not wrappers
        map to themselves.
    """
    if not urls:
        return {}
    import asyncio

    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def one(url: str) -> tuple[str, str]:
        async with semaphore:
            return url, await resolve_url(url, timeout=timeout)

    results = await asyncio.gather(*(one(u) for u in urls), return_exceptions=True)
    out: dict[str, str] = {}
    for item in results:
        if isinstance(item, Exception):
            continue
        out[item[0]] = item[1]
    return out


def is_unreadable_wrapper(url: str) -> bool:
    """Return whether the URL is a wrapper no fetcher can read directly.

    Google News hands out ``news.google.com/rss/articles/<opaque>`` links.
    The publisher URL behind them is only obtainable through a browser
    handshake, so a plain HTTP fetch returns a script-only shell and a reader
    service refuses the request. Treating such a link as a candidate article
    spends a request and yields nothing, so callers skip it and prefer the
    readable links from the same result set.
    """
    return _is_wrapper(url)


__all__ = ["resolve_url", "resolve_urls", "is_unreadable_wrapper"]
