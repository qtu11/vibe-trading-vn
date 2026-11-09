"""APA references survive actual Word, PDF and PowerPoint rendering."""

from datetime import date
import json
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from pptx import Presentation
from pypdf import PdfReader

from src.reporting.citations import apa_reference_suffix, reference_sources
from src.reporting.renderer import export_report
from src.reporting.schema import ResearchReport, Source


def test_reference_metadata_is_not_fabricated_and_urls_are_deduplicated():
    source = Source(id="S1", title="Báo cáo FPT", provider="FPT", url="https://example.com/report", published_at=date(2026, 3, 30))
    assert apa_reference_suffix(source) == " (2026, March 30). FPT."
    unknown = Source(id="S2", title="ABC report", provider="Publisher")
    assert apa_reference_suffix(unknown) == " (n.d.). Publisher."
    duplicate = source.model_copy(update={"id": "S3"})
    assert [item.id for item in reference_sources([source, duplicate, unknown])] == ["S2", "S1"]


def test_all_document_formats_include_apa_references_and_clickable_urls(tmp_path):
    payload = json.loads((Path(__file__).parents[1] / "vibe_report_engine/examples/demo_report.json").read_text(encoding="utf-8"))
    report = ResearchReport.model_validate(payload)
    source = report.sources[0]
    source.url = "https://example.com/apa-reference"
    source.published_at = date(2026, 3, 30)
    outputs = export_report(report, tmp_path, formats=("docx", "pdf", "pptx"))
    assert outputs["warnings"] == []

    document = Document(outputs["docx"])
    paragraphs = document.paragraphs
    assert any(paragraph.text == "Tài liệu tham khảo (APA 7th)" for paragraph in paragraphs)
    reference = next(paragraph for paragraph in paragraphs if paragraph.text.startswith(source.title) and "(2026, March 30)" in paragraph.text)
    assert reference.runs[0].italic
    assert reference.paragraph_format.first_line_indent.inches == -0.5
    assert source.provider in reference.text
    links = reference._p.findall(qn("w:hyperlink"))
    assert any(document.part.rels[link.get(qn("r:id"))].target_ref == str(source.url) for link in links)

    pdf = PdfReader(outputs["pdf"])
    text = "\n".join(page.extract_text() for page in pdf.pages)
    assert "APA 7th" in text and "2026, March 30" in text
    assert any(annotation.get_object().get("/A", {}).get("/URI") == str(source.url) for page in pdf.pages for annotation in page.get("/Annots", []))

    slides = Presentation(outputs["pptx"]).slides
    references = [slide for slide in slides if any(shape.has_text_frame and shape.text == "Tài liệu tham khảo (APA 7th)" for shape in slide.shapes)]
    assert len(references) == len(reference_sources(report.sources))
    assert any(run.hyperlink.address == str(source.url) for slide in references for shape in slide.shapes if shape.has_text_frame for paragraph in shape.text_frame.paragraphs for run in paragraph.runs)
    assert any("(2026, March 30)" in shape.text for slide in references for shape in slide.shapes if shape.has_text_frame)
