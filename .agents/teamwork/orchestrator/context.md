# Audit Context: Vibe-Trading

## Scope Details
- Target Codebase: `D:\Vibe-Trading`
- Backend Components:
  - `agent/api_server.py`
  - `agent/src/api/`
  - `agent/mcp_server.py`
  - `agent/src/tools/`
  - `agent/src/core/` (AgentLoop, Swarm)
  - `src/reporting/` (Report & document engine)
- Frontend Components:
  - `frontend/src/lib/api.ts`
  - `frontend/src/types/`
  - `frontend/src/components/` (Research panels, charts, trade cards, report artifact viewers)
  - `frontend/src/hooks/`
- Vulnerability Focus Areas:
  - Route mismatches and missing error handling
  - Type drift between Pydantic and TypeScript
  - Numeric scaling (VND currency, decimal places, float inaccuracies)
  - Concurrency, cancellation tokens, unclosed streams, path traversal risks
