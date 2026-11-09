"""Data Contracts and Models for Multi-Source Synthesis and Grounding.

Module: M4 / Workstream 4 (Map-Reduce & Structured Synthesis Engine)
Defines the schema for extracted metrics, conflict resolution, and the
final unified SynthesizedResearchArtifact.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List, Optional, Union
from pydantic import BaseModel, Field

from src.tools.optimizer import PrunedDocument


class ExtractedMetric(BaseModel):
    """One atomic financial fact/metric extracted from a single source during the Map phase."""

    ticker: str = Field(default="", description="Target stock ticker symbol (e.g. HPG, VNM, AAPL)")
    metric_name: str = Field(description="Normalized financial metric name (e.g. Doanh thu thuần, Lợi nhuận sau thuế, EPS, P/E)")
    fiscal_period: str = Field(default="", description="Fiscal period or point in time (e.g. Q3/2024, 9T/2024, FY2023)")
    value: Union[float, int, str] = Field(description="Numerical or qualitative value extracted")
    unit: str = Field(default="", description="Reporting unit (e.g. tỷ đồng, %, đồng/cp, lần, USD)")
    source_id: str = Field(description="Stable source citation ID (e.g. S1, S2)")
    publisher_tier: int = Field(default=4, description="Credibility tier (1: Official, 2: Wire, 3: Research, 4: Media, 5: Social)")
    source_title: str = Field(default="", description="Title of the source publication")
    source_url: str = Field(default="", description="Canonical or original URL of the source")
    raw_snippet: str = Field(default="", description="Raw sentence or table row supporting this fact")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Confidence score of the extraction")


class ConflictResolution(BaseModel):
    """Reconciliation and conflict resolution outcome for a single metric across multiple sources."""

    metric_name: str = Field(description="Canonical metric name")
    fiscal_period: str = Field(default="", description="Fiscal period under evaluation")
    status: str = Field(
        description="Reconciliation status: 'concordant' (agreed), 'discrepancy' (conflicting), or 'single_source'"
    )
    canonical_value: Optional[Union[float, int, str]] = Field(
        default=None, description="The authoritative reconciled value (prioritizing higher-tier sources)"
    )
    canonical_source_id: Optional[str] = Field(
        default=None, description="The primary source ID chosen for the canonical value"
    )
    unit: str = Field(default="", description="Common measurement unit")
    all_reported_values: list[dict[str, Any]] = Field(
        default_factory=list,
        description="List of all reported values with source_id, value, and publisher_tier",
    )
    discrepancy_delta_pct: Optional[float] = Field(
        default=None, description="Percentage discrepancy delta between minimum and maximum reported values"
    )
    resolution_rationale: str = Field(
        default="", description="Deterministic rationale explaining how the conflict was resolved or tiered"
    )


class SynthesizedResearchArtifact(BaseModel):
    """The master deliverable artifact produced by the Map-Reduce synthesis engine.

    Adheres strictly to the token boundary (<2000 tokens) and the grounding gate
    specifications in `figures.py` and `sources.py`.
    """

    query: str = Field(description="Original user/agent research query")
    target_tickers: list[str] = Field(default_factory=list, description="List of ticker symbols analyzed")
    executive_summary: str = Field(
        description="Publication-grade Markdown summary (<400 words) with grounded citations [S1], [S2]"
    )
    reconciled_metrics: list[ConflictResolution] = Field(
        default_factory=list, description="Reconciled metrics matrix with source corroboration"
    )
    raw_extracted_facts: list[ExtractedMetric] = Field(
        default_factory=list, description="All individual facts extracted from the Map phase"
    )
    sources_used: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Index of cited sources with source_id, title, url, domain, and publisher_tier",
    )
    token_stats: dict[str, Any] = Field(
        default_factory=dict,
        description="Efficiency statistics: raw_tokens, pruned_tokens, reduction_pct, latency_ms",
    )
    synthesis_timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="UTC ISO 8601 timestamp of synthesis generation",
    )

    def to_compact_markdown(self) -> str:
        """Render a publication-ready compact markdown block for direct AgentLoop consumption."""
        parts = [
            f"### Tổng hợp Nghiên cứu Tài chính: {', '.join(self.target_tickers) if self.target_tickers else self.query}",
            "",
            self.executive_summary.strip(),
            "",
        ]

        if self.reconciled_metrics:
            parts.append("#### Ma trận Đối chiếu Số liệu Đa nguồn")
            parts.append("| Chỉ tiêu | Kỳ | Giá trị Chuẩn hóa | Đơn vị | Nguồn Xác thực | Trạng thái | Ghi chú |")
            parts.append("| :--- | :--- | ---: | :--- | :--- | :---: | :--- |")
            for m in self.reconciled_metrics:
                src = f"[{m.canonical_source_id}]" if m.canonical_source_id else "-"
                status_icon = "Đồng thuận" if m.status == "concordant" else ("Bất đồng" if m.status == "discrepancy" else "1 Nguồn")
                val_str = f"{m.canonical_value:,.2f}" if isinstance(m.canonical_value, float) else str(m.canonical_value or "-")
                parts.append(f"| {m.metric_name} | {m.fiscal_period or '-'} | {val_str} | {m.unit} | {src} | {status_icon} | {m.resolution_rationale} |")
            parts.append("")

        if self.sources_used:
            parts.append("#### Nguồn Dữ liệu Trích dẫn")
            for s in self.sources_used:
                tier_label = f"Tier {s.get('tier', 4)}"
                parts.append(f"- **[{s.get('source_id')}]** {s.get('title', 'N/A')} ({tier_label}): {s.get('url', '')}")
            parts.append("")

        return "\n".join(parts)
