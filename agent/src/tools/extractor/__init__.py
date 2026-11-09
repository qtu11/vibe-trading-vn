"""Token-Optimized DOM Cleaning, High-Fidelity Markdown & Cross-Site Deduplication Engine.

Interface Contracts:
- M2 -> M3: CleanDocument(url, canonical_url, title, clean_markdown, metadata, syndicated_sources, simhash)
"""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field

from src.tools.extractor.dom_cleaner import DOMCleaner, DOMCleanResult
from src.tools.extractor.markdown_converter import MarkdownConverter, extract_metadata
from src.tools.extractor.deduplicator import (
    compute_exact_hash,
    compute_simhash_64,
    deduplicate_documents,
    hamming_distance,
    is_near_duplicate,
    normalize_canonical_url,
)


class CleanDocument(BaseModel):
    """Standard CleanDocument model (M2 -> M3 Interface Contract)."""
    url: str = ""
    canonical_url: str = ""
    title: str = ""
    clean_markdown: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    syndicated_sources: list[str] = Field(default_factory=list)
    simhash: int = 0


def clean_html(html_str: str, url: str = "") -> CleanDocument:
    """Execute the full 3-stage cleaning pipeline and convert to high-fidelity Markdown."""
    cleaner = DOMCleaner()
    dom_result = cleaner.clean(html_str, base_url=url)

    converter = MarkdownConverter()
    clean_md = converter.convert(dom_result.sanitized_html, metadata=dom_result.metadata)

    simhash_val = compute_simhash_64(clean_md)

    canonical_url = dom_result.canonical_url or normalize_canonical_url(url)

    return CleanDocument(
        url=url,
        canonical_url=canonical_url,
        title=dom_result.title,
        clean_markdown=clean_md,
        metadata=dom_result.metadata,
        syndicated_sources=[],
        simhash=simhash_val,
    )


__all__ = [
    "CleanDocument",
    "DOMCleaner",
    "DOMCleanResult",
    "MarkdownConverter",
    "clean_html",
    "compute_exact_hash",
    "compute_simhash_64",
    "deduplicate_documents",
    "extract_metadata",
    "hamming_distance",
    "is_near_duplicate",
    "normalize_canonical_url",
]
