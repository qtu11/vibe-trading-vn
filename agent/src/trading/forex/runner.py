"""Closed-candle SMA crossover runner; operator-started, never auto-resumed."""

import asyncio
from datetime import datetime, timedelta, timezone
import logging
import threading

from .errors import ForexError
from .models import AIStrategy, Order, Strategy, digest, number, utcnow

logger = logging.getLogger(__name__)
INTERVAL_SECONDS = {"5m": 300, "15m": 900, "1h": 3600, "4h": 14400}


def completed_bars(rows, timeframe, now=None):
    """Reject stale/gapped history so an old crossover cannot become a new trade."""
    now = now or utcnow()
    interval = timedelta(seconds=INTERVAL_SECONDS[timeframe])
    unique = {}
    for row in rows:
        if row.get("complete") is not True:
            continue
        try:
            stamp = datetime.fromisoformat(row["time"].replace("Z", "+00:00"))
            if stamp.tzinfo is None or stamp.utcoffset() is None:
                raise ValueError("Timezone required")
            stamp = stamp.astimezone(timezone.utc)
            number(row["close"], positive=True)
        except (KeyError, TypeError, ValueError) as exc:
            raise ForexError("INVALID_HISTORY", "Broker candle time or price is invalid") from exc
        if stamp in unique and unique[stamp]["close"] != row["close"]:
            raise ForexError("INVALID_HISTORY", "Broker returned conflicting candles for the same time")
        unique[stamp] = row
    stamps = sorted(unique)
    if not stamps:
        return []
    last_close = stamps[-1] + interval
    if last_close > now + timedelta(seconds=2) or now - last_close > interval:
        raise ForexError("STALE_HISTORY", "Wait for current completed broker candles before starting a strategy")
    # A weekend or missing data requires a fresh continuous lookback window.
    if any(right - left != interval for left, right in zip(stamps, stamps[1:])):
        raise ForexError("HISTORY_GAP", "Strategy history has missing intervals; wait for a continuous lookback window")
    return [unique[stamp] for stamp in stamps]


def crossover(bars, fast, slow):
    closes = [number(row["close"], positive=True) for row in bars if row.get("complete") is True]
    if len(closes) < slow + 1:
        return None
    previous_fast = sum(closes[-fast - 1 : -1]) / fast
    previous_slow = sum(closes[-slow - 1 : -1]) / slow
    current_fast = sum(closes[-fast:]) / fast
    current_slow = sum(closes[-slow:]) / slow
    if previous_fast <= previous_slow and current_fast > current_slow:
        return "buy"
    if previous_fast >= previous_slow and current_fast < current_slow:
        return "sell"
    return None


class Runners:
    def __init__(self, service):
        self.service, self.tasks, self.states = service, {}, {}
        from .ai import AIEngine

        self.ai = AIEngine(service)
        self.stopped = {}

    def status(self, identifier):
        return self.states.get(
            identifier, {"running": False, "status": "stopped", "resume_policy": "operator_start_required"}
        )

    async def stop(self, identifier):
        if identifier in self.stopped:
            self.stopped[identifier].set()
        task = self.tasks.pop(identifier, None)
        if task:
            task.cancel()
            # The actor thread may be inside send. shield lets it finish and
            # persist its receipt before stop reports success.
            await asyncio.gather(task, return_exceptions=True)
        self.states[identifier] = {**self.status(identifier), "running": False, "status": "stopped"}
        return self.status(identifier)

    async def close(self):
        for identifier in list(self.tasks):
            await self.stop(identifier)

    def start(self, identifier, strategy: Strategy | AIStrategy):
        if identifier in self.tasks and not self.tasks[identifier].done():
            raise ForexError("RUNNER_ACTIVE", "Stop the active runner before changing its strategy")
        config = self.service.store.connection(identifier)
        if isinstance(strategy, AIStrategy) and (config.connector != "mt5" or config.environment != "demo"):
            raise ForexError("AI_DEMO_ONLY", "Automatic AI execution currently requires an MT5 demo account")
        if not config.execution_enabled or strategy.symbol not in config.symbols:
            raise ForexError("READONLY", "Enable execution and allow the strategy's native symbol first")
        self.states[identifier] = {
            "running": True,
            "status": "starting",
            "strategy": strategy.model_dump(mode="json"),
            "resume_policy": "operator_start_required",
            "mode": "ai" if isinstance(strategy, AIStrategy) else "sma",
        }
        self.stopped[identifier] = threading.Event()
        self.tasks[identifier] = asyncio.create_task(self._loop(identifier, strategy))
        return self.status(identifier)

    async def _loop(self, identifier, strategy):
        try:
            while True:
                work = asyncio.create_task(asyncio.to_thread(self.tick, identifier, strategy))
                try:
                    update = await asyncio.shield(work)
                except asyncio.CancelledError:
                    await work  # A started broker action must record its outcome.
                    raise
                self.states[identifier].pop("error", None)
                self.states[identifier].pop("code", None)
                self.states[identifier].update(update, running=True, checked_at=utcnow().isoformat())
                needs_operator = update.get("status") in ("halted", "unknown", "reconciliation_required") or update.get(
                    "code"
                ) in (
                    "READONLY",
                    "HALTED",
                    "ACCOUNT_MISMATCH",
                    "ENVIRONMENT_MISMATCH",
                    "BINDING_CHANGED",
                    "MANDATE_REQUIRED",
                    "MANDATE_EXPIRED",
                    "MANDATE_LIMIT",
                    "DAILY_LIMIT",
                    "DRAWDOWN_LIMIT",
                    "AI_DEMO_ONLY",
                    "AI_UNCONFIGURED",
                    "AI_UNAVAILABLE",
                    "TRADING_DISABLED",
                    "HEDGING_REQUIRED",
                    "POSITION_NOT_OWNED",
                )
                if needs_operator:
                    break
                await asyncio.sleep(strategy.interval_seconds)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Forex runner stopped unexpectedly")
        finally:
            self.states[identifier].update(running=False)

    def tick(self, identifier, strategy):
        try:
            if isinstance(strategy, AIStrategy):
                return self.ai.tick(identifier, strategy, self.stopped[identifier])
            config = self.service.store.connection(identifier)
            from src.live.halt import halt_flag_set

            if halt_flag_set(config.connector) or halt_flag_set(config.mandate_key):
                return {"status": "halted"}
            active = self.service.store.active(config.connector)
            for row in active:
                if row["connection_id"] == identifier:
                    self.service.execution(identifier, row["id"], reconcile=True)
            if self.service.store.active(config.connector):
                return {"status": "reconciliation_required"}
            account = self.service.read(identifier, "account")["data"]
            # This initial strategy enters only when flat; SL/TP manage exits.
            if account.get("positions") or account.get("orders"):
                return {"status": "waiting_for_flat_account"}
            rows = self.service.read(
                identifier, "candles", symbol=strategy.symbol, timeframe=strategy.timeframe, limit=strategy.slow + 2
            )["data"]
            rows = completed_bars(rows, strategy.timeframe)
            side = crossover(rows, strategy.fast, strategy.slow)
            if not side:
                return {"status": "no_signal", "last_bar": rows[-1]["time"] if rows else None}
            revision = digest(strategy.model_dump(mode="json"))
            key = "sma-" + digest({"connection": identifier, "revision": revision, "bar": rows[-1]["time"]})[:48]
            with self.service.store.db() as db:
                existing = db.execute(
                    "SELECT id,state FROM intents WHERE connection_id=? AND request_key=?", (identifier, key)
                ).fetchone()
            if existing:
                return {"status": "signal_already_recorded", "intent_id": existing[0]}
            quote = self.service.read(identifier, "quote", symbol=strategy.symbol)["data"]
            price = number(quote["ask"] if side == "buy" else quote["bid"])
            distance = number(quote["point"]) * strategy.stop_distance_points
            direction = 1 if side == "buy" else -1
            order = Order(
                symbol=strategy.symbol,
                side=side,
                quantity=strategy.quantity,
                stop_loss=str(price - direction * distance),
                take_profit=str(price + direction * distance * number(strategy.reward_ratio)),
                request_key=key,
                expires_at=utcnow() + timedelta(seconds=90),
                strategy_revision=revision,
            )
            intent = self.service.create_intent(identifier, order)
            result = self.service.submit(identifier, intent["id"])
            return {"status": result["state"], "intent_id": intent["id"], "last_bar": rows[-1]["time"]}
        except ForexError as exc:
            return {"status": "blocked", "code": exc.code, "error": str(exc)}
        except Exception:
            return {
                "status": "unavailable",
                "error": "Broker data or worker is unavailable; no automatic retry of a submitted order",
            }
