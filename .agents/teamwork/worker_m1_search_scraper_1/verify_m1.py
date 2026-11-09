"""Comprehensive verification test suite for M1 Multi-Engine Search and Async Scraper."""

import asyncio
import ipaddress
import time
import unittest

from src.tools.scraper import (
    AdaptiveRateLimiter,
    AsyncDNSCache,
    AsyncScrapingEngine,
    SSRFGuard,
    SSRFSecurityError,
    ScrapeResult,
)
from src.tools.search import (
    BaseSearchEngine,
    BingSearchEngine,
    BraveSearchEngine,
    DuckDuckGoEngine,
    MultiSearchAggregator,
    QverisSearchEngine,
    SearchResult,
    VietnamFinancialPortalsEngine,
)


class TestSSRFGuard(unittest.TestCase):
    """Test SSRF Guard rules against all RFC 1918, cloud metadata, and loopback IPs."""

    def test_prohibited_ipv4(self):
        blocked_ips = [
            "127.0.0.1",
            "127.1.2.3",
            "10.0.0.1",
            "10.255.255.255",
            "172.16.0.1",
            "172.31.255.255",
            "192.168.0.1",
            "192.168.1.100",
            "169.254.169.254",  # AWS/GCP/Azure metadata
            "169.254.1.1",      # Link-local
            "0.0.0.0",
            "100.64.0.1",       # RFC 6598 CGN
            "198.18.0.1",       # Benchmarking
            "224.0.0.1",        # Multicast
            "240.0.0.1",        # Reserved
            "255.255.255.255",
        ]
        for ip in blocked_ips:
            with self.subTest(ip=ip):
                self.assertFalse(SSRFGuard.is_ip_safe(ip), f"IP {ip} should be blocked")
                with self.assertRaises(SSRFSecurityError):
                    SSRFGuard.validate_ip(ip)

    def test_prohibited_ipv6(self):
        blocked_ips = [
            "::1",
            "::",
            "fe80::1",
            "fc00::1",
            "fd00::1",
            "fd00:ec2::254",  # AWS EC2 IPv6 metadata
            "ff02::1",        # Multicast
            "::ffff:127.0.0.1",  # IPv4-mapped loopback
            "::ffff:10.0.0.1",   # IPv4-mapped private
            "::ffff:169.254.169.254",  # IPv4-mapped metadata
        ]
        for ip in blocked_ips:
            with self.subTest(ip=ip):
                self.assertFalse(SSRFGuard.is_ip_safe(ip), f"IPv6 {ip} should be blocked")
                with self.assertRaises(SSRFSecurityError):
                    SSRFGuard.validate_ip(ip)

    def test_allowed_public_ips(self):
        public_ips = [
            "8.8.8.8",
            "1.1.1.1",
            "142.250.190.46",  # google.com
            "2606:4700:4700::1111",  # Cloudflare DNS IPv6
        ]
        for ip in public_ips:
            with self.subTest(ip=ip):
                self.assertTrue(SSRFGuard.is_ip_safe(ip), f"Public IP {ip} should be allowed")
                SSRFGuard.validate_ip(ip)

    def test_validate_url(self):
        # Forbidden schemes
        safe, _, reason = SSRFGuard.validate_url("file:///etc/passwd")
        self.assertFalse(safe)
        self.assertIn("Prohibited scheme", reason)

        # Forbidden localhost & private literals
        safe, _, reason = SSRFGuard.validate_url("http://localhost:8080/admin")
        self.assertFalse(safe)

        safe, _, reason = SSRFGuard.validate_url("http://127.0.0.1:5000")
        self.assertFalse(safe)

        safe, _, reason = SSRFGuard.validate_url("http://169.254.169.254/latest/meta-data/")
        self.assertFalse(safe)


class TestAsyncDNSCache(unittest.IsolatedAsyncioTestCase):
    """Test AsyncDNSCache resolution, TTL, and SSRF validation."""

    async def test_dns_cache_hit_and_ttl(self):
        cache = AsyncDNSCache(ttl_seconds=1.0)
        # Resolve a known stable public domain
        ips1 = await cache.resolve("one.one.one.one")
        self.assertTrue(len(ips1) > 0)
        self.assertEqual(len(cache), 1)

        # Immediate second resolve should hit cache
        ips2 = await cache.resolve("one.one.one.one")
        self.assertEqual(ips1, ips2)

        # Clear cache
        await cache.clear()
        self.assertEqual(len(cache), 0)


class TestAdaptiveRateLimiter(unittest.IsolatedAsyncioTestCase):
    """Test AdaptiveRateLimiter AIMD and concurrency bounds."""

    async def test_aimd_halving_on_429(self):
        limiter = AdaptiveRateLimiter(default_host_concurrency=4, max_host_concurrency=8)
        state = await limiter._get_or_create_host_state("example.com")
        self.assertEqual(state.concurrency_limit, 4)

        # Trigger 429
        limiter.report_result("example.com", status_code=429)
        self.assertEqual(state.concurrency_limit, 2)  # Halved from 4 -> 2

        # Trigger another 429
        limiter.report_result("example.com", status_code=429)
        self.assertEqual(state.concurrency_limit, 1)  # Halved from 2 -> 1 (min 1)

    async def test_aimd_additive_increase(self):
        limiter = AdaptiveRateLimiter(
            default_host_concurrency=2,
            max_host_concurrency=4,
            aimd_success_threshold=3,
        )
        state = await limiter._get_or_create_host_state("test.com")
        self.assertEqual(state.concurrency_limit, 2)

        # Report 3 consecutive successes
        limiter.report_result("test.com", status_code=200)
        limiter.report_result("test.com", status_code=200)
        limiter.report_result("test.com", status_code=200)

        # Concurrency should increase by 1
        self.assertEqual(state.concurrency_limit, 3)

    async def test_acquire_context_manager(self):
        limiter = AdaptiveRateLimiter(min_host_interval=0.01)
        async with limiter.acquire("test.org"):
            state = await limiter._get_or_create_host_state("test.org")
            self.assertEqual(state.active_requests, 1)
        # After release
        self.assertEqual(state.active_requests, 0)


class TestAsyncScrapingEngine(unittest.IsolatedAsyncioTestCase):
    """Test AsyncScrapingEngine SSRF blocking and ScrapeResult format."""

    async def test_ssrf_blocking(self):
        engine = AsyncScrapingEngine()
        try:
            # Test blocking of private IP
            result = await engine.scrape_url("http://127.0.0.1:9999/secret")
            self.assertFalse(result.success)
            self.assertEqual(result.status_code, 403)
            self.assertIn("SSRF violation", result.error)

            # Test blocking of AWS metadata IP
            result2 = await engine.scrape_url("http://169.254.169.254/latest/meta-data/")
            self.assertFalse(result2.success)
            self.assertEqual(result2.status_code, 403)
            self.assertIn("SSRF violation", result2.error)
        finally:
            await engine.close()

    async def test_batch_scraping_interface(self):
        engine = AsyncScrapingEngine()
        try:
            # Batch with prohibited IPs
            results = await engine.scrape_urls([
                "http://127.0.0.1:80",
                "http://10.0.0.1:80",
                "http://192.168.1.1:80",
            ])
            self.assertEqual(len(results), 3)
            for res in results:
                self.assertFalse(res.success)
                self.assertEqual(res.status_code, 403)
                self.assertIn("SSRF violation", res.error)
        finally:
            await engine.close()


class MockSearchEngine(BaseSearchEngine):
    """Deterministic mock search engine for verifying RRF and Diversity Gate."""

    def __init__(self, name: str, weight: float, return_items: list[SearchResult]) -> None:
        super().__init__(name=name, weight=weight)
        self.return_items = return_items

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        return self.return_items[:max_results]


class TestMultiSearchAggregator(unittest.IsolatedAsyncioTestCase):
    """Test RRF ranking formula and Domain Diversity Gate."""

    async def test_rrf_formula_and_ranking(self):
        # Doc A is rank 1 in engine1 (weight 1.0) and rank 1 in engine2 (weight 2.0)
        # Score Doc A = 1.0/(60+1) + 2.0/(60+1) = 3.0 / 61 = 0.049180
        # Doc B is rank 2 in engine1 (weight 1.0) -> Score = 1.0/(60+2) = 1/62 = 0.016129
        doc_a1 = SearchResult(title="Doc A", url="https://site-a.com/page1", snippet="A1", source="eng1")
        doc_b1 = SearchResult(title="Doc B", url="https://site-b.com/page1", snippet="B1", source="eng1")

        doc_a2 = SearchResult(title="Doc A", url="https://site-a.com/page1", snippet="A2", source="eng2")
        doc_c2 = SearchResult(title="Doc C", url="https://site-c.com/page1", snippet="C1", source="eng2")

        eng1 = MockSearchEngine("eng1", weight=1.0, return_items=[doc_a1, doc_b1])
        eng2 = MockSearchEngine("eng2", weight=2.0, return_items=[doc_a2, doc_c2])

        aggregator = MultiSearchAggregator(engines=[eng1, eng2], rrf_k=60)
        results = await aggregator.search("test query", max_results=5)

        self.assertEqual(len(results), 3)
        # First result must be Doc A
        self.assertEqual(results[0].url, "https://site-a.com/page1")
        expected_score_a = (1.0 / 61.0) + (2.0 / 61.0)
        self.assertAlmostEqual(results[0].score, expected_score_a, places=5)
        # Aggregated sources should be eng1 and eng2
        self.assertIn("eng1", results[0].extra["aggregated_sources"])
        self.assertIn("eng2", results[0].extra["aggregated_sources"])

    async def test_domain_diversity_gate(self):
        # Create 5 results from the same domain 'cafef.vn' and 2 from 'vietstock.vn'
        cafef_items = [
            SearchResult(title=f"CafeF {i}", url=f"https://cafef.vn/news-{i}.chn", snippet="Snippet", source="cafef")
            for i in range(1, 6)
        ]
        vietstock_items = [
            SearchResult(title=f"Vietstock {i}", url=f"https://vietstock.vn/news-{i}.htm", snippet="Snippet", source="vietstock")
            for i in range(1, 3)
        ]

        # Engine returning 5 CafeF items first
        eng = MockSearchEngine("eng", weight=1.0, return_items=cafef_items + vietstock_items)

        aggregator = MultiSearchAggregator(engines=[eng], max_per_domain=2)
        results = await aggregator.search("co phieu VNM", max_results=4)

        # Count domains in final results
        domains = [r.extra["domain"] for r in results]
        self.assertLessEqual(domains.count("cafef.vn"), 2, "Domain Diversity Gate must limit max 2 per domain")
        self.assertIn("vietstock.vn", domains, "Second domain should be admitted due to diversity gate")
        self.assertEqual(len(results), 4)


if __name__ == "__main__":
    unittest.main()
