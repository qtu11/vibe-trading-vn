# Research → Report handoff contract

## Input from the user

> Phân tích cổ phiếu FPT (HOSE) tại ngày 2026-11-06; xuất báo cáo PDF và DOCX theo thương hiệu Vibe-Trading.

## Processing policy (give to research agents)

1. Resolve `symbol`, market, listing venue, quote currency, price basis and research cutoff. If a symbol is ambiguous, search authoritative symbol listing before analysis.
2. Use existing market data tools and tools for company statements / filings. Capture `as_of`, `published_at`, `retrieved_at`, market timezone, units and actual source URI or immutable internal snapshot id. Never use LLM internal knowledge as a numeric primary source.
3. Calculate rates and valuation deterministically. For equities: forward EPS/P-E, DCF assumptions, risk-adjusted scenarios, price/target/upside on the same share and currency basis; adjustments for rights, splits, dividends and diluted shares. Market-price and valuation price timestamps must be explicit.
4. Each metric/claim needs `source_ids` matching `sources`. Explain invalid/missing evidence; `null` rather than imaginary numbers. Report approval and compliance gates should run before non-demo publication.
5. The final machine-readable output **must** validate against `ResearchReport` in `schema.py`; no Markdown, HTML, layout instructions, invented PDF paths, images or inline CSS in this JSON.
6. Call `export_report(report, root)` as a tool step. The AI should not manually rewrite Word/PDF styles. Register downloadable file IDs with authorized existing run artifact service. Do not trade automatically.

## Export tool signature

```python
from pathlib import Path
from pydantic import ValidationError
from schema import ResearchReport
from renderer import export_report

def export_research_report_tool(
    structured_research: dict,
    authorized_artifact_root: Path,
):
    validated = ResearchReport.model_validate(structured_research)
    return export_report(validated, authorized_artifact_root, formats=("docx", "pdf"))
```

The function is a reference implementation, not a completed MCP registration. Inspect the repository's actual tool contract, authentication and artifact management before exposing it to agents.

## Frontend request contract

Research stage: existing `POST /.../run` etc. → structured validated research JSON. This example does not prescribe an existing endpoint name.

Export stage (standalone demo only):

```http
POST /api/v1/reports/render/pdf
Authorization: Bearer <VIBE_REPORT_API_KEY>
Content-Type: application/json

{ ... ResearchReport JSON ... }
```

For production, pass `run_id` + supported requested format and let the backend load the validated report from its private run store. Don't trust client-submitted assertions of `verified` provenance or expose all report artifacts by guessing a path.
