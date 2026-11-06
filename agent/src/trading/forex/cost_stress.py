"""Frozen-OOS spread stress for supplied mid-bar SMA/EMA research."""

import math

from pydantic import Field, field_validator, model_validator

from .models import Contract, digest, number
from .walk_forward import WalkForwardRequest, _metrics_from_outcomes, _trade_outcomes, walk_forward


class CostStressRequest(Contract):
    research: WalkForwardRequest
    spread_bps: float = Field(ge=0, le=1000, allow_inf_nan=False)
    commission_bps: float = Field(ge=0, le=1000, allow_inf_nan=False)
    slippage_bps: float = Field(ge=0, le=1000, allow_inf_nan=False)
    gap_bps: float = Field(ge=0, le=1000, allow_inf_nan=False)

    @field_validator("spread_bps", "commission_bps", "slippage_bps", "gap_bps", mode="before")
    @classmethod
    def cost(cls, value):
        return float(number(value))

    @model_validator(mode="after")
    def base_cost(self):
        total = math.fsum((self.spread_bps, self.commission_bps, self.slippage_bps, self.gap_bps))
        if not math.isclose(total, self.research.round_trip_cost_bps, rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError("Explicit round-trip components must sum to research.round_trip_cost_bps")
        return self


def _arithmetic(outcomes, cost_bps, fixed_bps):
    count = len(outcomes)
    if not count:
        return {
            "gross_expectancy_bps": None, "net_expectancy_bps": None,
            "arithmetic_break_even_all_in_cost_bps": None,
            "arithmetic_break_even_spread_bps": None, "no_trade_reason": "NO_OOS_TRADES",
        }
    gross = math.fsum(item["gross_return"] for item in outcomes) / count * 10000
    return {
        "gross_expectancy_bps": gross, "net_expectancy_bps": gross - cost_bps,
        "arithmetic_break_even_all_in_cost_bps": gross,
        "arithmetic_break_even_spread_bps": gross - fixed_bps,
        "no_trade_reason": None,
    }


def cost_stress(request: CostStressRequest) -> dict:
    """Fit once at base cost, then price one immutable OOS trade tape three ways.

    Every component is a caller assumption in bps of each trade's notional.
    Gap is a fixed adverse cash charge, not a replay of a market-price gap.
    """
    base = walk_forward(request.research)
    rows = [bar.model_dump(mode="json") for bar in request.research.bars]
    fixed = math.fsum((request.commission_bps, request.slippage_bps, request.gap_bps))
    frozen = []
    all_outcomes = []
    for fold in base["folds"]:
        selected = fold.get("selected")
        item = {"fold": fold["fold"], "selected": selected, "out_of_sample": fold["out_of_sample"]}
        # A failed base fold must never silently disappear from a stress aggregate.
        if fold["status"] != "ok" or selected is None:
            item.update(status="error", code=fold.get("code", "BASE_FOLD_INCOMPLETE"), eligible=None, outcomes=None)
        else:
            bounds = fold["out_of_sample"]
            indices = range(bounds["signal_start_index"], bounds["signal_end_index"] + 1)
            eligible, outcomes = _trade_outcomes(rows, indices, selected["fast"], selected["slow"], request.research.strategy)
            item.update(status="ok", eligible=eligible, outcomes=outcomes)
            all_outcomes.extend(outcomes)
        frozen.append(item)
    tape_hash = digest({"dataset_hash": base["dataset_hash"], "folds": frozen})
    scenarios = []
    complete_tape = base["status"] == "ok" and all(fold["status"] == "ok" for fold in frozen)
    for multiplier in (1, 2, 3):
        spread = request.spread_bps * multiplier
        total = math.fsum((spread, fixed))
        folds, equity = [], 1.0
        for frozen_fold in frozen:
            fold = {"fold": frozen_fold["fold"], "selected": frozen_fold["selected"]}
            outcomes = frozen_fold["outcomes"]
            if outcomes is None:
                fold.update(status="error", code="BASE_FOLD_INCOMPLETE", metrics=None)
            else:
                metrics = _arithmetic(outcomes, total, fixed)
                metrics["trade_count"] = len(outcomes)
                try:
                    metrics.update(_metrics_from_outcomes(frozen_fold["eligible"], outcomes, total))
                    combined = equity * (1 + metrics["net_return"])
                    if not math.isfinite(combined):
                        raise ValueError("Combined research equity exceeded numeric bounds")
                    equity = combined
                    fold.update(status="ok", metrics=metrics)
                except ValueError:
                    # Arithmetic evidence survives bankruptcy/overflow; compounded equity does not.
                    metrics["net_return"] = None
                    fold.update(status="error", code="INVALID_RESEARCH_EQUITY", metrics=metrics)
            folds.append(fold)
        complete = complete_tape and all(fold["status"] == "ok" for fold in folds)
        aggregate = None
        if complete_tape:
            aggregate = {
                **_arithmetic(all_outcomes, total, fixed), "trade_count": len(all_outcomes),
                "sample_count": sum(fold["out_of_sample"]["sample_count"] for fold in frozen),
                "net_return": equity - 1 if complete else None,
            }
        scenarios.append({
            "spread_multiplier": multiplier, "spread_bps": spread,
            "commission_bps": request.commission_bps, "slippage_bps": request.slippage_bps,
            "gap_bps": request.gap_bps, "round_trip_cost_bps": total,
            "frozen_oos_tape_hash": tape_hash, "status": "ok" if complete else "incomplete",
            "folds": folds, "out_of_sample_metrics": aggregate,
        })
    config = request.model_dump(mode="json", exclude={"research"})
    return {
        "status": "ok" if all(item["status"] == "ok" for item in scenarios) else "incomplete",
        "experiment_kind": "frozen_oos_cost_stress", "cost_stress_version": 1,
        "selection_policy": "fit_once_at_base_cost_then_freeze_oos_parameters_signals_outcomes",
        "stress_grid": "base_2x_3x_spread_fixed_other_components",
        "frozen_oos_tape_hash": tape_hash,
        "config_hash": digest({"base_config_hash": base["config_hash"], "components": config, "version": 1}),
        "base_walk_forward": base, "scenarios": scenarios,
        "methodology": {
            "cost_basis": "round_trip_bps_of_each_unlevered_trade_notional",
            "price_basis": "mid", "cost_calibration": "caller_assumption_unverified",
            "signal_reselection_per_scenario": False,
            "break_even": "arithmetic_mean_gross_trade_return_bps_not_compounded_equity_root",
            "negative_break_even": "no_nonnegative_cost_or_spread_can_meet_this_arithmetic_break_even",
            "gap": "constant_adverse_charge_not_price_gap_replay",
            "excluded": ["bid_ask_ticks", "variable_spread", "dynamic_commission", "latency", "swap", "broker_execution"],
        },
    }
