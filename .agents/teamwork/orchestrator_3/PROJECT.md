# Project: Deep Research & Development Blueprint (Visualizations, Candlestick Engines, Data Pipelines, AI Quality, CFA Compliance)

## Architecture Overview
- Frontend Visualization Layer: React 19 + TypeScript + Apache ECharts 6.1 (Pie, Bar, Line, Candlestick, ForexCandlePlot, ForexPlanChart).
- Data Layer: Real-time tick streaming (WebSocket/SSE), connectors (MT5, CCXT, Exness, OANDA), batch loaders (Akshare, YFinance), tick aggregation, UTC alignment, VWAP.
- Agent & AI Reasoning Layer: ReAct agent loop (`agent/src/agent/loop.py`), Swarm DAG orchestrator (`agent/src/swarm/`), 6-role Council (`council.py`: Technical, Macro, Bull, Bear, Risk, Manager), grounding ledger, citation traceability.
- Quantitative & Standards Layer: CFA Level I/II/III curriculum and GIPS compliance (Geometric compounding, Sharpe sqrt(252), Sortino semideviation, Information Ratio, Calmar, MaxDD, Brinson-Fachler, Monte Carlo).

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Multi-Dimensional Financial Chart Audit | Audit Pie, Bar, Line, Candlestick components in `frontend/src/components/charts/` & `frontend/src/components/forex/` | WS1 | User Spec |
| 2 | Real-Time Candlestick Engine (Equities & XAU/USD) | WebSocket/SSE tick buffering, rAF throttling, multi-timeframe crosshair sync, MT5/Exness/OANDA integration | WS1 | User Spec |
| 3 | Ingestion & Normalization Pipelines | Broker connectors (MT5, CCXT) and loaders (Akshare, YFinance) audit, tick aggregation, UTC alignment, VWAP | WS2 | User Spec |
| 4 | Agent Architecture & Council Reasoning | ReAct loop, Swarm DAG, 6-role Council debate, grounding ledger, citation traceability, anti-hallucination | WS3 | User Spec |
| 5 | CFA Institute & Quantitative Accuracy Audit | Geometric return compounding, annualized Sharpe, Sortino downside semideviation, IR, Calmar, MaxDD, Brinson-Fachler, Monte Carlo | WS4 | User Spec |
| 6 | Master Blueprint & Implementation Synthesis | Unified architectural blueprint, math formulation, code locations, step-by-step implementation guide | Synthesis | User Spec |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| WS1 | Charts & Candlestick Engines | Audit all chart components, ECharts 6.1 lifecycle, tick aggregation, XAU/USD engine | None | DONE |
| WS2 | Data Ingestion & Pipelines | Connectors, loaders, data normalization, UTC alignment, VWAP | None | DONE |
| WS3 | Agent Architecture & AI Quality | ReAct loop, Swarm DAG, 6-role Council, grounding ledger, citations | None | DONE |
| WS4 | CFA Standards & Quant Accuracy | Math formula audit vs CFA/GIPS, risk metrics, factor attribution | None | DONE |
| SYN | Master Synthesis & Blueprint | Comprehensive final blueprint report | WS1, WS2, WS3, WS4 | DONE |

## Code Layout & Targets
- `frontend/src/components/charts/`
- `frontend/src/components/forex/`
- `agent/src/trading/connectors/`
- `agent/backtest/loaders/`
- `agent/src/agent/loop.py`
- `agent/src/swarm/`
- `agent/src/council.py`
- `agent/src/evaluation/` & `agent/src/backtest/`
