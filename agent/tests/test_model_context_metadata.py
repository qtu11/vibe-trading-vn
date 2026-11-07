"""Offline provider identity/limit discovery, with no keys or model calls."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
import json
from types import SimpleNamespace

import pytest

from src.agent.context_budget import CompactionBudget, resolve_configured_context, resolve_context, resolve_window
from src.providers import model_metadata as mm

MODEL = "deepseek-ai/deepseek-v4.1-flash-1017"
BASE = "https://gateway.example/v1"


@pytest.fixture(autouse=True)
def clean_metadata():
    mm.clear_model_metadata_cache()
    yield
    mm.clear_model_metadata_cache()


def test_exact_routed_dated_id_uses_explicit_gateway_limits_without_guessing():
    records = mm.remember_model_metadata("custom", BASE, {"data": [{"id": MODEL, "context_length": 1048576, "top_provider": {"max_prompt_tokens": 950000, "max_completion_tokens": 32768}}]})
    result = resolve_context("custom", MODEL, base_url=BASE)
    assert result.window == 1048576 and result.source == "provider:/models"
    assert result.confidence == "provider_reported"
    assert result.max_input_tokens == 950000 and result.max_output_tokens == 32768
    assert records[MODEL]["endpoint_scope"] == result.endpoint_scope
    assert result.reported_fields["context_length"] == 1048576
    assert resolve_context("custom", MODEL.removesuffix("-1017"), base_url=BASE).confidence == "fallback"
    assert resolve_context("custom", MODEL + "-new", base_url=BASE).confidence == "fallback"


def test_gateway_and_provider_scoping_prevents_borrowing_other_deployment_limit():
    metadata = mm.remember_model_metadata("custom", BASE, {"data": [{"id": MODEL, "max_model_len": 64000}]})[MODEL]
    assert resolve_context("custom", MODEL, base_url=BASE).window == 64000
    for provider, base in [("openai", BASE), ("custom", "https://other.example/v1"), ("custom", BASE + "/account-b")]:
        assert resolve_context(provider, MODEL, base_url=base).confidence == "fallback"
        assert resolve_context(provider, MODEL, base_url=base, provider_metadata=metadata).confidence == "fallback"
    assert resolve_context("custom", MODEL, base_url=BASE + "/chat/completions").window == 64000


def test_unknown_id_only_model_list_does_not_turn_model_name_into_a_specification():
    mm.remember_model_metadata("custom", BASE, {"data": [{"id": MODEL, "description": "1M tokens"}]})
    result = resolve_context("custom", MODEL, base_url=BASE)
    assert (result.window, result.source, result.confidence) == (128000, "default", "fallback")
    assert not result.reported_fields


@pytest.mark.parametrize("bad", [None, True, False, -1, 0, 999, "1M", "1048576.0", 1.5, float("inf"), 100000001, "١٠٤٨٥٧٦"])
def test_invalid_context_limit_values_are_never_trusted(bad):
    assert mm.normalize_model_metadata({"models": [{"name": "m", "context_window": bad}]}) == {}


def test_alias_fields_conflicts_and_output_only_are_not_misinterpreted():
    metadata = mm.normalize_model_metadata({"data": [{"id": "m", "context_window": 200000, "context_length": "131072", "limits": {"max_input_tokens": 120000}, "max_output_tokens": 4096}]})["m"]
    assert metadata["context_window"] == 131072
    assert metadata["max_input_tokens"] == 120000
    mm.remember_model_metadata("custom", BASE, {"data": [{"id": "out-only", "max_output_tokens": 32768}]})
    result = resolve_context("custom", "out-only", base_url=BASE)
    assert result.window == 128000 and result.confidence == "fallback"
    assert result.max_output_tokens == 32768 and result.max_input_tokens is None


def test_duplicates_use_smallest_explicit_limit_and_refresh_can_remove_stale_metadata():
    records = mm.remember_model_metadata("custom", BASE, {"data": [{"id": MODEL, "context_length": 1000000}, {"id": MODEL, "context_length": 64000}]})
    assert records[MODEL]["context_window"] == 64000
    assert resolve_context("custom", MODEL, base_url=BASE).window == 64000
    assert mm.remember_model_metadata("custom", BASE, {"data": [{"id": MODEL}]}) == {}
    assert resolve_context("custom", MODEL, base_url=BASE).confidence == "fallback"


def test_cache_has_ttl_and_capacity_and_returns_detached_values(monkeypatch):
    ticks = [1.0]
    monkeypatch.setattr(mm.time, "monotonic", lambda: ticks[0])
    monkeypatch.setattr(mm, "_MAX_ENTRIES", 2)
    mm.remember_model_metadata("custom", BASE, {"data": [{"id": "a", "context_window": 32000}, {"id": "b", "context_window": 64000}, {"id": "c", "context_window": 96000}]})
    assert mm.cached_model_metadata("custom", BASE, "a") is None
    detached = mm.cached_model_metadata("custom", BASE, "b")
    detached["context_window"] = 99999999
    assert mm.cached_model_metadata("custom", BASE, "b")["context_window"] == 64000
    ticks[0] = 1801.0
    assert mm.cached_model_metadata("custom", BASE, "b") is None


def test_registry_concurrent_endpoint_updates_are_bounded(monkeypatch):
    monkeypatch.setattr(mm, "_MAX_ENTRIES", 8)

    def mutate(index):
        base = f"https://gateway-{index}.example/v1"
        mm.remember_model_metadata("custom", base, {"data": [{"id": "m", "context_window": 64000}]})
        value = mm.cached_model_metadata("custom", base, "m")
        assert value is None or value["context_window"] == 64000

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(mutate, range(100)))
    assert len(mm._CACHE) <= 8


@pytest.mark.parametrize("base", ["https://user:password@example.com/v1", "https://example.com/v1?key=private", "https://example.com/v1#secret", "file:///tmp/models", "https://example.com:99999"])
def test_unsafe_endpoint_identity_never_retains_credentials_or_metadata(base):
    assert mm.normalize_endpoint(base) == ""
    assert mm.endpoint_scope(base) == ""
    mm.remember_model_metadata("custom", base, {"data": [{"id": "m", "context_length": 64000}]})
    assert mm.cached_model_metadata("custom", base, "m") is None
    assert not mm._CACHE


def test_normalized_endpoint_keeps_route_and_ignores_default_port_only():
    assert mm.normalize_endpoint("HTTPS://EXAMPLE.COM:443/team/v1/chat/completions/") == "https://example.com/team/v1"
    assert mm.normalize_endpoint("http://[::1]:11434/v1/models") == "http://[::1]:11434/v1"


def test_resolution_precedence_and_no_catalog_leak_to_custom_gateway():
    mm.remember_model_metadata("custom", BASE, {"data": [{"id": MODEL, "context_window": 64000}]})
    result = resolve_context("custom", MODEL, base_url=BASE, env_window=128000, learned_window=32000)
    assert result.window == 128000 and result.confidence == "operator_override"
    result = resolve_context("custom", MODEL, base_url=BASE, learned_window=32000)
    assert result.window == 32000 and result.confidence == "provider_error"
    assert resolve_window("custom", MODEL, base_url=BASE) == (64000, "provider:/models")
    assert resolve_context("custom", "deepseek-flash", base_url=BASE).confidence == "fallback"
    assert resolve_context("deepseek", "deepseek-flash", base_url=BASE).confidence == "fallback"
    assert resolve_context("deepseek", "deepseek-v4.1-flash-1017", base_url="https://api.deepseek.com/v1").confidence == "catalog"


@pytest.mark.parametrize("window,static,reserve,prompt,cap", [(32000,48000,4096,None,200000),(64000,10000,32000,50000,200000),(1000000,48000,16384,180000,200000),(1000,900,1500,None,200000),(64000,1000,0,None,20000)])
def test_output_reservation_input_limits_and_cost_cap_never_expand_window(window, static, reserve, prompt, cap):
    budget = CompactionBudget(window=window, source="test", max_tokens=cap, static_tokens=static, output_reserve=reserve, prompt_limit=prompt)
    assert 0 <= budget.micro_at <= budget.collapse_at <= budget.compact_at == budget.total <= budget.hard_limit <= max(0, window-reserve)
    assert budget.total <= cap
    if prompt is not None:
        assert budget.hard_limit <= prompt
    if static >= budget.total:
        assert budget.conversation == 0 and budget.static_over_budget


def test_read_selected_custom_identity_does_not_open_vault_or_create_model(tmp_path, monkeypatch):
    from src.providers.custom_profiles import CustomProviderStore
    from src.trading.credentials import CredentialStore

    store_path = tmp_path / "custom.json"
    store_path.write_text(json.dumps({"active_id": "p", "profiles": {"p": {"model": MODEL, "base_url": BASE}}}), encoding="utf-8")
    monkeypatch.setattr(CustomProviderStore, "_read", lambda self: json.loads(store_path.read_text()))
    monkeypatch.setattr(CredentialStore, "load", lambda *args, **kwargs: pytest.fail("No credential reads during context resolution"))
    config = SimpleNamespace(llm=SimpleNamespace(langchain_provider="custom", langchain_model_name="stale-env"), agent_tuning=SimpleNamespace(vibe_trading_context_window=None))
    mm.remember_model_metadata("custom", BASE, {"data": [{"id": MODEL, "context_window": 64000}]})
    result = resolve_configured_context(config)
    assert result.model_id == MODEL and result.window == 64000
    assert not (tmp_path / "jobs.sqlite").exists()


def test_runtime_snapshot_captures_actual_adapter_identity_and_output_reserve(monkeypatch):
    from src.providers import chat

    config = SimpleNamespace(llm=SimpleNamespace(langchain_provider="custom", langchain_model_name="stale-model", langchain_reasoning_effort="high", langchain_max_tokens=None))
    monkeypatch.setattr(chat, "get_env_config", lambda: config)
    monkeypatch.setattr(mm, "configured_model_identity", lambda cfg: {"provider":"custom", "model":"stale-model", "base_url":"https://stale.example/v1"})
    monkeypatch.setattr(chat, "build_llm", lambda **kwargs: SimpleNamespace(model_name=MODEL, openai_api_base=BASE, max_tokens=8192))
    mm.remember_model_metadata("custom", BASE, {"data": [{"id": MODEL, "context_window": 64000}]})
    llm = chat.ChatLLM()
    assert llm.model_name == MODEL
    assert llm.runtime_snapshot.base_url == BASE and llm.runtime_snapshot.output_reserve == 8192
    assert llm.context_metadata["context_window"] == 64000
    config.llm.langchain_model_name = "new-model"
    assert llm.runtime_snapshot.configured_model == MODEL
    with pytest.raises(FrozenInstanceError):
        llm.runtime_snapshot.base_url = "https://new.example"
