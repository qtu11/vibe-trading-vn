"""Agent tool for rendering Vibe-Trading research drafts (DOCX, PDF and PPTX)."""

from __future__ import annotations

import json
from typing import Any

from src.agent.tools import BaseTool
from src.reporting.service import ReportJobError, ReportJobService


def _repair_hint(code: str) -> str:
    """Actionable next step for a failed export, keyed by error class."""
    return _REPAIR_HINTS.get(code, "")


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
                    "risk_factors, price_history, sources, data_as_of). market is one of VN_EQUITY, FOREX, "
                    "CRYPTO. Deep reports use analysis_sections with heading, subtitle, paragraphs (array of "
                    "plain strings), bullets (array of plain strings), source_ids and page_break_before=true "
                    "for each substantive chapter. Meet a requested page count with distinct evidenced "
                    "analysis, never repeated filler. Include dated price references, explicit valuation "
                    "assumptions and conditional buy/sell rules; never invent prices or erase "
                    "missing-evidence markers."
                    " Use financial_table for period/currency/unit/consolidation-aligned results. "
                    "financial_table.columns is an array of strings and rows use {label, values:[display strings], "
                    "cell_evidence:[{source_ids,evidence_kind}]} with one evidence entry per value. "
                    "valuation_scenarios is {title, rows:[{case, assumptions, target_price, upside, source_ids, "
                    "evidence_kind, methodology}], source_ids, evidence_kind, methodology}, not a bare array. Distinguish "
                    "consolidated profit from profit attributable to parent shareholders and reconcile earnings "
                    "to operating cash flow, capex and debt. Choose sector-appropriate valuation: for a holding "
                    "company explain ownership-weighted SOTP/NAV, minorities, net debt and double counting; "
                    "do not reuse bank ratios as its valuation model. Present facts, derived values, assumptions "
                    "and opinions separately. Use valuation_scenarios, risk_factors, catalysts and analysis_sections "
                    "for bear/base/bull drivers, sensitivities, counterarguments and missing inputs. A target needs "
                    "sourced inputs and reproducible math; otherwise omit it and leave the report unrated. "
                    "These research practices do not establish CFA certification or a universal page minimum."
                    " investment_theses/risk_factors are {title, body, source_ids}; body is required. "
                    " Every metric needs key, label, value, unit and as_of. "
                    "as_of must be known by data_as_of; put a future plan/forecast period in label/note, "
                    "not in the observation date. price_basis uses raw, split_adjusted or total_return; "
                    "get_market_data aliases split and split_dividend map to split_adjusted and total_return "
                    "respectively, never relabel dividend-adjusted history as split-only. Every key_stats/forecast_stats "
                    "value is a display STRING, not a number. price_history is an array of "
                    "{date, close, unit, price_basis, source_ids}. All facts require source_ids resolving to "
                    "Source.url collected this run. All numeric surfaces, including key_stats, forecast_stats, "
                    "table rows/cell_evidence, charts and paragraphs, require attribution. Each "
                    "NarrativeSection may include up to 2 charts (title, caption, categories of at most 8, "
                    "bars={label, unit, decimals, values, source_ids, evidence_kind=cited|observed}, optional "
                    "line or line_formula=ratio_to_bars_pct|share_of_total_pct with "
                    "line_numerator/line_base_index); chart numbers must come from collected sources and "
                    "derived lines are server-computed. Set evidence_kind=derived or assumption, methodology "
                    "and input_keys for calculated/analytical values. overview_evidence and "
                    "executive_summary_evidence attribute their prose. market_price requires as_of, "
                    "observed_at, unit and price_basis matching get_market_data.quote_observation; "
                    "historical adjusted closes cannot substitute for the latest raw trade."
                    " For a rated calculated target_price, methodology must be an arithmetic expression "
                    "using exactly its input_keys (for example eps * target_pe); declare chosen coefficients "
                    "as assumption metrics with methodology. The server recomputes the target before accepting a rating. "
                    "All derived financial/valuation metric formulas are checked even in unrated drafts, including "
                    "currency/display scale and percent ratios. For example methodology='operating_cash_flow - capex' "
                    "uses those exact input_keys. Prose-only methodologies remain unverified and return a warning. "
                    "On calculation errors, use field_errors.formula/inputs/expected_value to repair the payload; "
                    "on a source URL mismatch, compare field_errors.expected_url with the source content before retrying."
                ),
            },
            "formats": {
                "type": "array",
                "items": {"type": "string", "enum": ["docx", "pdf", "pptx"]},
                "default": ["docx", "pdf", "pptx"],
                "description": "Download formats. Defaults to DOCX, PDF and PPTX.",
            },
            "minimum_pages": {"type": "integer", "minimum": 1, "maximum": 2000, "default": 1,
                              "description": "Minimum verified PDF pages for this deep research report; defaults to 1. Only set a higher value (for example 24) when the user explicitly asked for a document of that depth. Insufficient evidenced analysis returns partial status, never padded text."},
        },
        "required": ["report"],
    }

    def execute(
        self,
        report: dict[str, Any] | str,
        formats: list[str] | None = None,
        minimum_pages: int = 1,
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
            # What counts as success, precisely.
            #
            # The depth gate measures how deep the analysis is. It says
            # nothing about whether the export happened. A 12-page report
            # against a 24-page target rendered fine and produced a valid
            # DOCX; reporting ok=False there told the model the export
            # failed, so it retried -- eight reasoning rounds burned to
            # produce a file that already existed. That is the loop in the
            # screenshot.
            #
            # A *missing format* is different: the caller asked for a PDF
            # and only got a DOCX, so the request was not met. That stays a
            # failure.
            depth_shortfall = (
                isinstance(job.get("error"), dict)
                and job["error"].get("code") in {"INSUFFICIENT_REPORT_DEPTH", "PAGE_COUNT_UNAVAILABLE"}
            )
            missing_format = (
                isinstance(job.get("error"), dict)
                and job["error"].get("code") == "PARTIAL_EXPORT"
            )
            delivered = bool(job.get("artifacts"))
            receipt = {
                "ok": job["status"] == "succeeded" or (delivered and depth_shortfall and not missing_format),
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
            if delivered and depth_shortfall:
                # Tell the model the file is ready AND what is thin about it,
                # so it can decide to deliver it or deepen it -- instead of
                # assuming the export failed.
                receipt["depth_shortfall"] = {
                    "pdf_pages": job.get("pdf_pages"),
                    "requested_minimum_pages": job.get("minimum_pages"),
                    "message": (
                        "Tài liệu đã được tạo và tải về được, nhưng số trang thấp hơn "
                        "mức tối thiểu đã yêu cầu. Báo cáo vẫn dùng được: gửi kèm "
                        "download_url cho người dùng và nói rõ độ sâu thực tế."
                    ),
                }
            return json.dumps(receipt, ensure_ascii=False)
        except ReportJobError as exc:
            payload: dict[str, Any] = {
                "ok": False,
                "error_code": exc.code,
                "message": exc.message,
            }
            hint = _repair_hint(exc.code)
            if hint:
                payload["hint"] = hint
            # The stalled run in the screenshot burned eight full reasoning
            # rounds on this one call. A prose hint was not enough: the model
            # still had to guess *which* field and still had to re-derive the
            # whole payload from scratch on every retry.
            #
            # ``field_errors`` names each place to look and the change to
            # make; ``accepted_report`` hands back the payload the server
            # already normalised, so a retry is a diff rather than a rewrite.
            if exc.details:
                payload["field_errors"] = exc.details
            if exc.collected_sources:
                payload["collected_sources"] = exc.collected_sources
            if exc.normalization_warnings:
                payload["already_repaired"] = exc.normalization_warnings
            if exc.normalized_report is not None:
                payload["accepted_report"] = exc.normalized_report
            # Close the dead end the screenshot actually hit: unable to
            # export, the model tried to write the report JSON to a file with
            # ``edit_file report.json``. That produced no branded document and
            # failed too, costing another round.
            payload["do_not"] = (
                "Do not write the report to a file (write_file/edit_file) as a "
                "substitute for this call: a JSON or Markdown file is not the "
                "branded research document and will not satisfy the request."
            )
            return json.dumps(payload, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"ok": False, "error_code": "INTERNAL_ERROR", "message": str(exc)}, ensure_ascii=False)


#: What the model should change next time, per failure class. A bare error
#: code gave the model nothing to act on, so it re-sent the same report with
#: one field fixed and the loop continued.
_REPAIR_HINTS = {
    "SCHEMA_VALIDATION_FAILED": (
        "Sửa TẤT CẢ nhóm trong field_errors trong cùng một lần gửi, không chỉ nhóm đầu tiên. "
        "market phải là VN_EQUITY/FOREX/CRYPTO; mỗi metric cần key, label, value, unit, as_of; "
        "key_stats/forecast_stats.value phải là chuỗi; price_history là mảng các {date, close, unit, price_basis, source_ids}; "
        "mỗi metric có value đều cần as_of; investment_theses/risk_factors cần title + body; "
        "các đoạn văn cần source_ids khớp với sources. Giữ nguyên analysis_sections đã có; "
        "không xoá mục để né lỗi schema."
    ),
    "EVIDENCE_VALIDATION_FAILED": (
        "Đối chiếu từng field_errors với collected_sources (các URL công cụ đã đọc trong phiên này): "
        "dùng đúng expected_url/source_id, hoặc đọc thêm nguồn chứa số đó trước khi xuất. "
        "Sửa toàn bộ field_errors cùng lúc, giữ nguyên analysis_sections và chỉ thay số/nguồn sai; "
        "không xoá cả mục phân tích, không đoán URL và không đổi nhãn verified. "
        "Sửa accepted_report rồi gọi lại export_research_report; không thay bằng write_file PDF."
    ),
    "INVALID_PAYLOAD": "Kiểm tra lại cấu trúc JSON của report trước khi gửi lại.",
    "INVALID_FORMAT": "formats chỉ nhận docx, pdf, pptx.",
}
