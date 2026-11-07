"""Size context compaction from the model's real window and real token usage.

Compaction used to trigger at a fixed 40K *estimated* tokens (``chars / 4`` of
the messages, tool schemas excluded), with layer 1 clearing every tool result
but the last three once the estimate passed 20K. The system prompt alone
estimates at ~12.5K, so a cross-sectional question (a dozen companies' filings)
lost its evidence from the third iteration on, re-fetched it, got byte-identical
results and ended in ``no_progress``. gpt-6-sol has a 272K window and
deepseek-v4-pro 1M; the old budget used a few percent of either.

The budget here is the model's window (env override > limit learned from a
context-length error > ``context_windows.json`` > default), capped for cost,
minus the prompt's static part (system prompt + tool schemas). Layers 1-3 fire
at fixed fractions of what remains for the conversation.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Optional

from src.providers.model_metadata import cached_model_metadata, endpoint_scope, normalize_endpoint, token_limit

logger = logging.getLogger(__name__)

_CATALOG_PATH = Path(__file__).resolve().parents[1] / "providers" / "context_windows.json"

#: Share of the window a prompt may use; the rest is left for the reply,
#: reasoning tokens and the error of estimating growth between calls.
USABLE_FRACTION = 0.8
#: Layer 1 (clear old tool results, oldest first, only back down to this line)
#: and layer 2 (fold long text) start at these shares of the conversation
#: budget; layer 3 (summary) at all of it. Calibrated so the largest healthy
#: run measured on 2026-09-29 (154K real input, ~48K of it static) loses
#: nothing: with the 200K cost cap, layer 1 starts at ~170K.
MICRO_FRACTION = 0.8
COLLAPSE_FRACTION = 0.9
#: Floor for the conversation budget when the static prompt nearly fills the
#: window, so a tiny window still compacts instead of computing a negative.
MIN_CONVERSATION_TOKENS = 8_000

_LIMIT_RE = re.compile(
    r"(?:maximum context length|context length|context window|token limit|maximum of)"
    r"\D{0,40}?(\d[\d,]{3,})",
    re.IGNORECASE,
)
_warned_token_threshold = False


@lru_cache(maxsize=1)
def _catalog() -> dict[str, Any]:
    return json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))


def estimate_tokens(value: Any) -> int:
    """Rough token count (~4 chars/token) of any JSON-serialisable value."""
    return len(json.dumps(value, default=str, ensure_ascii=False)) // 4


def resolve_window(
    provider: str,
    model: str,
    *,
    env_window: Optional[int] = None,
    learned_window: Optional[int] = None,
    base_url: str = "",
    provider_metadata: dict | None = None,
) -> tuple[int, str]:
    """Return the model's context window and where the number came from.

    Args:
        provider: Canonical provider name (``openai-codex``, ``deepseek`` ...).
        model: Model name as configured.
        env_window: ``VIBE_TRADING_CONTEXT_WINDOW``, when set.
        learned_window: Limit read from a context-length error in this run.

    Returns:
        ``(window_tokens, source)``.
    """
    resolution = resolve_context(provider, model, env_window=env_window, learned_window=learned_window,
                                 base_url=base_url, provider_metadata=provider_metadata)
    return resolution.window, resolution.source


@dataclass(frozen=True)
class ModelContextResolution:
    """A context budget declaration, including the limits of its evidence.

    ``fallback`` is a safety budget and must never be displayed as a detected
    model specification. Provider metadata is a provider claim, not proof that
    every deployment or account can use the model's nominal maximum.
    """

    window: int
    source: str
    confidence: str
    model_id: str
    provider: str
    endpoint_scope: str = ""
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    reported_fields: dict = field(default_factory=dict)
    reference: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def resolve_context(provider: str, model: str, *, base_url: str = "",
                    provider_metadata: dict | None = None, env_window: int | None = None,
                    learned_window: int | None = None) -> ModelContextResolution:
    """Resolve override > learned limit > exact provider metadata > catalog.

    Lookup never performs network or reads user credentials. Routed IDs and
    dated suffixes are exact IDs in metadata; catalog aliases must be explicit.
    Endpoint changes cannot reuse a different gateway's reported model limits.
    """
    _warn_deprecated_token_threshold()
    provider = (provider or "").strip().lower().replace("_", "-")
    model = (model or "").strip()
    metadata = provider_metadata if isinstance(provider_metadata, dict) else cached_model_metadata(provider, base_url, model)
    scope = endpoint_scope(base_url)
    if (not isinstance(metadata, dict) or metadata.get("model_id") != model or
            metadata.get("provider") != provider or not scope or metadata.get("endpoint_scope") != scope):
        metadata = {}
    metadata_window = token_limit(metadata.get("context_window"), minimum=1000)
    values = {"model_id": model, "provider": provider, "endpoint_scope": endpoint_scope(base_url),
              "max_input_tokens": token_limit(metadata.get("max_input_tokens")),
              "max_output_tokens": token_limit(metadata.get("max_output_tokens")),
              "reported_fields": metadata.get("reported_fields", {}) if isinstance(metadata.get("reported_fields"), dict) else {}}
    override = token_limit(env_window, minimum=1000)
    learned = token_limit(learned_window, minimum=1000)
    if override is not None:
        return ModelContextResolution(override, "env:VIBE_TRADING_CONTEXT_WINDOW", "operator_override", **values)
    if learned is not None:
        return ModelContextResolution(learned, "learned:context_length_error", "provider_error", **values)
    if metadata_window is not None:
        return ModelContextResolution(metadata_window, "provider:/models", "provider_reported", **values)
    catalog = _catalog()
    endpoint = normalize_endpoint(base_url)
    for entry in catalog["models"]:
        providers = entry.get("providers", [entry["provider"]] if entry.get("provider") else [])
        # A model-vendor number must not silently apply to an arbitrary custom
        # proxy. Every catalog record now declares its provider scope.
        if not providers or provider not in providers:
            continue
        if base_url and (not endpoint or endpoint not in entry.get("base_urls", [])):
            continue
        if re.search(entry["pattern"], model, re.IGNORECASE):
            return ModelContextResolution(int(entry["window"]), f"catalog:{entry['pattern']}", "catalog", reference=entry["source"], **values)
    return ModelContextResolution(int(catalog["default_window"]), "default", "fallback", **values)


def resolve_configured_context(config=None) -> ModelContextResolution:
    """Read current settings/cache before a run, without network or a model."""
    from src.config.accessor import get_env_config
    from src.providers.model_metadata import configured_model_identity

    config = config if config is not None else get_env_config()
    identity = configured_model_identity(config)
    return resolve_context(identity["provider"], identity["model"], base_url=identity["base_url"],
                           env_window=config.agent_tuning.vibe_trading_context_window)


def _warn_deprecated_token_threshold() -> None:
    global _warned_token_threshold
    if _warned_token_threshold or "TOKEN_THRESHOLD" not in os.environ:
        return
    _warned_token_threshold = True
    logger.warning(
        "TOKEN_THRESHOLD is deprecated and ignored: it measured chars/4 of the "
        "messages without tool schemas. Compaction now follows the model's real "
        "context window; set VIBE_TRADING_CONTEXT_WINDOW to override it."
    )


def is_context_overflow(error_text: str) -> bool:
    """Whether a provider error says the prompt exceeded the context window."""
    lowered = (error_text or "").lower()
    return any(pattern in lowered for pattern in _catalog()["overflow_error_patterns"])


def parse_context_limit(error_text: str) -> Optional[int]:
    """Read the context limit a provider states in its overflow error, if any."""
    match = _LIMIT_RE.search(error_text or "")
    if not match:
        return None
    value = int(match.group(1).replace(",", ""))
    return value if value >= 1_000 else None


@dataclass(frozen=True)
class CompactionBudget:
    """Real-token thresholds for the three compaction layers.

    Attributes:
        window: Model context window in tokens.
        source: Where ``window`` came from.
        max_tokens: Cost ceiling on the prompt size, whatever the window.
        static_tokens: Tokens of the part compaction cannot shrink (system
            prompt + tool schemas).
    """

    window: int
    source: str
    max_tokens: int
    static_tokens: int
    output_reserve: int = 0
    prompt_limit: int | None = None

    @property
    def hard_limit(self) -> int:
        """Physical prompt bound after explicit output and provider input caps."""
        physical = max(0, self.window - max(0, self.output_reserve))
        return min(physical, max(0, self.prompt_limit)) if self.prompt_limit is not None else physical

    @property
    def total(self) -> int:
        """Largest prompt, in real tokens, the loop lets a run grow to."""
        return max(0, min(int(self.window * USABLE_FRACTION), self.max_tokens, self.hard_limit))

    @property
    def conversation(self) -> int:
        """Tokens left for the conversation after the static prompt."""
        return max(0, self.total - self.static_tokens)

    @property
    def static_over_budget(self) -> bool:
        """Whether compaction of history alone cannot make the request fit."""
        return self.static_tokens >= self.total

    @property
    def micro_at(self) -> int:
        return min(self.total, self.static_tokens + int(self.conversation * MICRO_FRACTION))

    @property
    def collapse_at(self) -> int:
        return min(self.total, self.static_tokens + int(self.conversation * COLLAPSE_FRACTION))

    @property
    def compact_at(self) -> int:
        return self.total


class ContextMeter:
    """Current prompt size in real tokens.

    The provider reports what the last request cost; messages appended or
    compacted since then are counted by estimate. Before any usage arrives the
    whole prompt is estimated, tool schemas included.
    """

    def __init__(self, estimator: Callable[[Any], int] = estimate_tokens) -> None:
        self._estimate = estimator
        self._anchor: Optional[tuple[int, int]] = None
        self.static_tokens: Optional[int] = None
        self._anchor_schema_tokens: Optional[int] = None
        self._static_schema_tokens: Optional[int] = None

    def observe(self, input_tokens: Optional[int], messages: list, *, tool_schema_tokens: Optional[int] = None) -> None:
        """Anchor on the real input size of the request just answered.

        Args:
            input_tokens: Provider-reported prompt tokens of that request.
            messages: Exactly the messages that request sent.
            tool_schema_tokens: Estimate of the schemas sent with that request.
        """
        if not isinstance(input_tokens, int) or isinstance(input_tokens, bool) or input_tokens <= 0:
            return
        self._anchor = (input_tokens, self._estimate(messages))
        self._anchor_schema_tokens = tool_schema_tokens
        if self.static_tokens is None:
            # The first request is the static prompt plus the opening turn(s).
            self.static_tokens = max(0, input_tokens - self._estimate(messages[1:]))
            self._static_schema_tokens = tool_schema_tokens

    def tokens(self, messages: list, tool_schema_tokens: int) -> int:
        """Real-token size the next request would have."""
        if self._anchor is None:
            return self._estimate(messages) + tool_schema_tokens
        anchor_input, anchor_estimate = self._anchor
        schema_delta = 0 if self._anchor_schema_tokens is None else tool_schema_tokens - self._anchor_schema_tokens
        return max(0, anchor_input + self._estimate(messages) - anchor_estimate + schema_delta)

    def static(self, messages: list, tool_schema_tokens: int) -> int:
        """Static prompt size: measured once usage arrives, else estimated."""
        if self.static_tokens is not None:
            schema_delta = 0 if self._static_schema_tokens is None else tool_schema_tokens - self._static_schema_tokens
            return max(0, self.static_tokens + schema_delta)
        return self._estimate(messages[:1]) + tool_schema_tokens
