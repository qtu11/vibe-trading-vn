from datetime import timedelta
from types import SimpleNamespace

import pytest

from src.trading.forex.errors import ForexError
from src.trading.forex.models import Strategy, utcnow
from src.trading.forex.runner import Runners, completed_bars, crossover


def test_crossover_ignores_incomplete_candle():
    def bars(values):
        return [{"close": str(x), "complete": True} for x in values]

    assert crossover(bars([3, 2, 1, 4]), 2, 3) == "buy"
    assert crossover(bars([1, 2, 3, 0.5]), 2, 3) == "sell"
    rows = bars([3, 2, 1]) + [{"close": "4", "complete": False}]
    assert crossover(rows, 2, 3) is None
    assert crossover(bars([1, 1, 1, 1]), 2, 3) is None


def recent_bars():
    now = utcnow().replace(second=0, microsecond=0)
    start = now - timedelta(minutes=20)
    return [
        {"time": (start + timedelta(minutes=5 * i)).isoformat(), "close": str(x), "complete": True}
        for i, x in enumerate([3, 2, 1, 4])
    ], now


def test_completed_bars_reject_stale_gapped_future_and_conflicting_data():
    rows, now = recent_bars()
    assert len(completed_bars([*rows, rows[-1]], "5m", now)) == 4
    for bad, at, code in [
        (rows, now + timedelta(minutes=10), "STALE_HISTORY"),
        (rows, now - timedelta(minutes=1), "STALE_HISTORY"),
        ([rows[0], *rows[2:]], now, "HISTORY_GAP"),
        ([*rows, {**rows[-1], "close": "5"}], now, "INVALID_HISTORY"),
    ]:
        with pytest.raises(ForexError) as exc:
            completed_bars(bad, "5m", at)
        assert exc.value.code == code


def test_runner_never_recreates_recorded_bar_signal_or_trades_stale_history(monkeypatch):
    rows, now = recent_bars()
    calls = []
    cfg = SimpleNamespace(connector="oanda", mandate_key="forex-demo")

    class DB:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def execute(self, *_):
            return self

        def fetchone(self):
            return ("already-recorded", "rejected")

    store = SimpleNamespace(connection=lambda _: cfg, active=lambda _: [], db=DB)

    def read(_, op, **kwargs):
        calls.append(op)
        return {"data": {"positions": [], "orders": []} if op == "account" else rows}

    service = SimpleNamespace(store=store, read=read)
    monkeypatch.setattr("src.trading.forex.runner.utcnow", lambda: now)
    runner = Runners(service)
    strategy = Strategy(symbol="EUR_USD", quantity="1", fast=2, slow=3, timeframe="5m")
    assert runner.tick("demo", strategy)["status"] == "signal_already_recorded"
    assert calls == ["account", "candles"]  # no quote, intent or broker write
    monkeypatch.setattr("src.trading.forex.runner.utcnow", lambda: now + timedelta(days=3))
    assert runner.tick("demo", strategy)["code"] == "STALE_HISTORY"


@pytest.mark.asyncio
async def test_runner_stops_after_unknown_and_requires_explicit_start(monkeypatch):
    import asyncio

    cfg = SimpleNamespace(execution_enabled=True, symbols=("EUR_USD",))
    service = SimpleNamespace(store=SimpleNamespace(connection=lambda _: cfg))
    runner = Runners(service)
    monkeypatch.setattr(runner, "tick", lambda *_: {"status": "unknown", "intent_id": "fx_fixture"})
    runner.start("demo", Strategy(symbol="EUR_USD", quantity="1"))
    await asyncio.wait_for(runner.tasks["demo"], timeout=2)
    assert runner.status("demo")["status"] == "unknown"
    assert not runner.status("demo")["running"]
