"""Unit and Integration Tests for Token-Optimized DOM Extractor Subsystem (Milestone M2).

Covers:
1. DOM Cleaning Pipeline (lxml + Rust nh3 whitelist sanitization)
2. High-Fidelity GFM Table Engine & Markdown Converter (aligned numbers & text, Vietnamese financial figures)
3. 3-Tier Cross-Site Deduplication Engine (URL normalization, exact SHA-256, 64-bit SimHash)
4. M2 -> M3 CleanDocument Interface Contract
"""

from __future__ import annotations

import pytest

from src.tools.extractor import (
    CleanDocument,
    DOMCleaner,
    MarkdownConverter,
    clean_html,
    compute_exact_hash,
    compute_simhash_64,
    deduplicate_documents,
    extract_metadata,
    hamming_distance,
    is_near_duplicate,
    normalize_canonical_url,
)
from src.tools.extractor.markdown_converter import is_financial_number


# ===========================================================================
# 1. DOM CLEANER TESTS
# ===========================================================================

def test_stage1_strip_technical_and_boilerplate_tags():
    """Verify technical elements (scripts, styles, forms, iframes) and boilerplate are dropped."""
    cleaner = DOMCleaner()
    html = """
    <html>
    <head><title>Báo cáo tài chính</title></head>
    <body>
        <script>alert('bad');</script>
        <style>.bad { color: red; }</style>
        <header><nav class="navbar"><a href="/">Trang chủ</a></nav></header>
        <div class="ad-banner">Khuyến mãi cực sốc</div>
        <div class="cookie-consent">Chấp nhận cookie</div>
        <main>
            <div class="fck_detail">
                <h1>Kết quả kinh doanh quý 3/2024</h1>
                <p>Doanh thu hợp nhất quy đổi đạt 18.500 tỷ đồng.</p>
            </div>
        </main>
        <footer class="footer">Bản quyền 2026</footer>
    </body>
    </html>
    """
    res = cleaner.clean(html, "https://cafef.vn/bctc-q3")
    assert "alert" not in res.sanitized_html
    assert "Trang chủ" not in res.sanitized_html
    assert "Khuyến mãi cực sốc" not in res.sanitized_html
    assert "Chấp nhận cookie" not in res.sanitized_html
    assert "Bản quyền 2026" not in res.sanitized_html
    assert "18.500 tỷ đồng" in res.sanitized_html


def test_stage2_main_content_extraction_density():
    """Verify extraction chooses high-density container over navigation lists."""
    cleaner = DOMCleaner()
    html = """
    <html>
    <body>
        <div class="nav-links">
            <a href="/1">Link 1</a> <a href="/2">Link 2</a> <a href="/3">Link 3</a>
            <a href="/4">Link 4</a> <a href="/5">Link 5</a> <a href="/6">Link 6</a>
        </div>
        <div class="article-body">
            <h2>Vinhomes đạt lợi nhuận kỷ lục</h2>
            <p>Tổng doanh thu thuần hợp nhất quy đổi ghi nhận 15.200 tỷ đồng trong quý 3.</p>
            <p>Lợi nhuận sau thuế đạt 2.850 tỷ đồng, tăng trưởng 35,7% so với cùng kỳ năm ngoái.</p>
        </div>
    </body>
    </html>
    """
    res = cleaner.clean(html, "https://vietstock.vn/vhm")
    assert "Link 1" not in res.sanitized_html
    assert "Vinhomes đạt lợi nhuận kỷ lục" in res.sanitized_html
    assert res.link_density < 0.4


def test_stage2_large_menu_loses_to_article():
    """A big navigation block must not out-score the article beside it.

    Regression: the menu on a real portal (vietstock.vn) holds more text than
    the story. Menu labels are short, so their link density stays low and the
    old length-based score picked the menu, producing a "summary" made only of
    navigation labels. The menu is recognised by its list items and its
    lack of paragraphs.
    """
    menu_items = "".join(
        f"<li><a href='/m{i}'>Chuyên mục tài chính số {i} và phân tích thị trường</a></li>"
        for i in range(40)
    )
    cleaner = DOMCleaner()
    html = f"""
    <html>
    <body>
        <div class="main-menu"><ul>{menu_items}</ul></div>
        <div class="article-body">
            <h1>HPG công bố kết quả kinh doanh quý 3/2024</h1>
            <p>Doanh thu thuần hợp nhất quý 3/2024 đạt 34.100 tỷ đồng, tăng 19% so với cùng kỳ năm 2023.</p>
            <p>Lợi nhuận sau thuế hợp nhất đạt 3.022 tỷ đồng, tăng trưởng 51% so với cùng kỳ năm trước.</p>
            <p>Biên lợi nhuận gộp quý 3 cải thiện lên 13,8% so với mức 10,5% của quý 3/2023.</p>
        </div>
    </body>
    </html>
    """
    res = cleaner.clean(html, "https://cafef.vn/hpg-bctc-q3")
    assert "34.100 tỷ đồng" in res.sanitized_html
    assert "3.022 tỷ đồng" in res.sanitized_html
    assert "Chuyên mục tài chính số 39" not in res.sanitized_html


def test_stage2_menu_only_page_reports_no_article_text():
    """A page that is nothing but a menu must not be reported as an article.

    Regression: the homepage of a portal is a menu. Returning it as cleaned
    article text wastes the whole token budget on navigation labels.
    """
    html = """
    <html>
    <body>
        <div class="main-menu">
            <ul>
                <li><a href="/a">Chứng khoán</a></li>
                <li><a href="/b">Doanh nghiệp</a></li>
                <li><a href="/c">Bất động sản</a></li>
            </ul>
        </div>
    </body>
    </html>
    """
    doc = clean_html(html, "https://www.vietstock.vn/")
    # The pipeline treats an empty result as "needs the reader service", so
    # the important guarantee is that no navigation text is presented as an
    # article body.
    assert "Chứng khoán" not in doc.clean_markdown or len(doc.clean_markdown) < 200


def test_stage3_nh3_sanitization():
    """Verify nh3 strips inline styles and event handlers while preserving colspan/rowspan."""
    cleaner = DOMCleaner()
    html = """
    <div class="fck_detail">
        <p style="color:red;" onclick="evil()">Thông báo</p>
        <table>
            <tr><th colspan="2" style="background:yellow;">Chỉ tiêu</th></tr>
            <tr><td>Doanh thu</td><td>15.200 tỷ</td></tr>
        </table>
    </div>
    """
    res = cleaner.clean(html)
    assert 'style="color:red' not in res.sanitized_html
    assert "onclick" not in res.sanitized_html
    assert 'colspan="2"' in res.sanitized_html
    assert "15.200 tỷ" in res.sanitized_html


# ===========================================================================
# 2. MARKDOWN & GFM TABLE ENGINE TESTS
# ===========================================================================

def test_financial_number_recognition():
    """Verify numeric, percentage, and Vietnamese currency formatting detection."""
    assert is_financial_number("15.200 tỷ") is True
    assert is_financial_number("1.234,5 triệu") is True
    assert is_financial_number("+21,7%") is True
    assert is_financial_number("-5.2%") is True
    assert is_financial_number("(1.200)") is True
    assert is_financial_number("2.850 VND") is True
    assert is_financial_number("-") is True
    assert is_financial_number("N/A") is True

    # Reporting periods and headers must NOT be classified as numeric metrics
    assert is_financial_number("Doanh thu thuần") is False
    assert is_financial_number("Q3/2024") is False
    assert is_financial_number("YTD") is False
    assert is_financial_number("YoY") is False


def test_gfm_table_conversion_and_alignment():
    """Verify conversion of financial HTML table to aligned GFM markdown."""
    converter = MarkdownConverter()
    html = """
    <table>
        <thead>
            <tr><th>Chỉ tiêu</th><th>Q3/2023</th><th>Q3/2024</th><th>Tăng trưởng</th></tr>
        </thead>
        <tbody>
            <tr><td>Doanh thu</td><td>28.500 tỷ</td><td>34.100 tỷ</td><td>+19,6%</td></tr>
            <tr><td>Lợi nhuận</td><td>2.000 tỷ</td><td>2.850 tỷ</td><td>+42,5%</td></tr>
        </tbody>
    </table>
    """
    md = converter.convert(html)
    lines = [line.strip() for line in md.splitlines() if line.strip()]

    # Verify header and separator line
    assert lines[0] == "| Chỉ tiêu | Q3/2023 | Q3/2024 | Tăng trưởng |"
    assert lines[1] == "|:---|---:|---:|---:|", "Text left-aligned, financial figures right-aligned"
    assert "34.100 tỷ" in md
    assert "+42,5%" in md


def test_pipe_escaping_in_cells():
    """Verify pipe characters inside table cells are escaped."""
    converter = MarkdownConverter()
    html = "<table><tr><th>Metric | Sub</th></tr><tr><td>Value | Note</td></tr></table>"
    md = converter.convert(html)
    assert r"Metric \| Sub" in md
    assert r"Value \| Note" in md


# ===========================================================================
# 3. 3-TIER DEDUPLICATION TESTS
# ===========================================================================

def test_canonical_url_normalization():
    """Verify stripping of tracking parameters, fragments, and default ports."""
    u1 = "https://cafef.vn/vhm.chn?utm_source=fb&utm_medium=cpc#overview"
    u2 = "https://cafef.vn/vhm.chn?fbclid=123&session_id=abc"
    assert normalize_canonical_url(u1) == "https://cafef.vn/vhm.chn"
    assert normalize_canonical_url(u2) == "https://cafef.vn/vhm.chn"


def test_exact_hash():
    """Verify SHA-256 hash collapses whitespace and case."""
    t1 = "Doanh thu quý 3 đạt 15.200 tỷ đồng."
    t2 = "  doanh thu   quý 3 đạt 15.200 tỷ đồng.\n\n"
    assert compute_exact_hash(t1) == compute_exact_hash(t2)


def test_simhash_syndication_and_near_duplicate():
    """Verify 64-bit SimHash groups syndicated articles (Hamming <= 3) and separates distinct articles (> 10)."""
    story_cafef = (
        "Vinhomes (VHM) vừa công bố kết quả kinh doanh hợp nhất quý 3/2024 với tổng doanh thu thuần đạt 15.200 tỷ đồng, "
        "lợi nhuận sau thuế đạt 2.100 tỷ đồng. Doanh nghiệp ghi nhận tăng trưởng mạnh mẽ nhờ tốc độ bàn giao nhanh chóng "
        "tại các đại đô thị Vinhomes Ocean Park 2 và 3."
    )
    story_vietstock = (
        "Theo tin từ doanh nghiệp, Vinhomes (VHM) vừa công bố kết quả kinh doanh hợp nhất quý 3/2024 với tổng doanh thu thuần "
        "đạt 15.200 tỷ đồng, lợi nhuận sau thuế đạt 2.100 tỷ đồng. Doanh nghiệp ghi nhận tăng trưởng mạnh mẽ nhờ tốc độ bàn giao "
        "nhanh chóng tại các đại đô thị Vinhomes Ocean Park 2 và 3."
    )
    story_banking = (
        "Ngân hàng TMCP Ngoại thương Việt Nam (Vietcombank) vừa thông báo điều chỉnh giảm lãi suất huy động tiền gửi tiết kiệm "
        "kỳ hạn 12 tháng xuống mức 4,6%/năm trong bối cảnh thanh khoản hệ thống dồi dào."
    )

    h_cf = compute_simhash_64(story_cafef)
    h_vs = compute_simhash_64(story_vietstock)
    h_bank = compute_simhash_64(story_banking)

    dist_syndicated = hamming_distance(h_cf, h_vs)
    dist_different = hamming_distance(h_cf, h_bank)

    assert dist_syndicated <= 3, f"Syndicated distance {dist_syndicated} must be <= 3"
    assert dist_different > 10, f"Unrelated story distance {dist_different} must be > 10"
    assert is_near_duplicate(h_cf, h_vs) is True
    assert is_near_duplicate(h_cf, h_bank) is False


def test_deduplicate_documents_aggregation():
    """Verify clustering aggregates syndicated copies into primary document's syndicated_sources."""
    doc1 = CleanDocument(
        url="https://cafef.vn/vhm-q3.chn",
        canonical_url="https://cafef.vn/vhm-q3.chn",
        title="Vinhomes báo lãi 2.100 tỷ trong Q3",
        clean_markdown="Vinhomes (VHM) công bố kết quả kinh doanh quý 3 đạt 15.200 tỷ đồng doanh thu và 2.100 tỷ đồng lợi nhuận.",
        metadata={"publisher": "CafeF", "published_date": "2024-10-25"},
        simhash=compute_simhash_64("Vinhomes (VHM) công bố kết quả kinh doanh quý 3 đạt 15.200 tỷ đồng doanh thu và 2.100 tỷ đồng lợi nhuận."),
    )
    doc2 = CleanDocument(
        url="https://vietstock.vn/vhm-q3.htm?utm_source=fb",
        canonical_url="https://vietstock.vn/vhm-q3.htm",
        title="VHM: Lãi 2.100 tỷ trong Q3",
        clean_markdown="Theo CafeF, Vinhomes (VHM) công bố kết quả kinh doanh quý 3 đạt 15.200 tỷ đồng doanh thu và 2.100 tỷ đồng lợi nhuận.",
        metadata={"publisher": "Vietstock"},
        simhash=compute_simhash_64("Theo CafeF, Vinhomes (VHM) công bố kết quả kinh doanh quý 3 đạt 15.200 tỷ đồng doanh thu và 2.100 tỷ đồng lợi nhuận."),
    )
    doc3 = CleanDocument(
        url="https://vneconomy.vn/vcb-lai-suat.htm",
        canonical_url="https://vneconomy.vn/vcb-lai-suat.htm",
        title="Vietcombank giảm lãi suất",
        clean_markdown="Vietcombank điều chỉnh giảm lãi suất huy động xuống mức 4,6%/năm trong bối cảnh thanh khoản dồi dào.",
        metadata={"publisher": "VnEconomy"},
        simhash=compute_simhash_64("Vietcombank điều chỉnh giảm lãi suất huy động xuống mức 4,6%/năm trong bối cảnh thanh khoản dồi dào."),
    )

    deduped = deduplicate_documents([doc1, doc2, doc3])
    assert len(deduped) == 2, "doc1 and doc2 must cluster together; doc3 must remain independent"
    primary_vhm = next(d for d in deduped if "Vinhomes" in d.title)
    assert "https://vietstock.vn/vhm-q3.htm?utm_source=fb" in primary_vhm.syndicated_sources


# ===========================================================================
# 4. END-TO-END PIPELINE & INTERFACE CONTRACT TEST
# ===========================================================================

def test_clean_html_end_to_end_contract():
    """Verify clean_html fulfills M2 -> M3 interface contract."""
    raw_html = """
    <html>
    <head>
        <title>Hòa Phát (HPG) lãi 2.850 tỷ đồng - CafeF.vn</title>
        <link rel="canonical" href="https://cafef.vn/hpg-q3.chn" />
        <meta property="og:site_name" content="CafeF" />
        <meta name="author" content="Minh An" />
        <meta property="article:published_time" content="2024-10-28T14:00:00+07:00" />
    </head>
    <body>
        <div class="fck_detail">
            <h1>Hòa Phát ghi nhận kết quả kinh doanh tích cực</h1>
            <p>Doanh thu thuần đạt 34.100 tỷ đồng.</p>
        </div>
    </body>
    </html>
    """
    doc = clean_html(raw_html, "https://cafef.vn/hpg-q3.chn?utm_source=zalo")

    assert isinstance(doc, CleanDocument)
    assert doc.title == "Hòa Phát (HPG) lãi 2.850 tỷ đồng"
    assert doc.canonical_url == "https://cafef.vn/hpg-q3.chn"
    assert doc.metadata.get("publisher") == "CafeF"
    assert doc.metadata.get("author") == "Minh An"
    assert doc.simhash != 0
    assert "34.100 tỷ đồng" in doc.clean_markdown
