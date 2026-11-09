"""The same quote-to-report gate must work for different issuers and fail closed."""

from dataclasses import replace
from datetime import datetime, timezone, timedelta
import json
import zipfile

from docx import Document
from pptx import Presentation
import pytest

from src.agent.grounding import GroundingLedger
from src.reporting.evidence import from_grounding_ledger, validate_report_evidence
from src.reporting.renderer import make_docx
from src.reporting.presentation import make_pptx
from src.reporting.schema import ResearchReport, KeyStat, PricePoint


def research(tmp_path, symbol="FPT", price=50800):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}.VN?interval=1d"
    quote = {
        "symbol": f"{symbol}.VN",
        "exchange": "HOSE",
        "value": price,
        "unit": "VND",
        "scale": 1,
        "observed_at": "2026-11-06T07:45:09+00:00",
        "retrieved_at": "2026-11-07T05:30:00+00:00",
        "price_basis": "raw",
        "data_role": "last_trade",
        "source_url": url,
    }
    payload = {
        f"{symbol}.VN": [{"date": "2026-11-06", "close": price / 2}],
        "_provenance": {f"{symbol}.VN": {"source_url": url, "quote_observation": quote}},
    }
    ledger = GroundingLedger(run_dir=tmp_path, user_message=f"Research {symbol}.VN")
    ledger.ingest_tool_result(
        tool_name="get_market_data",
        arguments={"codes": [f"{symbol}.VN"]},
        result=json.dumps(payload),
        call_id="actual-provider-boundary",
        success=True,
    )
    context = from_grounding_ledger(ledger, as_of=datetime(2026, 11, 7, 6, tzinfo=timezone.utc))
    assert len(context.quotes) == 1
    source_id = context.quotes[0].source_id
    assumption = {"evidence_kind": "assumption", "methodology": "Analytical opinion, not a reported fact"}
    data = dict(
        market="VN_EQUITY",
        symbol=symbol,
        exchange="HOSE",
        company_name=symbol,
        title=f"Research report {symbol}",
        subtitle="Generic evidence pipeline",
        data_as_of="2026-11-07",
        overview="Business description pending further research.",
        executive_summary="Decision requires an explicit valuation model and evidence.",
        overview_evidence=assumption,
        executive_summary_evidence=assumption,
        financial_metrics=[
            dict(
                key="market_price",
                label="Last trade",
                value=price,
                unit="VND",
                as_of="2026-11-06",
                observed_at=quote["observed_at"],
                price_basis="raw",
                source_ids=[source_id],
                decimals=0,
            )
        ],
        sources=[dict(id=source_id, title="Provider snapshot", provider="Yahoo Finance", url=url, status="verified")],
    )
    return ResearchReport.model_validate(data), context


@pytest.mark.parametrize("symbol,price", [("FPT", 50800), ("VCB", 53600), ("HPG", 21200)])
def test_multiple_stocks_use_provider_quote_instead_of_adjusted_close(tmp_path, symbol, price):
    report, context = research(tmp_path, symbol, price)
    audit = validate_report_evidence(report, context)
    assert audit.quote_verified
    assert audit.report.financial_metrics[0].value == price
    assert audit.report.financial_metrics[0].evidence_kind == "observed"
    assert audit.report.publication_status == "draft_unverified"


def test_history_keeps_the_same_url_without_becoming_a_current_raw_quote(tmp_path):
    report, context = research(tmp_path)
    report.price_history = [PricePoint(date="2026-11-06", close=25400, unit="VND", price_basis="total_return",
                                      source_ids=report.financial_metrics[0].source_ids)]
    audit = validate_report_evidence(report, context)
    assert audit.quote_verified
    assert audit.report.financial_metrics[0].value == 50800
    assert audit.report.price_history[0].close == 25400


@pytest.mark.parametrize(
    "change", ["invented_price", "wrong_symbol", "wrong_exchange", "wrong_unit", "wrong_basis", "wrong_date"]
)
def test_mismatched_quote_never_reaches_rendering(tmp_path, change):
    report, context = research(tmp_path)
    price = report.financial_metrics[0]
    if change == "invented_price":
        price.value = 138500
    elif change == "wrong_symbol":
        report.symbol = "VCB"
    elif change == "wrong_exchange":
        report.exchange = "HNX"
    elif change == "wrong_unit":
        price.unit = "nghìn VND"
    elif change == "wrong_basis":
        price.price_basis = "split_adjusted"
    else:
        price.as_of = datetime(2026, 11, 5).date()
    with pytest.raises(ValueError):
        validate_report_evidence(report, context)


def test_absent_stale_or_uncaptured_sources_cannot_claim_current_rating(tmp_path):
    report, context = research(tmp_path)
    report.recommendation = "MUA"
    with pytest.raises(ValueError, match="khuyến nghị mua/bán"):
        validate_report_evidence(report, None)
    report, context = research(tmp_path)
    stale = replace(context, as_of=context.as_of + timedelta(days=10))
    assert not validate_report_evidence(report, stale).quote_verified
    report, context = research(tmp_path)
    with pytest.raises(ValueError, match="chưa được công cụ thu thập"):
        validate_report_evidence(report, replace(context, sources=()))


def test_rated_target_cannot_bypass_arithmetic_with_methodology_prose(tmp_path):
    report, context = research(tmp_path)
    payload = report.model_dump(mode="json")
    payload["recommendation"] = "MUA"
    payload["valuation_metrics"] = [{"key": "target_price", "label": "Giá mục tiêu", "value": 999999,
        "unit": "VND", "as_of": "2026-11-06", "price_basis": "raw", "evidence_kind": "derived",
        "input_keys": ["market_price"], "methodology": "Chiết khấu dòng tiền kết hợp P/E mục tiêu"}]
    with pytest.raises(ValueError, match="cần công thức"):
        validate_report_evidence(ResearchReport.model_validate(payload), context)
    payload["valuation_metrics"][0]["evidence_kind"] = "assumption"
    with pytest.raises(ValueError, match="giả định"):
        validate_report_evidence(ResearchReport.model_validate(payload), context)


def test_rated_target_recomputes_declared_inputs_and_visible_assumptions(tmp_path):
    report, context = research(tmp_path)
    payload = report.model_dump(mode="json")
    payload["recommendation"] = "MUA"
    payload["valuation_metrics"] = [
        {"key": "target_multiple", "label": "Hệ số định giá giả định", "value": 1.1, "unit": "x",
         "as_of": "2026-11-06", "evidence_kind": "assumption", "methodology": "Giả định phân tích có điều kiện"},
        {"key": "target_price", "label": "Giá mục tiêu", "value": 55880, "unit": "VND", "decimals": 0,
         "as_of": "2026-11-06", "price_basis": "raw", "evidence_kind": "derived",
         "input_keys": ["market_price", "target_multiple"], "methodology": "market_price * target_multiple"},
    ]
    assert validate_report_evidence(ResearchReport.model_validate(payload), context).report.recommendation.value == "MUA"
    payload["valuation_metrics"][1]["value"] = 999999
    with pytest.raises(ValueError, match="không khớp công thức"):
        validate_report_evidence(ResearchReport.model_validate(payload), context)
    payload["valuation_metrics"][1].update(value=55880, input_keys=["market_price"], methodology="market_price * 1.1")
    with pytest.raises(ValueError, match="hằng số ẩn"):
        validate_report_evidence(ResearchReport.model_validate(payload), context)


def test_all_rendered_fact_surfaces_require_real_source_urls(tmp_path):
    report, _ = research(tmp_path)
    payload = report.model_dump(mode="json")
    payload["key_stats"] = [{"label": "Revenue", "value": "123"}]
    with pytest.raises(ValueError, match="Thiếu source_ids"):
        ResearchReport.model_validate(payload)
    payload["key_stats"][0]["source_ids"] = [payload["sources"][0]["id"]]
    payload["sources"][0]["url"] = None
    with pytest.raises(ValueError, match="Thiếu URL"):
        ResearchReport.model_validate(payload)


def test_docx_and_editable_pptx_have_clickable_source_urls(tmp_path):
    report, context = research(tmp_path)
    report = validate_report_evidence(report, context).report
    docx, pptx = tmp_path / "research.docx", tmp_path / "research.pptx"
    make_docx(report, docx)
    make_pptx(report, pptx)
    assert Document(docx).tables
    deck = Presentation(pptx)
    assert len(deck.slides) >= 5
    assert any(shape.has_text_frame for slide in deck.slides for shape in slide.shapes)
    url = str(report.sources[0].url).replace("&", "&amp;")
    for path in (docx, pptx):
        with zipfile.ZipFile(path) as archive:
            assert archive.testzip() is None
            relationships = "\n".join(archive.read(n).decode() for n in archive.namelist() if n.endswith(".rels"))
            assert url in relationships and 'TargetMode="External"' in relationships


def test_adjacent_valid_number_cannot_mask_an_invented_number(tmp_path):
    report, context = research(tmp_path)
    report.key_stats = [
        KeyStat(label="Unverified prose", value="99999 và 50800", source_ids=report.financial_metrics[0].source_ids)
    ]
    with pytest.raises(ValueError, match="99999"):
        validate_report_evidence(report, context)


def test_generic_renderer_never_injects_fpt_values(tmp_path):
    import inspect
    import re

    import src.reporting.renderer as renderer

    # The hardcoded FPT chart/table builders must be gone, not merely bypassed.
    for name in ("add_fpt_segment_overview_table", "_extract_chapter_combo_specs", "_extract_quarterly_combo_specs"):
        assert not hasattr(renderer, name)
    code = re.sub(r"#.*", "", inspect.getsource(renderer))
    for literal in ("FPT", "TCBS", "28538", "40023", "61864"):
        assert literal not in code
    report, _ = research(tmp_path)
    renderer.make_docx(report, tmp_path / "generic.docx")


IR_URL = "https://ir.example.vn/kqkd-9t-2026"


def _collected_page(tmp_path, context, page):
    """Bind a page through the real read_url intake, like a live agent run does."""
    ledger = GroundingLedger(run_dir=tmp_path / "page", user_message="Đọc báo cáo KQKD")
    ledger.ingest_tool_result(
        tool_name="read_url", arguments={"url": IR_URL},
        result=json.dumps({"url": IR_URL, "title": "KQKD 9T/2026", "content": page}, ensure_ascii=False),
        call_id="read-ir", success=True,
    )
    assert ledger.sources, "read_url intake must record the page"
    return replace(context, sources=(*context.sources, *ledger.sources))


def _chart_payload(report, **chart):
    payload = report.model_dump(mode="json")
    payload["sources"].append({"id": "IR1", "title": "KQKD 9T/2026", "provider": "IR",
                               "url": IR_URL})
    payload["analysis_sections"] = [{
        "heading": "Cơ cấu doanh thu", "paragraphs": ["Doanh thu theo khối."],
        "evidence_kind": "assumption", "methodology": "Bình luận phân tích",
        "charts": [chart],
    }]
    return payload


def test_section_chart_formula_line_is_server_computed(tmp_path):
    report, _ = research(tmp_path)
    bars = {"label": "Doanh thu", "unit": "tỷ VND", "values": [300.0, 100.0], "source_ids": ["IR1"]}
    chart = {"title": "Cơ cấu", "categories": ["A", "B"], "bars": bars,
             "line": {"label": "Tỷ trọng"}, "line_formula": "share_of_total_pct"}
    parsed = ResearchReport.model_validate(_chart_payload(report, **chart))
    line = parsed.analysis_sections[0].charts[0].line
    assert line.values == [75.0, 25.0] and line.evidence_kind == "derived"
    assert line.source_ids == ["IR1"] and "Máy chủ tính" in line.methodology
    # A model-typed line that disagrees with the formula is rejected.
    chart["line"] = {"label": "Tỷ trọng", "values": [80.0, 20.0]}
    with pytest.raises(ValueError, match="không khớp công thức"):
        ResearchReport.model_validate(_chart_payload(report, **chart))
    # Free-form derived/assumption chart numbers are not accepted at all.
    chart.pop("line_formula")
    chart["line"] = {"label": "Ước tính", "values": [1.0, 2.0], "evidence_kind": "assumption", "methodology": "x"}
    with pytest.raises(ValueError, match="cited/observed"):
        ResearchReport.model_validate(_chart_payload(report, **chart))
    # Every bar needs a source.
    chart.pop("line")
    chart["bars"] = {**bars, "source_ids": []}
    with pytest.raises(ValueError, match="Thiếu source_ids"):
        ResearchReport.model_validate(_chart_payload(report, **chart))


def test_section_chart_numbers_must_exist_in_collected_source(tmp_path):
    report, context = research(tmp_path)
    page = "Doanh thu khối CNTT đạt 300 tỷ đồng, khối Giáo dục đạt 100 tỷ đồng trong 9 tháng."
    bound = _collected_page(tmp_path, context, page)
    chart = {"title": "Doanh thu theo khối", "categories": ["CNTT", "Giáo dục"],
             "bars": {"label": "Doanh thu", "unit": "tỷ VND", "values": [300.0, 100.0], "source_ids": ["IR1"]},
             "line": {"label": "Tỷ trọng"}, "line_formula": "share_of_total_pct"}
    ok = ResearchReport.model_validate(_chart_payload(report, **chart))
    validate_report_evidence(ok, bound)
    docx = tmp_path / "chart.docx"
    make_docx(ok, docx)
    assert len(Document(docx).inline_shapes) >= 1
    slides = tmp_path / "chart.pptx"
    make_pptx(ok, slides)
    from pptx.enum.shapes import MSO_SHAPE_TYPE
    deck = Presentation(slides)
    assert sum(shape.shape_type == MSO_SHAPE_TYPE.PICTURE for slide in deck.slides for shape in slide.shapes) >= 2
    with zipfile.ZipFile(slides) as archive:
        assert any(IR_URL in archive.read(name).decode() for name in archive.namelist() if name.endswith(".rels"))

    chart["bars"]["values"] = [300.0, 140.0]  # 140 is not in the collected page
    invented = ResearchReport.model_validate(_chart_payload(report, **chart))
    with pytest.raises(ValueError, match="không có trong nội dung nguồn"):
        validate_report_evidence(invented, bound)


def test_slides_bound_text_and_preserve_cell_sources(tmp_path):
    from src.reporting.schema import FinancialTable, FinancialRow, DatumEvidence, NarrativeSection

    report, _ = research(tmp_path)
    evidence = DatumEvidence(source_ids=report.financial_metrics[0].source_ids)
    report.financial_table = FinancialTable(
        columns=["A", "B"], rows=[FinancialRow(label="Cell attribution", values=["50800"], cell_evidence=[evidence])]
    )
    report.analysis_sections = [
        NarrativeSection(heading="Long paragraph", paragraphs=["Data retained. " * 400], **evidence.model_dump())
    ]
    deck_path = tmp_path / "bounded.pptx"
    make_pptx(report, deck_path)
    deck = Presentation(deck_path)
    for slide in deck.slides:
        for shape in slide.shapes:
            assert shape.top >= 0 and shape.left >= 0
            assert shape.top + shape.height <= deck.slide_height + 2
            assert shape.left + shape.width <= deck.slide_width + 2
    assert (
        sum("Data retained." in shape.text for slide in deck.slides for shape in slide.shapes if shape.has_text_frame)
        > 1
    )
    make_docx(report, tmp_path / "sparse-table.docx")


def test_table_header_scale_and_derived_input_key_attribution(tmp_path):
    """Table-header units ('Đơn vị: Tỷ đồng') and input_keys attribution work end-to-end."""
    report, context = research(tmp_path)
    # The unit 'Tỷ đồng' appears once in the table header, far from the cell numbers.
    table_page = (
        "BẢNG KẾT QUẢ KINH DOANH HỢP NHẤT 9 THÁNG (Đơn vị tính: Tỷ đồng) "
        + ("Chi tiết chỉ tiêu bộ phận kinh doanh cốt lõi của doanh nghiệp. " * 2)
        + "| Khối CNTT nước ngoài: 28538 | Khối CNTT trong nước: 6977 |"
    )
    bound = _collected_page(tmp_path, context, table_page)
    chart = {
        "title": "Doanh thu theo khối",
        "categories": ["CNTT NN", "CNTT TN"],
        "bars": {"label": "Doanh thu", "unit": "tỷ VND", "values": [28538.0, 6977.0], "source_ids": ["IR1"]},
    }
    payload = _chart_payload(report, **chart)
    payload["valuation_metrics"] = [{
        "key": "target_price",
        "label": "Giá mục tiêu",
        "value": 55880,
        "unit": "VND",
        "as_of": "2026-11-06",
        "price_basis": "raw",
        "decimals": 0,
        "evidence_kind": "derived",
        "input_keys": ["market_price"],
        "methodology": "Chiết khấu dòng tiền kết hợp P/E mục tiêu",
    }]
    validated = validate_report_evidence(ResearchReport.model_validate(payload), bound).report
    docx_path = tmp_path / "derived_attr.docx"
    make_docx(validated, docx_path)
    doc = Document(docx_path)
    all_cells = "\n".join(cell.text for table in doc.tables for row in table.rows for cell in row.cells)
    assert "S1 · 06/11/2026" in all_cells

    # Reject a derived metric whose input_key points to an empty, sourceless metric.
    payload["financial_metrics"].append({
        "key": "empty_input",
        "label": "Rỗng",
        "value": None,
        "evidence_kind": "assumption",
        "methodology": "Chưa có dữ liệu",
    })
    payload["valuation_metrics"][0]["input_keys"] = ["empty_input"]
    with pytest.raises(ValueError, match="chưa có giá trị hoặc nguồn"):
        ResearchReport.model_validate(payload)


def test_engine_reexports_share_single_canonical_classes():
    import src.reporting.renderer as prod_renderer
    import src.reporting.schema as prod_schema
    import vibe_report_engine.renderer as eng_renderer
    import vibe_report_engine.schema as eng_schema

    assert eng_schema.ResearchReport is prod_schema.ResearchReport
    assert eng_schema.SectionChart is prod_schema.SectionChart
    assert eng_renderer.make_docx is prod_renderer.make_docx
    assert eng_renderer.export_report is prod_renderer.export_report
