"""Normalize explicit model limits without guessing from model names.

OpenAI-compatible /models responses often contain IDs only. Such an ID is not
evidence of a context window. Metadata here is provider-reported, scoped to the
exact provider, endpoint and model ID, and expires from a bounded memory cache.
This module performs no network, credential or filesystem operations.
"""

from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
import hashlib
import threading
import time
from typing import Any
from urllib.parse import urlsplit, urlunsplit

_TTL_SECONDS = 1800.0
_MAX_ENTRIES = 2048
_MAX_TOKEN_LIMIT = 100_000_000
_CACHE: OrderedDict[tuple[str, str, str], tuple[float, dict]] = OrderedDict()
_LOCK = threading.RLock()

_LIMIT_PATHS = {
    "context_window": ("context_window", "context_length", "max_context_tokens", "max_model_len", "context_window_tokens", "limit.context", "limits.context", "limits.context_window"),
    "max_input_tokens": ("max_input_tokens", "input_token_limit", "max_prompt_tokens", "top_provider.max_prompt_tokens", "limit.input", "limits.max_input_tokens", "limits.max_prompt_tokens"),
    "max_output_tokens": ("max_output_tokens", "output_token_limit", "max_completion_tokens", "top_provider.max_completion_tokens", "limit.output", "limits.max_output_tokens"),
}


def token_limit(value: Any, *, minimum: int = 1) -> int | None:
    """Accept only bounded positive integers, including decimal wire strings."""
    if isinstance(value, str) and value.isascii() and value.isdecimal() and len(value) <= 9:
        value = int(value)
    return value if type(value) is int and minimum <= value <= _MAX_TOKEN_LIMIT else None


def normalize_endpoint(base_url: str | None) -> str:
    """Canonical endpoint identity; never accept credentials/query/fragment."""
    try:
        parsed = urlsplit((base_url or "").strip())
        if (parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname or
                parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment):
            return ""
        host = parsed.hostname.lower().rstrip(".")
        if ":" in host:
            host = f"[{host}]"
        port = parsed.port
        if port is not None and not (parsed.scheme.lower() == "https" and port == 443 or parsed.scheme.lower() == "http" and port == 80):
            host += f":{port}"
        path = parsed.path.rstrip("/")
        for suffix in ("/chat/completions", "/responses", "/models"):
            if path.endswith(suffix):
                path = path[:-len(suffix)].rstrip("/")
                break
        return urlunsplit((parsed.scheme.lower(), host, path, "", ""))
    except (ValueError, TypeError):
        return ""


def endpoint_scope(base_url: str | None) -> str:
    normalized = normalize_endpoint(base_url)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest() if normalized else ""


def _get(record: dict, path: str) -> Any:
    value: Any = record
    for part in path.split("."):
        value = value.get(part) if isinstance(value, dict) else None
    return value


def normalize_model_metadata(payload: Any) -> dict[str, dict]:
    """Extract only explicit limits from common /models response records.

    Routed names and dated versions remain exact IDs. We never strip a suffix,
    treat an output limit as a context window, or infer limits from descriptions.
    Conflicting explicit fields use the smallest reported number and retain
    field provenance so that a gateway cannot inflate an enforced smaller cap.
    """
    if not isinstance(payload, dict):
        return {}
    records = payload.get("data", payload.get("models"))
    if not isinstance(records, list):
        return {}
    result = {}
    for record in records[:1000]:
        if not isinstance(record, dict):
            continue
        model = record.get("id") or record.get("name")
        if not isinstance(model, str) or not 1 <= len(model.strip()) <= 300:
            continue
        model = model.strip()
        normalized: dict = {"model_id": model, "source": "provider:/models", "confidence": "provider_reported", "reported_fields": {}}
        for field, paths in _LIMIT_PATHS.items():
            values = {path: value for path in paths if (value := token_limit(_get(record, path), minimum=1000 if field == "context_window" else 1)) is not None}
            if values:
                normalized[field] = min(values.values())
                normalized["reported_fields"].update(values)
        if normalized["reported_fields"]:
            previous = result.get(model)
            if previous is not None:
                for field in _LIMIT_PATHS:
                    values = [item[field] for item in (previous, normalized) if field in item]
                    if values:
                        normalized[field] = min(values)
                normalized["reported_fields"] = {**previous["reported_fields"], **normalized["reported_fields"]}
            result[model] = normalized
    return result


def remember_model_metadata(provider: str, base_url: str, payload: Any) -> dict[str, dict]:
    """Store sanitized limits for this exact endpoint; no keys are retained."""
    normalized = normalize_model_metadata(payload)
    scope = endpoint_scope(base_url)
    provider = (provider or "").strip().lower().replace("_", "-")
    if not scope or not provider:
        return normalized
    now = time.monotonic()
    for metadata in normalized.values():
        metadata["provider"] = provider
        metadata["endpoint_scope"] = scope
    with _LOCK:
        _expire(now)
        # A successful model-list response supersedes prior metadata for this
        # endpoint, including a refreshed ID-only response that omits limits.
        for key in list(_CACHE):
            if key[:2] == (provider, scope):
                del _CACHE[key]
        for model, metadata in normalized.items():
            _CACHE[(provider, scope, model)] = (now, deepcopy(metadata))
        while len(_CACHE) > _MAX_ENTRIES:
            _CACHE.popitem(last=False)
    return normalized


def _expire(now: float) -> None:
    for key, (created, _) in list(_CACHE.items()):
        if now - created >= _TTL_SECONDS:
            del _CACHE[key]


def cached_model_metadata(provider: str, base_url: str, model: str) -> dict | None:
    """Read a detached exact-identity entry, never start a provider request."""
    scope = endpoint_scope(base_url)
    if not scope:
        return None
    key = ((provider or "").strip().lower().replace("_", "-"), scope, (model or "").strip())
    with _LOCK:
        _expire(time.monotonic())
        value = _CACHE.get(key)
        if value is None:
            return None
        _CACHE.move_to_end(key)
        return deepcopy(value[1])


def clear_model_metadata_cache() -> None:
    """Clear process-local discovery state, useful when settings are reloaded."""
    with _LOCK:
        _CACHE.clear()


def configured_model_identity(config=None) -> dict[str, str]:
    """Read selected identity without constructing an LLM or opening a vault.

    Custom profile metadata is read separately from its credential status. This
    function does not probe the provider and never reads an API key.
    """
    from src.config.accessor import get_env_config, get_env_value
    from src.providers.capabilities import get_provider_capabilities, _provider_default_base_url

    config = config if config is not None else get_env_config()
    provider = str(config.llm.langchain_provider or "").strip().lower().replace("_", "-")
    model = str(config.llm.langchain_model_name or "").strip()
    base_url = ""
    if provider == "custom":
        from src.providers.custom_profiles import CustomProviderStore

        try:
            payload = CustomProviderStore()._read()
            item = payload.get("profiles", {}).get(payload.get("active_id"), {})
            if isinstance(item, dict):
                model = str(item.get("model") or model).strip()
                base_url = str(item.get("base_url") or "").strip()
        except (ValueError, OSError):
            pass
    elif provider == "openai-codex":
        base_url = str(config.llm.openai_codex_base_url or "")
    elif provider != "claude-cli":
        caps = get_provider_capabilities(provider, model)
        base_url = (get_env_value(caps.base_url_env) if caps.base_url_env else "") or get_env_value("OPENAI_BASE_URL") or get_env_value("OPENAI_API_BASE") or _provider_default_base_url(caps.name)
        if caps.name == "ollama" and base_url and not base_url.rstrip("/").endswith("/v1"):
            base_url = base_url.rstrip("/") + "/v1"
    return {"provider": provider, "model": model, "base_url": normalize_endpoint(base_url)}
