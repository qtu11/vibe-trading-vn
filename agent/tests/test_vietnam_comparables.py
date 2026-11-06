"""Evidence-bound VN equity comparisons: math, lookahead, missing data and paging."""

from copy import deepcopy
import asyncio
import json
from pathlib import Path

import pytest

from src.config.limits import TOOL_RESULT_LIMIT
from src.quantlib.valuation.comps import equity_multiple_set, multiple_distribution
from src.tools.vietnam_comparables import build_vietnam_comparables
from src.tools.vietnam_comparables_tool import VietnamComparablesTool


EXAMPLE = Path(__file__).resolve().parents[2] / "docs/examples/vn-comparables.example.json"


def supplied():
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def call(payload=None, **kwargs):
    return json.loads(VietnamComparablesTool().execute(payload=supplied() if payload is None else payload, **kwargs))


def test_example_uses_weighted_shares_for_earnings_and_current_shares_for_book():
    output = build_vietnam_comparables(supplied())
    assert output["target"]["eps_vnd"] == {"value": 2000, "reason": None}
    assert output["target"]["bvps_vnd"] == {"value": 10000, "reason": None}
    assert output["distribution"]["pe"]["median"] == 10
    assert output["distribution"]["pb"]["median"] == 2
    assert output["target"]["scenarios"]["pe"]["prices"]["median"] == 20000
    assert output["target"]["scenarios"]["pb"]["prices"]["median"] == 20000
    assert output["target"]["scenarios"]["pe"]["prices"]["p25"] == 15000
    assert output["historical_reconstruction"] is False
    assert output["price_age_seconds"] == 4500
    assert "forecast" in " ".join(output["limitations"])
    assert "historical percentile" in " ".join(output["limitations"])
    assert output["sector_mismatches"] == []


def test_quantlib_equity_only_adapter_reuses_distribution_without_ev_fabrication():
    peers = [equity_multiple_set("A", price_per_share=20, eps=2, book_value_per_share=10),
             equity_multiple_set("B", price_per_share=30, eps=3, book_value_per_share=None)]
    pe = multiple_distribution("pe", peers)
    pb = multiple_distribution("pb", peers)
    assert pe.median == 10
    assert pb.median == 2
    assert len(pb.excluded) == 1
    assert pb.excluded[0].denominator_value is None
    assert pb.excluded[0].reason == "missing_input"
    assert not hasattr(peers[0], "ev_bridge")


@pytest.mark.parametrize("value,reason", [(0, "non_positive_denominator"), (-2, "non_positive_denominator"),
                                         (float("inf"), "non_finite_denominator"), (None, "missing_input")])
def test_unusable_scalar_denominators_stay_excluded(value, reason):
    peer = equity_multiple_set("A", price_per_share=20, eps=value, book_value_per_share=10)
    assert peer.pe is None and peer.pb == 2
    assert peer.exclusions[0].reason == reason


@pytest.mark.parametrize("field,value", [
    ("patmi_vnd", None), ("patmi_vnd", "0"), ("patmi_vnd", "-100"),
    ("weighted_average_shares", None), ("weighted_average_shares", "0"), ("weighted_average_shares", "-10"),
])
def test_peer_bad_earnings_does_not_pollute_pe_or_drop_valid_pb(field, value):
    payload = supplied()
    payload["peers"][0][field] = value
    output = call(payload)
    assert output["ok"], output
    assert output["distribution"]["pe"]["count"] == 2
    assert output["distribution"]["pb"]["count"] == 3
    assert output["distribution"]["pe"]["excluded"][0]["peer_name"] == "PEERA.VN"
    assert output["distribution"]["pe"]["warning"]


@pytest.mark.parametrize("field,value", [("parent_equity_vnd", None), ("parent_equity_vnd", "0"),
                                         ("parent_equity_vnd", "-100"), ("current_common_shares", "0")])
def test_target_bad_book_blocks_only_pb_scenario(field, value):
    payload = supplied()
    payload["target"][field] = value
    output = call(payload)
    assert output["ok"], output
    assert output["target"]["scenarios"]["pb"]["prices"] is None
    assert output["target"]["scenarios"]["pb"]["reason"]
    assert output["target"]["scenarios"]["pe"]["prices"]["median"] == 20000


def test_no_eligible_peers_is_unknown_not_zero():
    payload = supplied()
    for peer in payload["peers"]:
        peer["price_vnd"] = None
    output = call(payload)
    assert output["ok"], output
    for name in ("pe", "pb"):
        assert output["distribution"][name]["count"] == 0
        assert output["distribution"][name]["median"] is None
        assert output["target"]["scenarios"][name] == {
            "unit": "VND_per_share", "target_input": "eps_vnd" if name == "pe" else "bvps_vnd",
            "reason": "no_eligible_peers", "prices": None,
        }


def test_hash_covers_excluded_peers_and_ignores_object_key_order():
    payload = supplied()
    original = build_vietnam_comparables(payload)["input_sha256"]
    reordered = json.loads(json.dumps(payload, sort_keys=True))
    assert build_vietnam_comparables(reordered)["input_sha256"] == original
    payload["peers"][0]["patmi_vnd"] = None
    excluded = build_vietnam_comparables(payload)["input_sha256"]
    assert excluded != original
    payload["peers"][0]["selection_basis"] += " revised"
    assert build_vietnam_comparables(payload)["input_sha256"] != excluded


def test_reconstruction_and_sector_mismatch_remain_explicit():
    payload = supplied()
    payload["peers"][0]["financial_evidence"]["retrieved_at"] = "2025-06-01T00:00:00Z"
    payload["peers"][0]["sector"] = "different_declared_sector"
    output = call(payload)
    assert output["ok"], output
    assert output["historical_reconstruction"] is True
    assert output["sector_mismatches"] == ["PEERA.VN"]


@pytest.mark.parametrize("path,value", [
    (("target", "financial_evidence", "available_at"), "2025-05-16T00:00:00Z"),
    (("target", "financial_evidence", "published_at"), "2024-01-01T00:00:00Z"),
    (("peers", 0, "price_observed_at"), "2025-05-14T07:45:00Z"),
    (("peers", 0, "share_basis"), "split_adjusted"),
    (("peers", 0, "symbol"), "CASE.VN"),
    (("peers", 1, "symbol"), "PEERA.VN"),
    (("peers", 0, "venue"), "NASDAQ"),
    (("target", "price_evidence", "source_url"), "file:///private.txt"),
    (("target", "price_evidence", "source_url"), "https://secret:token@example.invalid"),
    (("target", "price_evidence", "document_sha256"), "abc"),
    (("target", "price_evidence", "locator"), " "),
    (("target", "price_evidence", "available_at"), "2025-05-15T07:00:00Z"),
    (("target", "price_observed_at"), "2025-05-15T08:00:00Z"),
    (("period_end",), "2024-06-30"),
    (("period_start",), "2024-01-02"),
    (("as_of",), "2025-05-15T07:00:00Z"),
    (("as_of",), "2025-05-15T09:00:00"),
    (("consolidation",), "unknown"),
    (("schema_version",), True),
    (("target", "selection_basis"), ""),
    (("target", "share_basis_note"), " "),
    (("target", "patmi_vnd"), 100),
    (("target", "patmi_vnd"), True),
    (("target", "patmi_vnd"), "NaN"),
    (("target", "patmi_vnd"), "1e1000"),
    (("target", "patmi_vnd"), "1e-1000"),
    (("target", "patmi_vnd"), "+100"),
])
def test_bad_or_incomparable_input_fails_closed(path, value):
    payload = supplied()
    item = payload
    for key in path[:-1]:
        item = item[key]
    item[path[-1]] = value
    output = call(payload)
    assert output["ok"] is False, (path, value, output)
    assert len(json.dumps(output)) <= TOOL_RESULT_LIMIT


def test_fractional_timestamp_chronology_does_not_use_lexical_order():
    payload = supplied()
    payload["target"]["financial_evidence"].update(
        published_at="2025-03-31T00:00:00.100Z", available_at="2025-03-31T00:00:00Z"
    )
    assert call(payload)["ok"] is False
    payload = supplied()
    for company in [payload["target"], *payload["peers"]]:
        company["price_observed_at"] = "2025-05-15T07:45:00.000000Z"
    assert call(payload)["ok"] is True


def test_offsets_page_all_peers_without_changing_aggregate_or_hash():
    payload = supplied()
    template = deepcopy(payload["peers"][0])
    payload["peers"] = [dict(deepcopy(template), symbol=f"P{i}.VN", price_vnd=str((i + 1) * 10000)) for i in range(12)]
    offset, names, hashes, medians = 0, [], set(), set()
    while offset is not None:
        raw = VietnamComparablesTool().execute(payload=payload, offset=offset)
        assert len(raw) <= TOOL_RESULT_LIMIT
        page = json.loads(raw)
        assert page["ok"], page
        names.extend(row["symbol"] for row in page["peers"])
        hashes.add(page["input_sha256"])
        medians.add(page["distribution"]["pe"]["median"])
        assert page["paging"]["total"] == 12
        offset = page["paging"]["next_offset"]
    assert names == [f"P{i}.VN" for i in range(12)]
    assert len(hashes) == len(medians) == 1


@pytest.mark.parametrize("offset", [-1, True, 1.5, "0"])
def test_invalid_offset_is_rejected(offset):
    assert call(offset=offset)["ok"] is False


def test_input_bound_and_unknown_fields():
    payload = supplied()
    payload["unexpected"] = "x" * 64001
    assert "input budget" in call(payload)["error"]
    payload = supplied()
    payload["target"]["financial_evidence"]["path"] = "C:/private"
    assert call(payload)["ok"] is False
    payload = supplied()
    payload["peers"] *= 5
    assert call(payload)["ok"] is False


def test_output_budget_never_silently_truncates_json():
    payload = supplied()
    for company in [payload["target"], *payload["peers"]]:
        company["selection_basis"] = "x" * 256
        company["share_basis_note"] = "x" * 256
        for name in ("financial_evidence", "price_evidence"):
            company[name]["source_url"] = "https://example.invalid/" + "x" * 480
            company[name]["locator"] = "x" * 256
    raw = VietnamComparablesTool().execute(payload=payload)
    assert len(raw) <= TOOL_RESULT_LIMIT
    output = json.loads(raw)
    assert output["ok"] is True or "result budget" in output["error"]


def test_tool_schema_resolves_nested_evidence_and_company_definitions():
    from jsonschema import Draft202012Validator

    schema = VietnamComparablesTool().to_openai_schema()["function"]["parameters"]
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate({"payload": supplied(), "offset": 0})


def test_actual_registry_exposes_comparables_without_shell_tools():
    from src.tools import build_registry

    registry = build_registry(include_shell_tools=False)
    assert isinstance(registry.get("vietnam_comparables"), VietnamComparablesTool)
    assert json.loads(registry.execute("vietnam_comparables", {"payload": supplied()}))["ok"] is True


def test_comparables_runs_through_in_memory_fastmcp_with_identical_payload(monkeypatch):
    from fastmcp import Client
    import mcp_server
    from src.agent.tools import ToolRegistry

    registry = ToolRegistry()
    registry.register(VietnamComparablesTool())
    monkeypatch.setattr(mcp_server, "_registry", registry)

    async def run():
        async with Client(mcp_server.mcp) as client:
            return await client.call_tool("vietnam_comparables", {"payload": supplied(), "offset": 0})

    result = asyncio.run(run())
    output = json.loads(result.content[0].text)
    assert output["ok"] is True
    assert output["distribution"]["pe"]["median"] == 10
    assert output["target"]["scenarios"]["pb"]["prices"]["median"] == 20000
