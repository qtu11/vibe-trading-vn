"""Semantic Token Optimization and Adaptive Context Pruning Engine.

Module: M3 / Workstream 3 (Semantic Token Optimization & Adaptive Context Pruning)
Provides hierarchical structural chunking, BM25-FSB (Financial Salience Boosting)
scoring, and adaptive context budgeting with narrative order preservation,
reducing 75% to 90% of boilerplate/noise tokens while preserving 100% of
financial figures, tables, and reporting metrics.
"""

from __future__ import annotations

from typing import Any, List, Optional, Union
from pydantic import BaseModel, Field

from src.tools.optimizer.chunker import (
    Chunk,
    SemanticChunker,
    count_tokens,
    split_sentences,
)
from src.tools.optimizer.bm25_scorer import (
    BM25FSBScorer,
    tokenize_financial_text,
    extract_tickers_from_query,
    extract_periods_from_text,
)
from src.tools.optimizer.budgeter import (
    AdaptiveBudgeter,
    NON_TICKER_ACRONYMS,
)

# Contract Models matching PROJECT.md interface specifications
class CleanDocument(BaseModel):
    """M2 -> M3 Interface Contract: Clean Document representation."""

    url: str = Field(description="Original URL of the cleaned document")
    canonical_url: str = Field(default="", description="Normalized canonical URL")
    title: str = Field(default="", description="Extracted document title")
    clean_markdown: str = Field(default="", description="Sanitized Clean Markdown text")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Document metadata")
    syndicated_sources: list[str] = Field(default_factory=list, description="Near-duplicate syndicated URLs")
    simhash: int = Field(default=0, description="64-bit SimHash identifier")


class PrunedDocument(BaseModel):
    """M3 -> M4 Interface Contract: Pruned Document representation."""

    url: str = Field(description="URL of source document")
    title: str = Field(default="", description="Title of document")
    source_id: str = Field(default="S1", description="Grounding source identifier (S1, S2...)")
    publisher_tier: int = Field(default=4, description="Publisher credibility tier (1 to 5)")
    selected_chunks: list[Chunk] = Field(default_factory=list, description="Ordered high-salience chunks")
    original_token_count: int = Field(default=0, description="Original estimated token count")
    pruned_token_count: int = Field(default=0, description="Pruned token count after budget selection")
    pruning_ratio: float = Field(default=0.0, description="Token reduction ratio (0.0 to 1.0)")

    @property
    def combined_markdown(self) -> str:
        """Concatenate all selected chunks in narrative order."""
        return "\n\n".join(chunk.content for chunk in self.selected_chunks)


def _resolve_publisher_tier(url: str) -> int:
    """Resolve publisher tier (1-5) using project SOURCE_POLICIES when available."""
    if not url:
        return 4
    try:
        from src.agent.grounding.sources import policy_for_url, is_social_url
        if is_social_url(url):
            return 5
        policy = policy_for_url(url)
        if policy is not None and hasattr(policy, "tier"):
            return policy.tier
    except Exception:
        pass
    return 4


def prune_document(
    doc: Union[CleanDocument, dict[str, Any], Any],
    query: str,
    tickers: Optional[list[str]] = None,
    budget: Optional[int] = None,
    source_id: str = "S1",
    headroom: Optional[int] = None,
    chunker: Optional[SemanticChunker] = None,
    scorer: Optional[BM25FSBScorer] = None,
    budgeter: Optional[AdaptiveBudgeter] = None,
) -> PrunedDocument:
    """Prune a single document using structural chunking, BM25-FSB, and adaptive budgeting.

    Args:
        doc: CleanDocument instance, dictionary, or duck-typed document object.
        query: Research query string.
        tickers: Optional list of focus stock ticker symbols (e.g. ['HPG']).
        budget: Optional explicit token budget override (clamped to [600, 2500]).
        source_id: Grounding source identifier (e.g. 'S1', 'S2').
        headroom: Optional current compaction headroom tokens from AgentLoop.
        chunker: Optional custom SemanticChunker instance.
        scorer: Optional custom BM25FSBScorer instance.
        budgeter: Optional custom AdaptiveBudgeter instance.

    Returns:
        PrunedDocument containing only high-salience chunks in narrative order.
    """
    # 1. Normalize input document fields
    if isinstance(doc, dict):
        url = str(doc.get("url", ""))
        title = str(doc.get("title", ""))
        clean_markdown = str(doc.get("clean_markdown", ""))
    elif hasattr(doc, "clean_markdown"):
        url = getattr(doc, "url", "")
        title = getattr(doc, "title", "")
        clean_markdown = getattr(doc, "clean_markdown", "")
    else:
        url = ""
        title = ""
        clean_markdown = str(doc)

    original_token_count = count_tokens(clean_markdown)

    if not clean_markdown.strip():
        return PrunedDocument(
            url=url,
            title=title,
            source_id=source_id,
            publisher_tier=_resolve_publisher_tier(url),
            selected_chunks=[],
            original_token_count=0,
            pruned_token_count=0,
            pruning_ratio=0.0,
        )

    # 2. Structural & Semantic Chunking
    _chunker = chunker or SemanticChunker()
    chunks = _chunker.chunk(clean_markdown, source_title=title)

    if not chunks:
        return PrunedDocument(
            url=url,
            title=title,
            source_id=source_id,
            publisher_tier=_resolve_publisher_tier(url),
            selected_chunks=[],
            original_token_count=original_token_count,
            pruned_token_count=0,
            pruning_ratio=1.0 if original_token_count > 0 else 0.0,
        )

    # 3. BM25-FSB Scoring
    _scorer = scorer or BM25FSBScorer()
    scored_chunks = _scorer.score_chunks(
        chunks=chunks,
        query=query,
        tickers=tickers,
        discard_non_positive=False,
    )

    # 4. Adaptive Budget Allocation & Narrative Re-ordering
    _budgeter = budgeter or AdaptiveBudgeter()
    allocated_budget = _budgeter.calculate_budget(
        query=query,
        headroom=headroom,
        explicit_budget=budget,
        tickers=tickers,
    )

    selected_chunks = _budgeter.prune_and_reorder(
        scored_chunks=scored_chunks,
        budget=allocated_budget,
        source_id=source_id,
    )

    pruned_token_count = sum(c.token_count for c in selected_chunks)
    if original_token_count > 0:
        pruning_ratio = max(0.0, (original_token_count - pruned_token_count) / original_token_count)
    else:
        pruning_ratio = 0.0

    return PrunedDocument(
        url=url,
        title=title,
        source_id=source_id,
        publisher_tier=_resolve_publisher_tier(url),
        selected_chunks=selected_chunks,
        original_token_count=original_token_count,
        pruned_token_count=pruned_token_count,
        pruning_ratio=round(pruning_ratio, 4),
    )


def prune_documents(
    docs: list[Union[CleanDocument, dict[str, Any], Any]],
    query: str,
    tickers: Optional[list[str]] = None,
    total_budget: Optional[int] = None,
    headroom: Optional[int] = None,
) -> list[PrunedDocument]:
    """Batch prune multiple documents with fair budget distribution.

    Args:
        docs: List of CleanDocument objects or dictionaries.
        query: Research query string.
        tickers: Optional list of stock ticker symbols.
        total_budget: Optional total budget constraint across all documents.
        headroom: Optional AgentLoop token headroom.

    Returns:
        List of PrunedDocument instances labeled [S1, S2, ...].
    """
    if not docs:
        return []

    num_docs = len(docs)
    per_doc_budget: Optional[int] = None
    if total_budget is not None and total_budget > 0:
        per_doc_budget = max(600, total_budget // num_docs)

    results: list[PrunedDocument] = []
    for idx, doc in enumerate(docs):
        source_id = f"S{idx + 1}"
        pruned = prune_document(
            doc=doc,
            query=query,
            tickers=tickers,
            budget=per_doc_budget,
            source_id=source_id,
            headroom=headroom,
        )
        results.append(pruned)

    return results


__all__ = [
    "Chunk",
    "CleanDocument",
    "PrunedDocument",
    "SemanticChunker",
    "BM25FSBScorer",
    "AdaptiveBudgeter",
    "prune_document",
    "prune_documents",
    "count_tokens",
    "split_sentences",
    "tokenize_financial_text",
    "extract_tickers_from_query",
    "extract_periods_from_text",
    "NON_TICKER_ACRONYMS",
]


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    print("=== RUNNING SEMANTIC TOKEN PRUNER VERIFICATION SUITE ===")

    # Test 1: Sentence splitting boundary integrity
    s_text = "UBND TP. HCM phê duyệt dự án. Doanh thu tăng 15.4% YoY. Báo lãi 3.5 tỷ USD. Apple Inc. công bố kết quả."
    sents = split_sentences(s_text)
    assert len(sents) == 4, f"Sentence split count mismatch: {len(sents)}"
    assert "TP. HCM" in sents[0] and "15.4%" in sents[1] and "3.5 tỷ USD" in sents[2]
    print("[PASS] Test 1: Sentence splitting safeguards (abbreviations, percentages, decimals).")

    # Test 2: Atomic table preservation & header replication
    chunker = SemanticChunker(max_chunk_tokens=60)
    big_table = "| Chỉ tiêu | Q3/2023 | Q3/2024 |\n|:---|:---:|---:|\n" + "\n".join(
        [f"| Row {i} | {1000 + i} | {2000 + i} |" for i in range(20)]
    )
    t_chunks = chunker._chunk_table(big_table, breadcrumb="[Section: TableTest]", start_idx=0)
    assert len(t_chunks) > 1, "Big table should be partitioned"
    for tc in t_chunks:
        assert tc.is_table, "Partition must retain table flag"
        assert "| Chỉ tiêu | Q3/2023 | Q3/2024 |" in tc.content, "Header must be replicated"
        assert "|:---|:---:|---:|" in tc.content, "Delimiter must be replicated"
    print(f"[PASS] Test 2: Atomic table header replication across {len(t_chunks)} sub-chunks.")

    # Test 3: BM25-FSB scoring, bonuses, and boilerplate penalty
    scorer = BM25FSBScorer()
    sample_chunks = [
        Chunk(index=0, content="Chính sách bảo mật và điều khoản sử dụng CafeF.", raw_content="Chính sách bảo mật và điều khoản sử dụng CafeF.", token_count=15),
        Chunk(index=1, content="Tập đoàn Hòa Phát (HPG) đạt doanh thu thuần 34.100 tỷ đồng trong Q3/2024, lợi nhuận sau thuế đạt 3.022 tỷ đồng.", raw_content="Tập đoàn Hòa Phát (HPG) đạt doanh thu thuần 34.100 tỷ đồng trong Q3/2024, lợi nhuận sau thuế đạt 3.022 tỷ đồng.", token_count=35),
        Chunk(index=2, content="| Chỉ tiêu | Q3/2024 |\n|:---|---:|\n| Doanh thu | 34.100 tỷ |\n| Lợi nhuận | 3.022 tỷ |", raw_content="| Chỉ tiêu | Q3/2024 |\n|:---|---:|\n| Doanh thu | 34.100 tỷ |\n| Lợi nhuận | 3.022 tỷ |", token_count=25, is_table=True),
    ]
    scored = scorer.score_chunks(sample_chunks, query="Doanh thu lợi nhuận HPG Q3/2024", tickers=["HPG"], discard_non_positive=False)
    assert scored[0].score == 0.0, f"Boilerplate should have score 0, got {scored[0].score}"
    assert scored[1].score > 8.0, f"High-salience text should score > 8, got {scored[1].score}"
    assert scored[2].score > 6.0, f"Table should score > 6, got {scored[2].score}"
    print(f"[PASS] Test 3: BM25-FSB scoring (Chunk 1: {scored[1].score}, Table: {scored[2].score}, Boilerplate: {scored[0].score}).")

    # Test 4: Adaptive budget calculation
    budgeter = AdaptiveBudgeter()
    b_comp = budgeter.calculate_budget("So sánh kết quả kinh doanh HPG và NKG năm 2024")
    b_point = budgeter.calculate_budget("EPS HPG 2024")
    b_norm = budgeter.calculate_budget("Báo cáo ngành thép Việt Nam")
    assert b_comp == 1950, f"Expected 1950 for comparative, got {b_comp}"
    assert b_point == 1200, f"Expected 1200 for point lookup, got {b_point}"
    assert b_norm == 1500, f"Expected 1500 for normal, got {b_norm}"
    print(f"[PASS] Test 4: Adaptive budgeting (Comp: {b_comp}, Point: {b_point}, Normal: {b_norm}).")

    # Test 5: End-to-end token reduction (75% - 90%) with 100% table retention & narrative order
    art_parts = [
        "# Báo cáo chiến lược đầu tư Q3/2024\n## Kết quả HPG\nTập đoàn Hòa Phát (HPG) ghi nhận doanh thu 34.100 tỷ đồng, lợi nhuận sau thuế đạt 3.022 tỷ đồng trong Q3/2024.\n\n| Chỉ tiêu | Q3/2023 | Q3/2024 |\n|:---|:---:|---:|\n| Doanh thu | 28.700 tỷ | 34.100 tỷ |\n| Lợi nhuận | 2.000 tỷ | 3.022 tỷ |\n"
    ]
    for idx in range(12):
        art_parts.append(
            f"## Chuyên mục vĩ mô {idx}\nKinh tế quốc tế tiếp tục có nhiều biến động trước các quyết định lãi suất. "
            f"Thị trường tài chính toàn cầu thận trọng trước áp lực lạm phát và chuỗi cung ứng hàng hải số {idx}. "
            "Các chỉ số Dow Jones và S&P 500 ghi nhận những phiên điều chỉnh kỹ thuật đan xen."
        )
    art_parts.append("## Bản quyền\nChính sách bảo mật: Toàn bộ bản quyền thuộc về trang tin. Không sao chép khi chưa được phép.")
    big_doc = CleanDocument(
        url="https://hsx.vn/hpg-report-q3-2024.pdf",
        title="Báo cáo HPG Q3/2024",
        clean_markdown="\n\n".join(art_parts),
    )

    pruned = prune_document(
        doc=big_doc,
        query="Doanh thu lợi nhuận HPG Q3/2024",
        tickers=["HPG"],
        budget=650,
        source_id="S1",
    )

    print(f"Original tokens: {pruned.original_token_count}")
    print(f"Pruned tokens: {pruned.pruned_token_count}")
    print(f"Pruning ratio: {pruned.pruning_ratio * 100:.2f}%")
    print(f"Publisher tier: {pruned.publisher_tier} (HOSE -> Tier 1)")

    assert 0.75 <= pruned.pruning_ratio <= 0.90, f"Pruning ratio {pruned.pruning_ratio} outside 75-90%!"
    assert any(c.is_table for c in pruned.selected_chunks), "Financial table dropped!"
    assert pruned.publisher_tier == 1, f"Expected Tier 1 for hsx.vn, got {pruned.publisher_tier}"

    # Narrative order check
    indices = [c.index for c in pruned.selected_chunks]
    assert indices == sorted(indices), f"Narrative order violated: {indices}"
    print(f"[PASS] Test 5: End-to-end pruning (Ratio: {pruned.pruning_ratio * 100:.2f}%, Table preserved, Order: {indices}).")

    print("=== ALL VERIFICATION TESTS PASSED SUCCESSFULLY ===")

