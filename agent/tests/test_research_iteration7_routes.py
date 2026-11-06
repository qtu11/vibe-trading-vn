"""Iteration 7 HTTP/MCP contracts against real supplied-data engines and temp storage."""

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backtest.loaders import local_loader
from src.api.research_artifact_routes import register_research_artifact_routes
from src.api.research_routes import register_research_routes
from src.research_artifacts.service import ResearchArtifactService
from src.research_artifacts.store import ResearchArtifactStore
from src.tools.crypto_basis import build_crypto_basis
from src.tools.crypto_basis_tool import CryptoBasisTool
from src.tools.vietnam_reverse_dcf import build_vietnam_reverse_dcf

EXAMPLES = Path(__file__).resolve().parents[2] / "docs/examples"
BASE = "/api/research/artifacts"
AUTH = {"Authorization": "Bearer iteration7-fixture-key"}
NEW_KINDS = ("vietnam_reverse_dcf", "crypto_basis")
FILENAMES = {"vietnam_dcf": "vn-dcf.example.json", "vietnam_comparables": "vn-comparables.example.json",
             "vietnam_reverse_dcf": "vn-reverse-dcf.example.json", "crypto_basis": "crypto-basis.example.json"}
ROUTES = {"vietnam_reverse_dcf": "/api/research/vietnam/reverse-dcf", "crypto_basis": "/api/research/crypto/basis"}
BUILDERS = {"vietnam_reverse_dcf": build_vietnam_reverse_dcf, "crypto_basis": build_crypto_basis}


def supplied(kind):
    if kind == "vietnam":
        return {"code": "CASE.VN", "as_of": "2026-11-06T00:00:00Z"}
    payload = json.loads((EXAMPLES / FILENAMES[kind]).read_text(encoding="utf-8"))
    return {"payload": payload, "offset": 0} if kind == "vietnam_comparables" else payload


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr("src.api.security._configured_api_key", lambda: "iteration7-fixture-key")
    source = tmp_path / "statements.json"
    source.write_bytes((EXAMPLES / "vn-company-research.example.json").read_bytes())
    monkeypatch.setattr(local_loader, "_load_config", lambda: {"financial_statements": [{"symbol": "CASE.VN", "path": str(source)}]})
    service = ResearchArtifactService(ResearchArtifactStore(tmp_path / "research" / "artifacts.sqlite"),
                                      clock=lambda: datetime(2026, 11, 6, 12, tzinfo=timezone.utc))
    app = FastAPI()
    register_research_routes(app)
    register_research_artifact_routes(app, service)
    with TestClient(app) as client:
        yield client, service


def create(client, kind, payload=None, **kwargs):
    return client.post(BASE, json={"kind": kind, "request": supplied(kind) if payload is None else payload, **kwargs}, headers=AUTH)


@pytest.mark.parametrize("kind", NEW_KINDS)
def test_new_calculation_routes_preserve_real_builder_json_without_saving(api, kind):
    client, service = api
    payload = supplied(kind)
    response = client.post(ROUTES[kind], json=payload, headers=AUTH)
    assert response.status_code == 200, response.text
    output = response.json()
    assert output == json.loads(json.dumps(BUILDERS[kind](payload)))
    assert output["verification_status"] == "user_supplied_unverified"
    if kind == "vietnam_reverse_dcf":
        assert output["solver"]["status"] == "solved"
        assert output["solver"]["implied_terminal_growth"] == pytest.approx(0.03, abs=1e-8)
    else:
        assert output["summary"] == {"total": 3, "accepted": 2, "rejected": 1}
        assert output["rows"][0]["basis_fraction"] == "0.02"
        assert output["rows"][2]["annualized_basis"] is None
    assert not service.store.path.parent.exists()


@pytest.mark.parametrize("kind", NEW_KINDS)
def test_calculation_auth_checked_before_real_builder(api, monkeypatch, kind):
    client, service = api
    module = "src.tools.vietnam_reverse_dcf" if kind == "vietnam_reverse_dcf" else "src.tools.crypto_basis"
    function = "build_vietnam_reverse_dcf" if kind == "vietnam_reverse_dcf" else "build_crypto_basis"
    monkeypatch.setattr(f"{module}.{function}", lambda _: pytest.fail("Unauthorized request reached the engine"))
    assert client.post(ROUTES[kind], json=supplied(kind)).status_code == 401
    assert not service.store.path.parent.exists()


@pytest.mark.parametrize("kind", NEW_KINDS)
@pytest.mark.parametrize("extra", ["result", "path", "tool"])
def test_new_routes_reject_forged_outputs_paths_and_tools(api, kind, extra):
    client, service = api
    payload = supplied(kind)
    marker = "C:/private/not-a-source-path-secret"
    payload[extra] = {"ok": True} if extra == "result" else marker
    response = client.post(ROUTES[kind], json=payload, headers=AUTH)
    assert response.status_code == 422 and marker not in response.text
    assert not service.store.path.parent.exists()


@pytest.mark.parametrize("kind", NEW_KINDS)
def test_unexpected_calculation_errors_are_sanitized(api, monkeypatch, kind):
    client, _ = api
    module = "src.tools.vietnam_reverse_dcf" if kind == "vietnam_reverse_dcf" else "src.tools.crypto_basis"
    function = "build_vietnam_reverse_dcf" if kind == "vietnam_reverse_dcf" else "build_crypto_basis"
    def fail(_):
        raise RuntimeError("C:/private/provider-token secret")
    monkeypatch.setattr(f"{module}.{function}", fail)
    response = client.post(ROUTES[kind], json=supplied(kind), headers=AUTH)
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "RESEARCH_UNAVAILABLE"
    assert "provider-token" not in response.text


def test_all_five_kinds_save_actual_outputs_and_keep_database_schema1(api):
    client, service = api
    ids = set()
    for kind in ("vietnam", "vietnam_comparables", "vietnam_dcf", *NEW_KINDS):
        response = create(client, kind)
        assert response.status_code == 200, response.text
        revision = response.json()
        ids.add(revision["revision_id"])
        assert revision["kind"] == kind and revision["result"]["ok"] is True
        assert revision["verification_status"] == "user_supplied_unverified"
        assert revision["review_state"] == "pending_review"
        listing = client.get(BASE, params={"kind": kind}, headers=AUTH).json()
        assert listing["total"] == 1 and listing["items"][0]["revision_id"] == revision["revision_id"]
    assert len(ids) == client.get(BASE, headers=AUTH).json()["total"] == 5
    with sqlite3.connect(service.store.path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
        assert connection.execute("PRAGMA application_id").fetchone()[0] == 0x56524152


@pytest.mark.parametrize("kind", NEW_KINDS)
def test_new_kind_reads_never_initialize_missing_storage(api, kind):
    client, service = api
    result = client.get(BASE, params={"kind": kind}, headers=AUTH)
    assert result.status_code == 200 and result.json() == {"items": [], "total": 0, "next_offset": None}
    assert not service.store.path.parent.exists()


@pytest.mark.parametrize("kind", NEW_KINDS)
def test_new_revision_parent_diff_review_preserve_original_and_unverified_status(api, kind):
    client, service = api
    first_response = create(client, kind)
    assert first_response.status_code == 200, first_response.text
    first = first_response.json()
    payload = supplied(kind)
    if kind == "vietnam_reverse_dcf":
        payload["target_price_vnd"] = str(float(payload["target_price_vnd"]) + 1)
    else:
        payload["futures"][0].update(bid="102.9", ask="103.1")
    second_response = create(client, kind, payload, parent_revision_id=first["revision_id"])
    assert second_response.status_code == 200, second_response.text
    second = second_response.json()
    assert second["parent_revision_id"] == first["revision_id"]
    expected_scope = ({"symbol": "CASE.VN", "consolidation": "consolidated"} if kind == "vietnam_reverse_dcf"
                      else {"base": "CASE", "quote": "USDT"})
    assert second["scope"] == expected_scope
    diff_response = client.get(f"{BASE}/{second['revision_id']}/diff", params={"before": first["revision_id"], "limit": 2}, headers=AUTH)
    assert diff_response.status_code == 200
    diff = diff_response.json()
    assert diff["request_changed"] and diff["facts_changed"] and diff["result_changed"]
    assert not diff["source_changed"] and not diff["producer_changed"]
    assert diff["affected_metrics"] == []  # No narrative/DCF/basis claim graph is inferred.
    assert diff["truncated"] and len(diff["changes"]) == 2
    assert second["producer"]["execution"] == "server_deterministic_engine"
    content_scope = "one_bounded_reverse_dcf_scenario" if kind == "vietnam_reverse_dcf" else "one_supplied_basis_curve"
    assert second["content_scope"] == content_scope
    review = client.post(f"{BASE}/{second['revision_id']}/reviews", json={"decision": "acknowledged", "note": "Đã đọc; nguồn còn chưa xác minh", "reviewer": "Người kiểm tra"}, headers=AUTH)
    assert review.status_code == 200 and review.json()["verification_status"] == "user_supplied_unverified"
    current = client.get(f"{BASE}/{second['revision_id']}", headers=AUTH).json()
    assert current["review_state"] == "acknowledged"
    assert current["review_history"][0]["reviewer_identity"] == "self_reported_operator_label"
    assert current["hashes"] == second["hashes"] and current["result"] == second["result"]
    assert service.get_revision(first["revision_id"]) == first


def test_reverse_dcf_evidence_only_change_does_not_claim_financial_fact_change(api):
    client, _ = api
    first = create(client, "vietnam_reverse_dcf").json()
    payload = supplied("vietnam_reverse_dcf")
    payload["price_evidence"]["document_sha256"] = "b" * 64
    second = create(client, "vietnam_reverse_dcf", payload).json()
    response = client.get(f"{BASE}/{second['revision_id']}/diff", params={"before": first["revision_id"]}, headers=AUTH)
    assert response.status_code == 200
    diff = response.json()
    assert diff["source_changed"] and not diff["facts_changed"]
    assert diff["affected_metrics"] == []


@pytest.mark.parametrize("kind", NEW_KINDS)
def test_unavailable_outputs_remain_null_in_saved_research(api, kind):
    client, _ = api
    payload = supplied(kind)
    if kind == "vietnam_reverse_dcf":
        payload["target_price_vnd"] = "1000000000"
    else:
        payload["futures"] = [payload["futures"][-1]]  # A perpetual has no dated basis.
    response = create(client, kind, payload)
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    if kind == "vietnam_reverse_dcf":
        assert result["solver"]["status"] == "outside_bracket"
        assert result["solver"]["implied_terminal_growth"] is None
    else:
        assert result["summary"] == {"total": 1, "accepted": 0, "rejected": 1}
        assert result["rows"][0]["annualized_basis"] is None
    assert result["verification_status"] == "user_supplied_unverified"


@pytest.mark.parametrize("kind", NEW_KINDS)
def test_new_artifact_write_auth_and_cross_site_gate_precede_storage(api, kind):
    client, service = api
    body = {"kind": kind, "request": supplied(kind)}
    assert client.post(BASE, json=body).status_code == 401
    blocked = client.post(BASE, json=body, headers={**AUTH, "Origin": "https://hostile.invalid", "Sec-Fetch-Site": "cross-site"})
    assert blocked.status_code == 403
    assert not service.store.path.parent.exists()


@pytest.mark.parametrize("kind", NEW_KINDS)
@pytest.mark.parametrize("extra", ["result", "path", "mode"])
def test_new_artifact_inputs_cannot_forge_result_or_capture(api, kind, extra):
    client, service = api
    payload = supplied(kind)
    payload[extra] = {"ok": True} if extra == "result" else "capture" if extra == "mode" else "C:/private/source.json"
    response = create(client, kind, payload)
    assert response.status_code == 422
    assert not service.store.path.parent.exists()


@pytest.mark.parametrize("kind", NEW_KINDS)
def test_parent_scope_mismatch_is409_and_does_not_replace_source_revision(api, kind):
    client, service = api
    first = create(client, kind).json()
    payload = supplied(kind)
    if kind == "vietnam_reverse_dcf":
        payload["dcf"]["symbol"] = "OTHER.VN"
    else:
        payload["base"] = payload["spot"]["base"] = "OTHER"
        for future in payload["futures"]:
            future["base"] = "OTHER"
    response = create(client, kind, payload, parent_revision_id=first["revision_id"])
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "REVISION_SCOPE_MISMATCH"
    assert service.list_revisions()["total"] == 1
    assert service.get_revision(first["revision_id"]) == first


@pytest.mark.asyncio
async def test_real_main_mcp_basis_wrapper_reaches_readonly_tool_and_preserves_rejections(monkeypatch):
    import mcp_server
    from fastmcp import Client
    from src.agent.tools import ToolRegistry
    tool = CryptoBasisTool()
    assert tool.is_readonly is True and tool.deterministic is True and tool.repeatable is True
    assert tool.parameters["additionalProperties"] is False
    assert set(tool.parameters["properties"]) == {"payload", "offset"}
    payload = supplied("crypto_basis")
    registry = ToolRegistry()
    registry.register(tool)
    monkeypatch.setattr(mcp_server, "_registry", registry)
    async with Client(mcp_server.mcp) as client:
        listed = await client.list_tools()
        schema = next(entry for entry in listed if entry.name == "crypto_basis_curve").inputSchema
        assert set(schema["properties"]) == {"payload", "offset"}
        assert "mode" not in schema["properties"]
        response = await client.call_tool("crypto_basis_curve", {"payload": payload, "offset": 0})
    output = json.loads(response.content[0].text)
    assert output == json.loads(tool.execute(payload=payload, offset=0))
    assert output["summary"] == {"total": 3, "accepted": 2, "rejected": 1}
    assert output["rows"][2]["annualized_basis"] is None
    assert output["verification_status"] == "user_supplied_unverified"


@pytest.mark.parametrize("field", ["mode", "path", "result"])
def test_main_mcp_basis_forwards_payload_into_domain_validation_not_capture(monkeypatch, field):
    import mcp_server
    from src.agent.tools import ToolRegistry
    registry = ToolRegistry()
    registry.register(CryptoBasisTool())
    monkeypatch.setattr(mcp_server, "_registry", registry)
    payload = supplied("crypto_basis")
    payload[field] = "capture" if field == "mode" else "C:/private/source.json" if field == "path" else {"ok": True}
    output = json.loads(mcp_server.crypto_basis_curve(payload))
    assert output["ok"] is False and "error" in output
