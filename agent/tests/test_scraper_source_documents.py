"""Full fetched sources survive summary pruning and expose incomplete reads."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from src.tools.parallel_web_tools import ConcurrentScraperTool
from src.tools.scraper import AsyncScrapingEngine, ScrapeResult


@pytest.fixture(autouse=True)
def allowed_run(tmp_path, monkeypatch):
    monkeypatch.setenv('VIBE_TRADING_ALLOWED_RUN_ROOTS', str(tmp_path))


def scraper_results(monkeypatch, results, rendered=None):
    monkeypatch.setattr('src.tools.parallel_web_tools.AsyncScrapingEngine', lambda **kwargs: SimpleNamespace(
        scrape_urls=AsyncMock(return_value=results), close=AsyncMock(),
    ))
    fallback = AsyncMock(return_value=rendered or {})
    monkeypatch.setattr('src.tools.parallel_web_tools.fetch_rendered_markdown_batch_detailed', fallback)
    return fallback


def scrape(tmp_path, urls):
    return json.loads(ConcurrentScraperTool().execute(
        urls=urls, query='business opening', synthesize=False, token_budget=600, run_dir=str(tmp_path),
    ))


def test_complete_clean_text_and_raw_html_survive_bm25_pruning(tmp_path, monkeypatch):
    url = 'https://example.com/research'
    html = '<article><h1>Business opening</h1>' + '<p>Operating details and capital allocation. </p>' * 800
    html += '<p>TAIL_EVIDENCE_PRESERVED.</p></article>'
    scraper_results(monkeypatch, [ScrapeResult(url, html, 200, headers={'content-type': 'text/html'})])

    result = scrape(tmp_path, [url])

    document = result['source_documents'][0]
    assert Path(document['artifact_path']).read_bytes() == html.encode()
    full_text = Path(document['full_text_path']).read_text(encoding='utf-8')
    assert 'TAIL_EVIDENCE_PRESERVED' in full_text
    assert len(full_text) > len(result['summary_markdown'])
    assert document['coverage']['extraction_complete'] is True
    assert document['coverage']['text_delivery_complete'] is False
    assert document['coverage']['complete'] is False
    assert result['coverage']['extraction_complete'] is True
    assert result['coverage']['complete'] is False


@pytest.mark.parametrize('render_success', [False, True])
def test_nonempty_nextjs_shell_needs_rendering_and_failed_page_makes_batch_partial(tmp_path, monkeypatch, render_success):
    dynamic = 'https://example.com/investors'
    ordinary = 'https://example.com/article'
    shell = '<html><script id="__NEXT_DATA__">{"page":"/investors"}</script><h1>Investor Relations</h1><p>Select a year.</p></html>'
    rendered = 'Annual financial statements and cash flow analysis. ' * 30 if render_success else ''
    fallback = scraper_results(monkeypatch, [
        ScrapeResult(dynamic, shell, 200, headers={'content-type': 'text/html'}),
        ScrapeResult(ordinary, '<article><p>Business opening revenue and operations report.</p></article>', 200),
    ], {dynamic: (rendered, '' if render_success else 'http_403')})

    result = scrape(tmp_path, [dynamic, ordinary])

    fallback.assert_awaited_once_with([dynamic])
    document = next(doc for doc in result['source_documents'] if doc['url'] == dynamic)
    assert document['coverage']['extraction_complete'] is render_success
    assert result['coverage']['extraction_complete'] is render_success
    assert document['coverage']['text_delivery_complete'] is False
    assert result['coverage']['complete'] is False
    if render_success:
        assert rendered.strip() in Path(document['full_text_path']).read_text(encoding='utf-8')
    else:
        assert result['status'] == 'partial'
        assert document['coverage']['status'] in {'partial', 'blocked'}


@pytest.mark.asyncio
async def test_pdf_fetch_keeps_binary_out_of_html_and_retains_original_bytes(monkeypatch):
    data = b'%PDF-1.7\n\xff\x00binary document bytes\n%%EOF'
    monkeypatch.setattr('src.tools.scraper.fetcher.SSRFGuard.validate_url', lambda url: (True, '1.1.1.1', ''))
    engine = AsyncScrapingEngine()
    engine._client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, content=data, headers={'content-type': 'application/pdf'})
    ))
    try:
        result = await engine.scrape_url('https://example.com/filing.pdf')
    finally:
        await engine.close()

    assert result.html_content == '', 'Binary PDF data must never reach the HTML cleaner'
    assert result.content_bytes == data
    assert result.content_type == 'application/pdf'


@pytest.mark.asyncio
async def test_origin_size_limit_reports_partial_bytes_without_html_success(monkeypatch):
    monkeypatch.setattr('src.tools.scraper.fetcher.SSRFGuard.validate_url', lambda url: (True, '1.1.1.1', ''))
    monkeypatch.setattr('src.tools.scraper.fetcher._MAX_RESPONSE_BYTES', 100)
    engine = AsyncScrapingEngine()
    engine._client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(
        200, content=b'<article>' + b'x' * 1000, headers={'content-type': 'text/html'},
    )))
    try:
        result = await engine.scrape_url('https://example.com/report')
    finally:
        await engine.close()
    assert result.success is False
    assert result.truncated is True
    assert result.html_content == ''
    assert len(result.content_bytes) == 100
    assert result.error == 'response_size_limit_exceeded'


def test_scraper_dispatches_pdf_without_treating_it_as_delivered(tmp_path, monkeypatch):
    import io
    from reportlab.pdfgen import canvas

    output = io.BytesIO()
    writer = canvas.Canvas(output)
    writer.drawString(50, 750, 'Audited business operations and annual financial statement disclosures.')
    writer.save()
    data = output.getvalue()
    url = 'https://example.com/download?id=123'
    scraper_results(monkeypatch, [ScrapeResult(
        url, '', 200, content_bytes=data, content_type='application/octet-stream',
    )])

    result = scrape(tmp_path, [url])

    document = result['source_documents'][0]
    assert Path(document['artifact_path']).read_bytes() == data
    assert 'Audited business' in Path(document['full_text_path']).read_text(encoding='utf-8')
    assert document['coverage']['extraction_complete'] is True
    assert document['coverage']['text_delivery_complete'] is False


@pytest.mark.asyncio
async def test_truncated_rendered_reader_is_never_complete(monkeypatch):
    from src.tools.scraper import reader_fallback as fallback

    monkeypatch.setattr(fallback, '_MAX_READER_BYTES', 100)
    monkeypatch.setattr('src.tools.scraper.ssrf_guard.SSRFGuard.validate_url', lambda _: (True, '1.1.1.1', ''))
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(
        200, text='Annual business disclosure. ' * 100, headers={'content-type': 'text/plain'},
    ))) as client:
        body, reason = await fallback._fetch_rendered_markdown_detailed('https://example.com/report', client=client)
    assert body
    assert reason == 'response_size_limit_exceeded'


@pytest.mark.asyncio
async def test_rendered_reader_never_forwards_credentials_or_private_dns(monkeypatch):
    from src.tools.scraper import reader_fallback as fallback

    monkeypatch.setattr('src.tools.scraper.ssrf_guard.SSRFGuard.validate_url', lambda _: (False, '127.0.0.1', 'private'))
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: pytest.fail('Unsafe target was forwarded'))) as client:
        assert await fallback._fetch_rendered_markdown_detailed('https://public.example/report', client=client) == ('', 'unsafe_host')
        assert await fallback._fetch_rendered_markdown_detailed('https://user:secret@public.example/report', client=client) == ('', 'unsafe_url')


@pytest.mark.asyncio
async def test_scraper_keeps_grounding_run_when_called_from_running_event_loop(tmp_path, monkeypatch):
    from src.agent.tool_context import current_grounding

    url = 'https://example.com/research'
    scraper_results(monkeypatch, [ScrapeResult(url, '<article>Business operations disclosure.</article>', 200)])
    token = current_grounding.set(SimpleNamespace(run_dir=tmp_path))
    try:
        result = json.loads(ConcurrentScraperTool().execute(urls=[url], synthesize=False))
    finally:
        current_grounding.reset(token)
    assert Path(result['source_documents'][0]['artifact_path']).is_relative_to(tmp_path)


def test_redirected_source_keeps_requested_url_alias_and_final_origin(tmp_path, monkeypatch):
    url = 'https://example.com/latest'
    final = 'https://example.com/filing'
    scraper_results(monkeypatch, [ScrapeResult(
        url, '<article>Business operations disclosure.</article>', 200, final_url=final,
    )])
    result = scrape(tmp_path, [url])
    document = result['source_documents'][0]
    assert document['url'] == url
    assert document['source'] == final
    assert document['final_url'] == final


def test_failed_fetch_is_saved_without_claiming_successful_batch(tmp_path, monkeypatch):
    good = 'https://example.com/article'
    blocked = 'https://example.com/blocked'
    raw = b'<html>Access denied</html>'
    scraper_results(monkeypatch, [
        ScrapeResult(good, '<article>Business operations disclosure.</article>', 200),
        ScrapeResult(blocked, raw.decode(), 403, success=False, content_bytes=raw, error='HTTP 403'),
    ])
    result = scrape(tmp_path, [good, blocked])
    document = next(doc for doc in result['source_documents'] if doc['url'] == blocked)
    assert Path(document['artifact_path']).read_bytes() == raw
    assert document['coverage']['extraction_complete'] is False
    assert result['status'] == 'partial'
    assert result['coverage']['documents_extracted'] == 1
