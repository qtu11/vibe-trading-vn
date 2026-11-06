"""DCF and its assumptions are reachable over JSON through the existing tool."""

import asyncio
from copy import deepcopy
import json

import pytest

from src.quantlib.valuation.contracts import Assumption
from src.quantlib.valuation.dcf import run_dcf
from src.tools.quantlib_tool import QuantlibCallTool


def kwargs():
    return {
        "inputs": {
            "risk_free_rate": .04, "beta": 1.1, "equity_risk_premium": .06,
            "pretax_cost_of_debt": .08, "tax_rate": .2,
            "target_equity_weight": .8, "target_debt_weight": .2,
            "ebit": [120000000, 130000000], "depreciation_amortization": [10000000, 10000000],
            "capex": [15000000, 15000000], "delta_nwc": [5000000, 5000000],
            "terminal_growth": {"__assumption__": {"name": "terminal_growth", "value": .02, "basis": "Synthetic long-run scenario"}},
            "exit_multiple": {"__assumption__": {"name": "exit_multiple", "value": 8, "basis": "Synthetic exit scenario"}},
            "total_debt": 100000000, "cash_and_equivalents": 20000000,
            "minority_interest": 0, "preferred_equity": 0, "associate_investments": 0,
            "diluted_shares": 10000000,
        },
        "capital_structure_basis": "target", "discounting_convention": "year_end",
        "terminal_value_method": "perpetuity_growth",
    }


def test_json_dcf_matches_existing_model_and_preserves_assumption_basis():
    supplied = kwargs()
    expected = deepcopy(supplied)
    for name in ("terminal_growth", "exit_multiple"):
        expected["inputs"][name] = Assumption(**expected["inputs"][name]["__assumption__"])
    direct = run_dcf(**expected)
    result = json.loads(QuantlibCallTool().execute(action="call", module="valuation.dcf", function="run_dcf", kwargs=supplied))
    assert result["ok"], result
    assert result["result"]["value_per_share"] == pytest.approx(direct.value_per_share)
    assert result["result"]["terminal_value"]["terminal_growth"]["basis"] == "Synthetic long-run scenario"


def test_dcf_runs_through_fastmcp_with_same_input_contract(monkeypatch):
    import mcp_server
    from src.agent.tools import ToolRegistry

    registry = ToolRegistry()
    registry.register(QuantlibCallTool())
    monkeypatch.setattr(mcp_server, "_registry", registry)
    result = asyncio.run(mcp_server.mcp.call_tool("quantlib_call", {
        "action": "call", "module": "valuation.dcf", "function": "run_dcf", "kwargs": kwargs(),
    }))
    assert json.loads(result.content[0].text)["ok"] is True


@pytest.mark.parametrize("envelope", [
    {"name": "terminal_growth", "value": .02, "basis": ""},
    {"name": "terminal_growth", "value": True, "basis": "bad"},
    {"name": "terminal_growth", "value": float("nan"), "basis": "bad"},
    {"name": "terminal_growth", "value": float("inf"), "basis": "bad"},
    {"name": "terminal_growth", "value": 10**1000, "basis": "bad"},
    {"name": "terminal_growth", "value": .02, "basis": "ok", "module": "os"},
    "bad",
])
def test_invalid_assumption_envelopes_fail_closed(envelope):
    supplied = kwargs()
    supplied["inputs"]["terminal_growth"] = {"__assumption__": envelope}
    result = json.loads(QuantlibCallTool().execute(action="call", module="valuation.dcf", function="run_dcf", kwargs=supplied))
    assert result["ok"] is False
    assert "argument envelope" in result["error"]


def test_missing_input_is_not_replaced_by_a_default():
    supplied = kwargs()
    del supplied["inputs"]["tax_rate"]
    result = json.loads(QuantlibCallTool().execute(action="call", module="valuation.dcf", function="run_dcf", kwargs=supplied))
    assert result["ok"] is False
    assert "tax_rate" in result["error"]
