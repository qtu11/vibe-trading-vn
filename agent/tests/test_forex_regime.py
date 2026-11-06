"""Closed-bar availability, past-only calibration and replayable regime lifecycle."""

from copy import deepcopy
from datetime import datetime, timedelta
import json
from pathlib import Path
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import numpy as np
from pydantic import ValidationError
import pytest

from src.trading.forex.models import Connection
from src.trading.forex.regime import RegimeRequest, _step, regime
from src.trading.forex.research_dataset import ClosedBarDataset
from src.trading.forex.research_indicators import atr_series
from tests.test_forex_walk_forward import request_data


def supplied(**changes):
    original = request_data()
    return {**{key: original[key] for key in ("source", "symbol", "timeframe", "price_basis", "dataset_revision", "bars")},
            "sma_window": 4, "slope_bars": 2, "atr_period": 5, "train_end_index": 39,
            "entry_quantile": .75, "exit_quantile": .25, "min_dwell_bars": 3, "limit": 100, **changes}


def test_atr_reuses_sma_seeded_wilder_average_and_accounts_for_gaps_without_future_values():
    rows = [{"high": 11, "low": 9, "close": 10}, {"high": 14, "low": 12, "close": 13},
            {"high": 15, "low": 13, "close": 14}, {"high": 18, "low": 16, "close": 17}]
    # TR 2,4,2 seeds 8/3; next TR4 gives (8/3*2+4)/3 = 28/9.
    values = atr_series(rows, 3)
    assert values.iloc[:2].isna().all()
    assert values.iloc[2] == pytest.approx(8 / 3)
    assert values.iloc[3] == pytest.approx(28 / 9)
    assert atr_series(rows[:3], 3).iloc[2] == values.iloc[2]


def test_calibration_uses_only_declared_initial_prefix_and_first_evaluation_is_later():
    result = regime(RegimeRequest.model_validate(supplied()))
    assert result["status"] == "ok"
    calibration = result["calibration"]
    training = result["timeline"][:40]
    values = [abs(row["normalized_slope"]) for row in training if row["normalized_slope"] is not None]
    assert calibration["feature_count"] == len(values)
    assert calibration["entry_threshold"] == pytest.approx(np.quantile(values, .75, method="linear"))
    assert calibration["exit_threshold"] == pytest.approx(np.quantile(values, .25, method="linear"))
    assert calibration["entry_threshold"] > calibration["exit_threshold"] > 0
    assert all(row["regime"] == "unknown" and row["reason"] == "training_only" for row in training)
    first = result["timeline"][40]
    assert calibration["last_training_available_at"] == first["time"]
    assert calibration["first_decision_available_at"] == first["available_at"]
    assert datetime.fromisoformat(first["available_at"]) - datetime.fromisoformat(first["time"]) == timedelta(hours=1)
    assert result["summary"]["evaluated_bars"] == 80
    assert result["producer"]["source_sha256"]["src.trading.forex.research_indicators"]
    assert result["producer"]["source_sha256"]["src.shadow_account.indicators"]


def test_future_evaluation_prices_cannot_change_fitted_thresholds_or_earlier_decisions():
    data = supplied()
    before = regime(RegimeRequest.model_validate(data))
    changed = deepcopy(data)
    for bar in changed["bars"][70:]:
        for field in ("open", "high", "low", "close"):
            bar[field] *= 1.5
    after = regime(RegimeRequest.model_validate(changed))
    assert before["calibration"] == after["calibration"]
    assert before["timeline"][:70] == after["timeline"][:70]
    assert before["config_hash"] == after["config_hash"]
    assert before["dataset_hash"] != after["dataset_hash"]


def test_appending_future_bars_preserves_every_previously_replayed_feature_and_state_hash():
    full = supplied()
    prefix = {**full, "bars": full["bars"][:80]}
    old = regime(RegimeRequest.model_validate(prefix))
    appended = regime(RegimeRequest.model_validate(full))
    assert old["calibration"] == appended["calibration"]
    assert old["timeline"] == appended["timeline"][:80]
    assert old["latest"]["state_hash"] == appended["timeline"][79]["state_hash"]
    assert old == regime(RegimeRequest.model_validate(prefix))


def test_training_row_hashes_do_not_leak_thresholds_fitted_from_later_training_closes():
    data = supplied()
    before = regime(RegimeRequest.model_validate(data))
    changed = deepcopy(data)
    changed["bars"][30].update(open=100, high=121, low=99, close=120)
    after = regime(RegimeRequest.model_validate(changed))
    assert before["calibration"]["threshold_hash"] != after["calibration"]["threshold_hash"]
    assert before["timeline"][:30] == after["timeline"][:30]


def test_hysteresis_and_minimum_elapsed_bar_dwell_suppress_chatter_and_allow_a_frozen_reversal():
    state, reason, changed, left = _step("unknown", 2.1, 2, 1, index=40, changed_at=40, dwell=3)
    assert (state, changed, left) == ("uptrend", 40, 3)
    for index, feature in ((41, .9), (42, -2.1)):
        state, reason, changed, left = _step(state, feature, 2, 1, index=index, changed_at=changed, dwell=3)
        assert state == "uptrend" and reason == "minimum_dwell_hold"
    state, reason, changed, left = _step(state, -2.1, 2, 1, index=43, changed_at=changed, dwell=3)
    assert (state, reason, changed) == ("downtrend", "threshold_transition", 43)
    state, reason, changed, left = _step(state, -1.5, 2, 1, index=47, changed_at=changed, dwell=3)
    assert state == "downtrend" and reason == "hysteresis_hold"
    state, reason, changed, left = _step(state, None, 2, 1, index=48, changed_at=changed, dwell=100)
    assert state == "unknown" and left == 0


@pytest.mark.parametrize("change,code", [({"train_end_index": 5}, "INSUFFICIENT_CALIBRATION_FEATURES"),
                                       ({"sma_window": 200}, "INSUFFICIENT_CALIBRATION_FEATURES")])
def test_missing_training_features_remain_unknown_without_range_sentinels(change, code):
    result = regime(RegimeRequest.model_validate(supplied(**change)))
    assert result["status"] == "incomplete" and result["code"] == code
    assert result["calibration"]["entry_threshold"] is result["calibration"]["exit_threshold"] is None
    assert result["summary"]["unknown_bars"] == result["summary"]["evaluated_bars"]
    assert all(row["regime"] == "unknown" for row in result["timeline"])


@pytest.mark.parametrize("spread", [0, 1])
def test_flat_training_or_zero_atr_never_becomes_an_invented_neutral_state(spread):
    data = supplied()
    for bar in data["bars"]:
        bar.update(open=100, close=100, high=100 + spread, low=100 - spread)
    result = regime(RegimeRequest.model_validate(data))
    assert result["status"] == "incomplete"
    assert result["code"] in {"INSUFFICIENT_CALIBRATION_FEATURES", "DEGENERATE_CALIBRATION_THRESHOLDS"}
    assert result["latest"]["regime"] == "unknown"
    assert result["summary"]["neutral_bars"] == 0


def test_paging_does_not_recalibrate_or_change_summary_latest_or_hashes():
    first = regime(RegimeRequest.model_validate(supplied(limit=20)))
    second = regime(RegimeRequest.model_validate(supplied(offset=20, limit=20)))
    full = regime(RegimeRequest.model_validate(supplied()))
    for key in ("calibration", "summary", "config_hash", "dataset_hash", "latest"):
        assert first[key] == second[key] == full[key]
    assert first["timeline"] + second["timeline"] == full["timeline"][:40]
    assert first["paging"]["next_offset"] == 20
    assert len(second["timeline"]) == 20
    assert len(json.dumps(regime(RegimeRequest.model_validate(supplied(limit=100))), allow_nan=False)) < 128000


def test_shared_dataset_accepts_no_strategy_or_cost_and_keeps_existing_bar_validation():
    data = supplied()
    dataset = {key: data[key] for key in ("source", "symbol", "timeframe", "price_basis", "dataset_revision", "bars")}
    assert len(ClosedBarDataset.model_validate(dataset).bars) == 120
    for field, value in (("complete", False), ("open", True), ("high", 1), ("time", "2024-01-01")):
        changed = deepcopy(data)
        changed["bars"][0][field] = value
        with pytest.raises(ValidationError):
            RegimeRequest.model_validate(changed)
    changed = deepcopy(data)
    changed["bars"][1]["time"] = changed["bars"][0]["time"]
    with pytest.raises(ValidationError, match="contiguous"):
        RegimeRequest.model_validate(changed)


@pytest.mark.parametrize("field,value", [
    ("sma_window", True), ("sma_window", 1), ("sma_window", 201), ("slope_bars", 0),
    ("atr_period", "5"), ("atr_period", 201), ("train_end_index", 119), ("train_end_index", 0),
    ("entry_quantile", True), ("entry_quantile", float("nan")), ("entry_quantile", .3),
    ("exit_quantile", .75), ("exit_quantile", 0), ("min_dwell_bars", 0),
    ("limit", 101), ("offset", -1), ("offset", True),
])
def test_regime_parameters_have_strict_bounded_validation(field, value):
    with pytest.raises(ValidationError):
        RegimeRequest.model_validate(supplied(**{field: value}))


def test_published_fixture_matches_bundled_frontend_example_and_runs_actual_replay():
    repo = Path(__file__).resolve().parents[2]
    example = (repo / "docs/examples/forex-regime.example.json").read_text(encoding="utf-8")
    bundled = (repo / "frontend/src/data/research/forex-regime.example.json").read_text(encoding="utf-8")
    assert json.loads(example) == json.loads(bundled)
    result = regime(RegimeRequest.model_validate_json(example))
    assert result["status"] == "ok"
    assert result["summary"]["evaluated_bars"] > 0


def test_readonly_http_regime_auth_and_validation_never_accesses_broker_or_store(tmp_path, monkeypatch):
    from src.api.forex_routes import register_forex_routes
    from src.api.security import require_auth
    from src.trading.forex.service import ForexService
    from src.trading.forex.store import Store
    monkeypatch.setattr("src.api.security._configured_api_key", lambda: "fixture-key")
    store = Store(tmp_path / "forex.db")
    service = ForexService(store, credentials=Mock(), factory=Mock(side_effect=AssertionError("No broker")))
    app = FastAPI()
    register_forex_routes(app, service)
    with TestClient(app) as client:
        assert client.post("/api/forex/regime", json=supplied()).status_code == 401
        app.dependency_overrides[require_auth] = lambda: None
        result = client.post("/api/forex/regime", json=supplied())
        assert result.status_code == 200 and result.json()["status"] == "ok"
        assert client.post("/api/forex/regime", json=supplied(min_dwell_bars=True)).status_code == 422
    assert not store.path.exists()
    service.factory.assert_not_called()


@pytest.mark.asyncio
async def test_actual_mcp_regime_is_readonly_and_has_no_new_write_tool(tmp_path):
    from fastmcp import Client
    from src.trading.forex.mcp_server import build_server
    from src.trading.forex.service import ForexService
    from src.trading.forex.store import Store
    store = Store(tmp_path / "forex.db")
    store.save_connection(Connection(id="practice", label="Fixture", connector="oanda", account_ref="fixture"))
    service = ForexService(store, credentials=Mock(), factory=Mock(side_effect=AssertionError("No broker")))
    server = build_server(service, "practice")
    tools = {tool.name: tool for tool in await server.list_tools()}
    assert len(tools) == 14
    assert tools["forex_regime"].annotations.readOnlyHint is True
    assert tools["forex_regime"].annotations.openWorldHint is False
    assert not any("run_regime" in name for name in tools)
    async with Client(server) as client:
        result = (await client.call_tool("forex_regime", {"request": supplied()})).data
        assert result == regime(RegimeRequest.model_validate(supplied()))
    service.factory.assert_not_called()
