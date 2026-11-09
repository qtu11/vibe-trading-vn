"""Chat charts use captured tool candles, never model-written price arrays."""

import json
from pathlib import Path
from types import SimpleNamespace

from src.agent.answer_charts import append_observed_charts, collect_observed_charts
from src.agent.context import ContextBuilder
from src.agent.grounding.figures import _fenced_blocks
from src.agent.grounding.ledger import GroundingLedger
from src.agent.loop import AgentLoop
from src.agent.loop_grounding import validate_and_release
from src.agent.loop_streaming import TurnStream
from src.agent.tools import ToolRegistry
from src.agent.trace import TraceWriter
from src.tools.market_data_tool import MarketDataTool
from src.tools.price_chart_tool import PriceChartTool, build_chart_spec, chart_fence


def _captured_payload() -> dict:
    return json.loads((Path(__file__).parent / "fixtures" / "mbb_market_data_20261107.json").read_text(encoding="utf-8"))


def _chart_payloads(content: str) -> list[dict]:
    return [json.loads(content[start:end]) for _, _, info, (start, end) in _fenced_blocks(content) if info == "chart"]


def test_captured_mbb_data_reaches_answer_without_model_copying_json() -> None:
    payload = _captured_payload()
    charts = collect_observed_charts(MarketDataTool(), {"codes": ["MBB.VN"]}, json.dumps(payload))
    answer = append_observed_charts("MBB historical analysis.\n\nEvidence and risks.", charts)
    chart = _chart_payloads(answer)[0]

    assert chart["symbol"] == "MBB.VN"
    assert len(chart["bars"]) == 60
    assert chart["bars"][-1] == {"t": "2026-11-06T00:00:00", "o": 19000.0, "h": 19350.0, "l": 19000.0, "c": 19250.0, "v": 12496300}
    assert chart["price_unit"] == "VND"
    assert chart["adjustment"] == "split_dividend"
    assert chart["source_url"] == payload["_provenance"]["MBB.VN"]["source_url"]
    assert chart["retrieved_at"] == "2026-11-07T16:32:43.998885+00:00"
    assert answer.index("```chart") < answer.index("Evidence and risks")


def test_lowercase_requested_symbol_still_reaches_the_answer_chart() -> None:
    """A lowercase request must not silently render an "unavailable" chart.

    ``MarketDataTool`` keys its payload by the symbol exactly as requested, so
    ``mbb.vn`` produces a lowercase key while the chart spec presents the
    canonical uppercase form.
    """
    payload = _captured_payload()
    lowered = {
        "mbb.vn": payload["MBB.VN"],
        "_provenance": {"mbb.vn": payload["_provenance"]["MBB.VN"]},
    }
    charts = collect_observed_charts(MarketDataTool(), {"codes": ["mbb.vn"]}, json.dumps(lowered))
    chart = charts["MBB.VN"]

    assert chart["bars"], "lowercase request lost its observed candles"
    assert chart["bars"][-1]["c"] == 19250.0
    assert chart["price_unit"] == "VND"
    assert chart["source_url"] == payload["_provenance"]["MBB.VN"]["source_url"]


def test_chart_collector_only_accepts_first_party_market_tools() -> None:
    payload = json.dumps(_captured_payload())
    assert collect_observed_charts(SimpleNamespace(name="get_market_data"), {"codes": ["MBB.VN"]}, payload) == {}


def test_model_invented_chart_is_replaced_by_original_tool_candles() -> None:
    payload = _captured_payload()
    charts = collect_observed_charts(MarketDataTool(), {"codes": ["MBB.VN"]}, json.dumps(payload))
    invented = chart_fence({"symbol": "MBB.VN", "bars": [{"t": "2026-11-06", "o": 999999, "h": 999999, "l": 999999, "c": 999999}]})
    answer = append_observed_charts("Analysis.\n\n" + invented + "\n\nEnd.", charts)
    assert "999999" not in answer
    assert len(_chart_payloads(answer)) == 1
    assert _chart_payloads(answer)[0]["bars"][-1]["c"] == 19250.0
    assert answer.endswith("End.")


def test_unobserved_model_chart_never_becomes_a_visible_price_chart() -> None:
    invented = chart_fence({"symbol": "MBB.VN", "bars": [{"c": 999999}]})
    answer = append_observed_charts("Analysis.\n\n" + invented, {})
    assert "999999" not in answer
    assert "```chart" not in answer
    assert "Chart unavailable" in answer
    unclosed = append_observed_charts(invented.removesuffix("\n```"), {})
    assert "999999" not in unclosed
    assert "```chart" not in unclosed
    assert "Chart unavailable" in unclosed


def test_observed_chart_is_visible_before_long_prose_even_if_model_put_it_last() -> None:
    charts = collect_observed_charts(MarketDataTool(), {"codes": ["MBB.VN"]}, json.dumps(_captured_payload()))
    content = "MBB historical analysis.\n\nDetailed thesis.\n\n" + chart_fence({"symbol": "MBB.VN", "bars": []})
    answer = append_observed_charts(content, charts)
    assert answer.index("```chart") < answer.index("Detailed thesis.")
    assert len(_chart_payloads(answer)) == 1


def test_empty_market_data_and_failed_chart_show_unavailable_without_fake_candles() -> None:
    for tool, arguments in ((MarketDataTool(), {"codes": ["MBB.VN"]}), (PriceChartTool(), {"code": "MBB.VN"})):
        charts = collect_observed_charts(tool, arguments, '{"ok":false,"error":"provider unavailable"}')
        chart = _chart_payloads(append_observed_charts("Analysis.", charts))[0]
        assert chart["status"] == "unavailable"
        assert chart["bars"] == []
    for failure in ({"ok": False}, {"success": False}, {"status": "ERROR"}, {"status": "failed"}, {"status": "cancelled"}):
        contradictory = {**_captured_payload(), **failure}
        failed = collect_observed_charts(MarketDataTool(), {"codes": ["MBB.VN"]}, json.dumps(contradictory))
        assert failed["MBB.VN"]["bars"] == []


def test_builder_filters_invalid_candles_and_keeps_actual_sorted_rows() -> None:
    rows = _captured_payload()["MBB.VN"][-2:]
    malformed = {**rows[-1], "trade_date": "2026-11-07", "open": None}
    impossible = {**rows[-1], "trade_date": "2026-11-08", "high": 1.0}
    bad_date = {**rows[-1], "trade_date": "not a date"}
    spec = build_chart_spec("MBB.VN", [rows[-1], malformed, impossible, bad_date, rows[0]])
    assert spec is not None
    assert [bar["t"] for bar in spec["bars"]] == [row["trade_date"] for row in rows]
    assert build_chart_spec("MBB.VN", [malformed, impossible, bad_date]) is None


def test_tool_lifecycle_collects_full_payload_before_result_preview_truncation(monkeypatch, tmp_path: Path) -> None:
    payload = _captured_payload()
    tool = MarketDataTool()
    monkeypatch.setattr(tool, "execute", lambda **kwargs: json.dumps(payload))
    registry = ToolRegistry()
    registry.register(tool)
    agent = AgentLoop(registry=registry, llm=SimpleNamespace(), max_iterations=2)
    agent.memory.run_dir = str(tmp_path)
    trace = TraceWriter(tmp_path)
    agent._process_tool_calls([SimpleNamespace(id="captured", name="get_market_data", arguments={"codes": ["MBB.VN"], "start_date": "2026-08-01", "end_date": "2026-11-07"})], ContextBuilder, [], trace, [], 1)
    trace.close()
    assert agent._answer_charts["MBB.VN"]["bars"][-1]["c"] == 19250.0


def test_trusted_chart_metadata_survives_same_number_redaction(tmp_path: Path) -> None:
    chart = build_chart_spec("MBB.VN", _captured_payload()["MBB.VN"][-53:])
    assert chart is not None and chart["range"]["returned"] == 53
    text = "Unknown growth 53%.\n\n" + chart_fence(chart)
    ledger = GroundingLedger(run_dir=tmp_path, user_message="Explain captured MBB history")
    ledger._trusted_chart_payloads = {json.dumps(chart, ensure_ascii=False, separators=(",", ":"))}
    released, _ = ledger._sweep_same_values(text, {"53"})
    assert _chart_payloads(released)[0]["range"]["returned"] == 53


def test_observed_chart_survives_final_gate_and_replaces_the_live_stream(tmp_path: Path) -> None:
    payload = _captured_payload()
    agent = AgentLoop(registry=ToolRegistry(), llm=SimpleNamespace())
    agent._grounding = GroundingLedger(run_dir=tmp_path, user_message="Explain recorded historical candles")
    agent._grounding.ingest_tool_result(tool_name="get_market_data", arguments={"codes": ["MBB.VN"]}, result=json.dumps(payload), call_id="captured", success=True)
    agent._answer_charts = collect_observed_charts(MarketDataTool(), {"codes": ["MBB.VN"]}, json.dumps(payload))
    events = []
    agent._event_callback = lambda event, data: events.append((event, data))
    stream = TurnStream(grounding=agent._grounding, emit=agent._emit, iteration=1, heartbeat_interval=lambda: 1.0, reasoning_interval=lambda: 1.0)
    stream.buffer_text_output = False
    original = "Historical analysis.\n\nEvidence and risks."
    stream.on_text(original)
    trace = TraceWriter(tmp_path)
    decision = validate_and_release(agent, final_content=original, grounding_revisions=0, grounding_correction_text_only=False, pending_grounding_draft="", forced_grounding_release=False, syntax_fallback_emitted=False, stream=stream, trace=trace, react_trace=[], messages=[], iteration=1, current_iter=1, max_revisions=1)
    trace.close()
    assert not decision.retry
    assert _chart_payloads(decision.content)[0]["bars"][-1]["c"] == 19250.0
    assert any(event == "stream_reset" for event, _ in events)
    assert [data["delta"] for event, data in events if event == "text_delta"][-1] == decision.content
