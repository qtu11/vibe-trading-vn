"""Snapshot-only Markdown, five actual producers, complete JSON and safe text."""

from copy import deepcopy
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
from pathlib import Path
import re

import pytest

from backtest.loaders import local_loader
from src.research_artifacts.report import MAX_REPORT_BYTES, ReportExportError, render_revision_markdown
from src.research_artifacts.service import ResearchArtifactService
from src.research_artifacts.store import ResearchArtifactStore

EXAMPLES = Path(__file__).resolve().parents[2] / "docs/examples"
KINDS = ("vietnam", "vietnam_comparables", "vietnam_dcf", "vietnam_reverse_dcf", "crypto_basis")


@pytest.fixture
def revisions(tmp_path, monkeypatch):
    source = tmp_path / "curated.json"
    source.write_bytes((EXAMPLES / "vn-company-research.example.json").read_bytes())
    monkeypatch.setattr(local_loader, "_load_config", lambda: {"financial_statements": [{"symbol": "CASE.VN", "path": str(source)}]})
    service = ResearchArtifactService(ResearchArtifactStore(tmp_path / "artifacts.sqlite"), clock=lambda: datetime(2026, 11, 6, tzinfo=timezone.utc))
    inputs = {
        "vietnam": {"code": "CASE.VN", "as_of": "2026-11-05T00:00:00Z"},
        "vietnam_comparables": {"payload": json.loads((EXAMPLES / "vn-comparables.example.json").read_text(encoding="utf-8")), "offset": 0},
        "vietnam_dcf": json.loads((EXAMPLES / "vn-dcf.example.json").read_text(encoding="utf-8")),
        "vietnam_reverse_dcf": json.loads((EXAMPLES / "vn-reverse-dcf.example.json").read_text(encoding="utf-8")),
        "crypto_basis": json.loads((EXAMPLES / "crypto-basis.example.json").read_text(encoding="utf-8")),
    }
    return {kind: service.execute_and_save(kind, payload) for kind, payload in inputs.items()}


def attachment(markdown):
    match = re.search(r"(?m)^(?P<fence>`{3,})json\n(?P<json>[\s\S]*?)\n(?P=fence)$", markdown)
    assert match, "One complete JSON appendix is required"
    return json.loads(match.group("json"))


@pytest.mark.parametrize("kind", KINDS)
def test_actual_saved_kind_export_is_deterministic_complete_and_does_not_mutate(revisions, kind):
    revision = revisions[kind]
    original = deepcopy(revision)
    report = render_revision_markdown(revision)
    assert report == render_revision_markdown(deepcopy(revision))
    assert revision == original
    assert attachment(report) == revision
    assert len(report.encode("utf-8")) <= MAX_REPORT_BYTES
    assert "NGUỒN CHƯA XÁC MINH" in report
    assert "CHƯA PUBLISH/GỬI ĐI" in report
    assert "user\\_supplied\\_unverified" in report
    assert revision["revision_id"].replace("_", "\\_") in report
    assert revision["created_at"].replace(":", "\\:").replace("-", "\\-").replace(".", "\\.") in report
    for value in revision["hashes"].values():
        assert value in report


def test_vn_metric_units_reasons_source_ids_and_locators_are_visible(revisions):
    report = render_revision_markdown(revisions["vietnam"])
    assert "270000000" in report
    assert "free\\_cash\\_flow" in report
    assert "VND" in report
    assert "Evidence IDs của inputs" in report
    assert "source\\_file\\_sha256" in report
    assert "Locator / instrument" in report
    assert "Revision / document hash" in report
    assert "Tỷ số theo kỳ, không tự annualize" in report


def test_vn_cash_cycle_follows_only_recorded_transitive_evidence(revisions):
    revision = revisions["vietnam"]
    period = revision["result"]["data"]["CASE.VN"]["periods"][0]
    period["inputs"]["income.revenue"]["evidence"] = ["unique-recorded-ref"]
    report = render_revision_markdown(revision)
    cash_cycle_line = next(line for line in report.splitlines() if line.startswith("| cash\\_conversion\\_cycle |"))
    assert "unique\\-recorded\\-ref" in cash_cycle_line


def test_page_warning_and_exact_offset_never_claim_complete_history(revisions):
    revision = revisions["vietnam"]
    revision["result"]["paging"] = {"offset": 4, "total": 8, "returned": 4, "next_offset": 8, "complete": False}
    report = render_revision_markdown(revision)
    assert "CẢNH BÁO: trang chưa bao phủ" in report
    assert "Không tải các trang còn lại" in report
    assert attachment(report)["result"]["paging"] == revision["result"]["paging"]


def test_empty_returned_page_stays_empty_without_inferred_zero(revisions):
    revision = revisions["vietnam"]
    revision["result"]["data"]["CASE.VN"]["periods"] = []
    report = render_revision_markdown(revision)
    assert "Không có kỳ BCTC trong trang này" in report
    assert attachment(report)["result"]["data"]["CASE.VN"]["periods"] == []


def test_comparables_distributions_exclusions_and_price_share_bases_visible(revisions):
    report = render_revision_markdown(revisions["vietnam_comparables"])
    assert "PATMI/weighted shares" in report
    assert "parent common equity/book-snapshot shares" in report
    assert "Exclusions" in report
    assert "Phân phối toàn bộ peer set được engine ghi" in report
    assert "VND/cp" in report
    assert "không phải forecast" in report


def test_dcf_has_full_bridge_and_invalid_grid_null(revisions):
    revision = revisions["vietnam_dcf"]
    report = render_revision_markdown(revision)
    assert "Restricted cash bị loại \\(VND\\)" in report
    assert "7000000" in report
    assert "debt/minority/preferred/associates" in report
    assert "Grid dùng perpetuity growth, kể cả khi base case chọn exit multiple" in report
    assert "growth\\_must\\_be\\_below\\_wacc" in report
    assert "Chưa có / null" in report
    assert attachment(report)["result"]["sensitivity"]["cells"] == revision["result"]["sensitivity"]["cells"]


@pytest.mark.parametrize("status", ["outside_bracket", "non_identifiable", "iteration_limit"])
def test_reverse_unsolved_never_invents_growth_and_preserves_residual(revisions, status):
    revision = revisions["vietnam_reverse_dcf"]
    revision["result"]["solver"].update(status=status, implied_terminal_growth=None, residual_vnd_per_share="-0.000000000000000001", repriced_value_per_share_vnd=0)
    report = render_revision_markdown(revision)
    assert "KHÔNG CÓ NGHIỆM ĐƯỢC XÁC NHẬN" in report
    assert status.replace("_", "\\_") in report
    assert "\\-0\\.000000000000000001" in report
    saved = attachment(report)["result"]["solver"]
    assert saved["implied_terminal_growth"] is None and saved["repriced_value_per_share_vnd"] == 0


def test_crypto_rejected_negative_zero_and_units_are_distinct(revisions):
    revision = revisions["crypto_basis"]
    revision["result"]["rows"][0]["annualized_basis"] = "0"
    report = render_revision_markdown(revision)
    assert "Gross quoted basis, không phải executable yield" in report
    assert "fraction/year" in report
    assert "perpetual\\_has\\_no\\_dated\\_basis" in report
    assert "\\-0\\.060833" in report
    loaded = attachment(report)["result"]["rows"]
    assert loaded[0]["annualized_basis"] == "0"
    assert loaded[2]["annualized_basis"] is None


class Elements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags, self.hrefs = [], []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.hrefs.extend(value for key, value in attrs if key == "href")


@pytest.mark.parametrize("source", ["javascript:alert(1)", "data:text/html,<script>alert(1)</script>", "https://u:p@example.com/a", "file:///private", "https://example.com:bad/a", "https://example.com/ bad", "https://example.com/\n# title", "https://example.com\\@other.invalid/a"])
def test_unsafe_source_urls_never_create_active_links(revisions, source):
    import mistune
    revision = revisions["vietnam_dcf"]
    revision["request"]["evidence"][0]["source_url"] = source
    report = render_revision_markdown(revision)
    parser = Elements()
    parser.feed(mistune.create_markdown(escape=False, plugins=["table"])(report))
    assert all(not href.startswith(("javascript:", "data:", "file:")) and "u:p@" not in href for href in parser.hrefs)
    assert not parser.hrefs
    assert "không tạo liên kết" in report
    assert attachment(report)["request"]["evidence"][0]["source_url"] == source


def test_html_markdown_fences_tables_controls_and_review_injection_are_inert(revisions):
    import mistune
    revision = revisions["vietnam_dcf"]
    attack = '<img src=x onerror=alert(1)>|\n# Forged heading\n![tracking](https://evil.invalid/image)\n```\n<script>x</script>\n````\n\u202eprivate'
    revision["request"]["evidence"][0].update(locator=attack, source_url="https://example.com/a)![x](https://evil.invalid/x)<img>")
    revision["limitations"] = [attack]
    revision["review_history"] = [{"review_id": "rv-fixture", "created_at": "2026-11-06T00:00:00Z", "decision": "acknowledged", "reviewer": attack, "reviewer_identity": "self_reported_operator_label", "note": attack, "verification_status": "user_supplied_unverified"}]
    report = render_revision_markdown(revision)
    parser = Elements()
    parser.feed(mistune.create_markdown(escape=False, plugins=["table"])(report))
    assert "script" not in parser.tags and "img" not in parser.tags
    assert "<img" not in report and "<script" not in report
    assert "\u202e" not in report
    assert all("evil.invalid/image" not in href for href in parser.hrefs)
    assert attachment(report) == revision
    assert "self\\_reported\\_operator\\_label" in report


def test_valid_http_url_is_encoded_without_changing_source_value(revisions):
    import mistune
    revision = revisions["vietnam_dcf"]
    source = 'https://example.com/quote(a)?q="<value>"&id=1'
    revision["request"]["evidence"][0]["source_url"] = source
    report = render_revision_markdown(revision)
    parser = Elements()
    parser.feed(mistune.create_markdown(escape=False, plugins=["table"])(report))
    assert len(parser.hrefs) == 1
    assert "%28a%29" in parser.hrefs[0] and "%3Cvalue%3E" in parser.hrefs[0]
    assert attachment(report)["request"]["evidence"][0]["source_url"] == source


def test_export_has_no_engine_store_clock_network_or_filesystem_dependency(revisions, monkeypatch):
    import builtins
    import socket
    import src.tools.vietnam_dcf as dcf
    revision = revisions["vietnam_dcf"]
    expected = render_revision_markdown(revision)
    def forbidden(*args, **kwargs):
        pytest.fail("A saved report must not fetch, recalculate or read files")
    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(dcf, "build_vietnam_dcf", forbidden)
    monkeypatch.setattr(ResearchArtifactStore, "get_revision", forbidden)
    assert render_revision_markdown(revision) == expected


def test_real_review_is_exported_with_receipt_and_never_upgrades_sources(revisions, tmp_path):
    service = ResearchArtifactService(ResearchArtifactStore(tmp_path / "artifacts.sqlite"), clock=lambda: datetime(2026, 11, 6, tzinfo=timezone.utc))
    revision = revisions["vietnam_dcf"]
    receipt = service.review_revision(revision["revision_id"], decision="acknowledged", note="Đã đọc kịch bản; nguồn chưa xác minh", reviewer="Synthetic operator")
    saved = service.get_revision(revision["revision_id"])
    report = render_revision_markdown(saved)
    assert receipt["event"]["review_id"].replace("_", "\\_") in report
    assert "Synthetic operator" in report
    assert "Đã đọc kịch bản; nguồn chưa xác minh" in report
    assert attachment(report)["verification_status"] == "user_supplied_unverified"
    assert attachment(report)["review_history"] == saved["review_history"]


@pytest.mark.parametrize("mutation", ["kind", "unhashable_kind", "no_request", "nonfinite", "bad_status", "failed_result", "not_json", "unsupported_code"])
def test_invalid_revision_errors_are_stable_and_do_not_echo_content(revisions, mutation):
    revision = revisions["vietnam_dcf"]
    if mutation == "kind": revision["kind"] = "arbitrary-command"
    elif mutation == "unhashable_kind": revision["kind"] = []
    elif mutation == "no_request": del revision["request"]
    elif mutation == "nonfinite": revision["result"]["private"] = float("inf")
    elif mutation == "bad_status": revision["verification_status"] = "verified"
    elif mutation == "failed_result": revision["result"]["ok"] = False
    elif mutation == "not_json": revision["private"] = object()
    else:
        revision["kind"] = "vietnam"
        revision["request"]["code"] = {"private": "not-a-symbol"}
    with pytest.raises(ReportExportError) as exc:
        render_revision_markdown(revision)
    assert exc.value.code == "INVALID_REPORT_REVISION"
    assert "private" not in str(exc.value)


def test_oversized_complete_report_is_rejected_instead_of_truncating(revisions):
    revision = revisions["vietnam_dcf"]
    revision["limitations"] = ["ạ" * 60000]
    with pytest.raises(ReportExportError) as exc:
        render_revision_markdown(revision)
    assert exc.value.code == "REPORT_TOO_LARGE"
