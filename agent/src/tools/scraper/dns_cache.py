"""In-memory async DNS cache with TTL and SSRF validation."""

from __future__ import annotations

import asyncio
import logging
import socket
import time
from typing import NamedTuple

from .ssrf_guard import SSRFGuard, SSRFSecurityError

logger = logging.getLogger(__name__)


class DNSCacheEntry(NamedTuple):
    ips: list[str]
    expires_at: float


class AsyncDNSCache:
    """Coroutine-safe in-memory DNS cache with automatic TTL expiration and SSRF pre-screening."""

    def __init__(self, ttl_seconds: float = 300.0, max_entries: int = 1024) -> None:
        self.ttl_seconds = max(1.0, float(ttl_seconds))
        self.max_entries = max_entries
        self._cache: dict[str, DNSCacheEntry] = {}
        self._lock = asyncio.Lock()

    def _prune_expired(self, now: float) -> None:
        """Remove entries that have passed their TTL."""
        expired_keys = [k for k, entry in self._cache.items() if entry.expires_at <= now]
        for k in expired_keys:
            self._cache.pop(k, None)

        # If still over max entries, evict oldest entries
        if len(self._cache) > self.max_entries:
            sorted_keys = sorted(self._cache.keys(), key=lambda k: self._cache[k].expires_at)
            overflow_count = len(self._cache) - self.max_entries
            for k in sorted_keys[:overflow_count]:
                self._cache.pop(k, None)

    async def resolve(self, hostname: str) -> list[str]:
        """Resolve hostname to a list of validated, safe public IPs.

        Args:
            hostname: Target domain name to resolve.

        Returns:
            List of safe IPv4 / IPv6 addresses.

        Raises:
            SSRFSecurityError: If any resolved address violates SSRF invariants.
            socket.gaierror: If hostname resolution fails completely.
        """
        host_key = hostname.strip().lower()
        now = time.monotonic()

        # Check existing cached entry
        async with self._lock:
            cached = self._cache.get(host_key)
            if cached and cached.expires_at > now:
                return list(cached.ips)

        # Perform asynchronous getaddrinfo on event loop thread pool
        loop = asyncio.get_running_loop()
        try:
            addrinfo = await loop.getaddrinfo(
                host_key,
                None,
                proto=socket.IPPROTO_TCP,
            )
        except socket.gaierror as exc:
            logger.debug("DNS lookup failed for '%s': %s", host_key, exc)
            raise

        if not addrinfo:
            raise socket.gaierror(socket.EAI_NONAME, f"No address associated with hostname '{host_key}'")

        # Extract unique IP addresses
        discovered_ips: list[str] = []
        seen: set[str] = set()
        for item in addrinfo:
            sockaddr = item[4]
            ip_str = sockaddr[0]
            if ip_str not in seen:
                seen.add(ip_str)
                # Enforce SSRFGuard rule immediately
                SSRFGuard.validate_ip(ip_str)
                discovered_ips.append(ip_str)

        if not discovered_ips:
            raise SSRFSecurityError(f"No valid public IPs resolved for host '{host_key}'")

        # Store in cache
        async with self._lock:
            self._prune_expired(now)
            self._cache[host_key] = DNSCacheEntry(
                ips=discovered_ips,
                expires_at=now + self.ttl_seconds,
            )

        return discovered_ips

    async def clear(self) -> None:
        """Clear all entries in the DNS cache."""
        async with self._lock:
            self._cache.clear()

    def __len__(self) -> int:
        return len(self._cache)
