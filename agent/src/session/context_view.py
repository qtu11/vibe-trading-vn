"""Read-only context diagnostics. Does not call a model or write a memory."""

import json
from datetime import datetime, timezone
from pathlib import Path

from src.config.paths import get_runtime_root
from src.memory.persistent import PersistentMemory
from src.session.compaction_memory import prepare_session_history
from src.tools.redaction import redact_tool_result


def _artifact(run_dir, name):
    if not run_dir:
        return None
    try:
        root = (get_runtime_root() / "runs").resolve()
        path = (Path(run_dir) / name).resolve()
        if not path.is_relative_to(root) or not path.is_file() or path.stat().st_size > 1_000_000:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def context_view(service, session, *, memory=None):
    messages = service.store.get_messages(session.session_id, limit=1000)
    query = next((m.content for m in reversed(messages) if m.role == "user"), "")
    attempt = service.store.get_attempt(session.session_id, session.last_attempt_id) if session.last_attempt_id else None
    active = getattr(service, "_active_loops", {}).get(session.session_id)
    active_run_dir = getattr(getattr(active, "memory", None), "run_dir", None)
    run_dir = active_run_dir or (attempt.run_dir if attempt is not None else None)
    preview, _ = prepare_session_history(messages, query, exclude_current=False,
        session_id=session.session_id, runs_root=get_runtime_root() / "runs", previous_run_dir=run_dir)
    pm = memory if memory is not None else PersistentMemory()
    entries, recalls, memory_error = [], [], None
    try:
        entries = pm.list_entries()
        recalls = pm.find_relevant(query, max_results=3) if query else []
    except Exception:
        memory_error = "MEMORY_READ_UNAVAILABLE"
    saved = _artifact(run_dir, "request_context.json")
    current = getattr(active, "_latest_context_snapshot", None) if active is not None else None
    if not isinstance(current, dict) or current.get("version") != 1:
        current = saved if active is not None else None
    model_context = _model_context()
    if current is None and active is None:
        current = _session_preview(saved, preview, model_context)
    usage = _artifact(run_dir, "llm_usage.json")
    prior_plan = next((m.metadata.get("forex_trade_plan") for m in reversed(messages)
                       if m.linked_attempt_id == session.last_attempt_id and m.metadata.get("forex_trade_plan")), None)
    return {
        "version": 1, "session_id": session.session_id, "model_calls": 0,
        "stored_messages": len(messages), "scanned_message_limit": 1000, "preview": preview["stats"],
        "stored_messages_is_lower_bound": len(messages) == 1000,
        "model_context": model_context,
        "current_context": current,
        "preview_query_source": "latest_user_message",
        "last_run": saved if saved and saved.get("version") == 1 else None,
        "last_run_usage": usage,
        "last_run_council_usage_tracked": isinstance(prior_plan.get("llm_usage"), dict) if isinstance(prior_plan, dict) else None,
        "memory": {
            "available_entries": len(entries) if memory_error is None else None,
            "error": memory_error,
            "entries": [{"id": e.id, "title": e.title, "type": e.memory_type} for e in entries[:20]],
            "recall_preview": [{"id": e.id, "title": e.title, "type": e.memory_type,
                                "excerpt": redact_tool_result(e.body[:500])} for e in recalls],
            "automatic_fact_extraction": False,
        },
    }


def _model_context():
    """Resolve the selected model without constructing it or probing a provider."""
    try:
        from src.agent.context_budget import resolve_configured_context
        from src.config.accessor import get_env_config
        resolution = resolve_configured_context()
        data = resolution.as_dict()
        data.pop("endpoint_scope", None)
        data["model"] = data["model_id"]
        data["prompt_cost_cap"] = get_env_config().agent_tuning.vibe_trading_context_max_tokens
        return data
    except Exception:
        # Opening a diagnostics popover must work even before LLM setup.
        return None


def _session_preview(saved, preview, model_context):
    """Estimate a next-turn baseline from stored history and a matching model.

    The next draft, selected skills and newly recalled memories are unknown.
    This is deliberately labelled a preview, never provider-reported usage.
    """
    if not isinstance(saved, dict) or not isinstance(model_context, dict):
        return None
    prompt = saved.get("current_prompt")
    if (not isinstance(prompt, dict) or not prompt.get("model")
            or prompt["model"] != model_context.get("model")
            or prompt.get("provider") != model_context.get("provider")):
        return None
    static = prompt.get("static_prompt_tokens")
    if type(static) is not int or static < 0:
        components = saved.get("initial_components", {})
        chars = components.get("system_chars") if isinstance(components, dict) else None
        tools = prompt.get("tool_schema_estimated_tokens")
        if type(chars) is not int or chars < 0 or type(tools) is not int or tools < 0:
            return None
        static = chars // 4 + tools
    from src.agent.context_budget import estimate_tokens, CompactionBudget
    window, cap = model_context.get("window"), model_context.get("prompt_cost_cap")
    if type(window) is not int or window <= 0 or type(cap) is not int or cap <= 0:
        return None
    budget = CompactionBudget(window, model_context["source"], cap, static)
    return {
        "version": 1, "source": "session_preview", "run_id": saved.get("run_id", ""),
        "initial_selection": preview["stats"],
        "current_prompt": {
            "estimated_next_request_tokens": static + estimate_tokens(preview["history"]),
            "last_reported_input_tokens": None, "model": model_context["model"],
            "provider": model_context["provider"], "model_window": window,
            "window_source": model_context["source"], "window_confidence": model_context["confidence"],
            "prompt_cost_cap": cap, "compact_at": budget.compact_at,
            "phase": "session_preview", "observed_at": datetime.now(timezone.utc).isoformat(),
            "estimator": "saved_static_plus_selected_history",
            "includes_next_draft": False,
        },
    }
