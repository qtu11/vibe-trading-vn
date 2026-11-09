"""SSRF Guard with strict DNS resolution, RFC 1918/link-local/metadata blocking, and IP pinning."""

from __future__ import annotations

import ipaddress
import logging
import socket
import urllib.parse
from typing import Any, Iterable

import anyio
import httpcore
from httpcore._backends.anyio import AnyIOBackend
import httpx

logger = logging.getLogger(__name__)


def _http2_available() -> bool:
    """Return True when the optional HTTP/2 stack is installed.

    httpx needs the "h2" package for HTTP/2. Without it, httpcore raises
    ImportError at connection time, so every request fails. HTTP/1.1 works
    fine on its own, so the scraper falls back to it.
    """
    try:
        import h2  # noqa: F401
    except ImportError:
        return False
    return True


class SSRFSecurityError(ValueError):
    """Raised when an outbound request targets a prohibited IP or local resource."""
    pass


# Prohibited IPv4 networks (RFC 1918, RFC 6598, loopback, link-local, cloud metadata, multicast, etc.)
PROHIBITED_IPV4_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),          # Current network
    ipaddress.ip_network("10.0.0.0/8"),         # Private-Use (RFC 1918)
    ipaddress.ip_network("100.64.0.0/10"),      # Shared Address Space (RFC 6598)
    ipaddress.ip_network("127.0.0.0/8"),        # Loopback
    ipaddress.ip_network("169.254.0.0/16"),     # Link-Local & Cloud Metadata (169.254.169.254)
    ipaddress.ip_network("172.16.0.0/12"),      # Private-Use (RFC 1918)
    ipaddress.ip_network("192.0.0.0/24"),       # IETF Protocol Assignments
    ipaddress.ip_network("192.0.2.0/24"),       # TEST-NET-1
    ipaddress.ip_network("192.88.99.0/24"),     # 6to4 Relay Anycast
    ipaddress.ip_network("192.168.0.0/16"),     # Private-Use (RFC 1918)
    ipaddress.ip_network("198.18.0.0/15"),      # Benchmarking
    ipaddress.ip_network("198.51.100.0/24"),    # TEST-NET-2
    ipaddress.ip_network("203.0.113.0/24"),     # TEST-NET-3
    ipaddress.ip_network("224.0.0.0/4"),        # Multicast
    ipaddress.ip_network("240.0.0.0/4"),        # Reserved
    ipaddress.ip_network("255.255.255.255/32"), # Limited Broadcast
]

# Prohibited IPv6 networks (Loopback, ULA, Link-Local, Multicast, AWS metadata)
PROHIBITED_IPV6_NETWORKS = [
    ipaddress.ip_network("::/128"),             # Unspecified
    ipaddress.ip_network("::1/128"),            # Loopback
    ipaddress.ip_network("100::/64"),           # Discard-Only
    ipaddress.ip_network("2001::/23"),          # IETF Protocol Assignments
    ipaddress.ip_network("2001:db8::/32"),      # Documentation
    ipaddress.ip_network("fc00::/7"),           # Unique Local Address (ULA)
    ipaddress.ip_network("fe80::/10"),          # Link-Local Unicast
    ipaddress.ip_network("ff00::/8"),           # Multicast
    ipaddress.ip_network("fd00:ec2::254/128"),  # AWS IPv6 Metadata
]


class SSRFGuard:
    """Validator and IP resolver ensuring zero requests route to internal infrastructure."""

    @staticmethod
    def normalize_ip(ip_val: str | ipaddress.IPv4Address | ipaddress.IPv6Address) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
        """Parse string or IP object, unwrapping IPv4-mapped IPv6 addresses."""
        if not isinstance(ip_val, (ipaddress.IPv4Address, ipaddress.IPv6Address)):
            ip_obj = ipaddress.ip_address(str(ip_val).strip())
        else:
            ip_obj = ip_val

        # Unwrap IPv4-mapped IPv6 (e.g. ::ffff:127.0.0.1 -> 127.0.0.1)
        if isinstance(ip_obj, ipaddress.IPv6Address) and ip_obj.ipv4_mapped is not None:
            return ip_obj.ipv4_mapped
        return ip_obj

    @classmethod
    def is_ip_safe(cls, ip_val: str | ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
        """Check if an IP address is a safe public global routable address."""
        try:
            ip = cls.normalize_ip(ip_val)

            # Check built-in properties
            if not ip.is_global or ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
                return False

            if isinstance(ip, ipaddress.IPv4Address):
                for network in PROHIBITED_IPV4_NETWORKS:
                    if ip in network:
                        return False
            elif isinstance(ip, ipaddress.IPv6Address):
                for network in PROHIBITED_IPV6_NETWORKS:
                    if ip in network:
                        return False

            return True
        except Exception:
            return False

    @classmethod
    def validate_ip(cls, ip_val: str | ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
        """Raise SSRFSecurityError if IP is not safe."""
        if not cls.is_ip_safe(ip_val):
            raise SSRFSecurityError(f"SSRF blocked: IP address '{ip_val}' is prohibited.")

    @classmethod
    def validate_url(cls, url: str) -> tuple[bool, str | None, str | None]:
        """Validate URL scheme and host against SSRF rules.

        Returns:
            Tuple of (is_safe, resolved_ip, block_reason)
        """
        try:
            parsed = urllib.parse.urlsplit(url)
            scheme = (parsed.scheme or "").lower()
            if scheme not in {"http", "https"}:
                return False, None, f"Prohibited scheme '{scheme}' (only http/https allowed)"

            hostname = parsed.hostname
            if not hostname:
                return False, None, "Missing hostname in URL"

            hostname = hostname.strip().lower()
            if hostname in {"localhost", "127.0.0.1", "::1", "metadata.google.internal"}:
                return False, hostname, f"Prohibited hostname '{hostname}'"

            # Check if hostname is an IP literal
            try:
                ip_obj = ipaddress.ip_address(hostname)
                if not cls.is_ip_safe(ip_obj):
                    return False, str(ip_obj), f"Prohibited IP literal '{ip_obj}'"
                return True, str(ip_obj), None
            except ValueError:
                pass  # Hostname is a domain name, not an IP literal

            # Resolve DNS
            addrinfo = socket.getaddrinfo(hostname, parsed.port or (443 if scheme == "https" else 80), proto=socket.IPPROTO_TCP)
            if not addrinfo:
                return False, None, f"DNS resolution failed for '{hostname}'"

            for entry in addrinfo:
                sockaddr = entry[4]
                ip_str = sockaddr[0]
                if not cls.is_ip_safe(ip_str):
                    return False, ip_str, f"Host '{hostname}' resolved to prohibited IP '{ip_str}'"

            first_ip = addrinfo[0][4][0]
            return True, first_ip, None
        except Exception as exc:
            return False, None, f"URL validation error: {exc}"


class SSRFNetworkBackend(AnyIOBackend):
    """Custom network backend intercepting socket connections to enforce SSRFGuard and IP pinning."""

    def __init__(self, dns_resolver: Any = None) -> None:
        super().__init__()
        self.dns_resolver = dns_resolver

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        """Resolve host, validate against SSRF invariants, and pin connection to verified IP."""
        # Check if host is already an IP literal
        try:
            ip_obj = ipaddress.ip_address(host)
            SSRFGuard.validate_ip(ip_obj)
            pinned_ip = str(ip_obj)
        except ValueError:
            # Domain name: resolve via dns_resolver if provided, else getaddrinfo
            if self.dns_resolver is not None:
                resolved_ips = await self.dns_resolver.resolve(host)
            else:
                addrinfo = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
                resolved_ips = [entry[4][0] for entry in addrinfo]

            if not resolved_ips:
                raise SSRFSecurityError(f"DNS resolution returned no addresses for host '{host}'")

            # Validate all resolved IPs
            for ip_candidate in resolved_ips:
                SSRFGuard.validate_ip(ip_candidate)

            pinned_ip = resolved_ips[0]

        logger.debug("SSRF Guard pinned host '%s' to safe IP '%s'", host, pinned_ip)
        # Connect directly to pinned IP to prevent DNS rebinding
        return await super().connect_tcp(
            host=pinned_ip,
            port=port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )


class SSRFSafeTransport(httpx.AsyncHTTPTransport):
    """HTTPX Async Transport enforcing SSRF Guard and IP pinning on every request and redirect."""

    def __init__(
        self,
        dns_resolver: Any = None,
        verify: Any = True,
        http2: bool = True,
        limits: httpx.Limits | None = None,
        **kwargs: Any,
    ) -> None:
        transport_limits = limits or httpx.Limits(
            max_connections=60,
            max_keepalive_connections=30,
            keepalive_expiry=30.0,
        )
        # HTTP/2 needs the optional "h2" package. Without it, every request
        # fails with ImportError, so fall back to HTTP/1.1 instead.
        if http2 and not _http2_available():
            logger.info("HTTP/2 support is unavailable (missing 'h2'); using HTTP/1.1")
            http2 = False
        super().__init__(
            verify=verify,
            http2=http2,
            limits=transport_limits,
            **kwargs,
        )
        ssl_ctx = getattr(self._pool, "_ssl_context", None)
        backend = SSRFNetworkBackend(dns_resolver=dns_resolver)
        # Re-initialize internal connection pool with SSRF-protected network backend
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=ssl_ctx,
            max_connections=transport_limits.max_connections,
            max_keepalive_connections=transport_limits.max_keepalive_connections,
            keepalive_expiry=transport_limits.keepalive_expiry,
            http1=True,
            http2=http2,
            network_backend=backend,
        )
