# Original User Request

## Approved Task Prompt — 2026-11-06T12:51:44Z

# APPROVED TASK PROMPT: COMPREHENSIVE AUDIT OF BACKEND & FRONTEND LOGIC (VIBE-TRADING)

## Scope & Target Repository:
- Workspace: D:\Vibe-Trading
- Full-stack codebase: Python/FastAPI backend, AgentLoop, Swarm, MCP tools, Research Artifacts, Report Engine, React/TypeScript/Vite frontend.

## Key Objectives:
1. Backend Audit:
   - Deep inspection of all API routes in `agent/src/api/` and `agent/api_server.py`.
   - Audit error handling, input validation (Pydantic / Zod), boundary conditions, and race conditions.
   - Audit AgentLoop & Swarm execution, timeouts, cancellation tokens, and fallback strategies.
   - Audit `src.reporting` and document rendering engine for edge cases, missing dependencies, and concurrency safety.
   - Audit MCP tools in `agent/mcp_server.py` and tool registry in `agent/src/tools/`.

2. Frontend Audit:
   - Deep inspection of API client calls in `frontend/src/lib/api.ts` against actual backend routes.
   - Audit TypeScript types and contracts against FastAPI models to detect contract drifts and type mismatches.
   - Audit error boundaries, toast notifications, loading states, and network failure fallbacks across React components.
   - Check research panels, trade cards, charts, and report artifact viewers for rendering crashes or unhandled states.

3. Missing Logic & Vulnerability Check:
   - Identify unhandled HTTP status codes, missing query/body parameters, unvalidated user inputs.
   - Check numeric precision issues (VND scaling, token decimals, floating point rounding).
   - Check storage traversal risks, memory leaks, and unclosed streams.

4. Deliverables:
   - Categorized findings (Critical, High, Medium, Low).
   - Exact file locations and offending code lines.
   - Root causes and actionable patch recommendations.

Proceed with execution immediately.
