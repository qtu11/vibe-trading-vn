"""Rendering regressions that can change an investment report's meaning."""

from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from docx.oxml.ns import qn
from docx.shared import Cm
from matplotlib.patches import FancyBboxPatch

from src.reporting import renderer
from src.reporting.schema import (
    Catalyst,
    ComparisonTable,
    KeyStat,
    Market,
    Metric,
    NarrativeSection,
    PeriodPoint,
    PricePoint,
    ResearchReport,
)


def report(**updates):
    values = dict(
        market=Market.VN_EQUITY, symbol="TEST", exchange="TEST",
        company_name="Công ty kiểm thử", title="Báo cáo kiểm thử thiết kế",
        subtitle="Dữ liệu giả lập cho kiểm thử renderer", data_as_of=date(2026, 11, 6),
        overview="Tổng quan doanh nghiệp phục vụ kiểm thử.",
        executive_summary="Tóm tắt phục vụ kiểm thử thiết kế báo cáo.", demo=True,
    )
    values.update(updates)
    return ResearchReport.model_construct(**values)


@pytest.fixture
def chart_capture(monkeypatch):
    figures = []

    def capture(canvas, *args, **kwargs):
        figures.append(canvas.figure)

    monkeypatch.setattr(renderer.FigureCanvasAgg, "print_figure", capture)
    return figures


@pytest.mark.parametrize("values", [(-10, -20), (-30, 10), (0, 0)])
def test_quarterly_chart_includes_losses_and_zero(values, chart_capture, tmp_path):
    points = [PeriodPoint(period=f"Q{i}", value=value) for i, value in enumerate(values)]
    assert renderer.create_quarterly_chart(points, tmp_path / "quarterly.png")
    figure = chart_capture[0]
    axes = figure.axes[0]
    low, high = axes.get_ylim()
    assert low <= min(0, *values) <= max(0, *values) < high
    assert [bar.get_height() for bar in axes.patches] == list(values)
    for value, annotation in zip(values, axes.texts):
        if value < 0:
            assert annotation.get_position()[1] < 0
            assert annotation.get_verticalalignment() == "top"
    assert any(isinstance(artist, FancyBboxPatch) for artist in figure.artists)


@pytest.mark.parametrize("target, color", [(140, renderer.BRAND.green), (70, renderer.BRAND.red)])
def test_price_chart_shows_upside_and_downside_targets(target, color, chart_capture, tmp_path):
    sample = report(
        price_history=[PricePoint(date=date(2026, 11, 4), close=100),
                       PricePoint(date=date(2026, 11, 5), close=102)],
        financial_metrics=[Metric(key="market_price", label="Giá", value=102,
                                  unit="USD", decimals=2)],
        valuation_metrics=[Metric(key="target_price", label="Mục tiêu", value=target,
                                  unit="USD", decimals=2)],
    )
    assert renderer.create_price_chart(sample, tmp_path / "price.png")
    price_axes, volume_axes = chart_capture[0].axes
    assert price_axes.get_ylim()[0] < target < price_axes.get_ylim()[1]
    assert price_axes.lines[1].get_color() == f"#{color}"
    assert f"Giá mục tiêu {target},00 USD" in [item.get_text() for item in price_axes.texts]
    assert "102,00 USD" in [item.get_text() for item in price_axes.texts]
    assert not volume_axes.patches
    assert "Không có dữ liệu khối lượng" in [item.get_text() for item in volume_axes.texts]


def test_daily_volume_bars_do_not_overlap_or_fill_missing_values(chart_capture, tmp_path):
    sample = report(price_history=[
        PricePoint(date=date(2026, 11, 3), close=100, volume=10),
        PricePoint(date=date(2026, 11, 4), close=101),
        PricePoint(date=date(2026, 11, 5), close=102, volume=20),
    ])
    renderer.create_price_chart(sample, tmp_path / "volume.png")
    bars = chart_capture[0].axes[1].patches
    assert len(bars) == 2
    assert [bar.get_height() for bar in bars] == [10, 20]
    assert all(0 < bar.get_width() < 1 for bar in bars)


def test_contents_numbers_follow_optional_sections():
    sample = report(
        analysis_sections=[NarrativeSection(heading=f"Chương {i}") for i in range(3)],
        peer_comparison=ComparisonTable(title="Cùng ngành"),
        catalysts=[Catalyst(title="Sự kiện")],
        appendix_sections=[NarrativeSection(heading="Phụ lục")],
    )
    document = renderer.setup_document()
    renderer.add_cover_contents(document, sample)
    entries = [cell.text for row in document.tables[0].rows for cell in row.cells]
    assert "06–08  Phân tích chuyên sâu" in entries
    assert "09  Định giá" in entries
    assert "10  So sánh cùng ngành" in entries
    assert "11  Chất xúc tác và lịch sự kiện" in entries
    assert "12  Nguồn dữ liệu và phương pháp" in entries
    assert "13  Xếp hạng và công bố" in entries
    assert "PL  Phụ lục nghiên cứu" in entries


def test_narrative_chapters_honor_page_breaks_and_heading_navigation():
    section = SimpleNamespace(heading="Chương phân tích", subtitle="", paragraphs=["Nội dung"],
                              bullets=[], source_ids=[], page_break_before=True)
    document = renderer.setup_document()
    renderer.add_narrative_section(document, section, number="06")
    heading = document.paragraphs[0]
    assert heading.paragraph_format.page_break_before is True
    assert heading.style.name == "VT_H1"
    assert heading.style.element.pPr.find(qn("w:outlineLvl")).get(qn("w:val")) == "0"
    body = document.paragraphs[1]
    assert body.runs[0].font.size.pt == 10
    assert body.paragraph_format.line_spacing == 1.35


def test_paginated_research_uses_a_deliberate_full_chapter_map():
    sample = report(analysis_sections=[
        NarrativeSection(heading=f"Phân tích {i}", page_break_before=True) for i in range(24)
    ])
    document = renderer.setup_document()
    renderer.add_cover_contents(document, sample)
    assert document.paragraphs[0].paragraph_format.page_break_before is True
    assert len(document.tables[0].columns) == 2
    entries = [cell.text for row in document.tables[0].rows for cell in row.cells]
    assert "06  Phân tích 0" in entries
    assert "29  Phân tích 23" in entries
    assert "30  Định giá" in entries


def test_rating_strip_uses_supplied_valuation_labels():
    sample = report(valuation_metrics=[
        Metric(key="target_price", label="Giá trị cơ sở giả định", value=61_864, unit="VND"),
        Metric(key="upside", label="Chênh lệch theo mô hình", value=22.75, unit="%"),
    ])
    document = renderer.setup_document()
    renderer.add_rating_strip(document, sample)
    assert document.tables[0].cell(0, 1).paragraphs[0].text == "GIÁ TRỊ CƠ SỞ GIẢ ĐỊNH"
    assert document.tables[0].cell(0, 2).paragraphs[0].text == "CHÊNH LỆCH THEO MÔ HÌNH"


def test_cover_distinguishes_price_date_from_report_date():
    sample = report(financial_metrics=[
        Metric(key="market_price", label="Giá tham chiếu", value=50_400,
               unit="VND", as_of=date(2026, 11, 3)),
    ])
    document = renderer.setup_document()
    renderer.add_summary_split(document, sample)
    rail = document.tables[0].cell(0, 2).text
    assert "Giá tham chiếu\t50.400,00 đ" in rail
    assert "Ngày giá\t03/11/2026" in rail
    assert "Ngày chốt báo cáo\t06/11/2026" in rail


def test_forecasts_wrap_into_legible_rows_without_hardcoded_years():
    document = renderer.setup_document()
    stats = [KeyStat(label=f"Dự phóng {i}", value="123.456", note="2028F") for i in range(8)]
    renderer.add_forecast_band(document, stats, report())
    assert len(document.tables) == 2
    assert all(len(table.columns) == 7 for table in document.tables)
    assert all(table.columns[0].width > Cm(4) for table in document.tables)
    assert "DỰ PHÓNG VÀ GIẢ ĐỊNH" in document.paragraphs[0].text


def test_portrait_brand_mark_does_not_consume_the_cover():
    document = renderer.setup_document()
    renderer.add_masthead(document, report())
    assert document.inline_shapes[0].height == Cm(1.8)


def test_report_without_an_analyst_does_not_imply_a_named_human_review():
    document = renderer.setup_document()
    renderer.add_analyst_block(document, report())
    text = document.tables[0].cell(0, 0).text
    assert "CHUYÊN VIÊN PHÂN TÍCH" not in text
    assert "chưa có chuyên viên phê duyệt" in text


def test_pdf_export_rejects_a_stale_existing_file(monkeypatch, tmp_path):
    stale = tmp_path / "report.pdf"
    stale.write_bytes(b"previous export" * 100)
    monkeypatch.setattr(renderer, "find_soffice", lambda: "fake-soffice")
    monkeypatch.setattr(renderer.subprocess, "run", lambda *args, **kwargs:
                        SimpleNamespace(returncode=0, stderr=""))
    with pytest.raises(RuntimeError, match="PDF export failed"):
        renderer.convert_pdf(tmp_path / "report.docx", tmp_path)
    assert stale.read_bytes() == b"previous export" * 100


def test_pdf_export_replaces_existing_file_only_after_success(monkeypatch, tmp_path):
    destination = tmp_path / "report.pdf"
    destination.write_bytes(b"old" * 400)
    monkeypatch.setattr(renderer, "find_soffice", lambda: "fake-soffice")

    def convert(command, **kwargs):
        out_dir = Path(command[command.index("--outdir") + 1])
        (out_dir / "report.pdf").write_bytes(b"new" * 400)
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(renderer.subprocess, "run", convert)
    assert renderer.convert_pdf(tmp_path / "report.docx", tmp_path) == destination
    assert destination.read_bytes() == b"new" * 400
    assert not list(tmp_path.glob("vibe-pdf-*"))
