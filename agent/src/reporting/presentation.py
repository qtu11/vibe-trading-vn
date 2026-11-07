"""Editable research slides from the same validated report used by Word/PDF."""

from pathlib import Path
import tempfile
import math

from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.util import Inches, Pt

from src.reporting.brand import BRAND, resolve_brand_logo
from src.reporting.citations import datum_sources
from src.reporting.schema import DatumEvidence, ResearchReport


def make_pptx(report: ResearchReport, path: Path) -> Path:
    from src.reporting.renderer import (
        create_price_chart,
        create_quarterly_chart,
        display_metric,
        _section_chart_specs,
        create_vcbs_combo_pair_png,
    )

    deck = Presentation()
    deck.slide_width, deck.slide_height = Inches(13.333), Inches(7.5)
    logo = resolve_brand_logo()

    def textbox(slide, x, y, w, h, text, size=16, color=BRAND.ink, bold=False):
        box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        box.text_frame.word_wrap = True
        box.text_frame.margin_left = box.text_frame.margin_right = 0
        paragraph = box.text_frame.paragraphs[0]
        run = paragraph.add_run()
        run.text = str(text)
        run.font.name, run.font.size = BRAND.font, Pt(size)
        run.font.color.rgb, run.font.bold = RGBColor.from_string(color), bold
        return box

    def new_slide(title, subtitle=""):
        slide = deck.slides.add_slide(deck.slide_layouts[6])
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = RGBColor.from_string(BRAND.white)
        rule = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, deck.slide_width, Inches(0.12))
        rule.fill.solid()
        rule.fill.fore_color.rgb = RGBColor.from_string(BRAND.crimson)
        rule.line.fill.background()
        textbox(slide, 0.6, 0.35, 11.5, 0.45, title, 25, BRAND.navy, True)
        textbox(slide, 0.6, 0.95, 11.5, 0.55, subtitle, 11, BRAND.muted)
        textbox(
            slide,
            0.6,
            7.1,
            10.5,
            0.2,
            f"VIBE-TRADING RESEARCH · {report.symbol} / {report.exchange} · {report.data_as_of:%d/%m/%Y} · DỰ THẢO",
            8,
            BRAND.muted,
        )
        textbox(slide, 12, 7.05, 0.7, 0.3, str(len(deck.slides)), 9, BRAND.crimson)
        return slide

    def attributed(slide, y, text, evidence, *, size=16, height=None):
        height = height or (max(1, math.ceil((len(text) + 45) / 90)) * 0.28 + 0.12)
        box = textbox(slide, 0.75, y, 11.8, min(height, 6.85 - y), text, size)
        paragraph = box.text_frame.paragraphs[0]
        kind = getattr(evidence, "evidence_kind", "cited")
        if kind in ("derived", "assumption"):
            run = paragraph.add_run()
            run.text = " [suy ra]" if kind == "derived" else " [giả định]"
            run.font.size = Pt(10)
        for source in datum_sources(report, evidence):
            run = paragraph.add_run()
            run.text = f" [{source.id}]"
            run.hyperlink.address = str(source.url)
            run.font.size = Pt(10)
            run.font.color.rgb = RGBColor.from_string(BRAND.crimson)
        return box

    def section(title, paragraphs, evidence):
        slide, y = new_slide(title), 1.65
        for paragraph in paragraphs:
            content, item = paragraph if isinstance(paragraph, tuple) else (paragraph, evidence)
            # shortcut: conservative character pagination for the installed Arial face; use measured font layout for arbitrary font families.
            for start in range(0, len(content), 950):
                text = content[start : start + 950]
                height = max(1, math.ceil((len(text) + 45) / 90)) * 0.28 + 0.12
                if y + height > 6.85:
                    slide, y = new_slide(title, "Tiếp theo"), 1.65
                attributed(slide, y, text, item, height=height)
                y += height + 0.12

    cover = new_slide(f"{report.symbol} · {report.company_name}", report.report_type)
    if logo:
        cover.shapes.add_picture(str(logo), Inches(0.8), Inches(1.55), height=Inches(1.25))
    textbox(cover, 2.4, 1.75, 9.5, 1.2, report.title, 30, BRAND.crimson, True)
    textbox(cover, 0.8, 3.25, 11.7, 0.65, report.subtitle, 18, BRAND.muted)
    textbox(cover, 0.8, 4.25, 11.7, 0.6, report.recommendation.value, 26, BRAND.navy, True)
    textbox(
        cover,
        0.8,
        5.25,
        11.7,
        0.6,
        "Mỗi ký hiệu nguồn là URL bấm được. Giá trị giả định và giá tham chiếu được ghi riêng.",
        15,
        BRAND.muted,
    )
    section("Tóm tắt đầu tư", [report.executive_summary], report.executive_summary_evidence)
    section("Tổng quan", [report.overview], report.overview_evidence)
    metrics = [*report.financial_metrics, *report.valuation_metrics]
    for start in range(0, len(metrics), 6):
        slide = new_slide("Dữ liệu và định giá", "Giữ nguyên giá trị, đơn vị, ngày và nguồn của báo cáo")
        for offset, metric in enumerate(metrics[start : start + 6]):
            y = 1.6 + offset * 0.78
            date = metric.as_of.isoformat() if metric.as_of else "chưa có ngày"
            attributed(slide, y, f"{metric.label}: {display_metric(metric)} · {date}", metric, size=17)
    for title, stats in (("Điểm nhấn", report.key_stats), ("Dự phóng", report.forecast_stats)):
        for stat in stats:
            section(title, [f"{stat.label}: {stat.value}. {stat.note}"], stat)
    if report.financial_table:
        table = report.financial_table
        for row in table.rows:
            values = [
                (f"{column}: {value}", row.cell_evidence[index] if row.cell_evidence else row)
                for index, (column, value) in enumerate(zip(table.columns, row.values))
            ]
            section(table.title, [row.label, *values, row.note], row)
    with tempfile.TemporaryDirectory(prefix="vibe-slides-") as temp:
        for title, name, ready in (
            ("Giá và khối lượng", "price", create_price_chart(report, Path(temp) / "price.png")),
            (
                "Kết quả theo kỳ",
                "quarterly",
                create_quarterly_chart(report.quarterly_results, Path(temp) / "quarterly.png"),
            ),
        ):
            if ready:
                slide = new_slide(title)
                chart = Path(temp) / f"{name}.png"
                with Image.open(chart) as image:
                    width, height = image.size
                scale = min(11.6 / width, 4.55 / height)
                slide.shapes.add_picture(
                    str(chart),
                    Inches((13.333 - width * scale) / 2),
                    Inches(1.55),
                    width=Inches(width * scale),
                    height=Inches(height * scale),
                )
                points = report.price_history if name == "price" else report.quarterly_results
                source_ids = list(
                    dict.fromkeys(source.id for point in points for source in datum_sources(report, point))
                )
                attributed(slide, 6.35, "Nguồn dữ liệu biểu đồ:", DatumEvidence(source_ids=source_ids), size=10)
    for heading, claims in (("Luận điểm đầu tư", report.investment_theses), ("Rủi ro", report.risk_factors)):
        for claim in claims:
            section(f"{heading} · {claim.title}", [claim.body], claim)
    figure_no = 1
    for item in [*report.analysis_sections, *report.appendix_sections]:
        section(item.heading, [*item.paragraphs, *(f"• {b}" for b in item.bullets)], item)
        specs = _section_chart_specs(report, item, figure_no)
        figure_no += len(specs)
        with tempfile.TemporaryDirectory(prefix="vibe-section-slides-") as temp:
            for index, spec in enumerate(specs):
                chart = Path(temp) / f"chart-{index}.png"
                if create_vcbs_combo_pair_png([spec], chart, height_in=2.5):
                    slide = new_slide(item.heading, str(spec["caption"]))
                    with Image.open(chart) as image:
                        width, height = image.size
                    scale = min(11.6 / width, 4.55 / height)
                    slide.shapes.add_picture(
                        str(chart),
                        Inches((13.333 - width * scale) / 2),
                        Inches(1.55),
                        width=Inches(width * scale),
                        height=Inches(height * scale),
                    )
                    attributed(slide, 6.35, "Nguồn dữ liệu biểu đồ:", spec["evidence"], size=10)
    if report.peer_comparison:
        for row in report.peer_comparison.rows:
            values = [
                (f"{column}: {value}", row.cell_evidence[index] if row.cell_evidence else row)
                for index, (column, value) in enumerate(zip(report.peer_comparison.columns, row.values))
            ]
            section(
                report.peer_comparison.title,
                [row.company, *values, row.note],
                row,
            )
    if report.valuation_scenarios:
        for row in report.valuation_scenarios.rows:
            section(f"Kịch bản · {row.case}", [f"{row.target_price} · {row.upside}", row.assumptions], row)
    for catalyst in report.catalysts:
        section(
            catalyst.title,
            [f"{catalyst.horizon} · {catalyst.detail} · {catalyst.probability} · {catalyst.impact}"],
            catalyst,
        )
    for source in report.sources:
        slide = new_slide(f"Nguồn {source.id}", source.status)
        box = textbox(slide, 0.8, 1.65, 11.7, 4.8, f"{source.title}\n{source.provider}", 20)
        if source.url:
            run = box.text_frame.add_paragraph().add_run()
            run.text = str(source.url)
            run.hyperlink.address = str(source.url)
            run.font.size = Pt(13)
    section(
        "Phương pháp và giới hạn",
        [
            report.methodology,
            "Phân tích dự thảo, chưa có chuyên viên phê duyệt. Dữ liệu có thể chậm; cập nhật giá, giả định và rủi ro trước khi quyết định.",
        ],
        report.executive_summary_evidence,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    deck.save(path)
    return path
