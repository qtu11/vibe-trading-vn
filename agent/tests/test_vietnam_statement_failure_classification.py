"""A missing local source must not hide repairable input or evidence errors."""

import json

import pytest

from backtest.loaders import local_loader
from src.tools.financial_statements_tool import FinancialStatementsTool
from src.tools.vietnam_research_tool import VietnamResearchTool


@pytest.mark.parametrize("tool", [FinancialStatementsTool, VietnamResearchTool])
def test_missing_statement_source_points_to_original_filing_tools(monkeypatch, tool):
    monkeypatch.setattr(local_loader, "_load_config", lambda: {})
    result = json.loads(tool().execute(code="VIC.VN"))
    assert result["ok"] is False
    assert result["error_code"] == "statement_source_not_configured"
    assert "read_url" in result["remedy"]
    assert "read_document" in result["remedy"]


@pytest.mark.parametrize("tool", [FinancialStatementsTool, VietnamResearchTool])
@pytest.mark.parametrize("failure", ["cutoff", "json", "missing_file", "duplicate_config"])
def test_invalid_statement_input_is_not_a_missing_source(tmp_path, monkeypatch, tool, failure):
    path = tmp_path / "statements.json"
    path.write_text("invalid JSON", encoding="utf-8")
    entry = {"symbol": "VIC.VN", "path": str(path)}
    monkeypatch.setattr(local_loader, "_load_config", lambda: {
        "financial_statements": [entry, entry] if failure == "duplicate_config" else [entry],
    })
    if failure == "missing_file":
        path.unlink()
    args = {"code": "VIC.VN", "as_of": "bad"} if failure == "cutoff" else {"code": "VIC.VN"}
    result = json.loads(tool().execute(**args))
    assert result["ok"] is False
    assert result.get("error_code") != "statement_source_not_configured"
    assert "remedy" not in result
    assert str(tmp_path) not in json.dumps(result)


def test_research_arithmetic_error_is_not_a_missing_source(monkeypatch):
    import src.tools.vietnam_research_tool as module

    monkeypatch.setattr(module, "load_local_statement", lambda *args: {})

    def fail(*args):
        raise ArithmeticError("Incompatible calculation inputs")

    monkeypatch.setattr(module, "build_vietnam_research", fail)
    result = json.loads(VietnamResearchTool().execute(code="VIC.VN"))
    assert result["ok"] is False
    assert result["error"] == "Incompatible calculation inputs"
    assert result.get("error_code") != "statement_source_not_configured"
    assert "remedy" not in result
