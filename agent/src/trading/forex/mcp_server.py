"""Local stdio MCP: one operator-selected account per process."""

import argparse
import asyncio
import getpass
import json
from pathlib import Path
from typing import Annotated, Literal

from fastmcp import FastMCP
from pydantic import Field

from .errors import ForexError
from .models import Connection, Order, Symbol
from .service import ForexService, SECRET_FIELDS


def build_server(service: ForexService, connection_id: str, *, allow_execution=False):
    config = service.store.connection(connection_id)
    if allow_execution and not config.execution_enabled:
        raise ForexError("READONLY", "Operator must enable this connection's execution setting first")
    server = FastMCP("Vibe-Forex")
    read = {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": True}

    async def call(function, *args, **kwargs):
        try:
            if service.store.connection(connection_id).fingerprint() != config.fingerprint():
                raise ForexError(
                    "BINDING_CHANGED", "Connection settings changed; restart this account-bound MCP process"
                )
            return await asyncio.to_thread(function, *args, **kwargs)
        except ForexError as exc:
            return exc.payload()
        except Exception:
            return {
                "status": "error",
                "code": "BROKER_UNAVAILABLE",
                "error": "Broker service unavailable; check configuration, credentials and outstanding executions",
            }

    @server.tool(annotations=read)
    async def forex_connection_status() -> dict:
        """Verify the bound broker account and demo/live identity. Never places orders."""
        return await call(service.verify, connection_id)

    @server.tool(annotations=read)
    async def forex_list_instruments(
        query: Annotated[str, Field(max_length=100)] = "", limit: Annotated[int, Field(ge=1, le=300)] = 50
    ) -> dict:
        """Search native instrument names. Use returned names verbatim, including MT5 suffixes."""
        return await call(service.read, connection_id, "instruments", query=query, limit=limit)

    @server.tool(annotations=read)
    async def forex_get_account() -> dict:
        """Read the bound account, open positions, pending orders and available monetary fields."""
        return await call(service.read, connection_id, "account")

    @server.tool(annotations=read)
    async def forex_get_quote(symbol: Symbol) -> dict:
        """Read broker bid/ask and UTC timestamp for an exact native instrument. No research fallback."""
        return await call(service.read, connection_id, "quote", symbol=symbol)

    @server.tool(annotations=read)
    async def forex_get_candles(
        symbol: Symbol, timeframe: str = "15m", limit: Annotated[int, Field(ge=1, le=300)] = 100
    ) -> dict:
        """Read bounded native bars (MT5: 1m/5m/15m/30m/1h/4h/1d), with completeness and source."""
        return await call(service.read, connection_id, "candles", symbol=symbol, timeframe=timeframe, limit=limit)

    if config.connector == "mt5":

        @server.tool(annotations=read)
        async def forex_research_context(symbol: Symbol, include_macro: bool = True) -> dict:
            """Read 300 completed M5/H1/H4/D1 bars and dated macro context for the bound MT5 account.

            Returns computed trend/RSI/ATR/ranges with source hashes, DXY, TIPS
            real yield and, for gold, GLD holdings/estimated creations plus CME
            volume when available. Missing sources stay explicit. No orders.
            """
            from .analysis_context import research_context

            return await call(research_context, symbol, connection_id=connection_id,
                include_macro=include_macro, service=service)

        @server.tool(annotations=read)
        async def forex_research_plan(symbol: Symbol, entry_mode: Literal["auto", "market", "limit"] = "auto",
                                      include_macro: bool = True,
                                      forecast_timeframe: Literal["5m", "1h", "4h", "1d"] = "5m") -> dict:
            """Six configured-model research roles debate BUY/SELL and return validated price scenarios.

            Read-only; invokes up to six billable model calls on one MT5 evidence
            snapshot. A risk veto, stale quote or incomplete role returns WAIT.
            Reports retain actual model identity; role count is not model diversity.
            Never sends orders or starts a trading runner. Prices expire in 60 seconds.
            """
            from .council import research_plan

            return await call(research_plan, symbol, connection_id=connection_id, entry_mode=entry_mode,
                              include_macro=include_macro, forecast_timeframe=forecast_timeframe, service=service)

    @server.tool(annotations=read)
    async def forex_preview_order(order: Order) -> dict:
        """Estimate protected order risk, margin and constraints without sending an order."""
        return await call(service.preview, connection_id, order)

    @server.tool(annotations=read)
    async def forex_get_execution(intent_id: str) -> dict:
        """Inspect the persisted execution journal for this account. Does not change its state."""
        return await call(service.execution, connection_id, intent_id)

    if allow_execution:

        @server.tool(
            annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}
        )
        async def forex_reconcile_execution(intent_id: str) -> dict:
            """Read exact broker evidence and update the execution journal. Never retries broker submissions."""
            return await call(service.execution, connection_id, intent_id, reconcile=True)

        @server.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True})
        async def forex_create_intent(order: Order) -> dict:
            """Persist an immutable account-bound intent. A request key cannot change payload. Does not trade."""
            return await call(service.create_intent, connection_id, order)

        @server.tool(
            annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True}
        )
        async def forex_submit_intent(intent_id: str) -> dict:
            """Submit one persisted intent through risk/consent/halt gates. ACK is not fill; unknown never resends."""
            return await call(service.submit, connection_id, intent_id)

    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description="Vibe Forex MCP — local account-bound MT5, Exness and OANDA")
    parser.add_argument("--connection-id")
    parser.add_argument(
        "--allow-execution",
        action="store_true",
        help="Expose execution tools; saved connection and live mandate are still required",
    )
    parser.add_argument("--import-config", type=Path, help="Operator-only: import one connection JSON without secrets")
    parser.add_argument(
        "--set-credentials", action="store_true", help="Operator-only: prompt securely and store in OS vault"
    )
    parser.add_argument("--list-connections", action="store_true")
    parser.add_argument(
        "--print-mcp-config",
        action="store_true",
        help="Print a read-only MCP config using this interpreter and runtime directory",
    )
    args = parser.parse_args(argv)
    service = ForexService()
    try:
        if args.import_config:
            config = Connection.model_validate_json(args.import_config.read_text(encoding="utf-8-sig"))
            service.save_connection(config)
            print(json.dumps({"status": "saved", "connection_id": config.id}))
            return 0
        if args.list_connections:
            print(json.dumps(service.connections(), ensure_ascii=False))
            return 0
        if not args.connection_id:
            parser.error("--connection-id is required for MCP or credential setup")
        if args.print_mcp_config:
            print(json.dumps(service.mcp_config(args.connection_id), ensure_ascii=False, indent=2))
            return 0
        if args.set_credentials:
            cfg = service.store.connection(args.connection_id)
            values = {field: getpass.getpass(field + ": ") for field in SECRET_FIELDS[cfg.connector]}
            service.save_credentials(cfg.id, values)
            print("Credentials saved in the OS vault.")
            return 0
        server = build_server(service, args.connection_id, allow_execution=args.allow_execution)
        server.run(transport="stdio")
        return 0
    except ForexError as exc:
        parser.exit(2, f"{exc.code}: {exc}\n")
    except ValueError:
        parser.exit(2, "Invalid connection configuration; secrets must be stored separately in the OS vault.\n")
    except Exception:
        parser.exit(2, "Forex setup/server failed; verify the runtime, OS vault and connection configuration.\n")
    finally:
        service.close()
