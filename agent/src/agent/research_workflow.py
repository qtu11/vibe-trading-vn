"""Server-owned completion checks for source-backed deep research."""

from __future__ import annotations

import math
import re
import unicodedata
from typing import Any

REVIEW_PRESET = "deep_research_review"
REVIEW_ROLES = ("source_analyst", "domain_analyst", "critical_reviewer", "research_editor")


def _plain(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower().replace("đ", "d"))
                   if not unicodedata.combining(c))


def requires_research_review(request: str) -> bool:
    """Keep quotes, conversions and code work out of the research team route."""
    text = _plain(request)
    if re.search(r"\b(source code|codebase|debug|sua code|lap trinh)\b", text):
        return False
    if re.search(r"\b(deep research|in.depth research|nghien cuu (?:chuyen )?sau)\b", text):
        return True
    # Vietnamese prompts often name the listing or the exchange instead of the
    # words "cổ phiếu"/"equity": "phân tích TCB trên sàn HOSE, xuất báo cáo".
    # A ticker/exchange is the same equity signal, but only alongside an
    # explicit analysis/report request -- a price lookup stays out.
    named_market = re.search(
        r"\b(hose|hnx|upcom|[a-z]{2,5}\.(?:vn|us|hk|sh|sz|bj))\b", text
    )
    analysis = re.search(
        r"\b(research report|analysis report|bao cao|phan tich|analy[sz]e|valuation|dinh gia)\b",
        text,
    )
    broad_research = re.search(r"\bresearch\b", text)
    equity = re.search(
        r"\b(equity|stock|co phieu|doanh nghiep|company|valuation|dinh gia|chung khoan)\b",
        text,
    )
    # "research the company culture" is not equity work. A bare "research"
    # therefore only counts when the prompt names a market asset or venue;
    # explicit analysis words still count with a generic company mention.
    market_asset = re.search(
        r"\b(equity|stock|co phieu|chung khoan|valuation|dinh gia)\b", text
    )
    return bool(
        (analysis and (equity or named_market))
        or (broad_research and (market_asset or named_market))
    )


def requested_export_formats(request: str) -> set[str]:
    text = re.sub(r"https?://\S+", "", _plain(request))
    if not re.search(r"\b(export|save|download|xuat|tao|create|generate|write|viet|ra file)\b", text):
        return set()
    return set(re.findall(r"\b(docx|pdf|pptx)\b", text))


def review_wait_windows() -> int:
    """Return how many ``run_swarm`` wait windows cover the whole review run.

    ``run_swarm`` blocks for at most ``SWARM_TIMEOUT`` seconds per call. The
    review preset runs four evidence-reading roles serially and each role has
    its own timeout plus retry budget, so a fixed resume count can abandon a
    run the runtime still considers healthy. Derive the window count from the
    preset that will actually execute (including a user override) and from the
    same layer deadline the runtime applies — ``timeout * (retries + 1)``,
    capped retry backoff, and the 60s layer buffer.

    The returned number includes the initial ``run_swarm`` call. Three
    windows (the previous fixed budget) are returned when the preset cannot be
    loaded; the run itself then fails with a clear preset error.
    """
    try:
        from src.config.accessor import get_env_config
        from src.swarm.presets import load_preset

        swarm = get_env_config().swarm
        preset = load_preset(REVIEW_PRESET)
        agents = {
            str(agent.get("id")): agent
            for agent in preset.get("agents", [])
            if isinstance(agent, dict)
        }
        total_seconds = 0.0
        for task in preset.get("tasks", []):
            if not isinstance(task, dict):
                continue
            agent = agents.get(str(task.get("agent_id")), {})
            timeout = max(1.0, float(agent.get("timeout_seconds") or 300))
            retries = max(0, int(agent.get("max_retries") or 0))
            total_seconds += (
                timeout * (retries + 1)
                + retries * float(swarm.swarm_worker_retry_max_delay_s)
                + 60.0
            )
        window = max(1, int(swarm.swarm_timeout))
        return max(2, math.ceil(total_seconds / window))
    except Exception:
        return 3


def completed_review(ledger: Any) -> dict[str, Any] | None:
    """A model's JSON verdict cannot substitute for runtime task receipts."""
    for receipt in reversed(ledger.swarm_run_receipts()):
        if receipt.get("preset") != REVIEW_PRESET or receipt.get("status") != "completed":
            continue
        tasks = {task.get("agent_id"): task for task in receipt.get("tasks", []) if isinstance(task, dict)}
        if all(tasks.get(role, {}).get("status") == "completed"
               and int(tasks[role].get("iterations") or 0) > 0
               and int(tasks[role].get("data_tool_calls") or 0) > 0 for role in REVIEW_ROLES):
            if ledger.sources:
                return receipt
    return None


def incomplete_documents(ledger: Any, urls: set[str]) -> list[dict[str, Any]]:
    from src.agent.grounding.sources import canonical_url
    from src.tools.source_documents import current_document_coverage, documents_for_run

    def url_key(value: str) -> str:
        try:
            return canonical_url(value)
        except ValueError:
            return value

    # Use the latest actual snapshot per URL; stale failed attempts do not poison a retry.
    latest = {}
    for doc in documents_for_run(ledger.run_dir):
        for key in ("url", "source_url", "source", "requested_url"):
            if doc.get(key):
                latest[url_key(doc[key])] = doc
    actual_sources = {url_key(source.url): source for source in ledger.sources if source.url}
    required = requires_research_review(ledger.user_message)
    gaps = []
    for url in sorted(urls):
        document = latest.get(url_key(url))
        if document is not None:
            coverage = current_document_coverage(document)
            if not coverage.get("complete"):
                gaps.append({"url": url, "coverage": coverage,
                             "full_text_path": document.get("full_text_path"),
                             "coverage_id": document.get("coverage_id")})
        elif required:
            source = actual_sources.get(url_key(url))
            if source is None or source.tool in {"web_search", "parallel_web_search", "get_stock_news", "get_research_reports", "read_url", "concurrent_scraper", "read_document"}:
                gaps.append({"url": url, "coverage": {"status": "blocked", "complete": False,
                             "extraction_complete": False, "text_delivery_complete": False,
                             "reason": "no_trusted_source_read"}})
    return gaps


def research_release_error(ledger: Any, *, content: str = "", report: dict | None = None) -> dict | None:
    """Apply the same review and cited-document boundary to chat and exports."""
    if ledger is None:
        return None
    required = requires_research_review(ledger.user_message)
    if required and completed_review(ledger) is None:
        return {"code": "RESEARCH_REVIEW_INCOMPLETE", "message": "Source analysis, domain analysis, critical review and editing must finish with actual evidence reads."}
    if report is not None:
        urls = {row["url"] for row in report.get("sources", []) if isinstance(row, dict) and isinstance(row.get("url"), str)}
    else:
        from src.agent.grounding.sources import source_ids_in
        ids = set(source_ids_in(content))
        urls = {source.url for source in ledger.sources if source.source_id in ids and source.url}
        urls.update(re.findall(r"https?://[^\s)>\]]+", content))
    if required and not urls:
        return {"code": "SOURCE_CITATIONS_REQUIRED", "message": "Cite the actual observed sources supporting the research; a generic completion statement is insufficient."}
    gaps = incomplete_documents(ledger, urls)
    if gaps:
        return {"code": "SOURCE_READ_INCOMPLETE", "message": "Read the remaining source chunks or omit the incomplete source and its unsupported claims.", "documents": gaps}
    return None
