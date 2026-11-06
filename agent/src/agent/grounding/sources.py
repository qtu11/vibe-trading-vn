"""External-source registry and source evidence intake.

The numeric gate only trusts numbers a tool put in a JSON payload. News
articles, search snippets and fetched pages put their numbers in prose, so a
figure quoted from them could never be grounded -- it was redacted as
``(omitted※)`` even when the article was the right citation.

This module closes that gap without weakening the gate:

* :class:`SourcePolicy` is a static, tiered registry of reputable publishers.
  A tier describes *who* published a page, never whether the page is true.
* :class:`SourceRecord` is one concrete page a tool returned this session. It
  keeps a bounded excerpt, a content hash and the numeric candidates parsed
  from the text, so a ``cited`` figure can be checked for presence in the
  source instead of being trusted on the model's word.
* :class:`_SourceMixin` ingests source-shaped tool results, assigns stable
  ``S1``/``S2`` ids, deduplicates by canonical URL, and renders the compact
  index the model sees on the tool result.

Only a bounded excerpt and a hash are retained: the full text stays with the
publisher. A source is always ``unverified`` -- presence in a document is not
independent confirmation of the number.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit, urlunsplit

from src.agent.grounding.identity import _utc_now

# Bounds keep the persisted artifact and the model-facing index small.
MAX_SOURCES_PER_SESSION = 40
MAX_SOURCE_TEXT_CHARS = 20_000
MAX_SOURCE_NUMBERS = 240
MAX_SOURCE_EXCERPT_CHARS = 400
MAX_SOURCE_QUOTES = 3
MAX_INDEX_ENTRIES = 8

# Tier vocabulary. The number is the registry rank, not a probability:
# 1 official/primary, 2 wire service, 3 licensed data/research,
# 4 broker or established financial media, 5 unknown/social.
TIER_LABELS = {
    1: "official/primary",
    2: "wire service",
    3: "licensed data or research",
    4: "broker or established financial media",
    5: "unverified/unknown",
}


@dataclass(frozen=True)
class SourcePolicy:
    """One publisher in the static reputation registry."""

    source_id: str
    display_name: str
    domains: tuple[str, ...]
    tier: int
    market: tuple[str, ...] = ("GLOBAL",)
    kinds: tuple[str, ...] = ("news",)
    cite_allowed: bool = True
    redistribute: bool = False
    terms_url: str | None = None


def _policy(
    source_id: str,
    display_name: str,
    domains: Iterable[str],
    tier: int,
    market: tuple[str, ...],
    kinds: tuple[str, ...] = ("news",),
    terms_url: str | None = None,
) -> SourcePolicy:
    return SourcePolicy(
        source_id=source_id,
        display_name=display_name,
        domains=tuple(domains),
        tier=tier,
        market=market,
        kinds=kinds,
        terms_url=terms_url,
    )


# The minimum registry the citation contract needs. Domain matching is
# suffix-based, so an entry for ``reuters.com`` also covers ``jp.reuters.com``.
# More specific hostnames must come before their parent domain.
SOURCE_POLICIES: tuple[SourcePolicy, ...] = (
    # ---- Tier 1: official exchanges, regulators, statistical agencies ----
    _policy("hose", "HOSE (HSX)", ("hsx.vn", "hose.vn"), 1, ("VN",), ("price", "filing")),
    _policy("hnx", "HNX", ("hnx.vn",), 1, ("VN",), ("price", "filing")),
    _policy("upcom", "UPCoM", ("upcom.hnx.vn",), 1, ("VN",), ("price", "filing")),
    _policy("ssc", "State Securities Commission", ("ssc.gov.vn",), 1, ("VN",), ("filing", "regulation")),
    _policy("vsdc", "VSDC", ("vsdc.vn",), 1, ("VN",), ("filing", "corporate_action")),
    _policy("sbv", "State Bank of Vietnam", ("sbv.gov.vn",), 1, ("VN",), ("macro",)),
    _policy("nso", "General Statistics Office", ("nso.gov.vn", "gso.gov.vn"), 1, ("VN",), ("macro",)),
    _policy("mof", "Ministry of Finance", ("mof.gov.vn",), 1, ("VN",), ("macro", "filing")),
    _policy("sec_edgar", "SEC EDGAR", ("sec.gov",), 1, ("US",), ("filing",)),
    _policy("federal_reserve", "Federal Reserve", ("federalreserve.gov",), 1, ("US",), ("macro", "filing")),
    _policy("fred", "FRED", ("fred.stlouisfed.org",), 1, ("US",), ("macro", "price")),
    _policy("bls", "BLS", ("bls.gov",), 1, ("US",), ("macro",)),
    _policy("bea", "BEA", ("bea.gov",), 1, ("US",), ("macro",)),
    _policy("ecb", "ECB", ("ecb.europa.eu",), 1, ("GLOBAL",), ("macro",)),
    _policy("boe", "Bank of England", ("bankofengland.co.uk",), 1, ("GLOBAL",), ("macro",)),
    _policy("boj", "Bank of Japan", ("boj.or.jp",), 1, ("GLOBAL",), ("macro",)),
    _policy("cftc", "CFTC", ("cftc.gov",), 1, ("FX", "CRYPTO"), ("filing", "positioning")),
    _policy("cme", "CME Group", ("cmegroup.com",), 1, ("FX", "US"), ("price", "reference")),
    _policy("lbma", "LBMA", ("lbma.org.uk",), 1, ("FX",), ("reference",)),
    _policy("world_gold_council", "World Gold Council", ("gold.org",), 1, ("FX",), ("research", "reference")),
    _policy("cninfo", "CNINFO", ("cninfo.com.cn",), 1, ("CN",), ("filing",)),
    _policy("sse", "Shanghai Stock Exchange", ("sse.com.cn",), 1, ("CN",), ("filing", "price")),
    _policy("szse", "Shenzhen Stock Exchange", ("szse.cn",), 1, ("CN",), ("filing", "price")),
    _policy("hkex", "HKEX", ("hkex.com.hk", "hkexnews.hk"), 1, ("HK",), ("filing", "price")),
    _policy("csrc", "CSRC", ("csrc.gov.cn",), 1, ("CN",), ("filing", "regulation")),
    _policy("pboc", "PBOC", ("pbc.gov.cn",), 1, ("CN",), ("macro",)),
    _policy("nbs", "National Bureau of Statistics of China", ("stats.gov.cn",), 1, ("CN",), ("macro",)),
    # ---- Tier 2: wire services and flagship financial press ----
    _policy("reuters", "Reuters", ("reuters.com",), 2, ("GLOBAL",), ("news",)),
    _policy("bloomberg", "Bloomberg", ("bloomberg.com",), 2, ("GLOBAL",), ("news", "data")),
    _policy("ft", "Financial Times", ("ft.com",), 2, ("GLOBAL",), ("news",)),
    _policy("wsj", "The Wall Street Journal", ("wsj.com",), 2, ("GLOBAL",), ("news",)),
    _policy("cnbc", "CNBC", ("cnbc.com",), 2, ("GLOBAL",), ("news",)),
    _policy("barrons", "Barron's", ("barrons.com",), 2, ("US",), ("news",)),
    _policy("caixin", "Caixin", ("caixin.com",), 2, ("CN",), ("news",)),
    _policy("scmp", "South China Morning Post", ("scmp.com",), 2, ("CN", "HK"), ("news",)),
    _policy("ap", "Associated Press", ("apnews.com",), 2, ("GLOBAL",), ("news",)),
    _policy("nikkei", "Nikkei", ("nikkei.com",), 2, ("GLOBAL",), ("news",)),
    _policy("economist", "The Economist", ("economist.com",), 2, ("GLOBAL",), ("news",)),
    # ---- Tier 3: licensed data and research ----
    _policy("fiingroup", "FiinGroup / FiinPro X", ("fiingroup.vn", "fiinpro.vn"), 3, ("VN",), ("data", "fundamentals")),
    _policy("vietstock_data", "Vietstock DataFeed", ("data.vietstock.vn",), 3, ("VN",), ("data", "fundamentals")),
    _policy("lseg", "LSEG", ("lseg.com",), 3, ("GLOBAL",), ("data",)),
    _policy("factset", "FactSet", ("factset.com",), 3, ("GLOBAL",), ("data",)),
    _policy("sp_global", "S&P Global", ("spglobal.com",), 3, ("GLOBAL",), ("data", "research")),
    _policy("wind", "Wind", ("wind.com.cn",), 3, ("CN",), ("data",)),
    _policy("trading_economics", "Trading Economics", ("tradingeconomics.com",), 3, ("GLOBAL",), ("macro", "data")),
    _policy("koyfin", "Koyfin", ("koyfin.com",), 3, ("GLOBAL",), ("data",)),
    _policy("morningstar", "Morningstar", ("morningstar.com",), 3, ("GLOBAL",), ("data", "research")),
    _policy("coingecko", "CoinGecko", ("coingecko.com",), 3, ("CRYPTO",), ("price", "data")),
    _policy("coinglass", "CoinGlass", ("coinglass.com",), 3, ("CRYPTO",), ("derivatives", "data")),
    _policy("glassnode", "Glassnode", ("glassnode.com",), 3, ("CRYPTO",), ("onchain", "data")),
    _policy("cryptoquant", "CryptoQuant", ("cryptoquant.com",), 3, ("CRYPTO",), ("onchain", "data")),
    _policy("defillama", "DefiLlama", ("defillama.com",), 3, ("CRYPTO",), ("onchain", "data")),
    _policy("dune", "Dune", ("dune.com",), 3, ("CRYPTO",), ("onchain", "data")),
    _policy("token_terminal", "Token Terminal", ("tokenterminal.com",), 3, ("CRYPTO",), ("onchain", "data")),
    # ---- Tier 4: broker research and established financial media ----
    _policy("ssi", "SSI Research", ("ssi.com.vn",), 4, ("VN",), ("research", "broker")),
    _policy("vietcap", "Vietcap", ("vietcap.com.vn",), 4, ("VN",), ("research", "broker")),
    _policy("vcbs", "VCBS", ("vcbs.com.vn",), 4, ("VN",), ("research", "broker")),
    _policy("tcbs", "TCBS", ("tcbs.com.vn",), 4, ("VN",), ("research", "broker")),
    _policy("hsc", "HSC", ("hsc.com.vn",), 4, ("VN",), ("research", "broker")),
    _policy("mbs", "MBS", ("mbs.com.vn",), 4, ("VN",), ("research", "broker")),
    _policy("bsc", "BSC", ("bsc.com.vn",), 4, ("VN",), ("research", "broker")),
    _policy("vndirect", "VNDirect", ("vndirect.com.vn",), 4, ("VN",), ("research", "broker")),
    _policy("mirae_asset", "Mirae Asset", ("miraeasset.com.vn",), 4, ("VN",), ("research", "broker")),
    _policy("kis_vn", "KIS Vietnam", ("kisvn.vn",), 4, ("VN",), ("research", "broker")),
    _policy("dsc", "DSC", ("dsc.com.vn",), 4, ("VN",), ("research", "broker")),
    _policy("cafef", "CafeF", ("cafef.vn",), 4, ("VN",), ("news",)),
    _policy("nguoiquansat", "Người Quan Sát", ("nguoiquansat.vn",), 4, ("VN",), ("news",)),
    _policy("vneconomy", "VnEconomy", ("vneconomy.vn",), 4, ("VN",), ("news",)),
    _policy("baodautu", "Báo Đầu tư", ("baodautu.vn",), 4, ("VN",), ("news",)),
    _policy("vnexpress", "VnExpress", ("vnexpress.net",), 4, ("VN",), ("news",)),
    _policy("vietnamnet", "VietnamNet", ("vietnamnet.vn",), 4, ("VN",), ("news",)),
    _policy("dantri", "Dân trí", ("dantri.com.vn",), 4, ("VN",), ("news",)),
    _policy("bnews", "Bnews", ("bnews.vn",), 4, ("VN",), ("news",)),
    _policy("ndh", "NDH", ("ndh.vn",), 4, ("VN",), ("news",)),
    _policy("vietstock", "Vietstock", ("vietstock.vn",), 4, ("VN",), ("news",)),
    _policy("saigon_times", "The Saigon Times", ("thesaigontimes.vn",), 4, ("VN",), ("news",)),
    _policy("vietnamnews", "Vietnam News", ("vietnamnews.vn",), 4, ("VN",), ("news",)),
    _policy("thanhnien", "Thanh Niên", ("thanhnien.vn",), 4, ("VN",), ("news",)),
    _policy("tuoitre", "Tuổi Trẻ", ("tuoitre.vn",), 4, ("VN",), ("news",)),
    _policy("tinnhanhchungkhoan", "Đầu tư Chứng khoán", ("tinnhanhchungkhoan.vn",), 4, ("VN",), ("news",)),
    _policy("eastmoney", "Eastmoney", ("eastmoney.com",), 4, ("CN",), ("news", "data")),
    _policy("sina_finance", "Sina Finance", ("sina.com.cn",), 4, ("CN",), ("news",)),
    _policy("ths", "同花顺", ("10jqka.com.cn",), 4, ("CN",), ("news", "data")),
    _policy("yicai", "Yicai", ("yicai.com",), 4, ("CN",), ("news",)),
    _policy("cls", "财联社", ("cls.cn",), 4, ("CN",), ("news",)),
    _policy("marketwatch", "MarketWatch", ("marketwatch.com",), 4, ("US",), ("news",)),
    _policy("yahoo_finance", "Yahoo Finance", ("finance.yahoo.com", "yahoo.com"), 4, ("GLOBAL",), ("news", "data")),
    _policy("business_insider", "Business Insider", ("businessinsider.com",), 4, ("GLOBAL",), ("news",)),
    _policy("forbes", "Forbes", ("forbes.com",), 4, ("GLOBAL",), ("news",)),
    _policy("fortune", "Fortune", ("fortune.com",), 4, ("GLOBAL",), ("news",)),
    _policy("investing_com", "Investing.com", ("investing.com",), 4, ("GLOBAL",), ("news", "data")),
)

# Social and user-generated domains: usable when the user points at them, but
# labelled unverified and never treated as an independent confirmation.
SOCIAL_DOMAINS: tuple[str, ...] = (
    "x.com",
    "twitter.com",
    "reddit.com",
    "facebook.com",
    "tiktok.com",
    "youtube.com",
    "medium.com",
    "substack.com",
    "blogspot.com",
    "wordpress.com",
    "linkedin.com",
    "telegram.org",
    "t.me",
)


def host_of(url: str) -> str:
    """Return a lower-case hostname for an HTTP(S) URL, or an empty string."""
    if not url:
        return ""
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""
    return host.rstrip(".")


def _host_matches(host: str, domain: str) -> bool:
    """Whether ``host`` is ``domain`` or a subdomain of it."""
    return bool(host) and (host == domain or host.endswith("." + domain))


def policy_for_url(
    url: str | None,
    *,
    publisher_url: str | None = None,
) -> SourcePolicy | None:
    """Resolve the most specific registry entry for a page or its publisher.

    Args:
        url: The page URL. A Google News redirect has no useful host, so the
            publisher's own URL (when a feed supplies one) is preferred.
        publisher_url: Optional publisher home URL from the feed metadata.

    Returns:
        The matching :class:`SourcePolicy`, or ``None`` for an unregistered
        publisher.
    """
    hosts = [host_of(item) for item in (publisher_url, url) if item]
    for host in hosts:
        if not host:
            continue
        for policy in SOURCE_POLICIES:
            if any(_host_matches(host, domain) for domain in policy.domains):
                return policy
    return None


def is_social_url(url: str | None) -> bool:
    """Whether a URL points at a user-generated/social domain."""
    host = host_of(url or "")
    return any(_host_matches(host, domain) for domain in SOCIAL_DOMAINS)


def canonical_url(url: str | None) -> str:
    """Normalise a URL for source deduplication.

    A fragment and trailing slash never identify a different document. The
    query string is kept: many publishers route a story through it.
    """
    if not url:
        return ""
    value = str(url).strip()
    if not value:
        return ""
    try:
        parts = urlsplit(value)
    except ValueError:
        return value
    if parts.scheme not in {"http", "https"}:
        return value
    host = (parts.hostname or "").lower()
    netloc = host
    if parts.port and parts.port not in {80, 443}:
        netloc = f"{host}:{parts.port}"
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), netloc, path, parts.query, ""))


@dataclass(frozen=True)
class SourceRecord:
    """One page a tool returned in this session, with bounded evidence text.

    ``numbers`` holds every plausible numeric reading of the source text. A
    ``cited`` figure is checked for membership there; membership is evidence
    that the source *says* the number, not that the number is true.
    """

    source_id: str
    call_id: str
    tool: str
    url: str | None
    domain: str
    title: str
    publisher: str
    tier: int
    market: tuple[str, ...]
    published_at: str | None
    retrieved_at: str
    language: str | None
    excerpt: str
    quotes: tuple[str, ...]
    numbers: tuple[float, ...]
    text_sha256: str
    content_chars: int
    verification: str = "unverified"
    policy_id: str | None = None
    cite_allowed: bool = True
    #: When the source's data is effective, not when the page was published.
    #: Filled from an explicit row field when the provider supplies one; the
    #: publication date is only a labelled fallback, never a ground-truth claim.
    data_effective_at: str | None = None
    #: ``"explicit"`` when the provider supplied the effective time, and
    #: ``"published_at"`` when the publication date stood in for it.
    data_effective_basis: str | None = None

    @property
    def tier_label(self) -> str:
        return TIER_LABELS.get(self.tier, TIER_LABELS[5])


# A number token: grouped thousands or plain, optional decimal part. The
# lookbehind keeps identifiers such as ``Q3`` and ``S1`` from becoming numbers.
_NUMBER_TOKEN_RE = re.compile(
    r"(?<![\w.])[-+]?(?:\d{1,3}(?:[.,]\d{3})+|\d+)(?:[.,]\d+)?(?![\w])"
)

_UNIT_WORDS = (
    (" nghìn tỷ", 1e12),
    (" ngàn tỷ", 1e12),
    (" triệu tỷ", 1e15),
    (" tỷ", 1e9),
    (" ty", 1e9),
    (" billion", 1e9),
    (" bn", 1e9),
    ("亿", 1e8),
    (" triệu", 1e6),
    (" million", 1e6),
    (" mn", 1e6),
    ("万", 1e4),
    (" vạn", 1e4),
    (" nghìn", 1e3),
    (" ngàn", 1e3),
    (" thousand", 1e3),
    ("千", 1e3),
)


def _numeric_variants(token: str) -> set[float]:
    """Return every plausible reading of one numeric token.

    Vietnamese and international grouping conflict (``1.234,5`` vs
    ``1,234.5``), so an ambiguous single separator yields both readings.
    Ambiguity is acceptable here: this is a presence check, not a valuation.
    """
    sign = -1.0 if token.startswith("-") else 1.0
    body = token.lstrip("+-").replace("\u00a0", "")
    if not body or not any(char.isdigit() for char in body):
        return set()
    if "," in body and "." in body:
        decimal = "," if body.rfind(",") > body.rfind(".") else "."
        thousands = "." if decimal == "," else ","
        cleaned = body.replace(thousands, "").replace(decimal, ".")
        try:
            return {sign * float(cleaned)}
        except ValueError:
            return set()
    if "," in body:
        parts = body.split(",")
        if len(parts) == 2 and len(parts[1]) == 3 and parts[0] != "0":
            # "1,234" is thousands in English and decimal-comma elsewhere.
            try:
                return {sign * float("".join(parts)), sign * float(parts[0] + "." + parts[1])}
            except ValueError:
                return set()
        try:
            return {sign * float("".join(parts))} if all(len(part) == 3 for part in parts[1:]) else {
                sign * float(body.replace(",", "."))
            }
        except ValueError:
            return set()
    if "." in body:
        parts = body.split(".")
        if len(parts) == 2 and len(parts[1]) == 3 and parts[0] not in {"", "0"}:
            try:
                return {sign * float("".join(parts)), sign * float(body)}
            except ValueError:
                return set()
        try:
            return {sign * float(body)}
        except ValueError:
            return set()
    try:
        return {sign * float(body)}
    except ValueError:
        return set()


def _scaled_variants(text: str, end: int, value: float) -> set[float]:
    """Unit multipliers immediately following a number (``1.2 tỷ``)."""
    tail = text[end : end + 18].casefold()
    scaled: set[float] = set()
    for word, factor in _UNIT_WORDS:
        if tail.startswith(word):
            scaled.add(value * factor)
            break
    return scaled


def numeric_candidates(text: str) -> tuple[float, ...]:
    """Extract bounded numeric candidates from source prose.

    Years, page numbers and document ids are kept: excluding them would need
    language-specific rules, and a false candidate only makes the presence
    check more permissive for that source, never for a different one.
    """
    if not text:
        return ()
    found: list[float] = []
    seen: set[float] = set()
    for match in _NUMBER_TOKEN_RE.finditer(text[:MAX_SOURCE_TEXT_CHARS]):
        for value in _numeric_variants(match.group(0)):
            if not (value == value and abs(value) != float("inf")):
                continue
            variants = {value} | _scaled_variants(text, match.end(), value)
            for item in variants:
                if item in seen:
                    continue
                seen.add(item)
                found.append(item)
                if len(found) >= MAX_SOURCE_NUMBERS:
                    return tuple(found)
    return tuple(found)


def _quotes(text: str) -> tuple[str, ...]:
    """Bounded quotes around the first few numbers, for human audit."""
    quotes: list[str] = []
    for match in _NUMBER_TOKEN_RE.finditer(text[:MAX_SOURCE_TEXT_CHARS]):
        start = max(0, match.start() - 120)
        end = min(len(text), match.end() + 120)
        quote = " ".join(text[start:end].split())
        if quote and quote not in quotes:
            quotes.append(quote[:400])
        if len(quotes) >= MAX_SOURCE_QUOTES:
            break
    return tuple(quotes)


def _bounded_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value[:MAX_SOURCE_TEXT_CHARS]


def _clip(value: Any, limit: int = MAX_SOURCE_EXCERPT_CHARS) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def _language_of(text: str) -> str | None:
    """A coarse language hint; the gate never uses it for a decision."""
    if not text:
        return None
    sample = text[:600]
    cjk = sum(1 for char in sample if "\u4e00" <= char <= "\u9fff")
    vietnamese = sum(
        1
        for char in sample
        if char in "ăâđêôơưĂÂĐÊÔƠƯáàảãạấầẩẫậắằẳẵặéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ"
    )
    if cjk >= max(4, len(sample) // 20):
        return "zh"
    if vietnamese >= 3:
        return "vi"
    return "en"


def _merge_numbers(*groups: Iterable[float]) -> tuple[float, ...]:
    seen: set[float] = set()
    merged: list[float] = []
    for group in groups:
        for value in group:
            if value in seen:
                continue
            seen.add(value)
            merged.append(value)
            if len(merged) >= MAX_SOURCE_NUMBERS:
                return tuple(merged)
    return tuple(merged)


class _SourceMixin:
    """Session source ledger: ingest, deduplicate, index and look up by id."""

    def _init_sources(self) -> None:
        self._sources: list[SourceRecord] = []
        self._source_by_id: dict[str, SourceRecord] = {}
        self._source_keys: dict[str, str] = {}
        self._source_seq = 0

    @property
    def sources(self) -> tuple[SourceRecord, ...]:
        """Every source collected this session, in id order."""
        return tuple(self._sources)

    def source_records(self) -> list[dict[str, Any]]:
        """Serialise the source ledger for ``grounding_evidence.json``."""
        return [self._source_payload(record) for record in self._sources]

    def source_by_id(self, source_id: str) -> SourceRecord | None:
        """Look up one source by its ``S#`` id (case-insensitive)."""
        value = str(source_id or "").strip()
        if value.startswith("[") and value.endswith("]"):
            value = value[1:-1]
        if value[:1].upper() == "S":
            value = "S" + value[1:]
        return self._source_by_id.get(value.upper().replace(" ", ""))

    def sources_index(self, call_id: str) -> list[dict[str, Any]]:
        """Compact index of sources this tool call produced, for the model."""
        rows = [record for record in self._sources if record.call_id == call_id]
        return [
            {
                "id": record.source_id,
                "publisher": record.publisher,
                "title": record.title[:120],
                "url": record.url,
                "tier": record.tier,
                "published_at": record.published_at,
                "data_effective_at": record.data_effective_at,
            }
            for record in rows[:MAX_INDEX_ENTRIES]
        ]

    def source_citations(self) -> list[dict[str, Any]]:
        """Compact, reply-safe projection of the source ledger.

        The full records in ``grounding_evidence.json`` carry quotes, numbers
        and hashes for audit. A chat reply only needs the identity, trust tier
        and the two timestamps a reader uses to judge freshness, so this
        projection is what reply metadata carries.
        """
        return [
            {
                "source_id": record.source_id,
                "title": record.title,
                "url": record.url,
                "domain": record.domain,
                "publisher": record.publisher,
                "tier": record.tier,
                "tier_label": record.tier_label,
                "market": list(record.market),
                "published_at": record.published_at,
                "data_effective_at": record.data_effective_at,
                "data_effective_basis": record.data_effective_basis,
                "retrieved_at": record.retrieved_at,
                "verification": record.verification,
                "cite_allowed": record.cite_allowed,
            }
            for record in self._sources
        ]

    @staticmethod
    def _source_payload(record: SourceRecord) -> dict[str, Any]:
        return {
            "source_id": record.source_id,
            "call_id": record.call_id,
            "tool": record.tool,
            "url": record.url,
            "domain": record.domain,
            "title": record.title,
            "publisher": record.publisher,
            "tier": record.tier,
            "tier_label": record.tier_label,
            "market": list(record.market),
            "published_at": record.published_at,
            "data_effective_at": record.data_effective_at,
            "data_effective_basis": record.data_effective_basis,
            "retrieved_at": record.retrieved_at,
            "language": record.language,
            "excerpt": record.excerpt,
            "quotes": list(record.quotes),
            "numbers": list(record.numbers),
            "text_sha256": record.text_sha256,
            "content_chars": record.content_chars,
            "verification": record.verification,
            "policy_id": record.policy_id,
            "cite_allowed": record.cite_allowed,
        }

    def _ingest_sources(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
        payload: Any,
        call_id: str,
    ) -> None:
        """Collect page-shaped results from source tools. Never raises."""
        try:
            if not isinstance(payload, dict):
                return
            if tool_name == "web_search":
                self._ingest_search_payload(payload, call_id)
            elif tool_name == "read_url":
                self._ingest_read_url(payload, call_id)
            elif tool_name in {"read_document", "doc_reader"}:
                self._ingest_document(payload, call_id)
            elif tool_name == "get_stock_news":
                self._ingest_news(payload, call_id)
        except Exception:  # noqa: BLE001 - source intake must not break a run
            return

    def _ingest_search_payload(self, payload: Mapping[str, Any], call_id: str) -> None:
        results = payload.get("results")
        if not isinstance(results, list):
            return
        for row in results[:MAX_INDEX_ENTRIES]:
            if not isinstance(row, Mapping):
                continue
            url = str(row.get("url") or "").strip()
            title = _clip(row.get("title"), 240)
            snippet = _bounded_text(row.get("snippet"))
            if not url and not title:
                continue
            self._add_source(
                call_id=call_id,
                tool="web_search",
                url=url or None,
                title=title or url,
                publisher="",
                published_at=str(
                    row.get("published_at")
                    or row.get("published")
                    or row.get("date")
                    or ""
                )
                or None,
                data_effective_at=str(
                    row.get("data_effective_at")
                    or row.get("effective_at")
                    or row.get("as_of")
                    or ""
                )
                or None,
                text=" ".join(part for part in (title, snippet) if part),
                excerpt=_clip(" ".join(part for part in (title, snippet) if part)),
                language=_language_of(snippet or title),
            )

    def _ingest_read_url(self, payload: Mapping[str, Any], call_id: str) -> None:
        url = str(payload.get("url") or "").strip()
        title = _clip(payload.get("title"), 240)
        content = _bounded_text(payload.get("content"))
        if not url and not content:
            return
        self._add_source(
            call_id=call_id,
            tool="read_url",
            url=url or None,
            title=title or url,
            publisher="",
            published_at=str(
                payload.get("published_at")
                or payload.get("published")
                or payload.get("date")
                or ""
            )
            or None,
            data_effective_at=str(
                payload.get("data_effective_at")
                or payload.get("effective_at")
                or payload.get("as_of")
                or ""
            )
            or None,
            text=content or title,
            excerpt=_clip(content or title),
            language=_language_of(content),
        )

    def _ingest_document(self, payload: Mapping[str, Any], call_id: str) -> None:
        name = _clip(payload.get("file"), 160)
        text = _bounded_text(payload.get("text"))
        if not name and not text:
            return
        self._add_source(
            call_id=call_id,
            tool="read_document",
            url=f"doc://{name}" if name else None,
            title=name or "user document",
            publisher="User document",
            published_at=str(
                payload.get("published_at")
                or payload.get("published")
                or payload.get("date")
                or ""
            )
            or None,
            data_effective_at=str(
                payload.get("data_effective_at")
                or payload.get("effective_at")
                or payload.get("as_of")
                or ""
            )
            or None,
            text=text,
            excerpt=_clip(text),
            language=_language_of(text),
        )

    def _ingest_news(self, payload: Mapping[str, Any], call_id: str) -> None:
        data = payload.get("data")
        if not isinstance(data, Mapping):
            return
        articles = data.get("articles")
        if not isinstance(articles, list):
            return
        provider = str(payload.get("source") or "")
        for row in articles[:MAX_INDEX_ENTRIES]:
            if not isinstance(row, Mapping):
                continue
            url = str(row.get("url") or "").strip()
            title = _clip(row.get("title"), 240)
            snippet = _bounded_text(row.get("snippet"))
            if not url and not title:
                continue
            self._add_source(
                call_id=call_id,
                tool="get_stock_news",
                url=url or None,
                title=title or url,
                publisher=str(row.get("source") or provider),
                publisher_url=str(row.get("publisher_url") or "") or None,
                published_at=str(
                    row.get("published_at")
                    or row.get("published")
                    or row.get("date")
                    or ""
                )
                or None,
                data_effective_at=str(
                    row.get("data_effective_at")
                    or row.get("effective_at")
                    or row.get("as_of")
                    or ""
                )
                or None,
                text=" ".join(part for part in (title, snippet) if part),
                excerpt=_clip(" ".join(part for part in (title, snippet) if part)),
                language=_language_of(snippet or title),
            )

    def _add_source(
        self,
        *,
        call_id: str,
        tool: str,
        url: str | None,
        title: str,
        publisher: str,
        published_at: str | None,
        text: str,
        excerpt: str,
        language: str | None,
        publisher_url: str | None = None,
        data_effective_at: str | None = None,
    ) -> SourceRecord | None:
        """Add or upsert one source, assigning a stable ``S#`` id.

        ``publisher_url`` exists for feeds (Google News most notably) whose
        article link is a redirect on the feed's own host. The real publisher
        determines the tier, and is also the clearer domain to show.

        ``data_effective_at`` is the time the source's *data* applies to. When
        a provider does not supply one, ``published_at`` stands in and
        ``data_effective_basis`` records that fallback, so a reader can tell
        the difference.
        """
        published_at = str(published_at or "").strip() or None
        explicit_effective = str(data_effective_at or "").strip() or None
        key = canonical_url(url) or f"title:{title.casefold()}"
        if not key:
            return None
        existing_id = self._source_keys.get(key)
        if existing_id is None and len(self._sources) >= MAX_SOURCES_PER_SESSION:
            return None
        policy = policy_for_url(url, publisher_url=publisher_url)
        domain = host_of(url) if url and url.startswith(("http://", "https://")) else ""
        if publisher_url:
            domain = host_of(publisher_url) or domain
        if not policy and is_social_url(url):
            tier = 5
        else:
            tier = policy.tier if policy else 5
        display = (
            publisher.strip()
            or (policy.display_name if policy else "")
            or domain
            or title
            or "unknown"
        )
        numbers = numeric_candidates(text or excerpt)
        quotes = _quotes(text or excerpt)
        digest = hashlib.sha256((text or excerpt).encode("utf-8")).hexdigest()

        if existing_id is not None:
            previous = self._source_by_id[existing_id]
            # A later ``read_url`` carries the full page; keep the larger text.
            if len(text or excerpt) <= previous.content_chars:
                return previous
            if explicit_effective:
                effective, effective_basis = explicit_effective, "explicit"
            elif previous.data_effective_at:
                effective, effective_basis = (
                    previous.data_effective_at,
                    previous.data_effective_basis,
                )
            elif published_at:
                effective, effective_basis = published_at, "published_at"
            else:
                effective, effective_basis = None, None
            record = SourceRecord(
                source_id=previous.source_id,
                call_id=call_id,
                tool=tool,
                url=url or previous.url,
                domain=domain or previous.domain,
                title=title or previous.title,
                publisher=display or previous.publisher,
                tier=tier,
                market=policy.market if policy else previous.market,
                published_at=published_at or previous.published_at,
                retrieved_at=_utc_now(),
                language=language or previous.language,
                excerpt=excerpt or previous.excerpt,
                quotes=quotes or previous.quotes,
                numbers=_merge_numbers(previous.numbers, numbers),
                text_sha256=digest,
                content_chars=len(text or excerpt),
                verification="unverified",
                policy_id=policy.source_id if policy else previous.policy_id,
                cite_allowed=policy.cite_allowed if policy else previous.cite_allowed,
                data_effective_at=effective,
                data_effective_basis=effective_basis,
            )
            self._replace_source(record)
            return record

        self._source_seq += 1
        source_id = f"S{self._source_seq}"
        effective = explicit_effective or published_at
        effective_basis = (
            "explicit" if explicit_effective else ("published_at" if effective else None)
        )
        record = SourceRecord(
            source_id=source_id,
            call_id=call_id,
            tool=tool,
            url=url,
            domain=domain,
            title=title or domain or source_id,
            publisher=display,
            tier=tier,
            market=policy.market if policy else ("GLOBAL",),
            published_at=published_at,
            retrieved_at=_utc_now(),
            language=language,
            excerpt=excerpt,
            quotes=quotes,
            numbers=numbers,
            text_sha256=digest,
            content_chars=len(text or excerpt),
            verification="unverified",
            policy_id=policy.source_id if policy else None,
            cite_allowed=policy.cite_allowed if policy else True,
            data_effective_at=effective,
            data_effective_basis=effective_basis,
        )
        self._sources.append(record)
        self._source_by_id[source_id] = record
        self._source_keys[key] = source_id
        return record

    def _replace_source(self, record: SourceRecord) -> None:
        for index, previous in enumerate(self._sources):
            if previous.source_id == record.source_id:
                self._sources[index] = record
                break
        self._source_by_id[record.source_id] = record


def source_ids_in(text: str) -> tuple[str, ...]:
    """Return the distinct ``[S#]``/``S#`` ids referenced in a string."""
    if not text:
        return ()
    found: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r"\[?(S\d{1,3})\]?", text, re.IGNORECASE):
        value = "S" + match.group(1)[1:]
        if value in seen:
            continue
        seen.add(value)
        found.append(value)
    return tuple(found)


def value_in_source(record: SourceRecord, value: float, *, tolerance: float = 0.005) -> bool:
    """Whether ``value`` appears among a source's numeric candidates.

    The band is the gate's own 0.5% relative tolerance, so a rounded
    presentation of a source number is accepted and an unrelated number is not.
    """
    for candidate in record.numbers:
        gap = abs(candidate - value)
        if gap <= max(abs(candidate), abs(value), 1.0) * tolerance:
            return True
    return False


def source_payload_text(payload: Any) -> str:
    """A bounded JSON view used by tests and diagnostics."""
    try:
        return json.dumps(payload, ensure_ascii=False)[:MAX_SOURCE_TEXT_CHARS]
    except (TypeError, ValueError):
        return ""


@dataclass
class SourceCitationCheck:
    """The outcome of resolving one ``cited`` figure against a source id."""

    source_ids: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    value_found: bool = False
    visible: bool = False
    fields: dict[str, Any] = field(default_factory=dict)
