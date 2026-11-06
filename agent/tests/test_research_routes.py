"""The web surface uses the same research engines and preserves auth/evidence."""

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backtest.loaders import local_loader
from src.api.research_routes import register_research_routes
from src.api.security import require_auth
from src.tools import crypto_derivatives_tool
from src.tools.vietnam_research_tool import VietnamResearchTool
from src.tools.vietnam_comparables_tool import VietnamComparablesTool
from src.tools.crypto_derivatives_archive import DerivativesArchive


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBE_TRADING_HOME", str(tmp_path))
    source = Path(__file__).resolve().parents[2] / "docs/examples/vn-company-research.example.json"
    config = tmp_path / "config.yaml"
    config.write_text(f"financial_statements:\n  - symbol: CASE.VN\n    path: {source.as_posix()}\n", encoding="utf-8")
    monkeypatch.setattr(local_loader, "_CONFIG_PATH", config)
    app = FastAPI()
    register_research_routes(app)
    app.dependency_overrides[require_auth] = lambda: None
    with TestClient(app) as test_client:
        yield test_client


def test_vietnam_route_preserves_real_engine_evidence_and_exact_decimals(client):
    args = {"code": "CASE.VN", "as_of": "2025-08-01T00:00:00Z"}
    response = client.post("/api/research/vietnam", json=args)
    assert response.status_code == 200
    result = response.json()
    assert result == json.loads(VietnamResearchTool().execute(**args))
    company = result["data"]["CASE.VN"]
    assert company["verification_status"] == "user_supplied_unverified"
    assert len(company["source_file_sha256"]) == 64
    assert company["periods"][0]["metrics"]["free_cash_flow"]["value"] == "65000000"
    assert company["periods"][0]["evidence"][0]["source_url"].startswith("https://")


@pytest.mark.parametrize("path,payload", [
    ("vietnam", {"code": "../CASE.VN"}),
    ("vietnam", {"code": "CASE.VN", "path": "C:/secret"}),
    ("vietnam", {"code": "CASE.VN", "as_of": "2025-01-01"}),
    ("vietnam", {"code": "CASE.VN", "offset": True}),
    ("vietnam", {"code": "CASE.VN", "offset": -1}),
    ("crypto", {"symbol": "BTC-USDT"}),
    ("crypto", {"symbol": "BTC-USDT-PERP", "limit": "30"}),
    ("crypto", {"symbol": "BTC-USDT-PERP", "limit": True}),
    ("crypto", {"symbol": "BTC-USDT-PERP", "limit": 101}),
    ("crypto", {"symbol": "BTC-USDT-PERP", "metric": "on_chain"}),
    ("crypto", {"symbol": "BTC-USDT-PERP", "tool": "shell"}),
])
def test_bad_arguments_rejected_before_engine(client, monkeypatch, path, payload):
    def forbidden(**_):
        pytest.fail("Invalid request must not invoke a research tool")
    monkeypatch.setattr(VietnamResearchTool, "execute", lambda self, **kwargs: forbidden(**kwargs))
    monkeypatch.setattr(crypto_derivatives_tool.CryptoDerivativesTool, "execute", lambda self, **kwargs: forbidden(**kwargs))
    assert client.post(f"/api/research/{path}", json=payload).status_code == 422


def test_crypto_route_uses_fixture_history_without_network(client, monkeypatch):
    market = {"symbol": "BTC/USDT:USDT", "base": "BTC", "quote": "USDT", "settle": "USDT", "swap": True,
              "linear": True, "inverse": False, "expiry": None, "contractSize": 1}
    rows = [{"symbol": market["symbol"], "timestamp": timestamp, "openInterestAmount": amount, "openInterestValue": amount * 100}
            for timestamp, amount in [(1704067200000, 10), (1704070800000, 12)]]
    calls = []
    def fixture_fetch(*args):
        calls.append(args)
        return market, rows
    monkeypatch.setattr(crypto_derivatives_tool, "_fetch_history", fixture_fetch)
    result = client.post("/api/research/crypto", json={"symbol": "BTC-USDT-PERP", "limit": 2}).json()
    assert result["ok"] and calls == [("BTC/USDT:USDT", "open_interest", "1h", 2)]
    assert result["summary"]["change_amount_base"] == 2
    assert result["provenance"]["historical_available_at"] is None
    assert result["coverage"]["unique_records"] == 2


def test_tool_error_is_preserved_and_unexpected_error_is_sanitized(client, monkeypatch):
    missing = client.post("/api/research/vietnam", json={"code": "UNSET.VN"}).json()
    assert missing["ok"] is False and "error" in missing
    def fail(self, **kwargs):
        raise RuntimeError("C:/private/path provider-secret")
    monkeypatch.setattr(VietnamResearchTool, "execute", fail)
    response = client.post("/api/research/vietnam", json={"code": "CASE.VN"})
    assert response.status_code == 503 and "provider-secret" not in response.text
    assert response.json()["detail"]["code"] == "RESEARCH_UNAVAILABLE"


@pytest.mark.parametrize("route,payload", [("vietnam", {"code": "CASE.VN"}), ("crypto", {"symbol": "BTC-USDT-PERP"})])
def test_auth_checked_before_research(monkeypatch, route, payload):
    monkeypatch.setattr("src.api.security._configured_api_key", lambda: "fixture-app-key")
    monkeypatch.setattr(VietnamResearchTool, "execute", lambda self, **_: '{"ok":true}')
    monkeypatch.setattr(crypto_derivatives_tool.CryptoDerivativesTool, "execute", lambda self, **_: '{"ok":true}')
    app = FastAPI()
    register_research_routes(app)
    with TestClient(app) as client:
        assert client.post(f"/api/research/{route}", json=payload).status_code == 401
        assert client.post(f"/api/research/{route}", json=payload, headers={"Authorization": "Bearer fixture-app-key"}).json() == {"ok": True}


def test_vietnam_comparables_api_executes_same_pure_tool(client):
    fixture = Path(__file__).resolve().parents[2] / "docs/examples/vn-comparables.example.json"
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    result = client.post("/api/research/vietnam/comparables", json={"payload": payload}).json()
    assert result == json.loads(VietnamComparablesTool().execute(payload=payload))
    assert result["ok"]
    assert result["target"]["scenarios"]["pe"]["prices"]["median"] == 20000


def test_crypto_capture_then_read_archive_without_another_provider_call(client, tmp_path, monkeypatch):
    archive = DerivativesArchive(tmp_path / "archive.sqlite")
    monkeypatch.setattr(crypto_derivatives_tool, "configured_archive", lambda: archive)
    market = {"symbol": "BTC/USDT:USDT", "base": "BTC", "quote": "USDT", "settle": "USDT", "swap": True,
              "linear": True, "inverse": False, "expiry": None, "contractSize": 1}
    rows = [{"symbol": market["symbol"], "timestamp": timestamp, "openInterestAmount": amount, "openInterestValue": amount * 100}
            for timestamp, amount in [(1704067200000, 10), (1704070800000, 12)]]
    monkeypatch.setattr(crypto_derivatives_tool, "_fetch_history", lambda *_: (market, rows))
    captured = client.post("/api/research/crypto/captures", json={"symbol": "BTC-USDT-PERP", "limit": 2}).json()
    assert captured["ok"], captured
    cutoff = captured["archive"]["recorded_at"]
    monkeypatch.setattr(crypto_derivatives_tool, "_fetch_history", lambda *_: pytest.fail("Archive read must not fetch"))
    result = client.post("/api/research/crypto", json={"symbol": "BTC-USDT-PERP", "limit": 2, "mode": "archive", "as_of": cutoff}).json()
    assert result["ok"], result
    assert result["source"] == "local_crypto_derivatives_archive"
    assert result["summary"]["change_amount_base"] == 2
    assert result["provenance"]["historical_available_at"] is None


@pytest.mark.parametrize("payload", [
    {"symbol": "BTC-USDT-PERP", "mode": "capture"},
    {"symbol": "BTC-USDT-PERP", "mode": "archive"},
    {"symbol": "BTC-USDT-PERP", "mode": "archive", "as_of": "2025-01-01"},
    {"symbol": "BTC-USDT-PERP", "mode": "live", "as_of": "2025-01-01T00:00:00Z"},
])
def test_crypto_read_route_rejects_write_mode_or_invalid_archive_cutoff(client, monkeypatch, payload):
    monkeypatch.setattr(crypto_derivatives_tool.CryptoDerivativesTool, "execute", lambda self, **_: pytest.fail("Invalid read must not execute"))
    assert client.post("/api/research/crypto", json=payload).status_code == 422


def test_capture_requires_write_auth_and_rejects_cross_site_writes(monkeypatch):
    calls = []
    monkeypatch.setattr("src.api.security._configured_api_key", lambda: "fixture-app-key")
    monkeypatch.setattr(crypto_derivatives_tool.CryptoDerivativesTool, "execute", lambda self, **kwargs: calls.append(kwargs) or '{"ok":true}')
    app = FastAPI(); register_research_routes(app)
    with TestClient(app) as client:
        payload = {"symbol": "BTC-USDT-PERP"}
        assert client.post("/api/research/crypto/captures", json=payload).status_code == 401
        headers = {"Authorization": "Bearer fixture-app-key"}
        assert client.post("/api/research/crypto/captures", json=payload, headers={**headers, "Origin": "https://untrusted.invalid", "Sec-Fetch-Site": "cross-site"}).status_code == 403
        assert calls == []
        assert client.post("/api/research/crypto/captures", json=payload, headers=headers).json() == {"ok": True}
        assert calls[0]["mode"] == "capture"


def test_main_mcp_rejects_capture_before_registry(monkeypatch):
    import mcp_server
    monkeypatch.setattr(mcp_server, "_get_registry", lambda: pytest.fail("MCP read must not reach capture"))
    result = json.loads(mcp_server.crypto_derivatives("BTC-USDT-PERP", mode="capture"))
    assert result["ok"] is False and result["error_code"] == "INVALID_ARGUMENT"


def test_vietnam_dcf_http_executes_same_pure_engine_and_preserves_scenario_limits(client):
    from src.tools.vietnam_dcf import build_vietnam_dcf
    fixture = Path(__file__).resolve().parents[2] / "docs/examples/vn-dcf.example.json"
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    response = client.post("/api/research/vietnam/dcf", json=payload)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result == json.loads(json.dumps(build_vietnam_dcf(payload)))
    assert result["methodology"] == "declared_non_financial_fcff_scenario"
    assert result["sensitivity"]["probabilities_assigned"] is False
    assert result["base_case"]["value_per_share"] > 0
    assert "caller-declared and unverified" in " ".join(result["limitations"])


@pytest.mark.parametrize("change", ["extra_path", "string_beta", "missing_forecast", "future_source"])
def test_vietnam_dcf_http_rejects_invalid_inputs_without_disclosing_values(client, change):
    fixture = Path(__file__).resolve().parents[2] / "docs/examples/vn-dcf.example.json"
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    marker = "C:/private/never-disclose-secret"
    if change == "extra_path":
        payload["path"] = marker
    elif change == "string_beta":
        payload["wacc"]["beta"]["value"] = marker
    elif change == "missing_forecast":
        payload.pop("forecast")
    else:
        payload["as_of"] = "2020-01-01T00:00:00Z"
    response = client.post("/api/research/vietnam/dcf", json=payload)
    assert response.status_code == 422
    assert marker not in response.text


def test_vietnam_dcf_read_auth_runs_before_engine(monkeypatch):
    monkeypatch.setattr("src.api.security._configured_api_key", lambda: "fixture-app-key")
    calls = []
    monkeypatch.setattr("src.api.research_routes.build_vietnam_dcf", lambda payload: calls.append(payload) or {"ok": True})
    app = FastAPI()
    register_research_routes(app)
    with TestClient(app) as test_client:
        assert test_client.post("/api/research/vietnam/dcf", json={}).status_code == 401
        assert calls == []
        response = test_client.post("/api/research/vietnam/dcf", json={}, headers={"Authorization": "Bearer fixture-app-key"})
        assert response.status_code == 200 and response.json() == {"ok": True}
        assert calls == [{}]


def test_vietnam_dcf_http_sanitizes_unexpected_engine_errors(client, monkeypatch):
    def fail(_):
        raise RuntimeError("C:/private/provider-token secret")
    monkeypatch.setattr("src.api.research_routes.build_vietnam_dcf", fail)
    response = client.post("/api/research/vietnam/dcf", json={})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "RESEARCH_UNAVAILABLE"
    assert "provider-token" not in response.text
