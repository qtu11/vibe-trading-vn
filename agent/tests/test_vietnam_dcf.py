"""VN DCF adapter: engine parity, explicit scale, evidence and invalid scenarios."""

from copy import deepcopy
from dataclasses import asdict
from decimal import Decimal
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.quantlib.valuation import dcf
from src.quantlib.valuation.contracts import Assumption, ValuationError
from src.tools.vietnam_dcf import VietnamDCFRequest, build_vietnam_dcf


EXAMPLE = Path(__file__).resolve().parents[2] / "docs/examples/vn-dcf.example.json"


def supplied():
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def reference(payload):
    scale = payload["amount_scale"]
    inputs = {name: value["value"] for name, value in payload["wacc"].items()}
    for name in ("ebit", "depreciation_amortization", "capex", "delta_nwc"):
        inputs[name] = [float(Decimal(row[name]) * scale) for row in payload["forecast"]]
    bridge = payload["equity_bridge"]
    for name in ("total_debt", "minority_interest", "preferred_equity", "associate_investments"):
        inputs[name] = float(Decimal(bridge[name]) * scale)
    inputs["cash_and_equivalents"] = float(Decimal(bridge["unrestricted_cash"]) * scale)
    inputs["diluted_shares"] = float(bridge["diluted_shares"])
    for name in ("terminal_growth", "exit_multiple"):
        item = payload[name]
        inputs[name] = Assumption(name, item["value"], item["basis"], ",".join(item["source_ids"]) or None)
    structure = payload["capital_structure"]
    if structure["kind"] == "target":
        inputs.update({name: structure[name] for name in ("target_equity_weight", "target_debt_weight")})
    else:
        inputs.update({name: float(Decimal(structure[name]) * scale) for name in ("market_value_of_equity", "market_value_of_debt")})
    result = dcf.run_dcf(inputs, capital_structure_basis=structure["kind"],
                         discounting_convention=payload["discounting_convention"],
                         terminal_value_method=payload["terminal_value_method"],
                         gdp_growth_ceiling=payload["gdp_growth_reference"]["value"])
    return result, inputs


@pytest.mark.parametrize("convention", ["mid_year", "year_end"])
@pytest.mark.parametrize("method", ["perpetuity_growth", "exit_multiple"])
def test_fixture_base_and_each_grid_cell_use_existing_engine(convention, method):
    payload = supplied()
    payload.update(discounting_convention=convention, terminal_value_method=method)
    output = build_vietnam_dcf(payload)
    expected, inputs = reference(payload)
    assert output["base_case"] == asdict(expected)
    assert output["sensitivity"]["terminal_value_method"] == "perpetuity_growth"
    assert output["sensitivity"]["probabilities_assigned"] is False
    assert len(output["sensitivity"]["cells"]) == 3
    for row in output["sensitivity"]["cells"]:
        for cell in row:
            if cell["terminal_growth"] >= cell["wacc"]:
                assert cell["value_per_share_vnd"] is None
                assert cell["reason"] == "growth_must_be_below_wacc"
                continue
            # An independently invoked existing complete DCF with a 100% equity
            # WACC reproduces every valid cell; the fixed FCFF/bridge is retained.
            cell_inputs = dict(inputs, risk_free_rate=cell["wacc"], beta=0,
                               equity_risk_premium=0, size_premium=0, country_risk_premium=0,
                               target_equity_weight=1, target_debt_weight=0,
                               terminal_growth=Assumption("terminal_growth", cell["terminal_growth"], "Explicit grid point"))
            valuation = dcf.run_dcf(cell_inputs, capital_structure_basis="target",
                                    discounting_convention=convention, terminal_value_method="perpetuity_growth")
            assert cell["value_per_share_vnd"] == pytest.approx(valuation.value_per_share)
            assert cell["reason"] is None
    json.dumps(output, allow_nan=False)


def test_scale_is_applied_to_money_and_never_actual_share_count():
    million = supplied()
    full = deepcopy(million)
    full["amount_scale"] = 1
    for row in full["forecast"]:
        for name in ("ebit", "depreciation_amortization", "capex", "delta_nwc"):
            row[name] = str(Decimal(row[name]) * 1_000_000)
    for name in ("total_debt", "unrestricted_cash", "restricted_cash", "minority_interest", "preferred_equity", "associate_investments"):
        full["equity_bridge"][name] = str(Decimal(full["equity_bridge"][name]) * 1_000_000)
    scaled, unscaled = build_vietnam_dcf(million), build_vietnam_dcf(full)
    assert scaled["base_case"] == unscaled["base_case"]
    assert scaled["base_case"]["net_debt_bridge"]["diluted_shares"] == 10_000_000
    assert scaled["base_case"]["fcff_bridge"][0]["fcff"] == 86_000_000
    assert scaled["money_output_unit"] == "VND"
    assert scaled["per_share_output_unit"] == "VND_per_share"
    assert scaled["input_sha256"] != unscaled["input_sha256"]


def test_restricted_cash_is_hashed_and_reported_but_never_added():
    payload = supplied()
    before = build_vietnam_dcf(payload)
    payload["equity_bridge"]["restricted_cash"] = "999"
    after = build_vietnam_dcf(payload)
    assert before["excluded_restricted_cash_vnd"] == 7_000_000
    assert after["excluded_restricted_cash_vnd"] == 999_000_000
    assert before["input_sha256"] != after["input_sha256"]
    assert before["base_case"] == after["base_case"]
    assert before["sensitivity"] == after["sensitivity"]
    payload["equity_bridge"]["unrestricted_cash"] = "21"
    increased = build_vietnam_dcf(payload)
    assert increased["base_case"]["value_per_share"] - after["base_case"]["value_per_share"] == pytest.approx(0.1)


def test_current_capital_values_use_money_scale_and_same_existing_wacc():
    payload = supplied()
    payload["capital_structure"] = {"kind": "current", "market_value_of_equity": "800", "market_value_of_debt": "200",
                                     "basis": "Synthetic current market values, not target weights", "source_ids": []}
    output = build_vietnam_dcf(payload)
    expected, _ = reference(payload)
    assert output["base_case"] == asdict(expected)
    assert output["base_case"]["wacc_build"]["equity_weight"] == 0.8
    assert output["base_case"]["wacc_build"]["capital_structure_basis"] == "current"


def test_hash_is_key_order_independent_preserves_tiny_input_changes_and_code_identity():
    payload = supplied()
    original = build_vietnam_dcf(payload)
    assert build_vietnam_dcf(json.loads(json.dumps(payload, sort_keys=True)))["input_sha256"] == original["input_sha256"]
    payload["forecast"][0]["ebit"] = "120.000000000000000000000000000001"
    precise = build_vietnam_dcf(payload)
    assert precise["normalized_inputs"]["forecast"][0]["ebit"].endswith("000001")
    assert precise["input_sha256"] != original["input_sha256"]
    assert precise["model_version"] == original["model_version"]
    assert len(original["model_version"]) == 64
    payload["evidence"][0]["locator"] += " revised"
    assert build_vietnam_dcf(payload)["input_sha256"] != precise["input_sha256"]


def test_decimal_presentation_normalization_does_not_create_new_economic_input():
    payload = supplied()
    before = build_vietnam_dcf(payload)
    payload["forecast"][0]["ebit"] = "1.20e2"
    payload["equity_bridge"]["minority_interest"] = "-0.0"
    assert build_vietnam_dcf(payload)["input_sha256"] == before["input_sha256"]


def test_missing_required_zero_premium_is_not_silently_substituted():
    payload = supplied()
    del payload["wacc"]["size_premium"]
    with pytest.raises(ValidationError, match="size_premium"):
        build_vietnam_dcf(payload)


@pytest.mark.parametrize("field,value", [("amount_scale", True), ("amount_scale", "1000000"), ("amount_scale", 100),
                                         ("schema_version", True), ("currency", "USD"), ("business_model", "bank"),
                                         ("consolidation", "separate"), ("as_of", "2026-11-06")])
def test_identity_scale_and_timestamp_contract_rejects_unsupported_inputs(field, value):
    payload = supplied()
    payload[field] = value
    with pytest.raises(ValueError):
        build_vietnam_dcf(payload)


@pytest.mark.parametrize("field,value", [("risk_free_rate", 4), ("tax_rate", -0.01), ("tax_rate", 1.01),
                                         ("beta", True), ("country_risk_premium", "0.05"), ("beta", None)])
def test_numeric_rates_are_explicit_fractions_and_booleans_not_numbers(field, value):
    payload = supplied()
    payload["wacc"][field]["value"] = value
    with pytest.raises(ValueError):
        build_vietnam_dcf(payload)


@pytest.mark.parametrize("field,value", [("capex", "-1"), ("depreciation_amortization", "-1"), ("ebit", 120),
                                         ("delta_nwc", "NaN"), ("ebit", "1e25"), ("ebit", "1e-13"),
                                         ("ebit", "0x10"), ("ebit", "1_000"),
                                         ("ebit", "1e999999999999999999999999999999"),
                                         ("ebit", "1000000000000000000000000.0000001")])
def test_forecast_amount_boundaries(field, value):
    payload = supplied()
    payload["forecast"][0][field] = value
    with pytest.raises(ValueError):
        build_vietnam_dcf(payload)


def test_negative_working_capital_is_cash_release_not_rejected_or_sign_flipped():
    payload = supplied()
    payload["forecast"][0]["delta_nwc"] = "-5"
    assert build_vietnam_dcf(payload)["base_case"]["fcff_bridge"][0]["fcff"] == 96_000_000


@pytest.mark.parametrize("field,value", [("total_debt", "-1"), ("restricted_cash", "-1"), ("unrestricted_cash", None),
                                         ("diluted_shares", "0"), ("diluted_shares", "1e19"),
                                         ("share_basis_note", " "), ("associate_earnings_excluded_from_forecast", False),
                                         ("associate_earnings_excluded_from_forecast", 1), ("source_ids", [])])
def test_equity_bridge_refuses_magnitudes_missing_dilution_or_associate_double_count(field, value):
    payload = supplied()
    payload["equity_bridge"][field] = value
    with pytest.raises(ValueError):
        build_vietnam_dcf(payload)


@pytest.mark.parametrize("change", ["unknown_reference", "duplicate_evidence", "future_available", "predates_snapshot", "future_snapshot", "blank_basis", "credential_url"])
def test_evidence_and_assumption_chronology_are_enforced(change):
    payload = supplied()
    if change == "unknown_reference":
        payload["wacc"]["beta"]["source_ids"] = ["missing"]
    elif change == "duplicate_evidence":
        payload["evidence"].append(deepcopy(payload["evidence"][0]))
    elif change == "future_available":
        payload["evidence"][0].update(available_at="2026-11-07T00:00:00Z", retrieved_at="2026-11-08T00:00:00Z")
    elif change == "predates_snapshot":
        payload["evidence"][0]["published_at"] = "2026-09-29T00:00:00Z"
    elif change == "future_snapshot":
        payload["equity_bridge"]["snapshot_date"] = "2026-11-07"
    elif change == "blank_basis":
        payload["terminal_growth"]["basis"] = " "
    else:
        payload["evidence"][0]["source_url"] = "https://user:password@example.invalid/file"
    with pytest.raises(ValueError):
        build_vietnam_dcf(payload)


def test_late_retrieval_explicitly_marks_historical_reconstruction_without_source_verification():
    payload = supplied()
    payload["evidence"][0]["retrieved_at"] = "2026-12-01T00:00:00Z"
    output = build_vietnam_dcf(payload)
    assert output["historical_reconstruction"] is True
    assert "unverified" in " ".join(output["limitations"])


@pytest.mark.parametrize("axis,values", [("wacc_values", [0.1, 0.1]), ("growth_values", [0.03, 0.02]),
                                        ("wacc_values", [-1.0]), ("growth_values", [True]),
                                        ("wacc_values", []), ("growth_values", list(range(10)))])
def test_sensitivity_bounded_unique_ordered_axes(axis, values):
    payload = supplied()
    payload["sensitivity"][axis] = values
    with pytest.raises(ValueError):
        build_vietnam_dcf(payload)


def test_sensitivity_equal_or_above_wacc_is_null_with_reason_and_no_json_nan():
    payload = supplied()
    payload["sensitivity"].update(wacc_values=[0.02], growth_values=[0.01, 0.02, 0.03])
    cells = build_vietnam_dcf(payload)["sensitivity"]["cells"][0]
    assert cells[0]["value_per_share_vnd"] is not None
    assert all(cell["value_per_share_vnd"] is None and cell["reason"] == "growth_must_be_below_wacc" for cell in cells[1:])


def test_unsafe_base_growth_is_refused_even_when_base_selects_exit_multiple():
    payload = supplied()
    payload["terminal_growth"]["value"] = 0.2
    payload["terminal_value_method"] = "exit_multiple"
    with pytest.raises(ValuationError, match="strictly less than WACC"):
        build_vietnam_dcf(payload)


@pytest.mark.parametrize("change", ["missing_weight", "weight_sum", "mixed_structure", "unknown_field", "noncontiguous_forecast", "too_many_years"])
def test_no_silently_ignored_configuration(change):
    payload = supplied()
    if change == "missing_weight":
        del payload["capital_structure"]["target_debt_weight"]
    elif change == "weight_sum":
        payload["capital_structure"]["target_debt_weight"] = 0.8
    elif change == "mixed_structure":
        payload["capital_structure"]["market_value_of_equity"] = "1000"
    elif change == "unknown_field":
        payload["currency_conversion_rate"] = 25000
    elif change == "noncontiguous_forecast":
        payload["forecast"][1]["year"] = 3
    else:
        payload["forecast"] = [dict(payload["forecast"][0], year=index) for index in range(1, 12)]
    with pytest.raises(ValueError):
        build_vietnam_dcf(payload)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_json_is_refused_before_calculation(value):
    payload = supplied()
    payload["terminal_growth"]["value"] = value
    with pytest.raises(ValueError, match="finite JSON"):
        build_vietnam_dcf(payload)


def test_input_budget_rejects_unbounded_payload_before_schema_work():
    payload = supplied()
    payload["irrelevant"] = "x" * 64_000
    with pytest.raises(ValueError, match="64000-byte"):
        build_vietnam_dcf(payload)


def test_typed_request_can_be_round_tripped_by_api_without_hidden_defaults():
    request = VietnamDCFRequest.model_validate(supplied())
    assert build_vietnam_dcf(request.model_dump())["base_case"] == build_vietnam_dcf(supplied())["base_case"]
    assert request.forecast[0].source_ids == []
