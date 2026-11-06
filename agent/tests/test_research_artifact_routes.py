"""Real temporary revision storage through authenticated research HTTP routes."""

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backtest.loaders import local_loader
from src.api.research_artifact_routes import register_research_artifact_routes
from src.research_artifacts.service import ResearchArtifactService
from src.research_artifacts.store import ResearchArtifactStore

EXAMPLES = Path(__file__).resolve().parents[2] / "docs/examples"
BASE = "/api/research/artifacts"
HEADERS = {"Authorization": "Bearer fixture-artifact-key"}
QUERY = {"code": "CASE.VN", "as_of": "2026-11-05T00:00:00Z"}
MISSING_ID = "rr_" + "a" * 32


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr("src.api.security._configured_api_key", lambda: "fixture-artifact-key")
    source = tmp_path / "statements.json"
    source.write_bytes((EXAMPLES / "vn-company-research.example.json").read_bytes())
    monkeypatch.setattr(local_loader, "_load_config", lambda: {"financial_statements": [{"symbol": "CASE.VN", "path": str(source)}]})
    service = ResearchArtifactService(ResearchArtifactStore(tmp_path / "artifacts" / "research.sqlite"),
                                      clock=lambda: datetime(2026, 11, 6, tzinfo=timezone.utc))
    app = FastAPI()
    register_research_artifact_routes(app, service)
    with TestClient(app) as client:
        yield client, service, source


def create(client, query=None, **kwargs):
    return client.post(BASE, json={"kind": "vietnam", "request": QUERY if query is None else query, **kwargs}, headers=HEADERS)


def test_read_list_and_missing_revision_do_not_create_runtime_storage(api):
    client, service, _ = api
    response = client.get(BASE, headers=HEADERS)
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "next_offset": None}
    missing = client.get(f"{BASE}/{MISSING_ID}", headers=HEADERS)
    assert missing.status_code == 404 and missing.json()["detail"]["code"] == "REVISION_NOT_FOUND"
    assert not service.store.path.parent.exists()


def test_statement_creation_read_and_parent_diff_use_actual_server_execution(api):
    client, service, source = api
    first_response = create(client)
    assert first_response.status_code == 200, first_response.text
    first = first_response.json()
    assert first["result"]["data"]["CASE.VN"]["periods"][0]["metrics"]["free_cash_flow"]["value"] == "65000000"
    assert first["verification_status"] == "user_supplied_unverified"
    assert client.get(f"{BASE}/{first['revision_id']}", headers=HEADERS).json() == first
    payload = json.loads(source.read_text(encoding="utf-8"))
    for row in payload["records"]:
        if row["statement"] == "cashflow" and row["period_end"] == "2025-06-30":
            row["facts"]["capex"]["value"] = "99"
    source.write_text(json.dumps(payload), encoding="utf-8")
    response = create(client, parent_revision_id=first["revision_id"])
    assert response.status_code == 200
    second = response.json()
    assert second["parent_revision_id"] == first["revision_id"]
    diff = client.get(f"{BASE}/{second['revision_id']}/diff", params={"before": first["revision_id"], "limit": 1}, headers=HEADERS)
    assert diff.status_code == 200
    body = diff.json()
    assert body["compatible_scope"] and body["facts_changed"] and body["source_changed"]
    assert body["truncated"] and len(body["changes"]) == 1
    assert "free_cash_flow" in {item["metric"] for item in body["affected_metrics"]}
    assert service.get_revision(first["revision_id"]) == first
    listing = client.get(BASE, params={"limit": 1}, headers=HEADERS).json()
    assert listing["total"] == 2 and listing["next_offset"] == 1
    assert listing["items"][0]["revision_id"] == second["revision_id"]


@pytest.mark.parametrize("kind,filename,wrap", [
    ("vietnam_comparables", "vn-comparables.example.json", True),
    ("vietnam_dcf", "vn-dcf.example.json", False),
])
def test_fixed_comparables_and_dcf_create_no_client_result_acceptance(api, kind, filename, wrap):
    client, _, _ = api
    payload = json.loads((EXAMPLES / filename).read_text(encoding="utf-8"))
    response = client.post(BASE, json={"kind": kind, "request": {"payload": payload} if wrap else payload}, headers=HEADERS)
    assert response.status_code == 200, response.text
    revision = response.json()
    assert revision["kind"] == kind and revision["result"]["ok"] is True
    assert revision["producer"]["execution"] == "server_deterministic_engine"
    assert len(revision["hashes"]["request_sha256"]) == 64
    if kind == "vietnam_comparables":
        assert revision["result"]["target"]["scenarios"]["pe"]["prices"]["median"] == 20000
    else:
        assert revision["content_scope"] == "one_bounded_dcf_scenario"
        assert revision["result"]["base_case"]["value_per_share"] > 0
    listing = client.get(BASE, params={"kind": kind}, headers=HEADERS).json()
    assert listing["total"] == 1


def test_review_adds_operator_acknowledgment_without_upgrading_trust(api):
    client, _, _ = api
    first = create(client).json()
    response = client.post(f"{BASE}/{first['revision_id']}/reviews", json={"decision": "acknowledged", "note": "Đã đọc; cần đối chiếu nguồn", "reviewer": "Người kiểm tra"}, headers=HEADERS)
    assert response.status_code == 200
    event = response.json()["event"]
    assert event["reviewer_identity"] == "self_reported_operator_label"
    assert event["verification_status"] == "user_supplied_unverified"
    current = client.get(f"{BASE}/{first['revision_id']}", headers=HEADERS).json()
    assert current["review_state"] == "acknowledged" and current["review_history"] == [event]
    for key in ("result", "request", "hashes", "created_at", "verification_status"):
        assert current[key] == first[key]


@pytest.mark.parametrize("method,path,payload", [
    ("get", BASE, None), ("get", f"{BASE}/{MISSING_ID}", None),
    ("get", f"{BASE}/{MISSING_ID}/diff?before={MISSING_ID}", None),
    ("post", BASE, {"kind": "vietnam", "request": QUERY}),
    ("post", f"{BASE}/{MISSING_ID}/reviews", {"decision": "acknowledged", "note": "Read", "reviewer": "Local"}),
])
def test_all_read_and_write_surfaces_require_auth_before_storage(api, method, path, payload):
    client, service, _ = api
    kwargs = {"json": payload} if payload is not None else {}
    response = client.request(method, path, **kwargs)
    assert response.status_code == 401
    assert not service.store.path.parent.exists()
    response = client.request(method, path, headers={"Authorization": "Bearer wrong-key"}, **kwargs)
    assert response.status_code == 401


@pytest.mark.parametrize("operation", ["create", "review"])
def test_cross_site_write_is_rejected_even_with_valid_bearer(api, operation):
    client, service, _ = api
    revision = create(client).json() if operation == "review" else None
    before = service.list_revisions()["total"]
    payload = ({"kind": "vietnam", "request": QUERY} if operation == "create"
               else {"decision": "acknowledged", "note": "Read", "reviewer": "Local"})
    path = BASE if operation == "create" else f"{BASE}/{revision['revision_id']}/reviews"
    response = client.post(path, json=payload,
                           headers={**HEADERS, "Origin": "https://hostile.invalid", "Sec-Fetch-Site": "cross-site"})
    assert response.status_code == 403
    assert service.list_revisions()["total"] == before
    if revision is not None:
        assert service.get_revision(revision["revision_id"])["review_history"] == []
    else:
        assert not service.store.path.parent.exists()


@pytest.mark.parametrize("payload", [
    {"kind": "bash", "request": {}},
    {"kind": "vietnam", "request": QUERY, "result": {"ok": True}},
    {"kind": "vietnam", "request": dict(QUERY, result={"ok": True})},
    {"kind": "vietnam", "request": dict(QUERY, path="C:/private/source.json")},
    {"kind": "vietnam", "request": dict(QUERY, code="../source")},
    {"kind": "vietnam", "request": dict(QUERY, offset=True)},
    {"kind": "vietnam_dcf", "request": {"result": {"ok": True}}},
])
def test_forged_result_tool_and_path_payloads_are_rejected_without_files(api, payload):
    client, service, _ = api
    response = client.post(BASE, json=payload, headers=HEADERS)
    assert response.status_code == 422
    assert not service.store.path.parent.exists()


def test_different_scopes_return409_without_replacing_any_revision(api):
    client, service, _ = api
    first = create(client).json()
    separate_query = dict(QUERY, consolidation="separate")
    other = create(client, separate_query).json()
    comparison = client.get(f"{BASE}/{other['revision_id']}/diff", params={"before": first["revision_id"]}, headers=HEADERS)
    assert comparison.status_code == 409
    assert comparison.json()["detail"]["code"] == "INCOMPATIBLE_SCOPE"
    parent = create(client, separate_query, parent_revision_id=first["revision_id"])
    assert parent.status_code == 409
    assert parent.json()["detail"]["code"] == "REVISION_SCOPE_MISMATCH"
    assert service.list_revisions()["total"] == 2
    assert service.get_revision(first["revision_id"]) == first


def test_actual_corrupted_manifest_returns409_on_read_list_diff(api):
    client, service, _ = api
    first, second = create(client).json(), create(client).json()
    with sqlite3.connect(service.store.path) as connection:
        connection.execute("DROP TRIGGER immutable_revision_update")
        connection.execute("UPDATE revisions SET manifest='{}' WHERE revision_id=?", (first["revision_id"],))
    for path in (BASE, f"{BASE}/{first['revision_id']}", f"{BASE}/{second['revision_id']}/diff?before={first['revision_id']}"):
        response = client.get(path, headers=HEADERS)
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "ARTIFACT_INTEGRITY_ERROR"


def test_foreign_store_returns409_and_keeps_its_schema(api):
    client, service, _ = api
    service.store.path.parent.mkdir()
    with sqlite3.connect(service.store.path) as connection:
        connection.execute("CREATE TABLE unrelated(value TEXT)")
    original = service.store.path.read_bytes()
    response = client.get(BASE, headers=HEADERS)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "ARTIFACT_STORE_INVALID"
    assert service.store.path.read_bytes() == original


def test_backward_clock_returns409_without_restamping_last_good(api):
    client, service, _ = api
    first = create(client).json()
    service.clock = lambda: datetime(2026, 1, 1, tzinfo=timezone.utc)
    response = create(client, parent_revision_id=first["revision_id"])
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "ARTIFACT_CLOCK_REGRESSION"
    assert service.get_revision(first["revision_id"]) == first


def test_failed_refresh_keeps_last_good_and_returns_safe_failure(api):
    client, service, source = api
    first = create(client).json()
    source.write_text("{}", encoding="utf-8")
    response = create(client, parent_revision_id=first["revision_id"])
    assert response.status_code == 422 and response.json()["detail"]["code"] == "RESEARCH_FAILED"
    assert service.list_revisions()["total"] == 1
    assert service.get_revision(first["revision_id"]) == first


def test_unexpected_storage_exception_does_not_expose_private_details(api, monkeypatch):
    client, service, _ = api
    def fail(**kwargs):
        raise RuntimeError("C:/private/provider-token secret")
    monkeypatch.setattr(service, "list_revisions", fail)
    response = client.get(BASE, headers=HEADERS)
    assert response.status_code == 503 and "provider-token" not in response.text
    assert response.json()["detail"]["code"] == "RESEARCH_ARTIFACT_UNAVAILABLE"


def test_default_lazy_service_list_does_not_create_runtime_files(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBE_TRADING_HOME", str(tmp_path / "runtime"))
    monkeypatch.setattr("src.api.security._configured_api_key", lambda: "fixture-artifact-key")
    app = FastAPI()
    register_research_artifact_routes(app)
    with TestClient(app) as client:
        response = client.get(BASE, headers=HEADERS)
        assert response.status_code == 200 and response.json()["items"] == []
    assert not (tmp_path / "runtime").exists()


@pytest.mark.parametrize("query", ["limit=101", "limit=0", "offset=-1", "offset=100001", "kind=crypto"])
def test_listing_invalid_bounds_fail_without_creating_storage(api, query):
    client, service, _ = api
    assert client.get(BASE + "?" + query, headers=HEADERS).status_code == 422
    assert not service.store.path.parent.exists()


def test_review_cannot_supply_verification_or_invalid_state(api):
    client, _, _ = api
    first = create(client).json()
    path = f"{BASE}/{first['revision_id']}/reviews"
    for payload in ({"decision": "verified", "note": "Read", "reviewer": "Local"},
                    {"decision": "acknowledged", "note": "Read", "reviewer": "Local", "verification_status": "verified"}):
        assert client.post(path, json=payload, headers=HEADERS).status_code == 422
