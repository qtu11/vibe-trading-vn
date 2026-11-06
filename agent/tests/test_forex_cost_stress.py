"""Frozen OOS cost stress, arithmetic interpretation and offline surface contracts."""

from copy import deepcopy
import importlib
import json
from pathlib import Path
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from src.trading.forex.cost_stress import CostStressRequest, cost_stress
from src.trading.forex.models import Connection, digest
from src.trading.forex.service import ForexService
from src.trading.forex.store import Store
from src.trading.forex.walk_forward import walk_forward
from tests.test_forex_walk_forward import request_data


def supplied(**changes):
    return {"research": request_data(), "spread_bps": 1, "commission_bps": .5,
            "slippage_bps": .25, "gap_bps": .25, **changes}


@pytest.fixture
def service(tmp_path):
    return ForexService(Store(tmp_path / "forex.db"), credentials=Mock(),
        factory=Mock(side_effect=AssertionError("Offline research must not access a broker")))


@pytest.mark.parametrize("strategy", ["sma_crossover", "ema_crossover"])
def test_frozen_base_selections_and_trade_tape_are_shared_by_all_stress_scenarios(strategy, monkeypatch):
    module = importlib.import_module("src.trading.forex.cost_stress")
    original = supplied()
    original["research"]["strategy"] = strategy
    request = CostStressRequest.model_validate(original)
    base = walk_forward(request.research)
    fit = Mock(wraps=module.walk_forward)
    tape = Mock(wraps=module._trade_outcomes)
    monkeypatch.setattr(module, "walk_forward", fit)
    monkeypatch.setattr(module, "_trade_outcomes", tape)
    result = cost_stress(request)
    assert result["status"] == "ok"
    fit.assert_called_once_with(request.research)
    assert tape.call_count == len(base["folds"])  # Freeze once per fold, never once per scenario.
    assert result["base_walk_forward"] == base
    assert [item["spread_multiplier"] for item in result["scenarios"]] == [1, 2, 3]
    assert [item["round_trip_cost_bps"] for item in result["scenarios"]] == [2, 3, 4]
    assert len(result["frozen_oos_tape_hash"]) == 64
    for scenario in result["scenarios"]:
        assert scenario["frozen_oos_tape_hash"] == result["frozen_oos_tape_hash"]
        assert [fold["selected"] for fold in scenario["folds"]] == [fold["selected"] for fold in base["folds"]]
        assert scenario["commission_bps"] == .5
        assert scenario["slippage_bps"] == scenario["gap_bps"] == .25
    baseline, doubled, tripled = [item["out_of_sample_metrics"] for item in result["scenarios"]]
    assert baseline["net_return"] == pytest.approx(base["out_of_sample_metrics"]["net_return"])
    assert baseline["trade_count"] == doubled["trade_count"] == tripled["trade_count"]
    assert baseline["net_expectancy_bps"] - doubled["net_expectancy_bps"] == pytest.approx(1)
    assert doubled["net_expectancy_bps"] - tripled["net_expectancy_bps"] == pytest.approx(1)
    assert baseline["net_return"] >= doubled["net_return"] >= tripled["net_return"]
    assert baseline["arithmetic_break_even_all_in_cost_bps"] == baseline["gross_expectancy_bps"]
    assert baseline["arithmetic_break_even_spread_bps"] == pytest.approx(baseline["gross_expectancy_bps"] - 1)
    assert result["methodology"]["signal_reselection_per_scenario"] is False
    assert "not_compounded" in result["methodology"]["break_even"]
    assert "not_price_gap_replay" in result["methodology"]["gap"]
    assert result == cost_stress(request)


def test_fixed_commission_and_gap_are_charged_once_on_mid_prices_and_negative_expectancy_survives():
    data = supplied(spread_bps=100, commission_bps=200, slippage_bps=300, gap_bps=400)
    data["research"]["round_trip_cost_bps"] = 1000
    result = cost_stress(CostStressRequest.model_validate(data))
    assert result["status"] == "ok"
    for scenario in result["scenarios"]:
        metrics = scenario["out_of_sample_metrics"]
        total = 900 + scenario["spread_multiplier"] * 100
        assert scenario["round_trip_cost_bps"] == total
        assert metrics["net_expectancy_bps"] == pytest.approx(metrics["gross_expectancy_bps"] - total)
        assert metrics["net_expectancy_bps"] < 0
        assert metrics["arithmetic_break_even_spread_bps"] < 0
    assert result["scenarios"][0]["out_of_sample_metrics"]["net_return"] < 0


def test_zero_spread_never_reduces_fixed_cost_or_invents_an_extra_fee():
    data = supplied(spread_bps=0, commission_bps=1, slippage_bps=.5, gap_bps=.5)
    result = cost_stress(CostStressRequest.model_validate(data))
    assert [item["round_trip_cost_bps"] for item in result["scenarios"]] == [2, 2, 2]
    assert result["scenarios"][0]["out_of_sample_metrics"] == result["scenarios"][2]["out_of_sample_metrics"]
    assert len({item["frozen_oos_tape_hash"] for item in result["scenarios"]}) == 1


def test_published_synthetic_cost_fixture_reuses_the_walk_forward_bars_and_base_result():
    examples = Path(__file__).resolve().parents[2] / "docs" / "examples"
    request = CostStressRequest.model_validate_json((examples / "forex-cost-stress.example.json").read_text(encoding="utf-8"))
    baseline = json.loads((examples / "forex-walk-forward.example.json").read_text(encoding="utf-8"))
    assert request.research == CostStressRequest.model_validate({**supplied(), "research": baseline}).research
    assert request.research.source == "synthetic_fixture"
    result = cost_stress(request)
    assert result["status"] == "ok"
    assert len(result["base_walk_forward"]["folds"]) == 3
    assert result["base_walk_forward"] == walk_forward(request.research)
    assert [item["round_trip_cost_bps"] for item in result["scenarios"]] == [2, 3, 4]
    assert all(item["frozen_oos_tape_hash"] == result["frozen_oos_tape_hash"] for item in result["scenarios"])


def test_no_oos_trades_has_null_expectancy_and_break_even_not_fabricated_zero():
    data = supplied()
    data["research"]["n_blocks"] = 2
    for bar in data["research"]["bars"][24:]:
        bar.update(open=102, high=103, low=101, close=102)
    result = cost_stress(CostStressRequest.model_validate(data))
    assert result["status"] == "ok"
    for scenario in result["scenarios"]:
        metrics = scenario["out_of_sample_metrics"]
        assert metrics["trade_count"] == 0
        assert metrics["net_return"] == 0
        assert metrics["net_expectancy_bps"] is None
        assert metrics["arithmetic_break_even_all_in_cost_bps"] is None
        assert metrics["arithmetic_break_even_spread_bps"] is None
        assert metrics["no_trade_reason"] == "NO_OOS_TRADES"


def test_failed_base_training_fold_is_retained_and_never_silently_dropped_from_stress_aggregate():
    data = supplied()
    data["research"]["candidates"] = [{"fast": 20, "slow": 80}]
    result = cost_stress(CostStressRequest.model_validate(data))
    assert result["status"] == "incomplete"
    assert result["base_walk_forward"]["folds"][0]["trials"][0]["code"] == "NO_TRAIN_TRADES"
    for scenario in result["scenarios"]:
        assert scenario["status"] == "incomplete"
        assert scenario["out_of_sample_metrics"] is None
        assert scenario["folds"][0]["code"] == "BASE_FOLD_INCOMPLETE"
        assert scenario["folds"][0]["metrics"] is None


def test_higher_spread_equity_exhaustion_keeps_negative_arithmetic_but_no_compounded_claim(monkeypatch):
    module = importlib.import_module("src.trading.forex.cost_stress")
    data = supplied(spread_bps=1000, commission_bps=0, slippage_bps=0, gap_bps=0)
    data["research"]["round_trip_cost_bps"] = 1000
    # Isolate the accounting boundary: a frozen long outcome loses 85% before costs.
    monkeypatch.setattr(module, "_trade_outcomes", lambda *args: (1, [{"signal_index": 30, "side": "buy", "gross_return": -.85}]))
    result = cost_stress(CostStressRequest.model_validate(data))
    assert result["scenarios"][0]["status"] == "ok"
    for scenario in result["scenarios"][1:]:
        assert scenario["status"] == "incomplete"
        assert scenario["folds"][0]["code"] == "INVALID_RESEARCH_EQUITY"
        metrics = scenario["out_of_sample_metrics"]
        assert metrics["net_return"] is None
        assert metrics["net_expectancy_bps"] < -10000
        assert metrics["arithmetic_break_even_all_in_cost_bps"] == -8500
    json.dumps(result, allow_nan=False)


def test_outcome_only_changes_preserve_train_selection_but_change_frozen_tape_identity():
    original = supplied()
    before = cost_stress(CostStressRequest.model_validate(original))
    changed = deepcopy(original)
    start = before["base_walk_forward"]["folds"][0]["out_of_sample"]["signal_start_index"]
    for bar in changed["research"]["bars"][start:]:
        for field in ("open", "high", "low", "close"):
            bar[field] *= 1.5
    after = cost_stress(CostStressRequest.model_validate(changed))
    assert before["base_walk_forward"]["folds"][0]["selected"] == after["base_walk_forward"]["folds"][0]["selected"]
    assert before["base_walk_forward"]["folds"][0]["trials"] == after["base_walk_forward"]["folds"][0]["trials"]
    assert before["frozen_oos_tape_hash"] != after["frozen_oos_tape_hash"]


@pytest.mark.parametrize("field", ["spread_bps", "commission_bps", "slippage_bps", "gap_bps"])
@pytest.mark.parametrize("value", [True, -1, float("nan"), float("inf"), 1001, "not-a-number"])
def test_invalid_costs_are_rejected_at_the_request_boundary(field, value):
    with pytest.raises(ValidationError):
        CostStressRequest.model_validate(supplied(**{field: value}))


@pytest.mark.parametrize("change", ["missing", "extra", "mismatch", "bidask"])
def test_components_are_explicit_and_must_match_the_base_mid_price_evaluation(change):
    data = supplied()
    if change == "missing":
        del data["gap_bps"]
    elif change == "extra":
        data["multipliers"] = [1, .5, 2]
    elif change == "mismatch":
        data["spread_bps"] = 20
    else:
        data["research"]["price_basis"] = "bid_ask"
    with pytest.raises(ValidationError):
        CostStressRequest.model_validate(data)


def test_registry_retains_kind_source_hashes_all_scenarios_and_immutable_cost_revisions(service):
    request = CostStressRequest.model_validate(supplied())
    first = service.run_cost_stress_experiment(request)
    assert first["status"] == "ok"
    assert first["request"] == request.model_dump(mode="json")
    assert first["result"] == cost_stress(request)
    assert first["engine"]["experiment_kind"] == "frozen_oos_cost_stress"
    assert len(first["engine"]["source_sha256"]["src.trading.forex.cost_stress"]) == 64
    assert first["input_hash"] == digest({"request": first["request"], "engine": first["engine"]})
    changed = supplied(spread_bps=1.5, commission_bps=0)
    second = service.run_cost_stress_experiment(CostStressRequest.model_validate(changed), first["experiment_id"])
    assert second["attempt"] == 2
    assert first["input_hash"] != second["input_hash"]
    assert service.store.research_run(first["experiment_id"], first["id"]) == first
    with service.store.db() as db:
        assert db.execute("SELECT count(*) FROM intents").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM connections").fetchone()[0] == 0
        assert db.execute("PRAGMA user_version").fetchone()[0] == 4
    service.factory.assert_not_called()


def test_failed_cost_stress_attempt_is_journaled_and_exception_text_is_private(service, monkeypatch):
    def fail(_):
        raise RuntimeError("secret C:/operator/private-export.json")
    monkeypatch.setattr("src.trading.forex.cost_stress.cost_stress", fail)
    run = service.run_cost_stress_experiment(CostStressRequest.model_validate(supplied()))
    assert run["status"] == "error"
    assert run["result"]["code"] == "RESEARCH_EVALUATION_FAILED"
    assert run["result"]["exception_type"] == "RuntimeError"
    assert "private-export" not in json.dumps(run)
    assert "secret" not in json.dumps(run)
    service.factory.assert_not_called()


def test_http_pure_stress_has_read_auth_and_journal_has_separate_write_auth(service, monkeypatch):
    from src.api.forex_routes import register_forex_routes
    from src.api.security import require_auth, require_settings_write_auth

    monkeypatch.setattr("src.api.security._configured_api_key", lambda: "fixture-app-key")
    app = FastAPI()
    register_forex_routes(app, service)
    with TestClient(app) as client:
        assert client.post("/api/forex/cost-stress", json=supplied()).status_code == 401
        app.dependency_overrides[require_auth] = lambda: None
        pure = client.post("/api/forex/cost-stress", json=supplied())
        assert pure.json() == cost_stress(CostStressRequest.model_validate(supplied()))
        assert service.store.research_experiments()["total"] == 0
        assert client.post("/api/forex/cost-stress/experiments", json=supplied()).status_code == 401
        app.dependency_overrides[require_settings_write_auth] = lambda: None
        created = client.post("/api/forex/cost-stress/experiments", json=supplied()).json()
        root = f"/api/forex/cost-stress/experiments/{created['experiment_id']}"
        assert client.post(root + "/runs", json=supplied()).json()["attempt"] == 2
        read = f"/api/forex/experiments/{created['experiment_id']}/runs/{created['id']}"
        assert client.get(read).json() == created
        assert client.post("/api/forex/cost-stress", json=supplied(spread_bps=-1)).status_code == 422
    service.factory.assert_not_called()


def test_http_cross_site_journal_write_is_denied_without_creating_a_record(service, monkeypatch):
    from src.api.forex_routes import register_forex_routes

    monkeypatch.setattr("src.api.security._configured_api_key", lambda: "fixture-app-key")
    app = FastAPI()
    register_forex_routes(app, service)
    with TestClient(app) as client:
        denied = client.post("/api/forex/cost-stress/experiments", json=supplied(), headers={
            "Authorization": "Bearer fixture-app-key", "Origin": "https://untrusted.invalid",
            "Sec-Fetch-Site": "cross-site",
        })
        assert denied.status_code == 403
    assert service.store.research_experiments()["total"] == 0


@pytest.mark.asyncio
async def test_actual_mcp_readonly_sweep_and_explicit_local_write_gate(service):
    from fastmcp import Client
    from src.trading.forex.mcp_server import build_server

    service.store.save_connection(Connection(id="practice", label="Fixture", connector="oanda", account_ref="fixture"))
    readonly = build_server(service, "practice")
    tools = {tool.name: tool for tool in await readonly.list_tools()}
    assert len(tools) == 14
    assert tools["forex_cost_stress"].annotations.readOnlyHint is True
    assert tools["forex_cost_stress"].annotations.openWorldHint is False
    assert "forex_run_cost_stress_experiment" not in tools
    async with Client(readonly) as client:
        pure = (await client.call_tool("forex_cost_stress", {"request": supplied()})).data
        assert pure == cost_stress(CostStressRequest.model_validate(supplied()))
    assert service.store.research_experiments()["total"] == 0
    enabled = build_server(service, "practice", allow_research_writes=True)
    tools = {tool.name: tool for tool in await enabled.list_tools()}
    assert len(tools) == 17
    assert tools["forex_run_cost_stress_experiment"].annotations.readOnlyHint is False
    assert tools["forex_run_cost_stress_experiment"].annotations.openWorldHint is False
    assert "forex_submit_intent" not in tools
    async with Client(enabled) as client:
        run = (await client.call_tool("forex_run_cost_stress_experiment", {"request": supplied()})).data
        assert run["result"] == pure
        again = (await client.call_tool("forex_get_experiment_run", {
            "experiment_id": run["experiment_id"], "run_id": run["id"],
        })).data
        assert again == run
    service.factory.assert_not_called()
