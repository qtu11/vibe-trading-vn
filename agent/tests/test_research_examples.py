"""The published synthetic examples must exercise actual local research callers."""

import json
from pathlib import Path

from backtest.loaders import local_loader
from src.tools.vietnam_research_tool import VietnamResearchTool
from src.tools.quantlib_tool import QuantlibCallTool
from src.trading.forex.walk_forward import WalkForwardRequest, walk_forward

EXAMPLES = Path(__file__).resolve().parents[2] / "docs/examples"


def test_documented_vn_company_example(tmp_path, monkeypatch):
    source = EXAMPLES / "vn-company-research.example.json"
    config = tmp_path / "config.yaml"
    config.write_text(f"financial_statements:\n  - symbol: CASE.VN\n    path: {source.as_posix()}\n", encoding="utf-8")
    monkeypatch.setattr(local_loader, "_CONFIG_PATH", config)
    result = json.loads(VietnamResearchTool().execute(code="CASE.VN", as_of="2025-08-01T00:00:00Z"))
    assert result["ok"], result
    latest = result["data"]["CASE.VN"]["periods"][0]
    assert latest["period_end"] == "2025-06-30"
    assert latest["inputs"]["income.revenue"]["value"] == "270000000"
    assert latest["metrics"]["free_cash_flow"]["value"] == "65000000"
    assert latest["checks"]["balance_sheet"] == "passed"


def test_documented_forex_example():
    request = WalkForwardRequest.model_validate_json((EXAMPLES / "forex-walk-forward.example.json").read_text(encoding="utf-8"))
    result = walk_forward(request)
    assert result["status"] == "ok", result
    assert len(result["folds"]) == 3
    assert all(fold["out_of_sample_metrics"]["trade_count"] > 0 for fold in result["folds"])


def test_documented_dcf_example():
    request = json.loads((EXAMPLES / "dcf-scenario.example.json").read_text(encoding="utf-8"))
    result = json.loads(QuantlibCallTool().execute(**request))
    assert result["ok"], result
    assert result["result"]["value_per_share"] > 0
