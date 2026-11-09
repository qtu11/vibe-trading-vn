"""Multi-Source Synthesis and Grounding Package.

Module: M4 / Workstream 4 (Map-Reduce & Structured Synthesis Engine)
Coordinates parallel Map fact extraction and Reduce cross-source reconciliation.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional, Sequence

from src.tools.synthesis.models import (
    ConflictResolution,
    ExtractedMetric,
    PrunedDocument,
    SynthesizedResearchArtifact,
)
from src.tools.synthesis.map_extractor import (
    DeterministicRuleExtractor,
    MapExtractor,
    METRIC_CANONICAL_MAP,
)
from src.tools.synthesis.reduce_synthesizer import ReduceSynthesizer


async def synthesize_research(
    docs: Sequence[PrunedDocument],
    query: str,
    target_tickers: Optional[list[str]] = None,
    map_extractor: Optional[MapExtractor] = None,
    reduce_synthesizer: Optional[ReduceSynthesizer] = None,
    token_stats: Optional[dict[str, Any]] = None,
) -> SynthesizedResearchArtifact:
    """End-to-end Map-Reduce synthesis workflow across pruned documents.

    Args:
        docs: List of PrunedDocument instances from M3.
        query: Research query string.
        target_tickers: Optional focus stock ticker symbols.
        map_extractor: Optional MapExtractor instance.
        reduce_synthesizer: Optional ReduceSynthesizer instance.
        token_stats: Optional performance and token statistics dictionary.

    Returns:
        SynthesizedResearchArtifact adhering to the grounding gate and token budget.
    """
    _mapper = map_extractor or MapExtractor()
    _reducer = reduce_synthesizer or ReduceSynthesizer()

    # Step 1: Parallel Map extraction
    facts = await _mapper.extract_facts(
        docs=docs,
        query=query,
        target_tickers=target_tickers,
    )

    # Step 2: Reduce reconciliation & synthesis
    artifact = _reducer.synthesize(
        query=query,
        docs=docs,
        facts=facts,
        target_tickers=target_tickers,
        token_stats=token_stats,
    )

    return artifact


__all__ = [
    "ConflictResolution",
    "DeterministicRuleExtractor",
    "ExtractedMetric",
    "MapExtractor",
    "PrunedDocument",
    "ReduceSynthesizer",
    "SynthesizedResearchArtifact",
    "METRIC_CANONICAL_MAP",
    "synthesize_research",
]
