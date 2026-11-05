"""Bounded role views of one immutable evidence snapshot; no extra model calls."""

import json


def role_payload(evidence, quote, candidates, reports, refs, *, role, task, entry_mode, forecast_timeframe):
    raw = role == "technical"
    frames = {}
    for frame, panel in evidence["timeframes"].items():
        view = dict(panel)
        if not raw and isinstance(view.get("price_action"), dict):
            view["price_action"] = {k: v for k, v in view["price_action"].items()
                                    if k not in {"recent_candles", "recent_candle_columns"}}
        frames[frame] = view
    # A stable common prefix allows provider caching where supported. Role/task
    # and growing reports follow the common evidence, not the other way around.
    return {
        "market": {"timeframes": frames, "macro": evidence["macro"]},
        "quote": {k: quote[k] for k in ("bid", "ask", "timestamp")},
        "candidates": candidates,
        "requested_entry_mode": entry_mode, "requested_forecast_timeframe": forecast_timeframe,
        "context_policy": {"raw_closed_ohlc_included": raw,
            "note": "Technical reads actual OHLC. Other roles use the same snapshot's computed evidence and analyst reports; do not claim to have inspected omitted candles."},
        "role": role, "task": task,
        "reports": {name: {k: v for k, v in report.items() if k in {
            "stance", "entry_mode", "summary", "counterargument", "evidence_refs", "veto", "forecast"}}
            for name, report in reports.items()},
        "allowed_refs": sorted(refs),
    }


def encode_payload(payload):
    return json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
