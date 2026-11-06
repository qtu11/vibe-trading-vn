"""Train-prefix calibration and causal ATR-normalized SMA-slope regime state."""

from datetime import timedelta
import math

import numpy as np
import pandas as pd
from pydantic import Field, field_validator, model_validator

from .models import digest, number
from .research_dataset import BAR_INTERVAL_SECONDS, ClosedBarDataset
from .research_indicators import atr_series

_STATES = ("unknown", "neutral", "uptrend", "downtrend")


class RegimeRequest(ClosedBarDataset):
    sma_window: int = Field(ge=2, le=200, strict=True)
    slope_bars: int = Field(ge=1, le=100, strict=True)
    atr_period: int = Field(ge=2, le=200, strict=True)
    train_end_index: int = Field(ge=1, le=1998, strict=True)
    entry_quantile: float = Field(ge=.5, le=.99, allow_inf_nan=False)
    exit_quantile: float = Field(ge=.01, le=.8, allow_inf_nan=False)
    min_dwell_bars: int = Field(ge=1, le=200, strict=True)
    offset: int = Field(default=0, ge=0, le=2000, strict=True)
    limit: int = Field(default=50, ge=1, le=100, strict=True)

    @field_validator("entry_quantile", "exit_quantile", mode="before")
    @classmethod
    def quantile(cls, value):
        return float(number(value))

    @model_validator(mode="after")
    def split_and_thresholds(self):
        if self.train_end_index >= len(self.bars) - 1:
            raise ValueError("train_end_index must leave at least one later evaluation bar")
        if self.exit_quantile >= self.entry_quantile:
            raise ValueError("exit_quantile must be smaller than entry_quantile")
        return self


def _finite(value):
    return float(value) if math.isfinite(value) else None


def _step(state, slope, entry, exit_threshold, *, index, changed_at, dwell):
    """Hysteresis with elapsed closed-bar dwell; unknown resets immediately."""
    if slope is None:
        return "unknown", "feature_unavailable", index, 0
    if state == "uptrend":
        desired = "downtrend" if slope <= -entry else "neutral" if slope <= exit_threshold else state
    elif state == "downtrend":
        desired = "uptrend" if slope >= entry else "neutral" if slope >= -exit_threshold else state
    else:
        desired = "uptrend" if slope >= entry else "downtrend" if slope <= -entry else "neutral"
    remaining = max(0, dwell - (index - changed_at)) if state != "unknown" else 0
    if desired != state and remaining:
        return state, "minimum_dwell_hold", changed_at, remaining
    if desired != state:
        return desired, "threshold_transition", index, dwell
    return state, "hysteresis_hold", changed_at, remaining


def regime(request: RegimeRequest) -> dict:
    """Replay every closed bar; only the initial training prefix calibrates thresholds."""
    rows = [bar.model_dump(mode="json") for bar in request.bars]
    identity = {key: getattr(request, key) for key in ("source", "symbol", "timeframe", "price_basis", "dataset_revision")}
    config = request.model_dump(mode="json", exclude={"bars", "offset", "limit"})
    config_hash = digest({"variant": "atr_normalized_sma_slope_regime_v1", **config})
    close = pd.Series([row["close"] for row in rows], dtype=float)
    sma = close.rolling(request.sma_window, min_periods=request.sma_window).mean()
    slope = (sma - sma.shift(request.slope_bars)) / request.slope_bars
    atr = atr_series(rows, request.atr_period)
    features = [float(value / scale) if math.isfinite(value) and math.isfinite(scale) and scale > 0 else None
                for value, scale in zip(slope, atr)]
    fit_values = [abs(value) for value in features[:request.train_end_index + 1] if value is not None]
    entry = exit_threshold = None
    code = None
    if len(fit_values) < 8:
        code = "INSUFFICIENT_CALIBRATION_FEATURES"
    else:
        fitted = np.quantile(fit_values, [request.entry_quantile, request.exit_quantile], method="linear")
        entry, exit_threshold = (float(value) for value in fitted)
        if not (math.isfinite(entry) and math.isfinite(exit_threshold) and entry > exit_threshold > 0):
            entry = exit_threshold = None
            code = "DEGENERATE_CALIBRATION_THRESHOLDS"
    interval = timedelta(seconds=BAR_INTERVAL_SECONDS[request.timeframe])
    available = lambda index: (request.bars[index].time + interval).isoformat().replace("+00:00", "Z")
    fit_input_hash = digest({**identity, "bars": rows[:request.train_end_index + 1]})
    threshold_hash = digest({"fit_input_hash": fit_input_hash, "entry": entry, "exit": exit_threshold,
                             "entry_quantile": request.entry_quantile, "exit_quantile": request.exit_quantile})
    calibration = {
        "status": "ok" if code is None else "insufficient", "code": code,
        "train_start_index": 0, "train_end_index": request.train_end_index,
        "last_training_available_at": available(request.train_end_index),
        "first_decision_available_at": available(request.train_end_index + 1), "feature_count": len(fit_values),
        "entry_threshold": entry, "exit_threshold": exit_threshold,
        "fit_input_hash": fit_input_hash, "threshold_hash": threshold_hash,
    }
    timeline, state, changed_at = [], "unknown", request.train_end_index + 1
    summary = {key + "_bars": 0 for key in _STATES}
    summary.update(evaluated_bars=0, transition_count=0, dwell_held_bars=0)
    prefix_hash = digest(identity)
    prior_state_hash = digest({"config_hash": config_hash, "state": "unknown"})
    for index, row in enumerate(rows):
        prefix_hash = digest({"previous": prefix_hash, "bar": row})
        before = state
        if index <= request.train_end_index:
            state, reason, remaining = "unknown", "training_only", 0
        elif code is not None:
            state, reason, remaining = "unknown", "calibration_unavailable", 0
        else:
            state, reason, changed_at, remaining = _step(state, features[index], entry, exit_threshold,
                index=index, changed_at=changed_at, dwell=request.min_dwell_bars)
        evaluation = index > request.train_end_index
        transition = evaluation and state != before
        item = {
            "index": index, "time": row["time"], "available_at": available(index),
            "phase": "evaluation" if evaluation else "training", "sma": _finite(sma.iloc[index]),
            "atr": _finite(atr.iloc[index]), "slope_per_bar": _finite(slope.iloc[index]),
            "normalized_slope": features[index], "regime": state, "reason": reason,
            "transition": transition, "dwell_remaining": remaining, "input_prefix_hash": prefix_hash,
        }
        if features[index] is None and evaluation and code is None:
            item["reason"] = "nonpositive_atr" if math.isfinite(atr.iloc[index]) and atr.iloc[index] <= 0 else "feature_warmup"
        # Training rows cannot depend on fitted thresholds that became known later.
        item["state_hash"] = digest({"previous": prior_state_hash, "row": item,
                                    "config_hash": config_hash, "threshold_hash": threshold_hash if evaluation else None})
        prior_state_hash = item["state_hash"]
        timeline.append(item)
        if evaluation:
            summary["evaluated_bars"] += 1
            summary[state + "_bars"] += 1
            summary["transition_count"] += int(transition)
            summary["dwell_held_bars"] += int(reason == "minimum_dwell_hold")
    page = timeline[request.offset:request.offset + request.limit]
    next_offset = request.offset + len(page)
    from .experiments import engine_manifest

    return {
        "status": "ok" if code is None else "incomplete", "code": code,
        "experiment_kind": "causal_atr_sma_regime", "regime_version": 1,
        "source_verification": "caller_supplied_unverified", "config": config, "config_hash": config_hash,
        "producer": engine_manifest(experiment_kind="causal_atr_sma_regime"),
        "dataset_hash": digest({**identity, "bars": rows}), "calibration": calibration, "summary": summary,
        "latest": timeline[-1], "timeline": page,
        "paging": {"offset": request.offset, "limit": request.limit, "total": len(timeline), "returned": len(page),
                   "next_offset": next_offset if next_offset < len(timeline) else None},
        "methodology": {
            "feature": "((trailing_SMA_t_minus_SMA_t_minus_slope_bars)/slope_bars)/Wilder_ATR_t",
            "atr_seed": "mean_first_atr_period_true_ranges_then_alpha_1_over_period_recursion",
            "first_true_range": "high_minus_low", "warmup": "unknown_until_both_slope_and_positive_ATR_exist",
            "calibration": "linear_quantiles_of_absolute_finite_normalized_slopes_in_initial_training_prefix_only",
            "minimum_training_features": 8, "smoothing": "trailing_only_no_centered_windows",
            "dwell": "minimum_elapsed_closed_bar_intervals_since_last_state_transition; unknown_resets_immediately",
            "neutral": "no_entry_threshold_crossing_under_this_heuristic_not_a_verified_sideways_market",
            "availability": "caller_declared_bar_open_plus_timeframe_assumed_known_at_close_not_verified_ingest_time",
            "replay": "full_supplied_prefix_replay_no_external_state_or_live_monitor",
            "excluded": ["ADX", "confirmed_swing_sequence", "multi_timeframe_consensus", "trade_signals", "PnL", "forecast", "broker_execution"],
        },
    }
