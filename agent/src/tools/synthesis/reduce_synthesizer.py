"""Reduce Synthesizer and Cross-Source Reconciliation Engine.

Module: M4 / Workstream 4 (Map-Reduce & Structured Synthesis Engine)
Aggregates mapped financial facts, corroborates numbers across sources,
resolves conflicts using SOURCE_POLICIES publisher tier hierarchy, and
generates a publication-grade Markdown synthesis under 400 words with
strict grounding citations [S1], [S2].
"""

from __future__ import annotations

import collections
from datetime import datetime, timezone
from typing import Any, List, Optional, Sequence, Union

from src.tools.synthesis.models import (
    ConflictResolution,
    ExtractedMetric,
    PrunedDocument,
    SynthesizedResearchArtifact,
)


class ReduceSynthesizer:
    """Multi-source reconciliation and synthesis engine."""

    def __init__(self, relative_tolerance: float = 0.015) -> None:
        """
        Args:
            relative_tolerance: Relative delta (1.5%) threshold below which two numbers are concordant.
        """
        self.relative_tolerance = relative_tolerance

    def reconcile_facts(self, facts: Sequence[ExtractedMetric]) -> list[ConflictResolution]:
        """Group and reconcile extracted facts across all sources."""
        if not facts:
            return []

        # Group by (ticker, metric_name, fiscal_period)
        grouped: dict[tuple[str, str, str], list[ExtractedMetric]] = collections.defaultdict(list)
        for f in facts:
            # Normalize metric name and period
            key = (f.ticker.upper(), f.metric_name, f.fiscal_period.upper())
            grouped[key].append(f)

        reconciled: list[ConflictResolution] = []

        for (ticker, metric_name, period), group in grouped.items():
            unit = group[0].unit

            # Deduplicate by (source_id, value)
            seen_source_values = set()
            unique_group: list[ExtractedMetric] = []
            for item in group:
                sv_key = (item.source_id, item.value)
                if sv_key not in seen_source_values:
                    seen_source_values.add(sv_key)
                    unique_group.append(item)

            # Sort by publisher tier ascending (1 is most authoritative), then by confidence descending
            unique_group.sort(key=lambda x: (x.publisher_tier, -x.confidence))

            all_values_meta = [
                {
                    "source_id": m.source_id,
                    "value": m.value,
                    "publisher_tier": m.publisher_tier,
                    "source_title": m.source_title,
                    "snippet": m.raw_snippet,
                }
                for m in unique_group
            ]

            if len(unique_group) == 1:
                reconciled.append(
                    ConflictResolution(
                        metric_name=f"{ticker} - {metric_name}" if ticker else metric_name,
                        fiscal_period=period,
                        status="single_source",
                        canonical_value=unique_group[0].value,
                        canonical_source_id=unique_group[0].source_id,
                        unit=unit,
                        all_reported_values=all_values_meta,
                        discrepancy_delta_pct=0.0,
                        resolution_rationale=f"Dữ liệu đơn nguồn trích xuất từ [{unique_group[0].source_id}] (Tier {unique_group[0].publisher_tier}).",
                    )
                )
                continue

            # Multiple sources reported this metric
            numeric_values: list[float] = []
            for item in unique_group:
                if isinstance(item.value, (int, float)):
                    numeric_values.append(float(item.value))

            is_concordant = True
            delta_pct = 0.0

            if len(numeric_values) >= 2:
                v_min = min(numeric_values)
                v_max = max(numeric_values)
                if v_max > 0:
                    delta_pct = round(((v_max - v_min) / v_max) * 100.0, 2)
                    if delta_pct > (self.relative_tolerance * 100.0):
                        is_concordant = False

            top_source = unique_group[0]

            if is_concordant:
                status = "concordant"
                src_list = ", ".join(f"[{m.source_id}]" for m in unique_group)
                rationale = f"Đồng thuận đa nguồn qua {src_list} (Độ lệch {delta_pct}% <= {self.relative_tolerance*100}%)."
            else:
                status = "discrepancy"
                competing = unique_group[1]
                rationale = (
                    f"Bất đồng số liệu ({delta_pct}%): Ưu tiên [{top_source.source_id}] (Tier {top_source.publisher_tier}) "
                    f"thay vì [{competing.source_id}] (Tier {competing.publisher_tier})."
                )

            reconciled.append(
                ConflictResolution(
                    metric_name=f"{ticker} - {metric_name}" if ticker else metric_name,
                    fiscal_period=period,
                    status=status,
                    canonical_value=top_source.value,
                    canonical_source_id=top_source.source_id,
                    unit=unit,
                    all_reported_values=all_values_meta,
                    discrepancy_delta_pct=delta_pct,
                    resolution_rationale=rationale,
                )
            )

        # Sort reconciled metrics alphabetically by metric name and period
        reconciled.sort(key=lambda x: (x.metric_name, x.fiscal_period))
        return reconciled

    def generate_executive_summary(
        self,
        query: str,
        target_tickers: list[str],
        reconciled_metrics: list[ConflictResolution],
        docs: Sequence[PrunedDocument],
    ) -> str:
        """Generate high-density, professional publication-grade Markdown summary (<400 words)."""
        ticker_label = ", ".join(target_tickers) if target_tickers else "doanh nghiệp mục tiêu"
        lines: list[str] = []

        # 1. Headline summary paragraph
        lines.append(
            f"Báo cáo tổng hợp số liệu tài chính đối chiếu đa nguồn cho {ticker_label} theo truy vấn '{query}'."
        )

        # 2. Key findings bullet points
        lines.append("")
        lines.append("**Các chỉ tiêu tài chính cốt lõi ghi nhận:**")

        highlight_count = 0
        for m in reconciled_metrics:
            if highlight_count >= 6:
                break
            val_str = f"{m.canonical_value:,.2f}" if isinstance(m.canonical_value, float) else str(m.canonical_value)
            period_str = f" kỳ {m.fiscal_period}" if m.fiscal_period else ""
            src_tag = f"[{m.canonical_source_id}]" if m.canonical_source_id else ""
            status_tag = ""
            if m.status == "discrepancy":
                status_tag = f" *(Bất đồng {m.discrepancy_delta_pct}% giữa các nguồn, ưu tiên {src_tag})*"
            elif m.status == "concordant":
                status_tag = f" *(Xác thực đa nguồn)*"

            lines.append(f"- **{m.metric_name}**{period_str}: **{val_str} {m.unit}** {src_tag}{status_tag}.")
            highlight_count += 1

        # 3. Contextual and strategic takeaways from top documents
        lines.append("")
        lines.append("**Đánh giá bối cảnh và triển vọng:**")
        noted_insights = 0
        for doc in docs:
            if noted_insights >= 3:
                break
            for chunk in doc.selected_chunks:
                # Find chunks with strategic or operational keywords
                content_lower = chunk.content.lower()
                if any(k in content_lower for k in ("triển vọng", "dự án", "kế hoạch", "biên lợi nhuận", "rủi ro", "thị phần", "công suất")):
                    clean_sent = chunk.content.strip().replace("\n", " ")
                    # Pick first 200 characters ending in punctuation
                    if len(clean_sent) > 200:
                        cut = clean_sent[:200].rfind(".")
                        clean_sent = clean_sent[:cut+1] if cut > 80 else clean_sent[:200] + "..."
                    lines.append(f"- {clean_sent} [{doc.source_id}]")
                    noted_insights += 1
                    break

        if not reconciled_metrics and not noted_insights:
            lines.append("- Dữ liệu từ các nguồn đã được làm sạch và lưu vết, không phát hiện mâu thuẫn trọng yếu.")

        return "\n".join(lines)

    def synthesize(
        self,
        query: str,
        docs: Sequence[PrunedDocument],
        facts: Sequence[ExtractedMetric],
        target_tickers: Optional[list[str]] = None,
        token_stats: Optional[dict[str, Any]] = None,
    ) -> SynthesizedResearchArtifact:
        """Run complete Reduce phase and create SynthesizedResearchArtifact."""
        active_tickers = target_tickers or []
        if not active_tickers:
            for f in facts:
                if f.ticker and f.ticker not in active_tickers:
                    active_tickers.append(f.ticker)

        reconciled = self.reconcile_facts(facts)
        summary = self.generate_executive_summary(
            query=query,
            target_tickers=active_tickers,
            reconciled_metrics=reconciled,
            docs=docs,
        )

        # Index sources used
        sources_used = [
            {
                "source_id": d.source_id,
                "title": d.title,
                "url": d.url,
                "tier": d.publisher_tier,
                "chunks_count": len(d.selected_chunks),
                "pruned_tokens": d.pruned_token_count,
            }
            for d in docs
        ]

        # Calculate or supplement token stats
        stats = token_stats or {}
        if "raw_tokens" not in stats:
            raw_t = sum(d.original_token_count for d in docs)
            pruned_t = sum(d.pruned_token_count for d in docs)
            ratio = (raw_t - pruned_t) / raw_t if raw_t > 0 else 0.0
            stats.update({
                "raw_tokens": raw_t,
                "pruned_tokens": pruned_t,
                "reduction_pct": round(ratio * 100.0, 2),
            })

        return SynthesizedResearchArtifact(
            query=query,
            target_tickers=active_tickers,
            executive_summary=summary,
            reconciled_metrics=reconciled,
            raw_extracted_facts=list(facts),
            sources_used=sources_used,
            token_stats=stats,
            synthesis_timestamp=datetime.now(timezone.utc).isoformat(),
        )
