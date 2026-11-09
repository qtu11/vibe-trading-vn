"""Base search engine interface and data contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SearchResult:
    """Standardized search result item across all search engines."""

    title: str
    url: str
    snippet: str
    source: str
    published_at: str | None = None
    score: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert SearchResult to standard dictionary."""
        data: dict[str, Any] = {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "source": self.source,
        }
        if self.published_at:
            data["published_at"] = self.published_at
        if self.score:
            data["score"] = round(self.score, 6)
        if self.extra:
            data["extra"] = self.extra
        return data


class BaseSearchEngine(ABC):
    """Abstract base class for all search engine adapters."""

    def __init__(self, name: str, weight: float = 1.0) -> None:
        self.name = name
        self.weight = max(0.1, float(weight))

    @abstractmethod
    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """Execute async search query and return ranked SearchResult items.

        Args:
            query: User search query string.
            max_results: Maximum number of results to fetch.

        Returns:
            List of SearchResult objects.
        """
        raise NotImplementedError

    async def is_available(self) -> bool:
        """Check if engine is configured and operational."""
        return True

    async def close(self) -> None:
        """Release underlying HTTP connections or resources."""
        pass

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(name='{self.name}', weight={self.weight})>"
