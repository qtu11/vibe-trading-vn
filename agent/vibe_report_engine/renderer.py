"""Create an editable brand-controlled DOCX and a visually equivalent PDF.

AI never supplies layout, styles, filesystem paths, images or arbitrary document XML.
"""
from __future__ import annotations
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from docx.enum.style import WD_STYLE_TYPE

from brand import BRAND, Brand
from schema import Claim, Metric, Recommendation, ResearchReport

HERE = Path(__file__).resolve().parent


def rgb(hex_color: str) -> RGBColor:
    return RGBColor.from_string(hex_color)


def shade(cell, fill: str):
    tc_pr = cell._tc.get_or_add_tcPr()
    existing = tc_pr.find(qn("w:shd"))
    if existing is not None:
        tc_pr.remove(existing)
    node = OxmlElement("w:shd")
    node.set(qn("w:fill"), fill)
    tc_pr.append(node)


def border_bottom(cell, color: str = BRAND.line, size: str = "5"):
    tcPr = cell._tc.get_or_add_tcPr()
    borders = tcPr.find(qn("w:tcBorders"))
    if borders is None:
        borders = OxmlElement("w:tcBorders")
        tcPr.append(borders)
    edge = OxmlElement("w:bottom")
    edge.set(qn("w:val"), "single")
    edge.set(qn("w:sz"), size)
    edge.set(qn("w:color"), color)
    borders.append(edge)


def set_cell_margins(cell, top=120, start=135, bottom=120, end=135):
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    margins = tcPr.first_child_found_in("w:tcMar")
    if margins is None:
        margins = OxmlElement("w:tcMar")
        tcPr.append(margins)
    for tag, val in (("top",top),("start",start),("bottom",bottom),("end",end)):
        x = margins.find(qn(f"w:{tag}"))
        if x is None:
            x = OxmlElement(f"w:{tag}")
            margins.append(x)
        x.set(qn("w:w"), str(val))
        x.set(qn("w:type"), "dxa")


def no_split(row):
    trPr = row._tr.get_or_add_trPr()
    trPr.append(OxmlElement("w:cantSplit"))


def p_text(paragraph, text: str, *, size=9, color=None, bold=False):
    run = paragraph.add_run(text)
    run.bold = bold
    run.font.name = BRAND.font
    run.font.size = Pt(size)
    run.font.color.rgb = rgb(color or BRAND.ink)
    return run


def set_para_spacing(paragraph, before=0, after=0, line=1.18):
    fmt = paragraph.paragraph_format
    fmt.space_before = Pt(before)
    fmt.space_after = Pt(after)
    fmt.line_spacing = line


def page_field(paragraph):
    r = paragraph.add_run()
    begin = OxmlElement("w:fldChar"); begin.set(qn("w:fldCharType"), "begin")
    instruction = OxmlElement("w:instrText")
    instruction.set(qn("xml:space"), "preserve")
    instruction.text = " PAGE "
    sep = OxmlElement("w:fldChar"); sep.set(qn("w:fldCharType"), "separate")
    cached = OxmlElement("w:t"); cached.text = "1"
    end = OxmlElement("w:fldChar"); end.set(qn("w:fldCharType"), "end")
    for x in (begin, instruction, sep, cached, end):
        r._r.append(x)


def setup_document():
    d = Document()
    s = d.sections[0]
    s.page_width = Cm(21)
    s.page_height = Cm(29.7)
    s.top_margin = Cm(2.15)
    s.bottom_margin = Cm(1.7)
    s.left_margin = Cm(1.8)
    s.right_margin = Cm(1.8)
    s.header_distance = Cm(0.75)
    s.footer_distance = Cm(0.85)
    styles = d.styles
    base = styles["Normal"]
    base.font.name = BRAND.font
    base.font.size = Pt(9)
    base.font.color.rgb = rgb(BRAND.ink)
    base.paragraph_format.line_spacing = 1.15
    base.paragraph_format.space_after = Pt(4)
    for name, size, col, spacing in [
        ("VT_H1", 17, BRAND.navy, 8),
        ("VT_H2", 12, BRAND.navy, 6),
        ("VT_SMALL", 8, BRAND.muted, 3),
    ]:
        style = styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        style.base_style = base
        style.font.name = BRAND.font
        style.font.size = Pt(size)
        style.font.color.rgb = rgb(col)
        style.font.bold = name != "VT_SMALL"
        style.paragraph_format.space_before = Pt(spacing)
        style.paragraph_format.space_after = Pt(4)
        style.paragraph_format.keep_with_next = name != "VT_SMALL"
    header = s.header.paragraphs[0]
    header.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    p_text(header, "VIBE", size=8, color=BRAND.green, bold=True)
    p_text(header, "-TRADING  /  RESEARCH DESK", size=8, color=BRAND.ink, bold=True)
    footer = s.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_text(footer, "VIBE RESEARCH   •   TÀI LIỆU NGHIÊN CỨU   •   ", size=7, color=BRAND.muted)
    p_text(footer, "TRANG ", size=7, color=BRAND.muted)
    page_field(footer)
    d.core_properties.title = "Vibe-Trading Equity Research"
    d.core_properties.author = "Vibe-Trading Report Engine"
    return d


def add_section_title(d, num, title):
    p = d.add_paragraph(style="VT_H1")
    p_text(p, f"{num}  /  ", size=16, color=BRAND.green, bold=True)
    p_text(p, title, size=16, color=BRAND.navy, bold=True)
    return p


def add_body(d, text):
    p = d.add_paragraph()
    p_text(p, text, size=9, color=BRAND.ink)
    set_para_spacing(p, after=5, line=1.22)
    return p


def add_tag(d, text):
    p = d.add_paragraph()
    p_text(p, text.upper(), size=7, color=BRAND.green, bold=True)
    set_para_spacing(p, after=4)


def add_masthead(d, r):
    tab = d.add_table(rows=1, cols=2)
    tab.autofit = False
    tab.columns[0].width = Cm(9.6)
    tab.columns[1].width = Cm(7.6)
    left, right = tab.rows[0].cells
    for c in [left, right]:
        shade(c, BRAND.navy)
        set_cell_margins(c, 180, 240, 210, 240)
    logo = HERE / "assets" / "vibe_logo.png"
    par = left.paragraphs[0]
    par.alignment = WD_ALIGN_PARAGRAPH.LEFT
    if logo.exists():
        par.add_run().add_picture(str(logo), width=Cm(5.0))
    else:
        p_text(par, BRAND.name, size=20, bold=True, color=BRAND.white)
    p_text(left.add_paragraph(), "INTELLIGENT MARKET RESEARCH", size=7.5, color=BRAND.cyan)
    r1 = right.paragraphs[0]
    r1.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    p_text(r1, "EQUITY  /  QUANT  /  AI", size=8, color=BRAND.cyan, bold=True)
    r2 = right.add_paragraph()
    r2.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    p_text(r2, f"DATA AS OF  {r.data_as_of.strftime('%d.%m.%Y')}", size=8, color=BRAND.white)
    r3 = right.add_paragraph(); r3.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    p_text(r3, "DEMO • CHỈ MINH HỌA" if r.demo else "RESEARCH NOTE • NOT A TRADE ORDER", size=7, color=BRAND.cyan)
    d.add_paragraph().paragraph_format.space_after = Pt(0)


def add_hero(d, r):
    add_tag(d, f"{r.market.value}  /  {r.exchange}  /  {r.symbol}")
    p = d.add_paragraph()
    p_text(p, r.company_name.upper(), size=21, color=BRAND.navy, bold=True)
    set_para_spacing(p, after=1)
    p = d.add_paragraph()
    p_text(p, r.title, size=15, color=BRAND.green, bold=True)
    set_para_spacing(p, after=3)
    p = d.add_paragraph()
    p_text(p, r.subtitle, size=9, color=BRAND.muted)
    set_para_spacing(p, after=8)
    t = d.add_table(rows=1, cols=2)
    t.autofit = False
    t.columns[0].width = Cm(10.8)
    t.columns[1].width = Cm(6.4)
    a, b = t.rows[0].cells
    for c in (a,b):
        shade(c, BRAND.mint if c == a else BRAND.deep)
        set_cell_margins(c, 180, 200, 150, 200)
    p_text(a.paragraphs[0], "LUẬN ĐIỂM ĐẦU TƯ", size=8, bold=True, color=BRAND.green)
    p_text(a.add_paragraph(), r.executive_summary, size=9.2, color=BRAND.ink)
    p_text(b.paragraphs[0], "ĐÁNH GIÁ", size=8, color=BRAND.cyan, bold=True)
    label = r.recommendation.value
    p_text(b.add_paragraph(), label, size=20 if len(label)<10 else 12, color=BRAND.white, bold=True)
    p_text(b.add_paragraph(), f"Tầm nhìn: {r.investment_horizon}", size=8, color=BRAND.cyan)
    d.add_paragraph().paragraph_format.space_after = Pt(0)


def display_metric(m):
    if m.value is None:
        return "N/A"
    f = f"{m.value:,.{m.decimals}f}".replace(",", " ")
    return (f + (" " + m.unit if m.unit else "")).strip()


def add_metric_band(d, metrics):
    choice = {m.key: m for m in metrics}
    keys = ["market_price", "target_price", "upside", "pe"]
    items = [choice.get(k) for k in keys]
    t = d.add_table(rows=1, cols=4)
    t.autofit = False
    for i, cell in enumerate(t.rows[0].cells):
        shade(cell, "F2F7F8")
        set_cell_margins(cell, 150, 150, 160, 110)
        if items[i]:
            p_text(cell.paragraphs[0], items[i].label.upper(), size=7, color=BRAND.muted, bold=True)
            p_text(cell.add_paragraph(), display_metric(items[i]), size=13, color=BRAND.green if i==2 else BRAND.navy, bold=True)
        else:
            p_text(cell.paragraphs[0], "CHƯA CÓ", size=7, color=BRAND.muted)
    d.add_paragraph().paragraph_format.space_after = Pt(0)


def create_price_chart(r, png_path):
    if len(r.price_history) < 2:
        return False
    x = [p.date for p in r.price_history]
    y = [p.close for p in r.price_history]
    fig, ax = plt.subplots(figsize=(10.4,2.8), dpi=155)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    ax.plot(x, y, color="#13BBA9", lw=2.5, zorder=5)
    ax.fill_between(x, y, min(y)*0.94, color="#C9F1E9", alpha=0.75)
    ax.grid(True, color="#E7EDEF", lw=0.8)
    ax.tick_params(colors="#738391", labelsize=8, length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.margins(x=0.02, y=0.08)
    ax.set_ylabel("Giá đóng cửa (minh họa)" if r.demo else "Giá đóng cửa", fontsize=8, color="#6B7C89")
    fig.autofmt_xdate(rotation=0)
    fig.tight_layout(pad=1.6)
    fig.savefig(png_path, dpi=155, facecolor="white")
    plt.close(fig)
    return True


def add_metric_table(d, title, items):
    p = d.add_paragraph(style="VT_H2")
    p_text(p, title, color=BRAND.navy, bold=True, size=12)
    if not items:
        add_body(d, "Không có số liệu được kiểm chứng tại thời điểm phát hành.")
        return
    tbl = d.add_table(rows=1, cols=3)
    tbl.autofit = False
    tbl.columns[0].width = Cm(7.9)
    tbl.columns[1].width = Cm(4.2)
    tbl.columns[2].width = Cm(5.1)
    for i, val in enumerate(("CHỈ TIÊU", "GIÁ TRỊ", "NGUỒN / KỲ")):
        c = tbl.rows[0].cells[i]
        shade(c, BRAND.navy); set_cell_margins(c, 115, 130, 115, 130)
        p_text(c.paragraphs[0], val, size=8, color=BRAND.white, bold=True)
    no_split(tbl.rows[0])
    for idx, item in enumerate(items):
        row = tbl.add_row()
        no_split(row)
        for c in row.cells:
            set_cell_margins(c, 105, 130, 95, 130)
            if idx%2 == 0:
                shade(c, "F3F8F8")
            border_bottom(c)
        p_text(row.cells[0].paragraphs[0], item.label, size=8.5)
        p_text(row.cells[1].paragraphs[0], display_metric(item), size=8.5, color=BRAND.navy, bold=True)
        src = ", ".join(item.source_ids) or "CHƯA CÓ"
        stamp = item.as_of.strftime("%d/%m/%Y") if item.as_of else "n/a"
        p_text(row.cells[2].paragraphs[0], f"[{src}]  {stamp}", size=7.5, color=BRAND.muted)
    d.add_paragraph().paragraph_format.space_after = Pt(0)


def add_claims(d, claims, fallback):
    if not claims:
        add_body(d, fallback)
        return
    for i, item in enumerate(claims, 1):
        p = d.add_paragraph()
        p.paragraph_format.keep_with_next = True
        p_text(p, f"{i:02d}  ", size=9, color=BRAND.green, bold=True)
        p_text(p, item.title, size=9.4, color=BRAND.navy, bold=True)
        set_para_spacing(p, before=3, after=2)
        p = d.add_paragraph()
        p_text(p, item.body, size=8.8)
        set_para_spacing(p, after=2)
        p = d.add_paragraph()
        p_text(p, "NGUỒN: " + (", ".join(f"[{s}]" for s in item.source_ids) or "Chưa xác minh"),
               size=7, color=BRAND.muted)
        set_para_spacing(p, after=1)


def add_sources(d, sources):
    tbl = d.add_table(rows=1, cols=3)
    tbl.autofit = False
    tbl.columns[0].width = Cm(2.0)
    tbl.columns[1].width = Cm(10.6)
    tbl.columns[2].width = Cm(4.6)
    for c, text in zip(tbl.rows[0].cells, ["MÃ", "TÀI LIỆU / NHÀ CUNG CẤP", "TRẠNG THÁI"]):
        shade(c, BRAND.navy); set_cell_margins(c, 90, 100, 90, 100)
        p_text(c.paragraphs[0], text, size=7.7, color=BRAND.white, bold=True)
    if not sources:
        add_body(d, "Không có nguồn dữ liệu.")
        return
    for i, src in enumerate(sources):
        rw = tbl.add_row(); no_split(rw)
        for c in rw.cells:
            set_cell_margins(c, 95, 100, 80, 100)
            if i%2==0: shade(c, "F2F7F8")
            border_bottom(c)
        p_text(rw.cells[0].paragraphs[0], f"[{src.id}]", size=7.4, color=BRAND.green, bold=True)
        p_text(rw.cells[1].paragraphs[0], src.title, size=7.5, color=BRAND.ink)
        p_text(rw.cells[1].add_paragraph(), f"{src.provider}   {str(src.url) if src.url else '(nguồn nội bộ)'}", size=6.5, color=BRAND.muted)
        p_text(rw.cells[2].paragraphs[0], src.status.upper(), size=7, color=BRAND.ink)


def make_docx(report: ResearchReport, path: Path):
    d = setup_document()
    d.core_properties.subject = f"{report.symbol} | {report.data_as_of.isoformat()}"
    add_masthead(d, report)
    add_hero(d, report)
    add_metric_band(d, [*report.financial_metrics, *report.valuation_metrics])
    add_section_title(d, "01", "Tổng quan doanh nghiệp")
    add_body(d, report.overview)
    add_section_title(d, "02", "Diễn biến thị trường")
    with tempfile.TemporaryDirectory() as tmp:
        png = Path(tmp) / "chart.png"
        if create_price_chart(report, png):
            par = d.add_paragraph()
            par.alignment = WD_ALIGN_PARAGRAPH.CENTER
            par.add_run().add_picture(str(png), width=Cm(16.6))
            set_para_spacing(par, after=2)
            p = d.add_paragraph(style="VT_SMALL")
            p_text(p, "Biểu đồ tạo từ price_history trong snapshot báo cáo; không lấy dữ liệu trực tiếp từ Internet.", size=7, color=BRAND.muted)
        else:
            add_body(d, "Chưa có chuỗi giá đủ điều kiện để dựng biểu đồ.")
    p = add_section_title(d, "03", "Hiệu quả tài chính và định giá")
    p.paragraph_format.page_break_before = True
    add_metric_table(d, "Chỉ số tài chính", report.financial_metrics)
    add_metric_table(d, "Chỉ số định giá", report.valuation_metrics)
    add_section_title(d, "04", "Luận điểm đầu tư")
    add_claims(d, report.investment_theses, "Chưa đủ dữ liệu để kết luận về triển vọng tăng trưởng.")
    add_section_title(d, "05", "Rủi ro cần theo dõi")
    add_claims(d, report.risk_factors, "Chưa có danh sách rủi ro đã được đánh giá.")
    p = add_section_title(d, "06", "Dữ liệu, nguồn và phương pháp")
    p.paragraph_format.page_break_before = True
    add_body(d, report.methodology)
    add_metric_table(d, "Tóm tắt tham chiếu", [m for m in report.financial_metrics if m.key in ("market_price", "market_cap")])
    add_sources(d, report.sources)
    d.add_paragraph().paragraph_format.space_after=Pt(2)
    add_section_title(d, "07", "Công bố và giới hạn sử dụng")
    if report.demo:
        add_body(d, "BẢN MINH HỌA - TOÀN BỘ SỐ LIỆU TRONG TÀI LIỆU NÀY LÀ DỮ LIỆU GIẢ LẬP. KHÔNG SỬ DỤNG ĐỂ GIAO DỊCH HOẶC ĐƯA RA QUYẾT ĐỊNH ĐẦU TƯ.")
    else:
        add_body(d, "Báo cáo phục vụ nghiên cứu, không phải chỉ dẫn đặt lệnh. Dữ liệu phụ thuộc thời điểm chốt, độ trễ và phạm vi nguồn. Định giá là mô hình giả định, không bảo đảm giá thị trường tương lai. Người đọc phải tự đánh giá rủi ro và sự phù hợp.")
    add_body(d, "Mỗi con số phải có as_of, đơn vị, source_id và snapshot tương ứng. Kết quả AI phải được review bằng quy tắc dữ liệu và phương pháp định lượng; không tự coi nội dung của mô hình là bằng chứng độc lập.")
    path.parent.mkdir(parents=True, exist_ok=True)
    d.save(path)
    return path


def convert_pdf(docx_path: Path, out_dir: Path):
    exe = shutil.which("libreoffice") or shutil.which("soffice")
    if not exe:
        raise RuntimeError("Cần cài LibreOffice/soffice để xuất PDF từ DOCX")
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="vibe-lo-") as profile:
        # Isolated profile is essential when requests run concurrently.
        cmd = [exe, f"-env:UserInstallation={Path(profile).as_uri()}", "--headless", "--convert-to",
               "pdf:writer_pdf_Export", "--outdir", str(out_dir), str(docx_path)]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=90, check=False)
        pdf = out_dir / f"{docx_path.stem}.pdf"
        if result.returncode != 0 or not pdf.exists() or pdf.stat().st_size < 1000:
            raise RuntimeError(f"PDF export failed: {result.stderr[-700:]}")
        return pdf


def export_report(report: ResearchReport, root: Path, formats=("docx", "pdf")):
    if not set(formats).issubset({"docx", "pdf"}) or not formats:
        raise ValueError("formats must be docx and/or pdf")
    # Never derive a writable absolute path from a user/LLM-controlled value.
    job_id = uuid.uuid4().hex
    slug = re.sub(r"[^A-Za-z0-9_-]", "_", report.symbol)[:30]
    folder = root.resolve() / job_id
    folder.mkdir(parents=True, exist_ok=False)
    path = folder / f"VIBE_Research_{slug}_{report.data_as_of:%Y%m%d}.docx"
    make_docx(report, path)
    outputs = {"job_id": job_id}
    if "docx" in formats: outputs["docx"] = str(path)
    if "pdf" in formats: outputs["pdf"] = str(convert_pdf(path, folder))
    if "docx" not in formats: path.unlink(missing_ok=True)
    return outputs
