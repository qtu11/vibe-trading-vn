"""Agent tool for rendering Vibe-Trading research drafts (DOCX, PDF and PPTX)."""

from __future__ import annotations

import json
from typing import Any

from src.agent.tools import BaseTool
from src.reporting.service import ReportJobError, ReportJobService


class ExportResearchReportTool(BaseTool):
    """Render the same evidence-bound research into all three document formats."""

    name = "export_research_report"
    is_readonly = False
    description = (
        "Render and export a professional Vibe-Trading branded research report as editable DOCX "
        "PDF and PPTX. Receives structured research JSON complying with the ResearchReport "
        "schema, executes deterministic document rendering without altering business figures, and registers "
        "downloadable artifacts."
    )
    parameters = {
        "type": "object",
        "properties": {
            "report": {
                "type": "object",
                "description": (
                    "Structured research JSON validating against ResearchReport schema (symbol, market, "
                    "exchange, executive_summary, financial_metrics, valuation_metrics, investment_theses, "
                    "risk_factors, price_history, sources, data_as_of). Deep reports use analysis_sections "
                    "with heading, subtitle, paragraphs, bullets, source_ids and page_break_before=true for "
                    "each substantive chapter. Meet a requested page count with distinct evidenced analysis, "
                    "never repeated filler. Include dated price references, explicit valuation assumptions and "
                    "conditional buy/sell rules; never invent prices or erase missing-evidence markers."
                    " All facts require source_ids resolving to Source.url collected this run. All numeric "
                    "surfaces, including key_stats, forecast_stats, table rows/cell_evidence, charts and "
                    "paragraphs, require attribution. Each NarrativeSection may include up to 2 charts "
                    "(title, caption, categories, bars={label, unit, decimals, values, source_ids, "
                    "evidence_kind=cited|observed}, optional line or line_formula=ratio_to_bars_pct|"
                    "share_of_total_pct with line_numerator/line_base_index); chart numbers must come from "
                    "collected sources and derived lines are server-computed. Set evidence_kind=derived or "
                    "assumption, methodology and input_keys for calculated/analytical values. overview_evidence and "
                    "executive_summary_evidence attribute their prose. market_price requires as_of, "
                    "observed_at, unit and price_basis matching get_market_data.quote_observation; "
                    "historical adjusted closes cannot substitute for the latest raw trade."
                    " For a rated calculated target_price, methodology must be an arithmetic expression "
                    "using exactly its input_keys (for example eps * target_pe); declare chosen coefficients "
                    "as assumption metrics with methodology. The server recomputes the target before accepting a rating."
                ),
            },
            "formats": {
                "type": "array",
                "items": {"type": "string", "enum": ["docx", "pdf", "pptx"]},
                "default": ["docx", "pdf", "pptx"],
                "description": "Download formats. Defaults to DOCX, PDF and PPTX.",
            },
            "minimum_pages": {"type": "integer", "minimum": 1, "maximum": 2000, "default": 24,
                              "description": "Minimum verified PDF pages for this deep research report; defaults to 24. Insufficient evidenced analysis returns partial status, never padded text."},
        },
        "required": ["report"],
    }

    def execute(
        self,
        report: dict[str, Any] | str,
        formats: list[str] | None = None,
        minimum_pages: int = 24,
        **kwargs: Any,
    ) -> str:
        # The agent loop normalizes every call by injecting the active ``run_dir``
        # (see ``_normalize_tool_run_dir``). That keyword is transport metadata,
        # not report input. A signature that rejected it made this tool fail on
        # *every* call, which silently pushed the agent back to the plain
        # Markdown PDF writer: a 7-page ReportLab dump instead of the branded
        # research document. Accept and ignore host-injected keywords.
        if isinstance(report, str):
            try:
                report_dict = json.loads(report)
            except Exception as exc:
                return json.dumps({"ok": False, "error": f"Invalid JSON string: {exc}"}, ensure_ascii=False)
        else:
            report_dict = report

        requested_formats = ["docx", "pdf", "pptx"] if formats is None else formats
        service = ReportJobService()

        try:
            from src.agent.tool_context import current_grounding
            from src.reporting.evidence import from_grounding_ledger

            ledger = current_grounding.get()
            evidence_context = from_grounding_ledger(ledger) if ledger is not None else None
            job = service.create_job(report_data=report_dict, formats=requested_formats, evidence_context=evidence_context, minimum_pages=minimum_pages)
            download_links = [
                {"format": art["filename"].split(".")[-1], "filename": art["filename"], "url": art["download_url"]}
                for art in job["artifacts"]
            ]
            receipt = {
                "ok": job["status"] == "succeeded",
                "job_id": job["job_id"],
                "status": job["status"],
                "publication_status": job["publication_status"],
                "artifacts": job["artifacts"],
                "download_links": download_links,
                "warnings": job.get("warnings", []),
                "minimum_pages": job.get("minimum_pages"),
                "pdf_pages": job.get("pdf_pages"),
                "error": job.get("error"),
                "fence": f'```report_artifact\n{{"type": "report_artifact", "job_id": "{job["job_id"]}"}}\n```',
            }
            return json.dumps(receipt, ensure_ascii=False)
        except ReportJobError as exc:
            return json.dumps({"ok": False, "error_code": exc.code, "message": exc.message}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"ok": False, "error_code": "INTERNAL_ERROR", "message": str(exc)}, ensure_ascii=False)
