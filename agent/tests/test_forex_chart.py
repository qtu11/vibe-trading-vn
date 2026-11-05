"""Sanitized chart/shape/forecast contracts. Never send an order or use a network."""

from copy import deepcopy
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from src.trading.forex.chart import chart_snapshot
from src.trading.forex.errors import ForexError
from src.trading.forex.models import Connection, utcnow
from src.trading.forex.price_action import candle_evidence


def bars(count=35):
    boundary = int(utcnow().timestamp()) // 300 * 300
    return [{"time": datetime.fromtimestamp(boundary - (count - i) * 300, timezone.utc).isoformat(),
             "open": 100, "high": 102, "low": 98, "close": 101, "volume": 100 + i, "complete": True}
            for i in range(count)]


@pytest.mark.parametrize("name,previous,current", [
    ("doji_shape", (100, 102, 98, 101), (100, 102, 98, 100.1)),
    ("hammer_shape", (100, 102, 98, 101), (100, 101.1, 97, 101)),
    ("shooting_star_shape", (100, 102, 98, 101), (101, 104, 99.9, 100)),
    ("bullish_engulfing_shape", (101, 102, 98, 99), (98.5, 102, 98, 101.5)),
    ("bearish_engulfing_shape", (99, 102, 98, 101), (101.5, 102, 98, 98.5)),
    ("inside_bar", (100, 104, 96, 101), (100, 102, 98, 101)),
])
def test_explicit_shapes_are_bound_to_actual_closed_candles(name, previous, current):
    rows = bars()
    for b, values in ((rows[-2], previous), (rows[-1], current)):
        b.update(zip(("open", "high", "low", "close"), values))
    evidence = candle_evidence(rows)
    assert any(p["name"] == name and p["time"] == rows[-1]["time"] for p in evidence["patterns"])
    assert evidence["forming_candle_used"] is False
    assert evidence["recent_candles"][-1][1:5] == list(current)


def test_forming_candle_cannot_repaint_pattern_evidence_or_become_a_swing():
    rows = bars()
    expected = candle_evidence(rows)
    forming = {**rows[-1], "time": utcnow().isoformat(), "close": 1000, "high": 1001, "complete": False}
    assert candle_evidence(rows + [forming]) == expected
    assert all(p["time"] not in {b["time"] for b in rows[-2:]} for p in expected["swings_high"] + expected["swings_low"])


def test_breakout_range_excludes_last_closed_candle():
    rows = bars()
    rows[-1].update(open=101, high=111, low=100, close=110)
    result = candle_evidence(rows, atr=4)
    assert result["resistance_20"] == 102 and result["bullish_close_above"] == 102.4
    assert result["breakout"] == "close_above_range"


def test_bad_geometry_is_rejected_and_short_history_is_explicit():
    assert candle_evidence(bars(10))["status"] == "insufficient"
    bad = bars()
    bad[-1]["low"] = 200
    with pytest.raises(ValueError):
        candle_evidence(bad)


@pytest.fixture
def chart_broker():
    config = Connection(id="chart-fixture", label="Fixture", connector="mt5", account_ref="12345",
        server="Fixture-Demo", terminal_path=r"C:\Fixture\terminal64.exe", session_mode="existing_terminal")
    rows = bars()
    boundary = int(utcnow().timestamp()) // 300 * 300
    rows.append({**rows[-1], "time": datetime.fromtimestamp(boundary, timezone.utc).isoformat(), "complete": False})
    quote = {"bid": "100.1", "ask": "100.2", "timestamp": utcnow().isoformat()}
    payload = {"bars": rows, "quote": quote}
    calls = []
    def read(identifier, operation, **kwargs):
        assert operation == "chart" and identifier == config.id
        calls.append(kwargs)
        return {"data": deepcopy(payload)}
    service = SimpleNamespace(store=SimpleNamespace(connection=lambda _: config), read=read, current_binding=lambda _: None)
    return config, payload, service, calls


def test_native_chart_returns_actual_zero_bar_and_excludes_it_from_patterns(chart_broker):
    config, _, service, calls = chart_broker
    result = chart_snapshot("XAUUSDm", connection_id=config.id, service=service)
    assert result["forming_bar_time"] == result["bars"][-1]["time"]
    assert result["price_action"]["closed_count"] == len(result["bars"]) - 1
    assert result["price_action"]["as_of"] == result["bars"][-2]["time"]
    assert result["quote"]["is_fresh"] and result["trading_performed"] is False
    assert calls == [{"symbol": "XAUUSDm", "timeframe": "5m", "limit": 200}]


@pytest.mark.parametrize("invalid", ["duplicate", "future", "geometry", "crossed_quote"])
def test_chart_rejects_invalid_broker_data(chart_broker, invalid):
    config, payload, service, _ = chart_broker
    if invalid == "duplicate":
        payload["bars"][-1]["time"] = payload["bars"][-2]["time"]
    elif invalid == "future":
        payload["bars"][-1]["time"] = "2099-01-01T00:00:00+00:00"
    elif invalid == "geometry":
        payload["bars"][-1]["high"] = 90
    else:
        payload["quote"]["ask"] = "99"
    with pytest.raises(ForexError):
        chart_snapshot("XAUUSDm", connection_id=config.id, service=service)


def test_chart_account_binding_change_is_not_published(chart_broker):
    config, _, service, _ = chart_broker
    def reject(_):
        raise ForexError("BINDING_CHANGED", "Changed account")
    service.current_binding = reject
    with pytest.raises(ForexError, match="Changed account"):
        chart_snapshot("XAUUSDm", connection_id=config.id, service=service)


def test_sdk_reads_zero_bar_only_for_chart_not_strategy(monkeypatch):
    from src.trading.forex.adapters.mt5_worker import Native

    calls = []
    def rates(symbol, frame, start, count):
        calls.append(start)
        return [{"time": int(utcnow().timestamp()) // 300 * 300, "open": 100, "high": 102, "low": 99,
                 "close": 101, "tick_volume": 10, "real_volume": 0}]
    sdk = SimpleNamespace(TIMEFRAME_M5=5, copy_rates_from_pos=rates)
    client = Native(sdk, None, None)
    monkeypatch.setattr(client, "instrument", lambda _: None)
    monkeypatch.setattr(client, "quote", lambda _: {"bid": "101", "ask": "101.1"})
    monkeypatch.setattr(client, "identity", lambda: None)
    client.chart("XAUUSDm", "5m", 200)
    client.candles("XAUUSDm", "5m", 200)
    assert calls == [0, 1]


def test_read_waits_for_terminal_contention_without_replaying_native_operation(monkeypatch):
    from src.trading.forex.adapters import mt5_worker as worker

    entries, sleeps, operations = [], [], []
    @contextmanager
    def lock(key):
        entries.append(key)
        if len(entries) < 3:
            raise worker.DailyOrderLockUnavailable("Fixture busy")
        yield
    monkeypatch.setattr(worker, "daily_order_lock", lock)
    monkeypatch.setattr(worker, "monotonic", lambda: 0)
    monkeypatch.setattr(worker, "sleep", sleeps.append)
    with worker.terminal_read_lock("fixture"):
        operations.append("one-read")
    assert len(entries) == 3 and sleeps == [.05, .05] and operations == ["one-read"]


def test_read_contention_has_a_bounded_wait(monkeypatch):
    from src.trading.forex.adapters import mt5_worker as worker

    @contextmanager
    def busy(_):
        raise worker.DailyOrderLockUnavailable("Fixture busy")
        yield
    clock = iter([0, 11])
    monkeypatch.setattr(worker, "daily_order_lock", busy)
    monkeypatch.setattr(worker, "monotonic", lambda: next(clock))
    with pytest.raises(ForexError) as failure:
        with worker.terminal_read_lock("fixture"):
            pytest.fail("Must not run without lock")
    assert failure.value.code == "MT5_BUSY"


def test_error_after_read_lock_acquired_is_not_retried(monkeypatch):
    from src.trading.forex.adapters import mt5_worker as worker

    entries = []
    @contextmanager
    def lock(_):
        entries.append(1)
        yield
    monkeypatch.setattr(worker, "daily_order_lock", lock)
    with pytest.raises(worker.DailyOrderLockUnavailable):
        with worker.terminal_read_lock("fixture"):
            raise worker.DailyOrderLockUnavailable("Native operation failed after acquisition")
    assert entries == [1]


def test_dispatch_queues_reads_but_submission_lock_contention_stays_fail_closed(monkeypatch, chart_broker):
    from src.trading.forex.adapters import mt5_worker as worker

    config, _, _, _ = chart_broker
    queued, calls = [], []
    monkeypatch.setattr(worker, "terminal_read_lock", lambda key: (queued.append(key), nullcontext())[1])
    monkeypatch.setattr(worker, "existing_session", lambda path: nullcontext(object()))
    monkeypatch.setattr(worker, "Native", lambda *args: SimpleNamespace(identity=lambda: None, quote=lambda **kw: calls.append("quote")))
    @contextmanager
    def busy(_):
        raise worker.DailyOrderLockUnavailable("Fixture busy")
        yield
    monkeypatch.setattr(worker, "daily_order_lock", busy)
    payload = {"config": config.model_dump(mode="json"), "operation": "quote", "arguments": {"symbol": "XAUUSDm"}}
    worker.dispatch(payload)
    assert len(queued) == 1 and calls == ["quote"]
    with pytest.raises(worker.DailyOrderLockUnavailable):
        worker.dispatch({**payload, "operation": "submit", "arguments": {}})
    assert len(queued) == 1 and calls == ["quote"]
