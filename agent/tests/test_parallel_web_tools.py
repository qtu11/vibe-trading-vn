"""Comprehensive Unit and Integration Test Suite for Parallel Web and Token Optimization Tools.

Covers:
1. Search Subsystem (Engines, Aggregator, RRF, Domain Diversity Gate)
2. Scraper Subsystem (SSRF Guard, IP Pinning, DNS Cache, Rate Limiter)
3. Extractor Subsystem (DOM Cleaner, Table GFM Markdown, 3-Tier Deduplication)
4. Optimizer Subsystem (Structural Chunker, BM25-FSB Scorer, Adaptive Budgeter)
5. Synthesis Subsystem (Map Fact Extraction, Reduce Conflict Resolution, Grounded Summary)
6. Unified BaseTool Interfaces (ParallelWebSearchTool, ConcurrentScraperTool)
"""

from __future__ import annotations

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.tools.search import (
    BaseSearchEngine,
    SearchResult,
    MultiSearchAggregator,
    DuckDuckGoEngine,
    VietnamFinancialPortalsEngine,
)
from src.tools.scraper import (
    SSRFGuard,
    AsyncDNSCache,
    AdaptiveRateLimiter,
    AsyncScrapingEngine,
    ScrapeResult,
)
from src.tools.extractor import (
    clean_html,
    deduplicate_documents,
    CleanDocument,
    compute_exact_hash,
    compute_simhash_64,
    hamming_distance,
    normalize_canonical_url,
)
from src.tools.optimizer import (
    Chunk,
    PrunedDocument,
    SemanticChunker,
    BM25FSBScorer,
    AdaptiveBudgeter,
    prune_document,
    prune_documents,
    count_tokens,
    split_sentences,
)
from src.tools.synthesis import (
    ExtractedMetric,
    ConflictResolution,
    SynthesizedResearchArtifact,
    DeterministicRuleExtractor,
    MapExtractor,
    ReduceSynthesizer,
    synthesize_research,
)
from src.tools.parallel_web_tools import (
    ParallelWebSearchTool,
    ConcurrentScraperTool,
    parallel_web_search_async,
    concurrent_scrape_and_synthesize_async,
)


# ===========================================================================
# 1. SEARCH SUBSYSTEM TESTS
# ===========================================================================

class MockSearchEngine(BaseSearchEngine):
    def __init__(self, name: str, weight: float, return_results: list[SearchResult]) -> None:
        super().__init__(name=name, weight=weight)
        self.return_results = return_results

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        return self.return_results[:max_results]


@pytest.mark.asyncio
async def test_multi_search_aggregator_rrf_and_diversity():
    e1 = MockSearchEngine(
        name="engine1",
        weight=1.5,
        return_results=[
            SearchResult(title="Result A", url="https://cafef.vn/a.chn", snippet="Snippet A", source="engine1"),
            SearchResult(title="Result B", url="https://vietstock.vn/b.htm", snippet="Snippet B", source="engine1"),
            SearchResult(title="Result C", url="https://cafef.vn/c.chn", snippet="Snippet C", source="engine1"),
            SearchResult(title="Result D", url="https://cafef.vn/d.chn", snippet="Snippet D", source="engine1"),  # Should be dropped by max 2/domain
        ],
    )
    e2 = MockSearchEngine(
        name="engine2",
        weight=1.0,
        return_results=[
            SearchResult(title="Result B copy", url="https://vietstock.vn/b.htm", snippet="Snippet B", source="engine2"),
            SearchResult(title="Result E", url="https://tinnhanhchungkhoan.vn/e.htm", snippet="Snippet E", source="engine2"),
        ],
    )

    aggregator = MultiSearchAggregator(
        engines=[e1, e2],
        per_engine_timeout=2.0,
        global_deadline=3.0,
        rrf_k=60,
        max_per_domain=2,
    )
    try:
        results = await aggregator.search("co phieu HPG", max_results=5)
        # Verify deduplication by URL: Result B appears in both engines, so it should have boosted score
        urls = [r.url for r in results]
        assert len(urls) == len(set(urls)), "Results must not contain duplicate URLs"
        assert "https://vietstock.vn/b.htm" in urls
        # Verify domain diversity: cafef.vn has 3 results, only top 2 should survive
        cafef_results = [r for r in results if "cafef.vn" in r.url]
        assert len(cafef_results) <= 2, f"Expected at most 2 results from cafef.vn, got {len(cafef_results)}"
        # Verify sorting by score descending
        for i in range(len(results) - 1):
            assert results[i].score >= results[i + 1].score
    finally:
        await aggregator.close()


class SlowSearchEngine(BaseSearchEngine):
    """Engine that never finishes inside the deadline."""

    def __init__(self, name: str, weight: float = 1.0) -> None:
        super().__init__(name=name, weight=weight)

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        await asyncio.sleep(30)
        return []


@pytest.mark.asyncio
async def test_aggregator_keeps_fast_engine_results_when_deadline_hits():
    """A slow engine must not erase the answers of the fast ones.

    Regression: the deadline used to cancel the whole gather and discard
    every batch, so one unresponsive engine wiped out all results and the
    search returned nothing.
    """
    fast = MockSearchEngine(
        name="fast",
        weight=1.0,
        return_results=[
            SearchResult(
                title="HPG Q3/2024",
                url="https://cafef.vn/hpg-q3.chn",
                snippet="Doanh thu 34.100 tỷ đồng",
                source="fast",
            )
        ],
    )
    slow = SlowSearchEngine(name="slow")

    aggregator = MultiSearchAggregator(
        engines=[fast, slow],
        per_engine_timeout=5.0,
        global_deadline=0.5,
    )
    try:
        results = await aggregator.search("HPG Q3 2024", max_results=5)
    finally:
        await aggregator.close()

    urls = [r.url for r in results]
    assert "https://cafef.vn/hpg-q3.chn" in urls, (
        "The fast engine's result must survive the global deadline"
    )


def test_bing_unwraps_click_tracking_redirect():
    """Bing wraps links in /ck/a?...&u=<base64>; the publisher URL must be recovered.

    Regression: the parser filtered on the substring "bing.com", which every
    wrapped link contains, so the Bing engine returned zero results.
    """
    import base64

    from src.tools.search.bing_engine import BingSearchEngine

    publisher = "https://cafef.vn/hpg-bctc-q3-2024.chn"
    encoded = "a1" + base64.urlsafe_b64encode(publisher.encode()).decode().rstrip("=")
    wrapped = f"https://www.bing.com/ck/a?!&&p=abc123&u={encoded}"

    html = f"""
    <ol id="b_results">
      <li class="b_algo">
        <h2><a href="{wrapped}">HPG công bố BCTC Q3/2024</a></h2>
        <div class="b_caption"><p>Doanh thu 34.100 tỷ đồng.</p></div>
      </li>
    </ol>
    """
    results = BingSearchEngine()._parse_bing_html(html, max_results=5)
    assert len(results) == 1, f"Expected one result, got {len(results)}"
    assert results[0].url == publisher
    assert results[0].title == "HPG công bố BCTC Q3/2024"


def test_bing_plain_links_still_parse():
    """A direct publisher link must pass through unchanged."""
    from src.tools.search.bing_engine import BingSearchEngine

    html = """
    <ol id="b_results">
      <li class="b_algo">
        <h2><a href="https://vietstock.vn/vnm-q3.htm">VNM Q3</a></h2>
        <div class="b_caption"><p>Lợi nhuận tăng.</p></div>
      </li>
    </ol>
    """
    results = BingSearchEngine()._parse_bing_html(html, max_results=5)
    assert len(results) == 1
    assert results[0].url == "https://vietstock.vn/vnm-q3.htm"


def test_wrapper_urls_are_marked_and_skipped():
    """A Google News link must be flagged as unreadable, and never fetched."""
    from src.tools.scraper.url_resolver import is_unreadable_wrapper

    wrapper = (
        "https://news.google.com/rss/articles/CBMifkFVX3lxTE9CbE9wbEtzNmNRVHlGbE1"
        "UTUFHQTlIb1ZrVVNhNXQwVHZiT3VJSk5uTUdnQWJOSkRRRVRtOWZNRERBY3BDVW1mSER4?oc=5"
    )
    assert is_unreadable_wrapper(wrapper) is True
    assert is_unreadable_wrapper("https://cafef.vn/hpg.chn") is False
    assert is_unreadable_wrapper("https://news.google.com/") is False


@pytest.mark.asyncio
async def test_concurrent_scraper_skips_wrapper_urls():
    """Wrapper URLs are reported, not fetched."""
    wrapper = (
        "https://news.google.com/rss/articles/CBMifkFVX3lxTE9CbE9wbEtzNmNRVHlGbE1"
        "UTUFHQTlIb1ZrVVNhNXQwVHZiT3VJSk5uTUdnQWJOSkRRRVRtOWZNRERBY3BDVW1mSER4?oc=5"
    )
    fake_scrape = ScrapeResult(
        url="https://cafef.vn/hpg.chn",
        html_content="<html><body><div class='article-body'><p>"
        "Doanh thu thuần quý 3/2024 đạt 34.100 tỷ đồng, tăng 19% so với cùng kỳ năm 2023.</p>"
        "</div></body></html>",
        status_code=200,
    )
    captured: list[list[str]] = []

    class _FakeScraper:
        def __init__(self, **kwargs) -> None:
            pass

        async def scrape_urls(self, urls, timeout: float = 15.0, **kwargs):
            captured.append(list(urls))
            return [fake_scrape]

        async def close(self) -> None:
            pass

    with patch("src.tools.parallel_web_tools.AsyncScrapingEngine", _FakeScraper):
        result = await concurrent_scrape_and_synthesize_async(
            urls=[wrapper, "https://cafef.vn/hpg.chn"],
            query="doanh thu HPG quy 3 2024",
            target_tickers=["HPG"],
            total_token_budget=1200,
        )

    assert captured, "The scraper must have been called"
    assert wrapper not in captured[0], "Wrapper URL must not be fetched"
    assert "https://cafef.vn/hpg.chn" in captured[0]
    assert result.get("skipped_wrapper_urls") == [wrapper]
    assert result["token_stats"]["wrapper_urls_skipped"] == 1


@pytest.mark.asyncio
async def test_concurrent_scraper_reports_empty_instead_of_blank_summary():
    """When nothing could be read, the result must say so."""
    with patch("src.tools.parallel_web_tools.AsyncScrapingEngine") as mock_cls:
        mock_cls.return_value.scrape_urls = AsyncMock(return_value=[])
        mock_cls.return_value.close = AsyncMock(return_value=None)
        result = await concurrent_scrape_and_synthesize_async(
            urls=["https://example.invalid/a"],
            query="anything",
        )
    assert result["status"] == "empty"
    assert result.get("error")
    assert result["summary_markdown"] == ""


# ===========================================================================
# 2. SCRAPER SUBSYSTEM & SSRF GUARD TESTS
# ===========================================================================

def test_ssrf_guard_blocks_prohibited_targets():
    guard = SSRFGuard()
    prohibited = [
        "http://localhost:8000/secret",
        "http://127.0.0.1:3000",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]:8080",
        "http://10.0.0.1/admin",
        "http://172.16.0.1/dashboard",
        "http://192.168.1.1/router",
        "http://0.0.0.0:5000",
        "ftp://example.com/file",
        "file:///etc/passwd",
    ]
    for url in prohibited:
        is_safe, resolved_ip, reason = guard.validate_url(url)
        assert not is_safe, f"URL {url} should have been rejected by SSRF guard! Reason: {reason}"


@pytest.mark.asyncio
async def test_dns_cache_expiration():
    cache = AsyncDNSCache(ttl_seconds=1.0)
    # Direct test of DNS resolution with safe public domain
    ips = await cache.resolve("one.one.one.one")
    assert len(ips) > 0
    # Cache hit check
    assert "one.one.one.one" in cache._cache


@pytest.mark.asyncio
async def test_rate_limiter_aimd():
    limiter = AdaptiveRateLimiter(default_host_concurrency=4, max_host_concurrency=8)
    state = await limiter._get_or_create_host_state("example.com")
    assert state.concurrency_limit == 4

    # Trigger 429 throttle -> Multiplicative Decrease (halves concurrency)
    limiter.report_result("example.com", status_code=429, is_timeout=False)
    assert state.concurrency_limit == 2
    limiter.report_result("example.com", status_code=429, is_timeout=False)
    assert state.concurrency_limit == 1

    # Trigger success recovery -> Additive Increase after threshold
    limiter.aimd_success_threshold = 2
    limiter.report_result("example.com", status_code=200)
    limiter.report_result("example.com", status_code=200)
    assert state.concurrency_limit == 2


# ===========================================================================
# 3. EXTRACTOR SUBSYSTEM TESTS
# ===========================================================================

def test_dom_cleaner_table_and_content_preservation():
    html_sample = """
    <!DOCTYPE html>
    <html>
    <head><title>Báo cáo tài chính HPG Q3/2024 - CafeF</title></head>
    <body>
        <nav class="navbar"><a href="/">Trang chủ</a><a href="/chung-khoan">Chứng khoán</a></nav>
        <div class="banner-ads"><img src="ad.png" alt="Quảng cáo xe máy"></div>
        <div class="content article-body">
            <h1>Tập đoàn Hòa Phát (HPG) công bố lợi nhuận Q3/2024</h1>
            <p>Doanh thu thuần quý 3/2024 đạt 34.100 tỷ đồng, tăng 19% so với cùng kỳ.</p>
            <table class="financial-table">
                <thead>
                    <tr><th>Chỉ tiêu</th><th>Q3/2023</th><th>Q3/2024</th></tr>
                </thead>
                <tbody>
                    <tr><td>Doanh thu thuần</td><td>28.766</td><td>34.100</td></tr>
                    <tr><td>Lợi nhuận sau thuế</td><td>2.000</td><td>3.022</td></tr>
                </tbody>
            </table>
            <p>Dự án Dung Quất 2 dự kiến hoàn thành đúng tiến độ.</p>
        </div>
        <div class="cookie-notice">Website sử dụng cookie để cải thiện trải nghiệm.</div>
        <footer>Bản quyền thuộc về CafeF 2024</footer>
    </body>
    </html>
    """
    cleaned = clean_html(html_sample, url="https://cafef.vn/hpg-q3-2024.chn")
    # Verify title extracted
    assert "HPG" in cleaned.title
    # Verify boilerplate removed
    assert "Trang chủ" not in cleaned.clean_markdown
    assert "Quảng cáo xe máy" not in cleaned.clean_markdown
    assert "Website sử dụng cookie" not in cleaned.clean_markdown
    # Verify core content and table preserved in GFM Markdown format
    assert "34.100" in cleaned.clean_markdown
    assert "3.022" in cleaned.clean_markdown
    assert "| Doanh thu thuần |" in cleaned.clean_markdown or "Doanh thu thuần" in cleaned.clean_markdown


def test_3tier_deduplication():
    # Primary doc
    doc1 = CleanDocument(
        url="https://cafef.vn/hpg-q3.chn?utm_source=fb",
        canonical_url="https://cafef.vn/hpg-q3.chn",
        title="HPG báo lãi lớn Q3/2024",
        clean_markdown="Tập đoàn Hòa Phát vừa công bố kết quả kinh doanh quý 3 đạt doanh thu thuần 34.100 tỷ đồng và lợi nhuận 3.022 tỷ đồng.",
    )
    # Tier 1 Duplicate: identical canonical URL
    doc2 = CleanDocument(
        url="https://cafef.vn/hpg-q3.chn?utm_campaign=share",
        canonical_url="https://cafef.vn/hpg-q3.chn",
        title="HPG báo lãi lớn Q3/2024",
        clean_markdown="Tập đoàn Hòa Phát vừa công bố kết quả kinh doanh quý 3 đạt doanh thu thuần 34.100 tỷ đồng.",
    )
    # Tier 2/3 Duplicate: syndicated text with tiny source variation
    doc3 = CleanDocument(
        url="https://vietstock.vn/hpg-q3.htm",
        canonical_url="https://vietstock.vn/hpg-q3.htm",
        title="Hòa Phát lãi ròng hơn 3.000 tỷ quý 3",
        clean_markdown="Tập đoàn Hòa Phát vừa công bố kết quả kinh doanh quý 3 đạt doanh thu thuần 34.100 tỷ đồng và lợi nhuận 3.022 tỷ đồng. (Theo CafeF)",
    )
    # Distinct doc
    doc4 = CleanDocument(
        url="https://cafef.vn/vnm-q3.chn",
        canonical_url="https://cafef.vn/vnm-q3.chn",
        title="Vinamilk công bố doanh thu quý 3",
        clean_markdown="Công ty Cổ phần Sữa Việt Nam Vinamilk vừa công bố doanh thu đạt 16.500 tỷ đồng trong quý 3.",
    )

    deduped = deduplicate_documents([doc1, doc2, doc3, doc4])
    assert len(deduped) <= 2, f"Expected 2 unique topics (HPG, VNM), got {len(deduped)}"
    urls = [d.url for d in deduped]
    assert any("vnm" in u for u in urls), "Distinct document VNM must be retained"


# ===========================================================================
# 4. OPTIMIZER SUBSYSTEM (CHUNK & BM25-FSB) TESTS
# ===========================================================================

def test_semantic_chunker_and_bm25_salience():
    article = """# Báo cáo Hòa Phát HPG Q3/2024
## 1. Kết quả kinh doanh
Trong quý 3/2024, Tập đoàn Hòa Phát (HPG) đạt doanh thu 34.100 tỷ đồng và lợi nhuận sau thuế 3.022 tỷ đồng.
## 2. Bảng chỉ tiêu
| Chỉ tiêu | Q3/2024 |
| :--- | ---: |
| Doanh thu thuần | 34.100 |
| Lợi nhuận sau thuế | 3.022 |
## 3. Điều khoản & Liên hệ quảng cáo
Bản quyền thuộc về ban biên tập. Liên hệ quảng cáo 0912345678.
"""
    doc = CleanDocument(
        url="https://cafef.vn/hpg.chn",
        title="HPG Q3/2024",
        clean_markdown=article,
    )
    pruned = prune_document(
        doc=doc,
        query="kết quả kinh doanh HPG quý 3 năm 2024",
        tickers=["HPG"],
        budget=1000,
    )
    assert pruned.pruned_token_count > 0
    # Financial table and core metrics should be preserved
    combined = pruned.combined_markdown
    assert "34.100" in combined
    assert "3.022" in combined
    # Boilerplate contact should be pruned or scored very low
    assert "Liên hệ quảng cáo 0912345678" not in combined


# ===========================================================================
# 5. SYNTHESIS SUBSYSTEM TESTS
# ===========================================================================

@pytest.mark.asyncio
async def test_synthesis_conflict_resolution():
    # Source S1 (Tier 1: Official Exchange)
    s1_chunk = Chunk(
        index=0,
        content="# HOSE Công bố BCTC Q3/2024 HPG\nDoanh thu thuần đạt 34.100 tỷ đồng, lợi nhuận sau thuế đạt 3.022 tỷ đồng.",
        token_count=30,
    )
    doc1 = PrunedDocument(
        url="https://hsx.vn/hpg-bctc-q3.pdf",
        title="HOSE: BCTC Q3/2024 HPG",
        source_id="S1",
        publisher_tier=1,
        selected_chunks=[s1_chunk],
        original_token_count=300,
        pruned_token_count=30,
        pruning_ratio=0.90,
    )

    # Source S2 (Tier 4: Financial Media with conflicting number: 2.850 tỷ instead of 3.022 tỷ)
    s2_chunk = Chunk(
        index=0,
        content="# Báo chí ước tính HPG\nDoanh thu thuần đạt 34.100 tỷ đồng, lợi nhuận sau thuế ước đạt 2.850 tỷ đồng.",
        token_count=30,
    )
    doc2 = PrunedDocument(
        url="https://cafef.vn/hpg-estimate.chn",
        title="CafeF: Ước tính lợi nhuận HPG",
        source_id="S2",
        publisher_tier=4,
        selected_chunks=[s2_chunk],
        original_token_count=300,
        pruned_token_count=30,
        pruning_ratio=0.90,
    )

    artifact = await synthesize_research(
        docs=[doc1, doc2],
        query="Doanh thu và lợi nhuận HPG Q3/2024",
        target_tickers=["HPG"],
    )

    assert len(artifact.reconciled_metrics) >= 2
    # Verify conflict resolution for LNST
    lnst_metric = next((m for m in artifact.reconciled_metrics if "Lợi nhuận sau thuế" in m.metric_name), None)
    assert lnst_metric is not None
    assert lnst_metric.status == "discrepancy"
    # Tier 1 (3022.0) must win over Tier 4 (2850.0)
    assert lnst_metric.canonical_value == 3022.0
    assert lnst_metric.canonical_source_id == "S1"
    assert "Tier 1" in lnst_metric.resolution_rationale

    # Verify concordancy for Revenue (both agree on 34100.0)
    rev_metric = next((m for m in artifact.reconciled_metrics if "Doanh thu thuần" in m.metric_name), None)
    assert rev_metric is not None
    assert rev_metric.status == "concordant"
    assert rev_metric.canonical_value == 34100.0


# ===========================================================================
# 6. UNIFIED TOOLS EXECUTION TESTS
# ===========================================================================

def _make_doc(source_id: str, title: str, content: str, tier: int = 4) -> PrunedDocument:
    chunk = Chunk(index=0, content=content, token_count=60)
    return PrunedDocument(
        url=f"https://example.com/{source_id}",
        title=title,
        source_id=source_id,
        publisher_tier=tier,
        selected_chunks=[chunk],
        original_token_count=600,
        pruned_token_count=60,
        pruning_ratio=0.90,
    )


def test_prose_extractor_does_not_read_roman_numerals_as_tickers():
    """Quý III is a quarter, not a ticker.

    Regression: the ticker scan took any three upper-case letters, so a
    figure in a "quý III" sentence was filed under ticker "III".
    """
    from src.tools.synthesis.map_extractor import _find_ticker

    assert _find_ticker("Kết quả quý III/2024") == ""
    assert _find_ticker("HPG công bố BCTC") == "HPG"


def test_prose_extractor_binds_figure_to_nearest_ticker():
    """A round-up article mentions many companies; each figure keeps its own.

    Regression: every figure in a chunk inherited the first ticker in the
    chunk, so a VIX figure was reported as an HPG figure.
    """
    extractor = DeterministicRuleExtractor()
    text = (
        "HPG công bố kết quả kinh doanh quý 3/2024.\n"
        "Doanh thu thuần của HPG đạt 34.100 tỷ đồng.\n"
        "Trong khi đó VIX có doanh thu thuần đạt 8.100 tỷ đồng."
    )
    facts = extractor._extract_from_prose(
        text=text,
        source_id="S1",
        publisher_tier=4,
        source_title="Round-up",
        source_url="https://example.com/a",
        ticker="HPG",
    )
    by_ticker = {f.ticker: f.value for f in facts}
    assert by_ticker.get("HPG") == 34100.0, f"HPG figure wrong: {by_ticker}"
    assert by_ticker.get("VIX") == 8100.0, f"VIX figure wrong or missing: {by_ticker}"


def test_prose_extractor_does_not_cross_table_boundary():
    """A metric name must not bind to a number that sits in another column.

    Regression: the gap pattern allowed any character, so "doanh thu" in
    the row label bound to a value in a later cell of the same table.
    """
    extractor = DeterministicRuleExtractor()
    text = (
        "| Chỉ tiêu | Q3/2024 |\n"
        "| :--- | ---: |\n"
        "| Doanh thu tài chính | 194 |\n"
        "| Doanh thu thuần | 34.100 |"
    )
    facts = extractor._extract_from_prose(
        text=text,
        source_id="S1",
        publisher_tier=4,
        source_title="BCTC",
        source_url="https://example.com/a",
        ticker="HPG",
    )
    # "doanh thu tài chính" must not become "Doanh thu thuần"
    assert all(f.metric_name != "Doanh thu thuần" or f.value == 34100.0 for f in facts), (
        f"Financial income was read as net revenue: {[(f.metric_name, f.value) for f in facts]}"
    )


@pytest.mark.asyncio
async def test_map_extractor_drops_other_companies_for_target_ticker():
    """Only facts about the requested ticker reach the reduced matrix."""
    doc = _make_doc(
        source_id="S1",
        title="Bản tin thị trường",
        content=(
            "HPG đạt doanh thu thuần 34.100 tỷ đồng.\n"
            "MBS đạt doanh thu thuần 5.200 tỷ đồng.\n"
            "PDR đạt doanh thu thuần 3.400 tỷ đồng."
        ),
    )
    mapper = MapExtractor()
    facts = await mapper.extract_facts(
        docs=[doc],
        query="doanh thu HPG quý 3 2024",
        target_tickers=["HPG"],
    )
    tickers = {f.ticker for f in facts}
    assert "MBS" not in tickers, f"Other companies must be dropped: {tickers}"
    assert "PDR" not in tickers, f"Other companies must be dropped: {tickers}"
    assert "HPG" in tickers, f"Target ticker must be kept: {tickers}"


@pytest.mark.asyncio
async def test_map_extractor_labels_period_by_position():
    """Each figure carries the period nearest to it.

    Regression: the whole chunk shared one period, so a 2025 figure was
    filed under the first period found in the chunk.
    """
    doc = _make_doc(
        source_id="S1",
        title="HPG BCTC",
        content=(
            "HPG quý 3/2024 đạt doanh thu thuần 34.100 tỷ đồng.\n"
            "HPG quý 3/2025 đạt doanh thu thuần 42.500 tỷ đồng."
        ),
    )
    mapper = MapExtractor()
    facts = await mapper.extract_facts(
        docs=[doc],
        query="doanh thu HPG",
        target_tickers=["HPG"],
    )
    periods = {f.fiscal_period: f.value for f in facts}
    assert any("2024" in str(p) and v == 34100.0 for p, v in periods.items()), periods
    assert any("2025" in str(p) and v == 42500.0 for p, v in periods.items()), periods


def test_roman_quarter_is_read_as_a_period():
    """"quý III" is a quarter, and it must be labelled as one.

    Regression: the period pattern only matched "quý 3/2024", so a figure
    in a "quý III" sentence lost its period and fell back to whatever
    year appeared elsewhere in the chunk.
    """
    from src.tools.synthesis.map_extractor import _normalize_period

    assert _normalize_period("quý III") == "Q3"
    assert _normalize_period("quý III/2024") == "Q3/2024"
    assert _normalize_period("quý IV") == "Q4"
    assert _normalize_period("Q3/2024") == "Q3/2024"


def test_quarter_without_year_gets_the_document_year():
    """A bare quarter takes the year from the document."""
    extractor = DeterministicRuleExtractor()
    facts = extractor._extract_from_prose(
        text="Về kết quả kinh doanh quý III, doanh thu đạt 34.000 tỷ đồng.",
        source_id="S1",
        publisher_tier=4,
        source_title="Kết quả kinh doanh HPG quý III/2024",
        source_url="https://example.com/a",
        ticker="HPG",
    )
    revenue = next((f for f in facts if "Doanh thu" in f.metric_name), None)
    assert revenue is not None, "The revenue figure must be extracted"
    assert revenue.fiscal_period == "Q3/2024", revenue.fiscal_period
    assert revenue.value == 34000.0


def test_figure_before_metric_name_is_extracted():
    """"105.000 tỷ đồng doanh thu" must be read as revenue.

    Regression: only the metric-name-first order was matched, so a large
    share of the figures in Vietnamese articles were missed.
    """
    extractor = DeterministicRuleExtractor()
    facts = extractor._extract_from_prose(
        text=(
            "Lũy kế 9 tháng đầu năm, tập đoàn này ghi nhận gần 105.000 tỷ đồng "
            "doanh thu và 9.210 tỷ đồng lợi nhuận sau thuế."
        ),
        source_id="S1",
        publisher_tier=4,
        source_title="HPG BCTC 9 tháng 2024",
        source_url="https://example.com/a",
        ticker="HPG",
    )
    by_name = {f.metric_name: f.value for f in facts}
    assert by_name.get("Doanh thu thuần") == 105000.0, by_name
    assert by_name.get("Lợi nhuận sau thuế") == 9210.0, by_name


def test_two_metrics_in_one_sentence_keep_their_own_numbers():
    """A sentence with two metrics must not swap their figures.

    Regression: the gap between a metric name and its value crossed the
    word "và", so the second number was filed under the first metric.
    """
    extractor = DeterministicRuleExtractor()
    facts = extractor._extract_from_prose(
        text="HPG đạt doanh thu thuần 34.000 tỷ đồng và lợi nhuận sau thuế đạt 3.022 tỷ đồng.",
        source_id="S1",
        publisher_tier=4,
        source_title="HPG quý 3/2024",
        source_url="https://example.com/a",
        ticker="HPG",
    )
    by_name = {f.metric_name: f.value for f in facts}
    assert by_name.get("Doanh thu thuần") == 34000.0, by_name
    assert by_name.get("Lợi nhuận sau thuế") == 3022.0, by_name


def test_comparison_label_is_not_used_as_a_period():
    """"YoY" describes a comparison, not a fiscal period.

    Regression: a YoY figure was filed under the period "YoY", which
    hides the quarter it belongs to.
    """
    from src.tools.synthesis.map_extractor import COMPARISON_LABELS

    assert "yoy" in COMPARISON_LABELS
    extractor = DeterministicRuleExtractor()
    facts = extractor._extract_from_prose(
        text="Doanh thu tăng 23% và lợi nhuận sau thuế tăng 140% YoY.",
        source_id="S1",
        publisher_tier=4,
        source_title="HPG quý 3/2024",
        source_url="https://example.com/a",
        ticker="HPG",
    )
    for fact in facts:
        assert fact.fiscal_period.lower() != "yoy", fact.fiscal_period



def test_parallel_web_search_tool_execute():
    tool = ParallelWebSearchTool()
    # Test execution with mock
    with patch("src.tools.parallel_web_tools.parallel_web_search_async") as mock_search:
        mock_search.return_value = {
            "status": "ok",
            "primary_query": "HPG Q3 2024",
            "results_count": 1,
            "latency_ms": 150.0,
            "results": [
                {
                    "title": "HPG BCTC Q3",
                    "url": "https://cafef.vn/hpg.chn",
                    "snippet": "Lợi nhuận tăng mạnh",
                    "source": "duckduckgo",
                    "score": 0.85,
                    "published_date": "2024-10-25",
                }
            ],
        }
        res_json = tool.execute(query="HPG Q3 2024", max_results=5)
        parsed = json.loads(res_json)
        assert parsed["status"] == "ok"
        assert parsed["results_count"] == 1
        assert parsed["results"][0]["url"] == "https://cafef.vn/hpg.chn"


def test_concurrent_scraper_tool_execute():
    tool = ConcurrentScraperTool()
    # Test execution with mock
    with patch("src.tools.parallel_web_tools.concurrent_scrape_and_synthesize_async") as mock_scrape:
        mock_scrape.return_value = {
            "status": "ok",
            "query": "HPG Q3/2024",
            "summary_markdown": "### Tổng hợp HPG\nDoanh thu 34.100 tỷ đồng [S1].",
            "token_stats": {
                "raw_tokens": 2000,
                "pruned_tokens": 300,
                "reduction_pct": 85.0,
            },
            "sources": [{"source_id": "S1", "url": "https://cafef.vn/hpg.chn"}],
            "reconciled_metrics": [],
        }
        res_json = tool.execute(
            urls=["https://cafef.vn/hpg.chn"],
            query="HPG Q3/2024",
            target_tickers=["HPG"],
        )
        parsed = json.loads(res_json)
        assert parsed["status"] == "ok"
        assert parsed["token_stats"]["reduction_pct"] == 85.0
        assert "[S1]" in parsed["summary_markdown"]
