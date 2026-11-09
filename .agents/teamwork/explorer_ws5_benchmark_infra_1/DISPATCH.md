# Task Assignment: Explorer WS5 (Benchmark & Integration Infra)

## Identity
- Role: Codebase Researcher (WS5 & Benchmark)
- Type: teamwork_explorer
- Working directory: d:\Vibe-Trading\.agents\teamwork\explorer_ws5_benchmark_infra_1

## Mandatory Documents
- Read ORIGINAL_REQUEST.md: d:\Vibe-Trading\.agents\teamwork\ORIGINAL_REQUEST.md

## Scope & Objective
Survey existing test suites, tool registries, and testing infrastructure, then design Workstream 5 (Benchmark & Empirical Verification) and tool integration architecture:
1. Workstream 5 (Benchmark & Empirical Verification):
   - Inspect existing tests in `tests/`, `agent/tests/`, and tool definitions in `agent/src/tools/`.
   - Design empirical benchmark harness measuring:
     * Latency (e.g., p50, p90, p99 across multi-search and scraping).
     * Token savings percentage (validating the 75-90% token pruning requirement).
     * Throughput under concurrent load.
     * Information retrieval fidelity (key fact retention score).
   - Design comprehensive test suite (unit tests, mock network responses, integration tests, rate-limiting & error recovery tests).
2. Tool Integration & API Contract:
   - Design unified tool interfaces for `ParallelWebSearchTool` and `ConcurrentScraperTool` replacing or augmenting `agent/src/tools/web_search_tool.py` and `web_reader_tool.py`.
   - Ensure backward compatibility and seamless exposure to AgentLoop and MCP server.

## Deliverable
Write your findings and architectural specifications to:
`d:\Vibe-Trading\.agents\teamwork\explorer_ws5_benchmark_infra_1\handoff.md`

## 2026-11-08T14:41:49Z
Message from fc6481d3-86d0-438b-b509-e00be11b4dba:
Survey the current codebase in d:\Vibe-Trading and produce a comprehensive technical specification and architecture for Workstream 5 (Benchmark & Empirical Verification) and tool integration:
1. Workstream 5 (Benchmark & Empirical Verification):
- Inspect existing tests in `tests/`, `agent/tests/`, and tool definitions in `agent/src/tools/` and `agent/mcp_server.py`.
- Design an empirical benchmark harness measuring:
  * Latency comparison (baseline web_search / web_reader vs parallel multi-engine scraper).
  * Token consumption comparison: raw tokens vs pruned tokens (target: 75-90% token reduction).
  * Throughput under concurrent load (e.g. 5, 10, 20 concurrent queries).
  * Information retrieval fidelity (key fact retention score).
- Design comprehensive test suite (unit tests, mock network responses, integration tests, rate-limiting & error recovery tests).
2. Tool Integration & API Contract:
- Design unified tool interfaces for `ParallelWebSearchTool` and `ConcurrentScraperTool` replacing or augmenting `agent/src/tools/web_search_tool.py` and `web_reader_tool.py`.
- Ensure backward compatibility and seamless exposure to AgentLoop, API server, and MCP server.
