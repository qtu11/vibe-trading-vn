"""Run the Vietnam equity council and package its verdict for chat.

``run_swarm`` alone returns a long prose report whose numbers the chat gate
cannot check and whose sources the session ledger never saw.  This wrapper
keeps the same six-role preset but adds three things the chat path needs:

* an **observed snapshot** fetched through the same loader ``get_market_data``
  uses, so the stop/entry/target checks are anchored to real bars;
* a **deterministic chart** built from those bars, never from a model sketch;
* a **normalized verdict** from :mod:`src.tools.council_contract`, marked
  ``reported_by_council`` because swarm workers have no source ledger of
  their own.

The result carries one ready-to-paste ``council`` fenced block.  The block is
language-tagged code, so the grounding gate ignores the JSON inside it, while
the frontend renders the verdict, the debate columns and the chart.  The
wrapper deliberately does not copy the council's ``[S#]`` refs into the main
session ledger: a model-reported URL must not become a citable source.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping

from src.agent.tools import BaseTool
from src.market_data import fetch_market_data
from src.tools.council_contract import (
    ObservedSnapshot,
    evaluate_verdict,
    extract_verdict,
)
from src.tools.price_chart_tool import _rows_of, build_chart_spec

_PRESET = "vietnam_equity_council"
_MARKET = "Việt Nam (HOSE)"
_DEFAULT_HORIZON = "3-6 tháng"
_DEFAULT_LOOKBACK_DAYS = 420
_DEFAULT_BARS = 36
_MAX_BARS = 60
_DEBATE_SUMMARY_CHARS = 420
_PM_REPORT_CHARS = 1400
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,10}(?:\.VN)?$")

_COUNCIL_ROLES = {
    "fundamental_analyst": "Phân tích cơ bản",
    "technical_analyst": "Phân tích kỹ thuật",
    "bull_advocate": "Bên mua (Bull)",
    "bear_advocate": "Bên bán (Bear)",
    "risk_officer": "Quản trị rủi ro",
    "portfolio_manager": "Tổng giám đốc đầu tư (PM)",
}

_DISCLAIMER = (
    "Khuyến nghị tham khảo, không phải cam kết lợi nhuận. Giá có thể thay đổi "
    "sau ngày dữ liệu; kiểm tra lại thanh khoản, phí, thuế và điều kiện thị "
    "trường trước khi giao dịch."
)


def _error(message: str) -> str:
    return json.dumps({"ok": False, "error": message}, ensure_ascii=False)


def _normalize_vn_symbol(value: Any) -> tuple[str | None, str | None]:
    """Return a canonical ``.VN`` symbol, accepting a bare VN ticker."""
    if not isinstance(value, str) or not value.strip():
        return None, "missing required parameter: symbol"
    upper = value.strip().upper()
    if not _SYMBOL_RE.fullmatch(upper):
        return None, (
            f"invalid Vietnam symbol: {value!r}; expected a ticker such as "
            "FPT.VN or FPT"
        )
    if not upper.endswith(".VN"):
        upper += ".VN"
    return upper, None


def _clip(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _date_only(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return text[:10] if len(text) >= 10 and text[4] == "-" else text


def _snapshot_from_chart(code: str, chart: Mapping[str, Any]) -> ObservedSnapshot:
    """Derive the evaluation window from the same bars the chart displays."""
    bars = [bar for bar in chart.get("bars") or [] if isinstance(bar, Mapping)]
    closes = [bar.get("c") for bar in bars if isinstance(bar.get("c"), (int, float))]
    last_close = float(closes[-1]) if closes else 0.0

    def extreme(key: str) -> tuple[float | None, str | None]:
        values = [
            (float(bar[key]), _date_only(bar.get("t")))
            for bar in bars
            if isinstance(bar.get(key), (int, float))
        ]
        if not values:
            return None, None
        value, stamp = min(values) if key == "l" else max(values)
        return value, stamp

    window_low, low_date = extreme("l")
    window_high, high_date = extreme("h")
    return ObservedSnapshot(
        symbol=code,
        last_close=last_close,
        last_date=_date_only(bars[-1].get("t")) if bars else None,
        window_low=window_low,
        window_low_date=low_date,
        window_high=window_high,
        window_high_date=high_date,
        source=str(chart.get("source") or "") or None,
        currency=str(chart.get("currency") or "") or None,
        adjustment=str(chart.get("adjustment") or "") or None,
        bars=len(bars),
    )


def _snapshot_summary(snapshot: ObservedSnapshot) -> dict[str, Any]:
    return {
        "symbol": snapshot.symbol,
        "source": snapshot.source,
        "currency": snapshot.currency,
        "adjustment": snapshot.adjustment,
        "as_of": snapshot.last_date,
        "bars": snapshot.bars,
        "last_close": snapshot.last_close,
        "window_low": snapshot.low,
        "window_low_date": snapshot.window_low_date,
        "window_high": snapshot.high,
        "window_high_date": snapshot.window_high_date,
    }


def _debate(tasks: Any) -> list[dict[str, Any]]:
    """Project the six worker summaries into a bounded bull/bear record."""
    out: list[dict[str, Any]] = []
    if not isinstance(tasks, list):
        return out
    for task in tasks:
        if not isinstance(task, Mapping):
            continue
        agent_id = str(task.get("agent_id") or "")
        summary = task.get("summary") or ""
        error = task.get("error")
        out.append(
            {
                "id": task.get("id"),
                "agent_id": agent_id,
                "role": _COUNCIL_ROLES.get(agent_id, agent_id),
                "status": task.get("status"),
                "summary": _clip(summary, _DEBATE_SUMMARY_CHARS) if summary else "",
                "error": _clip(error, 300) if error else None,
            }
        )
    return out


def _run_swarm(
    prompt: str,
    variables: dict[str, str],
    *,
    max_llm_calls: int | None = None,
) -> dict[str, Any]:
    """Execute the preset through the normal swarm tool boundary.

    Kept as a module-level function so tests can replace the expensive LLM run
    without patching the whole tool class.  Shell tools follow the operator's
    global policy rather than being force-enabled by this wrapper.
    """
    from src.config.accessor import get_env_config
    from src.tools.swarm_tool import SwarmTool

    kwargs: dict[str, Any] = {
        "prompt": prompt,
        "preset_name": _PRESET,
        "variables": variables,
    }
    if max_llm_calls is not None:
        kwargs["max_llm_calls"] = max_llm_calls
    swarm = SwarmTool(
        include_shell_tools=get_env_config().api.vibe_trading_enable_shell_tools
    )
    raw = swarm.execute(**kwargs)
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {
            "status": "error",
            "error": f"swarm returned a non-JSON result: {str(raw)[:300]}",
        }
    return parsed if isinstance(parsed, dict) else {
        "status": "error",
        "error": "swarm returned a non-object result",
    }


def _council_block(
    *,
    code: str,
    snapshot: ObservedSnapshot,
    chart: dict[str, Any],
    evaluation: Mapping[str, Any],
    debate: list[dict[str, Any]],
    pm_report: str,
) -> dict[str, Any]:
    verdict = evaluation.get("verdict")
    sources = verdict.get("sources") if isinstance(verdict, Mapping) else []
    return {
        "type": "council",
        "version": 1,
        "symbol": code,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "snapshot": _snapshot_summary(snapshot),
        "chart": chart,
        "verdict": verdict,
        "evaluation": evaluation.get("evaluation") or {},
        "issues": evaluation.get("issues") or [],
        "actionable": bool(evaluation.get("actionable")),
        "trade_actionable": bool(evaluation.get("trade_actionable")),
        "blocked_reason": evaluation.get("blocked_reason"),
        # The existing actionability flags describe research consistency.
        # Daily historical bars do not provide an executable market quote.
        "execution_context": {
            "research_only": True,
            "execution_ready": False,
            "quote_status": "not_acquired",
            "order_book_status": "not_acquired",
            "session_status": "not_acquired",
            "holdings_status": "not_acquired",
            "order_type": None,
            "last_close_is_live_quote": False,
        },
        "debate": debate,
        "pm_report": pm_report,
        "sources": sources,
        "disclaimer": _DISCLAIMER,
    }


def _apply_vn_position_context(evaluation: dict[str, Any]) -> dict[str, Any]:
    """Keep generic short geometry out of a cash-equity reduction verdict."""
    verdict = evaluation.get("verdict")
    if not isinstance(verdict, Mapping) or verdict.get("stance") != "sell":
        return evaluation

    issue_code = "vn_sell_position_context_missing"
    issues = list(evaluation.get("issues") or [])
    if not any(issue.get("code") == issue_code for issue in issues):
        issues.append({
            "code": issue_code,
            "severity": "error",
            "message": (
                "Vietnam cash-equity SELL means reducing an existing position. "
                "Holdings and available-to-sell quantities have not been acquired; "
                "a new short order or a position reduction size cannot be inferred."
            ),
        })
    reasons = list(dict.fromkeys(
        reason.strip()
        for reason in str(evaluation.get("blocked_reason") or "").split(";")
        if reason.strip()
    ))
    if issue_code not in reasons:
        reasons.append(issue_code)
    metrics = dict(evaluation.get("evaluation") or {})
    for field in (
        "risk_per_share", "reward_per_share", "risk_reward",
        "stop_distance_pct", "sizing",
    ):
        metrics[field] = None
    return {
        **evaluation,
        "actionable": False,
        "trade_actionable": False,
        "issues": issues,
        "blocked_reason": "; ".join(reasons),
        "evaluation": metrics,
    }


class ResearchCouncilTool(BaseTool):
    """Run the Vietnam equity council and return a renderable verdict block."""

    name = "run_research_council"
    description = (
        "Run a six-role Vietnam equity research council (fundamental, technical, "
        "bull, bear, risk, PM) for one .VN symbol. It fetches observed OHLCV, "
        "runs the vietnam_equity_council preset, validates the PM verdict "
        "against those bars, and returns a ready-to-paste 'council' fenced "
        "block with the debate, deterministic chart, verdict and evaluation. "
        "Paste the fence verbatim. Council [S#] refs are self-reported and are "
        "not session sources: never copy them into prose as [S#] citations. "
        "Use this only when the user asks for the council/debate; for a simple "
        "quote or chart use get_market_data or build_price_chart."
    )
    parameters = {
        "type": "object",
        "properties": {
            "symbol": {
                "type": "string",
                "description": "Vietnam ticker such as 'FPT.VN' or 'FPT'.",
            },
            "horizon": {
                "type": "string",
                "description": "Investment horizon, e.g. '3-6 tháng'. Default '3-6 tháng'.",
                "default": _DEFAULT_HORIZON,
            },
            "chart_bars": {
                "type": "integer",
                "description": (
                    f"Recent daily bars in the attached chart (12-{_MAX_BARS}). "
                    f"Default {_DEFAULT_BARS}."
                ),
                "default": _DEFAULT_BARS,
            },
            "max_llm_calls": {
                "type": "integer",
                "minimum": 1,
                "description": "Optional cap on swarm LLM calls including retries.",
            },
        },
        "required": ["symbol"],
    }
    is_readonly = False
    repeatable = True

    def execute(self, **kwargs: Any) -> str:
        """Fetch bars, run the council, validate and render the verdict."""
        code, symbol_error = _normalize_vn_symbol(
            kwargs.get("symbol") or kwargs.get("code")
        )
        if symbol_error or code is None:
            return _error(symbol_error or "invalid symbol")

        horizon = _clip(kwargs.get("horizon") or _DEFAULT_HORIZON, 80)
        try:
            chart_bars = int(kwargs.get("chart_bars", _DEFAULT_BARS))
        except (TypeError, ValueError, OverflowError):
            chart_bars = _DEFAULT_BARS
        chart_bars = min(max(chart_bars, 12), _MAX_BARS)

        max_llm_calls: int | None = None
        raw_cap = kwargs.get("max_llm_calls")
        if raw_cap is not None and raw_cap != "":
            try:
                max_llm_calls = max(1, int(raw_cap))
            except (TypeError, ValueError, OverflowError):
                return _error("max_llm_calls must be a positive integer")

        end = date.today()
        start = end - timedelta(days=_DEFAULT_LOOKBACK_DAYS)
        try:
            payload = fetch_market_data(
                codes=[code],
                start_date=start.isoformat(),
                end_date=end.isoformat(),
                source="auto",
                interval="1D",
                max_rows=0,
                include_provenance=True,
            )
        except Exception as exc:  # noqa: BLE001 - surface any loader failure
            return _error(f"market data fetch failed for {code}: {exc}")
        if not isinstance(payload, dict):
            return _error(f"market data fetch returned no payload for {code}")

        rows = _rows_of(payload.get(code))
        if not rows:
            unresolved = payload.get("_unresolved")
            detail = f" ({', '.join(map(str, unresolved))})" if unresolved else ""
            return _error(f"no OHLCV bars for {code}{detail}")

        provenance = payload.get("_provenance")
        provenance = provenance if isinstance(provenance, dict) else {}
        chart = build_chart_spec(
            code,
            rows,
            provenance=provenance.get(code),
            interval="1D",
            max_bars=chart_bars,
            source="auto",
            requested_start=start.isoformat(),
            requested_end=end.isoformat(),
        )
        if chart is None:
            return _error(f"no dated OHLCV bars for {code}")

        snapshot = _snapshot_from_chart(code, chart)
        prompt = (
            f"Chủ trì hội đồng đầu tư cho {code} ({_MARKET}) trong {horizon}. "
            "Điều tra bằng công cụ, tranh luận bull/bear, kiểm soát rủi ro và "
            "xuất verdict JSON đúng schema ở cuối báo cáo PM."
        )
        try:
            run = _run_swarm(
                prompt,
                {"target": code, "market": _MARKET, "horizon": horizon},
                max_llm_calls=max_llm_calls,
            )
        except Exception as exc:  # noqa: BLE001 - the swarm layer is optional
            return _error(f"council run failed to start for {code}: {exc}")

        status = str(run.get("status") or "error")
        run_id = run.get("run_id")
        if status in {"error", "failed", "cancelled"} or run.get("error"):
            return json.dumps(
                {
                    "ok": False,
                    "error": str(run.get("error") or f"council run {status}"),
                    "status": status,
                    "run_id": run_id,
                    "symbol": code,
                },
                ensure_ascii=False,
            )
        if status != "completed":
            return json.dumps(
                {
                    "ok": False,
                    "error": (
                        f"council run {run_id or ''} is still {status}; "
                        "re-invoke run_swarm with the same preset and target "
                        "or read the run status before asking for a verdict"
                    ),
                    "status": status,
                    "run_id": run_id,
                    "symbol": code,
                },
                ensure_ascii=False,
            )

        report = str(run.get("final_report") or "")
        raw_verdict, extraction_issues = extract_verdict(report)
        evaluation = _apply_vn_position_context(evaluate_verdict(
            raw_verdict,
            observed=snapshot,
            extraction_issues=extraction_issues,
        ))
        debate = _debate(run.get("tasks"))
        block = _council_block(
            code=code,
            snapshot=snapshot,
            chart=chart,
            evaluation=evaluation,
            debate=debate,
            pm_report=_clip(report, _PM_REPORT_CHARS),
        )
        fence = "```council\n" + json.dumps(
            block, ensure_ascii=False, separators=(",", ":")
        ) + "\n```"
        return json.dumps(
            {
                "ok": True,
                "status": status,
                "run_id": run_id,
                "symbol": code,
                "actionable": block["actionable"],
                "trade_actionable": block["trade_actionable"],
                "blocked_reason": block["blocked_reason"],
                "execution_context": block["execution_context"],
                "fence": fence,
                "snapshot": block["snapshot"],
                "sources": block["sources"],
                "note": (
                    "Paste the council fence verbatim. Its [S#] refs are the "
                    "council's self-reported sources, not session sources; do "
                    "not reuse them as prose citations. Actionability checks "
                    "research consistency only; execution_ready remains false "
                    "without a live quote, order book, session and holdings context."
                ),
            },
            ensure_ascii=False,
        )
