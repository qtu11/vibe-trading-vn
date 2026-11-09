"""DOM Cleaning Pipeline (Stage 1, 2, 3) for Token-Optimized Web Extraction.

Stage 1: Fast tree parsing with lxml.html (<3ms). Strip technical tags and boilerplate.
Stage 2: Main Content Extraction using Text-to-Tag ratio and Link Density (<0.4).
Stage 3: Whitelist sanitization using Rust nh3.clean with permitted tags.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import lxml.html
import nh3

logger = logging.getLogger(__name__)

# Permitted HTML tags for Stage 3 whitelist sanitization (Rust nh3)
PERMITTED_TAGS = {
    "h1", "h2", "h3", "h4", "h5", "h6",
    "p",
    "table", "thead", "tbody", "tfoot", "tr", "th", "td",
    "ul", "ol", "li",
    "blockquote",
    "strong", "em", "b", "i",
    "code", "pre",
    "a", "hr", "br",
}

# Permitted tag attributes for nh3 sanitization
PERMITTED_ATTRIBUTES = {
    "th": {"colspan", "rowspan"},
    "td": {"colspan", "rowspan"},
    "a": {"href", "title"},
}

# Technical tags stripped immediately in Stage 1
TECHNICAL_TAGS = {
    "script", "style", "noscript", "iframe", "object", "embed",
    "svg", "canvas", "form", "input", "button", "select", "textarea",
    "dialog", "template", "applet", "frame", "frameset",
}

# Structural boilerplate tags dropped in Stage 1
BOILERPLATE_TAGS = {"header", "footer", "nav", "aside"}

# CSS class/id substrings indicating ads, tracking, popups, and boilerplate
BOILERPLATE_PATTERNS = [
    # Ads & banners
    "ad-", "ads-", "-ad-", "_ad_", "banner", "sponsor", "outbrain", "taboola", "dfp", "advert",
    # Popups, cookies, overlays
    "cookie", "consent", "modal", "popup", "overlay", "newsletter", "subscribe",
    # Social shares & comments
    "social-share", "share-buttons", "comment", "disqus", "fb-comments",
    # Related & recommendations
    "related-posts", "related-news", "recommend", "trending-posts", "most-viewed",
    # Navbars & footers
    "navbar", "site-footer", "page-footer", "site-header", "page-header", "sidebar",
]

# Known Vietnamese financial content container classes
KNOWN_CONTENT_CLASSES = [
    "fck_detail",         # CafeF article content
    "article-body",       # Vietstock article content
    "detail-content",     # VnEconomy / common
    "post-content",       # Common news CMS
    "content-detail",     # Báo Đầu tư / common
    "story-body",         # BBC / Financial news
    "entry-content",      # WordPress financial blogs
    "news-content",       # General VN financial news
    "article-content",    # General portal content
]


@dataclass
class DOMCleanResult:
    """Result of the 3-stage DOM cleaning process."""
    sanitized_html: str
    title: str
    canonical_url: str
    metadata: dict[str, Any] = field(default_factory=dict)
    text_length: int = 0
    link_density: float = 0.0


class DOMCleaner:
    """3-stage DOM Cleaner using lxml.html and Rust nh3."""

    def __init__(self) -> None:
        pass

    def clean(self, html_str: str, base_url: str = "") -> DOMCleanResult:
        """Run the full 3-stage cleaning pipeline on raw HTML."""
        if not html_str or not html_str.strip():
            return DOMCleanResult(
                sanitized_html="",
                title="",
                canonical_url=base_url,
                metadata={},
                text_length=0,
                link_density=0.0,
            )

        # Parse HTML tree with lxml.html
        try:
            tree = lxml.html.document_fromstring(html_str)
        except Exception:
            try:
                tree = lxml.html.fromstring(html_str)
            except Exception as e:
                logger.warning("Failed to parse HTML with lxml.html: %s", e)
                # Fallback to minimal sanitization directly with nh3
                clean_raw = nh3.clean(
                    html_str,
                    tags=PERMITTED_TAGS,
                    attributes=PERMITTED_ATTRIBUTES,
                    strip_comments=True,
                )
                return DOMCleanResult(
                    sanitized_html=clean_raw,
                    title="",
                    canonical_url=base_url,
                    metadata={},
                    text_length=len(clean_raw),
                    link_density=0.0,
                )

        # Early step: Extract document metadata before dropping head/scripts
        metadata = self._extract_metadata(tree, base_url)
        title = metadata.get("title", "")
        canonical_url = metadata.get("canonical_url") or base_url

        # Stage 1: Fast tree parsing & boilerplate stripping
        self._stage1_strip_boilerplate(tree)

        # Stage 2: Main Content Extraction using Text-to-Tag ratio & Link Density
        content_el, link_density = self._stage2_extract_main_content(tree)

        if content_el is None:
            # Fallback to body or document root if no candidate survived
            body = tree.find(".//body")
            content_el = body if body is not None else tree

        # Stage 3: Whitelist sanitization using Rust nh3
        raw_fragment = lxml.html.tostring(content_el, encoding="unicode")
        sanitized_html = self._stage3_sanitize_html(raw_fragment)

        text_length = len(content_el.text_content().strip())

        return DOMCleanResult(
            sanitized_html=sanitized_html,
            title=title,
            canonical_url=canonical_url,
            metadata=metadata,
            text_length=text_length,
            link_density=link_density,
        )

    def _extract_metadata(self, doc: lxml.html.HtmlElement, base_url: str) -> dict[str, Any]:
        """Extract title, canonical URL, publisher, author, published date, and description."""
        meta: dict[str, Any] = {
            "title": "",
            "canonical_url": "",
            "publisher": "",
            "author": "",
            "published_date": "",
            "description": "",
        }

        # 1. Canonical URL
        for link in doc.xpath(".//link[@rel='canonical']"):
            href = link.attrib.get("href", "").strip()
            if href:
                meta["canonical_url"] = href
                break
        if not meta["canonical_url"]:
            for m in doc.xpath(".//meta[@property='og:url']"):
                c = m.attrib.get("content", "").strip()
                if c:
                    meta["canonical_url"] = c
                    break
        if not meta["canonical_url"]:
            meta["canonical_url"] = base_url

        # 2. Title
        for m in doc.xpath(".//meta[@property='og:title'] | .//meta[@name='twitter:title']"):
            c = m.attrib.get("content", "").strip()
            if c:
                meta["title"] = c
                break
        if not meta["title"]:
            title_nodes = doc.xpath(".//title")
            if title_nodes and title_nodes[0].text_content().strip():
                meta["title"] = title_nodes[0].text_content().strip()
        if not meta["title"]:
            h1_nodes = doc.xpath(".//h1")
            if h1_nodes and h1_nodes[0].text_content().strip():
                meta["title"] = h1_nodes[0].text_content().strip()

        # Clean title suffix (e.g., " | CafeF", " - Báo Đầu tư")
        if meta["title"]:
            meta["title"] = re.sub(
                r"\s*[\-\|]\s*(?:CafeF\.vn|CafeF|Vietstock|VnEconomy|Báo Đầu tư|Bao Dau tu|VnExpress|Tin Nhanh Chứng Khoán).*$",
                "",
                meta["title"],
                flags=re.IGNORECASE,
            ).strip()

        # 3. Publisher / Site Name
        for m in doc.xpath(".//meta[@property='og:site_name'] | .//meta[@name='publisher']"):
            c = m.attrib.get("content", "").strip()
            if c:
                meta["publisher"] = c
                break
        if not meta["publisher"] and base_url:
            domain = urlparse(base_url).netloc.lower()
            if "cafef.vn" in domain:
                meta["publisher"] = "CafeF"
            elif "vietstock.vn" in domain:
                meta["publisher"] = "Vietstock"
            elif "vneconomy.vn" in domain:
                meta["publisher"] = "VnEconomy"
            elif "baodautu.vn" in domain:
                meta["publisher"] = "Báo Đầu tư"
            elif domain:
                meta["publisher"] = domain.replace("www.", "")

        # 4. Author
        for m in doc.xpath(".//meta[@name='author'] | .//meta[@property='article:author'] | .//meta[@name='twitter:creator']"):
            c = m.attrib.get("content", "").strip()
            if c:
                meta["author"] = c
                break
        if not meta["author"]:
            author_nodes = doc.xpath(
                "//*[contains(@class, 'author') or contains(@class, 'byline') or contains(@class, 'detail-author')]"
            )
            for node in author_nodes:
                text = node.text_content().strip()
                if 2 < len(text) < 60:
                    meta["author"] = text
                    break

        # 5. Published Date
        for m in doc.xpath(
            ".//meta[@property='article:published_time'] | .//meta[@name='pubdate'] | "
            ".//meta[@name='publishdate'] | .//meta[@name='date'] | .//meta[@property='og:updated_time']"
        ):
            c = m.attrib.get("content", "").strip()
            if c:
                meta["published_date"] = c
                break
        if not meta["published_date"]:
            time_nodes = doc.xpath(".//time")
            for t in time_nodes:
                dt = t.attrib.get("datetime", "").strip() or t.text_content().strip()
                if dt:
                    meta["published_date"] = dt
                    break

        # Check JSON-LD metadata if present
        for script in doc.xpath(".//script[@type='application/ld+json']"):
            try:
                raw_json = script.text_content().strip()
                if raw_json:
                    data = json.loads(raw_json)
                    if isinstance(data, list) and data:
                        data = data[0]
                    if isinstance(data, dict):
                        if not meta["title"] and "headline" in data:
                            meta["title"] = str(data["headline"]).strip()
                        if not meta["published_date"] and "datePublished" in data:
                            meta["published_date"] = str(data["datePublished"]).strip()
                        if not meta["author"]:
                            author_info = data.get("author")
                            if isinstance(author_info, dict):
                                meta["author"] = str(author_info.get("name", "")).strip()
                            elif isinstance(author_info, str):
                                meta["author"] = author_info.strip()
            except Exception:
                pass

        # 6. Description
        for m in doc.xpath(".//meta[@property='og:description'] | .//meta[@name='description']"):
            c = m.attrib.get("content", "").strip()
            if c:
                meta["description"] = c
                break

        return meta

    def _stage1_strip_boilerplate(self, doc: lxml.html.HtmlElement) -> None:
        """Stage 1: Strip technical tags and boilerplate containers."""
        # 1. Drop technical tags
        for el in doc.xpath(
            "//script | //style | //noscript | //iframe | //object | //embed | "
            "//svg | //canvas | //form | //input | //button | //select | //textarea | "
            "//dialog | //template | //applet | //head"
        ):
            el.drop_tree()

        # 2. Drop structural boilerplate tags
        for el in doc.xpath("//header | //footer | //nav | //aside | //*[@role='navigation'] | //*[@role='banner'] | //*[@role='contentinfo']"):
            el.drop_tree()

        # 3. Drop elements matching boilerplate classes/ids
        # Build an XPath condition for boilerplate patterns
        conditions = []
        for pat in BOILERPLATE_PATTERNS:
            conditions.append(f"contains(@class, '{pat}')")
            conditions.append(f"contains(@id, '{pat}')")
        xpath_query = f"//*[{' or '.join(conditions)}]"

        try:
            matched_elements = doc.xpath(xpath_query)
            for el in matched_elements:
                # Protect known content containers from being dropped
                class_attr = el.attrib.get("class", "").lower()
                if any(known in class_attr for known in KNOWN_CONTENT_CLASSES):
                    continue
                # Protect article or main tag
                if el.tag in ("article", "main", "body", "html"):
                    continue
                el.drop_tree()
        except Exception as e:
            logger.debug("Error during boilerplate class stripping: %s", e)

    def _stage2_extract_main_content(self, doc: lxml.html.HtmlElement) -> tuple[lxml.html.HtmlElement | None, float]:
        """Stage 2: Main Content Extraction using Text-to-Tag ratio and Link Density (<0.4)."""
        candidates: list[tuple[lxml.html.HtmlElement, float, float]] = []  # (element, score, link_density)

        # 1. First search known financial content containers
        known_xpath_parts = [f"contains(@class, '{cls_name}')" for cls_name in KNOWN_CONTENT_CLASSES]
        priority_query = f"//*[{' or '.join(known_xpath_parts)} or self::article or self::main]"

        priority_nodes = doc.xpath(priority_query)
        for node in priority_nodes:
            score, link_density = self._score_candidate(node, is_priority=True)
            if score > 0:
                candidates.append((node, score, link_density))

        # 2. General search across sections and divs if priority did not find high-scoring container
        if not candidates or max(c[1] for c in candidates) < 300.0:
            general_nodes = doc.xpath("//div | //section")
            for node in general_nodes:
                # Don't re-score priority nodes
                if node in priority_nodes:
                    continue
                score, link_density = self._score_candidate(node, is_priority=False)
                if score > 0:
                    candidates.append((node, score, link_density))

        if not candidates:
            # If no candidate survived filtering, evaluate body
            body = doc.find(".//body")
            if body is not None:
                _, ld = self._score_candidate(body, is_priority=False)
                return body, ld
            return doc, 0.0

        # Sort by score descending
        candidates.sort(key=lambda x: x[1], reverse=True)
        best_candidate, best_score, best_ld = candidates[0]
        return best_candidate, best_ld

    def _score_candidate(self, el: lxml.html.HtmlElement, is_priority: bool = False) -> tuple[float, float]:
        """Calculate content score and link density for a candidate container.

        Rules:
        - Link Density (<0.4): If link density >= 0.4, reject candidate (score = 0.0).
        - Text-to-Tag ratio: Higher text per child tag indicates actual reading content.
        - Paragraphs & Tables: Financial reports heavily feature <p> and <table>.

        Scoring on raw text length alone picks the navigation over the article:
        a site menu can hold more characters than the story, and its link
        labels are short, so its link density stays low. Prose is therefore
        measured on its own terms: paragraphs (``<p>``) carry article text,
        list items (``<li>``) carry menu entries, and table cells carry
        figures. A container whose text is mostly list items and has no
        paragraphs is a menu and is pushed far below any article.
        """
        text = el.text_content().strip()
        text_len = len(text)
        if text_len < 40:
            return 0.0, 1.0

        # Compute link density
        links = el.xpath(".//a")
        link_text_len = sum(len(a.text_content().strip()) for a in links)
        link_density = link_text_len / max(text_len, 1)

        # Enforce link density threshold (<0.4)
        if link_density >= 0.4:
            return 0.0, link_density

        # Count structural tags
        paragraphs = len(el.xpath(".//p"))
        tables = len(el.xpath(".//table"))
        headings = len(el.xpath(".//h1 | .//h2 | .//h3 | .//h4 | .//h5 | .//h6"))
        all_tags = len(el.xpath(".//*")) + 1

        # Text-to-Tag ratio
        text_to_tag = text_len / max(all_tags, 1)

        # Prose measurement. Whitespace is collapsed first: a list item whose
        # "text" is 90% indentation is not a 60-character menu label, and
        # counting raw characters lets the menu pass the length test.
        def _collapsed_len(node: lxml.html.HtmlElement) -> int:
            return len(" ".join(node.text_content().split()))

        paragraph_lens = [_collapsed_len(p) for p in el.xpath(".//p")]
        paragraph_text_len = sum(paragraph_lens)
        list_item_lens = [_collapsed_len(li) for li in el.xpath(".//li")]
        list_item_text_len = sum(list_item_lens)
        table_text_len = sum(_collapsed_len(c) for c in el.xpath(".//td | .//th"))

        # Sentence-sized text blocks, used to gauge whether this reads like
        # prose rather than a label list.
        block_lens = [
            length
            for length in paragraph_lens + list_item_lens + [
                _collapsed_len(c) for c in el.xpath(".//td | .//th")
            ]
            if length >= 40
        ]
        avg_block_len = (sum(block_lens) / len(block_lens)) if block_lens else 0.0

        # Menu test: the text is dominated by list items, carries no
        # paragraphs, and no single block reads like a sentence.
        meaningful_total = paragraph_text_len + list_item_text_len + table_text_len
        is_menu = (
            meaningful_total > 0
            and list_item_text_len >= meaningful_total * 0.6
            and paragraph_text_len < meaningful_total * 0.15
        )

        # Composite score
        # Base: text length scaled by non-link ratio
        score = float(text_len) * (1.0 - link_density)

        # Boost for paragraphs and financial tables
        structure_boost = 1.0 + (0.15 * min(paragraphs, 25)) + (0.5 * min(tables, 8)) + (0.1 * min(headings, 6))
        score *= structure_boost

        # Tag density modifier
        if text_to_tag > 25.0:
            score *= 1.2

        # Prose weight: paragraphs are article text, list items are menu
        # entries. Scale the score by the share of the container that is real
        # prose, and by how sentence-like its blocks are.
        if block_lens:
            avg_bonus = 1.0 + min(2.0, avg_block_len / 300.0)
            if paragraph_text_len > 0:
                prose_share = paragraph_text_len / max(meaningful_total, 1)
                score *= (0.6 + 1.4 * min(1.0, prose_share * 2)) * avg_bonus
            else:
                # No paragraphs at all: the only prose-like blocks are list
                # items, which is a menu signature.
                score *= 0.15 * avg_bonus

        if is_menu:
            # A menu must never win over the article it sits next to.
            score *= 0.05

        if is_priority:
            score *= 1.5

        return score, link_density

    def _stage3_sanitize_html(self, raw_html: str) -> str:
        """Stage 3: Whitelist sanitization using Rust nh3.clean."""
        if not raw_html or not raw_html.strip():
            return ""

        cleaned = nh3.clean(
            raw_html,
            tags=PERMITTED_TAGS,
            attributes=PERMITTED_ATTRIBUTES,
            url_schemes={"http", "https"},
            strip_comments=True,
        )
        return cleaned.strip()
