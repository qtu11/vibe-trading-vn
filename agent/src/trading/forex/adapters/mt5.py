"""Isolate MetaTrader's process-global native SDK from the web/MCP processes."""

import json
import os
import subprocess
import sys

from ..errors import ForexError
from ..models import Connection, Order


class MT5:
    def __init__(self, config: Connection, credentials: dict):
        self.config, self.credentials = config, credentials
        if config.session_mode == "credentials" and not credentials.get("password"):
            raise ForexError("CREDENTIALS_UNAVAILABLE", "Save the MT5 account password in the OS vault")

    def call(self, operation: str, **arguments) -> dict | list:
        payload = {
            "config": self.config.model_dump(mode="json"),
            "credentials": self.credentials,
            "operation": operation,
            "arguments": arguments,
        }
        try:
            result = subprocess.run(
                [sys.executable, "-m", "src.trading.forex.adapters.mt5_worker"],
                input=json.dumps(payload),
                text=True,
                encoding="utf-8",
                capture_output=True,
                timeout=40,
                creationflags=0x08000000 if os.name == "nt" else 0,
                env={**os.environ, "PYTHONUTF8": "1"},
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ForexError(
                "MT5_WORKER_UNAVAILABLE", "MT5 worker did not complete; a submission may require reconciliation"
            ) from exc
        try:
            response = json.loads(result.stdout)
        except (ValueError, TypeError) as exc:
            raise ForexError("MT5_WORKER_UNAVAILABLE", "MT5 worker returned no valid response") from exc
        if response.get("status") == "error":
            raise ForexError(response.get("code", "MT5_ERROR"), response.get("error", "MT5 operation failed"))
        return response["data"]

    def account(self):
        return self.call("account")

    def instruments(self, query="", limit=50):
        return self.call("instruments", query=query, limit=limit)

    def quote(self, symbol):
        return self.call("quote", symbol=symbol)

    def candles(self, symbol, timeframe, limit):
        return self.call("candles", symbol=symbol, timeframe=timeframe, limit=limit)

    def chart(self, symbol, timeframe, limit):
        return self.call("chart", symbol=symbol, timeframe=timeframe, limit=limit)

    def prepare(self, order: Order):
        return self.call("prepare", order=order.model_dump(mode="json"))

    def submit(self, order: Order, prepared: dict):
        return self.call("submit", order=order.model_dump(mode="json"), intent_id=prepared.get("intent_id"))

    def reconcile(self, receipt):
        return self.call("reconcile", receipt=receipt)

    def close(self):
        pass


def probe_terminal(path):
    """Read the already logged-in identity; no login/password or broker writes."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "src.trading.forex.adapters.mt5_worker"],
            input=json.dumps({"operation": "probe", "terminal_path": path}),
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=20,
            creationflags=0x08000000 if os.name == "nt" else 0,
            env={**os.environ, "PYTHONUTF8": "1"},
        )
        response = json.loads(result.stdout)
        if response.get("status") != "ok":
            raise ForexError(response.get("code", "MT5_UNAVAILABLE"), response.get("error", "Cannot inspect MT5"))
        return response["data"]
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        raise ForexError("MT5_UNAVAILABLE", "Cannot inspect this running MT5 terminal") from exc
