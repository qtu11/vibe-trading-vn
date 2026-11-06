"""Append-only local research snapshots; reads never initialize storage.

Integrity hashes detect modification, not a hostile database operator who can
rewrite both hashes and data. Operator review never verifies external evidence.
"""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Callable
import uuid

from src.config.paths import get_runtime_root

_APPLICATION_ID = 0x56524152
_MAX_BYTES = 128_000
_SCHEMA = """
CREATE TABLE revisions (
    revision_id TEXT PRIMARY KEY, kind TEXT NOT NULL, created_at TEXT NOT NULL,
    parent_revision_id TEXT REFERENCES revisions(revision_id),
    manifest TEXT NOT NULL, manifest_sha256 TEXT NOT NULL
);
CREATE INDEX revisions_scope ON revisions(kind, created_at);
CREATE TABLE reviews (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT, review_id TEXT NOT NULL UNIQUE,
    revision_id TEXT NOT NULL REFERENCES revisions(revision_id),
    event TEXT NOT NULL, event_sha256 TEXT NOT NULL
);
CREATE INDEX reviews_revision ON reviews(revision_id, sequence);
CREATE TRIGGER immutable_revision_update BEFORE UPDATE ON revisions
BEGIN SELECT RAISE(ABORT, 'research revisions are append-only'); END;
CREATE TRIGGER immutable_revision_delete BEFORE DELETE ON revisions
BEGIN SELECT RAISE(ABORT, 'research revisions are append-only'); END;
CREATE TRIGGER immutable_review_update BEFORE UPDATE ON reviews
BEGIN SELECT RAISE(ABORT, 'research reviews are append-only'); END;
CREATE TRIGGER immutable_review_delete BEFORE DELETE ON reviews
BEGIN SELECT RAISE(ABORT, 'research reviews are append-only'); END;
PRAGMA user_version=1;
PRAGMA application_id=1448231250;
"""

_ATTEMPT_SCHEMA = """
CREATE TABLE attempts (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id TEXT NOT NULL UNIQUE, idempotency_key TEXT UNIQUE,
    kind TEXT NOT NULL, parent_revision_id TEXT REFERENCES revisions(revision_id),
    caller_input_sha256 TEXT NOT NULL, created_at TEXT NOT NULL,
    manifest TEXT NOT NULL, manifest_sha256 TEXT NOT NULL
);
CREATE INDEX attempts_parent ON attempts(parent_revision_id, sequence);
CREATE TABLE attempt_outcomes (
    attempt_id TEXT PRIMARY KEY REFERENCES attempts(attempt_id),
    status TEXT NOT NULL CHECK(status IN ('succeeded', 'failed')),
    revision_id TEXT UNIQUE REFERENCES revisions(revision_id),
    finished_at TEXT NOT NULL, event TEXT NOT NULL, event_sha256 TEXT NOT NULL,
    CHECK((status='succeeded' AND revision_id IS NOT NULL) OR (status='failed' AND revision_id IS NULL))
);
CREATE TRIGGER immutable_attempt_update BEFORE UPDATE ON attempts
BEGIN SELECT RAISE(ABORT, 'research attempts are append-only'); END;
CREATE TRIGGER immutable_attempt_delete BEFORE DELETE ON attempts
BEGIN SELECT RAISE(ABORT, 'research attempts are append-only'); END;
CREATE TRIGGER immutable_outcome_update BEFORE UPDATE ON attempt_outcomes
BEGIN SELECT RAISE(ABORT, 'research outcomes are append-only'); END;
CREATE TRIGGER immutable_outcome_delete BEFORE DELETE ON attempt_outcomes
BEGIN SELECT RAISE(ABORT, 'research outcomes are append-only'); END;
PRAGMA user_version=2;
"""


class ArtifactError(ValueError):
    """Safe domain error suitable for authenticated API translation."""

    def __init__(self, code: str, message: str, *, receipt: dict | None = None):
        super().__init__(message)
        self.code = code
        self.receipt = receipt


def default_artifact_path() -> Path:
    return get_runtime_root() / "research" / "artifacts.sqlite"


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def utc_timestamp(value: datetime) -> str:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ArtifactError("INVALID_ARGUMENT", "Recording clock must include a timezone")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _revision_id(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"rr_[0-9a-f]{32}", value) is None:
        raise ArtifactError("INVALID_ARGUMENT", "Invalid research revision ID")
    return value


def _bounded_integer(value: object, minimum: int, maximum: int, name: str) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ArtifactError("INVALID_ARGUMENT", f"{name} is outside the supported bounds")
    return value


def validate_idempotency_key(value: object) -> str | None:
    if value is not None and (not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9_-]{8,128}", value) is None):
        raise ArtifactError("INVALID_ARGUMENT", "Idempotency key must contain 8..128 ASCII letters, digits, underscores or hyphens")
    return value


class ResearchArtifactStore:
    """Small stdlib SQLite store following the existing archive pattern."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path is not None else default_artifact_path()

    def _open(self, *, write: bool = False) -> sqlite3.Connection:
        if write:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self.path, timeout=5)
        else:
            connection = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @staticmethod
    def _schema(connection: sqlite3.Connection, *, initialize: bool = False, upgrade: bool = False) -> int:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        application = connection.execute("PRAGMA application_id").fetchone()[0]
        if version in {1, 2} and application == _APPLICATION_ID:
            if version == 1 and upgrade:
                for statement in re.split(r";\s*(?=CREATE |PRAGMA |$)", _ATTEMPT_SCHEMA.strip()):
                    if statement.strip():
                        connection.execute(statement)
                return 2
            return version
        populated = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' LIMIT 1").fetchone()
        if initialize and version == 0 and application == 0 and populated is None:
            # executescript would commit the caller's BEGIN IMMEDIATE. Keep
            # creation and the first append in the same writer transaction.
            for statement in re.split(r";\s*(?=CREATE |PRAGMA |$)", _SCHEMA.strip()):
                if statement.strip():
                    connection.execute(statement)
            return ResearchArtifactStore._schema(connection, upgrade=upgrade)
        raise ArtifactError("ARTIFACT_STORE_INVALID", "Unsupported research artifact database")

    @staticmethod
    def _verified(row: sqlite3.Row) -> dict:
        try:
            encoded = row["manifest"]
            if len(encoded.encode("utf-8")) > _MAX_BYTES:
                raise ValueError
            value = json.loads(encoded)
            if (digest(value) != row["manifest_sha256"] or value["revision_id"] != row["revision_id"]
                    or value["kind"] != row["kind"] or value["created_at"] != row["created_at"]
                    or value["parent_revision_id"] != row["parent_revision_id"]
                    or digest(value["request"]) != value["hashes"]["request_sha256"]
                    or digest(value["result"]) != value["hashes"]["result_sha256"]
                    or digest(value["producer"]) != value["hashes"]["producer_sha256"]
                    or value["result"].get("ok") is not True
                    or value["verification_status"] != "user_supplied_unverified"):
                raise ValueError
            return value
        except (KeyError, TypeError, ValueError, RecursionError):
            raise ArtifactError("ARTIFACT_INTEGRITY_ERROR", "Research revision failed its stored integrity checks") from None

    @staticmethod
    def _reviews(connection: sqlite3.Connection, revision_id: str) -> list[dict]:
        rows = connection.execute("SELECT * FROM reviews WHERE revision_id=? ORDER BY sequence LIMIT 1001", (revision_id,)).fetchall()
        if len(rows) > 1000:
            raise ArtifactError("ARTIFACT_QUERY_TOO_LARGE", "Revision review history exceeds the supported bound")
        result = []
        for row in rows:
            try:
                if len(row["event"].encode("utf-8")) > 16_000:
                    raise ValueError
                event = json.loads(row["event"])
                if (digest(event) != row["event_sha256"] or event["review_id"] != row["review_id"]
                        or event["revision_id"] != revision_id
                        or event["decision"] not in {"acknowledged", "changes_requested"}
                        or event["verification_status"] != "user_supplied_unverified"):
                    raise ValueError
                result.append(event)
            except (KeyError, TypeError, ValueError, RecursionError):
                raise ArtifactError("ARTIFACT_INTEGRITY_ERROR", "Review history failed its stored integrity checks") from None
        return result

    @classmethod
    def _get(cls, connection: sqlite3.Connection, revision_id: str) -> dict:
        row = connection.execute("SELECT * FROM revisions WHERE revision_id=?", (revision_id,)).fetchone()
        if row is None:
            raise ArtifactError("REVISION_NOT_FOUND", "Research revision was not found")
        value = cls._verified(row)
        history = cls._reviews(connection, revision_id)
        return dict(value, review_state=history[-1]["decision"] if history else "pending_review", review_history=history)

    @classmethod
    def _append(cls, connection: sqlite3.Connection, manifest: dict, *, clock: Callable[[], datetime] | None = None) -> dict:
        encoded = canonical(manifest)
        if len(encoded.encode("utf-8")) > _MAX_BYTES:
            raise ArtifactError("ARTIFACT_TOO_LARGE", "Research revision exceeds the 128000-byte storage bound")
        _revision_id(manifest["revision_id"])
        parent = manifest["parent_revision_id"]
        if parent is not None:
            _revision_id(parent)
        if clock is not None:
            manifest = dict(manifest, created_at=utc_timestamp(clock()))
            encoded = canonical(manifest)
        if parent is not None:
            prior = cls._get(connection, parent)
            if prior["kind"] != manifest["kind"] or prior["scope"] != manifest["scope"]:
                raise ArtifactError("REVISION_SCOPE_MISMATCH", "Parent revision has a different research scope")
        latest = connection.execute("SELECT MAX(created_at) FROM revisions").fetchone()[0]
        if latest is not None and manifest["created_at"] < latest:
            raise ArtifactError("ARTIFACT_CLOCK_REGRESSION", "Recording clock moved backward; no revision was appended")
        connection.execute("INSERT INTO revisions VALUES (?, ?, ?, ?, ?, ?)",
                           (manifest["revision_id"], manifest["kind"], manifest["created_at"], parent, encoded, digest(manifest)))
        return cls._get(connection, manifest["revision_id"])

    def append(self, manifest: dict, *, clock: Callable[[], datetime] | None = None) -> dict:
        """Low-level append; service save additionally records an attempt."""
        with closing(self._open(write=True)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            self._schema(connection, initialize=True, upgrade=True)
            return self._append(connection, manifest, clock=clock)

    def get_revision(self, revision_id: str) -> dict:
        _revision_id(revision_id)
        if not self.path.exists():
            raise ArtifactError("REVISION_NOT_FOUND", "Research revision was not found")
        with closing(self._open()) as connection, connection:
            connection.execute("BEGIN")
            self._schema(connection)
            return self._get(connection, revision_id)

    def list_revisions(self, *, kind: str | None = None, limit: int = 20, offset: int = 0) -> dict:
        _bounded_integer(limit, 1, 100, "limit")
        _bounded_integer(offset, 0, 100_000, "offset")
        if kind is not None and kind not in {"vietnam", "vietnam_comparables", "vietnam_dcf", "vietnam_reverse_dcf", "crypto_basis"}:
            raise ArtifactError("INVALID_ARGUMENT", "Unsupported research kind")
        if not self.path.exists():
            return {"items": [], "total": 0, "next_offset": None}
        with closing(self._open()) as connection, connection:
            connection.execute("BEGIN")
            self._schema(connection)
            where, args = (" WHERE kind=?", (kind,)) if kind is not None else ("", ())
            total = connection.execute("SELECT COUNT(*) FROM revisions" + where, args).fetchone()[0]
            rows = connection.execute("SELECT * FROM revisions" + where + " ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?",
                                      (*args, limit, offset)).fetchall()
            items = []
            for row in rows:
                value = self._verified(row)
                # Listing does not load every full note of every revision.
                latest = connection.execute("SELECT * FROM reviews WHERE revision_id=? ORDER BY sequence DESC LIMIT 1",
                                            (row["revision_id"],)).fetchone()
                value["review_state"] = "pending_review"
                if latest is not None:
                    try:
                        event = json.loads(latest["event"])
                        if (digest(event) != latest["event_sha256"] or event["review_id"] != latest["review_id"]
                                or event["revision_id"] != row["revision_id"]
                                or event["decision"] not in {"acknowledged", "changes_requested"}
                                or event["verification_status"] != "user_supplied_unverified"):
                            raise ValueError
                        value["review_state"] = event["decision"]
                    except (KeyError, ValueError, TypeError, RecursionError):
                        raise ArtifactError("ARTIFACT_INTEGRITY_ERROR", "Latest review failed its stored integrity checks") from None
                items.append({key: value[key] for key in ("revision_id", "kind", "scope", "created_at", "parent_revision_id",
                                                         "hashes", "content_scope", "verification_status", "review_state")})
            next_offset = offset + len(items)
            return {"items": items, "total": total, "next_offset": next_offset if next_offset < total else None}

    def review_revision(self, revision_id: str, *, decision: str, note: str, reviewer: str,
                        clock: Callable[[], datetime]) -> dict:
        _revision_id(revision_id)
        if decision not in {"acknowledged", "changes_requested"}:
            raise ArtifactError("INVALID_ARGUMENT", "Review decision must be acknowledged or changes_requested")
        if not isinstance(note, str) or not note.strip() or len(note) > 2000:
            raise ArtifactError("INVALID_ARGUMENT", "Review note must contain 1..2000 characters")
        if not isinstance(reviewer, str) or not reviewer.strip() or len(reviewer) > 120:
            raise ArtifactError("INVALID_ARGUMENT", "Reviewer label must contain 1..120 characters")
        if not self.path.exists():
            raise ArtifactError("REVISION_NOT_FOUND", "Research revision was not found")
        with closing(self._open(write=True)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            self._schema(connection, upgrade=True)
            revision = self._get(connection, revision_id)
            if len(revision["review_history"]) >= 1000:
                raise ArtifactError("ARTIFACT_QUERY_TOO_LARGE", "Revision review history exceeds the supported bound")
            recorded = utc_timestamp(clock())
            previous = revision["review_history"][-1]["created_at"] if revision["review_history"] else revision["created_at"]
            if recorded < previous:
                raise ArtifactError("ARTIFACT_CLOCK_REGRESSION", "Recording clock moved backward; no review was appended")
            event = {"review_id": "rv_" + uuid.uuid4().hex, "revision_id": revision_id, "created_at": recorded,
                     "decision": decision, "note": note.strip(), "reviewer": reviewer.strip(),
                     "reviewer_identity": "self_reported_operator_label", "verification_status": "user_supplied_unverified"}
            connection.execute("INSERT INTO reviews(review_id,revision_id,event,event_sha256) VALUES (?,?,?,?)",
                               (event["review_id"], revision_id, canonical(event), digest(event)))
            return {"event": event, "review_state": decision, "verification_status": "user_supplied_unverified"}

    @classmethod
    def _attempt(cls, connection: sqlite3.Connection, row: sqlite3.Row, *, include_request: bool = False) -> dict:
        try:
            if len(row["manifest"].encode("utf-8")) > 80_000:
                raise ValueError
            value = json.loads(row["manifest"])
            if (digest(value) != row["manifest_sha256"]
                    or any(value[key] != row[key] for key in ("attempt_id", "idempotency_key", "kind", "parent_revision_id", "caller_input_sha256", "created_at"))
                    or digest(value["request"]) != value["request_sha256"]):
                raise ValueError
            result = {key: value[key] for key in ("attempt_id", "idempotency_key", "kind", "parent_revision_id", "caller_input_sha256", "request_sha256", "created_at")}
            result.update(status="in_flight_unknown", finished_at=None, revision_id=None, error=None)
            outcome = connection.execute("SELECT * FROM attempt_outcomes WHERE attempt_id=?", (row["attempt_id"],)).fetchone()
            if outcome is not None:
                if len(outcome["event"].encode("utf-8")) > 4000:
                    raise ValueError
                event = json.loads(outcome["event"])
                if (digest(event) != outcome["event_sha256"]
                        or any(event[key] != outcome[key] for key in ("attempt_id", "status", "revision_id", "finished_at"))
                        or event["finished_at"] < value["created_at"]
                        or event["status"] not in {"succeeded", "failed"}
                        or (event["status"] == "succeeded") != (event["revision_id"] is not None)
                        or (event["status"] == "failed") != (event["error"] is not None)):
                    raise ValueError
                if event["status"] == "succeeded":
                    revision = cls._get(connection, event["revision_id"])
                    if (revision["kind"] != value["kind"] or revision["parent_revision_id"] != value["parent_revision_id"]
                            or revision["hashes"]["request_sha256"] != value["request_sha256"]):
                        raise ValueError
                result.update({key: event[key] for key in ("status", "finished_at", "revision_id", "error")})
            if include_request:
                result["request"] = value["request"]
            return result
        except (KeyError, ValueError, TypeError, RecursionError):
            raise ArtifactError("ARTIFACT_INTEGRITY_ERROR", "Research attempt failed its stored integrity checks") from None

    @classmethod
    def _attempt_by_id(cls, connection: sqlite3.Connection, attempt_id: str) -> dict:
        row = connection.execute("SELECT * FROM attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
        if row is None:
            raise ArtifactError("ATTEMPT_NOT_FOUND", "Research attempt was not found")
        return cls._attempt(connection, row)

    @classmethod
    def _existing_key(cls, connection: sqlite3.Connection, key: str | None, caller_hash: str) -> dict | None:
        if key is None:
            return None
        row = connection.execute("SELECT * FROM attempts WHERE idempotency_key=?", (key,)).fetchone()
        if row is None:
            return None
        receipt = cls._attempt(connection, row)
        if receipt["caller_input_sha256"] != caller_hash:
            raise ArtifactError("IDEMPOTENCY_CONFLICT", "Idempotency key is already bound to different research inputs", receipt=receipt)
        return receipt

    def lookup_attempt(self, key: str | None, caller_hash: str) -> dict | None:
        validate_idempotency_key(key)
        if key is None or not self.path.exists():
            return None
        with closing(self._open()) as connection, connection:
            connection.execute("BEGIN")
            if self._schema(connection) == 1:
                return None
            return self._existing_key(connection, key, caller_hash)

    def reserve_attempt(self, *, kind: str, request: dict, scope: dict, caller_hash: str,
                        parent_revision_id: str | None, idempotency_key: str | None,
                        clock: Callable[[], datetime]) -> tuple[dict, bool]:
        """Commit admission before executing; no model/engine holds the DB lock."""
        validate_idempotency_key(idempotency_key)
        if len(canonical(request).encode("utf-8")) > 64_000:
            raise ArtifactError("ARTIFACT_TOO_LARGE", "Normalized research request exceeds 64000 bytes")
        with closing(self._open(write=True)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            self._schema(connection, initialize=True, upgrade=True)
            existing = self._existing_key(connection, idempotency_key, caller_hash)
            if existing is not None:
                return existing, False
            if parent_revision_id is not None:
                parent = self._get(connection, parent_revision_id)
                if parent["kind"] != kind or parent["scope"] != scope:
                    raise ArtifactError("REVISION_SCOPE_MISMATCH", "Parent revision has a different research scope")
            created = utc_timestamp(clock())
            latest = connection.execute("SELECT MAX(moment) FROM (SELECT created_at AS moment FROM revisions UNION ALL SELECT created_at FROM attempts UNION ALL SELECT finished_at FROM attempt_outcomes)").fetchone()[0]
            if latest is not None and created < latest:
                raise ArtifactError("ARTIFACT_CLOCK_REGRESSION", "Recording clock moved backward; no attempt was reserved")
            value = {"schema_version": 1, "attempt_id": "ra_" + uuid.uuid4().hex,
                     "kind": kind, "parent_revision_id": parent_revision_id, "idempotency_key": idempotency_key,
                     "caller_input_sha256": caller_hash, "request": request,
                     "request_sha256": digest(request), "created_at": created}
            connection.execute("INSERT INTO attempts(attempt_id,idempotency_key,kind,parent_revision_id,caller_input_sha256,created_at,manifest,manifest_sha256) VALUES(?,?,?,?,?,?,?,?)",
                               (value["attempt_id"], idempotency_key, kind, parent_revision_id, caller_hash, created, canonical(value), digest(value)))
            return self._attempt_by_id(connection, value["attempt_id"]), True

    @staticmethod
    def _append_outcome(connection: sqlite3.Connection, attempt: dict, *, revision_id: str | None,
                        error: dict | None, clock: Callable[[], datetime]) -> None:
        finished = utc_timestamp(clock())
        earliest = attempt["created_at"]
        if revision_id is not None:
            earliest = max(earliest, connection.execute("SELECT created_at FROM revisions WHERE revision_id=?", (revision_id,)).fetchone()[0])
        if finished < earliest:
            raise ArtifactError("ARTIFACT_CLOCK_REGRESSION", "Recording clock moved backward; attempt completion remains unknown")
        event = {"attempt_id": attempt["attempt_id"], "status": "succeeded" if revision_id is not None else "failed",
                 "revision_id": revision_id, "finished_at": finished, "error": error}
        connection.execute("INSERT INTO attempt_outcomes VALUES(?,?,?,?,?,?)",
                           (event["attempt_id"], event["status"], revision_id, finished, canonical(event), digest(event)))

    def finish_attempt_success(self, attempt_id: str, manifest: dict, *, clock: Callable[[], datetime]) -> dict:
        with closing(self._open(write=True)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            self._schema(connection, upgrade=True)
            attempt = self._attempt_by_id(connection, attempt_id)
            if attempt["status"] != "in_flight_unknown":
                raise ArtifactError("RESEARCH_ATTEMPT_FINALIZED", "Research attempt already has a terminal outcome", receipt=attempt)
            if (attempt["kind"] != manifest["kind"] or attempt["parent_revision_id"] != manifest["parent_revision_id"]
                    or attempt["request_sha256"] != manifest["hashes"]["request_sha256"]):
                raise ArtifactError("ARTIFACT_INTEGRITY_ERROR", "Attempt and revision inputs do not match")
            revision = self._append(connection, manifest, clock=clock)
            if revision["created_at"] < attempt["created_at"]:
                raise ArtifactError("ARTIFACT_CLOCK_REGRESSION", "Recording clock moved backward; revision cannot precede attempt admission")
            self._append_outcome(connection, attempt, revision_id=revision["revision_id"], error=None, clock=clock)
            return revision

    def finish_attempt_failure(self, attempt_id: str, error: dict, *, clock: Callable[[], datetime]) -> dict:
        if (set(error) - {"code", "message", "stage", "exception_type"}
                or not isinstance(error.get("code"), str) or re.fullmatch(r"[A-Z_]{1,80}", error["code"]) is None
                or not isinstance(error.get("message"), str) or not 1 <= len(error["message"]) <= 320
                or error.get("stage") not in {"producer", "engine", "manifest"}
                or ("exception_type" in error and (not isinstance(error["exception_type"], str) or len(error["exception_type"]) > 80))):
            raise ArtifactError("INVALID_ARGUMENT", "Invalid safe attempt failure envelope")
        with closing(self._open(write=True)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            self._schema(connection, upgrade=True)
            attempt = self._attempt_by_id(connection, attempt_id)
            if attempt["status"] != "in_flight_unknown":
                raise ArtifactError("RESEARCH_ATTEMPT_FINALIZED", "Research attempt already has a terminal outcome", receipt=attempt)
            self._append_outcome(connection, attempt, revision_id=None, error=error, clock=clock)
            return self._attempt_by_id(connection, attempt_id)

    def get_attempt(self, attempt_id: str) -> dict:
        if not isinstance(attempt_id, str) or re.fullmatch(r"ra_[0-9a-f]{32}", attempt_id) is None:
            raise ArtifactError("INVALID_ARGUMENT", "Invalid research attempt ID")
        if not self.path.exists():
            raise ArtifactError("ATTEMPT_NOT_FOUND", "Research attempt was not found")
        with closing(self._open()) as connection, connection:
            connection.execute("BEGIN")
            if self._schema(connection) == 1:
                raise ArtifactError("ATTEMPT_NOT_FOUND", "Research attempt was not found")
            return self._attempt_by_id(connection, attempt_id)

    def list_attempts(self, *, kind: str | None = None, parent_revision_id: str | None = None,
                      idempotency_key: str | None = None, limit: int = 20, offset: int = 0) -> dict:
        _bounded_integer(limit, 1, 100, "limit")
        _bounded_integer(offset, 0, 100_000, "offset")
        validate_idempotency_key(idempotency_key)
        if kind is not None and kind not in {"vietnam", "vietnam_comparables", "vietnam_dcf", "vietnam_reverse_dcf", "crypto_basis"}:
            raise ArtifactError("INVALID_ARGUMENT", "Unsupported research kind")
        if parent_revision_id is not None:
            _revision_id(parent_revision_id)
        result = {"items": [], "total": 0, "next_offset": None, "refresh_state": None}
        if not self.path.exists():
            if parent_revision_id is not None:
                raise ArtifactError("REVISION_NOT_FOUND", "Research revision was not found")
            return result
        with closing(self._open()) as connection, connection:
            connection.execute("BEGIN")
            version = self._schema(connection)
            if parent_revision_id is not None:
                self._get(connection, parent_revision_id)
                result["refresh_state"] = {"state": "no_refresh_attempt", "parent_revision_id": parent_revision_id,
                                           "last_attempt": None, "last_good_revision_id": parent_revision_id}
            if version == 1:
                return result
            terms, arguments = [], []
            for column, value in (("kind", kind), ("parent_revision_id", parent_revision_id), ("idempotency_key", idempotency_key)):
                if value is not None:
                    terms.append(column + "=?")
                    arguments.append(value)
            where = " WHERE " + " AND ".join(terms) if terms else ""
            result["total"] = connection.execute("SELECT COUNT(*) FROM attempts" + where, arguments).fetchone()[0]
            rows = connection.execute("SELECT * FROM attempts" + where + " ORDER BY sequence DESC LIMIT ? OFFSET ?", (*arguments, limit, offset)).fetchall()
            result["items"] = [self._attempt(connection, row) for row in rows]
            following = offset + len(rows)
            result["next_offset"] = following if following < result["total"] else None
            if parent_revision_id is not None:
                latest = connection.execute("SELECT * FROM attempts WHERE parent_revision_id=? ORDER BY sequence DESC LIMIT 1", (parent_revision_id,)).fetchone()
                if latest is not None:
                    receipt = self._attempt(connection, latest)
                    success = connection.execute("SELECT a.* FROM attempts a JOIN attempt_outcomes o USING(attempt_id) WHERE a.parent_revision_id=? AND o.status='succeeded' ORDER BY a.sequence DESC LIMIT 1", (parent_revision_id,)).fetchone()
                    good = self._attempt(connection, success)["revision_id"] if success is not None else parent_revision_id
                    result["refresh_state"].update(state={"succeeded": "superseded", "failed": "refresh_failed", "in_flight_unknown": "refresh_in_flight_unknown"}[receipt["status"]],
                                                    last_attempt=receipt, last_good_revision_id=good)
            return result
