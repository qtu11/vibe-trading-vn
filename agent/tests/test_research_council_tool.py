"""Tests for the Vietnam equity council wrapper.

The loader and the swarm are mocked at the tool boundary, so these tests pin
the packaging contract — observed snapshot, deterministic chart, verdict
evaluation, debate projection — without spending an LLM run.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any
from unittest.mock import patch

import pytest

from src.agent.grounding.ledger import GroundingLedger
from src.tools import research_council_tool
from src.tools.council_contract import ObservedSnapshot, evaluate_verdict
from src.tools.research_council_tool import ResearchCouncilTool

pytestmark = pytest.mark.unit


def _payload(code: str = "FPT.VN", *, rows: int = 40) -> dict[str, Any]:
    start = date(2026, 7, 1)
    bars = [
        {
            "trade_date": (start + timedelta(days=index)).isoformat(),
            "open": 63_000 + index * 100,
            "high": 64_000 + index * 100,
            "low": 62_000 + index * 100,
            "close": 63_000 + index * 100,
            "volume": 1_200_000 + index,
        }
        for index in range(rows)
    ]
    return {
        code: bars,
        "_provenance": {
            code: {
                "source": "yahoo",
                "adjustment": "split_dividend",
                "volume_unit": "shares",
                "quote_currency": "VND",
            }
        },
    }


def _verdict(**overrides: Any) -> dict[str, Any]:
    verdict = {
        "stance": "MUA",
        "horizon": "3-6 tháng",
        "confidence": 68,
        "fair_value_range": "72-78",
        "entry_zone": "62,0-64,0",
        "stop": "59,5",
        "position_cap": "5% NAV",
        "catalysts": ["Ký thêm hợp đồng xuất khẩu phần mềm"],
        "risks": ["Tăng trưởng chậm lại ở mảng nước ngoài"],
        "invalidation": "Đóng cửa dưới 59,5 trong 3 phiên",
        "sources": [
            {
                "ref": "S1",
                "title": "Báo cáo thường niên FPT 2025",
                "publisher": "FPT",
                "url": "https://fpt.com.vn/bao-cao-thuong-nien",
                "published_at": "2026-03-30",
            }
        ],
        "chart": None,
    }
    verdict.update(overrides)
    return verdict


def _swarm_result(verdict: dict[str, Any] | None = None, *, status: str = "completed") -> dict[str, Any]:
    report = (
        "Hội đồng kết luận: khuyến nghị tham khảo, không phải cam kết lợi nhuận.\n\n"
        "```json\n" + json.dumps(verdict if verdict is not None else _verdict(), ensure_ascii=False) + "\n```"
    )
    return {
        "status": status,
        "run_id": "swarm-1",
        "final_report": report,
        "tasks": [
            {
                "id": "task-bull",
                "agent_id": "bull_advocate",
                "status": "completed",
                "summary": "Luận điểm mua dựa trên tăng trưởng doanh thu.",
                "error": None,
            },
            {
                "id": "task-bear",
                "agent_id": "bear_advocate",
                "status": "completed",
                "summary": "Rủi ro định giá và tập trung khách hàng.",
                "error": None,
            },
        ],
    }


def _run(
    *,
    payload: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    with (
        patch.object(
            research_council_tool,
            "fetch_market_data",
            return_value=payload if payload is not None else _payload(),
        ),
        patch.object(
            research_council_tool,
            "_run_swarm",
            return_value=result if result is not None else _swarm_result(),
        ),
    ):
        raw = ResearchCouncilTool().execute(**kwargs)
    return json.loads(raw)


class TestSymbolHandling:
    def test_bare_vn_ticker_is_canonicalized(self) -> None:
        out = _run(symbol="fpt")

        assert out["ok"] is True
        assert out["symbol"] == "FPT.VN"
        block = json.loads(
            out["fence"].removeprefix("```council\n").removesuffix("\n```")
        )
        assert block["symbol"] == "FPT.VN"

    def test_non_vn_symbol_is_rejected_before_fetching(self) -> None:
        with patch.object(research_council_tool, "fetch_market_data") as fetch:
            out = json.loads(ResearchCouncilTool().execute(symbol="AAPL.US"))

        assert out["ok"] is False
        assert "invalid Vietnam symbol" in out["error"]
        assert "FPT.VN" in out["error"]
        fetch.assert_not_called()

    def test_missing_symbol_is_rejected(self) -> None:
        out = json.loads(ResearchCouncilTool().execute())

        assert out["ok"] is False
        assert "symbol" in out["error"]

    def test_bad_llm_cap_is_rejected_before_fetching(self) -> None:
        with patch.object(research_council_tool, "fetch_market_data") as fetch:
            out = json.loads(
                ResearchCouncilTool().execute(symbol="FPT.VN", max_llm_calls="zero")
            )

        assert out["ok"] is False
        assert "max_llm_calls" in out["error"]
        fetch.assert_not_called()


class TestFailureEnvelopes:
    def test_loader_failure_is_an_error_envelope(self) -> None:
        with patch.object(
            research_council_tool,
            "fetch_market_data",
            side_effect=RuntimeError("loader down"),
        ):
            out = json.loads(ResearchCouncilTool().execute(symbol="FPT.VN"))

        assert out["ok"] is False
        assert "loader down" in out["error"]

    def test_no_bars_is_an_error_envelope(self) -> None:
        out = _run(payload={"_unresolved": ["FPT.VN"], "_provenance": {}}, symbol="FPT.VN")

        assert out["ok"] is False
        assert "no OHLCV bars" in out["error"]

    def test_failed_swarm_is_an_error_envelope(self) -> None:
        out = _run(
            result={"status": "failed", "run_id": "swarm-2", "error": "provider down"},
            symbol="FPT.VN",
        )

        assert out["ok"] is False
        assert out["status"] == "failed"
        assert out["run_id"] == "swarm-2"
        assert "provider down" in out["error"]

    def test_running_swarm_is_reported_without_a_verdict(self) -> None:
        out = _run(result={"status": "running", "run_id": "swarm-3"}, symbol="FPT.VN")

        assert out["ok"] is False
        assert out["status"] == "running"
        assert "re-invoke" in out["error"]


class TestCouncilContract:
    def test_completed_run_returns_a_ready_to_paste_fence(self) -> None:
        out = _run(symbol="FPT.VN")

        assert out["ok"] is True
        assert out["status"] == "completed"
        assert out["actionable"] is True
        assert out["trade_actionable"] is True
        assert out["blocked_reason"] is None
        assert out["snapshot"]["bars"] == 36
        assert out["snapshot"]["currency"] == "VND"
        assert out["snapshot"]["source"] == "yahoo"
        assert out["sources"][0]["verification"] == "reported_by_council"

        assert out["fence"].startswith("```council\n")
        assert out["fence"].endswith("\n```")
        block = json.loads(
            out["fence"].removeprefix("```council\n").removesuffix("\n```")
        )
        assert block["type"] == "council"
        assert block["version"] == 1
        assert block["actionable"] is True
        assert block["trade_actionable"] is True
        assert block["execution_context"] == {
            "research_only": True,
            "execution_ready": False,
            "quote_status": "not_acquired",
            "order_book_status": "not_acquired",
            "session_status": "not_acquired",
            "holdings_status": "not_acquired",
            "order_type": None,
            "last_close_is_live_quote": False,
        }
        assert out["execution_context"] == block["execution_context"]
        assert block["verdict"]["stance"] == "buy"
        assert block["verdict"]["stance_label"] == "MUA"
        # thousands in the verdict reconcile to the whole-VND bars
        assert block["verdict"]["stop"] == pytest.approx(59_500)
        assert block["evaluation"]["price_scale"] == pytest.approx(1000)
        assert block["chart"]["bars"][-1]["t"] == "2026-08-09"
        assert block["disclaimer"]

    def test_sell_is_a_reduction_requiring_holdings_not_a_generic_short(self) -> None:
        verdict = _verdict(stance="BÁN", fair_value_range="48-52", stop="70")
        out = _run(result=_swarm_result(verdict), symbol="FPT.VN")
        block = json.loads(
            out["fence"].removeprefix("```council\n").removesuffix("\n```")
        )
        direct = evaluate_verdict(
            verdict,
            observed=research_council_tool._snapshot_from_chart("FPT.VN", block["chart"]),
        )
        # Generic contracts still support short geometry. The VN wrapper has
        # no holdings or available-to-sell context for a cash-equity reduction.
        assert direct["actionable"] is True
        assert direct["evaluation"]["risk_reward"] is not None
        assert direct["evaluation"]["sizing"] is not None
        assert block["verdict"]["stance"] == "sell"
        assert out["actionable"] is block["actionable"] is False
        assert out["trade_actionable"] is block["trade_actionable"] is False
        issue = next(item for item in block["issues"] if item["code"] == "vn_sell_position_context_missing")
        assert issue["severity"] == "error"
        assert "reducing an existing position" in issue["message"]
        assert "have not been acquired" in issue["message"]
        assert block["blocked_reason"] == "vn_sell_position_context_missing"
        for field in ("risk_per_share", "reward_per_share", "risk_reward", "stop_distance_pct", "sizing"):
            assert block["evaluation"][field] is None
        assert block["execution_context"]["holdings_status"] == "not_acquired"
        assert block["execution_context"]["order_type"] is None
        assert block["execution_context"]["execution_ready"] is False

    def test_sell_preserves_other_errors_without_duplicate_blocking_reasons(self) -> None:
        direct = evaluate_verdict(
            _verdict(stance="BÁN", fair_value_range="48-52", stop="59", sources=[]),
            observed=ObservedSnapshot(symbol="FPT.VN", last_close=67_000, currency="VND"),
        )
        guarded = research_council_tool._apply_vn_position_context(direct)
        repeated = research_council_tool._apply_vn_position_context(guarded)
        assert repeated == guarded
        codes = [issue["code"] for issue in guarded["issues"]]
        assert "sources_missing" in codes
        assert "stop_on_wrong_side" in codes
        assert codes.count("vn_sell_position_context_missing") == 1
        reasons = guarded["blocked_reason"].split("; ")
        assert len(reasons) == len(set(reasons))
        assert "sources_missing" in reasons
        assert "vn_sell_position_context_missing" in reasons

    def test_sell_context_does_not_change_the_observed_chart_or_snapshot(self) -> None:
        buy = _run(symbol="FPT.VN")
        sell = _run(result=_swarm_result(_verdict(stance="BÁN", fair_value_range="48-52", stop="70")), symbol="FPT.VN")
        blocks = [json.loads(out["fence"].removeprefix("```council\n").removesuffix("\n```")) for out in (buy, sell)]
        assert blocks[0]["chart"] == blocks[1]["chart"]
        assert blocks[0]["snapshot"] == blocks[1]["snapshot"]
        assert blocks[1]["chart"]["bars"][-1]["c"] == 66_900

    def test_decisions_without_sources_are_not_actionable(self) -> None:
        verdict = _verdict(sources=[])
        out = _run(
            result=_swarm_result(verdict),
            symbol="FPT.VN",
        )

        assert out["ok"] is True
        assert out["actionable"] is False
        block = json.loads(
            out["fence"].removeprefix("```council\n").removesuffix("\n```")
        )
        assert block["actionable"] is False
        assert block["verdict"] is not None
        assert "sources_missing" in {issue["code"] for issue in block["issues"]}

    def test_a_stop_above_entry_for_a_long_is_not_actionable(self) -> None:
        verdict = _verdict(stop="70")
        out = _run(result=_swarm_result(verdict), symbol="FPT.VN")

        assert out["ok"] is True
        block = json.loads(
            out["fence"].removeprefix("```council\n").removesuffix("\n```")
        )
        assert block["actionable"] is False
        assert block["trade_actionable"] is False
        assert any("stop" in issue["code"] for issue in block["issues"])

    def test_a_report_without_a_verdict_is_not_actionable(self) -> None:
        out = _run(
            result={
                "status": "completed",
                "run_id": "swarm-4",
                "final_report": "Hội đồng chưa đủ dữ liệu để kết luận.",
                "tasks": [],
            },
            symbol="FPT.VN",
        )

        assert out["ok"] is True
        block = json.loads(
            out["fence"].removeprefix("```council\n").removesuffix("\n```")
        )
        assert block["verdict"] is None
        assert block["actionable"] is False
        assert block["execution_context"]["research_only"] is True
        assert block["execution_context"]["execution_ready"] is False
        assert block["execution_context"]["last_close_is_live_quote"] is False
        assert any(issue["code"] == "verdict_missing" for issue in block["issues"])

    def test_debate_projection_uses_role_labels(self) -> None:
        out = _run(symbol="FPT.VN")

        block = json.loads(
            out["fence"].removeprefix("```council\n").removesuffix("\n```")
        )
        roles = {entry["agent_id"]: entry for entry in block["debate"]}
        assert roles["bull_advocate"]["role"] == "Bên mua (Bull)"
        assert roles["bear_advocate"]["role"] == "Bên bán (Bear)"
        assert len(roles["bull_advocate"]["summary"]) <= 420

    def test_chart_bars_are_clamped_to_the_supported_range(self) -> None:
        small = _run(symbol="FPT.VN", chart_bars=1)
        huge = _run(symbol="FPT.VN", chart_bars=9999)

        assert small["snapshot"]["bars"] == 12
        assert huge["snapshot"]["bars"] <= research_council_tool._MAX_BARS


class TestLedgerIngestion:
    def test_only_the_observed_bars_enter_the_evidence_ledger(self, tmp_path) -> None:
        out = _run(symbol="FPT.VN")
        ledger = GroundingLedger(run_dir=tmp_path, user_message="Hội đồng FPT.VN")

        ledger.ingest_tool_result(
            tool_name="run_research_council",
            arguments={"symbol": "FPT.VN"},
            result=json.dumps(out, ensure_ascii=False),
            call_id="council-1",
            success=True,
        )

        records = [record for record in ledger._evidence if record.tool == "run_research_council"]
        assert records
        assert {record.symbol for record in records} == {"FPT.VN"}
        assert {record.field for record in records} == {
            "open", "high", "low", "close", "volume",
        }
        # The PM's target/stop are claims, not observations, and must not gain
        # the status of source-checked evidence.
        assert not any(record.value == pytest.approx(78_000) for record in records)
        assert not any(record.value == pytest.approx(59_500) for record in records)

    def test_a_malformed_council_payload_records_a_failure(self, tmp_path) -> None:
        ledger = GroundingLedger(run_dir=tmp_path, user_message="Hội đồng FPT.VN")

        ledger.ingest_tool_result(
            tool_name="run_research_council",
            arguments={"symbol": "FPT.VN"},
            result=json.dumps({"ok": True, "fence": "```council\nnot json\n```"}),
            call_id="council-bad",
            success=True,
        )

        assert not [record for record in ledger._evidence if record.tool == "run_research_council"]


class TestEvaluateVerdictDirect:
    def test_the_wrapper_matches_a_direct_evaluation(self) -> None:
        """The VN position guard leaves an internally valid BUY unchanged."""
        verdict = _verdict()
        direct = evaluate_verdict(
            verdict,
            observed=ObservedSnapshot(
                symbol="FPT.VN",
                last_close=67_000,
                window_low=62_000,
                window_high=68_000,
                source="yahoo",
                currency="VND",
                bars=36,
            ),
        )
        out = _run(symbol="FPT.VN")

        block = json.loads(
            out["fence"].removeprefix("```council\n").removesuffix("\n```")
        )
        assert block["actionable"] == direct["actionable"]
        assert block["evaluation"]["risk_reward"] == direct["evaluation"]["risk_reward"]
