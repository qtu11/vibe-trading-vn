"""Durable admission, idempotent replay, failed refreshes and schema migration."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import threading

import pytest

from backtest.loaders import local_loader
from src.research_artifacts import service as module
from src.research_artifacts.service import ResearchArtifactService, _scope
from src.research_artifacts.store import ArtifactError, ResearchArtifactStore, _SCHEMA, digest

EXAMPLES = Path(__file__).resolve().parents[2] / "docs/examples"
QUERY = {"code": "CASE.VN", "as_of": "2026-11-06T00:00:00Z"}
NOW = datetime(2026, 11, 6, 12, tzinfo=timezone.utc)
KEY = "research_request_001"


@pytest.fixture
def research(tmp_path, monkeypatch):
    source = tmp_path / "statements.json"
    source.write_bytes((EXAMPLES / "vn-company-research.example.json").read_bytes())
    monkeypatch.setattr(local_loader, "_load_config", lambda: {"financial_statements": [{"symbol": "CASE.VN", "path": str(source)}]})
    service = ResearchArtifactService(ResearchArtifactStore(tmp_path / "reports" / "artifacts.sqlite"), clock=lambda: NOW)
    return service, source


def save(service, request=None, **kwargs):
    return service.execute_and_save("vietnam", QUERY if request is None else request, **kwargs)


def reserve_without_execution(service, *, request=None, key=KEY, parent=None):
    original = QUERY if request is None else request
    normalized = service._normalize("vietnam", original)
    return service.store.reserve_attempt(kind="vietnam", request=normalized, scope=_scope("vietnam", normalized),
        caller_hash=digest({"kind": "vietnam", "request": original, "parent_revision_id": parent}),
        parent_revision_id=parent, idempotency_key=key, clock=service.clock)[0]


def test_successful_key_replays_original_result_without_engine_source_or_producer(research, monkeypatch):
    service, source = research
    first = save(service, idempotency_key=KEY)
    source.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(service, "_calculate", lambda *_: pytest.fail("Replay ran engine"))
    monkeypatch.setattr(module, "_producer", lambda *_: pytest.fail("Replay read producer source"))
    replayed = save(service, idempotency_key=KEY)
    assert replayed == first
    assert service.list_revisions()["total"] == service.list_attempts()["total"] == 1
    receipt = service.list_attempts(idempotency_key=KEY)["items"][0]
    assert receipt["status"] == "succeeded" and receipt["revision_id"] == first["revision_id"]
    assert receipt["finished_at"] and receipt["request_sha256"] == first["hashes"]["request_sha256"]
    assert "request" not in receipt


def test_omitted_cutoff_is_bound_to_original_request_not_retry_clock(research):
    service, _ = research
    first = save(service, {"code": "CASE.VN"}, idempotency_key=KEY)
    service.clock = lambda: NOW + timedelta(days=2)
    replay = save(service, {"code": "CASE.VN"}, idempotency_key=KEY)
    assert replay["revision_id"] == first["revision_id"]
    assert replay["request"]["as_of"] == "2026-11-06T12:00:00.000000Z"
    assert replay["created_at"] == first["created_at"]


def test_replay_reads_current_review_state_without_mutating_saved_result(research):
    service, _ = research
    first = save(service, idempotency_key=KEY)
    service.review_revision(first["revision_id"], decision="acknowledged", note="Read, source unverified", reviewer="Local")
    replay = save(service, idempotency_key=KEY)
    assert replay["review_state"] == "acknowledged"
    assert replay["hashes"] == first["hashes"] and replay["result"] == first["result"]


@pytest.mark.parametrize("change", ["input", "parent", "kind"])
def test_reusing_key_for_different_input_parent_or_kind_conflicts(research, change):
    service, _ = research
    first = save(service, idempotency_key=KEY)
    with pytest.raises(ArtifactError) as error:
        if change == "kind":
            service.execute_and_save("crypto_basis", QUERY, idempotency_key=KEY)
        else:
            save(service, dict(QUERY, as_of="2026-11-05T00:00:00Z") if change == "input" else QUERY,
                 parent_revision_id=first["revision_id"] if change == "parent" else None, idempotency_key=KEY)
    assert error.value.code == "IDEMPOTENCY_CONFLICT"
    assert error.value.receipt["revision_id"] == first["revision_id"]
    assert service.list_revisions()["total"] == service.list_attempts()["total"] == 1


def test_concurrent_same_key_has_one_owner_and_no_engine_held_database_lock(research, monkeypatch):
    service, _ = research
    original = service._calculate
    entered, release = threading.Event(), threading.Event()
    calls = []
    def blocked(*args):
        calls.append(args)
        entered.set()
        assert release.wait(5)
        return original(*args)
    monkeypatch.setattr(service, "_calculate", blocked)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(save, service, idempotency_key=KEY)
        try:
            assert entered.wait(5)
            # The owner's engine is blocked, but read/admission transactions
            # must still finish without waiting for its execution.
            assert service.list_attempts()["items"][0]["status"] == "in_flight_unknown"
            with pytest.raises(ArtifactError) as error:
                save(service, idempotency_key=KEY)
            assert error.value.code == "RESEARCH_ATTEMPT_IN_FLIGHT"
            assert error.value.receipt["status"] == "in_flight_unknown"
            with pytest.raises(ArtifactError) as error:
                save(service, dict(QUERY, period="annual"), idempotency_key=KEY)
            assert error.value.code == "IDEMPOTENCY_CONFLICT"
        finally:
            release.set()
        revision = first.result(5)
    assert len(calls) == 1
    assert save(service, idempotency_key=KEY)["revision_id"] == revision["revision_id"]
    assert service.list_attempts()["total"] == service.list_revisions()["total"] == 1


def test_two_concurrent_admissions_cannot_reserve_same_key_twice(research, monkeypatch):
    service, _ = research
    barrier = threading.Barrier(2)
    reserve = service.store.reserve_attempt
    calculate = service._calculate
    calls = []
    def simultaneous(**kwargs):
        barrier.wait(5)
        return reserve(**kwargs)
    def count(*args):
        calls.append(args)
        return calculate(*args)
    monkeypatch.setattr(service.store, "reserve_attempt", simultaneous)
    monkeypatch.setattr(service, "_calculate", count)
    def run():
        try:
            return save(service, idempotency_key=KEY)
        except ArtifactError as exc:
            assert exc.code == "RESEARCH_ATTEMPT_IN_FLIGHT"
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run) for _ in range(2)]
        completed = [future.result(10) for future in futures]
    assert any(item is not None for item in completed)
    assert len(calls) == service.list_attempts()["total"] == service.list_revisions()["total"] == 1


def test_interrupted_admission_remains_unknown_after_new_service_and_never_auto_reexecutes(research, monkeypatch):
    service, _ = research
    pending = reserve_without_execution(service)
    restarted = ResearchArtifactService(ResearchArtifactStore(service.store.path), clock=lambda: NOW + timedelta(days=30))
    monkeypatch.setattr(restarted, "_calculate", lambda *_: pytest.fail("Crash survivor was re-executed"))
    with pytest.raises(ArtifactError) as error:
        save(restarted, idempotency_key=KEY)
    assert error.value.code == "RESEARCH_ATTEMPT_IN_FLIGHT"
    assert error.value.receipt["attempt_id"] == pending["attempt_id"]
    assert restarted.list_revisions()["total"] == 0
    assert restarted.list_attempts()["items"][0]["status"] == "in_flight_unknown"


def test_failed_refresh_retains_last_good_and_replays_failure_without_running_again(research, monkeypatch):
    service, source = research
    first = save(service)
    source.write_text("{}", encoding="utf-8")
    with pytest.raises(ArtifactError) as error:
        save(service, parent_revision_id=first["revision_id"], idempotency_key=KEY)
    assert error.value.code == "RESEARCH_FAILED"
    receipt = error.value.receipt
    assert receipt["status"] == "failed" and receipt["error"]["stage"] == "engine"
    listing = service.list_attempts(parent_revision_id=first["revision_id"])
    assert listing["refresh_state"]["state"] == "refresh_failed"
    assert listing["refresh_state"]["last_good_revision_id"] == first["revision_id"]
    assert service.get_revision(first["revision_id"]) == first
    source.write_bytes((EXAMPLES / "vn-company-research.example.json").read_bytes())
    monkeypatch.setattr(service, "_calculate", lambda *_: pytest.fail("Failed key was re-executed"))
    with pytest.raises(ArtifactError) as replay:
        save(service, parent_revision_id=first["revision_id"], idempotency_key=KEY)
    assert replay.value.code == "RESEARCH_FAILED" and replay.value.receipt == receipt


def test_later_failed_refresh_retains_latest_successful_child_as_last_good(research):
    service, source = research
    parent = save(service)
    child = save(service, parent_revision_id=parent["revision_id"], idempotency_key="successful_child")
    assert service.list_attempts(parent_revision_id=parent["revision_id"])["refresh_state"]["state"] == "superseded"
    source.write_text("{}", encoding="utf-8")
    with pytest.raises(ArtifactError):
        save(service, parent_revision_id=parent["revision_id"], idempotency_key="failed_child_001")
    state = service.list_attempts(parent_revision_id=parent["revision_id"])["refresh_state"]
    assert state["state"] == "refresh_failed" and state["last_good_revision_id"] == child["revision_id"]
    assert service.get_revision(parent["revision_id"]) == parent


def test_pending_refresh_has_visible_unknown_state_without_restamping_parent(research):
    service, _ = research
    parent = save(service)
    pending = reserve_without_execution(service, parent=parent["revision_id"])
    state = service.list_attempts(parent_revision_id=parent["revision_id"])["refresh_state"]
    assert state["state"] == "refresh_in_flight_unknown"
    assert state["last_attempt"]["attempt_id"] == pending["attempt_id"]
    assert service.get_revision(parent["revision_id"]) == parent


def test_producer_failure_is_retained_and_private_exception_text_never_persisted(research, monkeypatch):
    service, _ = research
    def fail(_):
        raise OSError("C:/private/provider-token secret")
    monkeypatch.setattr(module, "_producer", fail)
    with pytest.raises(ArtifactError) as error:
        save(service, idempotency_key=KEY)
    assert error.value.code == "RESEARCH_EXECUTION_FAILED"
    assert error.value.receipt["error"]["stage"] == "producer"
    assert error.value.receipt["error"]["exception_type"] == "OSError"
    assert "provider-token" not in str(error.value) + json.dumps(service.list_attempts())
    assert service.list_revisions()["total"] == 0


def test_failure_persistence_error_keeps_outcome_unknown_and_retry_never_runs_engine(research, monkeypatch):
    service, source = research
    source.write_text("{}", encoding="utf-8")
    def unavailable(*args, **kwargs):
        raise OSError("private db path")
    monkeypatch.setattr(service.store, "finish_attempt_failure", unavailable)
    with pytest.raises(ArtifactError) as error:
        save(service, idempotency_key=KEY)
    assert error.value.code == "RESEARCH_ATTEMPT_UNCERTAIN"
    assert error.value.receipt["status"] == "in_flight_unknown"
    monkeypatch.setattr(service, "_calculate", lambda *_: pytest.fail("Unknown outcome retried engine"))
    with pytest.raises(ArtifactError) as replay:
        save(service, idempotency_key=KEY)
    assert replay.value.code == "RESEARCH_ATTEMPT_IN_FLIGHT"
    assert service.list_attempts()["total"] == 1 and service.list_revisions()["total"] == 0


def test_revision_and_success_outcome_are_one_atomic_transaction(research, monkeypatch):
    service, _ = research
    def fail_after_revision(*args, **kwargs):
        raise sqlite3.OperationalError("Cannot commit outcome")
    monkeypatch.setattr(service.store, "_append_outcome", fail_after_revision)
    with pytest.raises(ArtifactError) as error:
        save(service, idempotency_key=KEY)
    assert error.value.code == "RESEARCH_ATTEMPT_UNCERTAIN"
    assert service.list_revisions()["total"] == 0
    assert service.list_attempts()["items"][0]["status"] == "in_flight_unknown"
    with sqlite3.connect(service.store.path) as connection:
        assert connection.execute("SELECT count(*) FROM attempt_outcomes").fetchone()[0] == 0


def test_lost_success_receipt_is_recovered_from_committed_terminal_outcome(research, monkeypatch):
    service, _ = research
    original = service.store.finish_attempt_success
    def commit_then_fail(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("Response lost after commit")
    monkeypatch.setattr(service.store, "finish_attempt_success", commit_then_fail)
    revision = save(service, idempotency_key=KEY)
    assert revision["result"]["ok"] is True
    assert service.list_attempts()["items"][0]["revision_id"] == revision["revision_id"]
    assert service.list_revisions()["total"] == 1


def test_clock_rewind_during_success_cannot_complete_before_revision_creation(research):
    service, _ = research
    timestamps = iter([NOW, NOW + timedelta(seconds=3), NOW + timedelta(seconds=4), NOW + timedelta(seconds=2)])
    service.clock = lambda: next(timestamps)
    with pytest.raises(ArtifactError) as error:
        save(service, idempotency_key=KEY)
    assert error.value.code == "RESEARCH_ATTEMPT_UNCERTAIN"
    assert service.list_revisions()["total"] == 0
    assert service.list_attempts()["items"][0]["status"] == "in_flight_unknown"


def test_clock_rewind_at_append_cannot_put_revision_before_attempt_admission(research):
    service, _ = research
    # A later outcome timestamp must not hide a rewind at the revision append.
    timestamps = iter([NOW, NOW + timedelta(seconds=3), NOW - timedelta(seconds=1), NOW + timedelta(seconds=1)])
    service.clock = lambda: next(timestamps)
    with pytest.raises(ArtifactError) as error:
        save(service, idempotency_key=KEY)
    assert error.value.code == "RESEARCH_ATTEMPT_UNCERTAIN"
    assert error.value.receipt["status"] == "in_flight_unknown"
    assert error.value.receipt["created_at"] == "2026-11-06T12:00:00.000000Z"
    assert service.list_revisions()["total"] == 0
    with sqlite3.connect(service.store.path) as connection:
        assert connection.execute("SELECT count(*) FROM attempt_outcomes").fetchone()[0] == 0


def legacy_store(service, path):
    revision = save(service)
    service.review_revision(revision["revision_id"], decision="acknowledged", note="Existing review", reviewer="Local")
    with closing(sqlite3.connect(service.store.path)) as source, closing(sqlite3.connect(path)) as target:
        target.executescript(_SCHEMA)
        target.executemany("INSERT INTO revisions VALUES(?,?,?,?,?,?)", source.execute("SELECT * FROM revisions").fetchall())
        target.executemany("INSERT INTO reviews VALUES(?,?,?,?,?)", source.execute("SELECT * FROM reviews").fetchall())
        target.commit()
    return ResearchArtifactService(ResearchArtifactStore(path), clock=lambda: NOW), service.get_revision(revision["revision_id"])


def test_schema1_reads_are_byte_preserving_and_write_migration_keeps_old_manifests(research, tmp_path):
    service, _ = research
    old, revision = legacy_store(service, tmp_path / "legacy.sqlite")
    original_bytes = old.store.path.read_bytes()
    assert old.get_revision(revision["revision_id"]) == revision
    assert old.list_revisions()["total"] == 1
    assert old.list_attempts()["items"] == []
    assert old.list_attempts(parent_revision_id=revision["revision_id"])["refresh_state"]["state"] == "no_refresh_attempt"
    assert old.store.path.read_bytes() == original_bytes
    with sqlite3.connect(old.store.path) as connection:
        prior_row = connection.execute("SELECT manifest,manifest_sha256 FROM revisions").fetchone()
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
    child = save(old, parent_revision_id=revision["revision_id"], idempotency_key=KEY)
    with sqlite3.connect(old.store.path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
        assert connection.execute("SELECT manifest,manifest_sha256 FROM revisions WHERE revision_id=?", (revision["revision_id"],)).fetchone() == prior_row
    assert old.get_revision(revision["revision_id"]) == revision
    assert old.list_attempts()["items"][0]["revision_id"] == child["revision_id"]


def test_read_missing_attempts_never_creates_runtime_directories(tmp_path):
    service = ResearchArtifactService(ResearchArtifactStore(tmp_path / "missing" / "artifacts.sqlite"))
    assert service.list_attempts() == {"items": [], "total": 0, "next_offset": None, "refresh_state": None}
    assert service.list_attempts(idempotency_key=KEY)["items"] == []
    assert not service.store.path.parent.exists()


def test_attempt_and_terminal_events_are_append_only(research):
    service, _ = research
    save(service, idempotency_key=KEY)
    with sqlite3.connect(service.store.path) as connection:
        for table in ("attempts", "attempt_outcomes"):
            for statement in (f"UPDATE {table} SET attempt_id=attempt_id", f"DELETE FROM {table}"):
                with pytest.raises(sqlite3.IntegrityError, match="append-only"):
                    connection.execute(statement)


def test_corrupted_attempt_cannot_replay_or_silently_disappear(research):
    service, _ = research
    save(service, idempotency_key=KEY)
    with sqlite3.connect(service.store.path) as connection:
        connection.execute("DROP TRIGGER immutable_attempt_update")
        connection.execute("UPDATE attempts SET manifest='{}'")
    for operation in (lambda: save(service, idempotency_key=KEY), lambda: service.list_attempts()):
        with pytest.raises(ArtifactError) as error:
            operation()
        assert error.value.code == "ARTIFACT_INTEGRITY_ERROR"
    assert service.list_revisions()["total"] == 1


def test_no_key_preserves_distinct_saves_and_exact_paged_attempt_counts(research):
    service, _ = research
    first, second = save(service), save(service)
    assert first["revision_id"] != second["revision_id"]
    first_page = service.list_attempts(limit=1)
    assert first_page["total"] == 2 and first_page["next_offset"] == 1
    second_page = service.list_attempts(limit=1, offset=1)
    assert second_page["next_offset"] is None
    assert first_page["items"][0]["idempotency_key"] is None
    assert first_page["items"][0]["attempt_id"] != second_page["items"][0]["attempt_id"]


@pytest.mark.parametrize("key", [True, 123, "short", "a" * 129, "with space", "with/slash", "có_dấu_key", "api:key:value"])
def test_invalid_idempotency_keys_fail_before_storage_creation(research, key):
    service, _ = research
    with pytest.raises(ArtifactError) as error:
        save(service, idempotency_key=key)
    assert error.value.code == "INVALID_ARGUMENT"
    assert not service.store.path.parent.exists()


@pytest.mark.parametrize("kwargs", [{"limit": True}, {"offset": -1}, {"kind": "shell"}, {"idempotency_key": "../badkey"}])
def test_attempt_query_bounds_are_strict_before_file_access(tmp_path, kwargs):
    service = ResearchArtifactService(ResearchArtifactStore(tmp_path / "missing" / "artifacts.sqlite"))
    with pytest.raises(ArtifactError):
        service.list_attempts(**kwargs)
    assert not service.store.path.parent.exists()
