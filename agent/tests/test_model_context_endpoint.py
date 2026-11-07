"""Draft-chat discovery is authenticated and never invokes a model."""

from __future__ import annotations

import httpx
import pytest
from types import SimpleNamespace
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

import api_server  # noqa: F401 -- settings route registration uses the host module
from src.agent import context_budget
from src.api import custom_provider_routes, settings_routes
from src.providers import custom_profiles, model_metadata
from src.providers import llm

BASE = "https://gateway.example/v1"
MODEL = "vendor/routed-model-1017"


@pytest.fixture
def context_client(monkeypatch):
    model_metadata.clear_model_metadata_cache()
    identity = {"provider": "custom", "model": MODEL, "base_url": BASE}
    monkeypatch.setattr(model_metadata, "configured_model_identity", lambda: identity.copy())
    monkeypatch.setattr(context_budget, "resolve_configured_context", lambda: context_budget.resolve_context(
        identity["provider"], identity["model"], base_url=identity["base_url"],
    ))
    monkeypatch.setattr(custom_profiles, "active_provider_credentials", lambda: {
        "model": MODEL, "base_url": BASE, "api_key": "test-vault-secret",
    })
    monkeypatch.setattr(custom_provider_routes, "_reject_private_dns_targets", lambda base: None)

    async def auth(request: Request):
        if request.headers.get("x-test-auth") != "allowed":
            raise HTTPException(401, "Authentication required")

    app = FastAPI()
    settings_routes.register_settings_routes(app, auth, auth)
    client = TestClient(app, headers={"x-test-auth": "allowed"})
    yield client, identity
    model_metadata.clear_model_metadata_cache()


def test_draft_discovers_limits_once_and_refreshes_without_completion(context_client, monkeypatch):
    client, _ = context_client
    requests = []

    def handle(request):
        requests.append(request)
        assert request.method == "GET" and request.url == BASE + "/models"
        assert request.headers["authorization"] == "Bearer test-vault-secret"
        return httpx.Response(200, json={"data": [{"id": MODEL, "context_length": 64000,
            "max_input_tokens": 60000, "max_output_tokens": 4096}]})

    monkeypatch.setattr(custom_provider_routes, "_provider_async_client", lambda base: httpx.AsyncClient(
        transport=httpx.MockTransport(handle), follow_redirects=False,
    ))
    for path in ("/settings/llm/context", "/settings/llm/context", "/settings/llm/context?refresh=true"):
        response = client.get(path)
        assert response.status_code == 200
        body = response.json()
        assert body["model"] == MODEL and body["window"] == 64000
        assert body["confidence"] == "provider_reported" and body["automatic_compaction"]
        assert body["max_input_tokens"] == 60000 and body["max_output_tokens"] == 4096
        assert "test-vault-secret" not in response.text and "endpoint_scope" not in body
    assert len(requests) == 2


def test_id_only_list_remains_explicitly_a_fallback(context_client, monkeypatch):
    client, _ = context_client
    monkeypatch.setattr(custom_provider_routes, "_provider_async_client", lambda base: httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"data": [{"id": MODEL}]})),
    ))
    response = client.get("/settings/llm/context")
    assert response.status_code == 200
    assert response.json()["confidence"] == "fallback"
    assert response.json()["source"] == "default"


@pytest.mark.parametrize("credentials", [None, {
    "model": "different-model", "base_url": "https://different.example/v1", "api_key": "other-secret",
}])
def test_missing_or_changed_profile_never_sends_a_key_to_stale_endpoint(context_client, monkeypatch, credentials):
    client, _ = context_client
    monkeypatch.setattr(custom_profiles, "active_provider_credentials", lambda: credentials)
    monkeypatch.setattr(custom_provider_routes, "_provider_async_client", lambda base: pytest.fail("No discovery request"))
    response = client.get("/settings/llm/context")
    assert response.status_code == 200
    assert response.json()["warning"] == "model_metadata_unavailable"
    assert response.json()["confidence"] == "fallback"


def test_standard_provider_uses_exact_configured_endpoint(context_client, monkeypatch):
    client, identity = context_client
    identity["provider"] = "deepseek"
    monkeypatch.setattr(settings_routes, "_read_settings_env_values", lambda: {
        "DEEPSEEK_BASE_URL": BASE, "DEEPSEEK_API_KEY": "test-saved-secret",
    })
    requests = []

    async def discover(provider, *, base_url, api_key):
        requests.append((provider.name, base_url, api_key))
        model_metadata.remember_model_metadata(provider.name, base_url, {
            "data": [{"id": MODEL, "context_window": 32000}],
        })
        return settings_routes.LLMModelsResponse(provider=provider.name, models=[MODEL], source="provider")

    monkeypatch.setattr(settings_routes, "_list_provider_models", discover)
    response = client.get("/settings/llm/context?refresh=true")
    assert response.status_code == 200 and response.json()["window"] == 32000
    assert requests == [("deepseek", BASE, "test-saved-secret")]


def test_discovery_requires_auth_before_accessing_credentials(context_client, monkeypatch):
    client, _ = context_client
    monkeypatch.setattr(custom_profiles, "active_provider_credentials", lambda: pytest.fail("No vault read"))
    response = client.get("/settings/llm/context", headers={"x-test-auth": "denied"})
    assert response.status_code == 401


def test_unknown_custom_adapter_rejects_an_unconfirmed_effort(context_client):
    client, _ = context_client
    response = client.put("/settings/llm", json={
        "provider": "custom", "model_name": MODEL, "base_url": BASE, "reasoning_effort": "high",
    })
    assert response.status_code == 400
    assert "empty to leave it unset" in response.json()["detail"]


@pytest.mark.parametrize("provider", ["moonshot", "kimi-coding", "copilot", "gemini", "zhipu", "ollama"])
def test_adapters_without_named_effort_do_not_advertise_it(provider):
    option = settings_routes.LLM_PROVIDER_BY_NAME[provider]
    assert settings_routes._supported_reasoning_efforts(option, option.default_model, option.default_base_url) == []


@pytest.mark.parametrize("mode,available,enabled", [
    ("native", False, False), ("native", True, False),
    ("auto", True, False), ("auto", False, True), ("openai-compatible", True, True),
])
def test_deepseek_effort_choices_follow_the_selected_adapter(monkeypatch, mode, available, enabled):
    option = settings_routes.LLM_PROVIDER_BY_NAME["deepseek"]
    monkeypatch.setattr(llm, "_deepseek_adapter_mode", lambda: mode)
    monkeypatch.setattr(llm, "_native_deepseek_adapter_available", lambda: available)
    levels = settings_routes._supported_reasoning_efforts(option, option.default_model, option.default_base_url)
    assert bool(levels) is enabled


@pytest.mark.parametrize("provider", ["openai", "openrouter", "deepseek", "anthropic"])
def test_gateway_does_not_inherit_vendor_effort_support(provider):
    option = settings_routes.LLM_PROVIDER_BY_NAME[provider]
    assert settings_routes._supported_reasoning_efforts(option, option.default_model, BASE) == []


@pytest.mark.parametrize("model,fields,enabled", [
    ("claude-sonnet-4-6", {"reasoning_effort": object()}, True),
    ("claude-haiku-4-5", {"reasoning_effort": object()}, False),
    ("future-unknown-model", {"reasoning_effort": object()}, False),
    ("claude-sonnet-4-6", {}, False),
])
def test_anthropic_effort_requires_both_model_and_adapter_support(monkeypatch, model, fields, enabled):
    option = settings_routes.LLM_PROVIDER_BY_NAME["anthropic"]
    monkeypatch.setattr(llm, "import_module", lambda name: SimpleNamespace(
        ChatAnthropic=SimpleNamespace(model_fields=fields),
    ))
    levels = settings_routes._supported_reasoning_efforts(option, model, option.default_base_url)
    assert bool(levels) is enabled
    assert "none" not in levels


def test_public_settings_do_not_claim_an_ignored_native_effort(monkeypatch, tmp_path):
    monkeypatch.setattr(api_server, "ENV_PATH", tmp_path / ".env")
    monkeypatch.setattr(llm, "_deepseek_adapter_mode", lambda: "native")
    body = settings_routes._build_llm_settings_response({
        "LANGCHAIN_PROVIDER": "deepseek", "LANGCHAIN_MODEL_NAME": "deepseek-v4-pro",
        "DEEPSEEK_BASE_URL": "https://api.deepseek.com/v1", "LANGCHAIN_REASONING_EFFORT": "medium",
    })
    assert body.reasoning_effort == ""
    assert next(option for option in body.providers if option.name == "deepseek").reasoning_efforts == []
    assert next(option for option in body.providers if option.name == "moonshot").reasoning_efforts == []
    assert not (tmp_path / ".env").exists()


def test_update_rejects_effort_which_the_native_adapter_would_ignore(context_client, monkeypatch):
    client, _ = context_client
    monkeypatch.setattr(llm, "_deepseek_adapter_mode", lambda: "native")
    monkeypatch.setattr(settings_routes, "_read_settings_env_values", lambda: {})
    monkeypatch.setattr(settings_routes, "_persist_settings_updates", lambda values: pytest.fail("No ignored setting saved"))
    response = client.put("/settings/llm", json={
        "provider": "deepseek", "model_name": "deepseek-v4-pro",
        "base_url": "https://api.deepseek.com/v1", "reasoning_effort": "medium",
    })
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_model_discovery_reports_each_models_actual_effort_choices(monkeypatch):
    option = settings_routes.LLM_PROVIDER_BY_NAME["anthropic"]
    monkeypatch.setattr(llm, "import_module", lambda name: SimpleNamespace(
        ChatAnthropic=SimpleNamespace(model_fields={"reasoning_effort": object()}),
    ))
    client_type = httpx.AsyncClient
    monkeypatch.setattr(settings_routes.httpx, "AsyncClient", lambda **kwargs: client_type(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"data": [
            {"id": "claude-sonnet-4-6"}, {"id": "claude-haiku-4-5"},
        ]})),
    ))
    response = await settings_routes._list_provider_models(option, base_url=option.default_base_url, api_key="test-key")
    assert response.effort_levels["claude-sonnet-4-6"] == ["low", "medium", "high", "max"]
    assert response.effort_levels["claude-haiku-4-5"] == []
