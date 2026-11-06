"""Council verdict contract: parsing, unit reconciliation and actionability."""

from __future__ import annotations

import json

import pytest

from src.tools.council_contract import (
    ObservedSnapshot,
    evaluate_verdict,
    extract_verdict,
    parse_number,
    parse_range,
)

pytestmark = pytest.mark.unit


def snapshot(**overrides) -> ObservedSnapshot:
    data = {
        "symbol": "FPT.VN",
        "last_close": 63_000.0,
        "last_date": "2026-09-30",
        "window_low": 58_000.0,
        "window_low_date": "2026-07-10",
        "window_high": 72_000.0,
        "window_high_date": "2026-08-15",
        "source": "yahoo",
        "currency": "VND",
        "adjustment": "split_dividend",
        "bars": 60,
    }
    data.update(overrides)
    return ObservedSnapshot(**data)


def verdict(**overrides) -> dict:
    data = {
        "stance": "MUA",
        "horizon": "3-6 tháng",
        "confidence": 0.68,
        "fair_value_range": "85-92",
        "entry_zone": "61-63",
        "stop": 58,
        "position_cap": "5% NAV",
        "catalysts": [
            "Hợp đồng AI mới ở thị trường Mỹ",
            "Biên lợi nhuận FPT Software cải thiện",
        ],
        "risks": ["Định giá P/E cao", "Tăng trưởng CNTT toàn cầu chậm lại"],
        "invalidation": "Đóng cửa dưới 58.000 trong hai phiên liên tiếp",
        "sources": [
            {
                "ref": "S1",
                "title": "Báo cáo tài chính hợp nhất quý 2/2026",
                "url": "https://fpt.com.vn/ir",
                "publisher": "FPT",
                "published_at": "2026-07-25",
            }
        ],
    }
    data.update(overrides)
    return data


class TestNumbers:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (63.5, 63.5),
            ("63,5", 63.5),
            ("63.000", 63_000.0),
            ("1.234,5", 1_234.5),
            ("1,234.5", 1_234.5),
            ("1,234", 1_234.0),
            ("1.234.567", 1_234_567.0),
            ("0,125", 0.125),
            ("1,2 tỷ", 1_200_000_000.0),
            ("85 nghìn", 85_000.0),
            ("5% NAV", 5.0),
            ("12,345.67", 12_345.67),
        ],
    )
    def test_vietnamese_and_us_separators(self, raw, expected) -> None:
        assert parse_number(raw) == pytest.approx(expected)

    @pytest.mark.parametrize("raw", [None, "", "n/a", "không có", True, float("nan")])
    def test_unparseable_values_stay_none(self, raw) -> None:
        assert parse_number(raw) is None

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("61-63", (61.0, 63.0)),
            ("61 – 63", (61.0, 63.0)),
            ("61 đến 63", (61.0, 63.0)),
            ("63k-65", (63_000.0, 65_000.0)),
            ("63k-65k", (63_000.0, 65_000.0)),
            ("85-92 nghìn", (85_000.0, 92_000.0)),
            ([72, 68], (68.0, 72.0)),
            ({"low": 61, "high": 63}, (61.0, 63.0)),
        ],
    )
    def test_ranges(self, raw, expected) -> None:
        assert parse_range(raw) == pytest.approx(expected)

    def test_range_rejects_a_lone_number(self) -> None:
        assert parse_range("chưa xác định") is None


class TestExtraction:
    def test_reads_a_fenced_verdict_after_prose(self) -> None:
        report = (
            "Tranh luận xong. Kết luận:\n\n"
            "```json\n"
            + json.dumps({"stance": "MUA", "confidence": 70})
            + "\n```\n"
        )
        parsed, issues = extract_verdict(report)
        assert parsed == {"stance": "MUA", "confidence": 70}
        assert issues == []

    def test_reads_an_unfenced_balanced_object_with_braces_in_text(self) -> None:
        report = (
            "Ghi chú {không phải JSON}. "
            + json.dumps(
                {
                    "stance": "GIỮ",
                    "note": "prior {nested} text and a } brace",
                    "entry_zone": "61-63",
                }
            )
        )
        parsed, issues = extract_verdict(report)
        assert parsed is not None
        assert parsed["stance"] == "GIỮ"
        assert parsed["note"].startswith("prior")
        assert issues == []

    def test_last_verdict_wins(self) -> None:
        report = (
            '{"stance": "CHỜ", "confidence": 30}\n'
            '{"stance": "MUA", "confidence": 70}\n'
        )
        parsed, _ = extract_verdict(report)
        assert parsed is not None
        assert parsed["stance"] == "MUA"

    def test_unwraps_nested_verdict(self) -> None:
        parsed, _ = extract_verdict('```json\n{"verdict": {"stance": "TRÁNH"}}\n```')
        assert parsed == {"stance": "TRÁNH"}

    def test_missing_verdict_is_reported(self) -> None:
        parsed, issues = extract_verdict("Không có JSON ở đây, chỉ có văn xuôi.")
        assert parsed is None
        assert issues and "verdict_missing" in issues[0]


class TestEvaluation:
    def test_valid_vietnam_verdict_is_actionable(self) -> None:
        result = evaluate_verdict(verdict(), observed=snapshot())

        assert result["actionable"] is True
        assert result["trade_actionable"] is True
        assert result["blocked_reason"] is None
        assert result["verdict"]["stance"] == "buy"
        assert result["verdict"]["stance_label"] == "MUA"
        assert result["verdict"]["confidence_pct"] == pytest.approx(68.0)
        assert result["verdict"]["entry_zone"] == {"low": 61_000.0, "high": 63_000.0}
        assert result["verdict"]["stop"] == pytest.approx(58_000.0)
        assert result["verdict"]["fair_value"] == {"low": 85_000.0, "high": 92_000.0}
        assert result["verdict"]["position_cap_pct"] == pytest.approx(5.0)
        assert result["evaluation"]["price_scale"] == pytest.approx(1000.0)
        assert result["evaluation"]["risk_reward"] == pytest.approx(5.75)
        sizing = result["evaluation"]["sizing"]
        assert sizing["risk_1pct"]["shares"] == 2_500
        assert sizing["position_cap"]["shares"] == 800
        assert sizing["binding"] == "position_cap"

    def test_sources_are_labelled_reported_by_council(self) -> None:
        result = evaluate_verdict(verdict(), observed=snapshot())
        sources = result["verdict"]["sources"]
        assert sources[0]["ref"] == "S1"
        assert sources[0]["verification"] == "reported_by_council"
        assert result["verdict"]["verification"] == "reported_by_council"

    def test_stop_above_entry_for_a_long_is_not_actionable(self) -> None:
        result = evaluate_verdict(verdict(stop=65), observed=snapshot())

        codes = {item["code"] for item in result["issues"]}
        assert "stop_on_wrong_side" in codes
        assert result["actionable"] is False
        assert result["trade_actionable"] is False

    def test_no_sources_means_no_advice(self) -> None:
        result = evaluate_verdict(verdict(sources=[]), observed=snapshot())

        codes = {item["code"] for item in result["issues"]}
        assert "sources_missing" in codes
        assert result["actionable"] is False
        assert result["verdict"] is not None

    def test_target_below_entry_is_rejected(self) -> None:
        result = evaluate_verdict(verdict(fair_value_range="55-60"), observed=snapshot())

        codes = {item["code"] for item in result["issues"]}
        assert "fair_value_not_above_entry" in codes
        assert result["actionable"] is False

    def test_entry_far_outside_the_observed_window_is_rejected(self) -> None:
        result = evaluate_verdict(verdict(entry_zone="150-160"), observed=snapshot())

        codes = {item["code"] for item in result["issues"]}
        assert "entry_zone_outside_observed" in codes
        assert result["actionable"] is False

    def test_mixed_suffix_and_bare_prices_are_reconciled(self) -> None:
        result = evaluate_verdict(
            verdict(entry_zone="61-63 nghìn", fair_value_range="85-92 nghìn", stop=58),
            observed=snapshot(),
        )

        assert result["actionable"] is True
        assert result["verdict"]["entry_zone"] == {"low": 61_000.0, "high": 63_000.0}
        assert result["verdict"]["stop"] == pytest.approx(58_000.0)
        assert result["evaluation"]["price_scale"] == pytest.approx(1000.0)

    def test_bare_entry_with_a_suffixed_target_is_reconciled(self) -> None:
        result = evaluate_verdict(
            verdict(entry_zone="61-63", fair_value_range="85-92 nghìn", stop=58),
            observed=snapshot(),
        )

        assert result["actionable"] is True
        assert result["verdict"]["entry_zone"] == {"low": 61_000.0, "high": 63_000.0}
        assert result["verdict"]["stop"] == pytest.approx(58_000.0)

    def test_conflicting_magnitude_suffixes_are_rejected(self) -> None:
        result = evaluate_verdict(
            verdict(entry_zone="61-63 nghìn", fair_value_range="5.000 tỷ", stop=58),
            observed=snapshot(),
        )

        codes = {item["code"] for item in result["issues"]}
        assert "price_units_conflict" in codes
        assert result["actionable"] is False

    def test_position_cap_range_uses_the_low_end(self) -> None:
        result = evaluate_verdict(verdict(position_cap="3-5% NAV"), observed=snapshot())

        assert result["verdict"]["position_cap_pct"] == pytest.approx(3.0)
        assert result["evaluation"]["position_cap_note"] == "range_3-5_used_low_end"

    def test_confidence_fraction_and_percent_agree(self) -> None:
        fraction = evaluate_verdict(verdict(confidence=0.7), observed=snapshot())
        percent = evaluate_verdict(verdict(confidence=70), observed=snapshot())

        assert fraction["verdict"]["confidence_pct"] == pytest.approx(70.0)
        assert percent["verdict"]["confidence_pct"] == pytest.approx(70.0)

    def test_sell_verdict_requires_a_stop_above_entry(self) -> None:
        sell = verdict(
            stance="BÁN",
            entry_zone="61-63",
            stop=67,
            fair_value_range="48-52",
            position_cap="4% NAV",
        )
        result = evaluate_verdict(sell, observed=snapshot())
        assert result["actionable"] is True
        assert result["verdict"]["stance"] == "sell"

        wrong = evaluate_verdict(dict(sell, stop=55), observed=snapshot())
        assert "stop_on_wrong_side" in {item["code"] for item in wrong["issues"]}

    def test_hold_does_not_require_an_entry_or_stop(self) -> None:
        result = evaluate_verdict(
            verdict(
                stance="GIỮ",
                entry_zone=None,
                stop=None,
                fair_value_range=None,
                position_cap=None,
            ),
            observed=snapshot(),
        )

        assert result["actionable"] is True
        assert result["trade_actionable"] is False
        assert result["verdict"]["entry_zone"] is None

    def test_reported_chart_is_ignored(self) -> None:
        result = evaluate_verdict(
            verdict(chart={"type": "candlestick", "bars": [{"t": "2026-01-01", "c": 1}]}),
            observed=snapshot(),
        )

        assert result["verdict"]["reported_chart_ignored"] is True

    def test_missing_verdict_is_not_actionable(self) -> None:
        result = evaluate_verdict(
            None, observed=snapshot(), extraction_issues=["verdict_missing: empty"]
        )

        assert result["actionable"] is False
        assert result["verdict"] is None
        assert result["issues"][0]["code"] == "verdict_missing"
