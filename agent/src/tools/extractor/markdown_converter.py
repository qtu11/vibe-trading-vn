"""High-Fidelity Markdown and Table Engine.

Converts sanitized HTML to GitHub Flavored Markdown (GFM):
- High-fidelity table engine with alignment (:--- for text, ---: for numeric/percentage)
- Full support for colspan and rowspan without breaking grid layout
- Strict preservation of Vietnamese financial numbers (15.200 tỷ, 1.234,5 triệu) and reporting periods (Q3/2024, YTD, YoY)
- Metadata extraction (title, publisher, author, published date, canonical URL)
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlparse

import lxml.html

logger = logging.getLogger(__name__)

# Strict regex matching Vietnamese and international financial figures
# e.g., 15.200 tỷ, 1.234,5 triệu, +21,7%, -5.2%, (1.200), 2.850 VND, -, N/A
FINANCIAL_NUMBER_PATTERN = re.compile(
    r"^[\+\-]?\s*\(?\s*[\$€₫]?\s*(?:[\d\.\,]+\s*(?:tỷ|tỉ|triệu|nghìn|ngàn|tr|t|%|VND|USD|đồng)?|N/?A|-{1,2})\s*\)?%?$",
    re.IGNORECASE,
)

# Known reporting periods to explicitly keep as textual headers
REPORTING_PERIOD_PATTERN = re.compile(
    r"^(?:Q[1-4](?:/\d{2,4})?|YTD|YoY|MoM|QoQ|TTM|\d{1,2}T(?:/\d{2,4})?|Năm\s*\d{4}|\d{4}|Kế\s*hoạch|Ước\s*tính|Dự\s*phóng)$",
    re.IGNORECASE,
)


def is_financial_number(val: str) -> bool:
    """Check if a table cell value represents a numeric/financial metric or percentage."""
    s = val.strip()
    if not s:
        return False
    # Explicitly check reporting periods: they are column/row labels, not numeric figures
    if REPORTING_PERIOD_PATTERN.match(s):
        return False
    return bool(FINANCIAL_NUMBER_PATTERN.match(s))


class MarkdownConverter:
    """High-Fidelity HTML-to-Markdown Converter with GFM Table Engine."""

    def __init__(self) -> None:
        pass

    def convert(self, html_str: str, metadata: dict[str, Any] | None = None) -> str:
        """Convert sanitized HTML into clean GitHub Flavored Markdown (GFM)."""
        if not html_str or not html_str.strip():
            return ""

        # Wrap in a root div so fragment_fromstring can parse arbitrary HTML blocks
        wrapped_html = f"<div>{html_str}</div>"
        try:
            root = lxml.html.fragment_fromstring(wrapped_html)
        except Exception:
            try:
                root = lxml.html.document_fromstring(html_str)
            except Exception as e:
                logger.warning("Failed to parse HTML for Markdown conversion: %s", e)
                return html_str.strip()

        md_output = self._convert_element(root)

        # Normalize consecutive blank lines to maximum 2 newlines
        md_output = re.sub(r"\n{3,}", "\n\n", md_output).strip()
        return md_output

    def _convert_element(self, element: lxml.html.HtmlElement) -> str:
        """Recursively convert an lxml element tree to Markdown."""
        parts: list[str] = []

        for child in element.iterchildren():
            tag = child.tag.lower() if isinstance(child.tag, str) else ""

            if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
                level = int(tag[1])
                heading_text = self._convert_inlines(child).strip()
                if heading_text:
                    parts.append(f"{'#' * level} {heading_text}\n\n")

            elif tag == "p":
                p_text = self._convert_inlines(child).strip()
                if p_text:
                    parts.append(f"{p_text}\n\n")

            elif tag == "table":
                table_md = self._convert_table_to_gfm(child)
                if table_md.strip():
                    parts.append(f"{table_md}\n\n")

            elif tag == "ul":
                list_md = self._convert_list(child, ordered=False)
                if list_md.strip():
                    parts.append(f"{list_md}\n\n")

            elif tag == "ol":
                list_md = self._convert_list(child, ordered=True)
                if list_md.strip():
                    parts.append(f"{list_md}\n\n")

            elif tag == "blockquote":
                quote_text = self._convert_inlines(child).strip()
                if quote_text:
                    lines = [f"> {line}" for line in quote_text.splitlines()]
                    parts.append("\n".join(lines) + "\n\n")

            elif tag == "pre":
                code_text = child.text_content().strip()
                if code_text:
                    parts.append(f"```\n{code_text}\n```\n\n")

            elif tag == "hr":
                parts.append("---\n\n")

            elif tag in ("div", "section", "article", "main", "body"):
                # Nested structural container
                nested_md = self._convert_element(child)
                if nested_md.strip():
                    parts.append(f"{nested_md}\n\n")

            else:
                # Other elements: fallback to inline text
                inline_text = self._convert_inlines(child).strip()
                if inline_text:
                    parts.append(f"{inline_text}\n\n")

        # If element had no child elements, return its text content directly
        if not parts and element.text_content().strip():
            return element.text_content().strip()

        return "".join(parts)

    def _convert_inlines(self, element: lxml.html.HtmlElement) -> str:
        """Convert inline tags (strong, em, a, code, br) to Markdown."""
        parts: list[str] = []

        if element.text:
            parts.append(element.text)

        for child in element.iterchildren():
            tag = child.tag.lower() if isinstance(child.tag, str) else ""

            if tag in ("strong", "b"):
                inner = self._convert_inlines(child)
                parts.append(f"**{inner}**")
            elif tag in ("em", "i"):
                inner = self._convert_inlines(child)
                parts.append(f"*{inner}*")
            elif tag == "code":
                inner = child.text_content()
                parts.append(f"`{inner}`")
            elif tag == "a":
                href = child.attrib.get("href", "").strip()
                inner = self._convert_inlines(child).strip()
                if href and inner and not href.startswith("javascript:"):
                    parts.append(f"[{inner}]({href})")
                elif inner:
                    parts.append(inner)
            elif tag == "br":
                parts.append("\n")
            else:
                parts.append(self._convert_inlines(child))

            if child.tail:
                parts.append(child.tail)

        text = "".join(parts)
        # Collapse spaces within inline runs
        return re.sub(r"[ \t]+", " ", text)

    def _convert_list(self, list_el: lxml.html.HtmlElement, ordered: bool = False, depth: int = 0) -> str:
        """Convert <ul> and <ol> list hierarchies to indented Markdown lists."""
        lines: list[str] = []
        indent = "  " * depth
        idx = 1

        for li in list_el.xpath("./li"):
            prefix = f"{idx}. " if ordered else "- "
            idx += 1

            # Extract direct inline text of this li
            li_parts: list[str] = []
            if li.text:
                li_parts.append(li.text.strip())

            nested_lists: list[lxml.html.HtmlElement] = []
            for child in li.iterchildren():
                tag = child.tag.lower() if isinstance(child.tag, str) else ""
                if tag in ("ul", "ol"):
                    nested_lists.append(child)
                else:
                    li_parts.append(self._convert_inlines(child))
                if child.tail:
                    li_parts.append(child.tail.strip())

            item_text = " ".join(" ".join(li_parts).split())
            lines.append(f"{indent}{prefix}{item_text}")

            for nested in nested_lists:
                nested_md = self._convert_list(nested, ordered=(nested.tag.lower() == "ol"), depth=depth + 1)
                lines.append(nested_md)

        return "\n".join(lines)

    def _convert_table_to_gfm(self, table_el: lxml.html.HtmlElement) -> str:
        """Convert HTML <table> into standard GitHub Flavored Markdown (GFM).

        Guarantees:
        - 2D grid normalization supporting colspan and rowspan without broken layouts.
        - Textual columns aligned left (:---), numeric/percentage aligned right (---:).
        - Strict preservation of Vietnamese financial numbers (15.200 tỷ, 1.234,5 triệu).
        - Pipes inside cells escaped as \\|.
        """
        # Collect rows in document order across thead, tbody, direct tr, and tfoot
        rows: list[lxml.html.HtmlElement] = []
        thead = table_el.xpath("./thead")
        tbody = table_el.xpath("./tbody")
        tfoot = table_el.xpath("./tfoot")

        if thead or tbody or tfoot:
            for th in thead:
                rows.extend(th.xpath("./tr"))
            for tb in tbody:
                rows.extend(tb.xpath("./tr"))
            rows.extend(table_el.xpath("./tr"))
            for tf in tfoot:
                rows.extend(tf.xpath("./tr"))
        else:
            rows = table_el.xpath(".//tr")

        if not rows:
            return ""

        # 2D Grid mapping: grid[row_idx][col_idx] = text
        grid: list[list[str]] = []
        occupied: set[tuple[int, int]] = set()
        row_idx = 0

        for tr in rows:
            while len(grid) <= row_idx:
                grid.append([])

            col_idx = 0
            cells = tr.xpath("./th | ./td")
            for cell in cells:
                while (row_idx, col_idx) in occupied:
                    col_idx += 1

                colspan = 1
                rowspan = 1
                if "colspan" in cell.attrib:
                    try:
                        colspan = max(1, int(cell.attrib["colspan"]))
                    except ValueError:
                        colspan = 1
                if "rowspan" in cell.attrib:
                    try:
                        rowspan = max(1, int(cell.attrib["rowspan"]))
                    except ValueError:
                        rowspan = 1

                cell_text = self._clean_table_cell(cell)

                for r_offset in range(rowspan):
                    target_r = row_idx + r_offset
                    while len(grid) <= target_r:
                        grid.append([])
                    for c_offset in range(colspan):
                        target_c = col_idx + c_offset
                        occupied.add((target_r, target_c))
                        while len(grid[target_r]) <= target_c:
                            grid[target_r].append("")

                        if r_offset == 0 and c_offset == 0:
                            grid[target_r][target_c] = cell_text
                        else:
                            # Fill spanned cells with empty placeholder to maintain rectangular grid
                            grid[target_r][target_c] = ""

                col_idx += colspan
            row_idx += 1

        # Normalize grid to uniform width
        max_cols = max((len(r) for r in grid), default=0)
        if max_cols == 0:
            return ""

        for r in grid:
            while len(r) < max_cols:
                r.append("")

        # Filter out empty rows
        grid = [r for r in grid if any(cell.strip() for cell in r)]
        if not grid:
            return ""

        # Determine alignment for each column
        alignments: list[str] = []
        for c in range(max_cols):
            # Look at data rows (from row 1 onwards)
            data_cells = [grid[r][c].strip() for r in range(1, len(grid)) if grid[r][c].strip()]
            if not data_cells:
                data_cells = [grid[0][c].strip()] if grid[0][c].strip() else []

            numeric_matches = sum(1 for val in data_cells if is_financial_number(val))
            if data_cells and (numeric_matches / len(data_cells)) >= 0.5:
                alignments.append("---:")  # Right aligned for numbers, percentages, currencies
            else:
                alignments.append(":---")  # Left aligned for text and labels

        # Format rows into Markdown GFM table
        lines: list[str] = []
        # Header row
        header_row = "| " + " | ".join(grid[0]) + " |"
        lines.append(header_row)

        # Alignment separator row
        sep_row = "|" + "|".join(alignments) + "|"
        lines.append(sep_row)

        # Data rows
        for r in grid[1:]:
            data_row = "| " + " | ".join(r) + " |"
            lines.append(data_row)

        return "\n" + "\n".join(lines) + "\n"

    def _clean_table_cell(self, cell: lxml.html.HtmlElement) -> str:
        """Extract and clean cell text preserving Vietnamese financial figures and escaping pipes."""
        # Convert inlines (handles <strong>, <em>, etc.)
        raw_text = self._convert_inlines(cell)
        # Collapse internal newlines and whitespace into single spaces
        clean_text = " ".join(raw_text.split())
        # Escape pipe character to prevent breaking GFM table layout
        clean_text = clean_text.replace("|", r"\|")
        return clean_text.strip()


def extract_metadata(html_str: str, base_url: str = "") -> dict[str, Any]:
    """Helper to extract article metadata from HTML."""
    from src.tools.extractor.dom_cleaner import DOMCleaner
    cleaner = DOMCleaner()
    res = cleaner.clean(html_str, base_url=base_url)
    return res.metadata
