"""Published downloads must contain a readable document, not just a magic prefix."""

import pytest
from pypdf import PdfWriter

from src.tools.report_artifacts import publish_report_artifact, resolve_report_artifact


@pytest.mark.parametrize("kind", ["header_only", "empty", "encrypted"])
def test_unreadable_pdf_is_not_published(tmp_path, monkeypatch, kind):
    destination = tmp_path / "published"
    monkeypatch.setattr("src.tools.report_artifacts.reports_root", lambda: destination)
    path = tmp_path / "report.pdf"
    if kind == "header_only":
        path.write_bytes(b"%PDF-1.7\nnot a document\n%%EOF")
    else:
        writer = PdfWriter()
        if kind == "encrypted":
            writer.add_blank_page(width=595, height=842)
            writer.encrypt("fixture-password")
        writer.write(path)
    with pytest.raises(ValueError, match="PDF"):
        publish_report_artifact(path)
    assert not destination.exists()


def test_readable_pdf_remains_downloadable(tmp_path, monkeypatch):
    monkeypatch.setattr("src.tools.report_artifacts.reports_root", lambda: tmp_path / "published")
    path = tmp_path / "report.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.write(path)
    artifact = publish_report_artifact(path)
    resolved = resolve_report_artifact(artifact["report_id"])
    assert resolved is not None
    assert resolved[0].read_bytes() == path.read_bytes()
