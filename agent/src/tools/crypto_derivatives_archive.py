"""Append-only local captures of parsed public CCXT derivative observations.

Availability here means observed by this installation, never the exchange's
historical publication time. SQLite is used only at an administrator-configured
path; opening an archive for research never creates or migrates it.
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

import yaml

from backtest.loaders import local_loader

NORMALIZATION_VERSION = "binance-usdm-derivatives-v1"
_MAX_CAPTURE_BYTES = 1_000_000
_MAX_SUPPORT_CAPTURES = 512
_MAX_SUPPORT_BYTES = 20_000_000
_MAX_SUPPORT_OBSERVATIONS = 20_000
_APPLICATION_ID = 0x56435259
_SCHEMA = """
CREATE TABLE IF NOT EXISTS captures (
    capture_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, metric TEXT NOT NULL,
    period TEXT NOT NULL, retrieved_at TEXT NOT NULL, recorded_at TEXT NOT NULL,
    manifest TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS capture_scope ON captures(symbol, metric, period, recorded_at);
CREATE TABLE IF NOT EXISTS observations (
    capture_id TEXT NOT NULL REFERENCES captures(capture_id),
    timestamp_ms INTEGER NOT NULL, rate_type TEXT NOT NULL, observation_sha256 TEXT NOT NULL,
    observation TEXT NOT NULL, PRIMARY KEY(capture_id, timestamp_ms, rate_type)
);
CREATE INDEX IF NOT EXISTS observation_event ON observations(timestamp_ms, rate_type);
CREATE TRIGGER IF NOT EXISTS immutable_captures_update BEFORE UPDATE ON captures
BEGIN SELECT RAISE(ABORT, 'captures are append-only'); END;
CREATE TRIGGER IF NOT EXISTS immutable_captures_delete BEFORE DELETE ON captures
BEGIN SELECT RAISE(ABORT, 'captures are append-only'); END;
CREATE TRIGGER IF NOT EXISTS immutable_observations_update BEFORE UPDATE ON observations
BEGIN SELECT RAISE(ABORT, 'observations are append-only'); END;
CREATE TRIGGER IF NOT EXISTS immutable_observations_delete BEFORE DELETE ON observations
BEGIN SELECT RAISE(ABORT, 'observations are append-only'); END;
PRAGMA user_version=1;
PRAGMA application_id=1447252569;
"""


class ArchiveError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def timestamp(value: object) -> datetime:
    if not isinstance(value, str) or len(value) > 64:
        raise ArchiveError("INVALID_ARGUMENT", "as_of must be an ISO timestamp with timezone")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.utcoffset() is None:
            raise ValueError
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        raise ArchiveError("INVALID_ARGUMENT", "as_of must be an ISO timestamp with timezone") from None


def iso(value: datetime) -> str:
    # Fixed precision and timezone keep SQLite text ordering chronological.
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def configured_archive() -> "DerivativesArchive":
    try:
        config = local_loader._load_config() or {}
    except (OSError, UnicodeError, yaml.YAMLError):
        raise ArchiveError("ARCHIVE_NOT_CONFIGURED", "Cannot read Data Bridge archive configuration") from None
    entry = config.get("crypto_derivatives_archive") if isinstance(config, dict) else None
    if not isinstance(entry, dict) or set(entry) != {"path"}:
        raise ArchiveError("ARCHIVE_NOT_CONFIGURED", "Configure crypto_derivatives_archive.path in Data Bridge")
    raw = entry["path"]
    if not isinstance(raw, str) or not raw.strip() or len(raw) > 4096:
        raise ArchiveError("ARCHIVE_NOT_CONFIGURED", "Archive path must be an administrator-configured absolute path")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ArchiveError("ARCHIVE_NOT_CONFIGURED", "Archive path must be an administrator-configured absolute path")
    return DerivativesArchive(path)


class DerivativesArchive:
    def __init__(self, path: Path, *, clock: Callable[[], datetime] | None = None):
        self.path = Path(path)
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _open(self, *, write: bool = False) -> sqlite3.Connection:
        if write:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self.path, timeout=5)
        else:
            connection = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        if not write and (connection.execute("PRAGMA user_version").fetchone()[0] != 1
                          or connection.execute("PRAGMA application_id").fetchone()[0] != _APPLICATION_ID):
            connection.close()
            raise ArchiveError("ARCHIVE_INVALID", "Unsupported derivative archive schema")
        return connection

    def append(self, *, symbol: str, metric: str, period: str | None, market: dict,
               raw_rows: list, observations: list[dict], retrieved_at: str) -> dict:
        """Persist one bounded fetch transaction, preserving every normalized row."""
        # Reuse the exact ingestion contract instead of accepting arbitrary rows.
        from src.tools.crypto_derivatives_tool import _observations, _validate_market

        retrieved = timestamp(retrieved_at)
        if re.fullmatch(r"[A-Z0-9]{1,30}-USDT-PERP", symbol) is None:
            raise ArchiveError("ARCHIVE_INVALID", "Invalid archive instrument")
        ccxt_symbol = symbol.removesuffix("-USDT-PERP") + "/USDT:USDT"
        _validate_market(market, ccxt_symbol)
        from src.tools.crypto_derivatives_tool import _PERIODS
        if (metric not in {"open_interest", "funding"} or (metric == "funding" and period is not None)
                or (metric == "open_interest" and period not in _PERIODS)):
            raise ArchiveError("ARCHIVE_INVALID", "Invalid archive metric or period")
        if not isinstance(raw_rows, list) or not 1 <= len(raw_rows) <= 100:
            raise ArchiveError("ARCHIVE_INVALID", "Capture must contain 1..100 provider observations")
        normalized = _observations(raw_rows, ccxt_symbol, metric, 100, int(retrieved.timestamp() * 1000))
        if normalized != observations:
            raise ArchiveError("ARCHIVE_INVALID", "Capture does not match the normalized provider observations")
        payload = {"market": market, "rows": raw_rows}
        manifest = {
            "schema_version": 1, "normalization_version": NORMALIZATION_VERSION,
            "symbol": symbol, "metric": metric, "period": period,
            "retrieved_at": iso(retrieved),
            "ccxt_payload": payload, "ccxt_payload_sha256": digest(payload),
            "observations": observations, "normalized_observations_sha256": digest(observations),
        }
        if len(canonical(manifest).encode("utf-8")) + 100 > _MAX_CAPTURE_BYTES:
            raise ArchiveError("ARCHIVE_INVALID", "Capture exceeds the bounded archive payload size")
        with closing(self._open(write=True)) as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            application = connection.execute("PRAGMA application_id").fetchone()[0]
            populated = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' LIMIT 1").fetchone()
            if (version not in (0, 1) or (populated and application != _APPLICATION_ID)
                    or (version == 1 and application != _APPLICATION_ID)):
                raise ArchiveError("ARCHIVE_INVALID", "Unsupported derivative archive schema")
            connection.executescript(_SCHEMA)
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                # Assign the recording clock while holding the writer lock.
                # A backward clock must never insert a newly learned revision
                # into an earlier historical cutoff.
                recorded = self.clock().astimezone(timezone.utc)
                newest = connection.execute("SELECT MAX(recorded_at) FROM captures").fetchone()[0]
                if newest is not None and iso(recorded) < newest:
                    raise ArchiveError("ARCHIVE_CLOCK_REGRESSION", "Local recording clock moved backward; capture was not appended")
                if retrieved > recorded:
                    raise ArchiveError("ARCHIVE_INVALID", "Retrieval time cannot follow local archive recording time")
                manifest["recorded_at"] = iso(recorded)
                encoded = canonical(manifest)
                capture_id = digest(manifest)
                connection.execute("INSERT OR IGNORE INTO captures VALUES (?, ?, ?, ?, ?, ?, ?)",
                                   (capture_id, symbol, metric, period or "", iso(retrieved), iso(recorded), encoded))
                connection.executemany("INSERT OR IGNORE INTO observations VALUES (?, ?, ?, ?, ?)", [
                    (capture_id, row["timestamp_ms"], row.get("rate_type") or "", digest(row), canonical(row))
                    for row in observations
                ])
        return {"capture_id": capture_id, "recorded_at": iso(recorded),
                "normalization_version": NORMALIZATION_VERSION,
                "ccxt_payload_sha256": manifest["ccxt_payload_sha256"],
                "normalized_observations_sha256": manifest["normalized_observations_sha256"]}

    @staticmethod
    def _verify(capture_id: str, encoded: str) -> dict:
        try:
            if not isinstance(encoded, str) or len(encoded.encode("utf-8")) > _MAX_CAPTURE_BYTES:
                raise ValueError
            manifest = json.loads(encoded)
            fields = {"schema_version", "normalization_version", "symbol", "metric", "period", "retrieved_at",
                      "recorded_at", "ccxt_payload", "ccxt_payload_sha256", "observations", "normalized_observations_sha256"}
            if (not isinstance(manifest, dict) or set(manifest) != fields or digest(manifest) != capture_id
                    or type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1
                    or manifest["normalization_version"] != NORMALIZATION_VERSION
                    or digest(manifest["ccxt_payload"]) != manifest["ccxt_payload_sha256"]
                    or digest(manifest["observations"]) != manifest["normalized_observations_sha256"]):
                raise ValueError
            from src.tools.crypto_derivatives_tool import _PERIODS, _observations, _validate_market

            if (not isinstance(manifest["symbol"], str) or re.fullmatch(r"[A-Z0-9]{1,30}-USDT-PERP", manifest["symbol"]) is None
                    or manifest["metric"] not in ("open_interest", "funding")
                    or (manifest["metric"] == "open_interest" and manifest["period"] not in _PERIODS)
                    or (manifest["metric"] == "funding" and manifest["period"] is not None)
                    or not isinstance(manifest["ccxt_payload"], dict) or set(manifest["ccxt_payload"]) != {"market", "rows"}):
                raise ValueError
            retrieved, recorded = timestamp(manifest["retrieved_at"]), timestamp(manifest["recorded_at"])
            if retrieved > recorded or iso(retrieved) != manifest["retrieved_at"] or iso(recorded) != manifest["recorded_at"]:
                raise ValueError
            ccxt_symbol = manifest["symbol"].removesuffix("-USDT-PERP") + "/USDT:USDT"
            _validate_market(manifest["ccxt_payload"]["market"], ccxt_symbol)
            normalized = _observations(manifest["ccxt_payload"]["rows"], ccxt_symbol, manifest["metric"], 100,
                                       int(retrieved.timestamp() * 1000))
            if not normalized or normalized != manifest["observations"]:
                raise ValueError
            return manifest
        except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
            raise ArchiveError("ARCHIVE_INVALID", "Archive capture checksum or manifest is invalid") from None

    def get_capture(self, capture_id: str) -> dict:
        """Resolve exact captured parsed payload and its transform revision."""
        if not isinstance(capture_id, str) or re.fullmatch(r"[0-9a-f]{64}", capture_id) is None:
            raise ArchiveError("INVALID_ARGUMENT", "capture_id must contain 64 lowercase hex characters")
        with closing(self._open()) as connection:
            row = connection.execute("SELECT manifest FROM captures WHERE capture_id=?", (capture_id,)).fetchone()
            if row is None:
                raise ArchiveError("NO_DATA", "No matching derivative capture")
            return self._verify(capture_id, row["manifest"])

    def query(self, *, symbol: str, metric: str, period: str | None, as_of: str, limit: int) -> dict:
        from src.tools.crypto_derivatives_tool import _PERIODS

        if (not isinstance(symbol, str) or re.fullmatch(r"[A-Z0-9]{1,30}-USDT-PERP", symbol) is None
                or metric not in ("open_interest", "funding")
                or (metric == "open_interest" and period not in _PERIODS)
                or (metric == "funding" and period is not None)
                or type(limit) is not int or not 1 <= limit <= 100):
            raise ArchiveError("INVALID_ARGUMENT", "Archive query scope or limit is invalid")
        cutoff = timestamp(as_of)
        params = (symbol, metric, period or "", iso(cutoff), int(cutoff.timestamp() * 1000))
        with closing(self._open()) as connection:
            # A read transaction pins every statement to the same SQLite snapshot.
            connection.execute("BEGIN")
            captures: dict[str, dict] = {}
            support = connection.execute("""
                SELECT c.capture_id, c.symbol, c.metric, c.period, c.recorded_at, c.retrieved_at,
                  LENGTH(CAST(c.manifest AS BLOB)) AS payload_bytes,
                  (SELECT COUNT(*) FROM observations full_o WHERE full_o.capture_id=c.capture_id) AS observation_count
                FROM captures c WHERE c.symbol=? AND c.metric=? AND c.period=? AND c.recorded_at<=? LIMIT ?
            """, (*params[:4], _MAX_SUPPORT_CAPTURES + 1)).fetchall()
            if (len(support) > _MAX_SUPPORT_CAPTURES
                    or sum(item["payload_bytes"] for item in support) > _MAX_SUPPORT_BYTES
                    or sum(item["observation_count"] for item in support) > _MAX_SUPPORT_OBSERVATIONS):
                raise ArchiveError("ARCHIVE_QUERY_TOO_LARGE", "Visible revision history exceeds verification bounds; use an earlier cutoff or an operator-managed archive partition")
            # Lineage counters are evidence too. Verify every visible capture,
            # including a capture whose entire observation index is missing.
            for item in support:
                source = connection.execute("SELECT manifest FROM captures WHERE capture_id=?", (item["capture_id"],)).fetchone()
                manifest = self._verify(item["capture_id"], source["manifest"])
                if (manifest["symbol"], manifest["metric"], manifest["period"] or "", manifest["recorded_at"], manifest["retrieved_at"]) != (
                        item["symbol"], item["metric"], item["period"], item["recorded_at"], item["retrieved_at"]):
                    raise ArchiveError("ARCHIVE_INVALID", "Supporting capture scope does not match its manifest")
                stored = connection.execute("SELECT * FROM observations WHERE capture_id=?", (item["capture_id"],)).fetchall()
                expected = {(row["timestamp_ms"], row.get("rate_type") or ""): row for row in manifest["observations"]}
                if len(stored) != len(expected) or len(expected) != len(manifest["observations"]):
                    raise ArchiveError("ARCHIVE_INVALID", "Supporting capture observation set is incomplete or duplicated")
                for stored_row in stored:
                    try:
                        normalized = json.loads(stored_row["observation"])
                        if (expected.get((stored_row["timestamp_ms"], stored_row["rate_type"])) != normalized
                                or digest(normalized) != stored_row["observation_sha256"]):
                            raise ValueError
                    except (ValueError, TypeError, KeyError, RecursionError):
                        raise ArchiveError("ARCHIVE_INVALID", "Supporting observation checksum is invalid") from None
                captures[item["capture_id"]] = manifest
            selected = connection.execute("""
                WITH ranked AS (
                  SELECT o.*, c.recorded_at, c.retrieved_at,
                    ROW_NUMBER() OVER (PARTITION BY o.timestamp_ms, o.rate_type
                      ORDER BY c.recorded_at DESC, o.capture_id DESC) AS rank
                  FROM observations o JOIN captures c USING(capture_id)
                  WHERE c.symbol=? AND c.metric=? AND c.period=? AND c.recorded_at<=? AND o.timestamp_ms<=?
                ) SELECT * FROM ranked WHERE rank=1 ORDER BY timestamp_ms DESC, rate_type DESC LIMIT ?
            """, (*params, limit + 1)).fetchall()
            limited = len(selected) > limit
            selected = selected[:limit]
            rows = []
            for chosen in reversed(selected):
                capture_id = chosen["capture_id"]
                manifest = captures[capture_id]
                if (manifest["symbol"], manifest["metric"], manifest["period"] or "", manifest["recorded_at"], manifest["retrieved_at"]) != (
                        symbol, metric, period or "", chosen["recorded_at"], chosen["retrieved_at"]):
                    raise ArchiveError("ARCHIVE_INVALID", "Archive scope does not match capture manifest")
                row = json.loads(chosen["observation"])
                if (digest(row) != chosen["observation_sha256"] or row not in manifest["observations"]
                        or row["timestamp_ms"] != chosen["timestamp_ms"]
                        or (row.get("rate_type") or "") != chosen["rate_type"]):
                    raise ArchiveError("ARCHIVE_INVALID", "Archived observation checksum is invalid")
                stats = connection.execute("""
                    SELECT MIN(c.recorded_at), COUNT(DISTINCT o.observation_sha256),
                      COUNT(DISTINCT CASE WHEN c.recorded_at=? THEN o.observation_sha256 END)
                    FROM observations o JOIN captures c USING(capture_id)
                    WHERE c.symbol=? AND c.metric=? AND c.period=? AND c.recorded_at<=?
                      AND o.timestamp_ms=? AND o.rate_type=?
                """, (chosen["recorded_at"], *params[:4], chosen["timestamp_ms"], chosen["rate_type"])).fetchone()
                if stats[2] > 1:
                    raise ArchiveError("ARCHIVE_CONFLICT", "Conflicting revisions share the latest local recording time; no aggregate was inferred")
                row["archive_evidence"] = {
                    "capture_id": capture_id, "observation_sha256": chosen["observation_sha256"],
                    "first_observed_at": stats[0], "selected_recorded_at": chosen["recorded_at"],
                    "distinct_revisions": stats[1],
                }
                rows.append(row)
            snapshot_sha = digest([{"observation": {key: value for key, value in row.items() if key != "archive_evidence"},
                                    "capture_id": row["archive_evidence"]["capture_id"]} for row in rows])
            return {"observations": rows, "as_of": iso(cutoff), "limited": limited,
                    "snapshot_sha256": snapshot_sha,
                    "revised_observations": sum(row["archive_evidence"]["distinct_revisions"] > 1 for row in rows),
                    "selected_capture_count": len({row["capture_id"] for row in selected}),
                    "verified_supporting_capture_count": len(captures)}
