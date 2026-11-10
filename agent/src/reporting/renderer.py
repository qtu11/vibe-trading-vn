"""Create an editable brand-controlled DOCX and a visually equivalent PDF.

The renderer owns every design decision: page geometry, colour, type scale,
column widths, charts and the rating furniture. The AI supplies content only
(values, labels, periods, commentary) through the :mod:`src.reporting.schema`
contract, so a report can never smuggle layout instructions into the document.

Layout follows the masthead grammar of Vietnamese broker research: a white
masthead with the mark on the left, a signal rule, a metric-card band, a
two-column summary with a stock-information rail, boxed thesis/risk callouts,
a multi-period financial table and a price/volume chart.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.dates import DateFormatter
from matplotlib.figure import Figure
from matplotlib.patches import FancyBboxPatch
from matplotlib.ticker import MaxNLocator
from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Inches, Pt, RGBColor

from src.reporting.brand import BRAND, resolve_brand_logo
from src.reporting.citations import apa_reference_suffix, datum_source_ids, datum_sources, reference_sources
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from src.reporting.schema import (
    Catalyst,
    ChartSeries,
    Claim,
    ComparisonTable,
    DatumEvidence,
    FinancialTable,
    KeyStat,
    Metric,
    NarrativeSection,
    PeriodPoint,
    RatingBand,
    ResearchReport,
    SensitivityTable,
)

#: Usable text width on A4 with 1.7 cm side margins.
CONTENT_W = 17.4

#: Vietnamese precomposed glyphs are covered by Arial/Liberation Sans. Charts
#: use DejaVu Sans, which ships with matplotlib and also covers Vietnamese.
CHART_FONT = "DejaVu Sans"

_UNIT_LABELS = {
    "VND": "đ",
    "tỷ VND": "tỷ đồng",
    "tỷ đồng": "tỷ đồng",
    "triệu VND": "triệu đồng",
    "%": "%",
    "x": "x",
}

_SOURCE_STATUS = {
    "verified": "Đã xác minh",
    "user_supplied": "Người dùng cung cấp",
    "unverified": "Chưa xác minh",
    "simulated": "Dữ liệu mô phỏng",
}

_STATUS_LABELS = {
    "certified": "Báo cáo chính thức",
    "draft_unverified": "Dự thảo · chưa phê duyệt",
    "simulated_demo": "Bản minh họa",
}


# ---------------------------------------------------------------------------
# Low-level XML helpers
# ---------------------------------------------------------------------------

_PPR_SEQ = (
    "w:pStyle", "w:keepNext", "w:keepLines", "w:pageBreakBefore", "w:framePr",
    "w:widowControl", "w:numPr", "w:suppressLineNumbers", "w:pBdr", "w:shd",
    "w:tabs", "w:suppressAutoHyphens", "w:kinsoku", "w:wordWrap",
    "w:overflowPunct", "w:topLinePunct", "w:autoSpaceDE", "w:autoSpaceDN",
    "w:bidi", "w:adjustRightInd", "w:snapToGrid", "w:spacing", "w:ind",
    "w:contextualSpacing", "w:mirrorIndents", "w:suppressOverlap", "w:jc",
    "w:textDirection", "w:textAlignment", "w:textboxTightWrap",
    "w:outlineLvl", "w:divId", "w:cnfStyle", "w:rPr", "w:sectPr",
    "w:pPrChange",
)

_RPR_SEQ = (
    "w:rStyle", "w:rFonts", "w:b", "w:bCs", "w:i", "w:iCs", "w:caps",
    "w:smallCaps", "w:strike", "w:dstrike", "w:outline", "w:shadow",
    "w:emboss", "w:imprint", "w:noProof", "w:snapToGrid", "w:vanish",
    "w:webHidden", "w:color", "w:spacing", "w:w", "w:kern", "w:position",
    "w:sz", "w:szCs", "w:highlight", "w:u", "w:effect", "w:bdr", "w:shd",
    "w:fitText", "w:vertAlign", "w:rtl", "w:cs", "w:em", "w:lang",
    "w:eastAsianLayout", "w:specVanish", "w:oMath",
)

_TCPR_SEQ = (
    "w:cnfStyle", "w:tcW", "w:gridSpan", "w:hMerge", "w:vMerge",
    "w:tcBorders", "w:shd", "w:noWrap", "w:tcMar", "w:textDirection",
    "w:tcFitText", "w:vAlign", "w:hideMark", "w:headers", "w:cellIns",
    "w:cellDel", "w:cellMerge", "w:tcPrChange",
)

_TRPR_SEQ = (
    "w:cnfStyle", "w:divId", "w:gridBefore", "w:gridAfter", "w:wBefore",
    "w:wAfter", "w:cantSplit", "w:trHeight", "w:tblHeader",
    "w:tblCellSpacing", "w:jc", "w:hidden", "w:ins", "w:del",
    "w:trPrChange",
)

_TBLPR_SEQ = (
    "w:tblStyle", "w:tblpPr", "w:tblOverlap", "w:bidiVisual",
    "w:tblStyleRowBandSize", "w:tblStyleColBandSize", "w:tblW", "w:jc",
    "w:tblCellSpacing", "w:tblInd", "w:tblBorders", "w:shd", "w:tblLayout",
    "w:tblCellMar", "w:tblLook", "w:tblCaption", "w:tblDescription",
)

_TBORDER_SEQ = (
    "w:top", "w:left", "w:bottom", "w:right", "w:insideH", "w:insideV",
    "w:tl2br", "w:tr2bl",
)


def _insert_ordered(parent, element, sequence: tuple[str, ...]):
    """Insert *element* into *parent* honouring the OOXML child order."""
    order = {qn(tag): index for index, tag in enumerate(sequence)}
    target = order.get(element.tag, len(sequence))
    for child in parent:
        if order.get(child.tag, len(sequence)) > target:
            child.addprevious(element)
            return element
    parent.append(element)
    return element


def rgb(hex_color: str) -> RGBColor:
    return RGBColor.from_string(hex_color)


def shade(cell, fill: str):
    """Paint a table cell background, replacing any previous fill."""
    tc_pr = cell._tc.get_or_add_tcPr()
    existing = tc_pr.find(qn("w:shd"))
    if existing is not None:
        tc_pr.remove(existing)
    node = OxmlElement("w:shd")
    node.set(qn("w:val"), "clear")
    node.set(qn("w:color"), "auto")
    node.set(qn("w:fill"), fill)
    _insert_ordered(tc_pr, node, _TCPR_SEQ)


def cell_border(cell, edge: str = "bottom", color: str = BRAND.line, size: int = 6):
    """Draw one edge of a cell border. *size* is in eighths of a point."""
    tc_pr = cell._tc.get_or_add_tcPr()
    borders = tc_pr.find(qn("w:tcBorders"))
    if borders is None:
        borders = OxmlElement("w:tcBorders")
        _insert_ordered(tc_pr, borders, _TCPR_SEQ)
    existing = borders.find(qn(f"w:{edge}"))
    if existing is not None:
        borders.remove(existing)
    node = OxmlElement(f"w:{edge}")
    node.set(qn("w:val"), "single")
    node.set(qn("w:sz"), str(size))
    node.set(qn("w:space"), "0")
    node.set(qn("w:color"), color)
    _insert_ordered(borders, node, _TBORDER_SEQ)


def no_borders(table):
    """Clear every table-level border so only explicit cell edges show."""
    tbl_pr = table._tbl.tblPr
    existing = tbl_pr.find(qn("w:tblBorders"))
    if existing is not None:
        tbl_pr.remove(existing)
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        node = OxmlElement(f"w:{edge}")
        node.set(qn("w:val"), "nil")
        borders.append(node)
    _insert_ordered(tbl_pr, borders, _TBLPR_SEQ)


def set_cell_margins(cell, top=120, start=140, bottom=120, end=140):
    tc_pr = cell._tc.get_or_add_tcPr()
    margins = tc_pr.find(qn("w:tcMar"))
    if margins is None:
        margins = OxmlElement("w:tcMar")
        _insert_ordered(tc_pr, margins, _TCPR_SEQ)
    for tag, val in (("top", top), ("left", start), ("bottom", bottom), ("right", end)):
        node = margins.find(qn(f"w:{tag}"))
        if node is None:
            node = OxmlElement(f"w:{tag}")
            margins.append(node)
        node.set(qn("w:w"), str(val))
        node.set(qn("w:type"), "dxa")


def row_flags(row, *, header: bool = False, no_split: bool = True):
    tr_pr = row._tr.get_or_add_trPr()
    if no_split and tr_pr.find(qn("w:cantSplit")) is None:
        _insert_ordered(tr_pr, OxmlElement("w:cantSplit"), _TRPR_SEQ)
    if header and tr_pr.find(qn("w:tblHeader")) is None:
        _insert_ordered(tr_pr, OxmlElement("w:tblHeader"), _TRPR_SEQ)


def para_rule(paragraph, color: str = BRAND.line, size: int = 8, edge: str = "bottom"):
    """Draw a rule on a paragraph edge (used for masthead and section rules)."""
    p_pr = paragraph._p.get_or_add_pPr()
    borders = p_pr.find(qn("w:pBdr"))
    if borders is None:
        borders = OxmlElement("w:pBdr")
        _insert_ordered(p_pr, borders, _PPR_SEQ)
    existing = borders.find(qn(f"w:{edge}"))
    if existing is not None:
        borders.remove(existing)
    node = OxmlElement(f"w:{edge}")
    node.set(qn("w:val"), "single")
    node.set(qn("w:sz"), str(size))
    node.set(qn("w:space"), "4")
    node.set(qn("w:color"), color)
    order = {qn(tag): i for i, tag in enumerate(("w:top", "w:left", "w:bottom", "w:right", "w:between", "w:bar"))}
    target = order.get(node.tag, 0)
    for child in borders:
        if order.get(child.tag, 0) > target:
            child.addprevious(node)
            return
    borders.append(node)


def p_text(
    paragraph,
    text: str,
    *,
    size: float = 9,
    color: str | None = None,
    bold: bool = False,
    italic: bool = False,
    font: str | None = None,
    spacing: int | None = None,
):
    """Add a run with the full font stack: Latin, East Asian and complex script."""
    run = paragraph.add_run(text)
    run.bold = bold
    run.italic = italic
    run.font.size = Pt(size)
    run.font.color.rgb = rgb(color or BRAND.ink)
    face = font or BRAND.font
    run.font.name = face
    r_pr = run._r.get_or_add_rPr()
    r_fonts = r_pr.find(qn("w:rFonts"))
    if r_fonts is None:  # pragma: no cover - python-docx always creates it
        r_fonts = OxmlElement("w:rFonts")
        _insert_ordered(r_pr, r_fonts, _RPR_SEQ)
    r_fonts.set(qn("w:ascii"), face)
    r_fonts.set(qn("w:hAnsi"), face)
    r_fonts.set(qn("w:eastAsia"), BRAND.font_cjk)
    r_fonts.set(qn("w:cs"), face)
    lang = OxmlElement("w:lang")
    lang.set(qn("w:val"), BRAND.locale)
    lang.set(qn("w:eastAsia"), "zh-CN")
    lang.set(qn("w:bidi"), "ar-SA")
    _insert_ordered(r_pr, lang, _RPR_SEQ)
    return run


def append_source_links(paragraph, item, *, full_url=False):
    """Put a real external source URL immediately after a value or paragraph."""
    report = getattr(paragraph.part, "_research_report", None)
    if report is None:
        return
    kind = getattr(item, "evidence_kind", "cited")
    if kind in ("derived", "assumption"):
        p_text(paragraph, " [suy ra]" if kind == "derived" else " [giả định]", size=6.2, color=BRAND.muted)
    for source in datum_sources(report, item):
        link = OxmlElement("w:hyperlink")
        link.set(qn("r:id"), paragraph.part.relate_to(str(source.url), RT.HYPERLINK, is_external=True))
        run = OxmlElement("w:r")
        props = OxmlElement("w:rPr")
        color = OxmlElement("w:color")
        color.set(qn("w:val"), BRAND.crimson)
        size = OxmlElement("w:sz")
        size.set(qn("w:val"), "12")
        props.extend([color, size])
        run.append(props)
        text = OxmlElement("w:t")
        text.set(qn("xml:space"), "preserve")
        text.text = f" {source.url}" if full_url else f" [{source.id}]"
        run.append(text)
        link.append(run)
        paragraph._p.append(link)


def set_para_spacing(paragraph, before=0, after=0, line=1.18):
    fmt = paragraph.paragraph_format
    fmt.space_before = Pt(before)
    fmt.space_after = Pt(after)
    fmt.line_spacing = line


def field_run(paragraph, instruction: str, placeholder: str = "1", **kwargs):
    """Insert a Word field (PAGE, NUMPAGES) with a cached placeholder."""
    run = p_text(paragraph, "", **kwargs)
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = f" {instruction} "
    sep = OxmlElement("w:fldChar")
    sep.set(qn("w:fldCharType"), "separate")
    cached = OxmlElement("w:t")
    cached.text = placeholder
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    for node in (begin, instr, sep, cached, end):
        run._r.append(node)
    return run


# ---------------------------------------------------------------------------
# Number formatting (vi-VN)
# ---------------------------------------------------------------------------


def fmt_number(value: float, decimals: int = 0) -> str:
    """Format with dots for thousands and commas for decimals: 138.500, 27,8."""
    text = f"{abs(float(value)):,.{decimals}f}"
    text = text.replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    return ("−" if value < 0 else "") + text


def fmt_signed(value: float, decimals: int | None = None) -> str:
    if decimals is None:
        decimals = 0 if abs(value) >= 100 or float(value).is_integer() else 1
    sign = "+" if value >= 0 else "−"
    return sign + fmt_number(abs(value), decimals)


def unit_label(unit: str) -> str:
    return _UNIT_LABELS.get(unit, unit)


def display_metric(metric: Metric) -> str:
    if metric.value is None:
        return "N/A"
    text = fmt_number(metric.value, metric.decimals)
    if metric.unit == "%":
        return f"{text}%"
    label = unit_label(metric.unit)
    return f"{text} {label}".strip()


def metric_headline(metric: Metric) -> str:
    """Return the big number; the unit belongs on the caption line."""
    if metric.value is None:
        return "N/A"
    text = fmt_number(metric.value, metric.decimals)
    return f"{text}%" if metric.unit == "%" else text


def metric_tone(metric: Metric) -> str:
    if metric.change_tone == "positive":
        return BRAND.green
    if metric.change_tone == "negative":
        return BRAND.red
    if metric.change_tone == "neutral":
        return BRAND.muted
    return BRAND.green if (metric.change or 0) >= 0 else BRAND.red


def metric_caption(metric: Metric) -> tuple[str, str]:
    """Return (caption, tone colour) for a metric card."""
    parts: list[str] = []
    if metric.unit and metric.unit != "%":
        parts.append(unit_label(metric.unit))
    if metric.change is not None:
        decimals = 0 if abs(metric.change) >= 100 else 1
        parts.append(
            f"{fmt_signed(metric.change, decimals)}{metric.change_unit} {metric.change_period}".strip()
        )
        return " · ".join(parts), metric_tone(metric)
    if metric.note:
        parts.append(metric.note)
    return " · ".join(parts), BRAND.muted


def select_featured(metrics: list[Metric], limit: int = 5) -> list[Metric]:
    chosen: list[Metric] = []
    seen: set[int] = set()
    for metric in metrics:
        if metric.featured and metric.value is not None:
            chosen.append(metric)
            seen.add(id(metric))
    for metric in metrics:
        if len(chosen) >= limit:
            break
        if id(metric) in seen or metric.value is None:
            continue
        chosen.append(metric)
        seen.add(id(metric))
    return chosen[:limit]


# ---------------------------------------------------------------------------
# Document scaffolding
# ---------------------------------------------------------------------------


def fixed_table(document, widths_cm: list[float]):
    """A borderless table with fixed geometry, one column per width."""
    table = document.add_table(rows=0, cols=len(widths_cm))
    table.autofit = False
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    try:
        table.style = document.styles["Normal Table"]
    except KeyError:  # pragma: no cover - custom templates
        pass
    no_borders(table)
    tbl_pr = table._tbl.tblPr
    margins = OxmlElement("w:tblCellMar")
    for tag, val in (("top", 0), ("left", 0), ("bottom", 0), ("right", 0)):
        node = OxmlElement(f"w:{tag}")
        node.set(qn("w:w"), str(val))
        node.set(qn("w:type"), "dxa")
        margins.append(node)
    _insert_ordered(tbl_pr, margins, _TBLPR_SEQ)
    for index, width in enumerate(widths_cm):
        table.columns[index].width = Cm(width)
    return table


def add_row(table, widths_cm: list[float]):
    row = table.add_row()
    for cell, width in zip(row.cells, widths_cm):
        cell.width = Cm(width)
        cell.vertical_alignment = WD_ALIGN_VERTICAL.TOP
    return row


def body_par(container, *, align=WD_ALIGN_PARAGRAPH.JUSTIFY, before=0, after=4, line=1.26):
    paragraph = container.add_paragraph()
    paragraph.alignment = align
    set_para_spacing(paragraph, before=before, after=after, line=line)
    return paragraph


# pyrefly: ignore[not-a-type]
def setup_document() -> Document:
    document = Document()
    section = document.sections[0]
    section.page_width = Cm(21)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(1.75)
    section.bottom_margin = Cm(1.65)
    section.left_margin = Cm(1.7)
    section.right_margin = Cm(1.7)
    section.header_distance = Cm(0.85)
    section.footer_distance = Cm(0.8)
    # A research cover carries its own masthead; running furniture starts p.2.
    section.different_first_page_header_footer = True

    styles = document.styles
    base = styles["Normal"]
    # pyrefly: ignore[missing-attribute]
    base.font.name = BRAND.font
    # pyrefly: ignore[missing-attribute]
    # pyrefly: ignore[missing-attribute]
    base.font.size = Pt(9)
    # pyrefly: ignore[missing-attribute]
    base.font.color.rgb = rgb(BRAND.ink)
    # pyrefly: ignore[missing-attribute]
    base.paragraph_format.line_spacing = 1.18
    # pyrefly: ignore[missing-attribute]
    base.paragraph_format.space_after = Pt(3)
    base_element = base.element
    r_pr = base_element.get_or_add_rPr()
    r_fonts = r_pr.find(qn("w:rFonts"))
    if r_fonts is not None:
        r_fonts.set(qn("w:eastAsia"), BRAND.font_cjk)
        r_fonts.set(qn("w:cs"), BRAND.font)
    lang = OxmlElement("w:lang")
    lang.set(qn("w:val"), BRAND.locale)
    lang.set(qn("w:eastAsia"), "zh-CN")
    _insert_ordered(r_pr, lang, _RPR_SEQ)

    for name, size, col, bold in (
        ("VT_H1", 15, BRAND.navy, True),
        ("VT_H2", 11, BRAND.navy, True),
        ("VT_SMALL", 7.5, BRAND.muted, False),
    ):
        style = styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        # pyrefly: ignore[missing-attribute]
        style.base_style = base
        # pyrefly: ignore[missing-attribute]
        style.font.name = BRAND.font
        # pyrefly: ignore[missing-attribute]
        style.font.size = Pt(size)
        # pyrefly: ignore[missing-attribute]
        style.font.color.rgb = rgb(col)
        # pyrefly: ignore[missing-attribute]
        style.font.bold = bold
        # pyrefly: ignore[missing-attribute]
        style.paragraph_format.space_before = Pt(6)
        # pyrefly: ignore[missing-attribute]
        style.paragraph_format.space_after = Pt(3)
        # pyrefly: ignore[missing-attribute]
        style.paragraph_format.keep_with_next = bold
        if name == "VT_H1":
            level = OxmlElement("w:outlineLvl")
            level.set(qn("w:val"), "0")
            _insert_ordered(style.element.get_or_add_pPr(), level, _PPR_SEQ)

    _build_running_header(section)
    _build_footer(section.footer.paragraphs[0])
    _build_footer(section.first_page_footer.paragraphs[0])

    document.core_properties.title = "Vibe-Trading Equity Research"
    document.core_properties.author = "Vibe-Trading Securities · Research"
    document.core_properties.language = BRAND.locale
    return document


def _build_running_header(section, report: ResearchReport | None = None):
    header = section.header
    for tbl in list(header.tables):
        tbl._element.getparent().remove(tbl._element)
    for par in list(header.paragraphs[1:]):
        par._element.getparent().remove(par._element)
    first_par = header.paragraphs[0]
    first_par.clear()
    set_para_spacing(first_par, before=0, after=0, line=0.2)

    widths = [6.8, CONTENT_W - 6.8]
    table = header.add_table(rows=1, cols=2, width=Cm(CONTENT_W))
    table.autofit = False
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    no_borders(table)
    row = table.rows[0]
    row_flags(row)
    left, right = row.cells
    left.width = Cm(widths[0])
    right.width = Cm(widths[1])
    for cell in (left, right):
        set_cell_margins(cell, 20, 10, 45, 10)
        cell_border(cell, "bottom", "14532D", 16)

    p_left = left.paragraphs[0]
    p_left.alignment = WD_ALIGN_PARAGRAPH.LEFT
    set_para_spacing(p_left, before=0, after=1, line=1.05)
    p_text(p_left, "VIBE-TRADING", size=10.5, color="14532D", bold=True)
    p_left_sub = left.add_paragraph()
    p_left_sub.alignment = WD_ALIGN_PARAGRAPH.LEFT
    set_para_spacing(p_left_sub, before=0, after=0, line=1.0)
    p_text(p_left_sub, "Equity Research", size=6.8, color=BRAND.muted)

    p_right = right.paragraphs[0]
    p_right.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    set_para_spacing(p_right, before=0, after=1, line=1.05)
    if report is not None:
        p_text(
            p_right,
            f"{report.company_name.upper()} – {report.symbol} ({report.exchange})",
            size=9.5,
            color="14532D",
            bold=True,
        )
        metrics = _metric_map(report)
        target = metrics.get("target_price")
        upside = metrics.get("upside")
        rating = report.recommendation.value
        rating_col = "15803D" if rating in ("MUA", "KHẢ QUAN") else BRAND.rating_color(rating)
        summary_parts = [rating]
        if target is not None and target.value is not None:
            summary_parts.append(display_metric(target))
        line2_text = " – ".join(summary_parts)
        if upside is not None and upside.value is not None:
            line2_text += f" ({fmt_signed(upside.value, upside.decimals)}%)"
        p_right_sub = right.add_paragraph()
        p_right_sub.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        set_para_spacing(p_right_sub, before=0, after=0, line=1.05)
        p_text(p_right_sub, line2_text, size=8.6, color=rating_col, bold=True)
    else:
        p_text(p_right, "BÁO CÁO PHÂN TÍCH DOANH NGHIỆP", size=8.5, color="14532D", bold=True)


def _build_footer(paragraph):
    paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
    paragraph.paragraph_format.tab_stops.clear_all()
    paragraph.paragraph_format.tab_stops.add_tab_stop(Cm(CONTENT_W / 2), WD_TAB_ALIGNMENT.CENTER)
    paragraph.paragraph_format.tab_stops.add_tab_stop(Cm(CONTENT_W), WD_TAB_ALIGNMENT.RIGHT)
    p_text(paragraph, f"{BRAND.legal}  ·  {BRAND.desk}", size=6.8, color=BRAND.muted)
    p_text(paragraph, "\tNghiên cứu đầu tư · đọc công bố và rủi ro\t", size=6.8, color=BRAND.muted)
    p_text(paragraph, "TRANG ", size=6.8, color=BRAND.muted)
    field_run(paragraph, "PAGE", "1", size=6.8, color=BRAND.muted)
    p_text(paragraph, " / ", size=6.8, color=BRAND.muted)
    field_run(paragraph, "NUMPAGES", "1", size=6.8, color=BRAND.muted)
    para_rule(paragraph, BRAND.line, 4, edge="top")
    set_para_spacing(paragraph, before=0, after=0)


# ---------------------------------------------------------------------------
# Cover furniture
# ---------------------------------------------------------------------------


def add_masthead(document, report: ResearchReport):
    table = fixed_table(document, [9.2, 8.2])
    row = add_row(table, [9.2, 8.2])
    left, right = row.cells
    for cell in (left, right):
        set_cell_margins(cell, 0, 0, 90, 0)
    logo = resolve_brand_logo()
    paragraph = left.paragraphs[0]
    paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
    if logo and logo.exists():
        mark = paragraph.add_run().add_picture(str(logo), height=Cm(1.8))
        if mark.width > Cm(5.4):
            mark.height = int(mark.height * Cm(5.4) / mark.width)
            mark.width = Cm(5.4)
        name = left.add_paragraph()
        set_para_spacing(name, before=0, after=0, line=1)
        p_text(name, BRAND.name, size=11, color=BRAND.crimson, bold=True, spacing=20)
    else:  # pragma: no cover - repository always ships the mark
        p_text(paragraph, BRAND.name, size=18, color=BRAND.navy, bold=True, spacing=40)

    first = right.paragraphs[0]
    first.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    p_text(first, BRAND.legal, size=7.6, color=BRAND.navy, bold=True, spacing=18)
    p_text(first, "  ·  ", size=7.6, color=BRAND.teal, bold=True)
    p_text(first, BRAND.desk, size=7.6, color=BRAND.teal, bold=True, spacing=24)

    second = right.add_paragraph()
    second.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    set_para_spacing(second, before=1, after=0)
    p_text(second, "EQUITY RESEARCH", size=7, color=BRAND.muted, spacing=14)

    third = right.add_paragraph()
    third.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    set_para_spacing(third, before=1, after=0)
    p_text(third, f"{report.exchange}  ·  {report.symbol}", size=7, color=BRAND.navy, bold=True, spacing=12)

    # Double rule: thick signal line over a hairline, the broker masthead cue.
    thick = document.add_paragraph()
    set_para_spacing(thick, before=2, after=0, line=1)
    para_rule(thick, BRAND.teal, 22)
    thin = document.add_paragraph()
    set_para_spacing(thin, before=2, after=7, line=1)
    para_rule(thin, BRAND.navy, 4)


def add_cover_title(document, report: ResearchReport):
    kicker = document.add_paragraph()
    set_para_spacing(kicker, before=2, after=3)
    p_text(kicker, report.report_type.upper(), size=7, color=BRAND.teal, bold=True, spacing=28)
    p_text(kicker, f"   {report.data_as_of.strftime('%d/%m/%Y')}", size=7, color=BRAND.muted, spacing=10)

    title = document.add_paragraph()
    set_para_spacing(title, before=0, after=3, line=1.06)
    p_text(title, report.title.upper(), size=19, color=BRAND.navy, bold=True, spacing=-6)

    company = document.add_paragraph()
    set_para_spacing(company, before=1, after=8)
    p_text(company, f"{report.exchange}  ·  {report.company_name}", size=9, color=BRAND.ink, bold=True)
    if report.sector:
        p_text(company, f"  ·  {report.sector}", size=9, color=BRAND.muted)
    if report.subtitle:
        subtitle = document.add_paragraph()
        set_para_spacing(subtitle, before=0, after=8)
        p_text(subtitle, report.subtitle, size=8.6, color=BRAND.muted, italic=True)


def _metric_map(report: ResearchReport) -> dict[str, Metric]:
    merged: dict[str, Metric] = {}
    for metric in [*report.valuation_metrics, *report.financial_metrics]:
        merged[metric.key] = metric
    return merged


def add_rating_strip(document, report: ResearchReport):
    """Recommendation, target, upside and horizon as four signal cells."""
    metrics = _metric_map(report)
    target = metrics.get("target_price")
    upside = metrics.get("upside")
    rating = report.recommendation.value
    rating_color = BRAND.rating_color(rating)

    widths = [4.5, 4.3, 4.3, 4.3]
    table = fixed_table(document, widths)
    row = add_row(table, widths)
    row_flags(row)
    cells = row.cells

    cards = [
        ("KHUYẾN NGHỊ", rating, rating_color, BRAND.rating_tint(rating)),
        (target.label.upper() if target else "GIÁ MỤC TIÊU", display_metric(target) if target else "—", BRAND.navy, BRAND.wash),
        (
            upside.label.upper() if upside else "CHÊNH LỆCH MỤC TIÊU",
            display_metric(upside) if upside and upside.value is not None else "—",
            BRAND.green if upside and (upside.value or 0) >= 0 else BRAND.red,
            BRAND.wash,
        ),
        ("TẦM NHÌN ĐẦU TƯ", report.investment_horizon, BRAND.navy, BRAND.wash),
    ]
    for index, (cell, (label, value, color, fill)) in enumerate(zip(cells, cards)):
        shade(cell, fill)
        cell_border(cell, "top", color if label == "KHUYẾN NGHỊ" else BRAND.teal, 20 if label == "KHUYẾN NGHỊ" else 12)
        set_cell_margins(cell, 130, 170, 130, 120)
        p = cell.paragraphs[0]
        p_text(p, label, size=6.5, color=BRAND.muted, bold=True, spacing=18)
        v = cell.add_paragraph()
        set_para_spacing(v, before=2, after=0, line=1.02)
        p_text(v, value, size=15 if len(value) <= 12 else 11, color=color, bold=True)
        if index in (1, 2):
            append_source_links(v, target if index == 1 else upside)

    spacer = document.add_paragraph()
    set_para_spacing(spacer, before=0, after=4, line=1)


def add_metric_band(document, metrics: list[Metric]):
    chosen = select_featured([m for m in metrics if m.value is not None])
    if not chosen:
        return
    card_count = len(chosen)
    gap = 0.16
    card_w = (CONTENT_W - gap * (card_count - 1)) / card_count
    widths: list[float] = []
    for index in range(card_count):
        widths.append(card_w)
        if index < card_count - 1:
            widths.append(gap)

    table = fixed_table(document, widths)
    row = add_row(table, widths)
    row_flags(row)
    card_index = 0
    for column, cell in enumerate(row.cells):
        if column % 2 == 1:
            continue
        metric = chosen[card_index]
        card_index += 1
        fill = BRAND.white if metric.change is None else BRAND.wash
        shade(cell, fill)
        accent = metric_tone(metric) if metric.change is not None else BRAND.teal
        cell_border(cell, "top", accent, 18)
        cell_border(cell, "bottom", BRAND.line, 4)
        set_cell_margins(cell, 115, 130, 120, 110)

        label = cell.paragraphs[0]
        p_text(label, metric.label.upper(), size=6.2, color=BRAND.muted, bold=True, spacing=12)
        set_para_spacing(label, before=0, after=2, line=1.05)

        headline = metric_headline(metric)
        value_par = cell.add_paragraph()
        set_para_spacing(value_par, before=0, after=0, line=1.0)
        p_text(value_par, headline, size=15.5 if len(headline) <= 9 else 12.5, color=BRAND.navy, bold=True)
        append_source_links(value_par, metric)

        caption, tone = metric_caption(metric)
        if caption:
            cap = cell.add_paragraph()
            set_para_spacing(cap, before=1, after=0, line=1.05)
            p_text(cap, caption, size=6.6, color=tone, bold=metric.change is not None)

    spacer = document.add_paragraph()
    set_para_spacing(spacer, before=0, after=5, line=1)


def add_summary_split(document, report: ResearchReport):
    """62/38 split: investment summary on the left, stock rail on the right."""
    left_w, gap, right_w = 10.9, 0.28, CONTENT_W - 10.9 - 0.28
    table = fixed_table(document, [left_w, gap, right_w])
    row = add_row(table, [left_w, gap, right_w])
    left, spacer_cell, right = row.cells
    shade(spacer_cell, BRAND.white)
    set_cell_margins(left, 0, 0, 20, 220)
    shade(right, BRAND.wash)
    cell_border(right, "top", BRAND.teal, 12)
    set_cell_margins(right, 175, 210, 175, 200)

    heading = left.paragraphs[0]
    p_text(heading, "TÓM TẮT ĐẦU TƯ", size=7.4, color=BRAND.teal, bold=True, spacing=24)
    set_para_spacing(heading, before=2, after=4, line=1.05)
    lead = body_par(left, after=4, line=1.30)
    p_text(lead, report.executive_summary, size=9.2, color=BRAND.ink)
    append_source_links(lead, report.executive_summary_evidence)

    p = right.paragraphs[0]
    p_text(p, "THÔNG TIN TÀI SẢN", size=7.2, color=BRAND.teal, bold=True, spacing=20)
    set_para_spacing(p, before=0, after=5, line=1.05)

    metrics = _metric_map(report)
    rows = [
        ("Mã", f"{report.symbol} · {report.exchange}", None),
    ]
    if report.sector:
        rows.append(("Ngành", report.sector, None))
    for key, label, decimals in (
        ("market_price", "Giá tham chiếu", None),
        ("market_cap", "Vốn hóa", None),
        ("pe", "P/E", None),
        ("forward_eps", "EPS dự phóng", None),
    ):
        metric = metrics.get(key)
        if metric is not None and metric.value is not None:
            # pyrefly: ignore[bad-argument-type]
            rows.append((label, display_metric(metric), metric))
            if key == "market_price" and metric.as_of:
                # pyrefly: ignore[bad-argument-type]
                rows.append(("Ngày giá", metric.as_of.strftime("%d/%m/%Y"), metric))
    rows.append(("Ngày chốt báo cáo", report.data_as_of.strftime("%d/%m/%Y"), None))

    for label, value, evidence in rows:
        paragraph = right.add_paragraph()
        set_para_spacing(paragraph, before=0, after=2.4, line=1.08)
        paragraph.paragraph_format.tab_stops.add_tab_stop(Cm(right_w - 0.62), WD_TAB_ALIGNMENT.RIGHT)
        p_text(paragraph, label, size=7.4, color=BRAND.muted)
        p_text(paragraph, "\t", size=7.4, color=BRAND.muted)
        p_text(paragraph, value, size=7.6, color=BRAND.navy, bold=True)
        if evidence is not None:
            append_source_links(paragraph, evidence)

    note = right.add_paragraph()
    set_para_spacing(note, before=5, after=0, line=1.12)
    p_text(note, "Giá tham chiếu theo ngày ghi rõ ở trên; đối chiếu kỳ của từng chỉ tiêu.", size=6.2, color=BRAND.muted, italic=True)

    spacer = document.add_paragraph()
    set_para_spacing(spacer, before=0, after=6, line=1)


def add_highlights(document, stats: list[KeyStat]):
    if not stats:
        return
    add_block_label(document, "ĐIỂM NHẤN ĐẦU TƯ", BRAND.teal)
    columns = 2
    count = len(stats)
    rows = (count + columns - 1) // columns
    col_w = (CONTENT_W - 0.3) / 2
    table = fixed_table(document, [col_w, 0.3, col_w])
    for row_index in range(rows):
        row = add_row(table, [col_w, 0.3, col_w])
        for col_index in range(columns):
            index = row_index * columns + col_index
            cell = row.cells[col_index * 2]
            if index >= count:
                continue
            stat = stats[index]
            set_cell_margins(cell, 90, 0, 110, 120)
            cell_border(cell, "bottom", BRAND.line, 4)
            value_color = {
                "positive": BRAND.green,
                "negative": BRAND.red,
                "neutral": BRAND.navy,
            }.get(stat.tone, BRAND.navy)
            value = cell.paragraphs[0]
            set_para_spacing(value, before=0, after=1, line=1.0)
            p_text(value, stat.value, size=15, color=value_color, bold=True)
            append_source_links(value, stat)
            label = cell.add_paragraph()
            set_para_spacing(label, before=0, after=1, line=1.05)
            p_text(label, stat.label.upper(), size=6.8, color=BRAND.navy, bold=True, spacing=8)
            if stat.note:
                note = cell.add_paragraph()
                set_para_spacing(note, before=0, after=0, line=1.08)
                p_text(note, stat.note, size=6.6, color=BRAND.muted)
                append_source_links(note, stat)

    spacer = document.add_paragraph()
    set_para_spacing(spacer, before=0, after=6, line=1)


def add_forecast_band(document, stats: list[KeyStat], report: ResearchReport):
    if not stats:
        return
    heading = add_block_label(document, "DỰ PHÓNG VÀ GIẢ ĐỊNH", BRAND.teal)
    heading.paragraph_format.page_break_before = any(section.page_break_before for section in report.analysis_sections)
    for offset in range(0, len(stats), 4):
        batch = stats[offset:offset + 4]
        gap = 0.16
        card_w = (CONTENT_W - gap * (len(batch) - 1)) / len(batch)
        widths = [card_w]
        for _ in batch[1:]:
            widths.extend([gap, card_w])
        table = fixed_table(document, widths)
        row = add_row(table, widths)
        row_flags(row)
        for stat, cell in zip(batch, row.cells[::2]):
            shade(cell, BRAND.deep)
            cell_border(cell, "top", BRAND.teal, 12)
            set_cell_margins(cell, 110, 120, 110, 110)
            label = cell.paragraphs[0]
            p_text(label, stat.label.upper(), size=6.2, color=BRAND.cyan, bold=True, spacing=10)
            set_para_spacing(label, before=0, after=2, line=1.05)
            value = cell.add_paragraph()
            set_para_spacing(value, before=0, after=1, line=1.0)
            p_text(value, stat.value, size=13.5, color=BRAND.white, bold=True)
            append_source_links(value, stat)
            if stat.note:
                note = cell.add_paragraph()
                set_para_spacing(note, before=0, after=0, line=1.08)
                p_text(note, stat.note, size=6.4, color=BRAND.cyan)
                append_source_links(note, stat)

    spacer = document.add_paragraph()
    set_para_spacing(spacer, before=0, after=4, line=1)


def add_block_label(document, text: str, color: str):
    paragraph = document.add_paragraph()
    set_para_spacing(paragraph, before=2, after=4, line=1.05)
    paragraph.paragraph_format.keep_with_next = True
    p_text(paragraph, text, size=7.6, color=color, bold=True, spacing=24)
    return paragraph


def add_cover_contents(document, report: ResearchReport):
    """A compact cover index, or full chapter map for paginated deep research."""
    deep = any(section.page_break_before for section in report.analysis_sections)
    label = document.add_paragraph()
    if deep and not report.forecast_stats:
        label.paragraph_format.page_break_before = True
    label.paragraph_format.keep_with_next = True
    set_para_spacing(label, before=2, after=3, line=1.05)
    p_text(label, "TRONG BÁO CÁO NÀY", size=6.6, color=BRAND.muted, bold=True, spacing=22)

    sections = [
        ("01", "Tổng quan doanh nghiệp"),
        ("02", "Kết quả kinh doanh"),
        ("03", "Diễn biến giá"),
        ("04", "Luận điểm đầu tư"),
        ("05", "Rủi ro cần theo dõi"),
    ]
    number = 6
    if report.analysis_sections:
        last = number + len(report.analysis_sections) - 1
        if deep:
            sections.extend((f"{index:02d}", section.heading) for index, section in enumerate(report.analysis_sections, number))
        else:
            sections.append((f"{number:02d}–{last:02d}", "Phân tích chuyên sâu"))
        number = last + 1
    sections.append((f"{number:02d}", "Định giá"))
    number += 1
    if report.peer_comparison is not None:
        sections.append((f"{number:02d}", "So sánh cùng ngành"))
        number += 1
    if report.catalysts:
        sections.append((f"{number:02d}", "Chất xúc tác và lịch sự kiện"))
        number += 1
    sections.extend([
        (f"{number:02d}", "Nguồn dữ liệu và phương pháp"),
        (f"{number + 1:02d}", "Xếp hạng và công bố"),
    ])
    if report.appendix_sections:
        sections.append(("PL", "Phụ lục nghiên cứu"))
    columns = 2 if deep else 4
    col_w = CONTENT_W / columns
    table = fixed_table(document, [col_w] * columns)
    for offset in range(0, len(sections), columns):
        row = add_row(table, [col_w] * columns)
        row_flags(row)
        for cell, (number, title) in zip(row.cells, sections[offset:offset + columns]):
            set_cell_margins(cell, 55 if deep else 50, 0, 55 if deep else 50, 120 if deep else 100)
            cell_border(cell, "top", BRAND.line, 4)
            paragraph = cell.paragraphs[0]
            set_para_spacing(paragraph, before=0, after=0, line=1.05)
            p_text(paragraph, f"{number}  ", size=7.2, color=BRAND.teal, bold=True)
            p_text(paragraph, title, size=7.6 if deep else 7, color=BRAND.navy)


# ---------------------------------------------------------------------------
# Sectional content
# ---------------------------------------------------------------------------


def add_section_title(document, number: str, title: str, subtitle: str = ""):
    paragraph = document.add_paragraph(style="VT_H1")
    set_para_spacing(paragraph, before=10, after=2, line=1.05)
    paragraph.paragraph_format.keep_with_next = True
    p_text(paragraph, f"{number}   ", size=12, color=BRAND.teal, bold=True)
    p_text(paragraph, title.upper(), size=13, color=BRAND.navy, bold=True, spacing=6)
    para_rule(paragraph, BRAND.teal, 10)
    if subtitle:
        sub = document.add_paragraph()
        set_para_spacing(sub, before=2, after=5, line=1.1)
        sub.paragraph_format.keep_with_next = True
        p_text(sub, subtitle, size=7.8, color=BRAND.muted, italic=True)
    return paragraph


def add_body(document, text: str, *, size: float = 9, after: float = 4):
    paragraph = body_par(document, after=after, line=1.28)
    p_text(paragraph, text, size=size, color=BRAND.ink)
    return paragraph


def add_paragraph_lead(document, lead: str, body: str):
    paragraph = body_par(document, after=4, line=1.28)
    p_text(paragraph, lead, size=9, color=BRAND.navy, bold=True)
    p_text(paragraph, body, size=9, color=BRAND.ink)
    return paragraph


def add_financial_table(document, table_spec: FinancialTable):
    add_block_label(document, table_spec.title, BRAND.navy)
    if table_spec.subtitle:
        sub = document.add_paragraph()
        set_para_spacing(sub, before=0, after=4, line=1.1)
        p_text(sub, table_spec.subtitle, size=7.2, color=BRAND.muted, italic=True)
        append_source_links(sub, table_spec)

    if not table_spec.rows:
        add_body(document, "Chưa có số liệu kỳ báo cáo trong snapshot.", size=8.4)
        return

    has_note = any(row.note for row in table_spec.rows)
    value_columns = max(len(table_spec.columns), max((len(row.values) for row in table_spec.rows), default=0))
    label_w = 4.9
    note_w = 3.4 if has_note else 0
    value_w = (CONTENT_W - label_w - note_w) / max(value_columns, 1)
    widths = [label_w] + [value_w] * value_columns + ([note_w] if has_note else [])

    table = fixed_table(document, widths)
    header = add_row(table, widths)
    row_flags(header, header=True)
    headers = ["CHỈ TIÊU"] + [column.upper() for column in table_spec.columns]
    headers += [""] * (value_columns - len(table_spec.columns))
    if has_note:
        headers.append("GHI CHÚ")
    for index, cell in enumerate(header.cells):
        shade(cell, BRAND.navy)
        set_cell_margins(cell, 85, 90, 85, 90)
        paragraph = cell.paragraphs[0]
        paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT if index == 0 else WD_ALIGN_PARAGRAPH.RIGHT
        if has_note and index == len(header.cells) - 1:
            paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
        p_text(paragraph, headers[index], size=6.8, color=BRAND.white, bold=True, spacing=4)

    for row_index, spec_row in enumerate(table_spec.rows):
        row = add_row(table, widths)
        row_flags(row)
        values = list(spec_row.values) + [""] * (value_columns - len(spec_row.values))
        for col_index, cell in enumerate(row.cells):
            set_cell_margins(cell, 70, 90, 65, 90)
            if spec_row.emphasis:
                shade(cell, BRAND.mint)
                cell_border(cell, "top", BRAND.navy, 6)
            elif row_index % 2 == 1:
                shade(cell, BRAND.wash)
            cell_border(cell, "bottom", BRAND.line, 4)
            paragraph = cell.paragraphs[0]
            set_para_spacing(paragraph, before=0, after=0, line=1.06)
            if col_index == 0:
                paragraph.paragraph_format.left_indent = Cm(0.28 * spec_row.indent)
                p_text(
                    paragraph,
                    spec_row.label,
                    size=7.6,
                    color=BRAND.navy if spec_row.emphasis else BRAND.ink,
                    bold=spec_row.emphasis,
                )
            elif has_note and col_index == len(row.cells) - 1:
                p_text(paragraph, spec_row.note, size=6.6, color=BRAND.muted, italic=True)
                if spec_row.note:
                    append_source_links(paragraph, spec_row)
            else:
                paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                p_text(
                    paragraph,
                    values[col_index - 1],
                    size=7.6,
                    color=BRAND.navy if spec_row.emphasis else BRAND.ink,
                    bold=spec_row.emphasis,
                )
                if col_index - 1 < len(spec_row.values):
                    evidence = spec_row.cell_evidence[col_index - 1] if spec_row.cell_evidence else spec_row
                    append_source_links(paragraph, evidence)

    if table_spec.note:
        note = document.add_paragraph()
        set_para_spacing(note, before=2, after=6, line=1.12)
        p_text(note, table_spec.note, size=6.6, color=BRAND.muted, italic=True)
        append_source_links(note, table_spec)
    else:
        spacer = document.add_paragraph()
        set_para_spacing(spacer, before=0, after=4, line=1)


def add_metric_table(document, title: str, items: list[Metric], *, empty_note: str = ""):
    add_block_label(document, title, BRAND.navy)
    if not items:
        add_body(document, empty_note or "Không có số liệu được kiểm chứng tại thời điểm phát hành.", size=8.4)
        return
    widths = [7.4, 4.4, 5.6]
    table = fixed_table(document, widths)
    header = add_row(table, widths)
    row_flags(header, header=True)
    for cell, label, align in zip(
        header.cells,
        ("CHỈ TIÊU", "GIÁ TRỊ", "NGUỒN / KỲ"),
        (WD_ALIGN_PARAGRAPH.LEFT, WD_ALIGN_PARAGRAPH.RIGHT, WD_ALIGN_PARAGRAPH.LEFT),
    ):
        shade(cell, BRAND.navy)
        set_cell_margins(cell, 80, 95, 80, 95)
        cell.paragraphs[0].alignment = align
        p_text(cell.paragraphs[0], label, size=7, color=BRAND.white, bold=True, spacing=6)

    for index, item in enumerate(items):
        row = add_row(table, widths)
        row_flags(row)
        for cell in row.cells:
            set_cell_margins(cell, 70, 95, 65, 95)
            if index % 2 == 1:
                shade(cell, BRAND.wash)
            cell_border(cell, "bottom", BRAND.line, 4)
        p_text(row.cells[0].paragraphs[0], item.label, size=8, color=BRAND.ink)
        value_par = row.cells[1].paragraphs[0]
        value_par.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        p_text(value_par, display_metric(item), size=8, color=BRAND.navy, bold=True)
        append_source_links(value_par, item)
        report = getattr(document.part, "_research_report", None)
        source = ", ".join(datum_source_ids(report, item)) or "chưa có"
        stamp = item.as_of.strftime("%d/%m/%Y") if item.as_of else "n/a"
        p_text(row.cells[2].paragraphs[0], f"{source} · {stamp}", size=7, color=BRAND.muted)
    spacer = document.add_paragraph()
    set_para_spacing(spacer, before=0, after=4, line=1)


def add_callout(document, title: str, claims: list[Claim], accent: str, empty_note: str):
    if not claims:
        add_body(document, empty_note, size=8.6)
        return
    table = fixed_table(document, [CONTENT_W])
    header = add_row(table, [CONTENT_W])
    row_flags(header)
    head_cell = header.cells[0]
    shade(head_cell, BRAND.wash)
    cell_border(head_cell, "left", accent, 24)
    set_cell_margins(head_cell, 75, 160, 65, 160)
    head_cell.paragraphs[0].paragraph_format.keep_with_next = True
    p_text(head_cell.paragraphs[0], title.upper(), size=7.6, color=accent, bold=True, spacing=20)

    for index, claim in enumerate(claims, 1):
        row = add_row(table, [CONTENT_W])
        row_flags(row)
        cell = row.cells[0]
        shade(cell, BRAND.wash)
        cell_border(cell, "left", accent, 24)
        set_cell_margins(cell, 55, 160, 65, 180)
        head = cell.paragraphs[0]
        set_para_spacing(head, before=1, after=1, line=1.10)
        head.paragraph_format.keep_with_next = True
        p_text(head, f"{index:02d}  ", size=8.6, color=accent, bold=True)
        p_text(head, claim.title, size=8.5, color=BRAND.navy, bold=True)
        body = cell.add_paragraph()
        set_para_spacing(body, before=0, after=1.5, line=1.18)
        p_text(body, claim.body, size=8.0, color=BRAND.ink)
        append_source_links(body, claim)
        source = cell.add_paragraph()
        set_para_spacing(source, before=0, after=0, line=1.05)
        p_text(
            source,
            "Nguồn: " + (", ".join(datum_source_ids(getattr(document.part, "_research_report", None), claim)) or "chưa xác minh"),
            size=6.4,
            color=BRAND.muted,
            italic=True,
        )
    spacer = document.add_paragraph()
    set_para_spacing(spacer, before=0, after=3, line=1)


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------


def _chart_figure(width_in: float, height_in: float) -> tuple[Figure, FigureCanvasAgg]:
    figure = Figure(figsize=(width_in, height_in), dpi=210, facecolor="white")
    figure.add_artist(FancyBboxPatch(
        (0.003, 0.009), 0.994, 0.982,
        boxstyle="round,pad=0,rounding_size=0.025",
        transform=figure.transFigure,
        facecolor=f"#{BRAND.wash}", edgecolor=f"#{BRAND.line}", linewidth=0.8,
        zorder=-1,
    ))
    canvas = FigureCanvasAgg(figure)
    return figure, canvas


def create_price_chart(report: ResearchReport, png_path: Path) -> bool:
    """Price line over a volume histogram, with the target-price reference."""
    if len(report.price_history) < 2:
        return False

    dates = [point.date for point in report.price_history]
    closes = [point.close for point in report.price_history]
    market_price = _metric_map(report).get("market_price")
    decimals = market_price.decimals if market_price else (0 if report.market.value == "VN_EQUITY" else 4)
    history_unit = report.price_history[0].unit
    price_unit = unit_label(history_unit or (market_price.unit if market_price else ""))
    basis = report.price_history[0].price_basis

    figure, canvas = _chart_figure(6.7, 2.35)
    grid = figure.add_gridspec(2, 1, height_ratios=[3.1, 1], hspace=0.08)
    price_ax = figure.add_subplot(grid[0])
    volume_ax = figure.add_subplot(grid[1], sharex=price_ax)

    with matplotlib.rc_context({"font.family": CHART_FONT}):
        baseline = min(closes) * 0.93
        # pyrefly: ignore[bad-argument-type]
        price_ax.plot(dates, closes, color="#B91C1C", lw=2.0, zorder=4, solid_capstyle="round")
        # pyrefly: ignore[bad-argument-type]
        price_ax.fill_between(dates, closes, baseline, color="#FECACA", alpha=0.55, zorder=2)
        # pyrefly: ignore[bad-argument-type]
        price_ax.scatter([dates[-1]], [closes[-1]], color="#DC2626", s=30, zorder=6, edgecolor="white", linewidth=0.8)
        price_ax.annotate(
            f"{fmt_number(closes[-1], decimals)} {price_unit}".strip(),
            xy=(dates[-1], closes[-1]),
            xytext=(-6, 9),
            textcoords="offset points",
            ha="right",
            fontsize=7.2,
            color="#1A0F0F",
            fontweight="bold",
        )

        target = _metric_map(report).get("target_price")
        # pyrefly: ignore[unnecessary-type-conversion]
        comparable = report.demo or (target and target.unit == history_unit and target.price_basis == basis)
        target_visible = bool(comparable and target is not None and target.value is not None and target.value > 0)
        if target_visible:
            # pyrefly: ignore[missing-attribute]
            target_color = BRAND.green if target.value >= closes[-1] else BRAND.red
            # pyrefly: ignore[missing-attribute]
            price_ax.axhline(target.value, color=f"#{target_color}", lw=1.0, ls=(0, (4, 3)), zorder=3)
            price_ax.annotate(
                # pyrefly: ignore[bad-argument-type]
                f"Giá mục tiêu {display_metric(target)}",
                # pyrefly: ignore[missing-attribute]
                xy=(dates[0], target.value),
                xytext=(4, 4),
                textcoords="offset points",
                fontsize=6.6,
                color=f"#{target_color}",
                fontweight="bold",
            )

        ceiling = max(closes) * 1.08
        if target_visible:
            # pyrefly: ignore[missing-attribute]
            baseline = min(baseline, target.value * 0.97)
            # pyrefly: ignore[missing-attribute]
            ceiling = max(ceiling, target.value * 1.08)
        price_ax.set_ylim(baseline, ceiling)
        price_ax.set_facecolor(f"#{BRAND.wash}")
        price_ax.grid(axis="y", color="#F3E8E8", lw=0.7)
        price_ax.tick_params(colors="#7A6262", labelsize=6.6, length=0)
        price_ax.tick_params(axis="x", labelbottom=False)
        for spine in price_ax.spines.values():
            spine.set_visible(False)
        price_ax.yaxis.set_major_locator(MaxNLocator(4))
        price_ax.yaxis.set_major_formatter(lambda value, _pos: fmt_number(value, decimals))
        if basis:
            basis_label = {"raw": "chưa điều chỉnh", "split_adjusted": "điều chỉnh chia tách",
                           "total_return": "điều chỉnh chia tách và cổ tức"}[basis]
            price_ax.set_title(f"{price_unit} · {basis_label}", loc="left", fontsize=6.5, color=f"#{BRAND.muted}")

        bar_color = "#E7D4D4"
        hi_color = "#DC2626"
        bar_width = min((right - left).days for left, right in zip(dates, dates[1:])) * 0.7
        for i, point in enumerate(report.price_history):
            if point.volume is not None:
                color = hi_color if i == len(dates) - 1 else bar_color
                # pyrefly: ignore[bad-argument-type]
                volume_ax.bar([point.date], [point.volume], color=color, width=bar_width, zorder=3)
        if all(point.volume is None for point in report.price_history):
            volume_ax.text(0.5, 0.5, "Không có dữ liệu khối lượng", transform=volume_ax.transAxes,
                           ha="center", va="center", fontsize=6.6, color=f"#{BRAND.muted}")
            volume_ax.set_yticks([])
        else:
            volume_ax.yaxis.set_major_locator(MaxNLocator(2))
        volume_ax.set_facecolor(f"#{BRAND.wash}")
        volume_ax.grid(axis="y", color="#F8EFEF", lw=0.6)
        volume_ax.tick_params(colors="#7A6262", labelsize=6.2, length=0)
        volume_ax.yaxis.set_major_formatter(lambda value, _pos: fmt_number(value / 1_000_000, 1) + "tr")
        for spine in volume_ax.spines.values():
            spine.set_visible(False)
        volume_ax.xaxis.set_major_locator(MaxNLocator(6))
        volume_ax.xaxis.set_major_formatter(DateFormatter("%d/%m"))

        # The left-aligned unit/basis title sits above the axes, so the plot
        # needs headroom for it: at top=0.94 the first line of the title is
        # clipped by the figure edge.
        figure.subplots_adjust(left=0.1, right=0.975, top=0.88, bottom=0.14, hspace=0.1)
        canvas.print_figure(str(png_path), dpi=210, facecolor="white")
    return True


def create_quarterly_chart(points: list[PeriodPoint], png_path: Path) -> bool:
    if len(points) < 2:
        return False
    labels = [point.period for point in points]
    values = [point.value for point in points]
    highlight_index = next((i for i, point in enumerate(points) if point.highlight), len(points) - 1)

    figure, canvas = _chart_figure(6.7, 2.05)
    axes = figure.add_subplot(111)
    with matplotlib.rc_context({"font.family": CHART_FONT}):
        colors = ["#DC2626" if i == highlight_index else "#ECCACA" for i in range(len(values))]
        edges = ["#B91C1C" if i == highlight_index else "#DFC0C0" for i in range(len(values))]
        bars = axes.bar(range(len(values)), values, color=colors, edgecolor=edges, linewidth=0.6, width=0.58, zorder=3)
        low, high = min(0, *values), max(0, *values)
        span = high - low or 1
        axes.set_ylim(low - span * 0.18 if low < 0 else 0, high + span * 0.24)
        axes.set_facecolor(f"#{BRAND.wash}")
        for index, (bar, value) in enumerate(zip(bars, values)):
            axes.annotate(
                fmt_number(value, 0 if abs(value) >= 100 else 1),
                xy=(bar.get_x() + bar.get_width() / 2, bar.get_height()),
                xytext=(0, 4 if value >= 0 else -4),
                textcoords="offset points",
                ha="center",
                va="bottom" if value >= 0 else "top",
                fontsize=6.8,
                color="#7F1D1D" if index == highlight_index else "#7A6262",
                fontweight="bold" if index == highlight_index else "normal",
            )
        axes.set_xticks(range(len(labels)))
        axes.set_xticklabels(labels, fontsize=6.8, color="#7A6262")
        axes.grid(axis="y", color="#F3E8E8", lw=0.6, zorder=1)
        axes.tick_params(axis="y", left=False, labelleft=False, length=0)
        axes.tick_params(axis="x", length=0)
        for spine in axes.spines.values():
            spine.set_visible(False)
        axes.axhline(0, color="#EBDDDD", lw=0.8)
        figure.subplots_adjust(left=0.035, right=0.975, top=0.9, bottom=0.14)
        canvas.print_figure(str(png_path), dpi=210, facecolor="white")
    return True


def add_chart(document, png: Path, caption: str, width_cm: float = CONTENT_W, evidence=()):
    paragraph = document.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.paragraph_format.keep_with_next = True
    set_para_spacing(paragraph, before=2, after=1, line=1)
    paragraph.add_run().add_picture(str(png), width=Cm(width_cm))
    caption_par = document.add_paragraph()
    set_para_spacing(caption_par, before=0, after=6, line=1.08)
    p_text(caption_par, caption, size=6.8, color=BRAND.muted, italic=True)
    report = getattr(document.part, "_research_report", None)
    if report is not None:
        source_ids = list(dict.fromkeys(source.id for item in evidence for source in datum_sources(report, item)))
        append_source_links(caption_par, DatumEvidence(source_ids=source_ids))


def _draw_vcbs_combo_panel(ax1, spec: dict[str, object]):
    # pyrefly: ignore[not-iterable]
    categories = [str(c) for c in spec.get("categories", [])]
    # pyrefly: ignore[not-iterable]
    bars = [float(v) for v in spec.get("bars", [])]
    # pyrefly: ignore[not-iterable]
    line = [float(v) for v in spec.get("line", [])]
    title = str(spec.get("title", ""))
    bar_label = str(spec.get("bar_label", "Giá trị (Tỷ VND)"))
    line_label = str(spec.get("line_label", "Tỷ lệ (%)"))
    # pyrefly: ignore[bad-argument-type]
    bar_decimals = int(spec.get("bar_decimals", 0))
    # pyrefly: ignore[bad-argument-type]
    line_decimals = int(spec.get("line_decimals", 1))
    line_suffix = str(spec.get("line_suffix", "%"))

    x = list(range(len(categories)))
    bar_colors = ["#0B4F32" if v >= 0 else "#B91C1C" for v in bars]
    rects = ax1.bar(
        x,
        bars,
        width=0.38,
        color=bar_colors,
        edgecolor="#052E16",
        linewidth=0.35,
        zorder=3,
        label=bar_label.upper(),
    )
    has_line = bool(line and len(line) == len(categories))
    low_bar, high_bar = min(0.0, *bars), max(0.0, *bars)
    span_bar = (high_bar - low_bar) or 1.0
    top_pad = 0.56 if has_line else 0.28
    ax1.set_ylim(low_bar - span_bar * 0.24 if low_bar < 0 else 0.0, high_bar + span_bar * top_pad)
    ax1.set_facecolor("#FFFFFF")
    ax1.grid(axis="y", color="#E2E8F0", lw=0.6, zorder=1)
    ax1.set_axisbelow(True)
    ax1.set_xticks(x)
    ax1.set_xticklabels(categories, fontsize=6.3, color="#0F172A", rotation=20 if len(categories) > 5 else 0)
    ax1.yaxis.set_major_locator(MaxNLocator(6))
    ax1.yaxis.set_major_formatter(lambda value, _pos: fmt_number(value, bar_decimals))
    ax1.tick_params(axis="y", colors="#0F172A", labelsize=6.3, length=0)
    ax1.tick_params(axis="x", colors="#0F172A", labelsize=6.3, length=2)
    if low_bar < 0:
        ax1.axhline(0, color="#94A3B8", lw=0.7, zorder=2)

    for rect, val in zip(rects, bars):
        ax1.annotate(
            fmt_number(val, bar_decimals),
            xy=(rect.get_x() + rect.get_width() / 2, rect.get_height()),
            xytext=(0, 2.2 if val >= 0 else -7.5),
            textcoords="offset points",
            ha="center",
            va="bottom" if val >= 0 else "top",
            fontsize=5.6,
            color="#0B4F32" if val >= 0 else "#991B1B",
            fontweight="bold",
            zorder=6,
            bbox=dict(boxstyle="round,pad=0.10", facecolor="white", edgecolor="none", alpha=0.88),
        )

    ax2 = ax1.twinx()
    if line and len(line) == len(categories):
        ax2.plot(
            x,
            line,
            color="#EA580C",
            lw=2.2,
            marker="o",
            markersize=3.4,
            markerfacecolor="#EA580C",
            markeredgecolor="white",
            markeredgewidth=0.6,
            zorder=4,
            label=line_label,
        )
        low_line, high_line = min(line), max(line)
        span_line = (high_line - low_line) or (abs(high_line) * 0.25 or 1.0)
        # Keep the orange trend line in the upper visual band so it never collides with bar labels
        ax2.set_ylim(low_line - span_line * 1.45, high_line + span_line * 0.24)
        ax2.yaxis.set_major_locator(MaxNLocator(6))
        ax2.yaxis.set_major_formatter(lambda value, _pos: f"{fmt_number(value, line_decimals)}{line_suffix}")
        ax2.tick_params(axis="y", colors="#0F172A", labelsize=6.3, length=0)
    else:
        ax2.set_yticks([])

    for spine in (*ax1.spines.values(), *ax2.spines.values()):
        spine.set_visible(True)
        spine.set_color("#CBD5E1")
        spine.set_linewidth(0.8)

    ax1.set_title(title, fontsize=7.8, fontweight="bold", color="#0F172A", pad=8)
    handles1, labels1 = ax1.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    if handles1 or handles2:
        ax1.legend(
            handles1 + handles2,
            labels1 + labels2,
            loc="upper center",
            bbox_to_anchor=(0.5, -0.20 if len(categories) > 5 else -0.15),
            ncol=2,
            frameon=False,
            fontsize=6.0,
            handlelength=1.5,
            columnspacing=1.2,
        )


def create_vcbs_combo_pair_png(
    specs: list[dict[str, object]],
    png_path: Path,
    height_in: float = 2.40,
) -> bool:
    """Render one or two dual-axis combo panels (VCBS institutional style)."""
    specs = [spec for spec in specs if spec.get("categories")][:2]
    if not specs:
        return False
    figure = Figure(figsize=(7.4, height_in), dpi=220, facecolor="white")
    canvas = FigureCanvasAgg(figure)
    grid = figure.add_gridspec(1, len(specs), wspace=0.28)
    with matplotlib.rc_context({"font.family": CHART_FONT}):
        for index, spec in enumerate(specs):
            _draw_vcbs_combo_panel(figure.add_subplot(grid[index]), spec)
        if len(specs) == 2:
            figure.subplots_adjust(left=0.065, right=0.935, top=0.86, bottom=0.24, wspace=0.28)
        else:
            figure.subplots_adjust(left=0.08, right=0.92, top=0.86, bottom=0.24)
        canvas.print_figure(str(png_path), dpi=220, facecolor="white")
    return True


def add_vcbs_chart_pair(
    document,
    specs: list[dict[str, object]],
    png_path: Path,
    height_in: float = 2.40,
):
    """Embed 1-2 combo panels with a caption header and a per-panel source footer."""
    specs = [spec for spec in specs if spec.get("categories")][:2]
    if not create_vcbs_combo_pair_png(specs, png_path, height_in=height_in):
        return
    if len(specs) == 2:
        widths = [CONTENT_W / 2 - 0.25, 0.5, CONTENT_W / 2 - 0.25]
        slots = ((0, specs[0]), (2, specs[1]))
    else:
        widths = [CONTENT_W]
        slots = ((0, specs[0]),)

    head_table = fixed_table(document, widths)
    fig_row = add_row(head_table, widths)
    row_flags(fig_row)
    for idx, spec in slots:
        cell = fig_row.cells[idx]
        set_cell_margins(cell, 25, 10, 15, 10)
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        p.paragraph_format.keep_with_next = True
        set_para_spacing(p, before=0, after=1, line=1.08)
        run = p_text(p, str(spec.get("caption", "")), size=8.2, color="0F172A", bold=True)
        run.underline = True

    paragraph = document.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.paragraph_format.keep_with_next = True
    set_para_spacing(paragraph, before=1, after=1, line=1)
    paragraph.add_run().add_picture(str(png_path), width=Cm(CONTENT_W))

    src_table = fixed_table(document, widths)
    src_row = add_row(src_table, widths)
    row_flags(src_row)
    for idx, spec in slots:
        cell = src_row.cells[idx]
        set_cell_margins(cell, 5, 10, 25, 10)
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        set_para_spacing(p, before=0, after=1, line=1.05)
        p_text(p, str(spec.get("source", "")), size=7.2, color=BRAND.ink)
        evidence = spec.get("evidence")
        if isinstance(evidence, DatumEvidence):
            append_source_links(p, evidence)


def _series_label(series: ChartSeries) -> str:
    unit = series.unit.strip()
    return f"{series.label} ({unit})" if unit and unit not in series.label else series.label


def _section_chart_specs(
    report: ResearchReport,
    section: NarrativeSection,
    first_figure: int,
) -> list[dict[str, object]]:
    """Translate validated ``SectionChart`` data into panel specs; never adds numbers.

    Every bar/line value comes from the report the validators accepted: cited
    series were matched against collected source text, formula lines were
    recomputed by the schema. The source footer is built from the report's own
    ``Source`` records, so no provider name is ever hardcoded here.
    """
    sources = {source.id: source for source in report.sources}
    specs: list[dict[str, object]] = []
    for offset, chart in enumerate(section.charts):
        series = [s for s in (chart.bars, chart.line_numerator, chart.line) if s is not None]
        source_ids = list(dict.fromkeys(sid for s in series for sid in datum_source_ids(report, s)))
        providers = list(dict.fromkeys(sources[sid].provider for sid in source_ids if sid in sources))
        source_text = "Nguồn: " + (", ".join(providers) or "chưa có nguồn")
        if source_ids:
            source_text += f" [{', '.join(source_ids)}]"
        if chart.line is not None and chart.line.evidence_kind == "derived":
            source_text += f"; {chart.line.methodology}"
        caption = chart.caption or chart.title
        spec: dict[str, object] = {
            "title": chart.title,
            "categories": list(chart.categories),
            "bars": list(chart.bars.values),
            "bar_label": _series_label(chart.bars),
            "bar_decimals": chart.bars.decimals,
            "source": source_text,
            "caption": f"Hình {first_figure + offset}: {caption}",
            "evidence": DatumEvidence(source_ids=source_ids),
        }
        if chart.line is not None:
            line_unit = chart.line.unit.strip()
            spec.update(
                line=list(chart.line.values),
                line_label=_series_label(chart.line),
                line_decimals=chart.line.decimals,
                line_suffix=line_unit if line_unit in {"%", "x", "đ"} else "",
            )
        specs.append(spec)
    return specs


# ---------------------------------------------------------------------------
# Closing furniture
# ---------------------------------------------------------------------------


def add_rating_scale(document, bands: list[RatingBand]):
    if not bands:
        return
    add_block_label(document, "THANG ĐIỂM XẾP HẠNG", BRAND.navy)
    widths = [3.4, CONTENT_W - 3.4]
    table = fixed_table(document, widths)
    for index, band in enumerate(bands):
        row = add_row(table, widths)
        row_flags(row)
        label_cell, rule_cell = row.cells
        for cell in (label_cell, rule_cell):
            set_cell_margins(cell, 70, 90, 65, 90)
            cell_border(cell, "bottom", BRAND.line, 4)
            if index % 2 == 1:
                shade(cell, BRAND.wash)
        p_text(
            label_cell.paragraphs[0],
            band.label.upper(),
            size=7.6,
            color=BRAND.rating_color(band.label),
            bold=True,
            spacing=8,
        )
        p_text(rule_cell.paragraphs[0], band.rule, size=7.4, color=BRAND.ink)
    spacer = document.add_paragraph()
    set_para_spacing(spacer, before=0, after=6, line=1)


def add_analyst_block(document, report: ResearchReport):
    analyst = report.analyst
    widths = [8.8, CONTENT_W - 8.8]
    table = fixed_table(document, widths)
    row = add_row(table, widths)
    row_flags(row)
    left, right = row.cells
    shade(left, BRAND.wash)
    shade(right, BRAND.wash)
    cell_border(left, "top", BRAND.teal, 12)
    cell_border(right, "top", BRAND.navy, 12)
    set_cell_margins(left, 150, 200, 160, 180)
    set_cell_margins(right, 150, 200, 160, 180)

    p_text(left.paragraphs[0], "CHUYÊN VIÊN PHÂN TÍCH" if analyst else "THÔNG TIN NGHIÊN CỨU", size=7, color=BRAND.teal, bold=True, spacing=18)
    if analyst:
        name = left.add_paragraph()
        set_para_spacing(name, before=3, after=1, line=1.05)
        p_text(name, analyst.name, size=11, color=BRAND.navy, bold=True)
        title = left.add_paragraph()
        set_para_spacing(title, before=0, after=2, line=1.12)
        p_text(title, analyst.title, size=7.4, color=BRAND.muted, italic=True)
        contact_bits = [bit for bit in (analyst.email, analyst.phone) if bit]
        if contact_bits:
            contact = left.add_paragraph()
            set_para_spacing(contact, before=0, after=0, line=1.1)
            p_text(contact, "  ·  ".join(contact_bits), size=7, color=BRAND.ink)
    else:
        p_text(left.add_paragraph(), f"{BRAND.name} {BRAND.desk}", size=10, color=BRAND.navy, bold=True)
        p_text(left.add_paragraph(), "Phân tích dự thảo; chưa có chuyên viên phê duyệt.", size=7.4, color=BRAND.muted)

    p_text(right.paragraphs[0], "THÔNG TIN PHÁT HÀNH", size=7, color=BRAND.navy, bold=True, spacing=18)
    release_rows = [
        ("Ngày chốt dữ liệu", report.data_as_of.strftime("%d/%m/%Y")),
        ("Trạng thái", _STATUS_LABELS.get(report.publication_status, report.publication_status)),
        ("Khuyến nghị", report.recommendation.value),
        ("Tầm nhìn", report.investment_horizon),
    ]
    for label, value in release_rows:
        paragraph = right.add_paragraph()
        set_para_spacing(paragraph, before=2, after=0, line=1.1)
        paragraph.paragraph_format.tab_stops.add_tab_stop(
            Cm(widths[1] - 0.62), WD_TAB_ALIGNMENT.RIGHT
        )
        p_text(paragraph, label, size=7, color=BRAND.muted)
        p_text(paragraph, "\t", size=7, color=BRAND.muted)
        p_text(
            paragraph,
            value,
            size=7.2,
            color=BRAND.rating_color(report.recommendation.value)
            if label == "Khuyến nghị"
            else BRAND.navy,
            bold=True,
        )
    spacer = document.add_paragraph()
    set_para_spacing(spacer, before=0, after=6, line=1)


def add_sources(document, sources):
    document.add_heading("Tài liệu tham khảo (APA 7th)", level=2)
    for source in reference_sources(sources):
        paragraph = document.add_paragraph()
        paragraph.paragraph_format.left_indent = Inches(0.5)
        paragraph.paragraph_format.first_line_indent = Inches(-0.5)
        set_para_spacing(paragraph, before=0, after=6, line=2)
        p_text(paragraph, source.title, size=8.4, italic=True)
        p_text(paragraph, "." if not source.title.endswith((".", "!", "?")) else "", size=8.4)
        p_text(paragraph, apa_reference_suffix(source), size=8.4)
        if source.url:
            append_source_links(paragraph, DatumEvidence(source_ids=[source.id]), full_url=True)
    add_body(document, "Tác giả chưa có trong metadata: dùng nhan đề ở vị trí tác giả; n.d. khi thiếu ngày xuất bản. Bảng dưới giữ mã nguồn và trạng thái kiểm chứng.", size=7)
    widths = [1.5, 11.3, CONTENT_W - 1.5 - 11.3]
    table = fixed_table(document, widths)
    header = add_row(table, widths)
    row_flags(header, header=True)
    for cell, label in zip(header.cells, ("MÃ", "TÀI LIỆU / NHÀ CUNG CẤP", "TRẠNG THÁI")):
        shade(cell, BRAND.navy)
        set_cell_margins(cell, 80, 90, 80, 90)
        p_text(cell.paragraphs[0], label, size=6.8, color=BRAND.white, bold=True, spacing=6)
    if not sources:
        add_body(document, "Không có nguồn dữ liệu.", size=8.4)
        return
    for index, source in enumerate(sources):
        row = add_row(table, widths)
        row_flags(row)
        for cell in row.cells:
            set_cell_margins(cell, 70, 90, 70, 90)
            if index % 2 == 1:
                shade(cell, BRAND.wash)
            cell_border(cell, "bottom", BRAND.line, 4)
        p_text(row.cells[0].paragraphs[0], source.id, size=7, color=BRAND.teal, bold=True)
        p_text(row.cells[1].paragraphs[0], source.title, size=7.2, color=BRAND.ink)
        detail = source.provider
        detail_par = row.cells[1].add_paragraph()
        set_para_spacing(detail_par, before=1, after=0, line=1.05)
        p_text(detail_par, detail, size=6.2, color=BRAND.muted)
        if source.url:
            append_source_links(detail_par, DatumEvidence(source_ids=[source.id]), full_url=True)
        if source.retrieved_at:
            stamp = row.cells[1].add_paragraph()
            p_text(stamp, f"Thu thập: {source.retrieved_at.isoformat()}", size=6.2, color=BRAND.muted)
        p_text(
            row.cells[2].paragraphs[0],
            _SOURCE_STATUS.get(source.status, source.status),
            size=6.8,
            color=BRAND.ink,
        )
    spacer = document.add_paragraph()
    set_para_spacing(spacer, before=0, after=4, line=1)


def _append_rich_text(paragraph, text: str, *, size: float = 9.5):
    """Render a paragraph or bullet with a bold lead-in if a colon appears early."""
    colon_idx = text.find(":")
    if 0 < colon_idx <= 68:
        p_text(paragraph, text[: colon_idx + 1], size=size, color=BRAND.navy, bold=True)
        p_text(paragraph, text[colon_idx + 1 :], size=size, color=BRAND.ink)
    else:
        p_text(paragraph, text, size=size, color=BRAND.ink)


def add_vcbs_analytical_table(document, bullets: list[str], section):
    """Render a structured VCBS-style analytical matrix table for non-chart chapters."""
    if not bullets:
        return
    widths = [4.1, CONTENT_W - 4.1 - 2.3, 2.3]
    table = fixed_table(document, widths)
    header = add_row(table, widths)
    row_flags(header, header=True)
    headers = (
        "TRỤ CỘT PHÂN TÍCH",
        "PHÂN TÍCH ĐỊNH LƯỢNG & DIỄN GIẢI TRỌNG TÂM",
        "THAM CHIẾU",
    )
    for idx, (cell, label) in enumerate(zip(header.cells, headers)):
        shade(cell, BRAND.crimson)
        set_cell_margins(cell, 75, 90, 75, 90)
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER if idx == 2 else WD_ALIGN_PARAGRAPH.LEFT
        p_text(p, label, size=6.8, color=BRAND.white, bold=True)

    for idx, bullet in enumerate(bullets, 1):
        row = add_row(table, widths)
        row_flags(row)
        colon_idx = bullet.find(":")
        if 0 < colon_idx <= 75:
            pillar = bullet[:colon_idx].strip()
            detail = bullet[colon_idx + 1 :].strip()
        else:
            pillar = f"Trụ cột phân tích {idx:02d}"
            detail = bullet.strip()

        for c_idx, cell in enumerate(row.cells):
            set_cell_margins(cell, 70, 90, 70, 90)
            shade(cell, "F8FAFC" if idx % 2 == 1 else BRAND.white)
            cell_border(cell, "bottom", BRAND.line, 4)
            if c_idx == 0:
                cell_border(cell, "left", BRAND.crimson, 12)

        p0 = row.cells[0].paragraphs[0]
        set_para_spacing(p0, before=0, after=0, line=1.12)
        p_text(p0, pillar, size=8.0, color=BRAND.navy, bold=True)

        p1 = row.cells[1].paragraphs[0]
        p1.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        set_para_spacing(p1, before=0, after=0, line=1.18)
        p_text(p1, detail, size=8.2, color=BRAND.ink)
        append_source_links(p1, section)

        p2 = row.cells[2].paragraphs[0]
        p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
        set_para_spacing(p2, before=0, after=0, line=1.08)
        append_source_links(p2, section)

    spacer = document.add_paragraph()
    set_para_spacing(spacer, before=0, after=3, line=1)


def add_narrative_section(
    document,
    section: NarrativeSection,
    number: str | None = None,
    *,
    chart_specs: list[dict[str, object]] | None = None,
    tmp_dir: Path | None = None,
):
    """Render a deep-analysis narrative section with VCBS 2-column layout, charts, and CFA takeaways."""
    heading = section.heading
    new_page = getattr(section, "page_break_before", False)
    if number:
        paragraph = add_section_title(document, number, heading, section.subtitle)
    else:
        paragraph = document.add_paragraph()
        set_para_spacing(paragraph, before=10, after=2, line=1.05)
        paragraph.paragraph_format.keep_with_next = True
        p_text(paragraph, heading.upper(), size=11.5, color=BRAND.navy, bold=True, spacing=4)
        para_rule(paragraph, BRAND.crimson, 8)
        if section.subtitle:
            sub = document.add_paragraph()
            set_para_spacing(sub, before=1, after=4, line=1.1)
            p_text(sub, section.subtitle, size=7.6, color=BRAND.muted, italic=True)
    paragraph.paragraph_format.page_break_before = new_page

    clean_paragraphs = [t.strip() for t in section.paragraphs if t and t.strip()]
    clean_bullets = [b.strip() for b in section.bullets if b and b.strip()]
    has_chart = bool(chart_specs) and tmp_dir is not None
    use_vcbs_table = bool(new_page and not has_chart and clean_bullets)

    if clean_paragraphs:
        first_body = add_body(
            document,
            clean_paragraphs[0],
            size=10 if new_page else 9.5,
            after=2.5 if has_chart else 3.5,
        )
        if new_page:
            first_body.paragraph_format.line_spacing = 1.35
        append_source_links(first_body, section)

    if has_chart and chart_specs and tmp_dir is not None:
        # pyrefly: ignore[unnecessary-type-conversion]
        slug = re.sub(r"[^A-Za-z0-9_-]", "_", str(number or heading))[:24]
        add_vcbs_chart_pair(
            document,
            chart_specs,
            tmp_dir / f"vcbs_{slug}.png",
            height_in=2.05,
        )
    elif use_vcbs_table:
        add_vcbs_analytical_table(document, clean_bullets, section)

    if len(clean_paragraphs) >= 2:
        left_w = 4.8
        gap_w = 0.35
        right_w = CONTENT_W - left_w - gap_w
        split_table = fixed_table(document, [left_w, gap_w, right_w])
        split_row = add_row(split_table, [left_w, gap_w, right_w])
        row_flags(split_row)
        left_cell, _, right_cell = split_row.cells
        shade(left_cell, BRAND.blush)
        cell_border(left_cell, "left", BRAND.crimson, 18)
        cell_border(left_cell, "top", BRAND.line, 4)
        cell_border(left_cell, "bottom", BRAND.line, 4)
        set_cell_margins(left_cell, 85 if has_chart else 105, 120, 85 if has_chart else 105, 110)
        set_cell_margins(right_cell, 20, 40, 20, 0)

        kicker = left_cell.paragraphs[0]
        set_para_spacing(kicker, before=0, after=3, line=1.08)
        p_text(kicker, "TRỌNG TÂM PHÂN TÍCH", size=7.2, color=BRAND.crimson, bold=True)

        callout_text = section.subtitle or heading
        lead_par = left_cell.add_paragraph()
        set_para_spacing(lead_par, before=0, after=4, line=1.18)
        p_text(lead_par, callout_text, size=9.0, color=BRAND.navy, bold=True)

        sec_sources = datum_source_ids(getattr(document.part, "_research_report", None), section)
        if sec_sources:
            src_par = left_cell.add_paragraph()
            set_para_spacing(src_par, before=2, after=0, line=1.08)
            p_text(src_par, "Nguồn kiểm chứng: " + ", ".join(sec_sources), size=7.0, color=BRAND.muted, italic=True)

        paired_paragraphs = clean_paragraphs[1:3]
        for p_idx, text in enumerate(paired_paragraphs):
            r_par = right_cell.paragraphs[0] if p_idx == 0 else right_cell.add_paragraph()
            r_par.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            set_para_spacing(
                r_par,
                before=0,
                after=2.5 if has_chart else 3.5,
                line=1.22 if has_chart else 1.28,
            )
            _append_rich_text(r_par, text, size=9.5)
            append_source_links(r_par, section)

        spacer = document.add_paragraph()
        set_para_spacing(spacer, before=0, after=2, line=1)

        for text in clean_paragraphs[3:]:
            extra_par = body_par(
                document,
                after=2.5 if has_chart else 3.5,
                line=1.22 if has_chart else 1.28,
            )
            _append_rich_text(extra_par, text, size=9.5)
            append_source_links(extra_par, section)

    if clean_bullets and not use_vcbs_table:
        box = fixed_table(document, [CONTENT_W])
        box_row = add_row(box, [CONTENT_W])
        row_flags(box_row)
        b_cell = box_row.cells[0]
        shade(b_cell, BRAND.wash)
        cell_border(b_cell, "left", BRAND.navy, 18)
        cell_border(b_cell, "top", BRAND.line, 4)
        cell_border(b_cell, "bottom", BRAND.line, 4)
        set_cell_margins(b_cell, 75 if has_chart else 95, 150, 75 if has_chart else 95, 150)
        b_head = b_cell.paragraphs[0]
        set_para_spacing(b_head, before=0, after=2, line=1.08)
        b_head.paragraph_format.keep_with_next = True
        p_text(
            b_head,
            "ĐIỂM NHẤN PHÂN TÍCH & ĐIỀU KIỆN KIỂM ĐỊNH ĐẦU TƯ",
            size=7.4,
            color=BRAND.navy,
            bold=True,
        )
        for bullet in clean_bullets:
            b_par = b_cell.add_paragraph()
            b_par.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            set_para_spacing(b_par, before=1, after=1.5, line=1.20 if has_chart else 1.24)
            p_text(b_par, "▪  ", size=9.0, color="14532D", bold=True)
            _append_rich_text(b_par, bullet, size=9.2)
            append_source_links(b_par, section)

    sec_sources = datum_source_ids(getattr(document.part, "_research_report", None), section)
    if sec_sources:
        note = document.add_paragraph()
        set_para_spacing(note, before=2, after=3, line=1.05)
        p_text(note, "Nguồn dữ liệu: " + ", ".join(sec_sources), size=6.8, color=BRAND.muted, italic=True)


def add_comparison_table(document, table_spec: ComparisonTable):
    add_block_label(document, table_spec.title, BRAND.navy)
    if table_spec.subtitle:
        sub = document.add_paragraph()
        set_para_spacing(sub, before=0, after=3, line=1.1)
        p_text(sub, table_spec.subtitle, size=7.2, color=BRAND.muted, italic=True)
    if not table_spec.rows:
        return
    col_count = max(len(table_spec.columns), max((len(r.values) for r in table_spec.rows), default=0))
    left_w = 4.2
    note_w = 0
    if any(r.note for r in table_spec.rows):
        note_w = 2.6
    value_w = (CONTENT_W - left_w - note_w) / max(col_count, 1)
    widths = [left_w] + [value_w] * col_count + ([note_w] if note_w else [])
    table = fixed_table(document, widths)
    header = add_row(table, widths)
    row_flags(header, header=True)
    labels = ["CÔNG TY"] + [c.upper() for c in table_spec.columns] + (["GHI CHÚ"] if note_w else [])
    for i, (cell, label) in enumerate(zip(header.cells, labels + [""] * len(header.cells))):
        shade(cell, BRAND.deep)
        set_cell_margins(cell, 80, 85, 80, 85)
        cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.LEFT if i == 0 or (note_w and i == len(header.cells)-1) else WD_ALIGN_PARAGRAPH.RIGHT
        p_text(cell.paragraphs[0], label, size=6.6, color=BRAND.white, bold=True)
    for idx, row_spec in enumerate(table_spec.rows):
        row = add_row(table, widths)
        row_flags(row)
        values = list(row_spec.values) + [""] * col_count
        for i, cell in enumerate(row.cells):
            set_cell_margins(cell, 65, 85, 60, 85)
            shade(cell, BRAND.blush if idx % 2 == 1 else BRAND.white)
            cell_border(cell, "bottom", BRAND.line, 4)
            p = cell.paragraphs[0]
            set_para_spacing(p, before=0, after=0, line=1.05)
            if i == 0:
                p_text(p, row_spec.company, size=7.4, color=BRAND.navy, bold=True)
                if row_spec.ticker:
                    p_text(p, f"  ({row_spec.ticker})", size=6.8, color=BRAND.muted)
            elif note_w and i == len(row.cells) - 1:
                p_text(p, row_spec.note, size=6.2, color=BRAND.muted, italic=True)
            else:
                p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                p_text(p, values[i - 1], size=7.2, color=BRAND.ink)
                if i - 1 < len(row_spec.values):
                    evidence = row_spec.cell_evidence[i - 1] if row_spec.cell_evidence else row_spec
                    append_source_links(p, evidence)
    if table_spec.note:
        n = document.add_paragraph()
        set_para_spacing(n, before=2, after=5, line=1.1)
        p_text(n, table_spec.note, size=6.4, color=BRAND.muted, italic=True)


def add_sensitivity_table(document, table_spec: SensitivityTable):
    add_block_label(document, table_spec.title, BRAND.navy)
    if table_spec.subtitle:
        sub = document.add_paragraph()
        set_para_spacing(sub, before=0, after=3, line=1.1)
        p_text(sub, table_spec.subtitle, size=7.2, color=BRAND.muted, italic=True)
    if not table_spec.rows:
        return
    widths = [2.8, 2.8, 2.4, CONTENT_W - 2.8 - 2.8 - 2.4]
    table = fixed_table(document, widths)
    header = add_row(table, widths)
    row_flags(header, header=True)
    for cell, label in zip(header.cells, ("KỊCH BẢN", "GIÁ MỤC TIÊU", "TIỀM NĂNG", "GIẢ ĐỊNH CHÍNH")):
        shade(cell, BRAND.deep)
        set_cell_margins(cell, 80, 85, 80, 85)
        p_text(cell.paragraphs[0], label, size=6.6, color=BRAND.white, bold=True)
    tone_colors = {"positive": BRAND.green, "negative": BRAND.red, "base": BRAND.crimson, "neutral": BRAND.navy}
    tone_fills = {"positive": "F0FDF4", "negative": "FEF2F2", "base": BRAND.blush, "neutral": BRAND.white}
    for row_spec in table_spec.rows:
        row = add_row(table, widths)
        row_flags(row)
        fill = tone_fills.get(row_spec.tone, BRAND.white)
        accent = tone_colors.get(row_spec.tone, BRAND.navy)
        for i, cell in enumerate(row.cells):
            shade(cell, fill)
            set_cell_margins(cell, 70, 85, 65, 85)
            cell_border(cell, "bottom", BRAND.line, 4)
            if i == 0:
                cell_border(cell, "left", accent, 14)
        p_text(row.cells[0].paragraphs[0], row_spec.case.upper(), size=7.4, color=accent, bold=True)
        p_text(row.cells[1].paragraphs[0], row_spec.target_price, size=7.6, color=BRAND.navy, bold=True)
        p_text(row.cells[2].paragraphs[0], row_spec.upside, size=7.4, color=accent, bold=row_spec.tone != "neutral")
        p_text(row.cells[3].paragraphs[0], row_spec.assumptions, size=6.8, color=BRAND.ink)
        for cell in row.cells[1:]:
            append_source_links(cell.paragraphs[0], row_spec)
    if table_spec.note:
        n = document.add_paragraph()
        set_para_spacing(n, before=2, after=5, line=1.1)
        p_text(n, table_spec.note, size=6.4, color=BRAND.muted, italic=True)


def add_catalysts(document, catalysts: list[Catalyst]):
    if not catalysts:
        return
    add_block_label(document, "CHẤT XÚC TÁC VÀ SỰ KIỆN THEO DÕI", BRAND.navy)
    widths = [2.2, 5.4, 2.0, 2.0, CONTENT_W - 2.2 - 5.4 - 2.0 - 2.0]
    table = fixed_table(document, widths)
    header = add_row(table, widths)
    row_flags(header, header=True)
    for cell, label in zip(header.cells, ("THỜI GIAN", "CHẤT XÚC TÁC", "XÁC SUẤT", "TÁC ĐỘNG", "CHI TIẾT")):
        shade(cell, BRAND.deep)
        set_cell_margins(cell, 75, 80, 75, 80)
        p_text(cell.paragraphs[0], label, size=6.4, color=BRAND.white, bold=True)
    tone_colors = {"positive": BRAND.green, "negative": BRAND.red, "neutral": BRAND.navy}
    for idx, c in enumerate(catalysts):
        row = add_row(table, widths)
        row_flags(row)
        for cell in row.cells:
            set_cell_margins(cell, 65, 80, 60, 80)
            shade(cell, BRAND.blush if idx % 2 == 1 else BRAND.white)
            cell_border(cell, "bottom", BRAND.line, 4)
        accent = tone_colors.get(c.tone, BRAND.navy)
        p_text(row.cells[0].paragraphs[0], c.horizon, size=6.8, color=BRAND.muted, bold=True)
        p_text(row.cells[1].paragraphs[0], c.title, size=7.2, color=BRAND.navy, bold=True)
        p_text(row.cells[2].paragraphs[0], c.probability, size=6.8, color=BRAND.ink)
        p_text(row.cells[3].paragraphs[0], c.impact, size=6.8, color=accent, bold=True)
        p_text(row.cells[4].paragraphs[0], c.detail, size=6.6, color=BRAND.ink)
        for cell in row.cells:
            append_source_links(cell.paragraphs[0], c)
    spacer = document.add_paragraph()
    set_para_spacing(spacer, before=0, after=5, line=1)


def add_disclosure(document, report: ResearchReport):
    table = fixed_table(document, [CONTENT_W])
    row = add_row(table, [CONTENT_W])
    row_flags(row)
    cell = row.cells[0]
    shade(cell, BRAND.wash)
    cell_border(cell, "left", BRAND.navy, 18)
    set_cell_margins(cell, 130, 190, 130, 190)
    p_text(cell.paragraphs[0], "MIỄN TRỪ TRÁCH NHIỆM", size=7.2, color=BRAND.navy, bold=True, spacing=16)
    if report.demo:
        text = (
            "BẢN MINH HỌA — toàn bộ số liệu trong tài liệu này là dữ liệu giả lập do AI khởi tạo. "
            "Cần cân nhắc kỹ, không sử dụng để giao dịch hoặc đưa ra quyết định đầu tư."
        )
    else:
        text = (
            "Báo cáo này được tổng hợp và phân tích tự động bởi hệ thống Trí tuệ Nhân tạo (AI) của Vibe-Trading "
            "phục vụ mục đích tham khảo và nghiên cứu chuyên môn, không phải lời khuyên đầu tư cá nhân hay chỉ dẫn đặt lệnh. "
            "Dữ liệu phụ thuộc thời điểm chốt, độ trễ và phạm vi nguồn; mô hình định giá không bảo đảm giá thị trường tương lai. "
            "Do đặc thù phân tích bởi AI, nhà đầu tư cần cân nhắc kỹ lưỡng, tự thẩm định thông tin và chịu hoàn toàn trách nhiệm "
            "trước khi đưa ra bất kỳ quyết định đầu tư nào."
        )
    body = cell.add_paragraph()
    set_para_spacing(body, before=3, after=2, line=1.18)
    p_text(body, text, size=6.8, color=BRAND.ink)
    method = cell.add_paragraph()
    set_para_spacing(method, before=0, after=0, line=1.18)
    p_text(method, report.methodology, size=6.8, color=BRAND.muted)


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def make_docx(report: ResearchReport, path: Path):
    document = setup_document()
    document.part._research_report = report
    _build_running_header(document.sections[0], report)
    document.core_properties.subject = f"{report.symbol} | {report.data_as_of.isoformat()}"

    add_masthead(document, report)
    add_cover_title(document, report)
    add_rating_strip(document, report)
    add_metric_band(document, [*report.financial_metrics, *report.valuation_metrics])
    add_summary_split(document, report)
    add_highlights(document, report.key_stats)
    add_forecast_band(document, report.forecast_stats, report)
    add_cover_contents(document, report)

    overview_heading = add_section_title(
        document,
        "01",
        "Tổng quan doanh nghiệp",
        "Mô hình kinh doanh, vị thế cạnh tranh và động lực tăng trưởng",
    )
    overview_heading.paragraph_format.page_break_before = False
    overview = add_body(document, report.overview, size=9.2, after=3)
    append_source_links(overview, report.overview_evidence)
    # Every value must come from the validated report, including for FPT.

    fin_heading = add_section_title(
        document,
        "02",
        "Kết quả kinh doanh",
        "So sánh nhiều kỳ, cơ cấu lợi nhuận và chất lượng tăng trưởng",
    )
    fin_heading.paragraph_format.page_break_before = True
    if report.financial_table is not None:
        add_financial_table(document, report.financial_table)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        quarterly_png = tmp_path / "quarterly.png"
        if create_quarterly_chart(report.quarterly_results, quarterly_png):
            add_block_label(document, "KẾT QUẢ THEO KỲ", BRAND.navy)
            notes = "; ".join(dict.fromkeys(point.note for point in report.quarterly_results if point.note))
            add_chart(
                document,
                quarterly_png,
                notes or "Nguồn: chuỗi kết quả theo kỳ tại thời điểm chốt báo cáo.",
                evidence=report.quarterly_results,
            )

        price_heading = add_section_title(
            document,
            "03",
            "Diễn biến giá",
            "Xu hướng giá đóng cửa và thanh khoản trong kỳ quan sát",
        )
        price_heading.paragraph_format.page_break_before = False
        price_png = tmp_path / "price.png"
        if create_price_chart(report, price_png):
            add_chart(
                document,
                price_png,
                "Nguồn: chuỗi giá tại thời điểm chốt báo cáo; đây không phải dữ liệu thị trường trực tiếp.",
                evidence=report.price_history,
            )
        else:
            add_body(document, "Chưa có chuỗi giá đủ điều kiện để dựng biểu đồ.", size=9.0)

        add_section_title(
            document,
            "04",
            "Luận điểm đầu tư",
            "Các động lực chính và điều kiện để luận điểm có hiệu lực",
        )
        add_callout(
            document,
            "Các điểm chính",
            report.investment_theses,
            BRAND.teal,
            "Chưa đủ dữ liệu để kết luận về triển vọng tăng trưởng.",
        )

        add_section_title(
            document,
            "05",
            "Rủi ro cần theo dõi",
            "Các biến số có thể làm lệch kịch bản cơ sở",
        )
        add_callout(
            document,
            "Rủi ro trọng yếu",
            report.risk_factors,
            BRAND.red,
            "Chưa có danh sách rủi ro đã được đánh giá.",
        )

        section_no = 6
        figure_no = 1
        if report.analysis_sections:
            for section in report.analysis_sections:
                # Charts come only from this section's validated, source-bound data.
                specs = _section_chart_specs(report, section, figure_no)
                figure_no += len(specs)
                add_narrative_section(
                    document,
                    section,
                    number=f"{section_no:02d}",
                    chart_specs=specs,
                    tmp_dir=tmp_path,
                )
                section_no += 1

    val_heading = add_section_title(
        document,
        f"{section_no:02d}",
        "Định giá",
        "Phương pháp, giả thuyết và độ nhạy của giá mục tiêu",
    )
    val_heading.paragraph_format.page_break_before = any(
        section.page_break_before for section in report.analysis_sections
    )
    section_no += 1
    add_metric_table(
        document,
        "Chỉ số định giá",
        report.valuation_metrics,
        empty_note="Chưa có chỉ số định giá được kiểm chứng.",
    )
    if report.valuation_scenarios is not None:
        add_sensitivity_table(document, report.valuation_scenarios)

    if report.peer_comparison is not None:
        add_section_title(
            document,
            f"{section_no:02d}",
            "So sánh cùng ngành",
            "Định giá tương đối và vị thế cạnh tranh",
        )
        section_no += 1
        add_comparison_table(document, report.peer_comparison)

    if report.catalysts:
        add_section_title(
            document,
            f"{section_no:02d}",
            "Chất xúc tác và lịch sự kiện",
            "Các yếu tố có thể thay đổi định giá trong 12 tháng tới",
        )
        section_no += 1
        add_catalysts(document, report.catalysts)

    add_section_title(
        document,
        f"{section_no:02d}",
        "Nguồn dữ liệu và phương pháp",
        "Mỗi con số gắn với một nguồn, một thời điểm và một đơn vị",
    )
    section_no += 1
    add_body(document, report.methodology, size=8.4)
    add_sources(document, report.sources)

    add_section_title(
        document,
        f"{section_no:02d}",
        "Xếp hạng, công bố và chuyên viên",
        "Thang điểm khuyến nghị, trách nhiệm nội dung và giới hạn sử dụng",
    )
    section_no += 1
    add_rating_scale(document, report.rating_scale)
    add_analyst_block(document, report)
    add_disclosure(document, report)

    if report.appendix_sections:
        appendix = document.add_paragraph()
        appendix.paragraph_format.page_break_before = True
        set_para_spacing(appendix, before=0, after=4, line=1.05)
        p_text(appendix, "PHỤ LỤC", size=16, color=BRAND.crimson, bold=True, spacing=18)
        para_rule(appendix, BRAND.crimson, 14)
        with tempfile.TemporaryDirectory() as appendix_tmp:
            for index, section in enumerate(report.appendix_sections, 1):
                specs = _section_chart_specs(report, section, figure_no)
                figure_no += len(specs)
                add_narrative_section(
                    document,
                    section,
                    number=f"PL{index}",
                    chart_specs=specs,
                    tmp_dir=Path(appendix_tmp),
                )

    path.parent.mkdir(parents=True, exist_ok=True)
    document.save(path)
    return path


# ---------------------------------------------------------------------------
# PDF conversion and export
# ---------------------------------------------------------------------------


def find_soffice() -> str | None:
    """Find LibreOffice or OpenOffice executable across environments.

    An operator override wins, because a per-user or portable extraction is the
    only option when the machine-wide MSI cannot be installed (it needs admin
    rights). ``VIBE_SOFFICE`` therefore names an absolute executable, and the
    search also covers the unpacked-package layout this app ships.
    """
    override = os.environ.get("VIBE_SOFFICE", "").strip()
    if override and os.path.isfile(override):
        return override
    exe = shutil.which("libreoffice") or shutil.which("soffice")
    if exe:
        return exe
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    candidates = [
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        os.path.join(os.environ.get("ProgramW6432", r"C:\Program Files"), "LibreOffice", "program", "soffice.exe"),
        os.path.join(local_appdata, "LibreOffice", "program", "soffice.exe") if local_appdata else "",
        os.path.join(local_appdata, "Programs", "LibreOffice", "program", "soffice.exe") if local_appdata else "",
        "/usr/bin/libreoffice",
        "/usr/bin/soffice",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    ]
    # A checkout-local unpacked LibreOffice (from ``msiexec /a``) keeps the PDF
    # path working on hosts where the machine-wide install is not permitted.
    project_root = Path(__file__).resolve().parents[3]
    candidates.extend(str(path) for path in (
        project_root / "tools" / "libreoffice" / "program" / "soffice.exe",
        project_root / "vendor" / "libreoffice" / "program" / "soffice.exe",
    ))
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate
    return None


def convert_pdf(docx_path: Path, out_dir: Path):
    exe = find_soffice()
    if not exe:
        raise RuntimeError("Cần cài LibreOffice/soffice để xuất PDF từ DOCX")
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="vibe-lo-") as profile, \
            tempfile.TemporaryDirectory(prefix="vibe-pdf-", dir=out_dir) as converted_dir:
        cmd = [
            exe,
            f"-env:UserInstallation={Path(profile).as_uri()}",
            "--headless",
            "--convert-to",
            "pdf:writer_pdf_Export",
            "--outdir",
            converted_dir,
            str(docx_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
        pdf = Path(converted_dir) / f"{docx_path.stem}.pdf"
        if result.returncode != 0 or not pdf.exists() or pdf.stat().st_size < 1000:
            raise RuntimeError(f"PDF export failed: {result.stderr[-700:]}")
        return pdf.replace(out_dir / pdf.name)


def export_report(report: ResearchReport, root: Path, formats=("docx", "pdf")):
    """Render *report* and return a receipt of the artifacts that were written.

    A failed optional PDF never hides a successfully written DOCX, but it is
    reported in ``warnings`` so callers stop claiming that both formats exist.
    """
    if not set(formats).issubset({"docx", "pdf", "pptx"}) or not formats:
        raise ValueError("formats must be docx, pdf and/or pptx")
    job_id = uuid.uuid4().hex
    slug = re.sub(r"[^A-Za-z0-9_-]", "_", report.symbol)[:30]
    folder = root.resolve() / job_id
    folder.mkdir(parents=True, exist_ok=False)
    path = folder / f"VIBE_Research_{slug}_{report.data_as_of:%Y%m%d}.docx"
    make_docx(report, path)
    outputs: dict[str, object] = {"job_id": job_id, "warnings": []}
    if "docx" in formats:
        outputs["docx"] = str(path)
    if "pdf" in formats:
        try:
            outputs["pdf"] = str(convert_pdf(path, folder))
        except Exception as exc:
            # pyrefly: ignore[missing-attribute]
            outputs["warnings"].append(f"PDF export failed: {exc}")
            if len(formats) == 1:
                raise
    if "pptx" in formats:
        from src.reporting.presentation import make_pptx
        try:
            outputs["pptx"] = str(make_pptx(report, folder / f"{path.stem}.pptx"))
        except Exception as exc:
            # pyrefly: ignore[missing-attribute]
            outputs["warnings"].append(f"PPTX export failed: {exc}")
            if len(formats) == 1:
                raise
    if "docx" not in formats:
        path.unlink(missing_ok=True)
    return outputs
