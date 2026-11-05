"""Read-only context diagnostics. Does not call a model or write a memory."""

import json
from pathlib import Path

from src.config.paths import get_runtime_root
from src.memory.persistent import PersistentMemory
from src.session.context import pack_history
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
    preview = pack_history(messages, query, exclude_current=False)
    pm = memory if memory is not None else PersistentMemory()
    entries, recalls, memory_error = [], [], None
    try:
        entries = pm.list_entries()
        recalls = pm.find_relevant(query, max_results=3) if query else []
    except Exception:
        memory_error = "MEMORY_READ_UNAVAILABLE"
    attempt = service.store.get_attempt(session.session_id, session.last_attempt_id) if session.last_attempt_id else None
    run_dir = attempt.run_dir if attempt is not None else None
    saved = _artifact(run_dir, "request_context.json")
    usage = _artifact(run_dir, "llm_usage.json")
    prior_plan = next((m.metadata.get("forex_trade_plan") for m in reversed(messages)
                       if m.linked_attempt_id == session.last_attempt_id and m.metadata.get("forex_trade_plan")), None)
    return {
        "version": 1, "session_id": session.session_id, "model_calls": 0,
        "stored_messages": len(messages), "scanned_message_limit": 1000, "preview": preview["stats"],
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
