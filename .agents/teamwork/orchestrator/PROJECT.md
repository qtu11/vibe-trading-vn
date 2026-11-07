# Project: Vibe-Trading Full-Stack Logic & Security Audit

## Architecture
- Backend: FastAPI, Pydantic, AgentLoop & Swarm execution engines, MCP tool registry (`agent/mcp_server.py`, `agent/src/tools/`), document/reporting engine (`src/reporting/`).
- Frontend: React, TypeScript, Vite, Tailwind/CSS, Lucide, Charting/Trading components, API client (`frontend/src/lib/api.ts`).
- Integration: REST endpoints, streaming responses (SSE/WebSocket), JSON contracts, file storage / report artifacts.

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Backend API Routes & Server | Deep inspection of `agent/api_server.py` and `agent/src/api/` | M1 | ORIGINAL_REQUEST |
| 2 | AgentLoop & Swarm Concurrency | Audit execution lifecycle, timeouts, cancellations, fallbacks | M1 | ORIGINAL_REQUEST |
| 3 | MCP Tools & Registry | Audit tool definitions, schemas, error isolation in `mcp_server.py` & `src/tools/` | M1 | ORIGINAL_REQUEST |
| 4 | Reporting Engine | Audit `src.reporting` document rendering, dependencies, concurrency | M1 | ORIGINAL_REQUEST |
| 5 | Frontend API Client & Contracts | Inspect `frontend/src/lib/api.ts` vs backend routes and parameters | M2 | ORIGINAL_REQUEST |
| 6 | TypeScript vs Pydantic Types | Audit type drift, missing fields, schema mismatches | M2 | ORIGINAL_REQUEST |
| 7 | React Error & State Handling | Audit error boundaries, toast notifications, loading/offline states | M2 | ORIGINAL_REQUEST |
| 8 | UI Component Robustness | Check research panels, trade cards, charts, report viewers for crash states | M2 | ORIGINAL_REQUEST |
| 9 | Numeric Precision & Currency | Audit VND scaling, token decimals, float math errors | M3 | ORIGINAL_REQUEST |
| 10 | Security & Resource Leaks | Audit path traversal, memory leaks, unclosed streams, race conditions | M3 | ORIGINAL_REQUEST |
| 11 | Synthesis & Deliverables | Compile findings, exact code locations, root causes, actionable patches | M4 | ORIGINAL_REQUEST |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Backend Deep Audit | `agent/src/api/`, `agent/api_server.py`, `agent/src/tools/`, AgentLoop, `src/reporting/` | none | DONE |
| M2 | Frontend Client & UI Audit | `frontend/src/lib/api.ts`, TypeScript contracts, React component error handling | none | DONE |
| M3 | Security, Logic & Precision Audit | Numeric precision, stream lifecycles, path traversal, race conditions | none | DONE |
| M4 | Deliverables Synthesis | Consolidation of verified findings, root causes, and patch proposals | M1, M2, M3 | DONE |

## Code Layout
- Backend routes: `agent/src/api/`, `agent/api_server.py`
- Backend core: `agent/src/core/`, `agent/src/tools/`, `agent/mcp_server.py`
- Reporting: `src/reporting/`
- Frontend API: `frontend/src/lib/api.ts`
- Frontend types: `frontend/src/types/`
- Frontend components: `frontend/src/components/`, `frontend/src/pages/`
