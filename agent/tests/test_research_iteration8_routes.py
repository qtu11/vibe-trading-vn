"""Authenticated attempt receipts and snapshot-only Markdown over real storage."""

from datetime import datetime, timezone

import pytest

from src.research_artifacts import report as report_module
from src.research_artifacts import service as service_module
from src.research_artifacts.service import _scope
from src.research_artifacts.store import digest
from tests.test_research_artifact_routes import (
    BASE, EXAMPLES, HEADERS, MISSING_ID, QUERY, api, create,
)


KEY = "http_research_request_001"


def stored_files(service):
    """Observe all DB sidecars, bytes and write times without changing them."""
    parent = service.store.path.parent
    if not parent.exists():
        return {}
    return {
        path.name: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in parent.iterdir() if path.is_file()
    }


def forbid_execution(*args, **kwargs):
    pytest.fail("An idempotent replay or read executed the research engine")


def test_attempt_listing_precedes_revision_route_requires_auth_and_creates_no_storage(api):
    client, service, _ = api
    path = BASE + "/attempts"
    for headers in ({}, {"Authorization": "Bearer wrong-key"}):
        assert client.get(path, headers=headers).status_code == 401
    response = client.get(path, headers=HEADERS)
    assert response.status_code == 200, response.text
    assert response.json() == {
        "items": [], "total": 0, "next_offset": None, "refresh_state": None,
    }
    scoped = client.get(path, params={"kind": "vietnam", "idempotency_key": KEY}, headers=HEADERS)
    assert scoped.status_code == 200 and scoped.json()["items"] == []
    assert not service.store.path.parent.exists()


def test_successful_key_replays_saved_revision_without_engine_source_or_new_attempt(api, monkeypatch):
    client, service, source = api
    first = create(client, {"code": "CASE.VN"}, idempotency_key=KEY)
    assert first.status_code == 200, first.text
    original = first.json()
    source.write_text("{}", encoding="utf-8")
    service.clock = lambda: datetime(2026, 11, 8, tzinfo=timezone.utc)
    monkeypatch.setattr(service, "_calculate", forbid_execution)
    monkeypatch.setattr(service_module, "_producer", forbid_execution)
    before = stored_files(service)
    replay = create(client, {"code": "CASE.VN"}, idempotency_key=KEY)
    assert replay.status_code == 200 and replay.json() == original
    attempts = client.get(BASE + "/attempts", params={"kind": "vietnam", "idempotency_key": KEY}, headers=HEADERS).json()
    assert attempts["total"] == 1
    receipt = attempts["items"][0]
    assert receipt["status"] == "succeeded" and receipt["revision_id"] == original["revision_id"]
    assert receipt["request_sha256"] == original["hashes"]["request_sha256"]
    assert "request" not in receipt and receipt["error"] is None
    assert stored_files(service) == before


@pytest.mark.parametrize("change", ["request", "parent", "kind"])
def test_key_bound_to_caller_body_parent_and_kind_returns_conflict_receipt(api, monkeypatch, change):
    client, service, _ = api
    first = create(client, idempotency_key=KEY).json()
    body = {"kind": "vietnam", "request": dict(QUERY), "idempotency_key": KEY}
    if change == "request":
        body["request"]["as_of"] = "2026-11-04T00:00:00Z"
    elif change == "parent":
        body["parent_revision_id"] = first["revision_id"]
    else:
        body["kind"] = "crypto_basis"
    monkeypatch.setattr(service, "_calculate", forbid_execution)
    before = stored_files(service)
    response = client.post(BASE, json=body, headers=HEADERS)
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "IDEMPOTENCY_CONFLICT"
    assert detail["receipt"]["status"] == "succeeded"
    assert detail["receipt"]["revision_id"] == first["revision_id"]
    assert service.list_revisions()["total"] == service.list_attempts()["total"] == 1
    assert stored_files(service) == before


def test_failed_refresh_receipt_keeps_last_good_and_failed_key_never_reruns(api, monkeypatch):
    client, service, source = api
    first = create(client).json()
    source.write_text("{}", encoding="utf-8")
    failed = create(client, parent_revision_id=first["revision_id"], idempotency_key=KEY)
    assert failed.status_code == 422
    detail = failed.json()["detail"]
    assert detail["code"] == "RESEARCH_FAILED"
    receipt = detail["receipt"]
    assert receipt["status"] == "failed" and receipt["revision_id"] is None
    assert receipt["parent_revision_id"] == first["revision_id"]
    assert receipt["error"]["stage"] == "engine"
    history = client.get(BASE + "/attempts", params={"parent_revision_id": first["revision_id"], "idempotency_key": KEY}, headers=HEADERS)
    assert history.status_code == 200
    history = history.json()
    assert history["items"] == [receipt]
    state = history["refresh_state"]
    assert state["state"] == "refresh_failed"
    assert state["last_good_revision_id"] == first["revision_id"]
    source.write_bytes((EXAMPLES / "vn-company-research.example.json").read_bytes())
    monkeypatch.setattr(service, "_calculate", forbid_execution)
    before = stored_files(service)
    replay = create(client, parent_revision_id=first["revision_id"], idempotency_key=KEY)
    assert replay.status_code == 422 and replay.json()["detail"] == detail
    assert client.get(f"{BASE}/{first['revision_id']}", headers=HEADERS).json() == first
    assert service.list_revisions()["total"] == 1
    assert stored_files(service) == before


def test_interrupted_attempt_returns409_with_unknown_receipt_without_stealing_or_execution(api, monkeypatch):
    client, service, _ = api
    normalized = service._normalize("vietnam", QUERY)
    attempt, acquired = service.store.reserve_attempt(
        kind="vietnam", request=normalized, scope=_scope("vietnam", normalized),
        caller_hash=digest({"kind": "vietnam", "request": QUERY, "parent_revision_id": None}),
        parent_revision_id=None, idempotency_key=KEY, clock=service.clock,
    )
    assert acquired
    monkeypatch.setattr(service, "_calculate", forbid_execution)
    before = stored_files(service)
    response = create(client, idempotency_key=KEY)
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "RESEARCH_ATTEMPT_IN_FLIGHT"
    assert detail["receipt"]["attempt_id"] == attempt["attempt_id"]
    assert detail["receipt"]["status"] == "in_flight_unknown"
    assert service.list_revisions()["total"] == 0
    assert stored_files(service) == before


def test_unexpected_engine_failure_has_safe503_and_durable_receipt(api, monkeypatch):
    client, service, _ = api
    first = create(client).json()

    def fail(*_):
        raise RuntimeError("C:/private/provider-token TOP_SECRET")

    monkeypatch.setattr(service, "_calculate", fail)
    response = create(client, parent_revision_id=first["revision_id"], idempotency_key=KEY)
    assert response.status_code == 503
    assert "TOP_SECRET" not in response.text and "provider-token" not in response.text
    detail = response.json()["detail"]
    assert detail["code"] == "RESEARCH_EXECUTION_FAILED"
    assert detail["receipt"]["status"] == "failed"
    assert detail["receipt"]["error"]["exception_type"] == "RuntimeError"
    assert service.get_revision(first["revision_id"]) == first


@pytest.mark.parametrize("key", ["", "short", "x" * 129, "contains space", "slashes/invalid", 8, True])
def test_invalid_save_key_returns422_before_creating_storage(api, key):
    client, service, _ = api
    assert create(client, idempotency_key=key).status_code == 422
    assert not service.store.path.parent.exists()


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1", "offset=100001", "kind=crypto", "idempotency_key=short", "parent_revision_id=bad%21id"])
def test_invalid_attempt_filters_return422_before_storage(api, query):
    client, service, _ = api
    assert client.get(BASE + "/attempts?" + query, headers=HEADERS).status_code == 422
    assert not service.store.path.parent.exists()


def test_report_reads_saved_utf8_and_current_review_without_engine_or_any_file_write(api, monkeypatch):
    client, service, source = api
    first = create(client).json()
    review = client.post(f"{BASE}/{first['revision_id']}/reviews", json={
        "decision": "acknowledged", "note": "Đã đọc; chưa xác minh tài liệu", "reviewer": "Người kiểm tra",
    }, headers=HEADERS)
    assert review.status_code == 200
    saved = service.get_revision(first["revision_id"])
    expected = report_module.render_revision_markdown(saved).encode("utf-8")
    source.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(service, "_calculate", forbid_execution)
    monkeypatch.setattr(service_module, "_producer", forbid_execution)
    before = stored_files(service)
    path = f"{BASE}/{first['revision_id']}/report"
    response = client.get(path, headers=HEADERS)
    assert response.status_code == 200
    assert response.content == expected
    assert "Đã đọc; chưa xác minh tài liệu" in response.text
    assert response.headers["content-type"] == "text/markdown; charset=utf-8"
    assert response.headers["content-disposition"] == f'attachment; filename="research-{first["revision_id"]}.md"'
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert client.get(path, headers=HEADERS).content == expected
    assert stored_files(service) == before
    assert service.get_revision(first["revision_id"]) == saved


def test_report_auth_missing_invalid_revision_never_creates_storage(api):
    client, service, _ = api
    path = f"{BASE}/{MISSING_ID}/report"
    for headers in ({}, {"Authorization": "Bearer wrong-key"}):
        assert client.get(path, headers=headers).status_code == 401
    missing = client.get(path, headers=HEADERS)
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "REVISION_NOT_FOUND"
    assert client.get(BASE + "/bad%21id/report", headers=HEADERS).status_code == 422
    assert not service.store.path.parent.exists()


def test_report_size_excess_is413_with_no_partial_markdown_or_write(api, monkeypatch):
    client, service, _ = api
    first = create(client).json()
    monkeypatch.setattr(report_module, "MAX_REPORT_BYTES", 1)
    before = stored_files(service)
    response = client.get(f"{BASE}/{first['revision_id']}/report", headers=HEADERS)
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "REPORT_TOO_LARGE"
    assert response.headers["content-type"] == "application/json"
    assert "content-disposition" not in response.headers
    assert stored_files(service) == before


def test_report_invalid_shape_maps_to422_and_unexpected_failure_stays_safe503(api, monkeypatch):
    client, service, _ = api
    first = create(client).json()
    before = stored_files(service)
    path = f"{BASE}/{first['revision_id']}/report"

    def invalid(_):
        raise report_module.ReportExportError("INVALID_REPORT_REVISION", "Saved revision cannot be exported")

    monkeypatch.setattr(report_module, "render_revision_markdown", invalid)
    response = client.get(path, headers=HEADERS)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_REPORT_REVISION"

    def unavailable(_):
        raise RuntimeError("C:/private/token DO_NOT_EXPOSE")

    monkeypatch.setattr(report_module, "render_revision_markdown", unavailable)
    response = client.get(path, headers=HEADERS)
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "RESEARCH_REPORT_UNAVAILABLE"
    assert "DO_NOT_EXPOSE" not in response.text and "private" not in response.text
    assert stored_files(service) == before
