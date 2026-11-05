"""Single-operator desktop forex controls, protected by existing API authorization."""

import asyncio
import json
import logging

from fastapi import Depends, FastAPI, HTTPException, Query, Request

from src.api.security import require_auth, require_settings_write_auth
from src.live.daily_count import DailyOrderLockUnavailable, daily_order_lock
from src.live.halt import trip_halt, clear_halt
from src.live.mandate.store import load_mandate
from src.live.mandate.commit import save_proposal
from src.tools.propose_mandate_tool import ProposeMandateProfilesTool
from src.trading.forex.errors import ForexError
from src.trading.forex.council import ResearchPlanRequest
from src.trading.forex.models import AIStrategy, Connection, Order, Strategy, number
from src.trading.forex.runner import Runners
from src.trading.forex.service import ForexService

logger = logging.getLogger(__name__)


def register_forex_routes(app: FastAPI, service=None):
    service = service or ForexService()
    runners = Runners(service)
    app.state.forex_service, app.state.forex_runners = service, runners
    read = [Depends(require_auth)]
    write = [Depends(require_settings_write_auth)]

    def invoke(function, *args, **kwargs):
        try:
            return function(*args, **kwargs)
        except ForexError as exc:
            raise HTTPException(
                status_code=409
                if exc.code in ("RECONCILIATION_REQUIRED", "EXECUTION_PENDING", "BINDING_CHANGED", "IDENTITY_LOCKED")
                else 400,
                detail=exc.payload(),
            ) from exc
        except DailyOrderLockUnavailable as exc:
            raise HTTPException(
                status_code=409, detail={"code": "BROKER_BUSY", "error": "Another account operation is in progress"}
            ) from exc
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning("Forex operation failed (%s)", type(exc).__name__)
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "BROKER_UNAVAILABLE",
                    "error": "Broker service unavailable; verify connection settings and OS-vault credentials",
                },
            ) from exc

    @app.get("/api/forex/connections", dependencies=read)
    def connections():
        return {
            "connections": invoke(service.connections),
            "connectors": [
                {
                    "id": "mt5",
                    "label": "MetaTrader 5 — Exness / IC Markets / Pepperstone / FxPro",
                    "requires": "Windows terminal + MetaTrader5 extra",
                },
                {
                    "id": "exness",
                    "label": "Exness Trading API",
                    "requires": "Eligible Exness platform account, API key, Gateway and Access Point",
                },
                {"id": "oanda", "label": "OANDA v20", "requires": "v20 account + personal access token"},
            ],
        }

    @app.put("/api/forex/connections/{identifier}", dependencies=write)
    def save_connection(identifier: str, payload: Connection):
        if identifier != payload.id:
            raise HTTPException(400, "Connection ID cannot change")
        if runners.status(identifier).get("running"):
            raise HTTPException(409, "Stop the runner before changing its connection")
        return {"connection": invoke(service.save_connection, payload)}

    @app.post("/api/forex/mt5/auto-connect", dependencies=write)
    def auto_connect():
        from src.trading.forex.discovery import attach_running

        return invoke(attach_running, service)

    @app.get("/api/forex/market-snapshot", dependencies=read)
    def market_snapshot(symbol: str = Query(..., min_length=1, max_length=64),
        connection_id: str | None = Query(None, max_length=58), timeframe: str = "5m",
        limit: int = Query(60, ge=1, le=300)):
        from src.trading.forex.research import snapshot
        return invoke(snapshot, symbol, connection_id=connection_id, timeframe=timeframe, limit=limit, service=service)

    @app.get("/api/forex/research-context", dependencies=read)
    def market_research_context(
        symbol: str = Query(..., min_length=1, max_length=64),
        connection_id: str = Query(..., min_length=1, max_length=58),
        include_macro: bool = True, include_bars: bool = False,
    ):
        from src.trading.forex.analysis_context import research_context

        return invoke(research_context, symbol, connection_id=connection_id,
            include_macro=include_macro, include_bars=include_bars, service=service)

    @app.get("/api/forex/chart", dependencies=read)
    def native_chart(symbol: str = Query(..., min_length=1, max_length=64),
                     connection_id: str = Query(..., min_length=1, max_length=58), timeframe: str = "5m",
                     limit: int = Query(200, ge=30, le=300)):
        from src.trading.forex.chart import chart_snapshot

        return invoke(chart_snapshot, symbol, connection_id=connection_id, timeframe=timeframe, limit=limit, service=service)

    @app.get("/api/forex/connections/{identifier}/ai", dependencies=read)
    def ai_status(identifier: str):
        invoke(service.store.connection, identifier)
        return {"analysis": invoke(service.store.latest_analysis, identifier), "runner": runners.status(identifier)}

    @app.post("/api/forex/research-plan", dependencies=read)
    def market_research_plan(payload: ResearchPlanRequest):
        """Read-only council; uses configured model calls, never starts a runner."""
        from src.trading.forex.council import research_plan

        return invoke(research_plan, payload.symbol, connection_id=payload.connection_id,
            service=service, entry_mode=payload.entry_mode, include_macro=payload.include_macro,
            forecast_timeframe=payload.forecast_timeframe)

    @app.post("/api/forex/connections/{identifier}/ai/analyze", dependencies=write)
    def ai_analyze(identifier: str, payload: AIStrategy):
        return invoke(runners.ai.analyze, identifier, payload)

    @app.post("/api/forex/connections/{identifier}/ai/start", dependencies=write)
    async def ai_start(identifier: str, payload: AIStrategy):
        config = invoke(service.store.connection, identifier)
        if config.connector != "mt5" or config.environment != "demo":
            raise HTTPException(400, {"code": "AI_DEMO_ONLY", "error": "AI automatic execution requires MT5 demo"})
        verified = await asyncio.to_thread(invoke, service.verify, identifier)
        if not verified["account"].get("trade_allowed"):
            raise HTTPException(
                400,
                {
                    "code": "TRADING_DISABLED",
                    "error": "MT5: enable Algo Trading and uncheck Tools > Options > Expert Advisors > Disable automatic trading through the external Python API",
                },
            )
        if not verified["account"].get("hedging"):
            raise HTTPException(
                400, {"code": "HEDGING_REQUIRED", "error": "AI automatic execution requires a demo hedge account"}
            )
        return invoke(runners.start, identifier, payload)

    @app.post("/api/forex/connections/{identifier}/credentials", dependencies=write)
    async def credentials(identifier: str, request: Request):
        # Parse separately: Pydantic's automatic error input must not echo secrets.
        raw = await request.body()
        if len(raw) > 20000:
            raise HTTPException(413, "Credential payload too large")
        try:
            values = json.loads(raw)
        except ValueError:
            raise HTTPException(400, "Invalid credential payload")
        if (
            not isinstance(values, dict)
            or len(values) > 3
            or any(not isinstance(v, str) or len(v) > 12000 for v in values.values())
        ):
            raise HTTPException(400, "Invalid credential fields")
        return await asyncio.to_thread(invoke, service.save_credentials, identifier, values)

    @app.post("/api/forex/connections/{identifier}/verify", dependencies=write)
    def verify(identifier: str):
        return invoke(service.verify, identifier)

    @app.get("/api/forex/connections/{identifier}/mcp-config", dependencies=read)
    def mcp_config(identifier: str):
        return invoke(service.mcp_config, identifier)

    @app.get("/api/forex/connections/{identifier}/account", dependencies=read)
    def account(identifier: str):
        return invoke(service.read, identifier, "account")

    @app.get("/api/forex/connections/{identifier}/instruments", dependencies=read)
    def instruments(identifier: str, query: str = Query("", max_length=100), limit: int = Query(50, ge=1, le=300)):
        return invoke(service.read, identifier, "instruments", query=query, limit=limit)

    @app.get("/api/forex/connections/{identifier}/quote", dependencies=read)
    def quote(identifier: str, symbol: str = Query(..., max_length=64)):
        return invoke(service.read, identifier, "quote", symbol=symbol)

    @app.get("/api/forex/connections/{identifier}/candles", dependencies=read)
    def candles(
        identifier: str,
        symbol: str = Query(..., max_length=64),
        timeframe: str = "15m",
        limit: int = Query(100, ge=1, le=300),
    ):
        return invoke(service.read, identifier, "candles", symbol=symbol, timeframe=timeframe, limit=limit)

    @app.post("/api/forex/connections/{identifier}/preview", dependencies=write)
    def preview(identifier: str, payload: Order):
        return invoke(service.preview, identifier, payload)

    @app.post("/api/forex/connections/{identifier}/intents", dependencies=write)
    def create_intent(identifier: str, payload: Order):
        return invoke(service.create_intent, identifier, payload)

    @app.get("/api/forex/connections/{identifier}/intents", dependencies=read)
    def list_intents(identifier: str, limit: int = Query(50, ge=1, le=100)):
        invoke(service.store.connection, identifier)
        return {"intents": invoke(service.store.executions, identifier, limit)}

    @app.get("/api/forex/connections/{identifier}/intents/{intent_id}", dependencies=read)
    def get_intent(identifier: str, intent_id: str):
        return invoke(service.execution, identifier, intent_id)

    @app.post("/api/forex/connections/{identifier}/intents/{intent_id}/submit", dependencies=write)
    def submit_intent(identifier: str, intent_id: str):
        return invoke(service.submit, identifier, intent_id)

    @app.post("/api/forex/connections/{identifier}/intents/{intent_id}/reconcile", dependencies=write)
    def reconcile(identifier: str, intent_id: str):
        return invoke(service.execution, identifier, intent_id, reconcile=True)

    @app.post("/api/forex/connections/{identifier}/intents/{intent_id}/operation-reference", dependencies=write)
    def recover_reference(identifier: str, intent_id: str, payload: dict):
        if set(payload) != {"operation_id"}:
            raise HTTPException(400, "Supply only the operation_id from broker evidence")
        return invoke(service.recover_exness_reference, identifier, intent_id, payload["operation_id"])

    @app.get("/api/forex/connections/{identifier}/events", dependencies=read)
    def events(identifier: str, after: int = Query(0, ge=0)):
        invoke(service.store.connection, identifier)
        return {"events": invoke(service.store.events, identifier, after)}

    @app.get("/api/forex/connections/{identifier}/runner", dependencies=read)
    def runner_status(identifier: str):
        invoke(service.store.connection, identifier)
        return runners.status(identifier)

    @app.post("/api/forex/connections/{identifier}/runner/start", dependencies=write)
    async def start_runner(identifier: str, payload: Strategy):
        return invoke(runners.start, identifier, payload)

    @app.post("/api/forex/connections/{identifier}/runner/stop", dependencies=write)
    async def stop_runner(identifier: str):
        return await runners.stop(identifier)

    @app.post("/api/forex/connections/{identifier}/halt", dependencies=write)
    async def halt(identifier: str):
        config = invoke(service.store.connection, identifier)
        trip_halt("frontend", "Operator halted forex connection", broker=config.mandate_key)
        await runners.stop(identifier)
        return {"status": "halted"}

    @app.post("/api/forex/connections/{identifier}/resume", dependencies=write)
    async def resume(identifier: str):
        config = invoke(service.store.connection, identifier)
        await runners.stop(identifier)

        def clear():
            with daily_order_lock(config.connector):
                if service.store.active(config.connector):
                    raise HTTPException(409, "Reconcile outstanding executions before resuming")
                clear_halt(broker=config.mandate_key)
                service.store.event(identifier, "connection_resumed", {})

        invoke(clear)
        return {"status": "resumed", "runner": "operator_start_required"}

    @app.post("/api/forex/connections/{identifier}/resume-broker", dependencies=write)
    async def resume_broker(identifier: str):
        config = invoke(service.store.connection, identifier)
        for candidate in list(runners.tasks):
            if service.store.connection(candidate).connector == config.connector:
                await runners.stop(candidate)

        def clear():
            with daily_order_lock(config.connector):
                if service.store.active(config.connector):
                    raise HTTPException(409, "Reconcile every outstanding execution on this connector before resuming")
                clear_halt(broker=config.connector)
                service.store.event(identifier, "broker_resumed", {"connector": config.connector})

        invoke(clear)
        return {"status": "resumed", "scope": config.connector, "runner": "operator_start_required"}

    @app.post("/api/forex/connections/{identifier}/mandate-proposal", dependencies=write)
    def propose(identifier: str):
        config = invoke(service.store.connection, identifier)
        data = invoke(service.verify, identifier)["account"]
        if data["currency"] != "USD" or config.environment != "live":
            raise HTTPException(400, "Live mandate requires a verified USD live account")
        equity = float(number(data["equity"], positive=True))
        limits = config.limits
        result = json.loads(
            ProposeMandateProfilesTool().execute(
                broker=config.mandate_key,
                intent="Account-bound forex execution",
                ceilings={
                    "account_funding_usd": equity,
                    "max_order_notional_usd": float(limits.max_order_notional_usd),
                    "max_total_exposure_usd": float(limits.max_total_exposure_usd),
                    "max_trades_per_day": limits.max_orders_per_day,
                    "leverage": float(limits.max_leverage),
                    "allowed_instruments": ["forex", "cfd"],
                    "universe": ["forex"],
                },
            )
        )
        if result.get("status") == "error":
            raise HTTPException(400, "Could not construct a bounded forex mandate proposal")
        for profile in result.get("profiles", []):
            profile["asset_classes"] = ["forex"]
            profile["flatten_on_halt"] = False
        save_proposal(result)
        return {**result, "account_ref": config.account_ref}

    @app.get("/api/forex/connections/{identifier}/mandate", dependencies=read)
    def mandate_status(identifier: str):
        config = invoke(service.store.connection, identifier)
        mandate = load_mandate(config.mandate_key)
        return {
            "broker": config.mandate_key,
            "account_ref": config.account_ref,
            "present": mandate is not None,
            "expires_at": mandate.consent.expires_at if mandate else None,
            "bound_account_ref": mandate.consent.account_ref if mandate else None,
        }


async def shutdown_forex(app):
    runners = getattr(getattr(app, "state", None), "forex_runners", None)
    try:
        if runners:
            await runners.close()
    finally:
        service = getattr(getattr(app, "state", None), "forex_service", None)
        if service:
            service.close()
