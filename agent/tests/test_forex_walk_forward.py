"""Offline parameter fitting, chronology and read-only API/MCP contracts."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.trading.forex.walk_forward import WalkForwardRequest, walk_forward


def request_data():
    start = datetime(2024, 1, 2, tzinfo=timezone.utc)
    closes = [100, 100, 100, 102, 101, 99, 98, 100, 103, 101, 98, 100] * 10
    return {
        "source": "sanitized-fixture",
        "symbol": "XAUUSDm",
        "timeframe": "1h",
        "price_basis": "mid",
        "dataset_revision": "fixture-v1",
        "bars": [
            {"time": (start + timedelta(hours=i)).isoformat(), "open": 100,
             "high": max(100, close) + 1, "low": min(100, close) - 1,
             "close": close, "complete": True}
            for i, close in enumerate(closes)
        ],
        "candidates": [{"fast": 2, "slow": 3}, {"fast": 3, "slow": 6}],
        "n_blocks": 4,
        "round_trip_cost_bps": 2,
    }


def test_retrains_each_fold_and_records_reproducible_data_and_configuration():
    request = WalkForwardRequest.model_validate(request_data())
    result = walk_forward(request)
    assert result == walk_forward(request)
    assert result["strategy_variant"] == "sma_crossover_next_open_one_bar_v1"
    assert result["runner_parity"] is False
    assert result["bar_timestamp"] == "open"
    assert result["embargo_fraction"] == 0
    assert len(result["folds"]) == 3
    assert result["config"]["round_trip_cost_bps"] == 2
    for fold in result["folds"]:
        assert fold["purged"] == 1
        assert fold["training"]["outcome_end"] < fold["out_of_sample"]["signal_start"]
        assert fold["training"]["outcome_available_at"] <= fold["out_of_sample"]["signal_start"]
        for bounds in (fold["training"], fold["out_of_sample"]):
            assert datetime.fromisoformat(bounds["outcome_available_at"]) - datetime.fromisoformat(bounds["outcome_end"]) == timedelta(hours=1)
        assert len(fold["trials"]) == 2
        scores = [trial for trial in fold["trials"] if trial["status"] == "ok"]
        assert fold["selected"] == max(scores, key=lambda trial: trial["metrics"]["net_return"])["parameters"]
        assert len(fold["training_data_hash"]) == len(fold["out_of_sample_input_hash"]) == 64
    assert result["folds"][1]["training"]["sample_count"] > result["folds"][0]["training"]["sample_count"]


def test_first_fold_fit_does_not_read_any_oos_price():
    original = request_data()
    baseline = walk_forward(WalkForwardRequest.model_validate(original))
    changed = deepcopy(original)
    first_oos = baseline["folds"][0]["out_of_sample"]["signal_start_index"]
    for bar in changed["bars"][first_oos:]:
        for field in ("open", "high", "low", "close"):
            bar[field] *= 1.7
    altered = walk_forward(WalkForwardRequest.model_validate(changed))
    before, after = baseline["folds"][0], altered["folds"][0]
    assert before["selected"] == after["selected"]
    assert before["trials"] == after["trials"]
    assert before["training_data_hash"] == after["training_data_hash"]
    assert before["out_of_sample_input_hash"] != after["out_of_sample_input_hash"]
    assert baseline["dataset_hash"] != altered["dataset_hash"]


def test_execution_uses_next_bar_open_and_fixed_one_bar_exit():
    from src.trading.forex.walk_forward import _evaluate

    rows = request_data()["bars"][:8]
    # At index 3 the 2/3 SMA crosses up. Its outcome is bar 4, not bar 3.
    rows[3]["open"] = 20
    rows[4]["open"], rows[4]["close"] = 100, 105
    result = _evaluate(rows, [3], 2, 3, 10)
    assert result["trade_count"] == 1
    assert result["gross_return_sum"] == pytest.approx(.05)
    assert result["net_return"] == pytest.approx(.049)
    rows[3]["open"] = 500
    assert _evaluate(rows, [3], 2, 3, 10) == result


def test_training_trial_failures_are_retained_instead_of_using_oos_for_fit():
    data = request_data()
    data["candidates"] = [{"fast": 2, "slow": 3}, {"fast": 20, "slow": 80}]
    result = walk_forward(WalkForwardRequest.model_validate(data))
    first = result["folds"][0]
    assert first["trials"][1]["code"] == "NO_TRAIN_TRADES"
    assert first["selected"] == {"fast": 2, "slow": 3}
    data["candidates"] = [{"fast": 20, "slow": 80}]
    failed = walk_forward(WalkForwardRequest.model_validate(data))
    assert failed["status"] == "incomplete"
    assert failed["folds"][0]["status"] == "error"
    assert failed["folds"][0]["code"] == "NO_VALID_TRAINING_TRIAL"
    assert failed["out_of_sample_metrics"] is None


@pytest.mark.parametrize("change", [
    lambda data: data.pop("round_trip_cost_bps"),
    lambda data: data.update(price_basis="bid"),
    lambda data: data.update(source=""),
    lambda data: data.update(dataset_revision=""),
    lambda data: data.update(n_blocks=True),
    lambda data: data.update(round_trip_cost_bps=True),
    lambda data: data.update(candidates=data["candidates"] * 9),
    lambda data: data.update(candidates=[{"fast": 3, "slow": 3}]),
    lambda data: data.update(candidates=[data["candidates"][0]] * 2),
    lambda data: data["bars"][2].update(complete=False),
    lambda data: data["bars"][2].update(complete=1),
    lambda data: data["bars"][2].update(time="2024-01-02T02:00:00"),
    lambda data: data["bars"][2].update(time=data["bars"][1]["time"]),
    lambda data: data["bars"].pop(2),
    lambda data: data["bars"][2].update(close="NaN"),
    lambda data: data["bars"][2].update(open=True),
    lambda data: data["bars"][2].update(low=120),
    lambda data: data["bars"][2].update(high=90),
    lambda data: data.update(connection_id="no-account-argument"),
])
def test_request_rejects_incomplete_ambiguous_or_unbounded_inputs(change):
    data = request_data()
    change(data)
    with pytest.raises(ValidationError):
        WalkForwardRequest.model_validate(data)


def test_timezone_normalization_has_one_identity():
    utc_data = request_data()
    offset_data = deepcopy(utc_data)
    for bar in offset_data["bars"]:
        stamp = datetime.fromisoformat(bar["time"])
        bar["time"] = stamp.astimezone(timezone(timedelta(hours=7))).isoformat()
    assert walk_forward(WalkForwardRequest.model_validate(utc_data)) == walk_forward(WalkForwardRequest.model_validate(offset_data))


def test_http_is_authenticated_readonly_and_never_calls_an_account(monkeypatch):
    from src.api.forex_routes import register_forex_routes
    from src.api.security import require_auth

    monkeypatch.setattr("src.api.security._configured_api_key", lambda: "fixture-app-key")
    service = Mock()
    app = FastAPI()
    register_forex_routes(app, service)
    with TestClient(app) as client:
        assert client.post("/api/forex/walk-forward", json=request_data()).status_code == 401
        app.dependency_overrides[require_auth] = lambda: None
        response = client.post("/api/forex/walk-forward", json=request_data())
        assert response.status_code == 200, response.text
        assert response.json() == walk_forward(WalkForwardRequest.model_validate(request_data()))
        bad = request_data()
        bad["bars"][1]["complete"] = False
        assert client.post("/api/forex/walk-forward", json=bad).status_code == 422
    assert service.mock_calls == []


@pytest.mark.asyncio
async def test_mcp_uses_same_contract_without_touching_bound_account():
    from fastmcp import Client
    from src.trading.forex.mcp_server import build_server
    from src.trading.forex.models import Connection

    service = Mock()
    service.store.connection.return_value = Connection(id="fixture", label="Fixture", connector="oanda", account_ref="101-001")
    server = build_server(service, "fixture")
    service.reset_mock()
    tools = {tool.name: tool for tool in await server.list_tools()}
    assert tools["forex_walk_forward"].annotations.readOnlyHint
    assert tools["forex_walk_forward"].annotations.openWorldHint is False
    async with Client(server) as client:
        result = await client.call_tool("forex_walk_forward", {"request": request_data()})
    assert result.data == walk_forward(WalkForwardRequest.model_validate(request_data()))
    assert service.mock_calls == []
