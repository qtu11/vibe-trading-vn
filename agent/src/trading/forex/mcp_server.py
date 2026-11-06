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
from .cost_stress import CostStressRequest, cost_stress
from .trade_paths import TradePathsRequest, trade_paths
from .regime import RegimeRequest, regime
from .models import Connection, Order, Symbol
from .service import ForexService, SECRET_FIELDS
from .walk_forward import WalkForwardRequest, walk_forward


def build_server(service: ForexService, connection_id: str, *, allow_execution=False, allow_research_writes=False):
    config = service.store.connection(connection_id)
    if allow_execution and not config.execution_enabled:
        raise ForexError("READONLY", "Operator must enable this connection's execution setting first")
    server = FastMCP("Vibe-Forex")
    read = {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": True}
    local_read = {**read, "openWorldHint": False}

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

    async def research_call(function, *args):
        try:
            return await asyncio.to_thread(function, *args)
        except ForexError as exc:
            return exc.payload()
        except Exception:
            return {"status": "error", "code": "RESEARCH_STORE_UNAVAILABLE", "error": "Local research storage is unavailable"}

    @server.tool(annotations=local_read)
    async def forex_list_experiments(
        limit: Annotated[int, Field(ge=1, le=100)] = 20, offset: Annotated[int, Field(ge=0)] = 0,
    ) -> dict:
        """List local supplied-data experiments and all-attempt counts. No broker access."""
        return await research_call(service.store.research_experiments, limit, offset)

    @server.tool(annotations=local_read)
    async def forex_get_experiment(
        experiment_id: str, limit: Annotated[int, Field(ge=1, le=100)] = 20,
        offset: Annotated[int, Field(ge=0)] = 0,
    ) -> dict:
        """List an experiment's attempts, including failed/incomplete attempts, newest first."""
        return await research_call(service.store.research_experiment, experiment_id, limit, offset)

    @server.tool(annotations=local_read)
    async def forex_get_experiment_run(experiment_id: str, run_id: str) -> dict:
        """Read immutable inputs, costs, engine versions and every trial/fold result for one attempt."""
        return await research_call(service.store.research_run, experiment_id, run_id)

    if allow_research_writes:

        @server.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False})
        async def forex_run_experiment(request: WalkForwardRequest, experiment_id: str | None = None) -> dict:
            """Persist a supplied-data SMA/EMA attempt; omit experiment_id to create an experiment.

            Keeps every failed trial and the full input/config/cost/version snapshot.
            Appending never overwrites evidence, activates a strategy or sends orders.
            """
            return await research_call(service.run_experiment, request, experiment_id)

        @server.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False})
        async def forex_run_cost_stress_experiment(request: CostStressRequest, experiment_id: str | None = None) -> dict:
            """Append a frozen-OOS spread sweep with explicit costs, source hashes and all failures.

            Creates an experiment when experiment_id is omitted. Local evidence
            write only; never activates a strategy, accesses a broker or sends orders.
            """
            return await research_call(service.run_cost_stress_experiment, request, experiment_id)

        @server.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False})
        async def forex_run_trade_paths_experiment(request: TradePathsRequest, experiment_id: str | None = None) -> dict:
            """Append seeded within-fold OOS block-resampling evidence to the local journal.

            Creates an experiment if experiment_id is omitted. Keeps base trials,
            sampling assumptions and failures. Never accesses a broker or trades.
            """
            return await research_call(service.run_trade_paths_experiment, request, experiment_id)

    @server.tool(annotations=local_read)
    async def forex_walk_forward(request: WalkForwardRequest) -> dict:
        """Fit bounded SMA/EMA candidates on past supplied OHLC and score chronological OOS folds.

        Caller declares complete contiguous mid-price bars, revision and constant
        round-trip costs. One-bar research variant; no account access or orders.
        """
        return await asyncio.to_thread(walk_forward, request)

    @server.tool(annotations=local_read)
    async def forex_cost_stress(request: CostStressRequest) -> dict:
        """Fit once at base cost, freeze OOS trades, then stress spread at base/2x/3x.

        Caller explicitly supplies round-trip spread, commission, slippage and
        fixed adverse gap charges in bps on mid bars. Other costs stay fixed.
        Arithmetic break-even may be negative. No broker, store write or orders.
        """
        return await asyncio.to_thread(cost_stress, request)

    @server.tool(annotations=local_read)
    async def forex_trade_paths(request: TradePathsRequest) -> dict:
        """Resample noncircular contiguous OOS trade blocks independently within each fold.

        Fit once on supplied historical mid bars at base costs, then freeze OOS
        returns. Seeded empirical return/drawdown bands are not predictive
        probabilities; no annualization, broker access or local evidence write.
        """
        return await asyncio.to_thread(trade_paths, request)

    @server.tool(annotations=local_read)
    async def forex_regime(request: RegimeRequest) -> dict:
        """Replay train-calibrated ATR-normalized SMA-slope regimes on supplied closed mid bars.

        Fits only an initial training prefix, then applies frozen quantile
        thresholds, hysteresis and minimum dwell. Warmup/invalid calibration
        stays unknown. No ADX, forecast, trade/PnL, broker or persistence.
        """
        return await asyncio.to_thread(regime, request)

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
    parser.add_argument("--allow-research-writes", action="store_true", help="Expose local supplied-data experiment persistence; never enables orders")
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
        server = build_server(service, args.connection_id, allow_execution=args.allow_execution, allow_research_writes=args.allow_research_writes)
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
