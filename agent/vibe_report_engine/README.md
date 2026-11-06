# Vibe-Trading Report Engine — integration starter

Reusable Python DOCX/PDF export service for Vibe-Trading. AI agents generate a `ResearchReport` JSON; this package validates its evidence references and renders consistently branded artifacts. No LLM calls, market-data scraping or trading are performed by this starter.

## Features
- One schema for VN equities, Forex and Crypto, with market-specific content extensible.
- One brand token file controlling fonts, palette and templates.
- Native **editable Word content**: masthead, metrics, research thesis, charts, financial tables, research citations, footer/page number and disclosures.
- PDF is converted **from the same DOCX**, so the two formats share layout.
- A validation gate: source IDs must exist, production sources must be marked verified, production ratings require market_price + target_price and evidence. This checks metadata consistency, **not factual truth**.
- UUID job workspaces; no request-controlled filesystem destination; isolated LibreOffice profiles.
- Demo fixture contains intentionally simulated ABCXY prices, sources and valuation; explicitly **not financial advice**.

## Setup

Python 3.11+ and LibreOffice / `soffice` are required for PDF:

```bash
pip install -r requirements.txt
python demo.py
```

Files are created under `outputs/<job_id>/VIBE_Research_ABCXY_20261030.docx` and `.pdf`.

## Run API

```bash
# Linux/macOS:
export VIBE_REPORT_API_KEY="replace-with-a-strong-secret"
# Windows PowerShell:
# $env:VIBE_REPORT_API_KEY="replace-with-a-strong-secret"
uvicorn api:app --host 127.0.0.1 --port 8900
```

Example:

```bash
curl -X POST http://127.0.0.1:8900/api/v1/reports/render/pdf \
  -H 'Authorization: Bearer replace-with-a-strong-secret' \
  -H 'Content-Type: application/json' \
  --data-binary @examples/demo_report.json \
  -o vibe_example.pdf
```

DOCX: replace `/pdf` with `/docx` and output filename accordingly.

## Integrating into existing Vibe-Trading repo

Current published tree has `agent/api_server.py` and `agent/src/api/` route modules (verify local source before editing). Import `router` from this module in existing app, using the project's own authentication guard rather than copying its demo auth logic. Do not introduce an independent AI runtime.

Recommended folders (adjust to actual import packages):

```text
agent/src/reporting/
  schema.py
  brand.py
  renderer.py
  assets/vibe_logo.png
agent/src/api/report_routes.py
```

After the existing AgentLoop or Swarm finishes research:

```python
from pydantic import ValidationError
from reporting.schema import ResearchReport
from reporting.renderer import export_report

# `research_json` is emitted by the existing agents/tools under a structured JSON contract.
report = ResearchReport.model_validate(research_json)
artifact_paths = export_report(report, app_artifact_root)
# Persist paths + run_id + report schema version + snapshot ID in the existing run store.
# Return authorized download links / artifact IDs via existing run API.
```

For multiple users, run export in a dedicated work queue; retain the authenticated owner, TTL, limits, virus scan if files are user-supplied, font availability, cleanup and audit log.

## Production requirements not implemented in this starter
- Data acquisition, licensed VN equity data, PIT adjustments, revision awareness, market schedules, split/dividend basis, disclosure time and quote recency.
- Independent calculations for upside, valuations and financial consistency, stress testing and compliance review.
- Asynchronous export queue, retries, job status, object storage, signed URLs, tenant isolation and file lifecycle.
- Proper market-specific schema sections (Forex: broker/spread/slippage; Crypto: spot/perpetual, funding, venues), proper data licenses and full editorial QA.
- Approved official mascot/logo. `assets/vibe_logo.png` is a generated text wordmark **placeholder**; replace with official logo owned by Vibe-Trading.

## Automated tests

```bash
python -m pytest tests -q
```
