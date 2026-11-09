"""Adaptive Token Budgeter and Narrative Order Preservation Engine.

Dynamically allocates context token budget based on AgentLoop compaction headroom
and query complexity, selects highest-salience chunks up to the budget, and
re-orders the selected chunks by their original document index to preserve
narrative coherence and chronological flow for LLM synthesis.
"""

from __future__ import annotations

import re
from typing import Any, List, Optional

from src.tools.optimizer.chunker import Chunk, count_tokens


# Common financial acronyms that should not be mistaken for stock tickers
NON_TICKER_ACRONYMS: frozenset[str] = frozenset({
    "EPS", "PE", "PB", "ROE", "ROA", "ROIC", "EBITDA", "EBIT", "CAGR",
    "YOY", "MOM", "QOQ", "YTD", "USD", "VND", "EUR", "GBP", "JPY", "CNY",
    "BPS", "DCF", "NAV", "IPO", "CEO", "CFO", "COO", "CTCK", "BCTC", "KQKD",
    "LNST", "LNTT", "DTT", "TNC", "GDP", "CPI", "FDI", "SBV", "FED", "SEC",
    "HOSE", "HNX", "UPCOM", "VSDC", "GSO", "SSC", "CP", "LLC", "JSC",
})


class AdaptiveBudgeter:
    """Calculates adaptive token budgets and selects chunks preserving narrative flow."""

    def __init__(
        self,
        b_min: int = 600,
        b_max: int = 2500,
        alpha: float = 0.05,
        default_headroom: int = 30000,
    ) -> None:
        self.b_min = b_min
        self.b_max = b_max
        self.alpha = alpha
        self.default_headroom = default_headroom

    def calculate_budget(
        self,
        query: str,
        headroom: Optional[int] = None,
        explicit_budget: Optional[int] = None,
        tickers: Optional[list[str]] = None,
    ) -> int:
        """Calculate dynamic tool token budget:

        B_tool = min(B_max, max(B_min, Headroom * alpha * C_query))
        """
        if explicit_budget is not None and explicit_budget > 0:
            return max(self.b_min, min(self.b_max, explicit_budget))

        hr = headroom if (headroom is not None and headroom > 0) else self.default_headroom

        # Determine query complexity coefficient C_query
        c_query = self._determine_complexity(query, tickers)

        raw_budget = int(hr * self.alpha * c_query)
        return max(self.b_min, min(self.b_max, raw_budget))

    def _determine_complexity(self, query: str, tickers: Optional[list[str]] = None) -> float:
        """Determine complexity coefficient C_query:

        - Comparative / multi-ticker query: 1.3 (B_tool ~ 1800 - 2500)
        - Single point lookup (short query, 1 ticker): 0.8 (B_tool ~ 600 - 1000)
        - Default general query: 1.0 (B_tool ~ 1500)
        """
        q_lower = query.lower()

        # Check for comparative indicators or multiple tickers
        comparative_keywords = (
            "so sánh", "so sanh", "compare", "comparison", "vs", "versus",
            "đối chiếu", "doi chieu", "toàn diện", "toan dien", "bảng xếp hạng",
        )
        is_comparative = any(kw in q_lower for kw in comparative_keywords)

        ticker_set: set[str] = set()
        if tickers:
            ticker_set.update(t.upper() for t in tickers if t and t.upper() not in NON_TICKER_ACRONYMS)
        matches = re.findall(r"\b[A-Z]{2,5}\b", query)
        for m in matches:
            if m.upper() not in NON_TICKER_ACRONYMS:
                ticker_set.add(m.upper())

        if is_comparative or len(ticker_set) >= 2:
            return 1.3

        # Check for single-point lookup
        words = q_lower.split()
        point_lookup_metrics = (
            "eps", "p/e", "pe", "p/b", "pb", "roe", "roa", "cổ tức", "co tuc",
            "giá mục tiêu", "gia muc tieu", "doanh thu", "lợi nhuận", "loi nhuan",
        )
        if len(words) <= 7 and any(m in q_lower for m in point_lookup_metrics):
            return 0.8

        return 1.0

    def prune_and_reorder(
        self,
        scored_chunks: list[Chunk],
        budget: int,
        source_id: str = "S1",
    ) -> list[Chunk]:
        """Filter positive-score chunks, select up to budget, and restore original document order.

        Guarantees:
        - Only chunks with score > 0 are eligible.
        - Accumulated tokens adhere to budget (at least 1 top chunk guaranteed if available).
        - Selected chunks are sorted by chunk.index ASCENDING (Narrative Order Preservation).
        - Source metadata header is attached.
        """
        if not scored_chunks:
            return []

        # 1. Filter out non-positive scores
        candidates = [c for c in scored_chunks if c.score > 0.0]
        if not candidates:
            # If all scores are 0, fallback to the top 2 initial chunks to avoid empty document
            candidates = sorted(scored_chunks, key=lambda c: c.index)[:2]

        # 2. Sort candidate chunks by BM25-FSB score descending
        ranked = sorted(candidates, key=lambda c: c.score, reverse=True)

        # 3. Accumulate up to budget
        selected: list[Chunk] = []
        total_tokens = 0

        for chunk in ranked:
            c_tok = chunk.token_count if chunk.token_count > 0 else count_tokens(chunk.content)
            if total_tokens + c_tok <= budget:
                selected.append(chunk)
                total_tokens += c_tok
            else:
                if not selected:
                    # Guarantee at least 1 top-scoring chunk is preserved
                    selected.append(chunk)
                    total_tokens += c_tok
                break

        # 4. Narrative Order Preservation: Sort by original document index ASCENDING
        selected.sort(key=lambda c: c.index)

        # 5. Attach Source & Section metadata tags
        for chunk in selected:
            chunk.metadata["source_id"] = source_id
            tag = f"[Source {source_id} | Chunk {chunk.index + 1} | {chunk.breadcrumb}]"
            chunk.metadata["source_tag"] = tag
            # If tag not already in content, prepend it
            if not chunk.content.startswith(f"[Source {source_id}"):
                # Strip any existing leading [Section: ...] header to avoid redundancy
                clean_body = re.sub(r"^\[Section:[^\]]+\]\s*", "", chunk.content).strip()
                chunk.content = f"{tag}\n\n{clean_body}"
                chunk.token_count = count_tokens(chunk.content)

        return selected
