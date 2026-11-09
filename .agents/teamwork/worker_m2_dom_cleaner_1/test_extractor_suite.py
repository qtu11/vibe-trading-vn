"""Comprehensive Verification Test Suite for Extractor Engine (Worker M2).

Covers:
1. DOM Cleaning Pipeline (Stage 1, 2, 3)
2. High-Fidelity GFM Table Engine & Markdown Converter
3. 3-Tier Cross-Site Deduplication & Syndication Aggregation
4. End-to-End CleanDocument Interface Contract (M2 -> M3)
"""

import sys
import unittest
from typing import Any

# Ensure stdout handles UTF-8 for Vietnamese characters
sys.stdout.reconfigure(encoding="utf-8")

from agent.src.tools.extractor import (
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
from agent.src.tools.extractor.markdown_converter import is_financial_number


class TestDOMCleaner(unittest.TestCase):
    """Test 3-stage DOM Cleaning Pipeline."""

    def setUp(self) -> None:
        self.cleaner = DOMCleaner()

    def test_stage1_strip_technical_tags(self) -> None:
        """Verify technical tags (script, style, iframe, form, etc.) are stripped."""
        html = """
        <html>
        <head><title>Test Page</title></head>
        <body>
            <script>alert("malicious script");</script>
            <style>body { color: red; }</style>
            <noscript>JavaScript is disabled</noscript>
            <iframe src="https://ads.example.com"></iframe>
            <form action="/login"><input type="text"><button>Submit</button></form>
            <svg><circle cx="50" cy="50" r="40" /></svg>
            <canvas id="myCanvas"></canvas>
            <div class="fck_detail">
                <p>Doanh thu quý 3 đạt 15.200 tỷ đồng.</p>
            </div>
        </body>
        </html>
        """
        res = self.cleaner.clean(html, "https://cafef.vn/bctc")
        self.assertNotIn("malicious script", res.sanitized_html)
        self.assertNotIn("JavaScript is disabled", res.sanitized_html)
        self.assertNotIn("<script>", res.sanitized_html)
        self.assertNotIn("<style>", res.sanitized_html)
        self.assertNotIn("<iframe", res.sanitized_html)
        self.assertNotIn("<form", res.sanitized_html)
        self.assertNotIn("<input", res.sanitized_html)
        self.assertNotIn("<svg", res.sanitized_html)
        self.assertIn("15.200 tỷ đồng", res.sanitized_html)

    def test_stage1_strip_boilerplate_containers(self) -> None:
        """Verify headers, footers, navbars, ads, popups, and cookie consent are stripped."""
        html = """
        <html>
        <body>
            <header class="navbar">Menu items</header>
            <nav role="navigation"><a href="/">Home</a><a href="/news">News</a></nav>
            <aside class="sidebar">Recent comments</aside>
            <div class="ad-banner">Click here for discounts!</div>
            <div class="cookie-consent-modal">We use cookies</div>
            <div class="social-share-buttons">Share on Facebook</div>
            <div class="related-posts">Other articles you may like</div>
            <main>
                <article class="article-body">
                    <h2>Báo cáo kinh doanh</h2>
                    <p>Lợi nhuận sau thuế đạt 2.850 tỷ đồng, tăng trưởng 35,7% YoY.</p>
                </article>
            </main>
            <footer class="footer">Copyright 2026</footer>
        </body>
        </html>
        """
        res = self.cleaner.clean(html, "https://vietstock.vn/bctc")
        self.assertNotIn("Click here for discounts", res.sanitized_html)
        self.assertNotIn("We use cookies", res.sanitized_html)
        self.assertNotIn("Share on Facebook", res.sanitized_html)
        self.assertNotIn("Menu items", res.sanitized_html)
        self.assertNotIn("Copyright 2026", res.sanitized_html)
        self.assertIn("Lợi nhuận sau thuế đạt 2.850 tỷ đồng", res.sanitized_html)

    def test_stage2_main_content_extraction_text_density(self) -> None:
        """Verify extraction selects container with high text density and link density < 0.4."""
        html = """
        <html>
        <body>
            <div class="nav-links">
                <a href="/1">Link 1</a> <a href="/2">Link 2</a> <a href="/3">Link 3</a>
                <a href="/4">Link 4</a> <a href="/5">Link 5</a> <a href="/6">Link 6</a>
            </div>
            <div class="fck_detail">
                <h1>Vinhomes (VHM) công bố BCTC Q3/2024</h1>
                <p>Tổng doanh thu thuần hợp nhất quy đổi đạt 18.500 tỷ đồng.</p>
                <p>Lợi nhuận hợp nhất trước thuế đạt 3.450 tỷ đồng, tăng trưởng vượt bậc nhờ bàn giao các dự án lớn tại Ocean Park.</p>
            </div>
        </body>
        </html>
        """
        res = self.cleaner.clean(html, "https://cafef.vn/vhm-q3")
        self.assertNotIn("Link 1", res.sanitized_html)
        self.assertIn("Vinhomes (VHM) công bố BCTC Q3/2024", res.sanitized_html)
        self.assertIn("18.500 tỷ đồng", res.sanitized_html)
        self.assertLess(res.link_density, 0.4)

    def test_stage3_nh3_sanitization(self) -> None:
        """Verify nh3 strips inline styles and preserves permitted table attributes."""
        html = """
        <div class="fck_detail">
            <p style="color:red; font-size:18px;" onclick="doEvil()">Bản tin tài chính</p>
            <table class="my-table" style="border:1px solid #000;">
                <tr>
                    <th colspan="2" style="background:#eee;">Tiêu đề</th>
                </tr>
                <tr>
                    <td>Dữ liệu</td>
                    <td>100 tỷ</td>
                </tr>
            </table>
        </div>
        """
        res = self.cleaner.clean(html)
        # Verify inline style and event handler stripped
        self.assertNotIn('style="color:red', res.sanitized_html)
        self.assertNotIn("onclick", res.sanitized_html)
        self.assertNotIn('style="border', res.sanitized_html)
        # Verify colspan preserved
        self.assertIn('colspan="2"', res.sanitized_html)
        self.assertIn("100 tỷ", res.sanitized_html)


class TestMarkdownConverter(unittest.TestCase):
    """Test High-Fidelity Markdown and Table Engine."""

    def setUp(self) -> None:
        self.converter = MarkdownConverter()

    def test_financial_number_regex(self) -> None:
        """Test is_financial_number matches Vietnamese currency, percentages, and accounting numbers."""
        self.assertTrue(is_financial_number("15.200 tỷ"))
        self.assertTrue(is_financial_number("15.200 tỉ"))
        self.assertTrue(is_financial_number("1.234,5 triệu"))
        self.assertTrue(is_financial_number("+21,7%"))
        self.assertTrue(is_financial_number("-5.2%"))
        self.assertTrue(is_financial_number("(1.200)"))
        self.assertTrue(is_financial_number("2.850 VND"))
        self.assertTrue(is_financial_number("15.200"))
        self.assertTrue(is_financial_number("1.234,5"))
        self.assertTrue(is_financial_number("-"))
        self.assertTrue(is_financial_number("N/A"))

        # Non-numeric headers and periods
        self.assertFalse(is_financial_number("Doanh thu thuần"))
        self.assertFalse(is_financial_number("Lợi nhuận sau thuế"))
        self.assertFalse(is_financial_number("Q3/2024"))
        self.assertFalse(is_financial_number("YTD"))
        self.assertFalse(is_financial_number("YoY"))

    def test_gfm_table_alignment_and_colspan(self) -> None:
        """Test conversion of complex financial table with colspan/rowspan to aligned GFM."""
        html = """
        <table>
            <thead>
                <tr>
                    <th rowspan="2">Chỉ tiêu tài chính</th>
                    <th colspan="2">Năm 2024</th>
                    <th rowspan="2">Biến động (%)</th>
                </tr>
                <tr>
                    <th>Q2</th>
                    <th>Q3</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td>Doanh thu thuần</td>
                    <td>15.200 tỷ</td>
                    <td>18.500 tỷ</td>
                    <td>+21,7%</td>
                </tr>
                <tr>
                    <td>Lợi nhuận sau thuế</td>
                    <td>2.100 tỷ</td>
                    <td>2.850 tỷ</td>
                    <td>+35,7%</td>
                </tr>
            </tbody>
        </table>
        """
        md = self.converter.convert(html)
        lines = [line.strip() for line in md.splitlines() if line.strip()]

        # Verify separator line alignments: text left (:---), numbers right (---:)
        # Columns: 0=Text (:---), 1=Number (---:), 2=Number (---:), 3=Percentage (---:)
        sep_line = lines[1]
        self.assertEqual(sep_line, "|:---|---:|---:|---:|")

        # Verify all rows have 4 columns
        for line in lines:
            if line.startswith("|"):
                # Count pipes
                pipe_count = line.count("|")
                self.assertEqual(pipe_count, 5, f"Row violates 4-column layout: {line}")

        # Verify data values preserved
        self.assertIn("15.200 tỷ", md)
        self.assertIn("18.500 tỷ", md)
        self.assertIn("+21,7%", md)
        self.assertIn("Doanh thu thuần", md)
        self.assertIn("Năm 2024", md)

    def test_pipe_escaping_in_cells(self) -> None:
        """Test that pipe character '|' inside a cell is escaped as '\\|'."""
        html = "<table><tr><th>Metric | Sub</th></tr><tr><td>Value | Note</td></tr></table>"
        md = self.converter.convert(html)
        self.assertIn(r"Metric \| Sub", md)
        self.assertIn(r"Value \| Note", md)

    def test_metadata_extraction(self) -> None:
        """Test metadata extraction from OpenGraph and HTML head."""
        html = """
        <html>
        <head>
            <title>Vinhomes báo lãi kỷ lục - CafeF.vn</title>
            <link rel="canonical" href="https://cafef.vn/vhm-record-profit.chn?utm_source=fb" />
            <meta property="og:site_name" content="CafeF" />
            <meta name="author" content="Nguyễn Văn A" />
            <meta property="article:published_time" content="2024-10-25T08:30:00+07:00" />
            <meta property="og:description" content="Kết quả kinh doanh vượt dự phóng của SSI." />
        </head>
        <body>
            <div class="fck_detail"><p>Nội dung bài viết...</p></div>
        </body>
        </html>
        """
        meta = extract_metadata(html, "https://cafef.vn/vhm")
        self.assertEqual(meta["title"], "Vinhomes báo lãi kỷ lục")
        self.assertEqual(meta["publisher"], "CafeF")
        self.assertEqual(meta["author"], "Nguyễn Văn A")
        self.assertEqual(meta["published_date"], "2024-10-25T08:30:00+07:00")
        self.assertIn("vhm-record-profit.chn", meta["canonical_url"])


class TestDeduplicator(unittest.TestCase):
    """Test 3-Tier Cross-Site Deduplication Engine."""

    def test_tier1_canonical_url_normalization(self) -> None:
        """Test stripping of tracking params, fragments, and trailing slashes."""
        u1 = "https://cafef.vn/vhm-bctc-q3.chn?utm_source=facebook&utm_medium=cpc&fbclid=IwAR123#overview"
        u2 = "https://cafef.vn/vhm-bctc-q3.chn?utm_campaign=finance&session_id=xyz789"
        norm1 = normalize_canonical_url(u1)
        norm2 = normalize_canonical_url(u2)
        self.assertEqual(norm1, "https://cafef.vn/vhm-bctc-q3.chn")
        self.assertEqual(norm2, "https://cafef.vn/vhm-bctc-q3.chn")
        self.assertEqual(norm1, norm2)

    def test_tier2_exact_hash(self) -> None:
        """Test exact text SHA-256 hash ignores extra whitespace and case."""
        t1 = "Doanh thu quý 3 đạt 15.200 tỷ đồng."
        t2 = "  doanh thu   quý 3 đạt 15.200 tỷ đồng.\n\n"
        h1 = compute_exact_hash(t1)
        h2 = compute_exact_hash(t2)
        self.assertEqual(h1, h2)

    def test_tier3_simhash_syndication(self) -> None:
        """Test 64-bit SimHash groups syndicated articles (Hamming distance <= 3)."""
        # Story published on CafeF
        story_cafef = (
            "Vinhomes (VHM) vừa công bố kết quả kinh doanh hợp nhất quý 3/2024 với tổng doanh thu thuần đạt 15.200 tỷ đồng, "
            "lợi nhuận sau thuế đạt 2.100 tỷ đồng. Doanh nghiệp ghi nhận tăng trưởng mạnh mẽ nhờ tốc độ bàn giao nhanh chóng "
            "tại các đại đô thị Vinhomes Ocean Park 2 và 3."
        )
        # Syndicated story on Vietstock with minor attribution preamble
        story_vietstock = (
            "Theo tin từ doanh nghiệp, Vinhomes (VHM) vừa công bố kết quả kinh doanh hợp nhất quý 3/2024 với tổng doanh thu thuần "
            "đạt 15.200 tỷ đồng, lợi nhuận sau thuế đạt 2.100 tỷ đồng. Doanh nghiệp ghi nhận tăng trưởng mạnh mẽ nhờ tốc độ bàn giao "
            "nhanh chóng tại các đại đô thị Vinhomes Ocean Park 2 và 3."
        )
        # Completely distinct story about banking interest rates
        story_banking = (
            "Ngân hàng TMCP Ngoại thương Việt Nam (Vietcombank) vừa thông báo điều chỉnh giảm lãi suất huy động tiền gửi tiết kiệm "
            "kỳ hạn 12 tháng xuống mức 4,6%/năm trong bối cảnh thanh khoản hệ thống dồi dào."
        )

        h_cf = compute_simhash_64(story_cafef)
        h_vs = compute_simhash_64(story_vietstock)
        h_bank = compute_simhash_64(story_banking)

        dist_syndicated = hamming_distance(h_cf, h_vs)
        dist_different = hamming_distance(h_cf, h_bank)

        self.assertLessEqual(dist_syndicated, 3, f"Syndicated distance {dist_syndicated} should be <= 3")
        self.assertGreater(dist_different, 10, f"Unrelated story distance {dist_different} should be > 10")
        self.assertTrue(is_near_duplicate(h_cf, h_vs))
        self.assertFalse(is_near_duplicate(h_cf, h_bank))

    def test_deduplicate_documents_aggregation(self) -> None:
        """Test syndication aggregation keeps primary record and populates syndicated_sources."""
        doc1 = CleanDocument(
            url="https://cafef.vn/vhm-q3.chn",
            canonical_url="https://cafef.vn/vhm-q3.chn",
            title="Vinhomes báo lãi 2.100 tỷ trong Q3",
            clean_markdown="Vinhomes (VHM) công bố kết quả kinh doanh quý 3 đạt 15.200 tỷ đồng doanh thu và 2.100 tỷ đồng lợi nhuận.",
            metadata={"publisher": "CafeF", "published_date": "2024-10-25"},
            simhash=compute_simhash_64("Vinhomes (VHM) công bố kết quả kinh doanh quý 3 đạt 15.200 tỷ đồng doanh thu và 2.100 tỷ đồng lợi nhuận."),
        )
        # Syndicated copy on Vietstock
        doc2 = CleanDocument(
            url="https://vietstock.vn/vhm-q3.htm?utm_source=fb",
            canonical_url="https://vietstock.vn/vhm-q3.htm",
            title="VHM: Lãi 2.100 tỷ trong Q3",
            clean_markdown="Theo CafeF, Vinhomes (VHM) công bố kết quả kinh doanh quý 3 đạt 15.200 tỷ đồng doanh thu và 2.100 tỷ đồng lợi nhuận.",
            metadata={"publisher": "Vietstock"},
            simhash=compute_simhash_64("Theo CafeF, Vinhomes (VHM) công bố kết quả kinh doanh quý 3 đạt 15.200 tỷ đồng doanh thu và 2.100 tỷ đồng lợi nhuận."),
        )
        # Distinct banking article
        doc3 = CleanDocument(
            url="https://vneconomy.vn/vcb-lai-suat.htm",
            canonical_url="https://vneconomy.vn/vcb-lai-suat.htm",
            title="Vietcombank giảm lãi suất",
            clean_markdown="Vietcombank điều chỉnh giảm lãi suất huy động xuống mức 4,6%/năm trong bối cảnh thanh khoản dồi dào.",
            metadata={"publisher": "VnEconomy"},
            simhash=compute_simhash_64("Vietcombank điều chỉnh giảm lãi suất huy động xuống mức 4,6%/năm trong bối cảnh thanh khoản dồi dào."),
        )

        deduped = deduplicate_documents([doc1, doc2, doc3])

        # doc1 and doc2 should be clustered into 1, while doc3 remains independent
        self.assertEqual(len(deduped), 2)
        primary_vhm = next(d for d in deduped if "Vinhomes" in d.title)
        self.assertIn("https://vietstock.vn/vhm-q3.htm?utm_source=fb", primary_vhm.syndicated_sources)


class TestEndToEndCleanHtml(unittest.TestCase):
    """Test full end-to-end clean_html pipeline."""

    def test_clean_html_realistic_article(self) -> None:
        """Test clean_html on a realistic Vietnamese financial article with boilerplate and tables."""
        raw_html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Hòa Phát (HPG) lãi ròng 2.850 tỷ đồng trong Q3/2024 - CafeF.vn</title>
            <meta property="og:title" content="Hòa Phát (HPG) lãi ròng 2.850 tỷ đồng trong Q3/2024" />
            <meta property="og:site_name" content="CafeF" />
            <meta name="author" content="Minh An" />
            <meta property="article:published_time" content="2024-10-28T14:00:00+07:00" />
            <link rel="canonical" href="https://cafef.vn/hpg-bctc-q3-2024.chn" />
        </head>
        <body>
            <header class="navbar"><nav><a href="/">Trang chủ</a></nav></header>
            <div class="ad-banner">Quảng cáo độc quyền</div>
            <div class="fck_detail">
                <h1>Hòa Phát (HPG) ghi nhận kết quả kinh doanh tích cực quý 3/2024</h1>
                <p>Tập đoàn Hòa Phát vừa công bố kết quả sản xuất kinh doanh quý 3/2024 với nhiều chỉ tiêu vượt kế hoạch.</p>
                <table>
                    <thead>
                        <tr>
                            <th>Chỉ tiêu</th>
                            <th>Q3/2023</th>
                            <th>Q3/2024</th>
                            <th>Tăng trưởng</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr>
                            <td>Sản lượng thép</td>
                            <td>1,8 triệu tấn</td>
                            <td>2,1 triệu tấn</td>
                            <td>+16,7%</td>
                        </tr>
                        <tr>
                            <td>Doanh thu thuần</td>
                            <td>28.500 tỷ</td>
                            <td>34.100 tỷ</td>
                            <td>+19,6%</td>
                        </tr>
                        <tr>
                            <td>Lợi nhuận sau thuế</td>
                            <td>2.000 tỷ</td>
                            <td>2.850 tỷ</td>
                            <td>+42,5%</td>
                        </tr>
                    </tbody>
                </table>
                <p>Dự án Khu liên hợp Dung Quất 2 đang bám sát tiến độ đề ra.</p>
            </div>
            <footer class="footer"><p>Bản quyền thuộc CafeF</p></footer>
        </body>
        </html>
        """
        doc = clean_html(raw_html, "https://cafef.vn/hpg-bctc-q3-2024.chn?utm_source=zalo")

        self.assertIsInstance(doc, CleanDocument)
        self.assertEqual(doc.title, "Hòa Phát (HPG) lãi ròng 2.850 tỷ đồng trong Q3/2024")
        self.assertEqual(doc.canonical_url, "https://cafef.vn/hpg-bctc-q3-2024.chn")
        self.assertEqual(doc.metadata.get("publisher"), "CafeF")
        self.assertEqual(doc.metadata.get("author"), "Minh An")
        self.assertNotEqual(doc.simhash, 0)

        # Check Markdown content
        self.assertNotIn("Quảng cáo độc quyền", doc.clean_markdown)
        self.assertNotIn("Bản quyền thuộc CafeF", doc.clean_markdown)
        self.assertIn("Hòa Phát (HPG) ghi nhận kết quả kinh doanh tích cực quý 3/2024", doc.clean_markdown)
        self.assertIn("| Chỉ tiêu | Q3/2023 | Q3/2024 | Tăng trưởng |", doc.clean_markdown)
        self.assertIn("|:---|---:|---:|---:|", doc.clean_markdown)
        self.assertIn("34.100 tỷ", doc.clean_markdown)
        self.assertIn("+42,5%", doc.clean_markdown)


if __name__ == "__main__":
    unittest.main()
