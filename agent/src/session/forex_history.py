"""Replay an explicitly requested old WAIT explanation without a new model run.

Only validated structured report metadata qualifies; prose or injected history
tags cannot authorize this path. New analysis and trading keep their usual gates.
"""

import json
import re
import unicodedata

from src.core.state import RunStateStore
from src.session.context import _get
from src.trading.forex.council import TradePlan


def _fold(text):
    return "".join(c for c in unicodedata.normalize("NFKD", text.casefold()).replace("đ", "d")
                   if not unicodedata.combining(c))


def previous_wait_explanation(messages, prompt):
    query = _fold(prompt)
    if not (re.search(r"\b(?:vi sao|tai sao|giai thich|why|explain|reason)\b", query)
            and re.search(r"\b(?:bao cao cu|luot truoc|da luu|previous report|old report|last report)\b", query)
            and re.search(r"\b(?:cho|wait|dung ngoai)\b", query)):
        return None
    # Only negate explicit fetch/re-run requests. Unknown mixed intent falls
    # through to the ordinary agent; this is not a general negation parser.
    remaining = re.sub(r"\b(?:khong|do not|don't)\s+(?:lay gia moi|chay lai council|gui lenh|fetch new prices|rerun council|send orders)\b", "", query)
    if re.search(r"\b(?:hien tai|bay gio|hom nay|moi nhat|cap nhat|lay gia|mua ngay|ban ngay|vao lenh|mo lenh|dong lenh|gui lenh|gia vao|tp|sl|limit|market|now|current|updated|latest|new analysis|buy|sell|open|close|compare|so sanh|file|code|backtest)\b", remaining):
        return None
    named = {m.casefold() for m in re.findall(r"\b[A-Z]{6}[A-Za-z]?\b", prompt)}
    prior = messages[:-1] if messages and _get(messages[-1], "role") == "user" else messages
    for message in reversed(prior):
        metadata = _get(message, "metadata", {}) or {}
        if _get(message, "role") != "assistant" or not isinstance(metadata, dict):
            continue
        raw = metadata.get("forex_trade_plan")
        if not isinstance(raw, dict):
            continue
        try:
            plan = TradePlan.model_validate(raw)
        except (ValueError, TypeError):
            return None
        if named and named != {plan.symbol.casefold()}:
            continue
        if plan.status != "wait" or plan.recommendation != "wait":
            return None
        reports = [r for role in ("risk", "manager") for r in plan.reports if r.role == role]
        if not reports:
            return None
        vi = bool(re.search(r"\b(?:vi sao|tai sao|giai thich|bao cao|luot truoc)\b", query))
        date = plan.created_at.isoformat()
        parts = [f"**{plan.symbol} · {'Giải thích CHỜ từ báo cáo đã lưu' if vi else 'WAIT explanation from the saved report'}**",
                 f"{'Nguồn' if vi else 'Source'}: {date}. " + (
                     "Đọc lại ý kiến đã lưu; không lấy giá mới, không chạy model/council và không gửi lệnh. Đây là phân tích lịch sử, không phải khuyến nghị hiện tại."
                     if vi else "Replaying saved opinions: no fresh prices, model/council calls or orders. This is historical analysis, not a current recommendation.")]
        for report in reports:
            summary = report.summary[:900]
            if len(report.summary) > 900:
                summary += " … [" + ("trích đoạn" if vi else "excerpt") + "]"
            parts.append(f"**{report.role.title()} · {'trích báo cáo cũ' if vi else 'saved report excerpt'}**\n\n" + "\n".join("> " + line for line in summary.splitlines()))
        return {"content": "\n\n".join(parts), "source_message": str(_get(message, "message_id", "")),
                "symbol": plan.symbol, "created_at": date, "roles": [r.role for r in reports],
                "eligible_messages": len(prior)}
    return None


def persist_explanation(explanation, attempt, runs_dir, emit):
    store = RunStateStore()
    run_dir = store.create_run_dir(runs_dir)
    store.save_request(run_dir, attempt.prompt, {"session_id": attempt.session_id})
    snapshot = {"version": 1, "source": "historical_forex_report", "run_id": run_dir.name, "model_calls": 0,
                "initial_selection": {"eligible_messages": explanation["eligible_messages"], "recent_messages": 0,
                                      "retrieved_messages": 1, "omitted_messages": max(0, explanation["eligible_messages"] - 1),
                                      "history_chars": len(explanation["content"]), "history_char_budget": 12000},
                "initial_components": {"recalled_memories": []},
                "historical_report": {k: explanation[k] for k in ("source_message", "symbol", "created_at", "roles")}}
    for name, data in (("request_context.json", snapshot), ("llm_usage.json", {
        "source": "historical_forex_report", "totals": {"input_tokens": 0, "output_tokens": 0, "calls": 0, "cache_read_tokens": 0}, "per_iteration": [],
    })):
        (run_dir / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    store.mark_success(run_dir)
    emit("context_snapshot", snapshot)
    emit("text_delta", {"delta": explanation["content"]})
    return {"status": "success", "content": explanation["content"], "run_dir": str(run_dir), "tool_trail": []}
