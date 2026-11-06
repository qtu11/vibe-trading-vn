"""Actual deterministic executions, immutable provenance and bounded deltas."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

import pytest

from backtest.loaders import local_loader
from src.research_artifacts.service import ResearchArtifactService
from src.research_artifacts.store import ArtifactError, ResearchArtifactStore, canonical, digest

EXAMPLES = Path(__file__).resolve().parents[2] / "docs" / "examples"
NOW = datetime(2026, 11, 6, 0, 0, tzinfo=timezone.utc)
QUERY = {"code": "CASE.VN", "as_of": "2026-11-05T00:00:00Z"}


@pytest.fixture
def research(tmp_path, monkeypatch):
    source = tmp_path / "source.json"
    source.write_bytes((EXAMPLES / "vn-company-research.example.json").read_bytes())
    monkeypatch.setattr(local_loader, "_load_config", lambda: {"financial_statements": [{"symbol": "CASE.VN", "path": str(source)}]})
    store = ResearchArtifactStore(tmp_path / "reports" / "artifacts.sqlite")
    return ResearchArtifactService(store, clock=lambda: NOW), source


def save(service, **kwargs):
    return service.execute_and_save("vietnam", QUERY, **kwargs)


def test_actual_server_execution_preserves_result_and_provenance(research):
    service, source = research
    revision = save(service)
    assert revision["result"]["ok"] is True
    assert revision["result"]["data"]["CASE.VN"]["source_file_sha256"]
    assert revision["result"]["data"]["CASE.VN"]["periods"][0]["inputs"]["income.revenue"]["value"] == "270000000"
    assert revision["content_scope"] == "one_returned_research_page"
    assert revision["verification_status"] == "user_supplied_unverified"
    assert revision["review_state"] == "pending_review" and revision["review_history"] == []
    assert revision["hashes"]["request_sha256"] == digest(revision["request"])
    assert revision["hashes"]["result_sha256"] == digest(revision["result"])
    assert "src.tools.vietnam_research_tool" in revision["producer"]["source_sha256"]
    assert service.get_revision(revision["revision_id"]) == revision
    assert service.list_revisions()["items"][0]["revision_id"] == revision["revision_id"]
    assert source.name not in canonical(revision["producer"])


def test_read_methods_do_not_initialize_missing_runtime_tree(tmp_path):
    path = tmp_path / "missing" / "artifacts.sqlite"
    service = ResearchArtifactService(ResearchArtifactStore(path))
    assert service.list_revisions() == {"items": [], "total": 0, "next_offset": None}
    with pytest.raises(ArtifactError, match="not found"):
        service.get_revision("rr_" + "a" * 32)
    with pytest.raises(ArtifactError, match="not found"):
        service.review_revision("rr_" + "a" * 32, decision="acknowledged", note="Read", reviewer="Local")
    assert not path.parent.exists()


def test_reexecution_creates_distinct_revision_without_overwriting_parent(research):
    service, _ = research
    first = save(service)
    second = save(service, parent_revision_id=first["revision_id"])
    assert first["revision_id"] != second["revision_id"]
    assert second["parent_revision_id"] == first["revision_id"]
    assert first["hashes"] == second["hashes"]
    assert service.get_revision(first["revision_id"]) == first
    diff = service.diff_revisions(first["revision_id"], second["revision_id"])
    assert diff["total_changes"] == 0 and diff["changes"] == []
    assert diff["affected_metrics"] == []
    assert not any(diff[name + "_changed"] for name in ("request", "result", "source", "facts", "producer"))


def test_fact_restatement_flags_only_dependent_metric_inputs(research):
    service, path = research
    first = save(service)
    payload = json.loads(path.read_text(encoding="utf-8"))
    # Change only cash-flow capex, keeping declared evidence unchanged. The
    # raw source hash changes, but unrelated margins do not become dependent.
    cashflows = [row for row in payload["records"] if row["statement"] == "cashflow"]
    cashflows[-1]["facts"]["capex"]["value"] = "999"
    path.write_text(json.dumps(payload), encoding="utf-8")
    second = save(service, parent_revision_id=first["revision_id"])
    diff = service.diff_revisions(first["revision_id"], second["revision_id"], limit=2)
    assert diff["facts_changed"] and diff["source_changed"] and diff["result_changed"]
    assert diff["request_changed"] is False and diff["producer_changed"] is False
    assert diff["truncated"] is True and len(diff["changes"]) == 2
    assert diff["total_changes"] > len(diff["changes"])
    names = {row["metric"] for row in diff["affected_metrics"]}
    assert "free_cash_flow" in names
    assert "net_margin" not in names and "balance_residual" not in names
    assert service.get_revision(first["revision_id"]) == first


def test_evidence_revision_flags_dependent_metrics_without_changing_facts(research):
    service, path = research
    first = save(service)
    payload = json.loads(path.read_text(encoding="utf-8"))
    for row in payload["records"]:
        if row["statement"] == "income":
            row["document_sha256"] = "c" * 64
    path.write_text(json.dumps(payload), encoding="utf-8")
    second = save(service, parent_revision_id=first["revision_id"])
    diff = service.diff_revisions(first["revision_id"], second["revision_id"])
    assert diff["source_changed"] and not diff["facts_changed"]
    names = {row["metric"] for row in diff["affected_metrics"]}
    assert "net_margin" in names
    assert "free_cash_flow" not in names and "balance_residual" not in names


def test_transitive_working_capital_dependency_and_null_vs_zero_are_explicit(research):
    service, path = research
    payload = json.loads(path.read_text(encoding="utf-8"))
    for row in payload["records"]:
        if row["statement"] == "balance":
            row["facts"]["accounts_receivable"] = {"value": "0", "unit": "VND", "scale": 1}
    path.write_text(json.dumps(payload), encoding="utf-8")
    first = save(service)
    for row in payload["records"]:
        if row["statement"] == "balance" and row["period_end"] == "2025-06-30":
            row["facts"]["accounts_receivable"]["value"] = None
    path.write_text(json.dumps(payload), encoding="utf-8")
    second = save(service)
    diff = service.diff_revisions(first["revision_id"], second["revision_id"])
    changed = [row for row in diff["changes"] if row["path"].endswith("/balance.accounts_receivable/value")]
    assert changed and any(row["before"] == "0" and row["after"] is None for row in changed)
    affected = {row["metric"]: row for row in diff["affected_metrics"]}
    assert affected["dso"]["changed_inputs"] == ["balance.accounts_receivable"]
    assert affected["cash_conversion_cycle"]["changed_inputs"] == ["balance.accounts_receivable"]
    assert "free_cash_flow" not in affected


def test_cutoff_change_is_not_falsely_reported_as_source_change(research):
    service, _ = research
    first = save(service)
    second = service.execute_and_save("vietnam", dict(QUERY, as_of="2026-11-06T00:00:00Z"))
    diff = service.diff_revisions(first["revision_id"], second["revision_id"])
    assert diff["request_changed"] and diff["result_changed"]
    assert not diff["source_changed"] and not diff["facts_changed"]
    assert not diff["affected_metrics"]


def test_acknowledgment_is_append_only_and_never_verifies_evidence(research):
    service, _ = research
    original = save(service)
    for decision in ("acknowledged", "changes_requested"):
        result = service.review_revision(original["revision_id"], decision=decision, note="Đã đọc, cần rà nguồn", reviewer="Người kiểm tra")
        assert result["verification_status"] == "user_supplied_unverified"
        assert result["event"]["reviewer_identity"] == "self_reported_operator_label"
    current = service.get_revision(original["revision_id"])
    assert current["review_state"] == "changes_requested"
    assert [event["decision"] for event in current["review_history"]] == ["acknowledged", "changes_requested"]
    assert current["hashes"] == original["hashes"] and current["result"] == original["result"]
    assert current["created_at"] == original["created_at"]


def test_sql_triggers_refuse_update_and_delete(research):
    service, _ = research
    revision = save(service)
    service.review_revision(revision["revision_id"], decision="acknowledged", note="Read", reviewer="Local")
    with sqlite3.connect(service.store.path) as connection:
        for table in ("revisions", "reviews"):
            for operation in (f"UPDATE {table} SET revision_id=revision_id", f"DELETE FROM {table}"):
                with pytest.raises(sqlite3.IntegrityError, match="append-only"):
                    connection.execute(operation)


def test_modified_manifest_fails_read_listing_and_diff(research):
    service, _ = research
    first, second = save(service), save(service)
    with sqlite3.connect(service.store.path) as connection:
        connection.execute("DROP TRIGGER immutable_revision_update")
        connection.execute("UPDATE revisions SET manifest='{}' WHERE revision_id=?", (first["revision_id"],))
    for call in (lambda: service.get_revision(first["revision_id"]), lambda: service.list_revisions(),
                 lambda: service.diff_revisions(first["revision_id"], second["revision_id"])):
        with pytest.raises(ArtifactError) as error:
            call()
        assert error.value.code == "ARTIFACT_INTEGRITY_ERROR"


def test_modified_review_fails_instead_of_silently_resetting_state(research):
    service, _ = research
    revision = save(service)
    service.review_revision(revision["revision_id"], decision="acknowledged", note="Read", reviewer="Local")
    with sqlite3.connect(service.store.path) as connection:
        connection.execute("DROP TRIGGER immutable_review_update")
        connection.execute("UPDATE reviews SET event='{}'")
    with pytest.raises(ArtifactError) as error:
        service.get_revision(revision["revision_id"])
    assert error.value.code == "ARTIFACT_INTEGRITY_ERROR"


def test_failed_refresh_preserves_last_good_revision_without_restamping(research):
    service, path = research
    original = save(service)
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ArtifactError) as error:
        save(service, parent_revision_id=original["revision_id"])
    assert error.value.code == "RESEARCH_FAILED"
    assert service.list_revisions()["total"] == 1
    assert service.get_revision(original["revision_id"]) == original


def test_explicit_defaults_and_clock_cutoff_are_saved(research):
    service, _ = research
    result = service.execute_and_save("vietnam", {"code": "CASE.VN"})
    assert result["request"] == {"code": "CASE.VN", "period": "quarter", "consolidation": "consolidated",
                                 "offset": 0, "as_of": "2026-11-06T00:00:00.000000Z"}


def test_comparables_executes_full_supplied_set_and_preserves_display_paging(research):
    service, _ = research
    payload = json.loads((EXAMPLES / "vn-comparables.example.json").read_text(encoding="utf-8"))
    revision = service.execute_and_save("vietnam_comparables", {"payload": payload})
    assert revision["result"]["target"]["scenarios"]["pe"]["prices"]["median"] == 20000
    assert revision["result"]["paging"]["total"] == 3
    assert revision["scope"]["symbol"] == "CASE.VN"
    assert service.list_revisions(kind="vietnam_comparables")["total"] == 1


def test_dcf_fixed_server_dispatch_preserves_input_and_code_hashes(research):
    service, _ = research
    payload = json.loads((EXAMPLES / "vn-dcf.example.json").read_text(encoding="utf-8"))
    result = service.execute_and_save("vietnam_dcf", payload)
    assert result["result"]["methodology"] == "declared_non_financial_fcff_scenario"
    assert result["result"]["base_case"]["value_per_share"] > 0
    assert result["content_scope"] == "one_bounded_dcf_scenario"
    assert "src.quantlib.valuation.dcf" in result["producer"]["source_sha256"]
    assert service.list_revisions(kind="vietnam_dcf")["total"] == 1


def test_scope_mismatch_refuses_parent_link_and_diff(research):
    service, _ = research
    first = save(service)
    other = service.execute_and_save("vietnam", dict(QUERY, consolidation="separate"))
    with pytest.raises(ArtifactError) as error:
        service.diff_revisions(first["revision_id"], other["revision_id"])
    assert error.value.code == "INCOMPATIBLE_SCOPE"
    with pytest.raises(ArtifactError) as error:
        service.execute_and_save("vietnam", dict(QUERY, consolidation="separate"), parent_revision_id=first["revision_id"])
    assert error.value.code == "REVISION_SCOPE_MISMATCH"
    assert service.list_revisions()["total"] == 2


def test_concurrent_creates_and_reviews_do_not_overwrite(research):
    service, _ = research
    with ThreadPoolExecutor(max_workers=4) as pool:
        revisions = list(pool.map(lambda _: save(service), range(8)))
    ids = {revision["revision_id"] for revision in revisions}
    assert len(ids) == service.list_revisions()["total"] == 8
    revision_id = revisions[0]["revision_id"]
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda number: service.review_revision(revision_id, decision="acknowledged", note=f"Review {number}", reviewer="Local"), range(8)))
    assert len(service.get_revision(revision_id)["review_history"]) == 8


def test_foreign_database_is_never_migrated_or_overwritten(tmp_path):
    path = tmp_path / "foreign.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE unrelated(value TEXT)")
    store = ResearchArtifactStore(path)
    with pytest.raises(ArtifactError) as error:
        store.list_revisions()
    assert error.value.code == "ARTIFACT_STORE_INVALID"
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 0
        assert connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [("unrelated",)]


def test_reading_existing_revisions_does_not_change_database_bytes(research):
    service, _ = research
    first, second = save(service), save(service)
    original = service.store.path.read_bytes()
    service.get_revision(first["revision_id"])
    service.list_revisions()
    service.diff_revisions(first["revision_id"], second["revision_id"])
    assert service.store.path.read_bytes() == original


def test_write_refuses_existing_foreign_database_without_schema_migration(research):
    service, _ = research
    service.store.path.parent.mkdir()
    with sqlite3.connect(service.store.path) as connection:
        connection.execute("CREATE TABLE unrelated(value TEXT)")
        connection.execute("INSERT INTO unrelated VALUES ('keep')")
    original = service.store.path.read_bytes()
    with pytest.raises(ArtifactError) as error:
        save(service)
    assert error.value.code == "ARTIFACT_STORE_INVALID"
    assert service.store.path.read_bytes() == original


def test_backward_recording_clock_fails_append_and_review(research):
    service, _ = research
    revision = save(service)
    service.clock = lambda: datetime(2026, 1, 1, tzinfo=timezone.utc)
    for call in (lambda: save(service), lambda: service.review_revision(revision["revision_id"], decision="acknowledged", note="Read", reviewer="Local")):
        with pytest.raises(ArtifactError) as error:
            call()
        assert error.value.code == "ARTIFACT_CLOCK_REGRESSION"
    assert service.list_revisions()["total"] == 1


@pytest.mark.parametrize("payload", [dict(QUERY, result={"ok": True}), dict(QUERY, tool="bash"),
                                     dict(QUERY, offset=True), dict(QUERY, offset=-1), dict(QUERY, as_of="2026-01-01"),
                                     dict(QUERY, code="../../secret"), dict(QUERY, period="month"), dict(QUERY, consolidation="mixed")])
def test_invalid_requests_cannot_forge_server_results_or_paths(research, payload):
    service, _ = research
    with pytest.raises(ArtifactError):
        service.execute_and_save("vietnam", payload)
    assert not service.store.path.exists()


@pytest.mark.parametrize("revision_id", ["../secrets", "a", "rr_" + "A" * 32, None])
def test_invalid_ids_fail_before_any_file_creation(tmp_path, revision_id):
    store = ResearchArtifactStore(tmp_path / "missing" / "artifacts.sqlite")
    with pytest.raises(ArtifactError):
        store.get_revision(revision_id)
    assert not store.path.parent.exists()


@pytest.mark.parametrize("kwargs", [{"limit": True}, {"limit": 101}, {"offset": -1}, {"kind": "bash"}])
def test_listing_bounds_apply_even_when_store_does_not_exist(tmp_path, kwargs):
    with pytest.raises(ArtifactError):
        ResearchArtifactStore(tmp_path / "missing.sqlite").list_revisions(**kwargs)


def test_listing_has_exact_stable_pagination_when_clock_is_equal(research):
    service, _ = research
    ids = [save(service)["revision_id"] for _ in range(3)]
    first = service.list_revisions(limit=2)
    assert [row["revision_id"] for row in first["items"]] == ids[::-1][:2]
    assert first["total"] == 3 and first["next_offset"] == 2
    final = service.list_revisions(limit=2, offset=2)
    assert [row["revision_id"] for row in final["items"]] == ids[:1]
    assert final["next_offset"] is None
