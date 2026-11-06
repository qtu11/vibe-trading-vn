"""Distinct, causal EMA research through the existing offline journal and API."""

from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.trading.forex.research_signals import ema_crossovers
from src.trading.forex.walk_forward import WalkForwardRequest, _evaluate, walk_forward
from tests.test_forex_walk_forward import request_data


def ema_request(**changes):
    return WalkForwardRequest.model_validate({**request_data(), "strategy": "ema_crossover", **changes})


def test_ema_recursion_has_first_close_seed_and_only_completed_prefix_crossovers():
    # alpha_fast=2/3, alpha_slow=1/2. At index 3 they are 101 1/3 and 101;
    # at index 5 they are 99.7037 and 100; at index 7, 99.5226 and 99.5.
    rows = [{"close": close} for close in [100, 100, 100, 102, 101, 99, 98, 100, 103]]
    assert ema_crossovers(rows, 2, 3) == [None, None, None, "buy", None, "sell", None, "buy", None]
    assert ema_crossovers(rows[:6], 2, 3) == ema_crossovers(rows, 2, 3)[:6]
    assert ema_crossovers([{"close": 100}] * 20, 2, 3) == [None] * 20
    assert ema_crossovers([], 2, 3) == []
    assert ema_crossovers([{"close": close} for close in [100, 102, 101]], 2, 3) == [None] * 3


def test_ema_has_separate_artifact_configuration_but_same_underlying_dataset():
    ema = walk_forward(ema_request())
    sma = walk_forward(WalkForwardRequest.model_validate(request_data()))
    assert ema["status"] == "ok"
    assert ema["strategy_variant"] == "ema_crossover_next_open_one_bar_v1"
    assert ema["config"]["strategy"] == "ema_crossover"
    assert ema["config_hash"] != sma["config_hash"]
    assert ema["dataset_hash"] == sma["dataset_hash"]
    assert ema["indicator_methodology"] == {
        "type": "ema", "alpha": "2/(window+1)", "seed": "first_close_in_supplied_dataset",
        "warmup": "slow+1_completed_closes", "history_scope": "available_prefix_only",
        "reseed_between_folds": False,
    }
    assert ema["runner_parity"] is False
    assert ema["execution_assumptions"] == sma["execution_assumptions"]
    assert ema == walk_forward(ema_request())


def test_published_synthetic_ema_example_runs_three_past_only_oos_folds():
    example = Path(__file__).resolve().parents[2] / "docs/examples/forex-ema-walk-forward.example.json"
    request = WalkForwardRequest.model_validate_json(example.read_text(encoding="utf-8"))
    result = walk_forward(request)
    assert result["status"] == "ok", result
    assert result["strategy_variant"] == "ema_crossover_next_open_one_bar_v1"
    assert len(result["folds"]) == 3
    assert all(fold["out_of_sample_metrics"]["trade_count"] > 0 for fold in result["folds"])


def test_omitted_and_explicit_sma_keep_the_established_response_contract():
    data = request_data()
    before = walk_forward(WalkForwardRequest.model_validate(data))
    assert before == walk_forward(WalkForwardRequest.model_validate({**data, "strategy": "sma_crossover"}))
    assert before["strategy_variant"] == "sma_crossover_next_open_one_bar_v1"
    assert "strategy" not in before["config"]
    assert "indicator_methodology" not in before


def test_ema_training_and_selection_ignore_every_oos_price():
    data = {**request_data(), "strategy": "ema_crossover"}
    original = walk_forward(WalkForwardRequest.model_validate(data))
    modified = deepcopy(data)
    cutoff = original["folds"][0]["out_of_sample"]["signal_start_index"]
    for bar in modified["bars"][cutoff:]:
        for field in ("open", "high", "low", "close"):
            bar[field] *= 1.5
    altered = walk_forward(WalkForwardRequest.model_validate(modified))
    first, changed = original["folds"][0], altered["folds"][0]
    assert first["selected"] == changed["selected"]
    assert first["trials"] == changed["trials"]
    assert first["training_data_hash"] == changed["training_data_hash"]
    assert first["out_of_sample_input_hash"] != changed["out_of_sample_input_hash"]


def test_training_indicator_is_given_only_available_closes(monkeypatch):
    import importlib

    module = importlib.import_module("src.trading.forex.walk_forward")
    supplied_prefixes = []

    def inspect(rows, fast, slow):
        supplied_prefixes.append((len(rows), fast, slow))
        return ema_crossovers(rows, fast, slow)

    monkeypatch.setattr(module, "ema_crossovers", inspect)
    result = module.walk_forward(ema_request())
    first = result["folds"][0]
    assert [count for count, _, _ in supplied_prefixes[:2]] == [first["training"]["signal_end_index"] + 1] * 2
    assert supplied_prefixes[2][0] == first["out_of_sample"]["signal_end_index"] + 1
    assert supplied_prefixes[2][0] > first["out_of_sample"]["signal_start_index"]
    assert supplied_prefixes[2][0] < len(request_data()["bars"])


def test_ema_signal_executes_next_open_and_deducts_one_round_trip_cost():
    rows = request_data()["bars"][:8]
    rows[3]["open"] = 20  # Signal-bar open never determines the fill.
    rows[4]["open"], rows[4]["close"] = 100, 105
    result = _evaluate(rows, [3], 2, 3, 10, "ema_crossover")
    assert result["trade_count"] == 1
    assert result["gross_return_sum"] == pytest.approx(.05)
    assert result["net_return"] == pytest.approx(.049)
    rows[3]["open"] = 500
    assert _evaluate(rows, [3], 2, 3, 10, "ema_crossover") == result


def test_ema_retains_failed_candidates_and_does_not_publish_incomplete_oos():
    result = walk_forward(ema_request(candidates=[{"fast": 2, "slow": 3}, {"fast": 20, "slow": 80}]))
    assert result["folds"][0]["trials"][1]["code"] == "NO_TRAIN_TRADES"
    assert result["folds"][0]["selected"] == {"fast": 2, "slow": 3}
    failed = walk_forward(ema_request(candidates=[{"fast": 20, "slow": 80}]))
    assert failed["status"] == "incomplete"
    assert failed["folds"][0]["code"] == "NO_VALID_TRAINING_TRIAL"
    assert failed["out_of_sample_metrics"] is None


@pytest.mark.parametrize("strategy", [None, True, "ema", "rsi", {"type": "ema_crossover"}])
def test_unsupported_or_untyped_strategy_is_rejected(strategy):
    with pytest.raises(ValidationError):
        ema_request(strategy=strategy)


def test_registry_retains_ema_variant_and_indicator_source_without_broker_calls(tmp_path):
    from src.trading.forex.service import ForexService
    from src.trading.forex.store import Store

    broker = Mock(side_effect=AssertionError("Offline research cannot request a broker adapter"))
    service = ForexService(Store(tmp_path / "forex.db"), credentials=Mock(), factory=broker)
    first = service.run_experiment(ema_request())
    assert first["request"]["strategy"] == "ema_crossover"
    assert first["result"]["strategy_variant"] == "ema_crossover_next_open_one_bar_v1"
    assert len(first["engine"]["source_sha256"]["src.trading.forex.research_signals"]) == 64
    assert Store(service.store.path).research_run(first["experiment_id"], first["id"]) == first
    second = service.run_experiment(WalkForwardRequest.model_validate(request_data()), first["experiment_id"])
    assert second["request"]["strategy"] == "sma_crossover"
    assert second["input_hash"] != first["input_hash"]
    assert second["attempt"] == 2
    broker.assert_not_called()
    service.credentials.assert_not_called()


def test_http_ema_reuses_authenticated_readonly_contract(monkeypatch):
    from src.api.forex_routes import register_forex_routes
    from src.api.security import require_auth

    monkeypatch.setattr("src.api.security._configured_api_key", lambda: "fixture-key")
    service = Mock()
    app = FastAPI()
    register_forex_routes(app, service)
    payload = ema_request().model_dump(mode="json")
    with TestClient(app) as client:
        assert client.post("/api/forex/walk-forward", json=payload).status_code == 401
        app.dependency_overrides[require_auth] = lambda: None
        response = client.post("/api/forex/walk-forward", json=payload)
        assert response.status_code == 200, response.text
        assert response.json() == walk_forward(ema_request())
        assert client.post("/api/forex/walk-forward", json={**payload, "strategy": "rsi"}).status_code == 422
    assert service.mock_calls == []


@pytest.mark.asyncio
async def test_mcp_validates_the_same_explicit_ema_strategy_without_account_calls():
    from fastmcp import Client
    from src.trading.forex.mcp_server import build_server
    from src.trading.forex.models import Connection

    service = Mock()
    service.store.connection.return_value = Connection(
        id="fixture", label="Fixture", connector="oanda", account_ref="101-001",
    )
    server = build_server(service, "fixture")
    service.reset_mock()
    async with Client(server) as client:
        result = await client.call_tool("forex_walk_forward", {"request": ema_request().model_dump(mode="json")})
    assert result.data == walk_forward(ema_request())
    assert service.mock_calls == []
