"""Within-fold dependence, frozen OOS evidence and bounded offline path research."""

from copy import deepcopy
import importlib
import json
from pathlib import Path
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import numpy as np
from pydantic import ValidationError
import pytest

from src.quantlib.risk import drawdown_series
from src.trading.forex.models import Connection, digest
from src.trading.forex.service import ForexService
from src.trading.forex.store import Store
from src.trading.forex.trade_paths import TradePathsRequest, _block_indices, _equity_path, trade_paths
from src.trading.forex.walk_forward import walk_forward
from tests.test_forex_walk_forward import request_data


def supplied(**changes):
    return {"research": request_data(), "seed": 42, "simulations": 100, "block_length": 2, **changes}


@pytest.fixture
def service(tmp_path):
    return ForexService(Store(tmp_path / "forex.db"), credentials=Mock(),
        factory=Mock(side_effect=AssertionError("Trade-path research cannot access a broker")))


def test_blocks_preserve_consecutive_loss_clusters_without_wrapping_and_truncate_only_the_last_block():
    rng = Mock()
    rng.integers.return_value = np.array([2, 0, 4])
    indices = _block_indices(7, 3, rng)
    assert indices.tolist() == [2, 3, 4, 0, 1, 2, 4]
    rng.integers.assert_called_once_with(0, 5, size=3)
    losses = np.array([.1, .2, -.1, -.2, -.3, .3, .4])
    assert losses[indices][:3].tolist() == [-.1, -.2, -.3]


def test_normalized_path_includes_starting_equity_and_matches_shared_drawdown_definition():
    equity, metrics = _equity_path([-.1, -.2, .25])
    assert equity.tolist() == pytest.approx([1, .9, .72, .9])
    assert metrics == pytest.approx({"trade_count": 3, "net_return": -.1, "max_drawdown": .28})
    assert metrics["max_drawdown"] == float(drawdown_series(equity).max())


@pytest.mark.parametrize("returns", [[float("nan")], [float("inf")], [-1], [-2], [1e200, 1e200], [-.9999999999] * 40])
def test_nonfinite_bankrupt_or_underflowed_paths_are_rejected_before_quantlib_can_drop_observations(returns):
    with pytest.raises(ValueError, match="INVALID_RESEARCH_EQUITY"):
        _equity_path(returns)


@pytest.mark.parametrize("strategy", ["sma_crossover", "ema_crossover"])
def test_fits_base_once_and_resamples_only_frozen_trades_within_each_fold(strategy, monkeypatch):
    module = importlib.import_module("src.trading.forex.trade_paths")
    data = supplied()
    data["research"]["strategy"] = strategy
    request = TradePathsRequest.model_validate(data)
    expected = walk_forward(request.research)
    fit = Mock(wraps=module.walk_forward)
    tape = Mock(wraps=module._trade_outcomes)
    blocks = Mock(wraps=module._block_indices)
    monkeypatch.setattr(module, "walk_forward", fit)
    monkeypatch.setattr(module, "_trade_outcomes", tape)
    monkeypatch.setattr(module, "_block_indices", blocks)
    result = trade_paths(request)
    assert result["status"] == "ok"
    fit.assert_called_once_with(request.research)
    assert tape.call_count == len(expected["folds"])
    counts = [fold["trade_count"] for fold in result["folds"]]
    assert blocks.call_count == request.simulations * len(counts)
    assert [call.args[0] for call in blocks.call_args_list[:len(counts)]] == counts
    assert result["base_walk_forward"] == expected
    assert result["actual_path"]["trade_count"] == expected["out_of_sample_metrics"]["trade_count"]
    assert result["actual_path"]["net_return"] == pytest.approx(expected["out_of_sample_metrics"]["net_return"])
    assert all(fold["possible_block_starts"] == fold["trade_count"] - request.block_length + 1 for fold in result["folds"])
    assert result["simulation_summary"]["valid_simulations"] == 100
    assert result["simulation_summary"]["invalid_simulations"] == 0
    assert result["methodology"]["annualization"] is None
    assert result["methodology"]["predictive_probability"] is False
    assert "p_value" not in json.dumps(result)
    assert result == trade_paths(request)


def test_seed_changes_sampled_paths_but_never_reselects_parameters_or_changes_the_frozen_tape():
    first = trade_paths(TradePathsRequest.model_validate(supplied()))
    second = trade_paths(TradePathsRequest.model_validate(supplied(seed=9)))
    assert first["status"] == second["status"] == "ok"
    assert first["base_walk_forward"] == second["base_walk_forward"]
    assert first["frozen_oos_tape_hash"] == second["frozen_oos_tape_hash"]
    assert first["config_hash"] != second["config_hash"]
    assert first["display_paths"]["samples"] != second["display_paths"]["samples"]


def test_quantiles_and_display_paths_are_bounded_and_keep_initial_equity():
    result = trade_paths(TradePathsRequest.model_validate(supplied()))
    display = result["display_paths"]
    assert len(display["steps"]) <= 100
    assert len(display["samples"]) <= 20
    assert display["steps"][0] == 0
    assert display["steps"][-1] == result["actual_path"]["trade_count"]
    assert display["actual"][0] == 1
    assert all(path[0] == 1 and len(path) == len(display["steps"]) for path in display["samples"])
    assert display["statistics_use_all_simulations"] is True
    for field in ("terminal_net_return_quantiles", "max_drawdown_quantiles"):
        values = list(result["simulation_summary"][field].values())
        assert values == sorted(values)
    assert all(0 <= value < 1 for value in result["simulation_summary"]["max_drawdown_quantiles"].values())
    assert len(json.dumps(result, allow_nan=False)) < 128000


def test_published_synthetic_trade_paths_example_nests_the_existing_walk_forward_fixture():
    examples = Path(__file__).resolve().parents[2] / "docs" / "examples"
    request = TradePathsRequest.model_validate_json((examples / "forex-trade-paths.example.json").read_text(encoding="utf-8"))
    baseline = json.loads((examples / "forex-walk-forward.example.json").read_text(encoding="utf-8"))
    assert request.research == TradePathsRequest.model_validate({**supplied(), "research": baseline}).research
    result = trade_paths(request)
    assert result["status"] == "ok"
    assert result["simulation_summary"]["valid_simulations"] == request.simulations
    assert len(result["folds"]) == 3
    assert result["actual_path"]["net_return"] == pytest.approx(result["base_walk_forward"]["out_of_sample_metrics"]["net_return"])


def test_failed_base_fold_and_too_short_positive_folds_never_produce_a_partial_simulation_aggregate():
    data = supplied()
    data["research"]["candidates"] = [{"fast": 20, "slow": 80}]
    failed = trade_paths(TradePathsRequest.model_validate(data))
    assert failed["code"] == "BASE_WALK_FORWARD_INCOMPLETE"
    assert failed["base_walk_forward"]["folds"][0]["trials"][0]["code"] == "NO_TRAIN_TRADES"
    short = trade_paths(TradePathsRequest.model_validate(supplied(block_length=64)))
    assert short["code"] == "INSUFFICIENT_FOLD_TRADES"
    assert any(fold["code"] == "INSUFFICIENT_FOLD_TRADES" for fold in short["folds"])
    for result in (failed, short):
        assert result["status"] == "incomplete"
        assert result["actual_path"] is result["simulation_summary"] is result["display_paths"] is None


def test_zero_trade_folds_are_retained_and_do_not_draw_fake_blocks(monkeypatch):
    module = importlib.import_module("src.trading.forex.trade_paths")
    original = module._trade_outcomes
    seen = 0
    def tape(*args):
        nonlocal seen
        seen += 1
        return (20, []) if seen == 1 else original(*args)
    monkeypatch.setattr(module, "_trade_outcomes", tape)
    result = trade_paths(TradePathsRequest.model_validate(supplied()))
    assert result["status"] == "ok"
    assert result["folds"][0]["trade_count"] == result["folds"][0]["possible_block_starts"] == 0
    assert result["actual_path"]["trade_count"] == sum(fold["trade_count"] for fold in result["folds"])


def test_no_oos_trades_remains_unknown_without_a_fabricated_flat_simulation():
    data = supplied()
    data["research"]["n_blocks"] = 2
    for bar in data["research"]["bars"][24:]:
        bar.update(open=102, high=103, low=101, close=102)
    result = trade_paths(TradePathsRequest.model_validate(data))
    assert result["code"] == "NO_OOS_TRADES"
    assert result["simulation_summary"] is result["display_paths"] is None


def test_numeric_simulation_failure_suppresses_all_quantiles_instead_of_dropping_bad_paths(monkeypatch):
    module = importlib.import_module("src.trading.forex.trade_paths")
    original, calls = module._equity_path, 0
    def fail_one(returns):
        nonlocal calls
        calls += 1
        if calls == 2:  # First simulation, after the observed path.
            raise ValueError("INVALID_RESEARCH_EQUITY")
        return original(returns)
    monkeypatch.setattr(module, "_equity_path", fail_one)
    result = trade_paths(TradePathsRequest.model_validate(supplied()))
    assert result["status"] == "incomplete" and result["code"] == "SIMULATION_NUMERIC_FAILURE"
    assert result["actual_path"] is not None
    summary = result["simulation_summary"]
    assert summary["valid_simulations"] == 99 and summary["invalid_simulations"] == 1
    assert summary["terminal_net_return_quantiles"] is summary["max_drawdown_quantiles"] is None
    assert summary["failure_examples"] == [{"simulation": 1, "code": "INVALID_RESEARCH_EQUITY"}]
    assert result["display_paths"] is None


def test_later_prices_cannot_change_the_first_folds_training_selection():
    data = supplied()
    first = trade_paths(TradePathsRequest.model_validate(data))
    changed = deepcopy(data)
    start = first["base_walk_forward"]["folds"][0]["out_of_sample"]["signal_start_index"]
    for bar in changed["research"]["bars"][start:]:
        for field in ("open", "high", "low", "close"):
            bar[field] *= 1.5
    second = trade_paths(TradePathsRequest.model_validate(changed))
    assert first["base_walk_forward"]["folds"][0]["trials"] == second["base_walk_forward"]["folds"][0]["trials"]
    assert first["frozen_oos_tape_hash"] != second["frozen_oos_tape_hash"]


@pytest.mark.parametrize("field,value", [
    ("seed", True), ("seed", -1), ("seed", 1.5), ("seed", 4294967296), ("seed", "42"),
    ("simulations", True), ("simulations", 99), ("simulations", 2001), ("simulations", 100.5),
    ("block_length", True), ("block_length", 1), ("block_length", 65), ("block_length", "2"),
])
def test_sampling_bounds_are_strict_at_the_request_boundary(field, value):
    with pytest.raises(ValidationError):
        TradePathsRequest.model_validate(supplied(**{field: value}))


def test_journal_preserves_seed_block_frozen_evidence_versions_and_failed_attempts(service):
    request = TradePathsRequest.model_validate(supplied())
    first = service.run_trade_paths_experiment(request)
    assert first["status"] == "ok"
    assert first["request"] == request.model_dump(mode="json")
    assert first["engine"]["experiment_kind"] == "frozen_oos_moving_block_bootstrap"
    assert "src.quantlib.risk" in first["engine"]["source_sha256"]
    assert "src.trading.forex.trade_paths" in first["engine"]["source_sha256"]
    assert first["input_hash"] == digest({"request": first["request"], "engine": first["engine"]})
    second = service.run_trade_paths_experiment(TradePathsRequest.model_validate(supplied(block_length=64)), first["experiment_id"])
    assert second["attempt"] == 2 and second["status"] == "incomplete"
    assert Store(service.store.path).research_run(first["experiment_id"], first["id"]) == first
    with service.store.db() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 4
        assert db.execute("SELECT count(*) FROM intents").fetchone()[0] == 0
    service.factory.assert_not_called()


def test_unexpected_evaluator_failure_is_retained_without_private_exception_text(service, monkeypatch):
    def fail(_):
        raise RuntimeError("secret local broker export path")
    monkeypatch.setattr("src.trading.forex.trade_paths.trade_paths", fail)
    run = service.run_trade_paths_experiment(TradePathsRequest.model_validate(supplied()))
    assert run["status"] == "error" and run["result"]["code"] == "RESEARCH_EVALUATION_FAILED"
    assert "secret" not in json.dumps(run)


def test_http_calculate_is_read_only_and_journal_requires_separate_write_auth(service, monkeypatch):
    from src.api.forex_routes import register_forex_routes
    from src.api.security import require_auth, require_settings_write_auth
    monkeypatch.setattr("src.api.security._configured_api_key", lambda: "fixture-key")
    app = FastAPI()
    register_forex_routes(app, service)
    with TestClient(app) as client:
        assert client.post("/api/forex/trade-paths", json=supplied()).status_code == 401
        app.dependency_overrides[require_auth] = lambda: None
        assert client.post("/api/forex/trade-paths", json=supplied()).json()["status"] == "ok"
        assert service.store.research_experiments()["total"] == 0
        assert client.post("/api/forex/trade-paths/experiments", json=supplied()).status_code == 401
        app.dependency_overrides[require_settings_write_auth] = lambda: None
        first = client.post("/api/forex/trade-paths/experiments", json=supplied()).json()
        route = f"/api/forex/trade-paths/experiments/{first['experiment_id']}/runs"
        assert client.post(route, json=supplied(seed=7)).json()["attempt"] == 2
        read = f"/api/forex/experiments/{first['experiment_id']}/runs/{first['id']}"
        assert client.get(read).json() == first
        assert client.post("/api/forex/trade-paths", json=supplied(seed=True)).status_code == 422
    service.factory.assert_not_called()


def test_cross_site_journal_write_creates_no_attempt(service, monkeypatch):
    from src.api.forex_routes import register_forex_routes
    monkeypatch.setattr("src.api.security._configured_api_key", lambda: "fixture-key")
    app = FastAPI()
    register_forex_routes(app, service)
    with TestClient(app) as client:
        response = client.post("/api/forex/trade-paths/experiments", json=supplied(), headers={
            "Authorization": "Bearer fixture-key", "Origin": "https://untrusted.invalid", "Sec-Fetch-Site": "cross-site"})
    assert response.status_code == 403
    assert service.store.research_experiments()["total"] == 0


@pytest.mark.asyncio
async def test_actual_mcp_default_is_local_readonly_and_persistence_requires_explicit_opt_in(service):
    from fastmcp import Client
    from src.trading.forex.mcp_server import build_server
    service.store.save_connection(Connection(id="practice", label="Fixture", connector="oanda", account_ref="fixture"))
    readonly = build_server(service, "practice")
    tools = {tool.name: tool for tool in await readonly.list_tools()}
    assert len(tools) == 14
    assert tools["forex_trade_paths"].annotations.readOnlyHint is True
    assert tools["forex_trade_paths"].annotations.openWorldHint is False
    assert "forex_run_trade_paths_experiment" not in tools
    async with Client(readonly) as client:
        result = (await client.call_tool("forex_trade_paths", {"request": supplied()})).data
        assert result == trade_paths(TradePathsRequest.model_validate(supplied()))
    enabled = build_server(service, "practice", allow_research_writes=True)
    assert len(await enabled.list_tools()) == 17
    async with Client(enabled) as client:
        run = (await client.call_tool("forex_run_trade_paths_experiment", {"request": supplied()})).data
        assert run["result"] == result
    assert "forex_submit_intent" not in {tool.name for tool in await enabled.list_tools()}
    service.factory.assert_not_called()
