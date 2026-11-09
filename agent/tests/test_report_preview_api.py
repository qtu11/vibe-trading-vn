"""Authenticated previews render the actual PDF without a browser PDF plug-in."""

from io import BytesIO
from docx import Document

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
import pytest
from reportlab.pdfgen.canvas import Canvas

from src.api.reports_routes import register_reports_routes
from src.api.security import require_auth
from src.reporting.service import ReportJobService
from src.tools.report_artifacts import publish_report_artifact


@pytest.fixture
def preview(tmp_path, monkeypatch):
    monkeypatch.setattr("src.tools.report_artifacts.reports_root", lambda: tmp_path / "reports")
    monkeypatch.setattr("src.api.reports_routes.ReportJobService", lambda: ReportJobService(tmp_path / "jobs"))
    pdf = tmp_path / "research.pdf"
    canvas = Canvas(str(pdf), pagesize=(595, 842))
    for text in ("First research page", "Second research page"):
        canvas.drawString(60, 700, text)
        canvas.showPage()
    canvas.save()
    artifact = publish_report_artifact(pdf)
    app = FastAPI()
    register_reports_routes(app)
    app.dependency_overrides[require_auth] = lambda: None
    return TestClient(app), app, artifact


def test_preview_manifest_and_png_are_from_the_pdf(preview):
    client, _, artifact = preview
    url = f"/api/reports/{artifact['report_id']}/preview"
    assert client.get(url).json() == {"pages": 2}
    response = client.get(url + "/1")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"].startswith("private")
    with Image.open(BytesIO(response.content)) as image:
        assert image.width <= 1201 and image.height <= 1801
        assert image.getextrema()[0][0] < 100


@pytest.mark.parametrize("suffix,status", [("/2", 404), ("/-1", 422), ("/2000", 422), ("/invalid", 422)])
def test_preview_bounds(preview, suffix, status):
    client, _, artifact = preview
    assert client.get(f"/api/reports/{artifact['report_id']}/preview{suffix}").status_code == status


def test_preview_requires_authentication(preview, monkeypatch):
    client, app, artifact = preview
    app.dependency_overrides.clear()
    monkeypatch.setattr("src.api.security._configured_api_key", lambda: "preview-test-secret")
    for suffix in ("", "/0"):
        assert client.get(f"/api/reports/{artifact['report_id']}/preview{suffix}").status_code in (401, 403)


def test_preview_refuses_unknown_ids_and_other_formats(preview, tmp_path):
    client, _, _ = preview
    for report_id in ("0" * 32, "not-an-opaque-handle"):
        assert client.get(f"/api/reports/{report_id}/preview").status_code == 404
    docx = tmp_path / "doc.docx"
    Document().save(docx)
    artifact = publish_report_artifact(docx)
    assert client.get(f"/api/reports/{artifact['report_id']}/preview").status_code == 404


def test_artifact_job_resolves_standalone_published_pdf(preview):
    client, _, artifact = preview
    report_id = artifact["report_id"]
    response = client.get(f"/api/reports/artifacts/{report_id}/job")
    assert response.status_code == 200
    job = response.json()
    assert job["status"] == "succeeded"
    assert job["formats"] == ["pdf"]
    assert len(job["artifacts"]) == 1
    assert job["artifacts"][0]["report_id"] == report_id
    assert job["artifacts"][0]["filename"] == "research.pdf"
    assert job["artifacts"][0]["media_type"] == "application/pdf"
