"""Write file tool: create or overwrite files in the workspace."""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

from src.agent.tool_context import current_grounding
from src.agent.tools import BaseTool
from src.tools.path_utils import allowed_write_roots
from src.tools.path_utils import resolve_safe_path
from src.tools.redaction import redact_internal_paths


def _requires_research_export(path: str, content: str) -> bool:
    ledger = current_grounding.get()
    if ledger is not None and any(
        failure.get("tool") == "export_research_report"
        for failure in getattr(ledger, "_tool_failures", ())
    ):
        return True
    request = getattr(ledger, "user_message", "")
    text = f"{request}\n{path}\n{content[:4000]}".casefold().replace("đ", "d")
    text = "".join(char for char in unicodedata.normalize("NFD", text) if not unicodedata.combining(char))
    text = text.replace("_", " ")
    # shortcut: text markers route standalone writes; use a typed document kind if more languages need routing.
    report = re.search(r"\b(?:research|report|analysis|bao cao|phan tich)\b|研究报告|研报", text)
    equity = re.search(r"\b(?:equity|stock|co phieu|hose|hnx|upcom|eps)\b|\bp/[eb]\b|股票|证券", text)
    return bool(report and equity)


class WriteFileTool(BaseTool):
    """Create or overwrite a workspace file, creating parent directories as needed."""

    name = "write_file"
    description = (
        "Write content to a file in the workspace or configured write roots. "
        "A .pdf path renders general Markdown/text documents; equity research reports must use "
        "export_research_report with structured evidence-bound content. Other paths write UTF-8 text. "
        "Creates parent directories automatically. Use the returned success/error as "
        "the authoritative outcome; include the returned download URL for PDF reports."
    )
    is_readonly = False
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path relative to run_dir"},
            "content": {"type": "string", "description": "Content to write"},
        },
        "required": ["path", "content"],
    }
    repeatable = True

    def execute(self, **kwargs: Any) -> str:
        """Write content to a file.

        Args:
            **kwargs: Must include path and content. Optional run_dir.

        Returns:
            JSON string with bytes_written or an error.
        """
        # DeepSeek-v4-pro (and some other models) sometimes emit write_file
        # with the path under an aliased key, or omit it entirely. Accept the
        # common aliases and return a correctable error instead of raising a
        # hard KeyError the model can't recover from.
        file_path = (
            kwargs.get("path")
            or kwargs.get("file_path")
            or kwargs.get("filepath")
            or kwargs.get("filename")
            or kwargs.get("file")
        )
        if not file_path:
            return json.dumps(
                {
                    "status": "error",
                    "error": "missing required argument 'path' (string): the file path relative to run_dir",
                },
                ensure_ascii=False,
            )
        content = next(
            (kwargs[key] for key in ("content", "text", "data") if kwargs.get(key) is not None),
            None,
        )
        if content is None:
            return json.dumps(
                {
                    "status": "error",
                    "error": "missing required argument 'content' (string): the file content to write",
                },
                ensure_ascii=False,
            )
        run_dir = kwargs.get("run_dir")

        try:
            resolved = resolve_safe_path(
                file_path=file_path,
                run_dir=run_dir,
                allowed_roots=allowed_write_roots(),
                purpose="write",
            )
        except ValueError as exc:
            return json.dumps(
                {
                    "status": "error",
                    "error": str(exc),
                },
                ensure_ascii=False,
            )

        try:
            if resolved.suffix.lower() == ".pdf" and _requires_research_export(str(file_path), content):
                return json.dumps({
                    "status": "error",
                    "error_code": "EQUITY_REPORT_REQUIRES_ENGINE",
                    "error": "Equity research PDFs must use export_research_report; the generic PDF writer cannot bypass its evidence validation or branded layout.",
                    "required_tool": "export_research_report",
                    "hint": "Repair the returned accepted_report/field_errors. Match source URLs to this run's collected sources, correct unsupported figures or mark missing inputs unavailable; never relabel sources as verified. Retry the structured export and deliver only its actual artifacts.",
                }, ensure_ascii=False)
            resolved.parent.mkdir(parents=True, exist_ok=True)
            artifact = {}
            if resolved.suffix.lower() == ".pdf":
                from src.tools.pdf_report import render_markdown_pdf
                from src.tools.report_artifacts import publish_pdf
                render_markdown_pdf(content, resolved)
                try:
                    artifact = publish_pdf(resolved)
                except OSError as exc:
                    # The requested file exists: a staging failure must not
                    # falsely report that the user's write was refused.
                    artifact = {"media_type": "application/pdf", "download_error": redact_internal_paths(str(exc))}
            else:
                resolved.write_text(content, encoding="utf-8")
            return json.dumps(
                {
                    "status": "ok",
                    "path": str(resolved),
                    "bytes_written": resolved.stat().st_size,
                    "requested_path": str(file_path),
                    **artifact,
                },
                ensure_ascii=False,
            )
        except Exception as exc:
            return json.dumps(
                {
                    "status": "error",
                    "error": redact_internal_paths(str(exc)),
                },
                ensure_ascii=False,
            )
