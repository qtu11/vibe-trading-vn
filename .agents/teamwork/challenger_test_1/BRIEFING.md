# BRIEFING — 2026-11-08T13:36:00Z

## Mission
Thực hiện kiểm thử thực nghiệm (empirical verification), chạy test suites hiện có, và thiết kế các bộ test harness stress-test các calculation engines và trade pipelines quan trọng trong dự án Vibe-Trading.

## 🔒 My Identity
- Archetype: empirical-challenger
- Roles: critic, specialist
- Working directory: D:\Vibe-Trading\.agents\teamwork\challenger_test_1
- Original parent: 7e08280a-8fd7-4506-96dd-ff29673b0567
- Milestone: milestone-1
- Instance: 1 of 1

## 🔒 Key Constraints
- Review-only — do NOT modify implementation code directly
- Strict empirical testing — all assertions must be backed by executed code logs
- No hardcoding or dummy implementations
- Strict Vietnamese language, no emojis, professional architectural style
- Avoid putting source code in .agents/teamwork/

## Current Parent
- Conversation ID: 7e08280a-8fd7-4506-96dd-ff29673b0567
- Updated: 2026-11-08T13:36:00Z

## Review Scope
- **Files reviewed and tested**:
  * `agent/tests/test_empirical_stress_harness.py`: Custom stress test harness covering 6 critical dimensions.
  * Backend suites (`agent/tests/`): 21,876 tests collected, core suites run and verified.
  * Frontend suites (`frontend/`): 125 test files / 1,136 vitest tests passing, `tsc -b` and `vite build` passing.
  * Calculation engines (`vietnam_equity.py`, `china_a.py`, `crypto.py`, `base.py`).
  * Currency & precision logic (`fx.py`, `vietnam_research_tool.py`).
  * Concurrency & database (`store.py`, `live_routes.py`, `kernel.py`).
- **Interface contracts**: D:\Vibe-Trading\.agents\teamwork\orchestrator_2\PROJECT.md
- **Review criteria**: correctness, numerical precision, edge cases, thread safety, database concurrency

## Key Decisions Made
- Executed full frontend test suite: 125 test files, 1,136 tests passed (0 failures).
- Verified full frontend typecheck and build via `tsc -b && vite build` (build succeeded in 5.96s).
- Successfully collected all 21,876 backend pytest tests after resolving environment dependencies (`matplotlib`, `python-docx`, `openpyxl`, `langchain-core`, `nh3`, `reportlab`, `pypdfium2`, `ccxt`).
- Created and executed empirical test harness `agent/tests/test_empirical_stress_harness.py` containing 14 automated stress tests.
- Re-verified empirical failure modes: SQLite `database is locked` under concurrency, floating-point fee accumulation drift, missing VND FX fail-closed, and accounting Capex sign convention rejections.

## Artifact Index
- D:\Vibe-Trading\.agents\teamwork\challenger_test_1\DISPATCH.md — Dispatch log
- D:\Vibe-Trading\.agents\teamwork\challenger_test_1\progress.md — Liveness heartbeat and progress
- D:\Vibe-Trading\.agents\teamwork\challenger_test_1\handoff.md — Final handoff report
- D:\Vibe-Trading\agent\tests\test_empirical_stress_harness.py — Automated empirical test harness for CI/CD

## Attack Surface
- **Hypotheses tested**:
  1. Position sizing handles boundary lot sizes (0, negative, fractional, extreme prices) -> Verified.
  2. Vietnam equity strictly rejects short-selling (`allow_short=True`) -> Confirmed `ValueError`.
  3. High-frequency floating-point fee calculations drift over large trade volumes -> Confirmed (0.0002495 drift over 50,000 trades).
  4. VND portfolio valuation fails closed when `usd_vnd` is missing -> Confirmed `PortfolioContractError`.
  5. Accounting Capex negative sign convention causes metric rejection in `vietnam_research_tool.py` -> Confirmed.
  6. SQLite concurrent write throughput triggers `database is locked` -> Confirmed under 16 concurrent threads.
  7. Live runner start lock deduplicates parallel requests -> Confirmed (1 started, 19 rejected).
  8. ProviderStreamError classifies transient vs client errors -> Confirmed.
  9. SchedulerKernel exponential backoff caps at max delay without big-int overflow -> Confirmed.
- **Vulnerabilities found**:
  * SQLite concurrency lock starvation: Default `sqlite3.connect` lacks WAL mode and busy timeout, dropping operations under thread contention.
  * Vietnam Research Tool sign expectation: `nonnegative=(1,)` rejects filings that record Capex as negative cash outflows.
  * Float rounding drift in trading engines: Accumulated fee math uses native `float` instead of `Decimal`.
  * FX missing rate for VND in standard external feeds (Frankfurter v1) leaves VND accounts unrateable unless explicit rates are provided.
- **Untested angles**:
  * Live websocket network disconnection under active live order execution.
  * Ultra-large CSV dataset memory consumption (> 1,000,000 rows) in runs detail routes.

## Loaded Skills
- None
