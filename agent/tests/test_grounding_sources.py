"""Source intake and citation-contract v2.

A ``cited`` figure used to be checked only for a visible name. These tests pin
the stronger contract: a source tool's page becomes an ``S#`` record, a cited
figure must be present in that record's text, and a table caption can cite the
whole table without one declaration per cell.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agent.grounding import GroundingLedger
from src.agent.grounding.sources import (
    numeric_candidates,
    policy_for_url,
    source_ids_in,
    value_in_source,
)

pytestmark = pytest.mark.unit

SYMBOL = "FPT.VN"

NEWS_PAYLOAD = json.dumps(
    {
        "ok": True,
        "market": "vietnam",
        "source": "google_news",
        "data": {
            "scope": "stock",
            "code": SYMBOL,
            "articles": [
                {
                    "title": "FPT doanh thu quý III đạt 1.234,5 tỷ đồng",
                    "url": "https://cafef.vn/fpt-doanh-thu-2026.chn",
                    "source": "CafeF",
                    "published": "2026-11-05T10:00:00+07:00",
                    "snippet": (
                        "Doanh thu 1.234,5 tỷ đồng, lợi nhuận sau thuế 456,7 tỷ đồng."
                    ),
                }
            ],
        },
    },
    ensure_ascii=False,
)


def _ledger(tmp_path: Path, *, message: str = "Research FPT.VN revenue") -> GroundingLedger:
    ledger = GroundingLedger(run_dir=tmp_path, user_message=message)
    ledger.ingest_tool_result(
        tool_name="get_stock_news",
        arguments={"code": SYMBOL},
        result=NEWS_PAYLOAD,
        call_id="news-1",
        success=True,
    )
    return ledger


def _block(*lines: str) -> str:
    return "\n\n```figures\n" + "\n".join(lines) + "\n```\n"


def test_numeric_candidates_read_both_separator_conventions() -> None:
    values = set(numeric_candidates("1.234,5 và 1,234.5"))

    assert 1234.5 in values


def test_numeric_candidates_scale_vietnamese_units() -> None:
    values = set(numeric_candidates("doanh thu 1,234 tỷ đồng"))

    assert 1234 in values
    assert 1234 * 1e9 in values


def test_registry_classifies_vietnamese_and_global_publishers() -> None:
    assert policy_for_url("https://cafef.vn/a.chn").tier == 4
    assert policy_for_url("https://vietnamnet.vn/a.html").tier == 4
    assert policy_for_url("https://nguoiquansat.vn/a.html").tier == 4
    assert policy_for_url("https://dantri.com.vn/a.htm").tier == 4
    assert policy_for_url("https://bnews.vn/a.html").tier == 4
    assert policy_for_url("https://www.reuters.com/markets/x").tier == 2
    assert policy_for_url("https://www.hsx.vn/vi/").tier == 1
    assert policy_for_url("https://unknown-blog.example/post") is None


def test_news_result_becomes_a_tiered_source_record(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)

    assert len(ledger.sources) == 1
    source = ledger.sources[0]
    assert source.source_id == "S1"
    assert source.publisher == "CafeF"
    assert source.tier == 4
    assert source.published_at == "2026-11-05T10:00:00+07:00"
    # The feed supplies no separate effective time, so the publication date
    # stands in and the fallback is recorded rather than hidden.
    assert source.data_effective_at == "2026-11-05T10:00:00+07:00"
    assert source.data_effective_basis == "published_at"
    assert value_in_source(source, 1234.5)
    assert value_in_source(source, 456.7)

    artifact = json.loads(
        (tmp_path / "artifacts" / "grounding_evidence.json").read_text(encoding="utf-8")
    )
    assert artifact["sources"][0]["source_id"] == "S1"
    assert artifact["sources"][0]["verification"] == "unverified"
    assert artifact["sources"][0]["data_effective_basis"] == "published_at"


def test_an_explicit_effective_time_is_not_replaced_by_the_publication_date(
    tmp_path: Path,
) -> None:
    ledger = GroundingLedger(run_dir=tmp_path, user_message="Research FPT.VN")
    ledger.ingest_tool_result(
        tool_name="get_stock_news",
        arguments={"code": SYMBOL},
        result=json.dumps(
            {
                "ok": True,
                "market": "vietnam",
                "source": "google_news",
                "data": {
                    "scope": "stock",
                    "code": SYMBOL,
                    "articles": [
                        {
                            "title": "FPT quý III",
                            "url": "https://cafef.vn/fpt-quy-iii.chn",
                            "source": "CafeF",
                            "published": "2026-11-05T10:00:00+07:00",
                            "as_of": "2026-09-30",
                            "snippet": "Doanh thu 1.234,5 tỷ đồng.",
                        }
                    ],
                },
            },
            ensure_ascii=False,
        ),
        call_id="news-as-of",
        success=True,
    )

    source = ledger.sources[0]
    assert source.published_at == "2026-11-05T10:00:00+07:00"
    assert source.data_effective_at == "2026-09-30"
    assert source.data_effective_basis == "explicit"


def test_reply_citations_carry_timestamps_but_not_source_text(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)

    citations = ledger.source_citations()

    assert citations[0]["source_id"] == "S1"
    assert citations[0]["published_at"] == "2026-11-05T10:00:00+07:00"
    assert citations[0]["data_effective_at"] == "2026-11-05T10:00:00+07:00"
    assert citations[0]["data_effective_basis"] == "published_at"
    assert citations[0]["tier_label"] == "broker or established financial media"
    assert "excerpt" not in citations[0]
    assert "numbers" not in citations[0]
    assert "quotes" not in citations[0]


def test_a_read_url_enriches_the_search_hit_without_a_new_id(tmp_path: Path) -> None:
    ledger = GroundingLedger(run_dir=tmp_path, user_message="Research FPT.VN")
    ledger.ingest_tool_result(
        tool_name="web_search",
        arguments={"query": "FPT.VN revenue"},
        result=json.dumps(
            {
                "status": "ok",
                "results": [
                    {
                        "title": "FPT results",
                        "url": "https://cafef.vn/fpt-doanh-thu-2026.chn",
                        "snippet": "Doanh thu",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        call_id="search-1",
        success=True,
    )
    ledger.ingest_tool_result(
        tool_name="read_url",
        arguments={"url": "https://cafef.vn/fpt-doanh-thu-2026.chn"},
        result=json.dumps(
            {
                "status": "ok",
                "title": "FPT results",
                "url": "https://cafef.vn/fpt-doanh-thu-2026.chn",
                "content": "Doanh thu 1.234,5 tỷ đồng, lợi nhuận 456,7 tỷ đồng.",
                "length": 60,
            },
            ensure_ascii=False,
        ),
        call_id="read-1",
        success=True,
    )

    assert [source.source_id for source in ledger.sources] == ["S1"]
    assert value_in_source(ledger.sources[0], 1234.5)


def test_a_cited_source_id_must_resolve_and_contain_the_value(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    valid = ledger.validate_final_answer(
        "FPT.VN doanh thu quý III đạt 1,234.5 tỷ đồng [S1]。"
        + _block("1,234.5 | cited | doanh thu quý III | [S1]")
    )
    wrong_value = ledger.validate_final_answer(
        "FPT.VN doanh thu quý III đạt 9,999.9 tỷ đồng [S1]。"
        + _block("9,999.9 | cited | doanh thu quý III | [S1]")
    )
    unknown_source = ledger.validate_final_answer(
        "FPT.VN doanh thu quý III đạt 1,234.5 tỷ đồng [S99]。"
        + _block("1,234.5 | cited | doanh thu quý III | [S99]")
    )

    assert valid.valid is True, valid.issues
    assert [issue["reason"] for issue in wrong_value.issues] == ["citation_value_not_in_source"]
    assert [issue["reason"] for issue in unknown_source.issues] == ["citation_unknown_source"]


def test_a_table_caption_cites_every_measured_cell(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    table = (
        "\n\n| Chỉ tiêu | Giá trị |\n|---|---|\n"
        "| Doanh thu | 1,234.5 |\n| Lợi nhuận sau thuế | 456.7 |\n\n"
        "Nguồn: CafeF [S1]\n"
    )

    result = ledger.validate_final_answer("FPT.VN kết quả quý III:" + table)

    assert result.valid is True, result.issues


def test_a_table_caption_does_not_bless_a_number_the_source_lacks(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    table = (
        "\n\n| Chỉ tiêu | Giá trị |\n|---|---|\n"
        "| Doanh thu | 9,999.9 |\n\nNguồn: CafeF [S1]\n"
    )

    result = ledger.validate_final_answer("FPT.VN kết quả quý III:" + table)

    assert [issue["reason"] for issue in result.issues] == ["citation_value_not_in_source"]


def test_a_legacy_caption_name_satisfies_visible_citation(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    table = (
        "\n\n| Chỉ tiêu | Giá trị |\n|---|---|\n"
        "| Doanh thu | 1,234.5 |\n\nNguồn: CafeF\n"
    )

    result = ledger.validate_final_answer(
        "FPT.VN kết quả quý III:" + table + _block("1,234.5 | cited | doanh thu | CafeF")
    )

    assert result.valid is True, result.issues


def test_an_unknown_publisher_is_collected_but_labelled_unverified(tmp_path: Path) -> None:
    ledger = GroundingLedger(run_dir=tmp_path, user_message="Research FPT.VN")
    ledger.ingest_tool_result(
        tool_name="web_search",
        arguments={"query": "FPT.VN"},
        result=json.dumps(
            {
                "status": "ok",
                "results": [
                    {
                        "title": "FPT revenue 1,234.5 billion",
                        "url": "https://unknown-blog.example/fpt",
                        "snippet": "FPT revenue was 1,234.5 billion VND.",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        call_id="search-2",
        success=True,
    )

    assert ledger.sources[0].tier == 5
    result = ledger.validate_final_answer(
        "FPT.VN revenue was 1,234.5 billion VND [S1]。"
        + _block("1,234.5 | cited | revenue | [S1]")
    )
    assert result.valid is True, result.issues


def test_source_ids_are_parsed_from_notes_and_refs() -> None:
    assert source_ids_in("CafeF [S1], Reuters [S2]") == ("S1", "S2")
    assert source_ids_in("no source") == ()


def test_a_google_news_redirect_is_tiered_by_its_publisher(tmp_path: Path) -> None:
    ledger = GroundingLedger(run_dir=tmp_path, user_message="Research FPT.VN")
    ledger.ingest_tool_result(
        tool_name="get_stock_news",
        arguments={"code": SYMBOL},
        result=json.dumps(
            {
                "ok": True,
                "market": "vietnam",
                "source": "google_news",
                "data": {
                    "scope": "stock",
                    "code": SYMBOL,
                    "articles": [
                        {
                            "title": "FPT profit rises to 456.7 billion dong",
                            "url": "https://news.google.com/rss/articles/CBMi-fpt",
                            "source": "Reuters",
                            "publisher_url": "https://www.reuters.com",
                            "published": "2026-11-05T10:00:00+00:00",
                            "snippet": "FPT profit was 456.7 billion dong.",
                        }
                    ],
                },
            },
            ensure_ascii=False,
        ),
        call_id="news-vn",
        success=True,
    )

    source = ledger.sources[0]
    assert source.tier == 2
    assert source.publisher == "Reuters"
    assert source.domain == "www.reuters.com"
    assert value_in_source(source, 456.7)
