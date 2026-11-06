"""Admission for Swarm-owned stream_chat invocations, independent of pricing."""

from __future__ import annotations

import threading

from src.agent.llm_usage import _normalize_llm_usage


class SwarmBudgetExceeded(RuntimeError):
    """Another logical model call cannot be admitted for this run."""


class SwarmCallBudget:
    """Reserve before dispatch; an interrupted reservation keeps unknown usage.

    shortcut: SDK retries and stream_chat's invoke fallback are inside one
    reservation, upgrade at the provider boundary for an HTTP-attempt cap.
    """

    def __init__(self, run, store, emit):
        self.run = run
        self.store = store
        self.emit = emit
        self.lock = threading.Lock()
        if run.llm_calls_started is None:
            run.llm_calls_started = 0
            run.llm_calls_unknown_usage = 0

    def reserve(self, agent_id: str, task_id: str, iteration: int) -> int:
        with self.lock:
            run = self.run
            if run.status not in ("pending", "running"):
                raise SwarmBudgetExceeded("run_not_active: no model call was dispatched")
            if run.max_llm_calls is not None and run.llm_calls_started >= run.max_llm_calls:
                run.budget_stop_reason = "max_llm_calls_reached"
                self.store.update_run(run)
                raise SwarmBudgetExceeded("max_llm_calls_reached: no model call was dispatched")
            run.llm_calls_started += 1
            run.llm_calls_unknown_usage += 1
            call_index = run.llm_calls_started
            # Persist before dispatch: a process crash never turns the call into zero usage.
            self.store.update_run(run)
            self.emit("llm_call_reserved", agent_id, task_id, {
                "call_index": call_index, "iteration": iteration,
            })
            return call_index

    def record(self, call_index: int, usage, status: str, agent_id: str, task_id: str) -> None:
        normalized = _normalize_llm_usage(usage)
        with self.lock:
            if normalized is not None:
                self.run.llm_calls_unknown_usage -= 1
            self.store.update_run(self.run)
            self.emit("llm_call_usage", agent_id, task_id, {
                "call_index": call_index, "status": status,
                "usage": normalized, "usage_source": "provider" if normalized else "unknown",
            })
