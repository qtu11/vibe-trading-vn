"""One execution path for HTTP, MCP and the deterministic runner."""

from datetime import timedelta
import sys
import re
import threading

from src.live.daily_count import daily_order_lock, increment_daily_count
from src.live.halt import halt_flag_set, read_halt, trip_halt
from src.trading.credentials import CredentialStore

from .errors import ForexError
from .audit import record_outcome
from .models import Connection, Order, utcnow
from .policy import authorize
from .risk import check
from .store import Store, ACTIVE

SECRET_FIELDS = {"mt5": ("password",), "exness": ("api_key", "private_key"), "oanda": ("token",)}


def adapter(config, credentials):
    if config.connector == "mt5":
        from .adapters.mt5 import MT5

        return MT5(config, credentials)
    if config.connector == "exness":
        from .adapters.exness import Exness

        return Exness(config, credentials)
    from .adapters.oanda import Oanda

    return Oanda(config, credentials)


class ForexService:
    def __init__(self, store=None, credentials=None, factory=None):
        self.store = store or Store()
        self.credentials = credentials or CredentialStore()
        self.factory = factory or adapter
        self.adapters = {}
        self.owners = {}
        self.cache_lock = threading.RLock()

    def close(self):
        with self.cache_lock:
            for client in self.adapters.values():
                client.close()
            self.adapters.clear()
            self.owners.clear()

    def invalidate(self, identifier):
        with self.cache_lock:
            for key in [key for key, owner in self.owners.items() if owner == identifier]:
                self.adapters.pop(key).close()
                self.owners.pop(key)

    def client(self, identifier):
        config = self.store.connection(identifier)
        with self.cache_lock:
            key = config.fingerprint()
            if key not in self.adapters:
                try:
                    values = (
                        {}
                        if config.connector == "mt5" and config.session_mode == "existing_terminal"
                        else self.credentials.load("forex-" + config.id, SECRET_FIELDS[config.connector])
                    )
                except Exception as exc:
                    raise ForexError(
                        "VAULT_UNAVAILABLE",
                        "Unlock the OS credential vault and install the keyring extra for this Python runtime",
                    ) from exc
                self.adapters[key] = self.factory(config, values)
                self.owners[key] = config.id
            return config, self.adapters[key]

    def save_connection(self, config: Connection):
        with daily_order_lock(config.connector):
            self.store.save_connection(config)
            self.invalidate(config.id)
        return config.model_dump(mode="json")

    def save_credentials(self, identifier, values):
        config = self.store.connection(identifier)
        if set(values) - set(SECRET_FIELDS[config.connector]):
            raise ForexError("INVALID_CREDENTIAL_FIELD", "Unexpected credential fields")
        with daily_order_lock(config.connector):
            if self.store.active(config.connector):
                raise ForexError("EXECUTION_PENDING", "Reconcile active executions before changing credentials")
            try:
                self.credentials.save("forex-" + identifier, values)
            except Exception as exc:
                raise ForexError(
                    "VAULT_UNAVAILABLE",
                    "OS vault could not save credentials; unlock the vault and verify the keyring extra",
                ) from exc
            self.invalidate(identifier)
        return {"status": "ok", "stored_fields": sorted(values)}

    def connections(self):
        result = []
        for config in self.store.connections():
            result.append(
                {
                    **config.model_dump(mode="json"),
                    "mandate_key": config.mandate_key,
                    "credential_ref": CredentialStore.reference("forex-" + config.id),
                    "identity_locked": self.store.has_history(config.id),
                    "global_halted": halt_flag_set(),
                    "broker_halted": read_halt(config.connector) is not None,
                    "connection_halted": read_halt(config.mandate_key) is not None,
                    "halted": halt_flag_set(config.connector) or halt_flag_set(config.mandate_key),
                }
            )
        return result

    def mcp_config(self, identifier):
        from src.config.paths import get_runtime_root

        self.store.connection(identifier)
        return {
            "mcpServers": {
                "forex-" + identifier: {
                    "command": sys.executable,
                    "args": ["-m", "forex_mcp_server", "--connection-id", identifier],
                    "env": {"VIBE_TRADING_HOME": str(get_runtime_root())},
                }
            }
        }

    def verify(self, identifier):
        config, client = self.client(identifier)
        data = client.account()
        self.current_binding(config)
        if str(data.get("account_ref")) != config.account_ref or data.get("environment") != config.environment:
            raise ForexError("ACCOUNT_MISMATCH", "Broker identity does not match the saved account/environment")
        if config.connector == "mt5":
            data["positions"] = [
                {**p, "managed": self.store.owns_position(config, p)} for p in data.get("positions", [])
            ]
        return {
            "status": "ready",
            "account": data,
            "execution_enabled": config.execution_enabled,
            "mandate_key": config.mandate_key,
            "credential_ref": CredentialStore.reference("forex-" + config.id),
        }

    def read(self, identifier, operation, **arguments):
        config, client = self.client(identifier)
        if operation not in ("account", "instruments", "quote", "candles", "chart"):
            raise ForexError("UNSUPPORTED_OPERATION", "Unknown forex read operation")
        if operation == "chart" and config.connector != "mt5":
            raise ForexError("CHART_MT5_REQUIRED", "Native live chart currently requires MT5")
        if "limit" in arguments:
            arguments["limit"] = max(1, min(int(arguments["limit"]), 300))
        if "timeframe" in arguments:
            supported = ("1m", "5m", "15m", "30m", "1h", "4h", "1d") if config.connector == "mt5" else ("5m", "15m", "1h", "4h")
            if arguments["timeframe"] not in supported:
                raise ForexError("INVALID_TIMEFRAME", "Unsupported timeframe for this broker connection")
        data = getattr(client, operation)(**arguments)
        self.current_binding(config)
        if operation == "account" and config.connector == "mt5":
            data["positions"] = [
                {**p, "managed": self.store.owns_position(config, p)} for p in data.get("positions", [])
            ]
        return {
            "status": "ok",
            "source": config.connector,
            "connection_id": identifier,
            "data": data,
        }

    def current_binding(self, config):
        if self.store.connection(config.id).fingerprint() != config.fingerprint():
            raise ForexError(
                "BINDING_CHANGED", "Connection changed while reading broker data; discard this response and refresh"
            )

    def preview(self, identifier, order: Order):
        config, client = self.client(identifier)
        assessment = client.prepare(order)
        self.current_binding(config)
        return {
            "status": "ok",
            "connection_id": identifier,
            "assessment": check(config, order, assessment),
            "execution_enabled": config.execution_enabled,
            "mandate_key": config.mandate_key,
        }

    def create_intent(self, identifier, order: Order):
        config = self.store.connection(identifier)
        if order.action == "close" and (config.connector != "mt5" or config.environment != "demo"):
            raise ForexError("CLOSE_UNSUPPORTED", "Position-specific closing is currently available on MT5 demo only")
        if not utcnow() < order.expires_at <= utcnow() + timedelta(minutes=15):
            raise ForexError("INVALID_EXPIRY", "Intent expiry must be in the next 15 minutes")
        if order.symbol not in config.symbols:
            raise ForexError("SYMBOL_NOT_ALLOWED", "Native symbol is outside the connection allowlist")
        return self.store.create_intent(config, order)

    def submit(self, identifier, intent_id, *, cancelled=None):
        row = self.store.intent(intent_id)
        if row["connection_id"] != identifier:
            raise ForexError("ACCOUNT_MISMATCH", "Intent belongs to another connection")
        if row["state"] != "prepared":
            return row  # Durable idempotency: repeated calls never resend.
        config, client = self.client(identifier)
        with daily_order_lock(config.connector):
            row = self.store.intent(intent_id)
            if row["state"] != "prepared":
                return row
            if row["binding_hash"] != config.fingerprint():
                raise ForexError("BINDING_CHANGED", "Connection changed; create a new intent")
            order = Order.model_validate(row["payload"])
            try:
                if cancelled and cancelled():
                    raise ForexError("RUNNER_STOPPED", "Runner stopped before broker submission")
                assessment = client.prepare(order)
                mandate = authorize(config, order, assessment, self.store)
                if cancelled and cancelled():
                    raise ForexError("RUNNER_STOPPED", "Runner stopped during order valuation")
            except ForexError as exc:
                refusal = {"code": exc.code, "error": str(exc)}
                self.store.event(identifier, "preflight_rejected", {"intent_id": intent_id, **refusal})
                try:
                    record_outcome(config, row, "rejected", refusal, gate_allowed=False)
                except Exception:
                    pass  # The action is already denied; never send after an audit failure.
                raise
            if not self.store.claim(intent_id):
                return self.store.intent(intent_id)
            context = self.store.intent(intent_id)["result"]
            assessment["intent_id"] = intent_id
            gate_allowed = False
            try:
                mandate = authorize(config, order, assessment, self.store, own_intent=intent_id)
                if cancelled and cancelled():
                    raise ForexError("RUNNER_STOPPED", "Runner stopped before starting broker submission")
                gate_allowed = True
                result = client.submit(order, assessment)
                state = result.get("state", "unknown")
                if state not in (*ACTIVE, "filled", "confirmed", "rejected", "cancelled"):
                    state = "unknown"
            except ForexError as exc:
                # Only provably pre-send/pre-ACK refusals are terminal. A worker
                # crash or network error must retain a recovery barrier.
                definitive = {
                    "BROKER_REJECTED",
                    "RATE_LIMIT",
                    "LIMITS_UNAVAILABLE",
                    "INVALID_STOPS",
                    "READONLY",
                    "HALTED",
                    "INTENT_EXPIRED",
                    "ACCOUNT_MISMATCH",
                    "ENVIRONMENT_MISMATCH",
                    "MANDATE_REQUIRED",
                    "MANDATE_EXPIRED",
                    "MANDATE_LIMIT",
                    "DAILY_LIMIT",
                    "INVALID_ATTEMPT",
                    "BINDING_CHANGED",
                    "SYMBOL_NOT_ALLOWED",
                    "UNSUPPORTED_ACCOUNT_CURRENCY",
                    "TRADING_DISABLED",
                    "PENDING_ORDERS",
                    "QUOTE_TIME_UNKNOWN",
                    "STALE_QUOTE",
                    "STALE_CONVERSION",
                    "INVALID_QUOTE",
                    "MARKET_CLOSED",
                    "SPREAD_LIMIT",
                    "INVALID_VOLUME_STEP",
                    "QUANTITY_LIMIT",
                    "INVALID_STOP_PRECISION",
                    "INVALID_STOP",
                    "INVALID_TAKE_PROFIT_PRECISION",
                    "INVALID_TAKE_PROFIT",
                    "NOTIONAL_LIMIT",
                    "STOP_RISK_LIMIT",
                    "EXPOSURE_UNAVAILABLE",
                    "EXPOSURE_LIMIT",
                    "LEVERAGE_LIMIT",
                    "INSUFFICIENT_MARGIN",
                    "DRAWDOWN_LIMIT",
                    "VALUATION_UNAVAILABLE",
                    "CONVERSION_UNAVAILABLE",
                    "EXECUTION_MODE_UNSUPPORTED",
                    "CLOSE_UNSUPPORTED",
                    "POSITION_NOT_OWNED",
                    "POSITION_CHANGED",
                    "HEDGING_REQUIRED",
                    "RUNNER_STOPPED",
                }
                state = "rejected" if exc.code in definitive else "unknown"
                result = {"state": state, "code": exc.code, "error": str(exc)}
            except Exception:
                state, result = (
                    "unknown",
                    {
                        "state": "unknown",
                        "code": "EXECUTION_UNKNOWN",
                        "error": "No definitive broker receipt; reconcile before another order",
                    },
                )
            result = {**context, **result, "state": state}
            if state == "unknown":
                trip_halt("file", "Forex execution outcome is unknown: " + intent_id, broker=config.connector)
            try:
                audit = record_outcome(config, row, state, result, mandate, gate_allowed=gate_allowed)
                if audit:
                    result["audit_id"] = audit["audit_id"]
                saved = self.store.finish(intent_id, state, result)
                increment_daily_count(config.mandate_key, action_id=intent_id)
            except Exception:
                trip_halt("file", "Forex execution accounting requires recovery", broker=config.connector)
                try:
                    self.store.finish(
                        intent_id,
                        "unknown",
                        {
                            **result,
                            "state": "unknown",
                            "broker_reported_state": state,
                            "code": "ACCOUNTING_RECOVERY_REQUIRED",
                        },
                    )
                except Exception:
                    pass  # The durable pre-send claim still fences all submissions.
                raise ForexError(
                    "ACCOUNTING_RECOVERY_REQUIRED",
                    "Submission may have completed; inspect the durable intent before continuing",
                )
            return saved

    def execution(self, identifier, intent_id, reconcile=False):
        row = self.store.intent(intent_id)
        if row["connection_id"] != identifier:
            raise ForexError("ACCOUNT_MISMATCH", "Intent belongs to another connection")
        if reconcile and row["state"] in ACTIVE:
            config, client = self.client(identifier)
            with daily_order_lock(config.connector):
                receipt = client.reconcile(row["result"])
                state = receipt.get("state", "unknown")
                if state not in (*ACTIVE, "filled", "confirmed", "rejected", "cancelled"):
                    state = "unknown"
                return self.store.finish(intent_id, state, receipt)
        return row

    def recover_exness_reference(self, identifier, intent_id, operation_id):
        """Trusted operator supplies a lost ACK's reference; broker must prove correlation."""
        if not isinstance(operation_id, str) or not re.fullmatch(r"[A-Za-z0-9._~-]{1,128}", operation_id):
            raise ForexError("INVALID_REFERENCE", "Invalid Exness operation ID")
        config, client = self.client(identifier)
        if config.connector != "exness":
            raise ForexError("UNSUPPORTED_OPERATION", "Manual operation reference recovery applies only to Exness API")
        with daily_order_lock(config.connector):
            row = self.execution(identifier, intent_id)
            if row["state"] not in ACTIVE or not row["result"].get("client_order_id"):
                raise ForexError("INVALID_ATTEMPT", "This intent does not have a pending correlated execution")
            receipt = client.reconcile({**row["result"], "operation_id": operation_id})
            state = receipt.get("state", "unknown")
            if state not in (*ACTIVE, "filled", "confirmed", "rejected", "cancelled"):
                state = "unknown"
            return self.store.finish(intent_id, state, receipt)
