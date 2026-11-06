"""Seeded, within-fold moving-block resampling of frozen OOS trade returns."""

import math

import numpy as np
from pydantic import Field

from src.quantlib.risk import drawdown_series

from .models import Contract, digest
from .walk_forward import WalkForwardRequest, _trade_outcomes, walk_forward

_QUANTILES = {"p05": .05, "p25": .25, "p50": .5, "p75": .75, "p95": .95}


class TradePathsRequest(Contract):
    research: WalkForwardRequest
    seed: int = Field(ge=0, le=4294967295, strict=True)
    simulations: int = Field(ge=100, le=2000, strict=True)
    block_length: int = Field(ge=2, le=64, strict=True)


def _block_indices(count: int, length: int, rng) -> np.ndarray:
    """Uniformly sample overlapping noncircular blocks, truncate the final block."""
    starts = rng.integers(0, count - length + 1, size=math.ceil(count / length))
    return (starts[:, None] + np.arange(length)).reshape(-1)[:count]


def _equity_path(returns) -> tuple[np.ndarray, dict]:
    values = np.asarray(returns, dtype=float)
    if not np.isfinite(values).all() or (values <= -1).any():
        raise ValueError("INVALID_RESEARCH_EQUITY")
    with np.errstate(over="ignore", under="ignore", invalid="ignore"):
        equity = np.concatenate(([1.0], np.cumprod(1 + values)))
    # quantlib deliberately drops nonfinite observations for some callers;
    # this study must reject the entire path before that cleaning can occur.
    if not np.isfinite(equity).all() or (equity <= 0).any():
        raise ValueError("INVALID_RESEARCH_EQUITY")
    return equity, {
        "trade_count": len(values), "net_return": float(equity[-1] - 1),
        "max_drawdown": float(drawdown_series(equity).max()),
    }


def _quantiles(values) -> dict:
    return {key: float(value) for key, value in zip(_QUANTILES, np.quantile(values, list(_QUANTILES.values()), method="linear"))}


def trade_paths(request: TradePathsRequest) -> dict:
    """Run base walk-forward once, then resample fixed-cost OOS trades only.

    Blocks preserve adjacency within each sampled block of a fold; they do not
    retain every dependency, calendar spacing, or dependence across fold edges.
    """
    base = walk_forward(request.research)
    rows = [bar.model_dump(mode="json") for bar in request.research.bars]
    frozen, folds, fold_returns = [], [], []
    for source in base["folds"]:
        item = {"fold": source["fold"], "selected": source.get("selected"), "out_of_sample": source["out_of_sample"]}
        if source["status"] != "ok" or source.get("selected") is None:
            item.update(status="error", code=source.get("code", "BASE_FOLD_INCOMPLETE"), outcomes=None)
            folds.append({"fold": source["fold"], "status": "error", "code": "BASE_FOLD_INCOMPLETE", "trade_count": None})
        else:
            bounds, selected = source["out_of_sample"], source["selected"]
            indices = range(bounds["signal_start_index"], bounds["signal_end_index"] + 1)
            eligible, outcomes = _trade_outcomes(rows, indices, selected["fast"], selected["slow"], request.research.strategy)
            item.update(status="ok", eligible_signal_count=eligible, outcomes=outcomes)
            count = len(outcomes)
            enough = count == 0 or count >= request.block_length
            folds.append({
                "fold": source["fold"], "status": "ok" if enough else "error",
                "code": None if enough else "INSUFFICIENT_FOLD_TRADES", "trade_count": count,
                "block_length": request.block_length, "possible_block_starts": max(0, count - request.block_length + 1),
                "frozen_trade_hash": digest(item),
            })
            fold_returns.append(np.asarray([outcome["gross_return"] - request.research.round_trip_cost_bps / 10000
                                            for outcome in outcomes], dtype=float))
        frozen.append(item)
    tape_hash = digest({"dataset_hash": base["dataset_hash"], "cost_bps": request.research.round_trip_cost_bps, "folds": frozen})
    config = request.model_dump(mode="json", exclude={"research"})
    result = {
        "status": "incomplete", "experiment_kind": "frozen_oos_moving_block_bootstrap", "trade_paths_version": 1,
        "config_hash": digest({"base_config_hash": base["config_hash"], "sampling": config, "version": 1}),
        "frozen_oos_tape_hash": tape_hash, "config": config, "base_walk_forward": base, "folds": folds,
        "actual_path": None, "simulation_summary": None, "display_paths": None,
        "methodology": {
            "method": "noncircular_overlapping_moving_block_bootstrap",
            "sampling_unit": "chronological_oos_trade_index_within_each_fold",
            "selection": "fit_once_at_base_cost_then_freeze_parameters_signals_outcomes",
            "cost": "base_constant_round_trip_bps_already_deducted_once_per_trade",
            "fold_policy": "independent_within_fold_blocks_preserve_each_fold_trade_count_no_cross_fold_blocks",
            "zero_trade_fold": "known_empty_fold_retained_without_block_draws",
            "block_policy": "uniform_start_with_replacement_concatenate_then_truncate_final_block",
            "rng": "numpy.Generator_PCG64_simulation_outer_fold_inner",
            "quantile_method": "linear", "equity": "initial_one_compounded_unlevered_trade_returns",
            "max_drawdown": "positive_loss_fraction_including_initial_equity",
            "annualization": None, "predictive_probability": False,
            "source_verification": "caller_supplied_unverified",
            "limitations": [
                "Empirical resampling conditions on the observed OOS trade sample, fixed selection and caller costs; it is not future-profit probability.",
                "Caller chooses block length; no optimal length, stationarity, calibration or full dependence preservation is established.",
                "Blocks retain adjacency only inside a block; sampling is independent across fold boundaries and ignores calendar spacing and idle bars.",
                "No permutation p-value, Sharpe annualization, broker fills, dynamic spreads, SL/TP, swap, margin or stop-out simulation.",
                "Any numeric path failure suppresses all simulation quantiles instead of dropping failed paths.",
            ],
        },
    }
    if base["status"] != "ok":
        return dict(result, code="BASE_WALK_FORWARD_INCOMPLETE")
    if any(fold["status"] != "ok" for fold in folds):
        return dict(result, code="INSUFFICIENT_FOLD_TRADES")
    total = sum(len(values) for values in fold_returns)
    if total == 0:
        return dict(result, code="NO_OOS_TRADES")
    try:
        actual_equity, actual = _equity_path(np.concatenate(fold_returns))
    except ValueError:
        return dict(result, code="INVALID_RESEARCH_EQUITY")
    result["actual_path"] = actual
    rng = np.random.Generator(np.random.PCG64(request.seed))
    paths = np.empty((request.simulations, total + 1), dtype=float)
    terminal, drawdowns, failures = [], [], []
    for simulation in range(request.simulations):
        sampled = [values[_block_indices(len(values), request.block_length, rng)] for values in fold_returns if len(values)]
        try:
            equity, metrics = _equity_path(np.concatenate(sampled))
        except ValueError:
            failures.append(simulation + 1)
            continue
        paths[simulation] = equity
        terminal.append(metrics["net_return"])
        drawdowns.append(metrics["max_drawdown"])
    summary = {
        "requested_simulations": request.simulations, "valid_simulations": len(terminal), "invalid_simulations": len(failures),
        "terminal_net_return_quantiles": None, "max_drawdown_quantiles": None,
        "failure_examples": [{"simulation": index, "code": "INVALID_RESEARCH_EQUITY"} for index in failures[:20]],
        "failure_examples_truncated": len(failures) > 20,
    }
    result["simulation_summary"] = summary
    if failures:
        return dict(result, code="SIMULATION_NUMERIC_FAILURE")
    summary.update(terminal_net_return_quantiles=_quantiles(terminal), max_drawdown_quantiles=_quantiles(drawdowns))
    steps = np.unique(np.linspace(0, total, min(total + 1, 100)).astype(int))
    samples = np.unique(np.linspace(0, request.simulations - 1, min(20, request.simulations)).astype(int))
    bands = np.quantile(paths[:, steps], list(_QUANTILES.values()), axis=0, method="linear")
    result["display_paths"] = {
        "steps": steps.tolist(), "actual": actual_equity[steps].tolist(),
        "bands": {name: values.tolist() for name, values in zip(_QUANTILES, bands)},
        "samples": paths[np.ix_(samples, steps)].tolist(), "sample_simulation_numbers": (samples + 1).tolist(),
        "display_sampled": True, "statistics_use_all_simulations": True,
    }
    return dict(result, status="ok", code=None)
