"""QVeris dataset and financial tool discovery search adapter."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from .base_engine import BaseSearchEngine, SearchResult

logger = logging.getLogger(__name__)


class QverisSearchEngine(BaseSearchEngine):
    """QVeris discovery engine for licensed financial datasets and tools."""

    def __init__(
        self,
        name: str = "qveris",
        weight: float = 1.1,
    ) -> None:
        super().__init__(name=name, weight=weight)

    async def is_available(self) -> bool:
        """Check if QVeris credentials exist in configuration."""
        try:
            from src.tools.qveris_tool import has_qveris_credentials
            return has_qveris_credentials()
        except Exception:
            return False

    def _sync_search(self, query: str, max_results: int) -> list[SearchResult]:
        """Perform synchronous QVeris search in worker thread."""
        try:
            from src.tools.qveris_tool import QVerisClient, has_qveris_credentials, load_qveris_config

            cfg = load_qveris_config()
            if not cfg.enabled and not has_qveris_credentials(cfg):
                logger.debug("QVeris is disabled or missing credentials.")
                return []

            client = QVerisClient(cfg)
            payload = client.search(query=query, limit=max_results)

            items = payload.get("tools") or payload.get("results") or []
            results: list[SearchResult] = []

            for item in items[:max_results]:
                tool_id = item.get("id") or item.get("tool_id") or ""
                name = item.get("name") or tool_id
                description = item.get("description") or item.get("summary") or ""
                provider = item.get("provider") or item.get("author") or "QVeris"
                url = item.get("url") or f"https://qveris.ai/tools/{tool_id}"

                snippet = f"[{provider}] {description}".strip()
                results.append(
                    SearchResult(
                        title=name,
                        url=url,
                        snippet=snippet,
                        source=self.name,
                        extra={
                            "tool_id": tool_id,
                            "provider": provider,
                            "pricing": item.get("pricing"),
                        },
                    )
                )

            return results
        except Exception as exc:
            logger.debug("QVeris search failed: %s", exc)
            return []

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """Search QVeris catalog asynchronously."""
        if not query or not query.strip():
            return []

        if not await self.is_available():
            return []

        return await asyncio.to_thread(self._sync_search, query, max_results)
