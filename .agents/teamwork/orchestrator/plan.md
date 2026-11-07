# Audit Execution Plan: Vibe-Trading Full-Stack Logic & Security

## 1. Objective
Execute a comprehensive technical and security audit of the Vibe-Trading platform spanning backend APIs, AgentLoop/Swarm, MCP tools, report generation, frontend client & React UI components, type safety/contracts, and cross-cutting vulnerabilities.

## 2. Work Breakdown Structure (WBS)
- Track 1: Backend Architecture & API Layer
  - API routes in `agent/src/api/` and `agent/api_server.py`.
  - Pydantic models, request validation, error responses.
  - AgentLoop & Swarm execution lifecycles, cancellation tokens, timeouts.
  - Reporting & document engine (`src/reporting/`).
  - MCP server & tools (`agent/mcp_server.py`, `agent/src/tools/`).
- Track 2: Frontend Client, React Architecture & Type Alignment
  - Client API implementation in `frontend/src/lib/api.ts` vs backend routes.
  - TypeScript types vs FastAPI Pydantic schema contracts.
  - React error boundaries, fallback states, toast error handling.
  - UI components (charts, research panels, trade cards, report viewers).
- Track 3: Cross-Cutting Logic, Numeric Precision & Vulnerability Analysis
  - Numeric precision (VND scaling, token decimals, float math).
  - Stream lifecycle, unclosed sockets/files, memory leaks.
  - Path traversal in file/report downloads/artifacts.
  - Race conditions in AgentLoop, Swarm, concurrent transactions.
- Track 4: Synthesis & Deliverable Compilation
  - Consolidate all verified findings into Critical, High, Medium, Low severity.
  - Validate exact file paths, line numbers, root cause explanations.
  - Provide concrete, production-ready patch recommendations for every finding.

## 3. Execution Phases
1. Phase 1: Planning and Workspace Setup (plan.md, progress.md, context.md, PROJECT.md).
2. Phase 2: Parallel Deep Explorations (Dispatch 3 teamwork_explorer subagents for Tracks 1, 2, 3).
3. Phase 3: Forensic & Vulnerability Auditing (Dispatch teamwork_auditor to independently stress-test logic).
4. Phase 4: Synthesis, Gate Evaluation & Final Audit Report Delivery.
