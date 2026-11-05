from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from pydantic import ValidationError

from src.trading.forex.models import Connection, Order, number, utcnow
from src.trading.forex.store import Store
from src.trading.forex.errors import ForexError


def config(**overrides):
    return Connection(id="demo", label="Demo", connector="oanda", account_ref="101-001", **overrides)


def order(**overrides):
    return Order.model_validate(
        dict(
            symbol="EUR_USD",
            side="buy",
            quantity="1",
            stop_loss="1.05",
            request_key="sample-1",
            expires_at=utcnow() + timedelta(minutes=1),
            **overrides,
        )
    )


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "1e9999999", True, "9" * 100])
def test_decimal_rejects_unbounded(value):
    with pytest.raises(ValueError):
        number(value)


def test_execution_needs_symbols_and_exness_demo_is_not_invented():
    with pytest.raises(ValidationError):
        config(execution_enabled=True)
    with pytest.raises(ValidationError):
        Connection(id="exness", label="Exness", connector="exness", account_ref="123")


def test_store_idempotent_across_threads_and_restarts(tmp_path):
    store = Store(tmp_path / "fx.db")
    cfg = config()
    store.save_connection(cfg)
    request = order()
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: store.create_intent(cfg, request), range(3)))
    assert len({r["id"] for r in results}) == 1
    identifier = results[0]["id"]
    assert Store(store.path).intent(identifier)["state"] == "prepared"
    with pytest.raises(ForexError, match="another payload"):
        store.create_intent(cfg, request.model_copy(update={"quantity": "2"}))
    assert store.claim(identifier)
    assert not store.claim(identifier)
    assert store.daily_count(cfg.id) == 1
    assert len(store.active("oanda")) == 1
    with pytest.raises(ForexError):
        store.save_connection(cfg)
    store.finish(identifier, "filled", {"filled_quantity": "1"})
    assert not store.active("oanda")
    assert [r["kind"] for r in store.events(cfg.id)] == ["submitting", "filled"]


def test_account_identity_and_original_binding_are_not_relabelled(tmp_path):
    store = Store(tmp_path / "fx.db")
    cfg = config()
    store.save_connection(cfg)
    row = store.create_intent(cfg, order())
    assert row["binding"] == cfg.model_dump(mode="json")
    with pytest.raises(ForexError) as exc:
        store.save_connection(cfg.model_copy(update={"account_ref": "101-999"}))
    assert exc.value.code == "IDENTITY_LOCKED"
    store.save_connection(cfg.model_copy(update={"label": "Renamed"}))
    assert store.intent(row["id"])["binding"]["label"] == "Demo"


def test_schema_one_migration_does_not_fabricate_old_binding(tmp_path):
    import sqlite3

    path = tmp_path / "fx.db"
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE intents(id TEXT PRIMARY KEY, connection_id TEXT, connector TEXT, request_key TEXT, payload_hash TEXT, binding_hash TEXT, payload TEXT, state TEXT, result TEXT, created_at TEXT, submitted_at TEXT)"
        )
        db.execute(
            "INSERT INTO intents VALUES('old','demo','oanda','old-key','hash','binding','{}','unknown','{}','2026-11-01',NULL)"
        )
        db.execute("PRAGMA user_version=1")
    assert Store(path).intent("old")["binding"] == {}
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 3
