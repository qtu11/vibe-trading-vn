# Project: Vibe-Trading Comprehensive Full-Stack Audit, Logic Verification, UI Flow & Performance Testing

## Architecture
- Backend: FastAPI, Pydantic v2 schemas, AgentLoop, Swarm runtime, Portfolio/Order Execution, Live Runner, Broker Adapters, MCP Tool Registry, Reporting Engine.
- Frontend: React 18/19 / TypeScript / Vite, Zustand/Context state management, ECharts/Trading charts, React Router, Tailwind/CSS.
- Storage & DB: SQLite3 databases (15 databases across portfolio, runs, sessions, goals, forex, etc.), JSON file stores.
- External Integrations: CCXT/Crypto exchanges, 19 Stock/Forex brokers, LLM APIs (OpenAI, Anthropic, QVeris, OpenRouter).

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Architecture & Data Flow Mapping | Map directory, dependencies, and trace UI -> API -> Service -> DB -> Broker flows | M1 | TASK_DEFINITION |
| 2 | Trading Engine & Financial Integrity | Audit trade execution, position sizing, risk management, balances, race conditions, precision | M2 | TASK_DEFINITION |
| 3 | Security & Secrets Posture | Inspect auth, tokens, API authz, input validation, SSRF, secrets | M2 | TASK_DEFINITION |
| 4 | UI/UX & Interaction Flow | Audit state management, rendering performance, error boundaries, form validation, contract drift | M3 | TASK_DEFINITION |
| 5 | Empirical Testing & Stress Testing | Run test suites, stress-test calculation engines & order pipelines, test latency/failures | M4 | TASK_DEFINITION |
| 6 | Comprehensive Audit Synthesis & Patches | Consolidate findings, root cause analysis, production-ready patches | M5 | TASK_DEFINITION |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Architecture & Data Flow Exploration | Map tech stack, module structure, and end-to-end data flows | none | DONE |
| M2 | Financial Logic & Security Deep Audit | Trade execution, position sizing, risk rules, concurrency, math precision, security vulnerabilities | M1 | DONE |
| M3 | UI/UX & Frontend Flow Deep Audit | State management, rendering performance, error boundaries, form validations, API contract alignment | M1 | DONE |
| M4 | Empirical Testing & Stress Validation | Execute unit/integration tests, write empirical verification harnesses for calculations & concurrency | M2, M3 | DONE |
| M5 | Master Audit Synthesis & Production Patches | Final deliverable report with severity classification, root causes, and production-ready patches | M1, M2, M3, M4 | DONE |

## Code Layout
- Backend: `agent/src/api/`, `agent/src/core/`, `agent/src/portfolio/`, `agent/src/agent/`, `agent/src/swarm/`, `agent/src/tools/`, `agent/mcp_server.py`, `agent/api_server.py`, `agent/src/reporting/`
- Frontend: `frontend/src/` (components, pages, lib, types, router)
- Tests: `agent/tests/`, `tests/`, `frontend/tests/`
