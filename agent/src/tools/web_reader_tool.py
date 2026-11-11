"""Read public HTML/PDF sources with immutable snapshots and bounded paging."""

from __future__ import annotations

from collections import OrderedDict
import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import re
import ipaddress
import json
import logging
import threading
import time
from urllib.parse import urlsplit

import requests

from src.agent.progress import emit_progress
from src.agent.tool_context import current_grounding
from src.tools.source_documents import document_result, persist_document
from src.tools.scraper.url_resolver import is_unreadable_wrapper, resolve_url_sync
from src.agent.tools import BaseTool

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


def _read_failure(code: str, error: str, url: str, *, status_code: int | None = None,
                  remedy: str | None = None) -> str:
    """Failure payload with a next step, not only a status line.

    The VIC run retried the same blocked URLs at iterations 12, 22 and 63-82
    because the error said "origin fallback is disabled" and nothing else.
    A reader failure is a source-selection problem: name the alternatives so
    the model stops spending rounds on one unreachable page.
    """
    payload: dict[str, object] = {
        "status": "error",
        "error_code": code,
        "error": error,
        "url": url,
        "remedy": remedy or (
            "Không thử lại nguyên URL này. Dùng nguồn thay thế đã công bố: trang quan hệ "
            "nhà đầu tư của tổ chức phát hành, hồ sơ công bố trên Sở giao dịch (HOSE/HNX), "
            "hoặc tệp người dùng đã tải lên qua read_document. Ghi rõ nguồn thay thế và "
            "ngày truy cập; nếu không có nguồn thay thế, ghi rõ dữ liệu chưa thu thập được."
        ),
    }
    if status_code is not None:
        payload["status_code"] = status_code
    return json.dumps(payload, ensure_ascii=False)


def _fetch_origin(url: str) -> dict:
    """Use the existing transport's DNS pinning on every origin redirect."""
    from src.tools.scraper import AsyncScrapingEngine

    async def fetch():
        engine = AsyncScrapingEngine()
        try:
            result = await engine.scrape_url(url, timeout=15.0)
            return {"data": result.content_bytes, "content_type": result.content_type,
                    "text": result.html_content,
                    "url": result.final_url or url, "status_code": result.status_code,
                    "error": result.error, "truncated": result.truncated,
                    "security_blocked": bool(result.error and result.error.startswith("SSRF violation:"))}
        finally:
            await engine.close()

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(fetch())
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, fetch()).result()


def _read_rendered(url: str, no_cache: bool) -> tuple[str, str, bool]:
    headers = {"Accept": "text/markdown"}
    if no_cache:
        headers["x-no-cache"] = "true"
    response = None
    try:
        started = time.monotonic()
        response = requests.get(f"{_JINA_PREFIX}{url}", headers=headers, timeout=_TIMEOUT,
                                allow_redirects=False, stream=True)
        if response.status_code != 200:
            raise ValueError(f"remote reader returned HTTP {response.status_code}")
        text = _response_text(response, started)
        if not text.strip():
            raise ValueError("remote reader returned empty content")
        from src.tools.scraper.reader_fallback import _strip_reader_header
        _, body = _strip_reader_header(text)
        if re.fullmatch(r"\s*(?:loading[.\s…]*|(?:please\s+)?enable javascript.*|access denied[.\s]*|verify you are human[.\s]*)", body, flags=re.IGNORECASE):
            raise ValueError("remote reader returned an unreadable shell")
        title = next((line[6:].strip()[:350] for line in text.splitlines() if line.startswith("Title:")), "")
        return text, title, _CACHED_MARKER in text
    finally:
        if response is not None:
            response.close()


def _cache_key(url: str, run_dir: str | Path | None = None) -> str:
    ledger = current_grounding.get()
    return f"{getattr(ledger, 'run_dir', None) or run_dir or ''}|{url}"


def read_url(url: str, no_cache: bool = False, offset: int = 0,
             max_chars: int = _MAX_LENGTH, run_dir: str | Path | None = None) -> str:
    """Read one fetched document; follow next_offset until delivery is complete.

    Static HTML and PDFs use the pinned origin transport. Dynamic HTML may
    send the full public URL to the third-party Jina reader. Extraction refers
    to the fetched document body, not every hidden tab/link on a website.
    """
    if not isinstance(url, str):
        return _read_failure("unsafe_url", "target URL is not allowed", "")
    target_url = url.strip()
    allowed, error = _url_allowed(target_url)
    if not allowed:
        return _read_failure("unsafe_url", error, target_url)
    if type(offset) is not int or offset < 0 or type(max_chars) is not int or not 1 <= max_chars <= 50000:
        return _read_failure("invalid_chunk", "offset must be nonnegative and max_chars must be between 1 and 50000", target_url)
    key = _cache_key(target_url, run_dir)
    original = None
    try:
        cached = _cache_get(key) if not no_cache else None
        if cached is not None:
            payload = json.loads(cached)
        else:
            # A Google News link is a redirect wrapper: the publisher URL only
            # exists behind the batchexecute handshake. Resolve it on a cache
            # miss only -- paging a long article must not redo the handshake
            # for every chunk -- but keep the requested URL as the citation key
            # so the report can cite the link it saw in the news feed.
            fetch_url = target_url
            resolved_url = ""
            if is_unreadable_wrapper(target_url):
                resolved_url = resolve_url_sync(target_url)
                if resolved_url == target_url:
                    return _read_failure(
                        "wrapper_unresolved",
                        "Google News wrapper could not be resolved to its publisher URL",
                        target_url,
                        remedy=(
                            "Link Google News này không phân giải được. Dùng link gốc của bài "
                            "(trường 'publisher_url' nếu feed có) hoặc tìm lại tiêu đề trên trang "
                            "nhà phát hành; không thử lại nguyên URL wrapper."
                        ),
                    )
                # The publisher URL comes from a remote handshake response, so
                # apply the same SSRF/scheme check as a user-supplied URL before
                # either the pinned origin fetch or the third-party reader sees it.
                allowed, error = _url_allowed(resolved_url)
                if not allowed:
                    return _read_failure("unsafe_url", error, target_url)
                fetch_url = resolved_url
            emit_progress("fetching", message=f"GET {fetch_url[:60]}")
            fetched = _fetch_origin(fetch_url)
            if fetched.get("security_blocked"):
                return _read_failure("unsafe_origin", "Origin connection was refused by the SSRF guard", target_url)
            data = fetched.get("data", b"")
            content_type = str(fetched.get("content_type", "")).split(";", 1)[0].lower()
            if content_type == "application/pdf" or data.lstrip().startswith(b"%PDF-"):
                from src.tools.doc_reader_tool import read_pdf_bytes
                payload = read_pdf_bytes(data, source=fetched.get("url", fetch_url), run_dir=run_dir, deliver=False, requested_url=target_url)
                payload.pop("text", None)
                payload.update(url=target_url, title=payload.get("file", "PDF"))
                if resolved_url:
                    payload["resolved_url"] = resolved_url
            else:
                original = None
                text, title, cached_remote = "", "", False
                complete = False
                method = "direct_html"
                if fetched.get("status_code") == 200 and not fetched.get("truncated"):
                    if content_type in {"text/html", "application/xhtml+xml"}:
                        from src.tools.extractor import clean_html
                        html = fetched.get("text") or data.decode("utf-8", errors="replace")
                        cleaned = clean_html(html, url=fetch_url)
                        text, title = cleaned.clean_markdown, cleaned.title
                        dynamic = len(text.strip()) < 1200 and bool(re.search(
                            r"__NEXT_DATA__|__next_f|id\s*=\s*['\"](?:root|app|__next)['\"]|enable javascript|loading\.\.\.", html, re.IGNORECASE))
                        complete = bool(text.strip()) and not dynamic
                    elif content_type in {"text/plain", "text/markdown", "text/x-markdown"}:
                        text = data.decode("utf-8", errors="replace")
                        complete = bool(text.strip())
                original = persist_document(source=fetched.get("url", fetch_url), content_type=content_type,
                                            content_bytes=data, full_text=text, run_dir=run_dir, requested_url=target_url,
                                            coverage={"extraction_complete": complete, "method": method,
                                                      "scope": "fetched_body_main_content"})
                if not complete:
                    # Do not send a binary document to a rendered HTML reader.
                    if data and content_type not in {"text/html", "application/xhtml+xml", "text/plain", "text/markdown", "text/x-markdown"}:
                        return json.dumps({"status": "error", "error": "Unsupported origin content type",
                                           "url": target_url, "source_document": original}, ensure_ascii=False)
                    text, title, cached_remote = _read_rendered(fetch_url, no_cache)
                    method = "rendered_reader"
                document = original if complete else persist_document(
                    source=fetched.get("url", fetch_url), content_type="text/markdown", content_bytes=text.encode("utf-8"),
                    full_text=text, run_dir=run_dir, requested_url=target_url,
                    coverage={"extraction_complete": True,
                    "method": method, "scope": "fetched_rendered_body"})
                payload = {"status": "ok", "url": target_url, "title": title,
                           "length": len(text), "source_document": document}
                if resolved_url:
                    payload["resolved_url"] = resolved_url
                if not complete:
                    payload["original_snapshot"] = original
                if cached_remote:
                    payload["cached"] = True
            if payload.get("status") == "ok":
                _cache_put(key, json.dumps(payload, ensure_ascii=False))
        result = document_result(payload, offset=offset, max_chars=max_chars, text_field="content")
        result["length"] = result["source_document"]["coverage"]["total_chars"]
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        logger.warning("read_url request failed (%s)", type(exc).__name__)
        error = str(exc) if isinstance(exc, ValueError) and str(exc).startswith("remote reader returned HTTP ") else f"Source could not be read ({type(exc).__name__})"
        failure = json.loads(_read_failure("source_unreachable", error, target_url))
        if original is not None:
            failure["source_document"] = original
        return json.dumps(failure, ensure_ascii=False)


class WebReaderTool(BaseTool):
    """Web reader tool."""

    name = "read_url"
    description = "Read public HTML or PDF sources. Preserves raw/full extracted text. Follow next_offset through all chunks; a saved source is not proof all text was read. Google News redirect wrappers are resolved to the publisher automatically. Dynamic pages may use third-party Jina."
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL of the web page to read"},
            "offset": {"type": "integer", "minimum": 0, "default": 0, "description": "Character offset supplied by next_offset; continue until null."},
            "max_chars": {"type": "integer", "minimum": 1, "maximum": 50000, "default": 8000, "description": "Upper bound per chunk; actual JSON delivery budget may return fewer characters."},
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
        return read_url(kwargs["url"], no_cache=bool(kwargs.get("no_cache", False)),
                        offset=kwargs.get("offset", 0), max_chars=kwargs.get("max_chars", _MAX_LENGTH), run_dir=kwargs.get("run_dir"))
