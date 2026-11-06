"""Offline Binance USD-M depth replay regressions; all numbers are synthetic."""
from __future__ import annotations

import copy
import json

import pytest

from src.tools import orderbook_depth_tool
from src.tools.binance_orderbook_replay import PROTOCOL, replay_binance_usdm
from src.tools.orderbook_depth_tool import OrderBookDepthTool


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def fail(*args):
        raise AssertionError("offline replay test attempted a live fetch")
    monkeypatch.setattr(orderbook_depth_tool, "_fetch_raw_book", fail)


def snapshot(update_id=100, **extra):
    return {"type": "snapshot", "lastUpdateId": update_id,
            "bids": [["99", "2"], ["98", "3"]],
            "asks": [["101", "2"], ["102", "3"]], **extra}


def delta(first=100, final=102, previous=99, **extra):
    return {"type": "delta", "e": "depthUpdate", "s": "BTCUSDT",
            "U": first, "u": final, "pu": previous, "b": [], "a": [], **extra}


def replay(*events):
    return {"protocol": PROTOCOL, "events": list(events)}


def run(*events):
    return replay_binance_usdm(replay(*events), "BTCUSDT")


def test_bridge_then_absolute_updates_and_unknown_deletion():
    book, diag = run(snapshot(), delta(b=[["99", "4"]]),
                     delta(103, 104, 102, b=[["98", "0"], ["95", "0"]],
                           a=[["101", "1"]], E=1700000000000))
    assert diag["state"] == "SYNCHRONIZED"
    assert diag["last_update_id"] == 104
    assert book["bids"] == [(99.0, 4.0)]
    assert book["asks"] == [(101.0, 1.0), (102.0, 3.0)]
    assert book["timestamp"] == 1700000000000


def test_snapshot_alone_never_presents_sequence_verified_features():
    book, diag = run(snapshot())
    assert book is None
    assert diag["state"] == "AWAITING_BRIDGE"
    assert diag["valid"] is False
    assert diag["requires_snapshot"] is False


def test_first_bridge_may_end_exactly_at_snapshot_update_id():
    book, diag = run(snapshot(), delta(99, 100, 98))
    assert diag["valid"] is True
    assert book["nonce"] == 100


def test_duplicate_and_stale_delta_do_not_reapply_or_change_timestamp():
    event = delta(b=[["99", "4"]], E=1700000000000)
    book, diag = run(snapshot(), delta(90, 99, 89), event, copy.deepcopy(event),
                     delta(90, 98, 89, b=[["99", "100"]]))
    assert book["bids"][0] == (99.0, 4.0)
    assert book["timestamp"] == 1700000000000
    assert [x["status"] for x in diag["events"]] == [
        "SNAPSHOT_ACCEPTED", "STALE_IGNORED", "DELTA_APPLIED",
        "DUPLICATE_IGNORED", "STALE_IGNORED"]


def test_conflicting_duplicate_invalidates_until_snapshot():
    book, diag = run(snapshot(), delta(), delta(b=[["99", "3"]]),
                     delta(103, 104, 102))
    assert book is None
    assert "conflicting duplicate" in diag["events"][2]["error"]
    assert diag["events"][-1]["status"] == "BLOCKED_UNTIL_SNAPSHOT"


@pytest.mark.parametrize("bad", [
    delta(101, 103, 100),
    delta(90, 99, 89),  # stale alone never bridges
])
def test_missing_bridge_or_only_stale_events_cannot_emit_book(bad):
    book, diag = run(snapshot(), bad)
    assert book is None
    assert diag["valid"] is False


def test_gap_cannot_be_healed_by_later_delta_but_new_snapshot_recovers():
    events = [snapshot(), delta(), delta(105, 106, 104),
              delta(103, 104, 102)]
    book, diag = run(*events)
    assert book is None
    assert "sequence gap" in diag["events"][2]["error"]
    assert diag["events"][3]["status"] == "BLOCKED_UNTIL_SNAPSHOT"
    book, diag = run(*events, snapshot(110), delta(109, 111, 108),
                     delta(112, 113, 111, b=[["99", "5"]]))
    assert diag["valid"] is True
    assert diag["events"][-1]["generation"] == 2
    assert book["bids"][0] == (99.0, 5.0)


@pytest.mark.parametrize("bad", [
    delta(s="ETHUSDT"), delta(U=True), delta(pu=102), delta(U=104, u=103),
    delta(b=[["NaN", "2"]]), delta(b=[["99", "Infinity"]]),
    delta(b=[["99", "-1"]]), delta(b=[["0", "1"]]),
    delta(b=[["99", True]]), delta(b=[["99", "0.0"], ["99.0", "1"]]),
    delta(b=[["99", "1", "unexpected"]]), delta(b=[["1e-999", "1"]]),
    delta(b=[["1e308", "1e308"]]), delta(E=True), delta(E=2**63),
    delta(b=[["101", "1"]]), delta(b=[["99", "0"], ["98", "0"]]),
])
def test_corrupt_delta_invalidates_without_feature_leak(bad):
    book, diag = run(snapshot(), delta(), bad, delta(103, 104, 102))
    assert book is None
    assert diag["state"] == "INVALID"
    assert diag["events"][-2]["status"] == "INVALID"


@pytest.mark.parametrize("bad", [
    snapshot(bids=[]), snapshot(bids=[["101", "1"]]),
    snapshot(bids=[["99", "0"]]), snapshot(lastUpdateId=True),
    snapshot(bids=[["NaN", "1"]]), snapshot(asks=[["101", "Infinity"]]),
])
def test_bad_snapshot_requires_replacement(bad):
    book, diag = run(bad, delta())
    assert book is None
    assert diag["requires_snapshot"] is True


@pytest.mark.parametrize("data", [
    None, {}, {"protocol": "spot", "events": [snapshot()]},
    replay(), replay(*([snapshot()] * 201)),
    {"protocol": PROTOCOL, "events": [snapshot()], "path": "private.json"},
])
def test_invalid_input_boundary(data):
    with pytest.raises(ValueError):
        replay_binance_usdm(data, "BTCUSDT")


def test_level_limits_are_explicit_instead_of_silent_truncation():
    book, diag = run(snapshot(bids=[[str(i), "1"] for i in range(1, 1002)]))
    assert book is None
    assert "at most 1000" in diag["events"][0]["error"]


def test_tool_offline_mode_reuses_spread_depth_impact_without_network(monkeypatch):
    def fail(*args):
        raise AssertionError("replay must never fetch live book")
    monkeypatch.setattr(orderbook_depth_tool, "_fetch_raw_book", fail)
    output = json.loads(OrderBookDepthTool().execute(
        symbol="BTC-USDT", exchange="binance", notional_quote=100, levels=2,
        replay=replay(snapshot(), delta(E=1700000000000))))
    assert output["ok"] is True
    assert output["source"] == "caller_supplied_replay"
    assert output["data"]["product"] == "binance_usdm_futures"
    assert output["data"]["mid_price"] == 100
    assert output["data"]["spread"]["absolute_quote"] == 2
    assert output["data"]["impact_cost"]["buy"]["filled_base_qty"] == 1
    assert output["data"]["timestamp"] == "2023-11-14T22:13:20Z"
    assert output["data"]["timestamp_source"] == "supplied_exchange_event"
    assert output["replay"]["valid"] is True


def test_tool_missing_replay_timestamp_is_unknown_not_current_time():
    output = json.loads(OrderBookDepthTool().execute(
        symbol="BTC-USDT", exchange="binance", replay=replay(snapshot(), delta())))
    assert output["ok"] is True
    assert output["data"]["timestamp"] is None
    assert output["data"]["timestamp_source"] == "unavailable"


def test_tool_invalid_final_state_has_trace_but_no_derived_data():
    output = json.loads(OrderBookDepthTool().execute(
        symbol="BTC-USDT", exchange="binance",
        replay=replay(snapshot(), delta(), delta(105, 106, 104))))
    assert output["ok"] is False
    assert output["replay"]["state"] == "INVALID"
    assert "data" not in output
    assert "impact_cost" not in json.dumps(output)


def test_tool_requires_binance_identity_for_replay():
    output = json.loads(OrderBookDepthTool().execute(
        symbol="BTC-USDT", exchange="okx", replay=replay(snapshot(), delta())))
    assert output["ok"] is False
    assert "binance" in output["error"]


def test_replay_schema_reaches_mirrored_mcp_tool():
    import asyncio
    import mcp_server
    async def inspect():
        tools = await mcp_server.mcp.list_tools()
        tool = next(t for t in tools if t.name == "orderbook_depth")
        assert "replay" in tool.parameters["properties"]
    asyncio.run(inspect())



def test_retained_book_limit_rejects_growth_instead_of_dropping_levels():
    events = [snapshot(bids=[[str(i), "1"] for i in range(1, 1001)],
                       asks=[["10000", "1"]]), delta()]
    for step in range(5):
        events.append(delta(103 + step, 103 + step, 102 + step,
                            b=[[str(i), "1"] for i in range(1001 + step * 1000,
                                                           2001 + step * 1000)]))
    book, diag = run(*events)
    assert book is None
    assert "exceeds 5000" in diag["last_error"]


def test_trace_is_bounded_and_aggregate_counts_retain_omitted_events():
    event = delta()
    output = OrderBookDepthTool().execute(
        symbol="BTC-USDT", exchange="binance",
        replay=replay(snapshot(), *([event] * 199)))
    data = json.loads(output)
    assert data["ok"] is True
    assert len(output) <= 10000
    assert len(data["replay"]["events"]) == 20
    assert data["replay"]["events_total"] == 200
    assert data["replay"]["events_omitted"] == 180
    assert data["replay"]["status_counts"] == {
        "SNAPSHOT_ACCEPTED": 1, "DELTA_APPLIED": 1, "DUPLICATE_IGNORED": 198}


def test_replay_round_trips_actual_tool_through_in_memory_mcp(monkeypatch):
    import asyncio
    import mcp_server
    from fastmcp import Client

    class Registry:
        def execute(self, name, params):
            assert name == "orderbook_depth"
            return OrderBookDepthTool().execute(**params)

    monkeypatch.setattr(mcp_server, "_registry", Registry())

    async def call():
        async with Client(mcp_server.mcp) as client:
            return await client.call_tool("orderbook_depth", {
                "symbol": "BTC-USDT", "exchange": "binance",
                "replay": replay(snapshot(), delta())})

    result = asyncio.run(call())
    assert result.is_error is False
    data = json.loads(result.structured_content["result"])
    assert data["replay"]["state"] == "SYNCHRONIZED"
    assert data["data"]["mid_price"] == 100


def test_feature_arithmetic_overflow_returns_json_error():
    output = json.loads(OrderBookDepthTool().execute(
        symbol="BTC-USDT", exchange="binance", notional_quote=1e308,
        replay=replay(snapshot(bids=[["1e-308", "1"]], asks=[["2e-308", "1"]]),
                      delta())))
    assert output["ok"] is False
    assert "overflows" in output["error"]
    assert "data" not in output


def test_output_limit_returns_explicit_narrow_request_error(monkeypatch):
    monkeypatch.setattr(orderbook_depth_tool, "TOOL_RESULT_LIMIT", 100)
    output = json.loads(OrderBookDepthTool().execute(
        symbol="BTC-USDT", exchange="binance", replay=replay(snapshot(), delta())))
    assert output["ok"] is False
    assert "reduce levels" in output["error"]
