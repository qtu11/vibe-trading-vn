"""Vietnamese-market grounding: locale magnitudes, units, markers and citations.

The TCB report these cases come from failed with sixteen
``figures_block_malformed`` lines and a page of ``(omitted※)`` markers in
Vietnamese prose. Each test below pins one part of that repair:

* the declaration parser reads Vietnamese scales and unit tails,
* the source index reads Vietnamese thousands grouping,
* a figure carrying a magnitude is compared at that magnitude,
* the gate speaks Vietnamese when the user does,
* a declared ``[S#]`` the prose forgot is rendered instead of the figure cut.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agent.grounding import GroundingLedger
from src.agent.grounding.figures import parse_figures_block
from src.agent.grounding.policies import ValidationResult
from src.agent.grounding.release import (
    _REDACTION_MARKER_EN,
    _REDACTION_MARKER_VI,
    _REDACTION_MARKER_ZH,
)
from src.agent.grounding.sources import numeric_candidates, value_in_source

SYMBOL = "FPT.VN"

#: The sixteen declaration lines the TCB draft wrote and the parser rejected.
TCB_LINES = (
    "230,1 nghìn tỷ | derived | 10.629.360.621 × 21.650 | get_stock_profile, technical_indicators",
    "28,9 nghìn tỷ | cited | LNTT 9T2026, Techcombank [S13] | S13",
    "10,4 nghìn tỷ | cited | LNTT quý III/2026 [S13] | S13",
    "2,50 nghìn tỷ | cited | chi phí dự phòng 9T2026 [S13] | S13",
    "khoảng 80% | derived | 4.425 / 5.537 | S13",
    "khoảng 20% | derived | 1.097 / 5.537 | S13",
    "1.318 nghìn tỷ | cited | tổng tài sản 30/09/2026 [S13] | S13",
    "419,0 nghìn tỷ | cited | tín dụng cá nhân và SME [S13] | S13",
    "3,54 tỷ cổ phiếu | cited | khối lượng phát hành trả cổ tức [S18] | S18",
    "24/28 mã | cited | số mã ngân hàng giảm trong tuần cuối tháng 10 [S3] | S3",
    "1,10 lần | count | hệ số P/B thấp trong bảng độ nhạy",
    "1,25 lần | count | hệ số P/B giữa trong bảng độ nhạy",
    "1,40 lần | count | hệ số P/B cao trong bảng độ nhạy",
    "7,0 lần | count | hệ số P/E thấp trong bảng độ nhạy",
    "8,0 lần | count | hệ số P/E giữa trong bảng độ nhạy",
    "9,0 lần | count | hệ số P/E cao trong bảng độ nhạy",
)


def _block(*rows: str) -> str:
    return "\n\n```figures\n" + "\n".join(rows) + "\n```"


def _news_payload() -> str:
    """One Vietnamese article whose prose carries the numbers a report cites."""
    return json.dumps(
        {
            "ok": True,
            "market": "vietnam",
            "source": "google_news",
            "data": {
                "scope": "stock",
                "code": SYMBOL,
                "articles": [
                    {
                        "title": "FPT công bố kết quả kinh doanh quý III/2026",
                        "url": "https://cafef.vn/fpt-quy-iii-2026.chn",
                        "source": "CafeF",
                        "published": "2026-11-05T10:00:00+07:00",
                        "as_of": "2026-09-30",
                        "snippet": (
                            "Tổng tài sản đạt 1.318 nghìn tỷ đồng, doanh thu 230100 tỷ "
                            "đồng và lợi nhuận trước thuế 28.900 tỷ đồng."
                        ),
                    }
                ],
            },
        },
        ensure_ascii=False,
    )


def _market_payload() -> str:
    return json.dumps(
        {
            SYMBOL: [
                {"trade_date": "2026-11-05", "open": 21_600, "high": 21_850,
                 "low": 21_550, "close": 21_650, "volume": 11_339_600},
                {"trade_date": "2026-11-06", "open": 21_650, "high": 21_900,
                 "low": 21_600, "close": 21_800, "volume": 9_500_000},
            ],
            "_provenance": {
                SYMBOL: {
                    "source": "hsx",
                    "requested_source": "auto",
                    "detected_source": "hsx",
                    "fallback_used": False,
                    "currency_conversion": "none",
                }
            },
        },
        ensure_ascii=False,
    )


def _ledger(tmp_path: Path, message: str = "Phân tích FPT.VN và đưa ra khuyến nghị") -> GroundingLedger:
    ledger = GroundingLedger(run_dir=tmp_path, user_message=message)
    ledger.ingest_tool_result(
        tool_name="get_stock_news",
        arguments={"code": SYMBOL},
        result=_news_payload(),
        call_id="news",
        success=True,
    )
    ledger.ingest_tool_result(
        tool_name="get_market_data",
        arguments={"codes": [SYMBOL]},
        result=_market_payload(),
        call_id="prices",
        success=True,
    )
    return ledger


# ---------------------------------------------------------------------------
# §1 — the declaration parser reads Vietnamese scales and unit tails
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("written", "value", "percent"),
    [
        ("230,1 nghìn tỷ", 230.1, False),
        ("28,9 nghìn tỷ", 28.9, False),
        ("10,4 nghìn tỷ", 10.4, False),
        ("2,50 nghìn tỷ", 2.5, False),
        ("1.318 nghìn tỷ", 1318.0, False),
        ("419,0 nghìn tỷ", 419.0, False),
        ("3,54 tỷ cổ phiếu", 3.54, False),
        ("khoảng 80%", 80.0, True),
        ("khoảng 20%", 20.0, True),
        ("hơn 3,54 tỷ cổ phiếu", 3.54, False),
        ("1,10 lần", 1.1, False),
        ("1.10 lần", 1.1, False),
        ("7,0 lần", 7.0, False),
    ],
)
def test_a_vietnamese_declaration_keeps_its_written_value(
    written: str, value: float, percent: bool
) -> None:
    """A scale word and a unit tail decorate the value; they never replace it."""
    block = parse_figures_block("x" + _block(f"{written} | count | note"))

    assert block.malformed == ()
    assert block.declarations[0].value == pytest.approx(value)
    assert block.declarations[0].percent is percent


def test_a_unit_tagged_pair_declares_both_counts() -> None:
    """"24/28 mã" is two figures in the prose, so it must be two declarations."""
    block = parse_figures_block("x" + _block("24/28 mã | cited | tuần cuối tháng 10 [S3] | S3"))

    assert block.malformed == ()
    assert [item.value for item in block.declarations] == [24.0, 28.0]


def test_a_bare_fraction_is_still_one_ratio() -> None:
    """The pair reading needs a unit; "1/3" is one equal weight."""
    block = parse_figures_block("x" + _block("1/3 | proposed | tỷ trọng"))

    assert block.malformed == ()
    assert len(block.declarations) == 1
    assert block.declarations[0].value == pytest.approx(1 / 3)


def test_the_tcb_declaration_block_now_parses_whole() -> None:
    """Every line of the failed draft reads; none is reported malformed."""
    block = parse_figures_block("x" + _block(*TCB_LINES))

    assert block.malformed == ()
    assert len(block.declarations) == len(TCB_LINES) + 1  # 24/28 mã is two
    assert [item.role for item in block.declarations].count("cited") == 8


# ---------------------------------------------------------------------------
# §2 — the source index reads Vietnamese grouping and scales the comparison
# ---------------------------------------------------------------------------


def test_numeric_candidates_read_vietnamese_thousands_grouping() -> None:
    """``1.318.000`` is 1318 thousand, not 1.318."""
    values = set(numeric_candidates("tổng tài sản 1.318.000 tỷ đồng"))

    assert 1_318_000 in values
    assert 1_318_000 * 1e9 in values


def test_numeric_candidates_read_a_vietnamese_magnitude() -> None:
    values = set(numeric_candidates("tổng tài sản 1.318 nghìn tỷ đồng"))

    assert 1318 in values
    assert 1318 * 1e12 in values


def test_a_scaled_figure_is_found_at_the_sources_own_scale(tmp_path: Path) -> None:
    """The draft writes "230,1 nghìn tỷ"; the source writes 230100 tỷ đồng.

    ``230100`` is not a spelling of ``230,1``, so only the scaled comparison
    can accept the figure.
    """
    ledger = _ledger(tmp_path)
    source = ledger.sources[0]

    assert value_in_source(source, 230.1) is False
    assert value_in_source(source, 230.1, scale=1e12) is True
    assert value_in_source(source, 1318.0, scale=1e12) is True


def test_a_cited_magnitude_passes_against_its_source(tmp_path: Path) -> None:
    """End to end: 28,9 nghìn tỷ with a visible [S1] is released unchanged."""
    ledger = _ledger(tmp_path)
    draft = (
        "FPT.VN công bố lợi nhuận trước thuế 28,9 nghìn tỷ đồng [S1]."
        + _block("28,9 nghìn tỷ | cited | LNTT 9T2026 [S1] | S1")
    )

    result = ledger.validate_final_answer(draft)

    assert result.valid is True, result.issues


def test_an_invented_magnitude_is_still_rejected(tmp_path: Path) -> None:
    """Scaling widens the band by the scale word, never past the source."""
    ledger = _ledger(tmp_path)
    draft = (
        "FPT.VN công bố lợi nhuận trước thuế 41,7 nghìn tỷ đồng [S1]."
        + _block("41,7 nghìn tỷ | cited | LNTT 9T2026 [S1] | S1")
    )

    result = ledger.validate_final_answer(draft)

    assert result.valid is False
    assert [issue["reason"] for issue in result.issues] == ["citation_value_not_in_source"]


# ---------------------------------------------------------------------------
# §3 — the gate speaks Vietnamese when the user does
# ---------------------------------------------------------------------------


def test_a_vietnamese_user_gets_the_vietnamese_marker() -> None:
    ledger = GroundingLedger(run_dir=Path("."), user_message="Phân tích FPT.VN")
    ledger._active_content = "Giá đóng cửa 21.650 đồng."

    assert ledger._marker_for("Giá đóng cửa 21.650 đồng.", 0) == _REDACTION_MARKER_VI
    assert ledger._marker_for("21.650 | close", 0) == _REDACTION_MARKER_VI


def test_a_chinese_line_keeps_the_chinese_marker() -> None:
    """The Chinese check runs first, so mixed CJK prose never flips to Vietnamese."""
    ledger = GroundingLedger(run_dir=Path("."), user_message="Phân tích FPT.VN")

    assert ledger._marker_for("最新收盘 21.650 元", 0) == _REDACTION_MARKER_ZH


def test_an_english_user_keeps_the_english_marker() -> None:
    ledger = GroundingLedger(run_dir=Path("."), user_message="Analyze FPT.VN")

    assert ledger._marker_for("Close 21.650.", 0) == _REDACTION_MARKER_EN


def test_a_vietnamese_note_reports_the_cut_in_vietnamese() -> None:
    ledger = GroundingLedger(run_dir=Path("."), user_message="Phân tích FPT.VN")

    note = ledger._release_note(2)

    assert "Đã lược bỏ 2 giá trị" in note
    assert "omitted" not in note
    assert _REDACTION_MARKER_VI not in note  # the note is text, not a cut marker


def test_a_redacted_vietnamese_answer_reads_as_vietnamese(tmp_path: Path) -> None:
    """An unverified price cannot leave its recommendation standing."""
    ledger = _ledger(tmp_path)
    draft = (
        "FPT.VN đóng cửa tại 99.999 đồng, khuyến nghị MUA."
        + _block("99.999 | observed | close 2026-11-06 | prices")
    )
    result = ledger.validate_final_answer(draft)
    assert result.valid is False

    released = ledger.redacted_release(draft, result)

    assert released is not None
    assert "Chưa đủ dữ liệu xác minh" in released
    assert "khuyến nghị MUA" not in released
    assert _REDACTION_MARKER_EN not in released


# ---------------------------------------------------------------------------
# §4 — a declared citation the prose forgot is rendered, not cut
# ---------------------------------------------------------------------------


def _visibility_issue(offset: int, source_ids: list[str]) -> ValidationResult:
    return ValidationResult(
        valid=False,
        issues=[
            {
                "code": "numeric_claim_conflict",
                "value": "28,9",
                "role": "cited",
                "span": [offset, offset + 4],
                "symbol": SYMBOL,
                "reason": "citation_not_visible",
                "claim": "28,9",
                "message": "28,9 source id is not visible.",
                "source_ids": source_ids,
            }
        ],
    )


def test_a_missing_citation_is_appended_to_its_line() -> None:
    ledger = GroundingLedger(run_dir=Path("."), user_message="Phân tích FPT.VN")
    content = "Lợi nhuận trước thuế đạt 28,9 nghìn tỷ đồng."
    offset = content.index("28,9")

    repaired = ledger.repair_citation_visibility(content, _visibility_issue(offset, ["S1"]))

    assert repaired == "Lợi nhuận trước thuế đạt 28,9 nghìn tỷ đồng [S1]."


def test_a_missing_citation_keeps_the_sentence_punctuation_last() -> None:
    ledger = GroundingLedger(run_dir=Path("."), user_message="Phân tích FPT.VN")
    content = "Lợi nhuận đạt 28,9 nghìn tỷ."
    offset = content.index("28,9")

    repaired = ledger.repair_citation_visibility(content, _visibility_issue(offset, ["S1", "S13"]))
    assert repaired == "Lợi nhuận đạt 28,9 nghìn tỷ [S1] [S13]."


def test_a_missing_citation_becomes_a_table_caption() -> None:
    ledger = GroundingLedger(run_dir=Path("."), user_message="Phân tích FPT.VN")
    content = "\n".join(
        [
            "| Chỉ tiêu | Giá trị |",
            "| --- | --- |",
            "| LNTT | 28,9 nghìn tỷ |",
            "Kết luận: duy trì MUA.",
        ]
    )
    offset = content.index("28,9")

    repaired = ledger.repair_citation_visibility(content, _visibility_issue(offset, ["S1"]))

    assert repaired is not None
    lines = repaired.splitlines()
    assert lines[3] == "Nguồn: [S1]"
    assert lines[4] == "Kết luận: duy trì MUA."


def test_an_english_user_gets_an_english_caption() -> None:
    ledger = GroundingLedger(run_dir=Path("."), user_message="Analyze FPT.VN")
    content = "\n".join(["| Metric | Value |", "| --- | --- |", "| NPAT | 28.9 |"])
    offset = content.index("28.9")

    repaired = ledger.repair_citation_visibility(content, _visibility_issue(offset, ["S1"]))

    assert repaired is not None
    assert "Source: [S1]" in repaired


def test_visibility_repair_declines_other_findings() -> None:
    """Only a missing visible id is repaired; an unsupported value is not."""
    ledger = GroundingLedger(run_dir=Path("."), user_message="Phân tích FPT.VN")
    validation = ValidationResult(
        valid=False,
        issues=[
            {
                "code": "numeric_claim_conflict",
                "value": "41,7",
                "reason": "citation_value_not_in_source",
                "span": [0, 4],
                "source_ids": ["S1"],
            }
        ],
    )

    assert ledger.repair_citation_visibility("41,7 nghìn tỷ.", validation) is None


def test_a_visible_declared_citation_is_released_without_a_cut(tmp_path: Path) -> None:
    """A citation-only rejection must not cost the figure."""
    ledger = _ledger(tmp_path)
    draft = (
        "Lợi nhuận trước thuế đạt 28,9 nghìn tỷ đồng."
        + _block("28,9 nghìn tỷ | cited | LNTT 9T2026 [S1] | S1")
    )
    result = ledger.validate_final_answer(draft)
    assert [issue["reason"] for issue in result.issues] == ["citation_not_visible"]

    released = ledger.redacted_release(draft, result)

    assert released is not None
    assert "28,9 nghìn tỷ" in released
    assert _REDACTION_MARKER_VI not in released
    assert "[S1]" in released
    assert ledger._released["citations_restored"] is True
    assert ledger._released["figures_removed"] == 0
