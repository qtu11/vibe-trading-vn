"""Deterministic company research from explicitly curated statement evidence."""

import asyncio
from copy import deepcopy
import json
from decimal import Decimal

import pytest

from backtest.loaders import local_loader
from src.tools.vietnam_research_tool import VietnamResearchTool


def filing(statement, start, end, facts, *, basis="standalone", period="quarter", **kwargs):
    return dict(
        statement=statement, period=period, period_start=start, period_end=end,
        period_basis=basis, consolidation="consolidated",
        published_at="2026-02-01T00:00:00Z", retrieved_at="2026-11-05T00:00:00Z",
        source_url="https://example.com/fictional-statement.pdf", document_sha256="a" * 64,
        locator=f"page 3, {statement}", revision="original",
        facts={name: {"value": None if value is None else str(value), "unit": "VND", "scale": 1000000}
               for name, value in facts.items()}, **kwargs,
    )


@pytest.fixture
def source(tmp_path, monkeypatch):
    path = tmp_path / "statements.json"
    config = tmp_path / "config.yaml"
    config.write_text(f"financial_statements:\n  - symbol: CASE.VN\n    path: {path.as_posix()}\n", encoding="utf-8")
    monkeypatch.setattr(local_loader, "_CONFIG_PATH", config)

    def save(rows):
        path.write_text(json.dumps(dict(schema_version=1, symbol="CASE.VN", venue="HOSE", records=rows)), encoding="utf-8")
    return save


def research(**kwargs):
    return json.loads(VietnamResearchTool().execute(code="CASE.VN", as_of="2026-03-01T00:00:00Z", **kwargs))


def periods(result):
    assert result["ok"], result
    return result["data"]["CASE.VN"]["periods"]


def test_unit_conversion_balance_and_cash_quality_have_lineage(source):
    source([
        filing("income", "2025-01-01", "2025-03-31", {"revenue": 200, "gross_profit": 80, "net_income": 100}),
        filing("cashflow", "2025-01-01", "2025-03-31", {"cfo": 60, "capex": 10}),
        filing("balance", "2024-12-31", "2024-12-31", {"total_assets": 1000, "total_liabilities": 600, "total_equity": 400}, basis="instant"),
        filing("balance", "2025-03-31", "2025-03-31", {"total_assets": 1000, "total_liabilities": 600, "total_equity": 400}, basis="instant"),
    ])
    row = next(row for row in periods(research()) if row["period_end"] == "2025-03-31")
    assert row["inputs"]["income.revenue"]["value"] == "200000000"
    assert row["metrics"]["balance_residual"]["value"] == "0"
    assert row["metrics"]["accruals"]["value"] == "0.04"
    assert row["metrics"]["cash_conversion"]["value"] == "0.6"
    assert row["metrics"]["free_cash_flow"]["value"] == "50000000"
    assert row["metrics"]["roe"]["value"] == "0.25"
    assert row["annualized"] is False
    refs = {e["id"] for e in row["evidence"]}
    assert set(row["inputs"]["income.revenue"]["evidence"]) <= refs
    assert row["evidence"][0]["locator"]


def test_ytd_quarters_and_annual_q4_do_not_sum_balance_sheets(source):
    rows = []
    for end, value, cadence in [("2025-03-31", 80, "quarter"), ("2025-06-30", 190, "quarter"),
                                ("2025-09-30", 330, "quarter"), ("2025-12-31", 470, "annual")]:
        rows.append(filing("income", "2025-01-01", end, {"revenue": value}, basis="year_to_date", period=cadence))
        rows.append(filing("balance", end, end, {"total_assets": value}, basis="instant", period=cadence))
    source(rows)
    payload = research()
    result = periods(payload)
    while payload["paging"]["next_offset"] is not None:
        payload = research(offset=payload["paging"]["next_offset"])
        result.extend(periods(payload))
    assert [(r["period_end"], r["inputs"]["income.revenue"]["value"]) for r in result] == [
        ("2025-12-31", "140000000"), ("2025-09-30", "140000000"),
        ("2025-06-30", "110000000"), ("2025-03-31", "80000000"),
    ]
    assert result[0]["inputs"]["balance.total_assets"]["value"] == "470000000"
    assert len(result[0]["inputs"]["income.revenue"]["evidence"]) == 2


@pytest.mark.parametrize("change", ["missing_previous", "different_revision", "different_scope", "missing_fact"])
def test_unsafe_ytd_subtraction_returns_unknown(source, change):
    first = filing("income", "2025-01-01", "2025-03-31", {"revenue": 80}, basis="year_to_date")
    second = filing("income", "2025-01-01", "2025-06-30", {"revenue": 190}, basis="year_to_date")
    if change == "different_revision":
        first["revision"] = "restated"
    if change == "different_scope":
        first["consolidation"] = "separate"
    if change == "missing_fact":
        first["facts"] = {"net_income": {"value": "1", "unit": "VND", "scale": 1}}
    source([second] if change == "missing_previous" else [first, second])
    row = next(row for row in periods(research()) if row["period_end"] == "2025-06-30")
    assert row["inputs"]["income.revenue"]["value"] is None
    assert row["inputs"]["income.revenue"]["reason"]
    if change == "different_revision":
        assert len(row["inputs"]["income.revenue"]["evidence"]) == 2


def test_wrong_currency_missing_zero_and_negative_values_stay_explicit(source):
    income = filing("income", "2025-01-01", "2025-03-31", {"revenue": 0, "net_income": -5, "gross_profit": None})
    income["facts"]["net_income"]["unit"] = "USD"
    source([income, filing("cashflow", "2025-01-01", "2025-03-31", {"cfo": -10, "capex": -2})])
    row = periods(research())[0]
    assert row["inputs"]["cashflow.cfo"]["value"] == "-10000000"
    assert row["inputs"]["income.net_income"]["value"] is None
    assert row["metrics"]["net_margin"]["value"] is None
    assert row["metrics"]["free_cash_flow"]["value"] is None
    assert row["metrics"]["free_cash_flow"]["reason"]


def test_restated_future_data_never_leaks_and_scope_is_selected(source):
    original = filing("income", "2025-01-01", "2025-03-31", {"revenue": 100})
    restated = deepcopy(original)
    restated.update(revision="restated", published_at="2026-04-01T00:00:00Z")
    restated["facts"]["revenue"]["value"] = "999"
    separate = deepcopy(original)
    separate.update(consolidation="separate")
    separate["facts"]["revenue"]["value"] = "12"
    source([original, restated, separate])
    assert periods(research())[0]["inputs"]["income.revenue"]["value"] == "100000000"
    assert periods(research(consolidation="separate"))[0]["inputs"]["income.revenue"]["value"] == "12000000"


def test_imbalance_is_reported_and_not_plugged(source):
    source([filing("balance", "2025-03-31", "2025-03-31", {
        "total_assets": 1000, "total_liabilities": 600, "total_equity": 390,
    }, basis="instant")])
    row = periods(research())[0]
    assert row["metrics"]["balance_residual"]["value"] == "10000000"
    assert row["checks"]["balance_sheet"] == "failed"
    assert row["inputs"]["balance.total_equity"]["value"] == "390000000"


def test_working_capital_uses_average_balances_and_actual_days(source):
    opening = {"accounts_receivable": 20, "inventories": 30, "accounts_payable": 10}
    closing = {"accounts_receivable": 40, "inventories": 50, "accounts_payable": 30}
    source([
        filing("income", "2025-01-01", "2025-03-31", {"revenue": 300, "cogs": 200}),
        filing("balance", "2024-12-31", "2024-12-31", opening, basis="instant"),
        filing("balance", "2025-03-31", "2025-03-31", closing, basis="instant"),
    ])
    row = periods(research())[0]
    assert row["metrics"]["dso"]["value"] == "9"
    assert row["metrics"]["dio"]["value"] == "18"
    assert row["metrics"]["dpo"]["value"] == "9"
    assert row["metrics"]["cash_conversion_cycle"]["value"] == "18"


def test_result_paging_and_registry_mcp_share_working_report(source, monkeypatch):
    import mcp_server
    from src.agent.tools import ToolRegistry

    source([filing("income", f"{year}-01-01", f"{year}-03-31", {"revenue": year}) for year in range(2010, 2026)])
    registry = ToolRegistry()
    registry.register(VietnamResearchTool())
    monkeypatch.setattr(mcp_server, "_registry", registry)
    output = asyncio.run(mcp_server.mcp.call_tool("vietnam_research", {"code": "CASE.VN", "as_of": "2026-03-01T00:00:00Z"}))
    payload = json.loads(output.content[0].text)
    seen = [r["period_end"] for r in periods(payload)]
    offset = payload["paging"]["next_offset"]
    while offset is not None:
        payload = research(offset=offset)
        seen.extend(r["period_end"] for r in periods(payload))
        offset = payload["paging"]["next_offset"]
    assert len(seen) == len(set(seen)) == 16
    assert payload["data"]["CASE.VN"]["verification_status"] == "user_supplied_unverified"


@pytest.mark.parametrize("kwargs", [{"period": "month"}, {"consolidation": "mixed"}, {"offset": -1}, {"offset": True}])
def test_invalid_research_arguments_fail_without_reading_config(kwargs, monkeypatch):
    monkeypatch.setattr(local_loader, "_load_config", lambda: pytest.fail("unexpected read"))
    assert research(**kwargs)["ok"] is False


def test_unsupported_stub_period_is_explicit(source):
    source([filing("income", "2025-02-01", "2025-03-31", {"revenue": 100})])
    result = research()
    assert result["ok"] is False
    assert "geometry" in result["error"]


def test_extreme_valid_magnitudes_cannot_hide_balance_residual(source):
    row = filing("balance", "2025-03-31", "2025-03-31", {
        "total_assets": "1e100", "total_liabilities": "1e-100", "total_equity": "1e100",
    }, basis="instant")
    for fact in row["facts"].values():
        fact["scale"] = 1
    source([row])
    output = periods(research())[0]
    assert output["checks"]["balance_sheet"] == "failed"
    assert Decimal(output["metrics"]["balance_residual"]["value"]) == Decimal("-1e-100")
