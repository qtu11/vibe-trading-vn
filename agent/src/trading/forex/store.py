"""Durable intents and pre-send claims; every method owns a short transaction."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path

from src.config.paths import get_runtime_root
from .errors import ForexError
from .models import Connection, Order, broker_reference, digest, utcnow

ACTIVE = ("submitting", "accepted", "working", "partial", "unknown")
_SCHEMA = """
CREATE TABLE IF NOT EXISTS connections (id TEXT PRIMARY KEY, config TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS intents (
 id TEXT PRIMARY KEY, connection_id TEXT NOT NULL, connector TEXT NOT NULL,
 request_key TEXT NOT NULL, payload_hash TEXT NOT NULL, binding_hash TEXT NOT NULL,
 payload TEXT NOT NULL, binding TEXT NOT NULL DEFAULT '{}', state TEXT NOT NULL, result TEXT NOT NULL DEFAULT '{}',
 created_at TEXT NOT NULL, submitted_at TEXT,
 UNIQUE(connection_id, request_key));
CREATE TABLE IF NOT EXISTS events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, connection_id TEXT NOT NULL,
 intent_id TEXT, kind TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS equity_peaks (connection_id TEXT PRIMARY KEY, equity TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS execution_state ON intents(connector,state);
CREATE TABLE IF NOT EXISTS ai_decisions (
 decision_key TEXT PRIMARY KEY, connection_id TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL);
"""


class Store:
    def __init__(self, path: Path | None = None):
        self.path = path or get_runtime_root() / "forex" / "execution.db"

    @contextmanager
    def db(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA busy_timeout=10000")
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=FULL")
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2, 3):
                raise ForexError("STORE_VERSION", "Forex store has an unsupported schema")
            if version != 3:
                conn.executescript(_SCHEMA)
                conn.execute("BEGIN IMMEDIATE")
                if "binding" not in {row[1] for row in conn.execute("PRAGMA table_info(intents)")}:
                    # Old rows retain an empty snapshot rather than invented provenance.
                    conn.execute("ALTER TABLE intents ADD COLUMN binding TEXT NOT NULL DEFAULT '{}'")
                conn.execute("PRAGMA user_version=3")
                conn.commit()
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def save_connection(self, config: Connection) -> None:
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute(
                "SELECT 1 FROM intents WHERE connection_id=? AND state IN (?,?,?,?,?)", (config.id, *ACTIVE)
            ).fetchone():
                raise ForexError("EXECUTION_PENDING", "Reconcile active executions before editing the connection")
            previous = db.execute("SELECT config FROM connections WHERE id=?", (config.id,)).fetchone()
            if previous and db.execute("SELECT 1 FROM intents WHERE connection_id=? LIMIT 1", (config.id,)).fetchone():
                old = Connection.model_validate_json(previous[0])
                identity = ("connector", "account_ref", "environment", "terminal_path", "server")
                if any(getattr(old, field) != getattr(config, field) for field in identity):
                    raise ForexError(
                        "IDENTITY_LOCKED",
                        "This connection has execution history; create a new connection ID for another account, environment or terminal",
                    )
            db.execute(
                "INSERT INTO connections VALUES (?,?) ON CONFLICT(id) DO UPDATE SET config=excluded.config",
                (config.id, config.model_dump_json()),
            )

    def connections(self) -> list[Connection]:
        with self.db() as db:
            return [
                Connection.model_validate_json(row[0])
                for row in db.execute("SELECT config FROM connections ORDER BY id")
            ]

    def connection(self, identifier: str) -> Connection:
        with self.db() as db:
            row = db.execute("SELECT config FROM connections WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise ForexError("CONNECTION_NOT_FOUND", "Unknown forex connection")
        return Connection.model_validate_json(row[0])

    @staticmethod
    def _intent(row) -> dict:
        result = dict(row)
        for field in ("payload", "binding", "result"):
            result[field] = json.loads(result[field])
        return result

    def intent(self, identifier: str) -> dict:
        with self.db() as db:
            row = db.execute("SELECT * FROM intents WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise ForexError("INTENT_NOT_FOUND", "Unknown forex intent")
        return self._intent(row)

    def create_intent(self, config: Connection, order: Order) -> dict:
        payload = order.model_dump(mode="json")
        fingerprint = digest({"binding": config.fingerprint(), "order": payload})
        identifier = "fx_" + uuid.uuid4().hex
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT * FROM intents WHERE connection_id=? AND request_key=?", (config.id, order.request_key)
            ).fetchone()
            if existing:
                if existing["payload_hash"] != fingerprint:
                    raise ForexError(
                        "IDEMPOTENCY_CONFLICT", "Request key already belongs to another payload or account binding"
                    )
                return self._intent(existing)
            db.execute(
                "INSERT INTO intents(id,connection_id,connector,request_key,payload_hash,binding_hash,payload,binding,state,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    identifier,
                    config.id,
                    config.connector,
                    order.request_key,
                    fingerprint,
                    config.fingerprint(),
                    json.dumps(payload),
                    config.model_dump_json(),
                    "prepared",
                    utcnow().isoformat(),
                ),
            )
        return self.intent(identifier)

    def claim(self, identifier: str) -> bool:
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM intents WHERE id=?", (identifier,)).fetchone()
            if not row or row["state"] != "prepared":
                return False
            binding = db.execute("SELECT config FROM connections WHERE id=?", (row["connection_id"],)).fetchone()
            if not binding or Connection.model_validate_json(binding[0]).fingerprint() != row["binding_hash"]:
                raise ForexError("BINDING_CHANGED", "Connection changed before the execution claim")
            if db.execute(
                "SELECT 1 FROM intents WHERE connector=? AND state IN (?,?,?,?,?) AND id<>?",
                (row["connector"], *ACTIVE, identifier),
            ).fetchone():
                raise ForexError("RECONCILIATION_REQUIRED", "Another execution on this connector is unresolved")
            submitted_at = utcnow().isoformat()
            context = {
                "intent_id": identifier,
                "client_order_id": broker_reference(identifier),
                "submitted_at": submitted_at,
                "symbol": json.loads(row["payload"])["symbol"],
            }
            db.execute(
                "UPDATE intents SET state='submitting',submitted_at=?,result=? WHERE id=?",
                (submitted_at, json.dumps(context), identifier),
            )
            self._event(db, row["connection_id"], identifier, "submitting", context)
        return True

    def finish(self, identifier: str, state: str, result: dict) -> dict:
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT connection_id FROM intents WHERE id=?", (identifier,)).fetchone()
            if row is None:
                raise ForexError("INTENT_NOT_FOUND", "Unknown forex intent")
            db.execute("UPDATE intents SET state=?,result=? WHERE id=?", (state, json.dumps(result), identifier))
            self._event(db, row[0], identifier, state, result)
        return self.intent(identifier)

    def active(self, connector: str) -> list[dict]:
        with self.db() as db:
            rows = db.execute(
                "SELECT * FROM intents WHERE connector=? AND state IN (?,?,?,?,?)", (connector, *ACTIVE)
            ).fetchall()
        return [self._intent(row) for row in rows]

    def daily_count(self, connection_id: str) -> int:
        with self.db() as db:
            return db.execute(
                "SELECT count(*) FROM intents WHERE connection_id=? AND submitted_at>=?",
                (connection_id, utcnow().date().isoformat()),
            ).fetchone()[0]

    def owns_position(self, config, position):
        """Require broker identity, magic, ticket AND a filled entry in this journal."""
        if position.get("magic") != 2601103 or position.get("symbol") not in config.symbols:
            return False
        with self.db() as db:
            rows = db.execute("SELECT * FROM intents WHERE connection_id=? AND state='filled'", (config.id,)).fetchall()
        for raw in rows:
            row = self._intent(raw)
            payload, binding = row["payload"], row["binding"]
            if any(
                binding.get(k) != getattr(config, k)
                for k in ("account_ref", "server", "terminal_path", "environment", "connector")
            ):
                continue
            if (
                payload.get("action", "open") == "open"
                and payload["symbol"] == position["symbol"]
                and payload["side"] == ("buy" if position.get("type") == 0 else "sell")
                and position.get("comment") == broker_reference(row["id"])
                and str(row["result"].get("order_id")) in {str(position.get("ticket")), str(position.get("identifier"))}
            ):
                return True
        return False

    def reserve_analysis(self, key, connection_id):
        with self.db() as db:
            return (
                db.execute(
                    "INSERT OR IGNORE INTO ai_decisions VALUES(?,?,?,?)",
                    (
                        key,
                        connection_id,
                        json.dumps({"status": "analyzing", "decision_key": key}),
                        utcnow().isoformat(),
                    ),
                ).rowcount
                == 1
            )

    def save_analysis(self, key, data):
        with self.db() as db:
            db.execute("UPDATE ai_decisions SET payload=? WHERE decision_key=?", (json.dumps(data), key))

    def analysis(self, key):
        with self.db() as db:
            row = db.execute("SELECT payload FROM ai_decisions WHERE decision_key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def latest_analysis(self, connection_id):
        with self.db() as db:
            row = db.execute(
                "SELECT payload FROM ai_decisions WHERE connection_id=? ORDER BY created_at DESC LIMIT 1",
                (connection_id,),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def has_history(self, connection_id: str) -> bool:
        with self.db() as db:
            return (
                db.execute("SELECT 1 FROM intents WHERE connection_id=? LIMIT 1", (connection_id,)).fetchone()
                is not None
            )

    def executions(self, connection_id: str, limit: int = 50) -> list[dict]:
        with self.db() as db:
            rows = db.execute(
                "SELECT * FROM intents WHERE connection_id=? ORDER BY created_at DESC LIMIT ?",
                (connection_id, max(1, min(limit, 100))),
            ).fetchall()
        return [self._intent(row) for row in rows]

    def events(self, connection_id: str, after: int = 0) -> list[dict]:
        with self.db() as db:
            rows = db.execute(
                "SELECT * FROM events WHERE connection_id=? AND id>? ORDER BY id LIMIT 100",
                (connection_id, max(0, after)),
            ).fetchall()
        return [{**dict(row), "payload": json.loads(row["payload"])} for row in rows]

    def event(self, connection_id: str, kind: str, payload: dict) -> None:
        with self.db() as db:
            self._event(db, connection_id, None, kind, payload)

    @staticmethod
    def _event(db, connection_id, intent_id, kind, payload):
        db.execute(
            "INSERT INTO events(connection_id,intent_id,kind,payload,created_at) VALUES(?,?,?,?,?)",
            (connection_id, intent_id, kind, json.dumps(payload), utcnow().isoformat()),
        )
