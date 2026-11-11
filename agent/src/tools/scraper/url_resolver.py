"""Resolve redirect-style URLs to their final destination.

Some search backends return a wrapper URL instead of the publisher's URL.
Google News is the common case: its RSS feed links point at
``news.google.com/rss/articles/CBMi...``, an opaque path that only redirects to
the real article after a JavaScript handshake. Feeding such a URL to a reader
service returns HTTP 403 (or a script-only shell), so the article is unreadable
even though the search found it.

Modern Google News wrappers no longer expose the publisher URL in the page
markup. They expose a signature/timestamp pair and expect the client to call
the ``batchexecute`` endpoint with the article id, timestamp and signature.
This module performs that handshake with plain HTTP and returns the publisher
URL. Resolution is best-effort: any failure returns the original URL, so the
caller can still report a blocked source instead of crashing the run.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextvars
import json
import logging
import re
from typing import Optional
from urllib.parse import quote, urlsplit

import httpx

logger = logging.getLogger(__name__)

#: Hosts whose links are wrappers around a publisher URL.
_WRAPPER_HOSTS = {"news.google.com"}

#: Google News article ids are opaque base64url blobs. Both the RSS path and
#: the web path use the same handshake.
_WRAPPER_PATHS = ("/rss/articles/", "/articles/")

_HANDSHAKE_URL = "https://news.google.com/_/DotsSplashUi/data/batchexecute"
_SIGNATURE_RE = re.compile(r'data-n-a-sg="([^"]+)"')
_TIMESTAMP_RE = re.compile(r'data-n-a-ts="(\d+)"')

_TIMEOUT = 10.0
_MAX_BODY_BYTES = 2 * 1024 * 1024
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
#: The batchexecute request body is a fixed Google contract; only the article
#: id, timestamp and signature vary.
_GARTURLREQ = (
    '["garturlreq",[["X","X",["X","X"],null,null,1,1,"US:en",null,1,'
    'null,null,null,null,null,0,1],"X","X",1,[1,1,1],1,1,null,0,0,null,0]'
)


def _article_id(url: str) -> str:
    """Return the opaque Google News article id, or ``""`` for a plain URL."""
    try:
        path = urlsplit(url).path
    except ValueError:
        return ""
    for prefix in _WRAPPER_PATHS:
        if path.startswith(prefix):
            return path[len(prefix):].strip("/")
    return ""


def _is_wrapper(url: str) -> bool:
    """Return whether the URL points at a Google News redirect wrapper."""
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
    except ValueError:
        return False
    if host not in _WRAPPER_HOSTS:
        return False
    return bool(_article_id(url))


def _is_google_host(host: str) -> bool:
    """Whether a resolved host is a Google property rather than a publisher."""
    labels = host.lower().rstrip(".").split(".")
    if "google" in labels:
        return True
    return any(
        ".".join(labels[index:]) in {
            "googleusercontent.com",
            "gstatic.com",
            "googleapis.com",
            "youtube.com",
            "ytimg.com",
        }
        for index in range(len(labels))
    )


def _publisher_url(candidate: object) -> str:
    """Accept only an absolute HTTP(S) URL on a non-Google host."""
    if not isinstance(candidate, str):
        return ""
    value = candidate.strip()
    if (
        not value
        or len(value) > 4096
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
        or "\\" in value
    ):
        return ""
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower()
    except ValueError:
        return ""
    if parsed.scheme.lower() not in {"http", "https"} or not host:
        return ""
    if parsed.username or parsed.password:
        return ""
    if _is_google_host(host):
        return ""
    return value


def _handshake_body(article_id: str, timestamp: str, signature: str) -> str:
    """Build the ``f.req`` form body for one article."""
    inner = f'{_GARTURLREQ},"{article_id}",{timestamp},"{signature}"]'
    return "f.req=" + quote(json.dumps([[["Fbv4je", inner]]]))


def _publisher_from_handshake(text: str) -> str:
    """Extract the publisher URL from a ``batchexecute`` response.

    The response starts with ``)]}'`` and then contains JSON frames. The
    ``wrb.fr`` frame carries a JSON string whose second element is the URL.
    """
    body = text
    if body.startswith(")]}'"):
        body = body[4:]
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("["):
            continue
        try:
            frames = json.loads(line)
        except (TypeError, ValueError):
            continue
        for frame in frames if isinstance(frames, list) else []:
            if not isinstance(frame, list) or len(frame) < 3:
                continue
            if frame[0] != "wrb.fr" or frame[1] != "Fbv4je":
                continue
            payload = frame[2]
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except (TypeError, ValueError):
                    continue
            if isinstance(payload, list) and len(payload) >= 2 and payload[0] == "garturlres":
                url = _publisher_url(payload[1])
                if url:
                    return url
    return ""


async def resolve_url(
    url: str,
    *,
    client: Optional[httpx.AsyncClient] = None,
    timeout: float = _TIMEOUT,
) -> str:
    """Resolve a wrapper URL to the publisher URL.

    Args:
        url: Candidate URL. Non-wrapper URLs are returned unchanged.
        client: Optional async HTTP client to reuse. Not closed by this function.
        timeout: Request timeout in seconds.

    Returns:
        The resolved publisher URL, or the original URL when resolution is
        not possible.
    """
    if not _is_wrapper(url):
        return url

    article_id = _article_id(url)
    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(timeout, connect=6.0),
            headers={"User-Agent": _USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
        )
    try:
        resp = await client.get(url)
        # Some wrapper variants answer with a plain 3xx to the publisher
        # instead of the JavaScript shell. ``follow_redirects`` already followed
        # it, so the final URL is the answer and no handshake is needed.
        direct = _publisher_url(str(getattr(resp, "url", "")))
        if direct:
            return direct
        if resp.status_code != 200:
            logger.warning("Google News wrapper returned HTTP %s", resp.status_code)
            return url
        body = resp.text[:_MAX_BODY_BYTES]
        signature = _SIGNATURE_RE.search(body)
        timestamp = _TIMESTAMP_RE.search(body)
        if signature is None or timestamp is None:
            logger.warning("Google News wrapper has no decoding parameters")
            return url
        post = await client.post(
            _HANDSHAKE_URL,
            headers={"content-type": "application/x-www-form-urlencoded;charset=UTF-8"},
            content=_handshake_body(article_id, timestamp.group(1), signature.group(1)),
        )
        if post.status_code != 200:
            logger.warning("Google News handshake returned HTTP %s", post.status_code)
            return url
        resolved = _publisher_from_handshake(post.text)
        return resolved or url
    except Exception as exc:  # noqa: BLE001 - resolution must never break the pipeline
        logger.warning("Could not resolve wrapper URL %s: %s", url[:80], exc)
        return url
    finally:
        if owns_client and client is not None:
            await client.aclose()


def resolve_url_sync(url: str, *, timeout: float = _TIMEOUT) -> str:
    """Synchronous :func:`resolve_url` for the synchronous reader tool."""
    if not _is_wrapper(url):
        return url

    def run() -> str:
        return asyncio.run(resolve_url(url, timeout=timeout))

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return run()
    # A tool call can run inside an event loop; a nested asyncio.run would
    # fail, so use a worker thread with its own loop.
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(contextvars.copy_context().run, run).result()


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
    """Return whether the URL is a wrapper a plain fetch cannot read directly.

    Google News hands out ``news.google.com/rss/articles/<opaque>`` links. The
    publisher URL behind them is only obtainable through the ``batchexecute``
    handshake, so a plain HTTP fetch returns a script-only shell and a reader
    service refuses the request. ``read_url`` resolves such a link first; other
    callers use this predicate to flag it instead of spending a request on it.
    """
    return _is_wrapper(url)


__all__ = ["resolve_url", "resolve_url_sync", "resolve_urls", "is_unreadable_wrapper"]
