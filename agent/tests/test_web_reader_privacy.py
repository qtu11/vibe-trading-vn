"""Regression tests for read_url third-party (Jina) hardening.

Network is mocked; no live r.jina.ai calls. HTTP errors retain only the
upstream status, never untrusted error bodies; a cached snapshot is surfaced
via `cached: true`; `no_cache=True` sends the x-no-cache header while
the default path is byte-identical (no extra header).
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

import src.tools.web_reader_tool as wr
from src.tools.web_reader_tool import read_url

URL = "https://example.com/page"


class _Resp:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text
        self.headers = {"Content-Type": "text/plain; charset=utf-8"}
        self.closed = False

    def iter_content(self, chunk_size):
        yield self.text.encode("utf-8")

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def clear_cache(monkeypatch):
    # These tests exercise only the rendered-reader boundary, after a safe empty origin response.
    monkeypatch.setattr(wr, "_fetch_origin", lambda url: {"data": b"", "content_type": "text/html", "url": url, "status_code": 200})
    with wr._CACHE_LOCK:
        wr._URL_MEMORY_CACHE.clear()
    yield
    with wr._CACHE_LOCK:
        wr._URL_MEMORY_CACHE.clear()


@pytest.fixture
def captured(monkeypatch):
    box = {}

    def fake_get(url, headers=None, timeout=None, **kwargs):
        box["url"] = url
        box["headers"] = headers or {}
        r = box["resp"]
        if isinstance(r, BaseException):
            raise r
        return r

    monkeypatch.setattr(wr.requests, "get", fake_get)
    return box


def test_http_error_surfaces_status_without_untrusted_body(captured):
    captured["resp"] = _Resp(451, "ParamValidationError: bad input")
    out = json.loads(read_url(URL))
    assert out["status"] == "error"
    assert "451" in out["error"]
    assert "ParamValidationError: bad input" not in out["error"]
    assert captured["resp"].closed


def test_exception_error_does_not_expose_internal_exception_or_address(captured):
    captured["resp"] = RuntimeError("boom: connect failed (10.0.0.1)")
    out = json.loads(read_url(URL))
    assert out["status"] == "error"
    assert "boom: connect failed" not in out["error"]
    assert "10.0.0.1" not in out["error"]


def test_cached_snapshot_is_flagged(captured):
    captured["resp"] = _Resp(200, "Title: X\n\nWarning: This is a cached snapshot\n\nbody")
    out = json.loads(read_url(URL))
    assert out["status"] == "ok"
    assert out.get("cached") is True


def test_fresh_response_has_no_cached_key(captured):
    captured["resp"] = _Resp(200, "Title: X\n\nlive body content")
    out = json.loads(read_url(URL))
    assert out["status"] == "ok"
    assert "cached" not in out  # additive: absent on the normal path


def test_no_cache_header_opt_in_only(captured):
    captured["resp"] = _Resp(200, "Title: X\n\nbody")
    read_url(URL)  # default
    assert "x-no-cache" not in {k.lower() for k in captured["headers"]}
    read_url(URL, no_cache=True)
    assert captured["headers"].get("x-no-cache") == "true"


def test_memory_cache_hit_is_explicit_and_does_not_call_network(captured, monkeypatch):
    captured["resp"] = _Resp(200, "Title: cached\n\nbody")
    first = json.loads(read_url(URL))
    assert "memory_cached" not in first

    def fail_get(*args, **kwargs):
        raise AssertionError("A fresh cache hit must not fetch")

    monkeypatch.setattr(wr.requests, "get", fail_get)
    second = json.loads(read_url(URL))
    assert second["memory_cached"] is True
    assert second["cache_age_seconds"] >= 0 and second["content"] == first["content"]


def test_no_cache_bypasses_local_snapshot_and_refreshes_only_on_success(captured):
    captured["resp"] = _Resp(200, "Title: first\n\nold")
    read_url(URL)
    captured["resp"] = _Resp(200, "Title: second\n\nnew")
    fresh = json.loads(read_url(URL, no_cache=True))
    assert fresh["title"] == "second" and "memory_cached" not in fresh
    assert captured["headers"]["x-no-cache"] == "true"
    assert json.loads(read_url(URL))["title"] == "second"


def test_ttl_expires_from_fetch_not_last_access(captured, monkeypatch):
    ticks = [100.0]
    monkeypatch.setattr(wr.time, "monotonic", lambda: ticks[0])
    captured["resp"] = _Resp(200, "Title: first\n\nold")
    read_url(URL)
    ticks[0] = 399.0
    assert json.loads(read_url(URL))["memory_cached"]
    ticks[0] = 400.0
    captured["resp"] = _Resp(200, "Title: refreshed\n\nnew")
    assert json.loads(read_url(URL))["title"] == "refreshed"
    assert len(wr._URL_MEMORY_CACHE) == 1


def test_lru_entry_and_byte_limits(monkeypatch):
    monkeypatch.setattr(wr, "_CACHE_MAX_ENTRIES", 2)
    monkeypatch.setattr(wr, "_CACHE_MAX_BYTES", 200)
    value = json.dumps({"status": "ok", "content": "x" * 25})
    wr._cache_put("a", value)
    wr._cache_put("b", value)
    assert wr._cache_get("a") is not None
    wr._cache_put("c", value)
    assert list(wr._URL_MEMORY_CACHE) == ["a", "c"]
    assert wr._cache_get("b") is None
    wr._cache_put("huge", json.dumps({"content": "x" * 300}))
    assert "huge" not in wr._URL_MEMORY_CACHE
    monkeypatch.setattr(wr, "_CACHE_MAX_BYTES", 80)
    wr._cache_put("d", value)
    assert len(wr._URL_MEMORY_CACHE) == 1
    assert sum(row[2] for row in wr._URL_MEMORY_CACHE.values()) <= 80


def test_cache_operations_are_safe_under_concurrent_reads_and_evictions(monkeypatch):
    monkeypatch.setattr(wr, "_CACHE_MAX_ENTRIES", 8)
    monkeypatch.setattr(wr, "_CACHE_MAX_BYTES", 2000)
    value = json.dumps({"status": "ok", "content": "fixture"})

    def mutate(index):
        key = f"https://example.com/{index}"
        wr._cache_put(key, value)
        result = wr._cache_get(key)
        if result is not None:
            assert json.loads(result)["memory_cached"]

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(mutate, range(200)))
    assert len(wr._URL_MEMORY_CACHE) <= 8
    assert sum(row[2] for row in wr._URL_MEMORY_CACHE.values()) <= 2000


def test_failed_responses_are_not_cached(captured):
    captured["resp"] = _Resp(503, "temporary")
    assert json.loads(read_url(URL))["status"] == "error"
    captured["resp"] = _Resp(200, "Title: recovered\n\nbody")
    assert json.loads(read_url(URL))["title"] == "recovered"
