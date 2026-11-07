"""The report CLI must enforce the requested PDF depth before delivery."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import generate_fpt_report as cli


def setup_cli(tmp_path, monkeypatch, pages=24, status="succeeded"):
    template = tmp_path / "input.json"
    template.write_text("{}", encoding="utf-8")
    pdf = tmp_path / "source.pdf"
    docx = tmp_path / "source.docx"
    pdf.write_bytes(b"%PDF-mocked-renderer")
    docx.write_bytes(b"PK\x03\x04mocked-renderer")
    job = {"status": status, "job_id": "a" * 32, "publication_status": "draft_unverified",
           "artifacts": [{"report_id": "pdf"}, {"report_id": "docx"}]}
    monkeypatch.setattr(cli, "ReportJobService", lambda: SimpleNamespace(create_job=lambda *args, **kwargs: job))
    monkeypatch.setattr(cli, "PdfReader", lambda path: SimpleNamespace(pages=[None] * pages))
    monkeypatch.setattr(cli, "resolve_report_artifact", lambda key: (pdf if key == "pdf" else docx, "mock"))
    output = tmp_path / "delivered"
    return ["--template", str(template), "--output-dir", str(output)], output


def test_short_report_is_not_copied_as_completed_delivery(tmp_path, monkeypatch):
    args, output = setup_cli(tmp_path, monkeypatch, pages=23)
    with pytest.raises(RuntimeError, match="requires at least 24"):
        cli.main(args)
    assert not output.exists()


def test_complete_report_delivers_both_formats_and_actual_page_count(tmp_path, monkeypatch, capsys):
    args, output = setup_cli(tmp_path, monkeypatch)
    assert cli.main(args) == 0
    assert {path.suffix for path in output.iterdir()} == {".pdf", ".docx"}
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["pdf_pages"] == 24
    assert all(Path(path).is_file() for path in receipt["outputs"])


def test_partial_export_does_not_print_success_or_deliver(tmp_path, monkeypatch, capsys):
    args, output = setup_cli(tmp_path, monkeypatch, status="partial")
    assert cli.main(args) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "partial"
    assert not output.exists()
