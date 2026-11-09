"""Adaptive Rate Limiter with host-bucket token bucket and AIMD concurrency control."""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator

logger = logging.getLogger(__name__)


@dataclass
class HostState:
    """Dynamic rate limit and concurrency state for a specific host."""

    concurrency_limit: int = 2
    max_concurrency: int = 6
    min_concurrency: int = 1
    active_requests: int = 0
    consecutive_successes: int = 0
    last_request_at: float = 0.0
    min_interval: float = 0.3
    backoff_until: float = 0.0


class AdaptiveRateLimiter:
    """Host-bucket rate limiter implementing Additive Increase / Multiplicative Decrease (AIMD)."""

    def __init__(
        self,
        global_max_concurrency: int = 16,
        default_host_concurrency: int = 2,
        max_host_concurrency: int = 6,
        min_host_interval: float = 0.25,
        aimd_success_threshold: int = 10,
    ) -> None:
        self.global_semaphore = asyncio.Semaphore(global_max_concurrency)
        self.default_host_concurrency = default_host_concurrency
        self.max_host_concurrency = max_host_concurrency
        self.min_host_interval = min_host_interval
        self.aimd_success_threshold = aimd_success_threshold
        self._host_states: dict[str, HostState] = {}
        self._lock = asyncio.Lock()

    def _normalize_host(self, host: str) -> str:
        h = host.strip().lower()
        if ":" in h:
            h = h.split(":")[0]
        if h.startswith("www."):
            h = h[4:]
        return h or "default"

    async def _get_or_create_host_state(self, host: str) -> HostState:
        norm = self._normalize_host(host)
        async with self._lock:
            state = self._host_states.get(norm)
            if state is None:
                state = HostState(
                    concurrency_limit=self.default_host_concurrency,
                    max_concurrency=self.max_host_concurrency,
                    min_interval=self.min_host_interval,
                )
                self._host_states[norm] = state
            return state

    @asynccontextmanager
    async def acquire(self, host: str) -> AsyncIterator[None]:
        """Asynchronously acquire a slot respecting global and host-level limits."""
        norm_host = self._normalize_host(host)

        # 1. Acquire global concurrency slot
        await self.global_semaphore.acquire()

        try:
            # 2. Wait for host-level slot and enforce minimum spacing
            while True:
                state = await self._get_or_create_host_state(norm_host)
                now = time.monotonic()

                # Check if host is in backoff period
                if state.backoff_until > now:
                    wait_time = state.backoff_until - now
                    await asyncio.sleep(min(wait_time, 2.0))
                    continue

                # Check if host concurrency limit is saturated
                if state.active_requests >= state.concurrency_limit:
                    await asyncio.sleep(0.05)
                    continue

                # Enforce minimum interval spacing
                elapsed = now - state.last_request_at
                if elapsed < state.min_interval:
                    await asyncio.sleep(state.min_interval - elapsed)

                # Acquire host slot
                async with self._lock:
                    state.active_requests += 1
                    state.last_request_at = time.monotonic()
                break

            try:
                yield
            finally:
                # Release host slot
                async with self._lock:
                    state = self._host_states.get(norm_host)
                    if state:
                        state.active_requests = max(0, state.active_requests - 1)
        finally:
            self.global_semaphore.release()

    def report_result(
        self,
        host: str,
        status_code: int | None = None,
        is_timeout: bool = False,
    ) -> None:
        """Update AIMD rate-limiting metrics based on response outcome.

        - Multiplicative Decrease: on HTTP 429, 503, or timeout.
        - Additive Increase: on consecutive successful responses (2xx/3xx).
        """
        norm_host = self._normalize_host(host)
        state = self._host_states.get(norm_host)
        if not state:
            return

        now = time.monotonic()

        # Check for throttling or backoff signals
        is_throttled = is_timeout or (status_code in {429, 503})

        if is_throttled:
            # Multiplicative Decrease: halve concurrency
            old_limit = state.concurrency_limit
            state.concurrency_limit = max(state.min_concurrency, state.concurrency_limit // 2)
            state.consecutive_successes = 0
            # Apply dynamic backoff (1.5s to 3.0s)
            state.backoff_until = now + (3.0 if status_code == 429 else 1.5)
            logger.warning(
                "Throttled by host '%s' (status=%s, timeout=%s). Reduced concurrency %d -> %d",
                norm_host, status_code, is_timeout, old_limit, state.concurrency_limit
            )
        elif status_code and 200 <= status_code < 400:
            # Additive Increase: increment concurrency after threshold
            state.consecutive_successes += 1
            if state.consecutive_successes >= self.aimd_success_threshold:
                if state.concurrency_limit < state.max_concurrency:
                    state.concurrency_limit += 1
                    logger.debug(
                        "Additive increase for host '%s': concurrency increased to %d",
                        norm_host, state.concurrency_limit
                    )
                state.consecutive_successes = 0
