"""Reverse DCF: independent algebra, fixed engine bridge and honest unknowns."""

from copy import deepcopy
from decimal import Decimal, localcontext
import json
from pathlib import Path

import pytest

from src.tools.vietnam_dcf import build_vietnam_dcf
from src.tools.vietnam_reverse_dcf import build_vietnam_reverse_dcf

EXAMPLE = Path(__file__).resolve().parents[2] / "docs/examples/vn-reverse-dcf.example.json"


def supplied():
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def target_at(request, growth):
    model = deepcopy(request["dcf"])
    model["terminal_growth"]["value"] = growth
    request["target_price_vnd"] = str(build_vietnam_dcf(model)["base_case"]["value_per_share"])
    return request


@pytest.mark.parametrize("timing", ["year_end", "mid_year"])
@pytest.mark.parametrize("growth", [-0.02, 0.0, 0.03, 0.06])
def test_solver_recovers_known_growth_and_full_bridge_algebra(timing, growth):
    request = supplied()
    request["dcf"]["discounting_convention"] = timing
    request["dcf"]["equity_bridge"].update(minority_interest="9", preferred_equity="4", associate_investments="3")
    output = build_vietnam_reverse_dcf(target_at(request, growth))
    solver, base = output["solver"], output["base_case"]
    assert solver["status"] == "solved"
    assert solver["implied_terminal_growth"] == pytest.approx(growth, abs=1e-8)
    assert abs(Decimal(solver["residual_vnd_per_share"])) <= Decimal(request["tolerance_vnd_per_share"])
    shares = float(request["dcf"]["equity_bridge"]["diluted_shares"])
    # Independent inversion of the Gordon bridge; restricted cash stays excluded.
    required_ev = float(request["target_price_vnd"]) * shares + (100 - 20 + 9 + 4 - 3) * 1_000_000
    tv = (required_ev - base["pv_of_explicit_fcff"]) / base["terminal_discount_factor"]
    last_fcff = base["fcff_bridge"][-1]["fcff"]
    algebraic_growth = (tv * output["fixed_wacc"] - last_fcff) / (tv + last_fcff)
    assert solver["implied_terminal_growth"] == pytest.approx(algebraic_growth, abs=1e-8)
    assert output["verification_status"] == "user_supplied_unverified"
    json.dumps(output, allow_nan=False)


def test_money_scale_never_multiplies_target_or_actual_shares():
    million, full = supplied(), supplied()
    full["dcf"]["amount_scale"] = 1
    for row in full["dcf"]["forecast"]:
        for key in ("ebit", "depreciation_amortization", "capex", "delta_nwc"):
            row[key] = str(Decimal(row[key]) * 1_000_000)
    for key in ("total_debt", "unrestricted_cash", "restricted_cash", "minority_interest", "preferred_equity", "associate_investments"):
        full["dcf"]["equity_bridge"][key] = str(Decimal(full["dcf"]["equity_bridge"][key]) * 1_000_000)
    one, two = build_vietnam_reverse_dcf(million), build_vietnam_reverse_dcf(full)
    assert one["solver"] == two["solver"]
    assert one["base_case"] == two["base_case"]
    assert one["input_sha256"] != two["input_sha256"]


def test_price_outside_bracket_is_not_extrapolated_or_clipped():
    request = supplied()
    request["target_price_vnd"] = "1000000"
    solver = build_vietnam_reverse_dcf(request)["solver"]
    assert solver["status"] == "outside_bracket"
    assert solver["implied_terminal_growth"] is None
    assert solver["repriced_value_per_share_vnd"] is None
    assert solver["iterations"] == 0


def test_zero_terminal_fcff_is_not_identifiable_even_if_price_matches():
    request = supplied()
    request["dcf"]["forecast"][0]["ebit"] = "3000"
    request["dcf"]["forecast"][-1].update(ebit="100", depreciation_amortization="10", capex="90", delta_nwc="0")
    target_at(request, 0.03)
    solver = build_vietnam_reverse_dcf(request)["solver"]
    assert solver["status"] == "non_identifiable"
    assert solver["implied_terminal_growth"] is None


def test_negative_terminal_fcff_handles_decreasing_price_orientation():
    request = supplied()
    request["dcf"]["forecast"][0]["ebit"] = "3000"
    request["dcf"]["forecast"][-1]["ebit"] = "0"
    output = build_vietnam_reverse_dcf(target_at(request, 0.03))
    assert output["solver"]["endpoints"][0]["value_per_share_vnd"] > output["solver"]["endpoints"][1]["value_per_share_vnd"]
    assert output["solver"]["implied_terminal_growth"] == pytest.approx(0.03, abs=1e-8)


@pytest.mark.parametrize("change", ["extra", "exit", "bracket_wacc", "bracket_order", "blank_basis", "price_future", "evidence_future", "evidence_old", "price_zero", "tolerance_negative", "numeric_price", "bool_version"])
def test_invalid_scenario_has_no_silent_defaults(change):
    request = supplied()
    if change == "extra": request["result"] = {"verified": True}
    elif change == "exit": request["dcf"]["terminal_value_method"] = "exit_multiple"
    elif change == "bracket_wacc": request["growth_bracket"]["upper"] = 0.0976
    elif change == "bracket_order": request["growth_bracket"]["lower"] = 0.07
    elif change == "blank_basis": request["share_basis_note"] = " "
    elif change == "price_future": request["price_observed_at"] = "2026-12-01T00:00:00Z"
    elif change == "evidence_future": request["price_evidence"].update(available_at="2026-12-01T00:00:00Z", retrieved_at="2026-12-01T00:00:00Z")
    elif change == "evidence_old": request["price_evidence"]["published_at"] = "2026-11-04T00:00:00Z"
    elif change == "price_zero": request["target_price_vnd"] = "0"
    elif change == "tolerance_negative": request["tolerance_vnd_per_share"] = "-1"
    elif change == "numeric_price": request["target_price_vnd"] = 100
    else: request["schema_version"] = True
    with pytest.raises(ValueError):
        build_vietnam_reverse_dcf(request)


def test_late_retrieval_remains_unverified_historical_reconstruction():
    request = supplied()
    request["price_evidence"]["retrieved_at"] = "2026-12-01T00:00:00Z"
    output = build_vietnam_reverse_dcf(request)
    assert output["historical_reconstruction"] is True
    assert output["verification_status"] == "user_supplied_unverified"


def test_payload_budget_and_nonfinite_are_rejected():
    for value in ("x" * 64000, float("nan"), float("inf")):
        request = supplied()
        request["extra"] = value
        with pytest.raises(ValueError): build_vietnam_reverse_dcf(request)


def test_bundled_example_is_identical_and_converges_to_declared_known_growth():
    assert EXAMPLE.read_bytes() == (EXAMPLE.parents[2] / "frontend/src/data/research/vn-reverse-dcf.example.json").read_bytes()
    assert build_vietnam_reverse_dcf(supplied())["solver"]["implied_terminal_growth"] == pytest.approx(0.03, abs=1e-8)


def test_large_decimal_price_never_falsely_converges_after_float_target_rounding():
    request = supplied()
    request["dcf"]["amount_scale"] = 1
    request["dcf"]["equity_bridge"]["diluted_shares"] = "1"
    for row in request["dcf"]["forecast"]: row["ebit"] = "1e22"
    request["growth_bracket"]["lower"] = 0.02
    value = build_vietnam_dcf(request["dcf"])["base_case"]["value_per_share"]
    # This integer differs from both the binary float and its JSON-visible
    # decimal; a 1e-12 price tolerance cannot be met by this engine output.
    request["target_price_vnd"] = format(Decimal.from_float(value) + 1, "f")
    request["tolerance_vnd_per_share"] = "0.000000000001"
    solver = build_vietnam_reverse_dcf(request)["solver"]
    assert solver["status"] != "solved"
    assert solver["implied_terminal_growth"] is None
    if solver["repriced_value_per_share_vnd"] is not None:
        exact_residual = Decimal(str(solver["repriced_value_per_share_vnd"])) - Decimal(request["target_price_vnd"])
        assert Decimal(solver["residual_vnd_per_share"]) == exact_residual
        assert abs(exact_residual) > Decimal(request["tolerance_vnd_per_share"])


def test_decimal_absolute_value_does_not_round_an_outside_endpoint_into_tolerance():
    request = supplied()
    request["growth_bracket"]["lower"] = 0.02
    value = build_vietnam_dcf(request["dcf"])["base_case"]["value_per_share"]
    with localcontext() as context:
        context.prec = 80
        request["target_price_vnd"] = format(Decimal(str(value)) - Decimal("1.00000000000000000000000000001"), "f")
    request["tolerance_vnd_per_share"] = "1"
    solver = build_vietnam_reverse_dcf(request)["solver"]
    assert solver["status"] == "outside_bracket"
    assert solver["implied_terminal_growth"] is None
