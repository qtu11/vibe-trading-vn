"""Comprehensive Test Suite for Semantic Token Optimization and Pruning Engine.

Module: M3 / Workstream 3 (Semantic Token Optimization & Adaptive Context Pruning)
Tests:
1. Sentence splitting safeguards (decimals, percentages, abbreviations, tickers).
2. Structural hierarchical chunking (H1-H4, breadcrumbs, code blocks, quotes).
3. Atomic table preservation and header replication across partitions.
4. Sliding window sentence chunking with ~15% overlap.
5. Bilingual financial tokenization and compound n-grams.
6. Ticker extraction and non-ticker acronym filtering.
7. BM25-FSB scoring, salience boosts (ticker +3, period +2.5, metric +2.0, table +1.5),
   and boilerplate penalty (-5.0).
8. Absence of ancestor breadcrumb leakage into BM25 scores.
9. Dynamic adaptive token budgeting (comparative 1.3, point lookup 0.8, normal 1.0).
10. Narrative order preservation (re-sorting chunks by original document index).
11. End-to-end token reduction (achieving 75% - 90% pruning) with 100% table and key
    fact retention.
12. Batch document pruning across multiple sources (S1, S2, ...).
"""

from __future__ import annotations

import pytest

from src.tools.optimizer import (
    Chunk,
    CleanDocument,
    PrunedDocument,
    SemanticChunker,
    BM25FSBScorer,
    AdaptiveBudgeter,
    prune_document,
    prune_documents,
    count_tokens,
    split_sentences,
    tokenize_financial_text,
    extract_tickers_from_query,
    extract_periods_from_text,
    NON_TICKER_ACRONYMS,
)


# ===========================================================================
# 1. SENTENCE SPLITTING SAFEGUARD TESTS
# ===========================================================================

def test_split_sentences_preserves_decimals_and_percentages():
    text = (
        "Doanh thu thuần quý 3 đạt 34.100 tỷ đồng, tăng trưởng 19.5% YoY. "
        "Lợi nhuận ròng đạt 3.022 tỷ đồng, tương đương mức tăng 51.2%. "
        "Biên lợi nhuận gộp cải thiện lên 13.8% so với 10.5% năm trước."
    )
    sentences = split_sentences(text)
    assert len(sentences) == 3
    assert "19.5% YoY" in sentences[0]
    assert "51.2%" in sentences[1]
    assert "13.8%" in sentences[2] and "10.5%" in sentences[2]


def test_split_sentences_preserves_abbreviations():
    text = (
        "UBND TP. HCM ban hành công văn mới gửi Ban quản lý khu kinh tế. "
        "Tập đoàn FPT Corp. và đối tác Apple Inc. cùng hợp tác phát triển AI. "
        "Theo TS. Nguyễn Văn A và PGS. Trần Văn B, thị trường đang hồi phục. "
        "Công ty Cổ phần Thép Hòa Phát Co., Ltd. đẩy mạnh xuất khẩu."
    )
    sentences = split_sentences(text)
    assert len(sentences) == 4
    assert "TP. HCM" in sentences[0]
    assert "Corp." in sentences[1] and "Inc." in sentences[1]
    assert "TS." in sentences[2] and "PGS." in sentences[2]
    assert "Co., Ltd." in sentences[3]


def test_split_sentences_preserves_currency_and_single_initials():
    text = (
        "Tỷ giá USD/VND giao dịch quanh mức 25.450 đồng. "
        "Chủ tịch H. D. Smith công bố kế hoạch đầu tư mới tại Việt Nam."
    )
    sentences = split_sentences(text)
    assert len(sentences) == 2
    assert "25.450 đồng" in sentences[0]
    assert "H. D. Smith" in sentences[1]


# ===========================================================================
# 2. STRUCTURAL CHUNKING & TABLE ATOMICITY TESTS
# ===========================================================================

def test_hierarchical_heading_breadcrumbs():
    markdown = """# Báo cáo Vĩ mô 2024
## Ngành Thép
### Triển vọng Hòa Phát HPG
Tập đoàn Hòa Phát đang dẫn đầu thị phần thép xây dựng tại Việt Nam với 38% thị phần.
### Triển vọng Hoa Sen HSG
Hoa Sen ghi nhận mức tăng trưởng xuất khẩu tôn mạ sang thị trường Mỹ và EU.
## Ngành Sữa
### Vinamilk VNM
Vinamilk tiếp tục duy trì biên lợi nhuận ròng ổn định quanh mức 15%.
"""
    chunker = SemanticChunker(target_chunk_tokens=100)
    chunks = chunker.chunk(markdown, source_title="Báo cáo Ngành")

    assert len(chunks) >= 3
    # Check breadcrumb structure
    hpg_chunks = [c for c in chunks if "Hòa Phát" in c.content]
    assert len(hpg_chunks) > 0
    assert "[Section: Báo cáo Ngành > Báo cáo Vĩ mô 2024 > Ngành Thép > Triển vọng Hòa Phát HPG]" in hpg_chunks[0].breadcrumb

    vnm_chunks = [c for c in chunks if "Vinamilk" in c.content]
    assert len(vnm_chunks) > 0
    assert "[Section: Báo cáo Ngành > Báo cáo Vĩ mô 2024 > Ngành Sữa > Vinamilk VNM]" in vnm_chunks[0].breadcrumb


def test_atomic_table_header_replication_when_oversized():
    # Build a table that exceeds max_chunk_tokens
    header = "| Kỳ báo cáo | Doanh thu | Lợi nhuận | Biên gộp |\n|:---|---:|---:|---:|\n"
    rows = [f"| Q{i % 4 + 1}/202{i // 4 + 1} | {20000 + i * 500} tỷ | {2000 + i * 100} tỷ | {12.0 + (i % 5) * 0.5}% |" for i in range(30)]
    big_table_markdown = header + "\n".join(rows)

    chunker = SemanticChunker(max_chunk_tokens=70)
    chunks = chunker.chunk(big_table_markdown, source_title="Bảng Tài Chính")

    assert len(chunks) > 1, "Large table must be partitioned"
    for c in chunks:
        assert c.is_table, "Every table partition must retain is_table=True"
        assert "| Kỳ báo cáo | Doanh thu | Lợi nhuận | Biên gộp |" in c.content, "Header must be replicated"
        assert "|:---|---:|---:|---:|" in c.content, "Header delimiter must be replicated"


def test_code_block_and_quote_atomic_preservation():
    markdown = """## Phân tích kỹ thuật
```python
def compute_rsi(prices, period=14):
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))
```
> Khuyến nghị mua đối với HPG với giá mục tiêu 35.000 đồng/cp dựa trên định giá DCF và P/E mục tiêu 14.5x.
"""
    chunker = SemanticChunker(max_chunk_tokens=200)
    chunks = chunker.chunk(markdown)

    types = [c.metadata.get("type") for c in chunks]
    assert "code" in types, "Code block must be preserved atomically"
    assert "quote" in types, "Blockquote must be preserved atomically"


# ===========================================================================
# 3. TOKENIZER & TICKER EXTRACTION TESTS
# ===========================================================================

def test_financial_tokenizer_compounds_and_tickers():
    text = "Tập đoàn Hòa Phát (HPG) có doanh thu thuần tăng 19% và lợi nhuận sau thuế đạt 3.022 tỷ đồng. Net income tăng 51%."
    tokens = tokenize_financial_text(text)

    # Compound phrases should be recognized with underscores
    assert "doanh_thu_thuần" in tokens
    assert "lợi_nhuận_sau_thuế" in tokens
    assert "net_income" in tokens
    # Uppercase stock ticker preserved
    assert "HPG" in tokens


def test_extract_tickers_filters_financial_acronyms():
    query = "So sánh EPS, P/E, EBITDA, ROE và KQKD của HPG và VNM trong năm 2024"
    tickers = extract_tickers_from_query(query)

    assert "HPG" in tickers
    assert "VNM" in tickers
    # Non-ticker acronyms must NOT be included
    for acronym in ["EPS", "PE", "EBITDA", "ROE", "KQKD"]:
        assert acronym not in tickers


def test_extract_periods_from_text():
    text = "Kết quả Q3/2024 và 9T2024 của doanh nghiệp tăng trưởng 15% YoY và 5% QoQ trong năm 2024."
    periods = extract_periods_from_text(text)
    assert any("q3" in p for p in periods)
    assert any("9t" in p for p in periods)
    assert any("yoy" in p for p in periods)
    assert any("qoq" in p for p in periods)


# ===========================================================================
# 4. BM25-FSB SCORING & LEAKAGE PREVENTION TESTS
# ===========================================================================

def test_bm25_salience_bonuses():
    scorer = BM25FSBScorer()
    sample_chunks = [
        Chunk(
            index=0,
            content="Liên hệ quảng cáo và điều khoản sử dụng báo chí CafeF.",
            raw_content="Liên hệ quảng cáo và điều khoản sử dụng báo chí CafeF.",
            token_count=15,
        ),
        Chunk(
            index=1,
            content="Tập đoàn Hòa Phát (HPG) ghi nhận doanh thu 34.100 tỷ đồng và lợi nhuận sau thuế đạt 3.022 tỷ đồng trong Q3/2024.",
            raw_content="Tập đoàn Hòa Phát (HPG) ghi nhận doanh thu 34.100 tỷ đồng và lợi nhuận sau thuế đạt 3.022 tỷ đồng trong Q3/2024.",
            token_count=35,
        ),
        Chunk(
            index=2,
            content="| Chỉ tiêu | Q3/2024 |\n|:---|---:|\n| Doanh thu thuần | 34.100 tỷ |\n| Lợi nhuận sau thuế | 3.022 tỷ |",
            raw_content="| Chỉ tiêu | Q3/2024 |\n|:---|---:|\n| Doanh thu thuần | 34.100 tỷ |\n| Lợi nhuận sau thuế | 3.022 tỷ |",
            token_count=25,
            is_table=True,
        ),
    ]

    scored = scorer.score_chunks(
        chunks=sample_chunks,
        query="doanh thu lợi nhuận HPG Q3/2024",
        tickers=["HPG"],
        discard_non_positive=False,
    )

    # Boilerplate chunk should receive score 0.0
    assert scored[0].score == 0.0
    assert scored[0].metadata.get("boilerplate_penalty") == 5.0

    # High salience text chunk receives ticker (+3), period (+2.5), metric (+2.0) bonuses
    assert scored[1].score > 8.0
    reasons_1 = scored[1].metadata.get("boost_reasons", [])
    assert any("ticker" in r for r in reasons_1)
    assert any("period" in r for r in reasons_1)
    assert any("metrics" in r for r in reasons_1)

    # Table chunk receives table (+1.5) bonus
    assert scored[2].score > 6.0
    reasons_2 = scored[2].metadata.get("boost_reasons", [])
    assert "table" in reasons_2


def test_no_ancestor_breadcrumb_leakage():
    """Ensure document title or top-level headings in breadcrumb do NOT cause noise chunks to score."""
    scorer = BM25FSBScorer()
    # A chunk with an ancestor breadcrumb containing HPG and Q3/2024, but body is pure macro text
    noise_chunk = Chunk(
        index=0,
        content="[Section: Báo cáo HPG Q3/2024 > Tổng quan Vĩ mô > Hoa Kỳ]\n\nChỉ số CPI tháng 9 tại Mỹ tăng 0.2% so với tháng trước, trong khi thị trường lao động duy trì trạng thái ổn định.",
        raw_content="Chỉ số CPI tháng 9 tại Mỹ tăng 0.2% so với tháng trước, trong khi thị trường lao động duy trì trạng thái ổn định.",
        breadcrumb="[Section: Báo cáo HPG Q3/2024 > Tổng quan Vĩ mô > Hoa Kỳ]",
        token_count=40,
    )

    scored = scorer.score_chunks(
        chunks=[noise_chunk],
        query="Doanh thu lợi nhuận HPG Q3/2024",
        tickers=["HPG"],
        discard_non_positive=False,
    )

    # Because HPG and Q3/2024 are only in the ancestor breadcrumb, the noise chunk MUST score 0.0
    assert scored[0].score == 0.0, f"Ancestor breadcrumb leaked into score! Got {scored[0].score}"


# ===========================================================================
# 5. ADAPTIVE BUDGETER & NARRATIVE ORDER TESTS
# ===========================================================================

def test_adaptive_budget_calculation():
    budgeter = AdaptiveBudgeter(b_min=600, b_max=2500, alpha=0.05, default_headroom=30000)

    # Comparative query -> C_query = 1.3 -> 30000 * 0.05 * 1.3 = 1950
    b_comp = budgeter.calculate_budget("So sánh kết quả kinh doanh HPG và NKG trong năm 2024")
    assert b_comp == 1950

    # Point lookup query -> C_query = 0.8 -> 30000 * 0.05 * 0.8 = 1200
    b_point = budgeter.calculate_budget("EPS HPG 2024")
    assert b_point == 1200

    # Normal query -> C_query = 1.0 -> 30000 * 0.05 * 1.0 = 1500
    b_norm = budgeter.calculate_budget("Báo cáo phân tích thị trường bất động sản")
    assert b_norm == 1500

    # Clamping checks
    b_explicit_low = budgeter.calculate_budget("test", explicit_budget=300)
    assert b_explicit_low == 600  # Clamped to b_min

    b_explicit_high = budgeter.calculate_budget("test", explicit_budget=5000)
    assert b_explicit_high == 2500  # Clamped to b_max


def test_narrative_order_preservation():
    budgeter = AdaptiveBudgeter()
    # Chunks created out of order by score
    chunks = [
        Chunk(index=0, content="Đoạn mở đầu giới thiệu bối cảnh.", raw_content="Đoạn mở đầu giới thiệu bối cảnh.", score=3.0, token_count=20),
        Chunk(index=1, content="Kết quả kinh doanh đột phá với doanh thu kỷ lục.", raw_content="Kết quả kinh doanh đột phá với doanh thu kỷ lục.", score=15.0, token_count=30),
        Chunk(index=2, content="Bảng tài chính chi tiết quý 3.", raw_content="Bảng tài chính chi tiết quý 3.", score=10.0, token_count=25),
        Chunk(index=3, content="Triển vọng và kế hoạch mở rộng nhà máy.", raw_content="Triển vọng và kế hoạch mở rộng nhà máy.", score=5.0, token_count=25),
    ]

    selected = budgeter.prune_and_reorder(chunks, budget=200, source_id="S1")
    indices = [c.index for c in selected]
    # Selected chunks MUST be sorted in ascending order of original index
    assert indices == [0, 1, 2, 3]
    # Tag must be attached
    assert all("[Source S1" in c.content for c in selected)


# ===========================================================================
# 6. QUANTITATIVE TOKEN PRUNING & FACT RETENTION (75% - 90%)
# ===========================================================================

def test_quantitative_token_pruning_and_table_retention():
    """Verify end-to-end token reduction between 75% and 90% without losing financial tables."""
    header_section = (
        "# Báo cáo chiến lược đầu tư Q3/2024\n"
        "## Kết quả HPG\n"
        "Tập đoàn Hòa Phát (HPG) ghi nhận doanh thu thuần 34.100 tỷ đồng, tăng 19% YoY. "
        "Lợi nhuận sau thuế đạt 3.022 tỷ đồng trong Q3/2024, tăng 51% YoY.\n\n"
        "| Chỉ tiêu tài chính | Q3/2023 | Q3/2024 | Tăng trưởng |\n"
        "|:---|:---:|:---:|---:|\n"
        "| Doanh thu thuần | 28.766 tỷ | 34.100 tỷ | +19% |\n"
        "| Lợi nhuận sau thuế | 2.000 tỷ | 3.022 tỷ | +51% |\n"
        "| Biên lợi nhuận gộp | 10.5% | 13.8% | +3.3% |\n"
    )

    macro_sections = []
    for idx in range(12):
        macro_sections.append(
            f"## Chuyên mục vĩ mô và quốc tế {idx}\n"
            f"Thị trường tài chính quốc tế ghi nhận nhiều chuyển động đa chiều trong kỳ số {idx}. "
            "Cục Dự trữ Liên bang Mỹ duy trì quan điểm thận trọng trong việc nới lỏng chính sách tiền tệ. "
            "Áp lực chuỗi cung ứng hàng hải toàn cầu và giá dầu thô Brent dao động trong biên độ hẹp. "
            "Thị trường chứng khoán khu vực châu Á ghi nhận dòng tiền phân hóa mạnh mẽ giữa các nhóm ngành."
        )

    boilerplate = (
        "## Điều khoản bản quyền & Bảo mật\n"
        "Chính sách bảo mật: Toàn bộ bản quyền thuộc về cơ quan báo chí. "
        "Mọi hành vi sao chép hay phân phối lại khi chưa có sự đồng ý bằng văn bản đều bị nghiêm cấm. "
        "Liên hệ quảng cáo và hợp tác truyền thông: contact@financialportal.vn."
    )

    full_markdown = header_section + "\n\n" + "\n\n".join(macro_sections) + "\n\n" + boilerplate

    doc = CleanDocument(
        url="https://hsx.vn/bctc-hpg-q3-2024.pdf",
        title="Báo cáo HPG Q3/2024",
        clean_markdown=full_markdown,
    )

    pruned = prune_document(
        doc=doc,
        query="Doanh thu lợi nhuận HPG Q3/2024 biên lợi nhuận gộp",
        tickers=["HPG"],
        budget=650,
        source_id="S1",
    )

    # 1. Pruning ratio check: must achieve 75% to 90%
    assert 0.75 <= pruned.pruning_ratio <= 0.90, (
        f"Pruning ratio {pruned.pruning_ratio * 100:.2f}% is outside required 75% - 90% range!"
    )

    # 2. Key facts and numbers retention check
    combined_text = pruned.combined_markdown
    assert "34.100" in combined_text, "Revenue figure lost!"
    assert "3.022" in combined_text, "Profit figure lost!"
    assert "13.8%" in combined_text, "Gross margin lost!"

    # 3. Financial table retention check
    assert any(c.is_table for c in pruned.selected_chunks), "Financial table dropped during pruning!"
    assert "| Doanh thu thuần |" in combined_text, "Table rows dropped!"

    # 4. Boilerplate exclusion check
    assert "Chính sách bảo mật" not in combined_text, "Boilerplate was not pruned!"
    assert "contact@financialportal.vn" not in combined_text, "Contact info was not pruned!"

    # 5. Narrative order check
    indices = [c.index for c in pruned.selected_chunks]
    assert indices == sorted(indices), f"Narrative order violated: {indices}"


# ===========================================================================
# 7. BATCH DOCUMENT PRUNING TESTS
# ===========================================================================

def test_prune_documents_batch():
    doc1 = CleanDocument(
        url="https://cafef.vn/hpg.chn",
        title="HPG Q3/2024",
        clean_markdown="# Kết quả HPG\nDoanh thu thuần HPG đạt 34.100 tỷ đồng và lợi nhuận sau thuế đạt 3.022 tỷ đồng.",
    )
    doc2 = CleanDocument(
        url="https://vietstock.vn/vnm.htm",
        title="VNM Q3/2024",
        clean_markdown="# Kết quả VNM\nVinamilk ghi nhận doanh thu 16.500 tỷ đồng và lợi nhuận sau thuế đạt 2.450 tỷ đồng.",
    )

    batch_pruned = prune_documents(
        docs=[doc1, doc2],
        query="doanh thu lợi nhuận HPG VNM",
        tickers=["HPG", "VNM"],
        total_budget=1600,
    )

    assert len(batch_pruned) == 2
    assert batch_pruned[0].source_id == "S1"
    assert batch_pruned[1].source_id == "S2"
    assert "34.100" in batch_pruned[0].combined_markdown
    assert "16.500" in batch_pruned[1].combined_markdown
