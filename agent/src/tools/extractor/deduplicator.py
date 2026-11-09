"""3-Tier Cross-Site Deduplicator for Web Documents.

Tier 1: Canonical URL Normalization (stripping UTM, tracking parameters, session IDs, hash fragments).
Tier 2: Exact text SHA-256 hash.
Tier 3: 64-bit SimHash with 3-grams and Vietnamese stop words removal (Hamming distance <= 3).
Syndication aggregation: Preserves primary record and attaches syndicated_sources.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections import Counter
from typing import Any, TypeVar
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

logger = logging.getLogger(__name__)

# Tracking and marketing query parameters to strip in Tier 1
TRACKING_QUERY_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "utm_id",
    "fbclid", "gclid", "gbraid", "wbraid", "dclid", "msclkid",
    "ref", "source", "session_id", "sid", "spm", "from", "feature",
    "_ga", "_gl", "mc_cid", "mc_eid", "yclid", "zanpid", "igshid",
}

# Standard Vietnamese stop words
VIETNAMESE_STOP_WORDS = {
    "và", "của", "các", "có", "được", "cho", "trong", "với", "đã", "là",
    "những", "khi", "này", "đó", "tại", "từ", "về", "ra", "lại", "theo",
    "sau", "trước", "do", "bởi", "đến", "ở", "nhưng", "mà", "nên", "thì",
    "nếu", "như", "sẽ", "cũng", "rất", "nhiều", "hơn", "đang", "vẫn", "bị",
    "qua", "đều", "phải", "đây", "vì", "để", "lên", "xuống", "hay", "hoặc",
    "cùng", "vào", "ngay", "chỉ", "cả", "thế", "nào", "gì", "ai", "bằng",
    "suốt", "giữa", "bên", "tới", "mỗi", "mọi", "nọ", "kia", "ấy",
}

T = TypeVar("T")


def normalize_canonical_url(url: str) -> str:
    """Tier 1: Normalize URL by stripping tracking parameters, session IDs, and fragments."""
    if not url or not url.strip():
        return ""

    raw_url = url.strip()
    try:
        parts = urlsplit(raw_url)
    except Exception:
        return raw_url

    scheme = parts.scheme.lower() or "https"
    netloc = parts.netloc.lower()

    # Strip default ports :80 and :443
    if netloc.endswith(":80") and scheme == "http":
        netloc = netloc[:-3]
    elif netloc.endswith(":443") and scheme == "https":
        netloc = netloc[:-4]

    # Normalize path: collapse duplicate slashes and strip trailing slash (except root '/')
    path = re.sub(r"/+", "/", parts.path)
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    if not path:
        path = "/"

    # Strip tracking parameters and sort query parameters
    filtered_query = []
    if parts.query:
        query_pairs = parse_qsl(parts.query, keep_blank_values=False)
        for k, v in query_pairs:
            if k.lower() not in TRACKING_QUERY_PARAMS:
                filtered_query.append((k, v))
        filtered_query.sort(key=lambda x: (x[0], x[1]))

    new_query = urlencode(filtered_query) if filtered_query else ""

    # Drop hash fragments
    return urlunsplit((scheme, netloc, path, new_query, ""))


def compute_exact_hash(text: str) -> str:
    """Tier 2: Compute SHA-256 hash of normalized lowercase text."""
    if not text:
        return hashlib.sha256(b"").hexdigest()

    # Collapse all whitespace and lowercase
    normalized = " ".join(text.split()).lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def compute_simhash_64(text: str) -> int:
    """Tier 3: Compute 64-bit SimHash using multi-scale shingles (unigrams, bigrams, trigrams) and Vietnamese stop words removal."""
    if not text or not text.strip():
        return 0

    # Extract alphanumeric words and filter out Vietnamese stop words
    words = [
        w for w in re.findall(r"[\w]+", text.lower(), flags=re.UNICODE)
        if w not in VIETNAMESE_STOP_WORDS
    ]

    if not words:
        # Fallback to character 3-grams for symbolic or non-alphanumeric texts
        clean_str = "".join(re.findall(r"[\w]+", text.lower(), flags=re.UNICODE))
        if len(clean_str) >= 3:
            features = Counter(clean_str[i:i+3] for i in range(len(clean_str) - 2))
        elif clean_str:
            features = Counter([clean_str])
        else:
            return 0
    else:
        # Multi-scale word shingles:
        # - Unigrams (weight 2): preserve entity, ticker, and numeric presence
        # - Bigrams (weight 1): capture Vietnamese 2-syllable compound words (từ ghép)
        # - Trigrams (weight 1): capture local syntactic phrase structure
        features = Counter()
        for w in words:
            features[w] += 2
        for i in range(len(words) - 1):
            features[f"{words[i]}_{words[i+1]}"] += 1
        for i in range(len(words) - 2):
            features[f"{words[i]}_{words[i+1]}_{words[i+2]}"] += 1

    # Accumulate 64-bit weight vector
    v = [0] * 64
    for feat, count in features.items():
        # 64-bit integer hash from SHA-256 digest
        h = int.from_bytes(hashlib.sha256(feat.encode("utf-8")).digest()[:8], "big")
        for i in range(64):
            if (h >> i) & 1:
                v[i] += count
            else:
                v[i] -= count

    # Build 64-bit fingerprint
    fingerprint = 0
    for i in range(64):
        if v[i] > 0:
            fingerprint |= (1 << i)

    return fingerprint


def hamming_distance(h1: int, h2: int) -> int:
    """Compute Hamming distance between two 64-bit integers."""
    return (h1 ^ h2).bit_count()


def is_near_duplicate(h1: int, h2: int, threshold: int = 3) -> bool:
    """Return True if Hamming distance <= threshold (near-duplicate syndicated story)."""
    if h1 == 0 or h2 == 0:
        return False
    return hamming_distance(h1, h2) <= threshold


def deduplicate_documents(docs: list[Any], simhash_threshold: int = 3) -> list[Any]:
    """Execute 3-tier Cross-Site Deduplication on a list of CleanDocuments.

    Tiers:
    1. Canonical URL Normalization
    2. Exact text SHA-256 hash
    3. 64-bit SimHash (Hamming distance <= simhash_threshold)

    Syndication Aggregation:
    - Retains the primary document with richest content/metadata.
    - Aggregates non-primary URLs into `primary.syndicated_sources`.
    """
    if not docs:
        return []

    # Cluster documents: clusters is a list of lists of docs
    clusters: list[list[Any]] = []

    for doc in docs:
        doc_canonical = getattr(doc, "canonical_url", "") or normalize_canonical_url(getattr(doc, "url", ""))
        doc_text = getattr(doc, "clean_markdown", "")
        doc_exact_hash = compute_exact_hash(doc_text)
        doc_simhash = getattr(doc, "simhash", 0)
        if not doc_simhash and doc_text:
            doc_simhash = compute_simhash_64(doc_text)
            if hasattr(doc, "simhash"):
                doc.simhash = doc_simhash

        matched_cluster = None

        for cluster in clusters:
            primary = cluster[0]
            primary_canonical = getattr(primary, "canonical_url", "") or normalize_canonical_url(getattr(primary, "url", ""))
            primary_text = getattr(primary, "clean_markdown", "")
            primary_exact_hash = compute_exact_hash(primary_text)
            primary_simhash = getattr(primary, "simhash", 0)

            # Tier 1 Check: Canonical URL match
            if doc_canonical and primary_canonical and doc_canonical == primary_canonical:
                matched_cluster = cluster
                break

            # Tier 2 Check: Exact text SHA-256 match
            if doc_exact_hash and primary_exact_hash and doc_exact_hash == primary_exact_hash:
                matched_cluster = cluster
                break

            # Tier 3 Check: SimHash near-duplicate (Hamming distance <= threshold)
            if doc_simhash != 0 and primary_simhash != 0 and is_near_duplicate(doc_simhash, primary_simhash, threshold=simhash_threshold):
                matched_cluster = cluster
                break

        if matched_cluster is not None:
            matched_cluster.append(doc)
        else:
            clusters.append([doc])

    deduplicated: list[Any] = []

    for cluster in clusters:
        if len(cluster) == 1:
            deduplicated.append(cluster[0])
            continue

        # Multiple documents in cluster: pick the primary document
        # Scoring factors: text length, presence of published_date, author, title
        def score_doc(d: Any) -> float:
            text = getattr(d, "clean_markdown", "")
            meta = getattr(d, "metadata", {}) or {}
            score = float(len(text))
            if getattr(d, "title", ""):
                score += 300.0
            if meta.get("published_date"):
                score += 200.0
            if meta.get("author"):
                score += 100.0
            # Bonus for high-tier financial publishers
            publisher = str(meta.get("publisher", "")).lower()
            if any(p in publisher for p in ("cafef", "vietstock", "vneconomy", "báo đầu tư", "tin nhanh chứng khoán")):
                score += 500.0
            return score

        cluster.sort(key=score_doc, reverse=True)
        primary = cluster[0]

        # Gather syndicated sources from the remaining documents in the cluster
        syndicated = set(getattr(primary, "syndicated_sources", []) or [])
        primary_url = getattr(primary, "url", "")
        primary_canonical = getattr(primary, "canonical_url", "")

        for secondary in cluster[1:]:
            sec_url = getattr(secondary, "url", "")
            if sec_url and sec_url != primary_url and sec_url != primary_canonical:
                syndicated.add(sec_url)

            # Include any nested syndicated sources from secondary
            for sub_src in getattr(secondary, "syndicated_sources", []) or []:
                if sub_src != primary_url and sub_src != primary_canonical:
                    syndicated.add(sub_src)

        if hasattr(primary, "syndicated_sources"):
            primary.syndicated_sources = sorted(list(syndicated))

        deduplicated.append(primary)

    return deduplicated
