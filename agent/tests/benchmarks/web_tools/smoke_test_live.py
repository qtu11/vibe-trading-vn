import asyncio
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.tools.parallel_web_tools import ParallelWebSearchTool, ConcurrentScraperTool

print("=== 1. TEST LIVE PARALLEL WEB SEARCH ===")
search_tool = ParallelWebSearchTool()
search_json = search_tool.execute(query="VNM ket qua kinh doanh quy 3 nam 2024 Vinamilk", max_results=3)
search_res = json.loads(search_json)
print("Search status:", search_res.get("status"))
print("Found results:", search_res.get("results_count"))
print("Latency ms:", search_res.get("latency_ms"))

urls = []
for r in search_res.get("results", [])[:3]:
    src = r.get("source")
    title = r.get("title", "")[:60]
    url = r.get("url")
    print(f" - [{src}] {title}... -> {url}")
    urls.append(url)

if urls:
    print("\n=== 2. TEST CONCURRENT SCRAPER & SYNTHESIZER ===")
    scraper_tool = ConcurrentScraperTool()
    scrape_json = scraper_tool.execute(
        urls=urls,
        query="Doanh thu loi nhuan Vinamilk VNM quy 3 nam 2024",
        target_tickers=["VNM"],
        token_budget=1500,
        synthesize=True,
    )
    scrape_res = json.loads(scrape_json)
    print("Scrape status:", scrape_res.get("status"))
    print("Token Stats:", scrape_res.get("token_stats"))
    print("Reconciled Metrics Count:", len(scrape_res.get("reconciled_metrics", [])))
    print("\nSummary Markdown Preview:")
    print(scrape_res.get("summary_markdown", "")[:450])
