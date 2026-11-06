"""Synthetic, temp-directory-only derivative captures; no exchange requests."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import sqlite3

import pytest

from src.tools import crypto_derivatives_archive as archive_mod
from src.tools import crypto_derivatives_tool as tool_mod
from src.tools.crypto_derivatives_archive import ArchiveError, DerivativesArchive, digest, iso

_EVENT = 1_700_000_000_000
_DAY = datetime(2024, 1, 1, tzinfo=timezone.utc)
_SYMBOL = "BTC-USDT-PERP"
_MARKET = {"symbol": "BTC/USDT:USDT", "base": "BTC", "quote": "USDT", "settle": "USDT",
           "swap": True, "linear": True, "inverse": False, "expiry": None, "contractSize": 1}


def _oi(q=10, timestamp_ms=_EVENT):
    return {"symbol": _MARKET["symbol"], "timestamp": timestamp_ms,
            "openInterestAmount": q, "openInterestValue": q * 100}


def _funding(rate_type=None, rate=0.001, timestamp_ms=_EVENT):
    return {"symbol": _MARKET["symbol"], "timestamp": timestamp_ms, "fundingRate": rate,
            "info": {"symbol": "BTCUSDT", "fundingTime": timestamp_ms,
                     "markPrice": "100", "rateType": rate_type}}


def _save(archive, rows=None, metric="open_interest", period="1h", retrieved_at=None):
    rows = rows or [_oi()]
    retrieved_at = retrieved_at or iso(_DAY - timedelta(seconds=1))
    normalized = tool_mod._observations(rows, _MARKET["symbol"], metric, 100,
                                       int(archive_mod.timestamp(retrieved_at).timestamp() * 1000))
    return archive.append(symbol=_SYMBOL, metric=metric, period=period if metric == "open_interest" else None,
                          market=_MARKET, raw_rows=rows, observations=normalized, retrieved_at=retrieved_at)


def _query(archive, cutoff=None, metric="open_interest", period="1h", limit=100):
    return archive.query(symbol=_SYMBOL, metric=metric, period=period if metric == "open_interest" else None,
                         as_of=cutoff or iso(_DAY + timedelta(days=3)), limit=limit)


def _archive(tmp_path, moment=_DAY):
    return DerivativesArchive(tmp_path / "captures.sqlite", clock=lambda: moment)


def test_capture_retains_exact_parsed_payload_hash_and_all_normalized_rows(tmp_path):
    archive = _archive(tmp_path)
    raw = [_oi(timestamp_ms=_EVENT + i * 1000) for i in range(100)]
    receipt = _save(archive, raw)
    manifest = archive.get_capture(receipt["capture_id"])
    assert manifest["ccxt_payload"] == {"market": _MARKET, "rows": raw}
    assert len(manifest["observations"]) == 100
    assert receipt["ccxt_payload_sha256"] == digest(manifest["ccxt_payload"])
    assert receipt["normalized_observations_sha256"] == digest(manifest["observations"])
    assert receipt["capture_id"] == digest(manifest)
    assert manifest["retrieved_at"] < manifest["recorded_at"]


def test_capture_time_never_backfills_event_time_availability(tmp_path):
    archive = _archive(tmp_path)
    _save(archive)
    assert _query(archive, iso(_DAY - timedelta(microseconds=1)))["observations"] == []
    row = _query(archive, iso(_DAY))["observations"][0]
    assert row["archive_evidence"]["first_observed_at"] == iso(_DAY)
    assert row["timestamp_ms"] == _EVENT


def test_cutoff_keeps_original_revision_after_later_correction(tmp_path):
    archive = _archive(tmp_path)
    first = _save(archive)
    before = _query(archive, iso(_DAY))
    archive.clock = lambda: _DAY + timedelta(days=1)
    second = _save(archive, [_oi(12)])
    assert first["capture_id"] != second["capture_id"]
    assert _query(archive, iso(_DAY)) == before
    newest = _query(archive)["observations"][0]
    assert newest["amount_base"] == 12
    assert newest["archive_evidence"]["distinct_revisions"] == 2
    assert newest["archive_evidence"]["capture_id"] == second["capture_id"]
    assert _query(archive)["revised_observations"] == 1


def test_clock_regression_cannot_backfill_a_previously_queried_cutoff(tmp_path):
    archive = _archive(tmp_path)
    _save(archive)
    before = _query(archive, iso(_DAY))
    archive.clock = lambda: _DAY - timedelta(microseconds=1)
    with pytest.raises(ArchiveError, match="clock moved backward") as exc:
        _save(archive, [_oi(13)])
    assert exc.value.code == "ARCHIVE_CLOCK_REGRESSION"
    assert _query(archive, iso(_DAY)) == before


def test_identical_overlapping_captures_do_not_duplicate_events_or_revisions(tmp_path):
    archive = _archive(tmp_path)
    _save(archive, [_oi(), _oi(11, _EVENT + 1000)])
    archive.clock = lambda: _DAY + timedelta(days=1)
    _save(archive, [_oi(11, _EVENT + 1000), _oi(12, _EVENT + 2000)])
    result = _query(archive)
    assert [row["amount_base"] for row in result["observations"]] == [10, 11, 12]
    assert result["selected_capture_count"] == 2
    assert result["revised_observations"] == 0
    assert result["observations"][1]["archive_evidence"]["first_observed_at"] == iso(_DAY)


def test_conflicting_latest_recording_time_is_unresolved(tmp_path):
    archive = _archive(tmp_path)
    _save(archive)
    _save(archive, [_oi(12)])
    with pytest.raises(ArchiveError, match="Conflicting revisions") as exc:
        _query(archive)
    assert exc.value.code == "ARCHIVE_CONFLICT"
    # A strictly later capture resolves the tie according to the declared policy.
    archive.clock = lambda: _DAY + timedelta(days=1)
    _save(archive, [_oi(13)])
    assert _query(archive)["observations"][0]["amount_base"] == 13


def test_funding_types_same_timestamp_remain_separate_and_not_oi(tmp_path):
    archive = _archive(tmp_path)
    _save(archive)
    _save(archive, [_funding("Regular"), _funding("Special", -0.001), _funding()], metric="funding")
    result = _query(archive, metric="funding")
    assert len(result["observations"]) == 3
    assert [row["rate_type"] for row in result["observations"]] == [None, "Regular", "Special"]
    assert _query(archive)["observations"][0]["amount_base"] == 10


def test_oi_periods_do_not_merge(tmp_path):
    archive = _archive(tmp_path)
    _save(archive, period="1h")
    _save(archive, [_oi(20)], period="4h")
    assert _query(archive, period="1h")["observations"][0]["amount_base"] == 10
    assert _query(archive, period="4h")["observations"][0]["amount_base"] == 20


def test_query_limits_actual_latest_events_without_filling_gaps(tmp_path):
    archive = _archive(tmp_path)
    _save(archive, [_oi(timestamp_ms=_EVENT + i * 10_000) for i in range(5)])
    result = _query(archive, limit=2)
    assert result["limited"] is True
    assert [row["timestamp_ms"] for row in result["observations"]] == [_EVENT + 30_000, _EVENT + 40_000]


def test_exact_capture_retry_is_idempotent_even_concurrently(tmp_path):
    archive = _archive(tmp_path)
    _save(archive)
    with ThreadPoolExecutor(max_workers=3) as pool:
        receipts = list(pool.map(lambda _: _save(archive), range(6)))
    assert len({item["capture_id"] for item in receipts}) == 1
    with sqlite3.connect(archive.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM captures").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 1


@pytest.mark.parametrize("table", ["captures", "observations"])
@pytest.mark.parametrize("verb", ["UPDATE", "DELETE"])
def test_append_only_triggers_reject_changes(tmp_path, table, verb):
    archive = _archive(tmp_path)
    _save(archive)
    sql = f"UPDATE {table} SET capture_id=capture_id" if verb == "UPDATE" else f"DELETE FROM {table}"
    with sqlite3.connect(archive.path) as connection, pytest.raises(sqlite3.IntegrityError, match="append-only"):
        connection.execute(sql)


def test_query_missing_archive_never_creates_parent_or_database(tmp_path):
    archive = DerivativesArchive(tmp_path / "missing" / "capture.sqlite")
    with pytest.raises(sqlite3.OperationalError):
        _query(archive)
    assert not archive.path.parent.exists()


def test_archive_rejects_unrelated_database_without_migration(tmp_path):
    archive = _archive(tmp_path)
    with sqlite3.connect(archive.path) as connection:
        connection.execute("CREATE TABLE private_state (value TEXT)")
        connection.execute("PRAGMA user_version=1")
    original = archive.path.read_bytes()
    with pytest.raises(ArchiveError, match="schema"):
        _query(archive)
    with pytest.raises(ArchiveError, match="schema"):
        _save(archive)
    assert archive.path.read_bytes() == original


def test_capture_checksum_corruption_fails_closed(tmp_path):
    archive = _archive(tmp_path)
    receipt = _save(archive)
    with sqlite3.connect(archive.path) as connection:
        connection.execute("DROP TRIGGER immutable_captures_update")
        connection.execute("UPDATE captures SET manifest='{}'")
    with pytest.raises(ArchiveError, match="checksum"):
        archive.get_capture(receipt["capture_id"])
    with pytest.raises(ArchiveError, match="checksum"):
        _query(archive)


def test_observation_corruption_fails_closed(tmp_path):
    archive = _archive(tmp_path)
    _save(archive)
    with sqlite3.connect(archive.path) as connection:
        connection.execute("DROP TRIGGER immutable_observations_update")
        connection.execute("UPDATE observations SET observation='{}'")
    with pytest.raises(ArchiveError, match="checksum"):
        _query(archive)


@pytest.mark.parametrize("corruption", ["manifest", "recording_time", "observation", "missing_observation", "missing_full_index"])
def test_older_supporting_capture_corruption_cannot_change_lineage(tmp_path, corruption):
    archive = _archive(tmp_path)
    first = _save(archive, [_oi(), _oi(11, _EVENT + 1000)])
    archive.clock = lambda: _DAY + timedelta(days=1)
    _save(archive, [_oi(12), _oi(13, _EVENT + 1000)])
    with sqlite3.connect(archive.path) as connection:
        for trigger in ("immutable_captures_update", "immutable_observations_update", "immutable_observations_delete"):
            connection.execute(f"DROP TRIGGER {trigger}")
        if corruption == "manifest":
            connection.execute("UPDATE captures SET manifest='{}' WHERE capture_id=?", (first["capture_id"],))
        elif corruption == "recording_time":
            connection.execute("UPDATE captures SET recorded_at='2023-12-31T00:00:00.000000Z' WHERE capture_id=?", (first["capture_id"],))
        elif corruption == "observation":
            connection.execute("UPDATE observations SET observation='{}' WHERE capture_id=?", (first["capture_id"],))
        elif corruption == "missing_observation":
            connection.execute("DELETE FROM observations WHERE capture_id=? AND timestamp_ms=?", (first["capture_id"], _EVENT + 1000))
        else:
            connection.execute("DELETE FROM observations WHERE capture_id=?", (first["capture_id"],))
    with pytest.raises(ArchiveError) as exc:
        _query(archive)
    assert exc.value.code == "ARCHIVE_INVALID"


@pytest.mark.parametrize("bound", ["_MAX_SUPPORT_CAPTURES", "_MAX_SUPPORT_BYTES", "_MAX_SUPPORT_OBSERVATIONS"])
def test_supporting_lineage_verification_has_work_bounds(monkeypatch, tmp_path, bound):
    archive = _archive(tmp_path)
    _save(archive)
    archive.clock = lambda: _DAY + timedelta(days=1)
    _save(archive, [_oi(12)])
    monkeypatch.setattr(archive_mod, bound, 1)
    with pytest.raises(ArchiveError) as exc:
        _query(archive)
    assert exc.value.code == "ARCHIVE_QUERY_TOO_LARGE"


def test_missing_entire_only_capture_index_is_invalid_not_no_data(tmp_path):
    archive = _archive(tmp_path)
    _save(archive)
    with sqlite3.connect(archive.path) as connection:
        connection.execute("DROP TRIGGER immutable_observations_delete")
        connection.execute("DELETE FROM observations")
    with pytest.raises(ArchiveError) as exc:
        _query(archive)
    assert exc.value.code == "ARCHIVE_INVALID"


@pytest.mark.parametrize("cutoff", [None, "2024-01-01", "nonsense", 123, "2024-01-01T00:00:00"])
def test_archive_mode_invalid_cutoff_never_contacts_provider(monkeypatch, cutoff):
    monkeypatch.setattr(tool_mod, "_fetch_history", lambda *_: pytest.fail("No provider request permitted"))
    result = json.loads(tool_mod.CryptoDerivativesTool().execute(symbol=_SYMBOL, mode="archive", as_of=cutoff))
    assert result["error_code"] == "INVALID_ARGUMENT"


@pytest.mark.parametrize("kwargs", [{"mode": "capture", "as_of": "2024-01-01T00:00:00Z"},
                                    {"mode": "live", "as_of": "2024-01-01T00:00:00Z"},
                                    {"mode": "invalid"}, {"mode": []}])
def test_invalid_mode_arguments_reject_before_network(monkeypatch, kwargs):
    monkeypatch.setattr(tool_mod, "_fetch_history", lambda *_: pytest.fail("No provider request permitted"))
    assert json.loads(tool_mod.CryptoDerivativesTool().execute(symbol=_SYMBOL, **kwargs))["error_code"] == "INVALID_ARGUMENT"


@pytest.mark.parametrize("entry", [None, {"path": "relative.sqlite"}, {"path": ""}, {"path": 42}, {"path": "x", "extra": 1}])
def test_configured_path_is_administrator_only(monkeypatch, entry):
    monkeypatch.setattr(archive_mod.local_loader, "_load_config", lambda: {"crypto_derivatives_archive": entry})
    monkeypatch.setattr(tool_mod, "_fetch_history", lambda *_: pytest.fail("No provider request permitted"))
    result = json.loads(tool_mod.CryptoDerivativesTool().execute(symbol=_SYMBOL, mode="capture"))
    assert result["error_code"] == "ARCHIVE_NOT_CONFIGURED"


def test_tool_capture_and_offline_archive_use_same_records(monkeypatch, tmp_path):
    archive = DerivativesArchive(tmp_path / "captures.sqlite")
    monkeypatch.setattr(archive_mod.local_loader, "_load_config", lambda: {"crypto_derivatives_archive": {"path": str(archive.path)}})
    raw = [_oi(timestamp_ms=_EVENT + i * 3_600_000) for i in range(20)]
    monkeypatch.setattr(tool_mod, "_fetch_history", lambda *_: (_MARKET, raw))
    captured = json.loads(tool_mod.CryptoDerivativesTool().execute(symbol=_SYMBOL, mode="capture"))
    assert captured["ok"] is True
    assert len(archive.get_capture(captured["archive"]["capture_id"])["observations"]) == 20
    monkeypatch.setattr(tool_mod, "_fetch_history", lambda *_: pytest.fail("Archive must stay offline"))
    replayed = json.loads(tool_mod.CryptoDerivativesTool().execute(symbol=_SYMBOL, mode="archive", as_of=iso(datetime.now(timezone.utc))))
    assert replayed["ok"] is True
    assert replayed["summary"] == captured["summary"]
    assert replayed["coverage"]["unique_records"] == 20
    assert len(replayed["observations"]) == 10
    assert replayed["source"] == "local_crypto_derivatives_archive"
    assert replayed["provenance"]["historical_available_at"] is None
    assert "local recording time" in replayed["provenance"]["historical_availability"]
    assert replayed["provenance"]["normalized_observations_sha256"] == captured["provenance"]["normalized_observations_sha256"]
    assert len(json.dumps(replayed)) < tool_mod.TOOL_RESULT_LIMIT


def test_tool_archive_summary_excludes_older_limit_rows(monkeypatch, tmp_path):
    archive = _archive(tmp_path)
    _save(archive, [_funding("Regular", i / 1000, _EVENT + i * 1000) for i in range(1, 6)], metric="funding")
    monkeypatch.setattr(tool_mod, "configured_archive", lambda: archive)
    monkeypatch.setattr(tool_mod, "_fetch_history", lambda *_: pytest.fail("Archive must stay offline"))
    result = json.loads(tool_mod.CryptoDerivativesTool().execute(
        symbol=_SYMBOL, metric="funding", mode="archive", as_of=iso(_DAY), limit=2))
    assert result["ok"] is True
    assert result["summary"]["realized_events"] == 2
    assert result["summary"]["rate_sum"] == pytest.approx(0.009)
    assert result["coverage"]["older_observations_omitted"] is True
    assert result["coverage"]["unique_records"] == 2


def test_tool_conflict_has_no_summary_or_inferred_funding_cash(monkeypatch, tmp_path):
    archive = _archive(tmp_path)
    _save(archive, [_funding("Regular")], metric="funding")
    _save(archive, [_funding("Regular", -0.002)], metric="funding")
    monkeypatch.setattr(tool_mod, "configured_archive", lambda: archive)
    result = json.loads(tool_mod.CryptoDerivativesTool().execute(
        symbol=_SYMBOL, metric="funding", mode="archive", as_of=iso(_DAY)))
    assert result["error_code"] == "ARCHIVE_CONFLICT"
    assert "summary" not in result


def test_capture_failure_is_atomic_across_full_observation_batch(tmp_path):
    archive = _archive(tmp_path)
    _save(archive)
    archive.clock = lambda: _DAY + timedelta(days=1)
    with sqlite3.connect(archive.path) as connection:
        connection.execute(f"CREATE TRIGGER fail_second_observation BEFORE INSERT ON observations "
                           f"WHEN NEW.timestamp_ms={_EVENT + 1000} BEGIN SELECT RAISE(ABORT, 'synthetic disk failure'); END;")
    with pytest.raises(sqlite3.IntegrityError, match="synthetic disk failure"):
        _save(archive, [_oi(12), _oi(13, _EVENT + 1000)])
    with sqlite3.connect(archive.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM captures").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 1
    assert _query(archive)["observations"][0]["amount_base"] == 10


def test_archive_reopen_and_read_leave_database_bytes_unchanged(tmp_path):
    archive = _archive(tmp_path)
    receipt = _save(archive)
    original = archive.path.read_bytes()
    reopened = DerivativesArchive(archive.path)
    assert reopened.get_capture(receipt["capture_id"])["symbol"] == _SYMBOL
    assert _query(reopened)["observations"][0]["amount_base"] == 10
    assert archive.path.read_bytes() == original


def test_capture_output_overflow_preflight_has_no_write(monkeypatch, tmp_path):
    archive = DerivativesArchive(tmp_path / "captures.sqlite")
    monkeypatch.setattr(tool_mod, "configured_archive", lambda: archive)
    monkeypatch.setattr(tool_mod, "_fetch_history", lambda *_: (_MARKET, [_oi()]))
    monkeypatch.setattr(tool_mod, "TOOL_RESULT_LIMIT", 2500)
    result = json.loads(tool_mod.CryptoDerivativesTool().execute(symbol=_SYMBOL, mode="capture"))
    assert result["error_code"] == "RESULT_TOO_LARGE"
    assert not archive.path.exists()


@pytest.mark.parametrize("failure", [ValueError("Circular reference detected"), RecursionError("nested provider payload")])
def test_nonserializable_recursive_provider_extra_is_safe_and_not_saved(monkeypatch, tmp_path, failure):
    archive = DerivativesArchive(tmp_path / "captures.sqlite")
    raw = [_oi()]

    def failed_serialization(_):
        # The repo raises Python's process recursion limit during imports, so
        # inject this boundary failure independently of that global setting.
        raise failure

    monkeypatch.setattr(archive_mod, "canonical", failed_serialization)
    monkeypatch.setattr(tool_mod, "configured_archive", lambda: archive)
    monkeypatch.setattr(tool_mod, "_fetch_history", lambda *_: (_MARKET, raw))
    result = json.loads(tool_mod.CryptoDerivativesTool().execute(symbol=_SYMBOL, mode="capture"))
    assert result["error_code"] == "ARCHIVE_UNAVAILABLE"
    assert not archive.path.exists()


def test_live_mode_never_reads_config_or_writes(monkeypatch):
    monkeypatch.setattr(tool_mod, "configured_archive", lambda: pytest.fail("Live is read-only and independent of archive"))
    monkeypatch.setattr(tool_mod, "_fetch_history", lambda *_: (_MARKET, [_oi()]))
    result = json.loads(tool_mod.CryptoDerivativesTool().execute(symbol=_SYMBOL))
    assert result["ok"] is True
    assert "archive" not in result


def test_archive_errors_do_not_expose_local_paths(monkeypatch, tmp_path):
    archive = DerivativesArchive(tmp_path / "private-name" / "missing.sqlite")
    monkeypatch.setattr(tool_mod, "configured_archive", lambda: archive)
    result = tool_mod.CryptoDerivativesTool().execute(symbol=_SYMBOL, mode="archive", as_of=iso(_DAY))
    assert json.loads(result)["error_code"] == "ARCHIVE_UNAVAILABLE"
    assert str(tmp_path) not in result
