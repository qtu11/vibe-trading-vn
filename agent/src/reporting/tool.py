"""Agent tool for rendering Vibe-Trading research drafts (DOCX + PDF)."""

from __future__ import annotations

import json
from typing import Any

from src.agent.tools import BaseTool
from src.reporting.service import ReportJobError, ReportJobService


class ExportResearchReportTool(BaseTool):
    """Render a Vibe-Trading branded research draft in DOCX and PDF formats."""

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
                ),
            },
            "formats": {
                "type": "array",
                "items": {"type": "string", "enum": ["docx", "pdf", "pptx"]},
                "default": ["docx", "pdf", "pptx"],
                "description": "Download formats. Defaults to DOCX, PDF and PPTX.",
            },
        },
        "required": ["report"],
    }

    def execute(self, report: dict[str, Any] | str, formats: list[str] | None = None) -> str:
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
            job = service.create_job(report_data=report_dict, formats=requested_formats, evidence_context=evidence_context)
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
                "error": job.get("error"),
                "fence": f'```report_artifact\n{{"type": "report_artifact", "job_id": "{job["job_id"]}"}}\n```',
            }
            return json.dumps(receipt, ensure_ascii=False)
        except ReportJobError as exc:
            return json.dumps({"ok": False, "error_code": exc.code, "message": exc.message}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"ok": False, "error_code": "INTERNAL_ERROR", "message": str(exc)}, ensure_ascii=False)
