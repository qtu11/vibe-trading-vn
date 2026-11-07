"""Web reader tool: fetch a URL as Markdown text via the Jina Reader API."""

from __future__ import annotations

from collections import OrderedDict
import ipaddress
import json
import logging
import threading
import time
from urllib.parse import urlsplit

import requests

from src.agent.progress import emit_progress
from src.agent.tools import BaseTool
from src.security.scanner import with_security_warnings

logger = logging.getLogger(__name__)

_JINA_PREFIX = "https://r.jina.ai/"
_TIMEOUT = 8
_MAX_LENGTH = 8000
_CACHED_MARKER = "Warning: This is a cached snapshot"
_CACHE_TTL = 300.0
_CACHE_MAX_ENTRIES = 128
_CACHE_MAX_BYTES = 2 * 1024 * 1024
_MAX_RESPONSE_BYTES = 256 * 1024
_RESPONSE_DEADLINE = 10.0

# Process-local optimization only: this is neither durable evidence nor proof
# that a page is current. Entries expire from their fetch time, not access time.
_URL_MEMORY_CACHE: OrderedDict[str, tuple[float, str, int]] = OrderedDict()
_CACHE_LOCK = threading.RLock()


def _cache_get(url: str) -> str | None:
    with _CACHE_LOCK:
        now = time.monotonic()
        _cache_expire(now)
        entry = _URL_MEMORY_CACHE.get(url)
        if entry is None:
            return None
        _URL_MEMORY_CACHE.move_to_end(url)
        result = json.loads(entry[1])
        result["memory_cached"] = True
        result["cache_age_seconds"] = round(max(0.0, now - entry[0]), 3)
        return json.dumps(result, ensure_ascii=False)


def _cache_expire(now: float) -> None:
    for key, (created, _, _) in list(_URL_MEMORY_CACHE.items()):
        if now - created >= _CACHE_TTL:
            del _URL_MEMORY_CACHE[key]


def _cache_put(url: str, result: str) -> None:
    size = len(url.encode("utf-8")) + len(result.encode("utf-8"))
    with _CACHE_LOCK:
        _cache_expire(time.monotonic())
        _URL_MEMORY_CACHE.pop(url, None)
        if size > _CACHE_MAX_BYTES:
            return
        _URL_MEMORY_CACHE[url] = (time.monotonic(), result, size)
        while (len(_URL_MEMORY_CACHE) > _CACHE_MAX_ENTRIES or
               sum(entry[2] for entry in _URL_MEMORY_CACHE.values()) > _CACHE_MAX_BYTES):
            _URL_MEMORY_CACHE.popitem(last=False)


def _direct_fetch(target_url: str) -> str | None:
    """Disabled: no local DNS/origin connection after a proxy failure.

    Hostname screening followed by requests.get would still allow DNS rebinding
    and redirects into private services. The reader deliberately fails closed
    until a separately pinned, redirect-safe origin transport is implemented.
    """
    return None


def _response_text(response, started: float) -> str:
    """Bound decoded response bytes, type and streaming processing time."""
    content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
    if content_type not in {"text/plain", "text/markdown", "text/x-markdown"}:
        raise ValueError("remote reader returned an unsupported content type")
    length = response.headers.get("Content-Length")
    if length is not None:
        try:
            if int(length) < 0 or int(length) > _MAX_RESPONSE_BYTES:
                raise ValueError
        except ValueError:
            raise ValueError("remote reader response exceeds the size limit") from None
    body = bytearray()
    # A single-byte iteration makes the processing deadline observable even
    # for a trickling response. Socket operations retain requests' timeout;
    # this deadline is not a claim of hard cancellation of OS DNS resolution.
    for chunk in response.iter_content(chunk_size=1):
        if time.monotonic() - started > _RESPONSE_DEADLINE:
            raise ValueError("remote reader response exceeded the processing deadline")
        if chunk:
            body.extend(chunk)
            if len(body) > _MAX_RESPONSE_BYTES:
                raise ValueError("remote reader response exceeds the size limit")
    return body.decode("utf-8", errors="replace")


def _url_allowed(url: str) -> tuple[bool, str]:
    """Return whether a URL is safe to forward to the remote reader service."""
    try:
        if len(url) > 4096 or any(ord(char) < 32 or ord(char) == 127 for char in url) or "\\" in url:
            return False, "target URL is not allowed"
        parsed = urlsplit(url.strip())
        parsed.port  # Reject malformed and out-of-range ports before networking.
    except ValueError:
        return False, "target URL is not allowed"

    if parsed.scheme.lower() not in {"http", "https"}:
        return False, "target URL is not allowed"
    if not parsed.hostname:
        return False, "target URL is not allowed"
    if parsed.username or parsed.password:
        return False, "target URL is not allowed"

    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        return False, "target URL is not allowed"

    ip_host = host.split("%", 1)[0]
    try:
        ip = ipaddress.ip_address(ip_host)
    except ValueError:
        return True, ""

    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or not ip.is_global
    ):
        return False, "target URL is not allowed"
    return True, ""


def read_url(url: str, no_cache: bool = False) -> str:
    """Fetch web page content via the Jina Reader API.

    The full URL (including query string) is sent to the third-party Jina
    Reader service (r.jina.ai); never pass credentials/tokens or private
    addresses. Results may be a cached snapshot.

    Args:
        url: Target URL.
        no_cache: Bypass the local cache and ask the remote reader for a fresh
            fetch. A successful response replaces the local snapshot.

    Returns:
        JSON result with title, content, url; ``cached: true`` is added
        when the remote reader reports a cached snapshot. Local hits add
        ``memory_cached`` and an age; neither flag verifies source accuracy.
        Origin fallback is disabled; failures make no local origin request.
    """
    if not isinstance(url, str):
        return json.dumps({"status": "error", "error": "target URL is not allowed"})
    target_url = url.strip()
    allowed, error = _url_allowed(target_url)
    if not allowed:
        return json.dumps({"status": "error", "error": error}, ensure_ascii=False)

    # Check in-memory URL cache first to avoid repeating network requests
    if not no_cache:
        cached_result = _cache_get(target_url)
        if cached_result is not None:
            return cached_result

    try:
        headers = {"Accept": "text/markdown"}
        if no_cache:
            headers["x-no-cache"] = "true"
        emit_progress(
            "fetching",
            message=f"GET {target_url[:60]}{'…' if len(target_url) > 60 else ''}",
        )
        resp = None
        try:
            started = time.monotonic()
            resp = requests.get(
                f"{_JINA_PREFIX}{target_url}",
                headers=headers,
                timeout=_TIMEOUT,
                allow_redirects=False,
                stream=True,
            )
            if resp.status_code == 200:
                original_text = _response_text(resp, started)
                if not original_text.strip():
                    raise ValueError("remote reader returned empty content")
                emit_progress("parsing", message="extracting markdown")
                text = original_text
                title = ""
                for line in text.split("\n"):
                    if line.startswith("Title:"):
                        title = line[6:].strip()[:350]
                        break

                if len(text) > _MAX_LENGTH:
                    text = text[:_MAX_LENGTH] + f"\n\n... (truncated, total {len(original_text)} chars)"

                result = {
                    "status": "ok",
                    "title": title,
                    "url": target_url,
                    "content": text,
                    "length": len(original_text),
                }
                if _CACHED_MARKER in original_text:
                    result["cached"] = True
                result_str = json.dumps(with_security_warnings(result, fields=("content",)), ensure_ascii=False)
                _cache_put(target_url, result_str)
                return result_str
            return json.dumps({"status": "error", "error": f"remote reader returned HTTP {resp.status_code}; origin fallback is disabled"}, ensure_ascii=False)
        finally:
            if resp is not None:
                resp.close()

    except Exception as exc:
        logger.warning("read_url request failed (%s)", type(exc).__name__)
        return json.dumps(
            {"status": "error", "error": "remote reader request failed; origin fallback is disabled"},
            ensure_ascii=False,
        )


class WebReaderTool(BaseTool):
    """Web reader tool."""

    name = "read_url"
    description = "Fetch web page content: provide a URL and receive the page as Markdown text. Useful for reading docs, articles, API references, etc."
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL of the web page to read"},
            "no_cache": {
                "type": "boolean",
                "description": (
                    "Request a fresh (uncached) fetch. Use only when the prior "
                    "read explicitly reported cached=true or the task genuinely "
                    "requires newer data. Never set no_cache merely because a "
                    "previous result was compacted or replayed."
                ),
                "default": False,
            },
        },
        "required": ["url"],
    }
    repeatable = True
    # Normal repeated reads remain allowed while the prior payload is visible.
    # If compaction removes an exact successful read, AgentLoop may restore the
    # run-scoped result instead of hitting Jina/the origin again. ``no_cache``
    # remains the explicit freshness escape hatch and bypasses that replay.
    replay_after_compaction = True

    def execute(self, **kwargs) -> str:
        """Fetch web page."""
        return read_url(kwargs["url"], no_cache=bool(kwargs.get("no_cache", False)))
