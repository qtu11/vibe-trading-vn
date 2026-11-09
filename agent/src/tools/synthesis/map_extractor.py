"""Parallel Map Extractor for Financial Fact and Metric Extraction.

Module: M4 / Workstream 4 (Map-Reduce & Structured Synthesis Engine)
Extracts structured financial facts, metrics, and quantitative evidence
from PrunedDocument chunks using deterministic rules (regex + Markdown table AST)
with optional LLM enhancement.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Callable, List, Optional, Sequence, Union

from src.tools.optimizer.bm25_scorer import (
    _PERIOD_PATTERN,
    extract_periods_from_text,
    extract_tickers_from_query,
)
from src.tools.optimizer.chunker import Chunk
from src.tools.synthesis.models import ExtractedMetric, PrunedDocument


# Standard Vietnamese financial metric naming map
METRIC_CANONICAL_MAP = {
    "doanh thu": "Doanh thu thuần",
    "doanh thu thuần": "Doanh thu thuần",
    "net revenue": "Doanh thu thuần",
    "revenue": "Doanh thu thuần",
    "lợi nhuận sau thuế": "Lợi nhuận sau thuế",
    "lợi nhuận ròng": "Lợi nhuận sau thuế",
    "lãi ròng": "Lợi nhuận sau thuế",
    "lnst": "Lợi nhuận sau thuế",
    "net profit": "Lợi nhuận sau thuế",
    "pat": "Lợi nhuận sau thuế",
    "lợi nhuận trước thuế": "Lợi nhuận trước thuế",
    "lntt": "Lợi nhuận trước thuế",
    "ebt": "Lợi nhuận trước thuế",
    "lợi nhuận gộp": "Lợi nhuận gộp",
    "gross profit": "Lợi nhuận gộp",
    "biên lợi nhuận gộp": "Biên lợi nhuận gộp",
    "biên gộp": "Biên lợi nhuận gộp",
    "gross margin": "Biên lợi nhuận gộp",
    "biên lợi nhuận ròng": "Biên lợi nhuận ròng",
    "biên ròng": "Biên lợi nhuận ròng",
    "net margin": "Biên lợi nhuận ròng",
    "eps": "Lãi cơ bản trên cổ phiếu (EPS)",
    "lãi cơ bản trên cổ phiếu": "Lãi cơ bản trên cổ phiếu (EPS)",
    "p/e": "Hệ số P/E",
    "pe": "Hệ số P/E",
    "p/b": "Hệ số P/B",
    "pb": "Hệ số P/B",
    "roe": "Tỷ suất sinh lời trên VCSH (ROE)",
    "roa": "Tỷ suất sinh lời trên tổng tài sản (ROA)",
    "cổ tức": "Cổ tức",
    "dividend": "Cổ tức",
    "tổng tài sản": "Tổng tài sản",
    "total assets": "Tổng tài sản",
    "vốn chủ sở hữu": "Vốn chủ sở hữu",
    "equity": "Vốn chủ sở hữu",
    "nợ vay": "Tổng nợ vay",
    "debt": "Tổng nợ vay",
}

#: Phrases that change the meaning of the metric they contain.
#:
#: "doanh thu tài chính" is financial income, not net revenue. "lợi nhuận
#: trước thuế" is not net profit. A substring match on "doanh thu" would
#: file the first as "Doanh thu thuần" and the second as "Lợi nhuận sau
#: thuế", both wrong. Each entry lists the phrase that must not appear next
#: to the given metric name.
METRIC_QUALIFIER_PHRASES = {
    "doanh thu": ("doanh thu tài chính", "doanh thu khác", "doanh thu hoạt động tài chính"),
    "lợi nhuận sau thuế": ("lợi nhuận trước thuế",),
    "lợi nhuận ròng": ("lợi nhuận trước thuế",),
    "lãi ròng": ("lợi nhuận trước thuế",),
}

# Regex to detect financial prose statements.
#
# The gap between the metric name and the value must not cross a table
# boundary or a line break, otherwise "doanh thu" in one sentence binds to a
# number that belongs to a different metric further down the table.
#
# The gap must also not contain a second metric name. "105.000 tỷ đồng doanh
# thu và 9.210 tỷ đồng lợi nhuận sau thuế" names two metrics in one
# sentence, and a gap that crosses "và" binds the second number to the
# first metric.
#
# Vietnamese puts the verb on either side of the metric name: "đạt doanh thu
# 34.100 tỷ" and "doanh thu đạt 34.100 tỷ" are both common. The pattern
# accepts both orders.
_PROSE_FILLER = r"(?:[^|.,;:\n]{0,60}?)"
_PROSE_VERB = (
    r"(?:đạt|ước đạt|ghi nhận|tăng|giảm|khoảng|ở mức|là|đạt mức|báo lãi|mang về)"
)
_PROSE_METRIC = (
    r"(?:biên lợi nhuận gộp|biên gộp|biên lợi nhuận ròng|biên ròng|doanh thu(?: thuần)?|"
    r"lợi nhuận sau thuế|lợi nhuận ròng|lãi ròng|lnst|lợi nhuận gộp|"
    r"lợi nhuận trước thuế|lntt|eps|p/e|p/b|roe|roa)"
)
#: The filler between a metric name and its value. It must not contain
#: another metric name, a unit word, a period label, or a conjunction that
#: starts a new figure.
_PROSE_GAP = (
    r"(?:(?!" + _PROSE_METRIC + r"|tỷ|triệu|nghìn|%|và |hoặc |cùng |"
    r"quý\s|Q[1-4]|\d{1,2}T|năm\s|FY)"
    r"[^|.,;:\n]){0,40}?"
)
PROSE_FACT_PATTERN = re.compile(
    r"(?i)\b(?P<metric>" + _PROSE_METRIC + r")\b"
    + _PROSE_GAP
    + r"(?:" + _PROSE_VERB + r")?\s*"
    r"(?P<val>[+-]?\d[\d.,]*)\s*"
    r"(?P<unit>tỷ(?:\s+đồng)?|triệu(?:\s+đồng)?|nghìn(?:\s+tỷ)?|%|đồng/cp|đồng|lần|usd)?",
    re.UNICODE,
)

#: The same statement with the figure first: "105.000 tỷ đồng doanh thu".
#: Vietnamese puts the number before the metric often enough that a pattern
#: that only reads the other way loses a large share of the figures.
PROSE_FACT_PATTERN_REVERSED = re.compile(
    r"(?i)(?P<val>[+-]?\d[\d.,]*)\s*"
    r"(?P<unit>tỷ(?:\s+đồng)?|triệu(?:\s+đồng)?|nghìn(?:\s+tỷ)?)\s*"
    r"(?P<lead>của\s+|về\s+|cho\s+)?"
    r"\b(?P<metric>" + _PROSE_METRIC + r")\b",
    re.UNICODE,
)

#: A period label and its position in the text. Used to label each figure
#: with the period nearest to it. The shared pattern from the optimizer is
#: reused so both stages agree on what a period looks like.
_PERIOD_IN_TEXT = _PERIOD_PATTERN

#: Labels that describe a comparison, not a fiscal period. "YoY" means the
#: figure is compared with the same period last year. Filing the figure
#: under "YoY" loses the quarter it belongs to, so these labels are
#: ignored when a figure gets its period.
COMPARISON_LABELS = frozenset({"yoy", "mom", "qoq"})

#: Vietnamese writes the quarter as a Roman numeral. Map it to the digit.
_ROMAN_QUARTERS = {"i": "1", "ii": "2", "iii": "3", "iv": "4"}


def _with_year(label: str, year: str) -> str:
    """Add the document year to a period that has no year of its own.

    "Q3" plus "2024" becomes "Q3/2024", and "9T" becomes "9T/2024". A label
    that already carries a year is left alone.
    """
    if not label or not year:
        return label
    if re.search(r"\d{4}", label):
        return label
    if re.fullmatch(r"Q[1-4]", label):
        return f"{label}/{year}"
    if re.fullmatch(r"\d{1,2}T", label):
        return f"{label}/{year}"
    return label


def _normalize_period(label: str) -> str:
    """Turn a period label into a canonical form.

    "quý III/2024" becomes "Q3/2024", "quý III" becomes "Q3", and "lũy kế
    9 tháng" becomes "9T". A year is added when the document mentions one,
    because "quý III" alone does not say which year it belongs to.
    """
    text = label.lower().replace(" ", "")
    if text.startswith("lũykế"):
        months = ""
        digits = "".join(ch for ch in text if ch.isdigit())
        if digits:
            months = digits
        if months:
            return f"{months}T"
    if text.startswith("quý"):
        rest = text[3:]
        quarter = rest.split("/")[0]
        year = ""
        if "/" in rest:
            year = rest.split("/", 1)[1]
        quarter = _ROMAN_QUARTERS.get(quarter, quarter)
        if quarter.isdigit() and 1 <= int(quarter) <= 4:
            return f"Q{quarter}/{year}" if year else f"Q{quarter}"
    if re.fullmatch(r"q[1-4]/20\d{2}", text):
        return text.upper()
    if re.fullmatch(r"q[1-4]", text):
        return text.upper()
    if re.fullmatch(r"\d{1,2}t/20\d{2}", text):
        return text.upper()
    if re.fullmatch(r"\d{1,2}t", text):
        return text.upper()
    if re.fullmatch(r"năm20\d{2}", text):
        return text.replace("năm", "FY")
    if re.fullmatch(r"fy20\d{2}", text):
        return text.upper()
    if re.fullmatch(r"20\d{2}", text):
        return text
    return text


def _parse_vietnamese_number(num_str: str) -> Optional[float]:
    """Parse Vietnamese formatted number (using dots as thousand separators or commas as decimals)."""
    if not num_str:
        return None
    cleaned = num_str.strip().rstrip("%").rstrip("xX×")
    # Case 1: Dot as thousand separator, comma as decimal (e.g. 3.022,50 or 34.100)
    if "." in cleaned and "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif "." in cleaned and len(cleaned.split(".")[-1]) == 3:
        # 34.100 -> 34100
        cleaned = cleaned.replace(".", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


#: Tokens that look like tickers but are not company codes.
#:
#: Roman numerals are how Vietnamese articles write quarters ("quý III").
#: Treating one as a ticker produces metrics like "III - Lợi nhuận sau
#: thuế", which then rank against the real figures. Listed companies such
#: as VND, VCB or SSI are left in, because a research query may target
#: them.
NON_TICKER_TOKENS = {
    # Roman numerals
    "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII",
    # Units and common abbreviations
    "USD", "EUR", "JPY", "CNY", "KRW",
    "Q1", "Q2", "Q3", "Q4", "YTD", "TTM", "EPS", "PE", "PB", "ROE", "ROA",
    "GDP", "CPI", "PPI", "LPR", "FED", "ECB", "IPO", "M&A", "VNPT", "BPS",
    "TVN", "HOSE", "HNX", "UPCOM", "OTC", "PHE", "APEC", "ASEAN", "G20",
}


#: A ticker is an all-caps token. Vietnamese articles also write tickers with
#: an exchange suffix, such as "HPG.HOSE" or "VIX:NYC".
_TICKER_IN_TEXT = re.compile(
    r"\b(?P<ticker>[A-Z]{2,5})(?:\.[A-Z]{2,5}|:[A-Z]{2,5})?\b",
    re.UNICODE,
)


def _has_qualifier(text: str, start: int, metric_end: int, raw_metric: str) -> bool:
    """Return True when a phrase that changes the metric meaning is present.

    The qualifier may sit right before the metric name, as in "doanh thu tài
    chính", or right after it, as in "doanh thu của doanh nghiệp". Only the
    characters around the match are checked, so an unrelated mention further
    down the paragraph does not reject the figure.
    """
    qualifiers = METRIC_QUALIFIER_PHRASES.get(raw_metric)
    if not qualifiers:
        return False

    left = max(0, start - 40)
    right = min(len(text), metric_end + 40)
    window = text[left:right].lower()
    return any(phrase in window for phrase in qualifiers)


def _ticker_near(text: str, start: int, end: int, window: int = 220) -> str:
    """Return the ticker closest to a span of text, or an empty string.

    The search looks in the sentence around the span, then in a wider
    window. Roman numerals, index codes and units are skipped.
    """
    left = max(0, start - window)
    right = min(len(text), end + window)
    segment = text[left:right]

    best: tuple[int, str] | None = None
    for match in _TICKER_IN_TEXT.finditer(segment):
        candidate = match.group(0).upper()
        if candidate in NON_TICKER_TOKENS:
            continue
        absolute = left + match.start()
        distance = abs(absolute - start)
        if best is None or distance < best[0]:
            best = (distance, candidate)
    return best[1] if best else ""


def _find_ticker(text: str) -> str:
    """Return the first real ticker in a string, or an empty string.

    Roman numerals, index codes, units and common abbreviations are skipped.
    A ticker is an all-caps token of 2 to 5 letters, optionally followed by
    a Vietnamese stock-exchange suffix.
    """
    for match in _TICKER_IN_TEXT.finditer(text or ""):
        candidate = match.group(0).upper()
        if candidate in NON_TICKER_TOKENS:
            continue
        return candidate
    return ""


def _is_target_fact(fact: "ExtractedMetric", target_set: set[str]) -> bool:
    """Keep a fact only if it is about one of the target tickers.

    A fact that names a different company is dropped. A fact with no ticker
    is kept, because prose about the target company usually has no ticker
    printed next to the number.
    """
    fact_ticker = (fact.ticker or "").upper()
    if not fact_ticker:
        return True
    return fact_ticker in target_set


class DeterministicRuleExtractor:
    """Zero-cost, sub-millisecond rule-based financial fact extractor."""

    def extract_from_chunk(
        self,
        chunk: Chunk,
        source_id: str,
        publisher_tier: int,
        source_title: str,
        source_url: str,
        default_ticker: str = "",
        query_periods: Optional[set[str]] = None,
    ) -> list[ExtractedMetric]:
        """Extract all financial facts from a single Chunk."""
        facts: list[ExtractedMetric] = []
        text = chunk.raw_content if chunk.raw_content else chunk.content

        # 1. Determine active ticker
        chunk_ticker = default_ticker
        detected = _find_ticker(text)
        if detected:
            chunk_ticker = detected

        # 2. Extract from Markdown Table if present
        if chunk.is_table or ("|---" in text or "|:---" in text):
            table_facts = self._extract_from_table(
                text=text,
                source_id=source_id,
                publisher_tier=publisher_tier,
                source_title=source_title,
                source_url=source_url,
                ticker=chunk_ticker,
            )
            facts.extend(table_facts)

        # 3. Extract from Prose
        prose_facts = self._extract_from_prose(
            text=text,
            source_id=source_id,
            publisher_tier=publisher_tier,
            source_title=source_title,
            source_url=source_url,
            ticker=chunk_ticker,
            query_periods=query_periods,
        )
        facts.extend(prose_facts)

        return facts

    def _extract_from_table(
        self,
        text: str,
        source_id: str,
        publisher_tier: int,
        source_title: str,
        source_url: str,
        ticker: str,
    ) -> list[ExtractedMetric]:
        facts: list[ExtractedMetric] = []
        lines = [line.strip() for line in text.splitlines() if line.strip().startswith("|")]
        if len(lines) < 3:
            return facts

        # Parse header row for fiscal periods
        header_cells = [c.strip() for c in lines[0].split("|")[1:-1]]
        periods_by_col: dict[int, str] = {}
        for col_idx, cell in enumerate(header_cells):
            detected_periods = extract_periods_from_text(cell)
            if detected_periods:
                periods_by_col[col_idx] = _normalize_period(detected_periods[0])
            elif "q" in cell.lower() or "năm" in cell.lower() or "tháng" in cell.lower():
                periods_by_col[col_idx] = _normalize_period(cell)

        # Parse data rows
        for line in lines[2:]:
            cells = [c.strip() for c in line.split("|")[1:-1]]
            if not cells:
                continue
            row_label = cells[0].lower()
            canonical_metric = None
            # Check longer keys first to prevent substring shadowing (e.g. 'biên lợi nhuận gộp' before 'lợi nhuận gộp')
            for key, name in sorted(METRIC_CANONICAL_MAP.items(), key=lambda x: len(x[0]), reverse=True):
                if key in row_label:
                    canonical_metric = name
                    break

            if not canonical_metric:
                continue

            # A row may name its own company. "VIX | Doanh thu thuần | 8.100"
            # must not be filed under the ticker of the article, so read the
            # row label for a ticker and use it when present.
            row_ticker = _find_ticker(cells[0]) or ticker

            for col_idx in range(1, len(cells)):
                if col_idx not in periods_by_col:
                    continue
                period = periods_by_col[col_idx]
                cell_val_str = cells[col_idx]
                num_val = _parse_vietnamese_number(cell_val_str)
                if num_val is None:
                    continue

                # Detect unit
                unit = "tỷ đồng"
                if "%" in cell_val_str or "biên" in canonical_metric.lower():
                    unit = "%"
                elif "eps" in canonical_metric.lower():
                    unit = "đồng/cp"
                elif "p/e" in canonical_metric.lower() or "p/b" in canonical_metric.lower():
                    unit = "lần"

                facts.append(
                    ExtractedMetric(
                        ticker=row_ticker,
                        metric_name=canonical_metric,
                        fiscal_period=period,
                        value=num_val,
                        unit=unit,
                        source_id=source_id,
                        publisher_tier=publisher_tier,
                        source_title=source_title,
                        source_url=source_url,
                        raw_snippet=f"{cells[0]} ({period}): {cell_val_str}",
                        confidence=0.98,
                    )
                )

        return facts

    def _extract_from_prose(
        self,
        text: str,
        source_id: str,
        publisher_tier: int,
        source_title: str,
        source_url: str,
        ticker: str,
        query_periods: Optional[set[str]] = None,
    ) -> list[ExtractedMetric]:
        facts: list[ExtractedMetric] = []
        local_periods = extract_periods_from_text(text)
        # A comparison label is not a fiscal period, so it must not become
        # the fallback period for figures that have no period of their own.
        real_periods = [p for p in local_periods if p not in COMPARISON_LABELS]
        default_period = (
            real_periods[0]
            if real_periods
            else (list(query_periods)[0] if query_periods else "")
        )

        # Period lookup by position, so a figure is labelled with the period
        # that sits nearest to it. A single period for the whole chunk would
        # label every figure with the first period found, which puts a 2025
        # number under 2024.
        period_positions = sorted(
            (m.start(), _normalize_period(m.group(0)))
            for m in _PERIOD_IN_TEXT.finditer(text)
            if m.group(0).lower() not in COMPARISON_LABELS
        )

        # A quarter written as "quý III" does not say which year it belongs
        # to. The year usually sits in the title or in another part of the
        # document, so use that when the quarter has no year of its own.
        doc_year = ""
        for candidate in (source_title or "", text):
            year_match = re.search(r"20\d{2}", candidate or "")
            if year_match:
                doc_year = year_match.group(0)
                break

        def _period_for(position: int) -> str:
            """Return the period closest to a position.

            Only periods in the same sentence are considered. A figure on
            one line must not take the period of a figure on another line,
            because a report that lists several quarters puts a period label
            next to each of them.
            """
            line_start = text.rfind("\n", 0, position) + 1
            line_end = text.find("\n", position)
            if line_end == -1:
                line_end = len(text)

            best: tuple[int, str] | None = None
            for pos, label in period_positions:
                if pos < line_start or pos > line_end:
                    continue
                distance = abs(pos - position)
                if best is None or distance < best[0]:
                    best = (distance, label)
            if best is not None:
                return _with_year(best[1], doc_year)
            return _with_year(default_period, doc_year)

        # A figure can be written with the metric name first ("doanh thu đạt
        # 34.000 tỷ") or with the figure first ("34.000 tỷ đồng doanh thu").
        # Both are collected here and the ones already covered by the first
        # pattern are dropped, so a sentence never yields the same number
        # twice.
        covered: list[tuple[int, int]] = [
            (m.start(), m.end()) for m in PROSE_FACT_PATTERN.finditer(text)
        ]

        def _already_covered(start: int, end: int) -> bool:
            return any(start >= s and end <= e for s, e in covered)

        for match in PROSE_FACT_PATTERN.finditer(text):
            raw_metric = match.group("metric").strip().lower()
            val_str = match.group("val").strip()
            unit_str = match.group("unit") or ""
            canonical_name = METRIC_CANONICAL_MAP.get(raw_metric, raw_metric.title())

            num_val = _parse_vietnamese_number(val_str)
            if num_val is None:
                continue

            # "doanh thu tài chính" is financial income, not net revenue.
            # Reject it when the phrase that changes the meaning sits next
            # to the metric name.
            if _has_qualifier(text, match.start(), match.end("metric"), raw_metric):
                continue

            # A market round-up article mentions many companies. The ticker
            # that sits closest to the figure is the company it measures,
            # not the first ticker in the chunk. Look inside the sentence
            # around the match first, then widen to the chunk.
            fact_ticker = _ticker_near(text, match.start(), match.end()) or ticker

            # Standardize unit
            unit = unit_str.strip()
            if not unit:
                if "biên" in canonical_name.lower():
                    unit = "%"
                elif "p/e" in canonical_name.lower() or "p/b" in canonical_name.lower():
                    unit = "lần"
                else:
                    unit = "tỷ đồng"

            period = _period_for(match.start())
            snippet_start = max(0, match.start() - 30)
            snippet_end = min(len(text), match.end() + 30)
            snippet = text[snippet_start:snippet_end].replace("\n", " ").strip()

            facts.append(
                ExtractedMetric(
                    ticker=fact_ticker,
                    metric_name=canonical_name,
                    fiscal_period=period,
                    value=num_val,
                    unit=unit,
                    source_id=source_id,
                    publisher_tier=publisher_tier,
                    source_title=source_title,
                    source_url=source_url,
                    raw_snippet=snippet,
                    confidence=0.90,
                )
            )

        for match in PROSE_FACT_PATTERN_REVERSED.finditer(text):
            raw_metric = match.group("metric").strip().lower()
            val_str = match.group("val").strip()
            unit_str = match.group("unit") or ""
            canonical_name = METRIC_CANONICAL_MAP.get(raw_metric, raw_metric.title())

            num_val = _parse_vietnamese_number(val_str)
            if num_val is None:
                continue

            if _already_covered(match.start(), match.end()):
                continue

            if _has_qualifier(text, match.start("metric"), match.end("metric"), raw_metric):
                continue

            fact_ticker = _ticker_near(text, match.start(), match.end()) or ticker
            period = _period_for(match.start())
            snippet_start = max(0, match.start() - 30)
            snippet_end = min(len(text), match.end() + 30)
            snippet = text[snippet_start:snippet_end].replace("\n", " ").strip()

            facts.append(
                ExtractedMetric(
                    ticker=fact_ticker,
                    metric_name=canonical_name,
                    fiscal_period=period,
                    value=num_val,
                    unit=unit_str.strip() or "tỷ đồng",
                    source_id=source_id,
                    publisher_tier=publisher_tier,
                    source_title=source_title,
                    source_url=source_url,
                    raw_snippet=snippet,
                    confidence=0.85,
                )
            )

        return facts


class MapExtractor:
    """Coordinator for parallel extraction across multiple PrunedDocuments."""

    def __init__(self, rule_extractor: Optional[DeterministicRuleExtractor] = None) -> None:
        self.rule_extractor = rule_extractor or DeterministicRuleExtractor()

    async def extract_facts(
        self,
        docs: Sequence[PrunedDocument],
        query: str,
        target_tickers: Optional[list[str]] = None,
    ) -> list[ExtractedMetric]:
        """Run parallel extraction on all pruned documents.

        Args:
            docs: List of PrunedDocument instances.
            query: Research query string.
            target_tickers: Known target ticker symbols.

        Returns:
            Flat list of ExtractedMetric instances tagged by source_id.
        """
        if not docs:
            return []

        query_tickers = target_tickers or extract_tickers_from_query(query)
        default_ticker = query_tickers[0] if query_tickers else ""
        query_periods = set(extract_periods_from_text(query))
        # Only filter when the user named specific tickers. A generic query
        # has no target, so every company mentioned stays in the result.
        target_set = {t.upper() for t in query_tickers if t}

        async def _extract_doc(doc: PrunedDocument) -> list[ExtractedMetric]:
            doc_facts: list[ExtractedMetric] = []
            for chunk in doc.selected_chunks:
                chunk_facts = self.rule_extractor.extract_from_chunk(
                    chunk=chunk,
                    source_id=doc.source_id,
                    publisher_tier=doc.publisher_tier,
                    source_title=doc.title,
                    source_url=doc.url,
                    default_ticker=default_ticker,
                    query_periods=query_periods,
                )
                doc_facts.extend(chunk_facts)
            return doc_facts

        # Execute extraction across documents concurrently
        tasks = [_extract_doc(d) for d in docs]
        results = await asyncio.gather(*tasks)

        all_facts: list[ExtractedMetric] = []
        for r in results:
            all_facts.extend(r)

        if target_set:
            all_facts = [f for f in all_facts if _is_target_fact(f, target_set)]

        return all_facts
