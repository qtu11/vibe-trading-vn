"""Read-only news tool: per-stock and global financial headlines.

Two public, no-auth news surfaces are wrapped behind one BaseTool contract:

* China A-share (and general China-market finance) headlines come from
  Eastmoney's free ``search-api`` news-list endpoint. Like every Eastmoney
  surface it rate-limits by source IP, so the request routes through the frozen,
  IP-throttled :mod:`backtest.loaders.eastmoney_client` rather than touching the
  host directly.
* US / HK headlines come from Yahoo Finance's public v1 search-news surface via
  the frozen, IP-throttled :mod:`backtest.loaders.yahoo_client`.

The tool never re-implements provider plumbing and never issues an un-throttled
request: every outbound call goes through a frozen client.

Scopes:

* ``stock`` (default) — headlines for a single security named by ``code``.
* ``global`` — broad market headlines, no ``code`` required.

A failure for one upstream is reported as an error envelope; the tool never
raises out of :meth:`StockNewsTool.execute`.
"""

from __future__ import annotations

import html
import json
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from backtest.loaders import eastmoney_client, yahoo_client
from backtest.loaders._http import throttled_get

from src.agent.tools import BaseTool

logger = logging.getLogger(__name__)

# Eastmoney free news search endpoint (JSON list of CMS articles). It is the
# same surface the site's search box calls; no auth, IP-throttled.
_EM_NEWS_URL = "https://search-api-web.eastmoney.com/search/jsonp"

# A-share / China-market suffixes that route to the Eastmoney news surface.
_EM_SUFFIXES = ("SH", "SZ", "BJ")
# Suffixes that route to Yahoo's search-news surface.
_YAHOO_SUFFIXES = ("US", "HK", "SA")
# Vietnam: Google News RSS first, CafeF's market RSS as fallback. Neither
# needs a key, and both are polite, read-only public feeds.
_VN_SUFFIXES = ("VN",)
_GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"
_CAFEF_MARKET_RSS = "https://cafef.vn/thi-truong-chung-khoan.rss"
_VN_NEWS_MIN_INTERVAL = 1.0

# Default broad-market query used when ``scope='global'`` carries no code.
_GLOBAL_QUERY = "财经"

# Bounds so a noisy upstream can never return an unbounded payload.
_DEFAULT_LIMIT = 20
_MAX_LIMIT = 50
# Per-article body trim so the envelope stays compact for the LLM.
_SNIPPET_CHARS = 280


def _clamp_limit(raw: Any) -> int:
    """Coerce a caller-supplied ``limit`` into the supported ``1.._MAX_LIMIT`` range.

    Args:
        raw: The raw ``limit`` value from the tool arguments (any type).

    Returns:
        An integer in ``[1, _MAX_LIMIT]``, falling back to ``_DEFAULT_LIMIT``
        when ``raw`` is missing or non-numeric.
    """
    try:
        value = int(raw)
    except (TypeError, ValueError, OverflowError):
        return _DEFAULT_LIMIT
    if value < 1:
        return 1
    return min(value, _MAX_LIMIT)


def _suffix_of(code: str) -> str:
    """Return the upper-cased exchange suffix of a symbol, or ``""`` when none."""
    if "." not in code:
        return ""
    return code.rpartition(".")[2].strip().upper()


def _bare_query(code: str) -> str:
    """Strip any exchange suffix to the bare code used as a news search term."""
    return code.strip().split(".", 1)[0].strip()


def _snippet(text: Any) -> str:
    """Trim an article body to a bounded plain-text snippet.

    Args:
        text: Raw body/summary value (any type).

    Returns:
        A whitespace-collapsed snippet capped at ``_SNIPPET_CHARS`` characters,
        or ``""`` when ``text`` is not a usable string.
    """
    if not isinstance(text, str):
        return ""
    collapsed = " ".join(text.split())
    if len(collapsed) <= _SNIPPET_CHARS:
        return collapsed
    return collapsed[:_SNIPPET_CHARS].rstrip() + "…"


def _decode_jsonp(payload: Any) -> Any:
    """Decode an Eastmoney response that may arrive JSON or JSONP-wrapped.

    The search endpoint usually returns a JSON object, but can echo a
    ``callback(...)`` JSONP envelope. A single outer call wrapper is stripped
    before parsing.

    Args:
        payload: The decoded body from the throttled client (``dict`` already, or
            a raw ``str`` when JSONP-wrapped).

    Returns:
        The decoded object, or ``None`` when nothing parseable is found.
    """
    if isinstance(payload, dict):
        return payload
    if not isinstance(payload, str):
        return None
    start = payload.find("(")
    end = payload.rfind(")")
    inner = payload[start + 1 : end] if start != -1 and end > start else payload
    try:
        return json.loads(inner)
    except (ValueError, TypeError):
        return None


def _em_article(raw: dict[str, Any]) -> dict[str, Any]:
    """Project one Eastmoney CMS article into a compact, named record.

    Args:
        raw: A single article dict from ``result.cmsArticleWebOld``.

    Returns:
        A flat ``{title, url, source, published, snippet}`` record.
    """
    return {
        "title": _snippet(raw.get("title")),
        "url": raw.get("url"),
        "source": raw.get("mediaName"),
        "published": raw.get("date"),
        "snippet": _snippet(raw.get("content")),
    }


def _fetch_eastmoney_news(query: str, limit: int) -> list[dict[str, Any]]:
    """Fetch China-market news headlines for a query from Eastmoney.

    Args:
        query: Free-text search term (bare code or keyword).
        limit: Maximum number of articles to return.

    Returns:
        A capped list of compact article records; empty when none.

    Raises:
        requests.RequestException: Network failure, propagated to the caller.
        requests.HTTPError: Non-2xx response status.
        ValueError: Body is not valid JSON.
    """
    param = json.dumps(
        {
            "uid": "",
            "keyword": query,
            "type": ["cmsArticleWebOld"],
            "client": "web",
            "clientType": "web",
            "param": {
                "cmsArticleWebOld": {
                    "searchScope": "default",
                    "sort": "default",
                    "pageIndex": 1,
                    "pageSize": limit,
                }
            },
        },
        ensure_ascii=False,
    )
    payload = eastmoney_client.get_json(
        _EM_NEWS_URL,
        params={"cb": "", "param": param, "_": "0"},
    )
    decoded = _decode_jsonp(payload)
    if not isinstance(decoded, dict):
        return []
    result = decoded.get("result")
    if not isinstance(result, dict):
        return []
    articles = result.get("cmsArticleWebOld")
    if not isinstance(articles, list):
        return []
    return [_em_article(a) for a in articles if isinstance(a, dict)][:limit]


def _yahoo_article(raw: dict[str, Any]) -> dict[str, Any]:
    """Project one Yahoo search-news item into the shared article shape.

    Args:
        raw: A single news dict from :func:`yahoo_client.search_news`.

    Returns:
        A flat ``{title, url, source, published, snippet}`` record.
    """
    published = None
    try:
        timestamp = float(raw.get("providerPublishTime"))
        published = datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    except (TypeError, ValueError, OSError, OverflowError):
        pass
    return {
        "title": _snippet(raw.get("title")),
        "url": raw.get("link"),
        "source": raw.get("publisher"),
        "published": published,
        "snippet": _snippet(raw.get("summary")),
    }


def _fetch_yahoo_news(query: str, limit: int) -> list[dict[str, Any]]:
    """Fetch US/HK news articles for a query via Yahoo search.

    Args:
        query: Free-text search term (bare ticker or keyword).
        limit: Maximum number of records to return.

    Returns:
        A capped list of compact article records; empty when none.

    Raises:
        requests.RequestException: Network/HTTP failure, propagated to caller.
    """
    articles = yahoo_client.search_news(query, limit)
    return [
        _yahoo_article(article) for article in articles if isinstance(article, dict)
    ][:limit]


def _vn_query(code: str) -> str:
    """Build a Vietnamese news query that is not just the ambiguous bare ticker.

    ``FPT`` alone matches unrelated entities; adding the market words and the
    listing spelling keeps the feed on the security the caller asked about.
    """
    bare = _bare_query(code)
    if not bare:
        return code.strip().upper()
    return f'"{bare}" (cổ phiếu OR chứng khoán OR "{bare}.VN")'


_TAG_RE = re.compile(r"<[^>]+>")


def _plain_text(value: Any) -> str:
    """Strip HTML from an RSS description and collapse whitespace."""
    if not isinstance(value, str):
        return ""
    return " ".join(html.unescape(_TAG_RE.sub(" ", value)).split())


def _rss_published(value: Any) -> str | None:
    """Convert an RFC-822 RSS date to ISO 8601, or return the raw value."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return parsedate_to_datetime(value.strip()).isoformat()
    except (TypeError, ValueError, OverflowError):
        return value.strip()


def _parse_rss_articles(
    text: str,
    limit: int,
    *,
    provider: str,
    code: str | None = None,
) -> list[dict[str, Any]]:
    """Parse RSS items into the article contract, optionally filtering by ticker.

    Google News titles end with " - Publisher"; that suffix is removed because
    the publisher already has its own field. ``publisher_url`` lets the
    grounding source registry classify a Google redirect by its real publisher.
    """
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ValueError(f"invalid RSS from {provider}: {exc}") from exc

    bare = _bare_query(code).casefold() if code else ""
    if bare:
        ticker_re = re.compile(
            rf"(?<![a-z0-9]){re.escape(bare)}(?![a-z0-9])", re.IGNORECASE
        )
    else:
        ticker_re = None

    articles: list[dict[str, Any]] = []
    for item in root.findall(".//item"):
        title = _plain_text(item.findtext("title"))
        url = (item.findtext("link") or "").strip()
        source_el = item.find("source")
        publisher = _plain_text(source_el.text if source_el is not None else "")
        publisher_url = (source_el.get("url") if source_el is not None else "") or ""
        snippet = _plain_text(item.findtext("description"))
        if not title and not url:
            continue
        if publisher and title.endswith(f" - {publisher}"):
            title = title[: -(len(publisher) + 3)].strip()
        if ticker_re is not None and not ticker_re.search(f"{title} {snippet}"):
            continue
        record: dict[str, Any] = {
            "title": _snippet(title),
            "url": url or None,
            "source": publisher or provider,
            "published": _rss_published(item.findtext("pubDate")),
            "snippet": _snippet(snippet),
        }
        if publisher_url:
            record["publisher_url"] = publisher_url
        articles.append(record)
        if len(articles) >= limit:
            break
    return articles


def _fetch_vn_google_news(code: str, limit: int) -> list[dict[str, Any]]:
    """Fetch Vietnamese Google News RSS for one listing."""
    response = throttled_get(
        _GOOGLE_NEWS_RSS,
        host_key="google_news_rss",
        min_interval=_VN_NEWS_MIN_INTERVAL,
        params={
            "q": _vn_query(code),
            "hl": "vi",
            "gl": "VN",
            "ceid": "VN:vi",
        },
        timeout=12.0,
    )
    response.raise_for_status()
    return _parse_rss_articles(
        response.text, limit, provider="google_news", code=code
    )


def _fetch_vn_cafef(code: str, limit: int) -> list[dict[str, Any]]:
    """Fetch CafeF's market RSS and keep items naming the listing."""
    response = throttled_get(
        _CAFEF_MARKET_RSS,
        host_key="cafef_rss",
        min_interval=_VN_NEWS_MIN_INTERVAL,
        timeout=12.0,
    )
    response.raise_for_status()
    return _parse_rss_articles(response.text, limit, provider="cafef", code=code)


class StockNewsTool(BaseTool):
    """Read-only per-stock and global financial news headlines."""

    name = "get_stock_news"
    description = (
        "Fetch recent financial news headlines, read-only and no auth. Markets: "
        "China A-share (SH/SZ/BJ) returns Eastmoney news ARTICLES "
        "(title/url/source/published/snippet) under 'articles'. US (.US), Hong "
        "Kong (.HK) and Brazil (B3 .SA) return Yahoo Finance news articles with "
        "the same fields. Vietnam (.VN) returns Vietnamese-language articles "
        "from Google News RSS, with CafeF's market RSS as fallback. Use "
        "scope 'stock' with a 'code', or scope 'global' (no code) for broad "
        "China-market finance articles. "
        'Example: {"code": "600519.SH", "scope": "stock", "limit": 10}.'
    )
    parameters = {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": (
                    "Symbol whose news to fetch, e.g. '600519.SH', 'AAPL.US', "
                    "'00700.HK', 'FPT.VN'. Required when scope='stock'; ignored "
                    "when scope='global'. The exchange suffix selects the "
                    "upstream: SH/SZ/BJ -> Eastmoney, US/HK -> Yahoo Finance, "
                    "VN -> Google News RSS with a CafeF fallback."
                ),
            },
            "scope": {
                "type": "string",
                "enum": ["stock", "global"],
                "description": (
                    "'stock' (default) for one security named by 'code'; "
                    "'global' for broad China-market finance headlines."
                ),
                "default": "stock",
            },
            "limit": {
                "type": "integer",
                "description": (
                    "Maximum number of headlines to return (1-50). Default 20."
                ),
                "default": _DEFAULT_LIMIT,
            },
        },
        "required": [],
    }

    def execute(self, **kwargs: Any) -> str:
        """Fetch news headlines for one stock or the broad market.

        Args:
            **kwargs: ``scope`` ('stock' | 'global', default 'stock'), ``code``
                (required when scope='stock'), and optional ``limit`` (1-50).

        Returns:
            A JSON string envelope. On success:
            ``{"ok": true, "market": <market>, "source": <source>,
            "data": {...}}``. On failure: ``{"ok": false, "error": "..."}``.
        """
        scope = kwargs.get("scope", "stock")
        if scope not in ("stock", "global"):
            return self._error(
                f"invalid scope: {scope!r}; expected 'stock' or 'global'"
            )

        limit = _clamp_limit(kwargs.get("limit"))

        if scope == "global":
            return self._run_global(limit)
        return self._run_stock(kwargs.get("code"), limit)

    def _run_global(self, limit: int) -> str:
        """Fetch broad China-market headlines from Eastmoney.

        Args:
            limit: Maximum number of headlines.

        Returns:
            A success or error JSON envelope.
        """
        try:
            articles = _fetch_eastmoney_news(_GLOBAL_QUERY, limit)
        except Exception as exc:  # noqa: BLE001 - surface any fetch failure as envelope
            logger.warning("global news fetch failed: %s", exc)
            return self._error(f"eastmoney news fetch failed: {exc}")
        return self._ok(
            "global", "eastmoney", {"scope": "global", "articles": articles}
        )

    def _run_stock(self, code_arg: Any, limit: int) -> str:
        """Fetch single-security headlines, routing by exchange suffix.

        Args:
            code_arg: Raw ``code`` argument (any type).
            limit: Maximum number of headlines.

        Returns:
            A success or error JSON envelope.
        """
        if not isinstance(code_arg, str) or not code_arg.strip():
            return self._error(
                "missing required parameter: code (required when scope='stock')"
            )

        code = code_arg.strip()
        suffix = _suffix_of(code)
        query = _bare_query(code)
        if not query:
            return self._error(f"invalid code: {code!r}")

        if suffix in _EM_SUFFIXES:
            return self._stock_via_eastmoney(code, query, limit)
        if suffix in _YAHOO_SUFFIXES:
            # A bare B3 code (PETR4) is ambiguous on Yahoo search; its own
            # spelling (PETR4.SA) is the listing.
            if suffix == "SA":
                query = code.upper()
            return self._stock_via_yahoo(code, query, limit)
        if suffix in _VN_SUFFIXES:
            return self._stock_via_vn(code, limit)
        return self._error(
            f"unsupported market for code {code!r}; expected suffix in "
            f"{_EM_SUFFIXES + _YAHOO_SUFFIXES + _VN_SUFFIXES}"
        )

    def _stock_via_eastmoney(self, code: str, query: str, limit: int) -> str:
        """Fetch A-share headlines from Eastmoney for one code."""
        try:
            articles = _fetch_eastmoney_news(query, limit)
        except Exception as exc:  # noqa: BLE001 - surface any fetch failure as envelope
            logger.warning("eastmoney news fetch failed for %s: %s", code, exc)
            return self._error(f"eastmoney news fetch failed: {exc}")
        return self._ok(
            "a_share",
            "eastmoney",
            {"scope": "stock", "code": code, "articles": articles},
        )

    def _stock_via_yahoo(self, code: str, query: str, limit: int) -> str:
        """Fetch US/HK news articles from Yahoo for one code."""
        market = {"HK": "hk", "SA": "br"}.get(_suffix_of(code), "us")
        try:
            articles = _fetch_yahoo_news(query, limit)
        except Exception as exc:  # noqa: BLE001 - surface any fetch failure as envelope
            logger.warning("yahoo news fetch failed for %s: %s", code, exc)
            return self._error(f"yahoo news fetch failed: {exc}")
        return self._ok(
            market,
            "yahoo",
            {"scope": "stock", "code": code, "articles": articles},
        )

    def _stock_via_vn(self, code: str, limit: int) -> str:
        """Fetch Vietnamese headlines, Google News first and CafeF as fallback.

        Google News RSS is the primary source because it indexes the whole
        Vietnamese financial press; CafeF's own market feed is the fallback
        when Google is unreachable or returns nothing for the listing. A
        provider that fails is recorded under ``provider_errors`` while the
        other one still answers, so a partial outage never looks like "no
        news". The call only fails when every provider fails.

        Args:
            code: Listing code such as ``FPT.VN``.
            limit: Maximum number of headlines.

        Returns:
            A success envelope with ``market="vietnam"`` and ``source`` naming
            the provider that answered, or an error envelope when all fail.
        """
        providers = (
            ("google_news", _fetch_vn_google_news),
            ("cafef", _fetch_vn_cafef),
        )
        errors: list[dict[str, str]] = []
        articles: list[dict[str, Any]] = []
        answered = ""
        for name, fetch in providers:
            try:
                articles = fetch(code, limit)
            except Exception as exc:  # noqa: BLE001 - one feed must not kill the call
                logger.warning("%s VN news fetch failed for %s: %s", name, code, exc)
                errors.append({"provider": name, "error": str(exc)})
                continue
            answered = name
            if articles:
                break
        if not answered:
            detail = "; ".join(
                f"{item['provider']}: {item['error']}" for item in errors
            )
            return self._error(f"vietnam news fetch failed for {code}: {detail}")

        extra: dict[str, Any] = {}
        if errors:
            extra["provider_errors"] = errors
            extra["partial"] = True
        return self._ok(
            "vietnam",
            answered,
            {"scope": "stock", "code": code, "articles": articles},
            **extra,
        )

    @staticmethod
    def _ok(
        market: str,
        source: str,
        data: dict[str, Any],
        **extra: Any,
    ) -> str:
        """Render a success envelope as a JSON string.

        Args:
            market: Market label (e.g. ``"a_share"``, ``"us"``, ``"global"``).
            source: Upstream provider name (``"eastmoney"``, ``"yahoo"`` or
                ``"google_news"``/``"cafef"``).
            data: The payload mapping.
            **extra: Optional top-level fields such as ``partial`` or
                ``provider_errors``.

        Returns:
            ``{"ok": true, "market": ..., "source": ..., "data": ...}`` as JSON.
        """
        payload: dict[str, Any] = {"ok": True, "market": market, "source": source}
        payload.update(extra)
        payload["data"] = data
        return json.dumps(payload, ensure_ascii=False)

    @staticmethod
    def _error(message: str) -> str:
        """Render a failure envelope as a JSON string.

        Args:
            message: Human-readable error text.

        Returns:
            ``{"ok": false, "error": message}`` as a JSON string.
        """
        return json.dumps({"ok": False, "error": message}, ensure_ascii=False)
