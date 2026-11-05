"""Local VN financials: reproducible, explicitly unverified, disclosure-time selection."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from backtest.loaders import local_loader
from src.tools.financial_statements_tool import FinancialStatementsTool


def record(**overrides):
    row = {
        "statement": "income", "period": "quarter",
        "period_start": "2025-01-01", "period_end": "2025-03-31",
        "period_basis": "standalone", "consolidation": "consolidated",
        "published_at": "2025-04-20T10:00:00+07:00",
        "retrieved_at": "2026-01-01T00:00:00Z",
        "source_url": "https://example.com/fictional-filing.pdf",
        "document_sha256": "a" * 64, "locator": "page 3, income table",
        "revision": "original",
        "facts": {
            "revenue": {"value": "9007199254740993.25", "unit": "VND", "scale": 1000000},
            "net_income": {"value": "-5.25", "unit": "VND", "scale": 1000000},
            "eps": {"value": None, "unit": "VND/share", "scale": 1},
        },
    }
    return dict(row, **overrides)


@pytest.fixture
def source(tmp_path, monkeypatch):
    path = tmp_path / "statements.json"
    config = tmp_path / "config.yaml"
    config.write_text(
        "financial_statements:\n  - symbol: VIC.VN\n    path: " + path.as_posix() + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(local_loader, "_CONFIG_PATH", config)

    def write(rows=None, **overrides):
        payload = dict(schema_version=1, symbol="VIC.VN", venue="HOSE", records=rows if rows is not None else [record()])
        payload.update(overrides)
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    write()
    return write


def execute(**kwargs):
    return json.loads(FinancialStatementsTool().execute(
        **dict(code="VIC.VN", statement="income", period="quarter", **kwargs)
    ))


def test_revision_selection_preserves_exact_facts_and_provenance(source):
    revised = record(revision="restated", published_at="2025-05-10T00:00:00Z")
    revised["facts"]["net_income"]["value"] = "-7.5"
    path = source([record(), revised])
    with patch("src.tools.financial_statements_tool.get_json", side_effect=AssertionError("network")):
        before = execute(as_of="2025-05-01T00:00:00Z")
        after = execute(as_of="2025-05-10T00:00:00Z")
    assert before["ok"] and after["ok"]
    result = before["data"]["VIC.VN"]
    row = result["periods"][0]
    assert before["market"] == "vn"
    assert before["source"] == "local_financial_statements"
    assert row["revision"] == "original"
    assert row["facts"]["revenue"]["value"] == "9007199254740993.25"
    assert row["facts"]["net_income"]["value"] == "-5.25"
    assert row["facts"]["eps"]["value"] is None
    assert row["facts"]["revenue"]["scale"] == 1000000
    assert row["retrieved_at"] > result["as_of"]  # historical reconstruction, not recorded replay
    assert result["source_file_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert result["verification_status"] == "user_supplied_unverified"
    assert "path" not in result
    assert after["data"]["VIC.VN"]["periods"][0]["revision"] == "restated"


def test_available_at_delays_visibility_and_no_future_default(source):
    source([record(available_at="2025-05-15T00:00:00Z"), record(
        period_start="2098-01-01", period_end="2098-03-31",
        published_at="2098-04-20T00:00:00Z", retrieved_at="2098-04-21T00:00:00Z",
    )])
    assert execute(as_of="2025-05-14T00:00:00Z")["paging"]["total"] == 0
    assert execute(as_of="2025-05-15T00:00:00Z")["paging"]["total"] == 1
    assert execute()["paging"]["total"] == 1


def test_scope_and_basis_are_not_merged(source):
    source([record(), record(consolidation="separate"), record(period_basis="year_to_date")])
    payload = execute(as_of="2025-05-01T00:00:00Z")
    rows = payload["data"]["VIC.VN"]["periods"]
    assert len(rows) == 3
    assert {(r["consolidation"], r["period_basis"]) for r in rows} == {
        ("consolidated", "standalone"), ("separate", "standalone"), ("consolidated", "year_to_date")
    }


def test_publication_local_date_and_cutoff_use_correct_timezones(source):
    source([record(published_at="2025-03-31T00:30:00+07:00")])
    assert execute(as_of="2025-03-30T17:29:59Z")["paging"]["total"] == 0
    assert execute(as_of="2025-03-30T17:30:00Z")["paging"]["total"] == 1


def test_local_periods_page_without_losing_history(source):
    source([record(period_start=f"{year}-01-01", period_end=f"{year}-03-31") for year in range(1980, 2025)])
    offset = 0
    dates = []
    while offset is not None:
        result = execute(offset=offset)
        dates.extend(row["REPORT_DATE"] for row in result["data"]["VIC.VN"]["periods"])
        offset = result["paging"]["next_offset"]
    assert len(dates) == len(set(dates)) == 45
    assert dates == sorted(dates, reverse=True)


@pytest.mark.parametrize("as_of", ["2025-05-01", "2025-05-01T00:00:00", "bad", 123])
def test_cutoff_must_be_a_timezone_aware_timestamp(source, as_of):
    assert execute(as_of=as_of)["ok"] is False


@pytest.mark.parametrize("field,value", [
    ("published_at", "2025-04-20"), ("retrieved_at", "bad"),
    ("available_at", "2025-01-01T00:00:00Z"), ("document_sha256", "bad"),
    ("source_url", "file:///secret"), ("source_url", "https://user:password@example.com/a"),
    ("locator", ""), ("revision", ""), ("period_start", "2025-04-01"),
    ("period_basis", "unknown"), ("consolidation", "mixed"),
    ("statement", "wrong"), ("period", "monthly"),
])
def test_invalid_metadata_fails_closed(source, field, value):
    source([record(**{field: value})])
    assert execute()["ok"] is False


@pytest.mark.parametrize("fact", [
    {"value": "NaN", "unit": "VND", "scale": 1},
    {"value": "Infinity", "unit": "VND", "scale": 1},
    {"value": True, "unit": "VND", "scale": 1},
    {"value": 1.25, "unit": "VND", "scale": 1},
    {"value": "1", "unit": "", "scale": 1},
    {"value": "1", "unit": "VND", "scale": 0},
    {"value": "1", "unit": "VND", "scale": True},
    {"value": "1", "unit": "VND"},
])
def test_invalid_fact_never_becomes_zero_or_float(source, fact):
    source([record(facts={"revenue": fact})])
    assert execute()["ok"] is False


def test_conflicting_revisions_at_same_time_fail(source):
    source([record(), record(revision="ambiguous")])
    assert execute()["ok"] is False


@pytest.mark.parametrize("overrides", [{"symbol": "OTHER.VN"}, {"venue": "NYSE"}, {"schema_version": True}])
def test_file_identity_must_match_config(source, overrides):
    source(**overrides)
    assert execute()["ok"] is False


def test_missing_config_does_not_fall_back_or_reveal_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(local_loader, "_CONFIG_PATH", tmp_path / "missing.yaml")
    with patch("src.tools.financial_statements_tool.get_json", side_effect=AssertionError("network")):
        result = execute()
    assert result["ok"] is False
    assert str(tmp_path) not in json.dumps(result)


def test_non_vn_cutoff_is_explicitly_unsupported():
    with patch("src.tools.financial_statements_tool.cik_for", side_effect=AssertionError("network")):
        result = json.loads(FinancialStatementsTool().execute(code="AAPL.US", as_of="2025-05-01T00:00:00Z"))
    assert result["ok"] is False
    assert "as_of" in result["error"]


def test_mcp_forwards_cutoff_to_existing_registered_tool(source, monkeypatch):
    import mcp_server
    from src.agent.tools import ToolRegistry

    registry = ToolRegistry()
    registry.register(FinancialStatementsTool())
    monkeypatch.setattr(mcp_server, "_registry", registry)
    response = asyncio.run(mcp_server.mcp.call_tool("get_financial_statements", {
        "code": "VIC.VN", "statement": "income", "period": "quarter", "as_of": "2025-05-01T00:00:00Z",
    }))
    result = json.loads(response.content[0].text)
    assert result["ok"] is True
    assert result["data"]["VIC.VN"]["as_of"] == "2025-05-01T00:00:00+00:00"


def test_duplicate_json_keys_are_rejected(source):
    path = source()
    path.write_text('{"schema_version": 1, "schema_version": 2}', encoding="utf-8")
    result = execute()
    assert result["ok"] is False
    assert "duplicate keys" in result["error"]


def test_large_file_and_single_record_fail_without_truncating_facts(source):
    path = source()
    path.write_bytes(b" " * 2_000_001)
    assert "2 MB" in execute()["error"]
    source([record(facts={f"field{i}": {"value": "1" * 80, "unit": "VND", "scale": 1} for i in range(100)})])
    assert "budget" in execute()["error"]


def test_invalid_config_and_missing_file_are_sanitized(source):
    path = source()
    path.unlink()
    result = execute()
    assert result["ok"] is False
    assert str(path) not in json.dumps(result)
    local_loader._CONFIG_PATH.write_text("financial_statements: [", encoding="utf-8")
    assert execute()["error"] == "Cannot read Data Bridge configuration"


@pytest.mark.parametrize("venue", ["HOSE", "HNX", "UPCOM"])
def test_balance_instant_and_declared_venue_are_retained(source, venue):
    source([record(statement="balance", period_basis="instant", period_start="2025-03-31")], venue=venue)
    result = json.loads(FinancialStatementsTool().execute(code="vic.vn", statement="balance", period="quarter"))
    assert result["ok"] is True
    assert result["data"]["vic.vn"]["venue"] == venue
    assert result["data"]["vic.vn"]["periods"][0]["period_basis"] == "instant"


def test_documented_example_is_readable(source):
    fixture = Path(__file__).resolve().parents[2] / "docs/examples/vn-financial-statements.example.json"
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    source(payload.pop("records"), **payload)
    assert execute(as_of="2025-05-01T00:00:00Z")["paging"]["total"] == 1
