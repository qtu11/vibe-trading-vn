"""Past-only SMA/EMA parameter research on supplied complete mid-price OHLC."""

import math
from datetime import datetime, timedelta
from typing import Literal

from pydantic import Field, field_validator, model_validator

from src.quantlib.crossvalidation import purged_walk_forward_splits

from .models import Contract, digest, number
from .runner import crossover
from .research_dataset import BAR_INTERVAL_SECONDS as _INTERVALS, ClosedBarDataset, ResearchBar
from .research_signals import ema_crossovers

_VARIANT = "sma_crossover_next_open_one_bar_v1"
_EMA_VARIANT = "ema_crossover_next_open_one_bar_v1"


class SMAParameters(Contract):
    """Common windows for both variants; retain the established contract name."""

    fast: int = Field(ge=2, le=100, strict=True)
    slow: int = Field(ge=3, le=200, strict=True)

    @model_validator(mode="after")
    def windows(self):
        if self.fast >= self.slow:
            raise ValueError("fast must be smaller than slow")
        return self


class WalkForwardRequest(ClosedBarDataset):
    strategy: Literal["sma_crossover", "ema_crossover"] = "sma_crossover"
    candidates: tuple[SMAParameters, ...] = Field(min_length=1, max_length=16)
    n_blocks: int = Field(default=4, ge=2, le=8, strict=True)
    round_trip_cost_bps: float = Field(ge=0, le=1000, allow_inf_nan=False)

    @field_validator("round_trip_cost_bps", mode="before")
    @classmethod
    def cost(cls, value):
        return float(number(value))

    @model_validator(mode="after")
    def unique_candidates(self):
        if len({(pair.fast, pair.slow) for pair in self.candidates}) != len(self.candidates):
            raise ValueError("Moving average candidates must be unique")
        return self


def _trade_outcomes(rows, indices, fast, slow, strategy="sma_crossover"):
    """Freeze causal crossover decisions and their one-bar gross outcomes."""
    outcomes, eligible = [], 0
    # Training indicator construction cannot inspect an OOS close, even when
    # its state would otherwise be causal. Labels remain the next bar only.
    ema_sides = None
    if strategy == "ema_crossover" and len(indices):
        ema_sides = ema_crossovers(rows[:int(max(indices)) + 1], fast, slow)
    for index in indices:
        if index < slow:
            continue
        eligible += 1
        side = ema_sides[index] if ema_sides is not None else crossover(rows[index - slow:index + 1], fast, slow)
        if side is None:
            continue
        outcome = rows[index + 1]
        gross = (outcome["close"] / outcome["open"] - 1) * (1 if side == "buy" else -1)
        outcomes.append({"signal_index": int(index), "side": side, "gross_return": gross})
    return eligible, outcomes


def _metrics_from_outcomes(eligible, outcomes, cost_bps):
    """The same accounting is shared by fitting and frozen-signal cost stress."""
    equity, gross_sum, net_sum, trades = 1.0, 0.0, 0.0, 0
    for outcome in outcomes:
        gross = outcome["gross_return"]
        net = gross - cost_bps / 10000
        equity *= 1 + net
        if net <= -1 or not math.isfinite(equity):
            raise ValueError("One-bar research equity exhausted or exceeded numeric bounds")
        gross_sum += gross
        net_sum += net
        trades += 1
    return {
        "eligible_signal_count": eligible,
        "trade_count": trades,
        "gross_return_sum": gross_sum,
        "net_return_sum": net_sum,
        "net_return": equity - 1,
    }


def _evaluate(rows, indices, fast, slow, cost_bps, strategy="sma_crossover"):
    eligible, outcomes = _trade_outcomes(rows, indices, fast, slow, strategy)
    return _metrics_from_outcomes(eligible, outcomes, cost_bps)


def _bounds(rows, indices, timeframe):
    start, end = int(indices[0]), int(indices[-1])
    outcome_close = datetime.fromisoformat(rows[end + 1]["time"].replace("Z", "+00:00")) + timedelta(seconds=_INTERVALS[timeframe])
    return {
        "signal_start_index": start,
        "signal_end_index": end,
        "signal_start": rows[start]["time"],
        "signal_end": rows[end]["time"],
        "outcome_start": rows[start + 1]["time"],
        "outcome_end": rows[end + 1]["time"],
        "outcome_available_at": outcome_close.isoformat().replace("+00:00", "Z"),
        "sample_count": len(indices),
    }


def walk_forward(request: WalkForwardRequest) -> dict:
    """Refit every fold from preceding labels; never accesses a service or account."""
    rows = [bar.model_dump(mode="json") for bar in request.bars]
    # Keep the established SMA response/config hash unchanged for old callers.
    excluded = {"bars", "strategy"} if request.strategy == "sma_crossover" else {"bars"}
    config = request.model_dump(mode="json", exclude=excluded)
    variant = _EMA_VARIANT if request.strategy == "ema_crossover" else _VARIANT
    identity = {name: config[name] for name in ("source", "symbol", "timeframe", "price_basis", "dataset_revision")}
    folds = []
    oos_equity, oos_trades, oos_samples = 1.0, 0, 0
    splits = purged_walk_forward_splits(
        len(rows) - 1, list(range(1, len(rows))), n_folds=request.n_blocks,
        embargo_fraction=0, expanding=True,
    )
    for fold_number, split in enumerate(splits, 1):
        fold = {
            "fold": fold_number, "status": "ok", "purged": split.purged, "embargoed": split.embargoed,
            "training": _bounds(rows, split.train, request.timeframe),
            "out_of_sample": _bounds(rows, split.test, request.timeframe),
            "training_data_hash": digest({**identity, "bars": rows[:int(split.train[-1]) + 2]}),
            "out_of_sample_input_hash": digest({**identity, "bars": rows[:int(split.test[-1]) + 2]}),
            "trials": [],
        }
        for candidate in request.candidates:
            trial = {"parameters": candidate.model_dump(), "status": "ok"}
            try:
                metrics = _evaluate(rows, split.train, candidate.fast, candidate.slow, request.round_trip_cost_bps, request.strategy)
                if metrics["trade_count"] == 0:
                    trial.update(status="error", code="NO_TRAIN_TRADES", error="No training crossover with a completed one-bar outcome")
                else:
                    trial["metrics"] = metrics
            except ValueError as exc:
                trial.update(status="error", code="INVALID_RESEARCH_EQUITY", error=str(exc))
            fold["trials"].append(trial)
        valid = [trial for trial in fold["trials"] if trial["status"] == "ok"]
        if not valid:
            fold.update(status="error", code="NO_VALID_TRAINING_TRIAL", selected=None, out_of_sample_metrics=None)
        else:
            selected = max(valid, key=lambda trial: (
                trial["metrics"]["net_return"], -trial["parameters"]["slow"], -trial["parameters"]["fast"],
            ))["parameters"]
            fold["selected"] = selected
            try:
                metrics = _evaluate(rows, split.test, selected["fast"], selected["slow"], request.round_trip_cost_bps, request.strategy)
                combined = oos_equity * (1 + metrics["net_return"])
                if not math.isfinite(combined):
                    raise ValueError("Combined research equity exceeded numeric bounds")
                fold["out_of_sample_metrics"] = metrics
                oos_equity, oos_trades, oos_samples = combined, oos_trades + metrics["trade_count"], oos_samples + len(split.test)
            except ValueError as exc:
                fold.update(status="error", code="INVALID_RESEARCH_EQUITY", error=str(exc), out_of_sample_metrics=None)
        folds.append(fold)
    complete = len(folds) == request.n_blocks - 1 and all(fold["status"] == "ok" for fold in folds)
    result = {
        "status": "ok" if complete else "incomplete",
        "strategy_variant": variant, "runner_parity": False, "bar_timestamp": "open",
        "source_verification": "caller_supplied_unverified",
        "config": config, "config_hash": digest({"variant": variant, **config}),
        "dataset_hash": digest({**identity, "bars": rows}),
        "selection_objective": "maximum_training_compounded_net_return",
        "tie_break": "smallest_slow_then_fast", "training_window": "expanding",
        "embargo_fraction": 0, "label_horizon_bars": 1,
        "execution_assumptions": {
            "signal": "completed_bar_close", "entry": "next_bar_mid_open", "exit": "same_next_bar_mid_close",
            "holding_bars": 1, "position": "one_unlevered_notional_per_crossover",
            "cost": "constant_round_trip_bps_deducted_per_trade",
            "cost_calibration": "caller_assumption_unverified",
            "excluded": ["bid_ask_ticks", "variable_spread", "swap", "latency", "sl_tp", "broker_execution"],
        },
        "folds": folds,
        "out_of_sample_metrics": {
            "net_return": oos_equity - 1, "trade_count": oos_trades, "sample_count": oos_samples,
        } if complete else None,
    }
    if request.strategy == "ema_crossover":
        result["indicator_methodology"] = {
            "type": "ema", "alpha": "2/(window+1)",
            "seed": "first_close_in_supplied_dataset",
            "warmup": "slow+1_completed_closes",
            "history_scope": "available_prefix_only",
            "reseed_between_folds": False,
        }
    return result
