# BAO CAO KHAO SAT TOAN DIEN KIEN TRUC HE THONG VA BAN DO CONG NGHE VIBE-TRADING
(Comprehensive Architectural Exploration & Technology Stack Analysis Report)

- Ma dac vu: explorer_arch_1
- Thu muc lam viec: D:\Vibe-Trading\.agents\teamwork\explorer_arch_1\
- Pham vi kiem toan: Toan bo kho ma nguon Vibe-Trading (Backend FastAPI, Frontend React 19/TS, Swarm DAG Engine, AgentLoop, Live Trading Runner, Portfolio & Paper Trading, Reporting & Document Export, MCP Server, Database Stores, Broker Connectors)
- Ngay hoan thanh: 2026-11-08

---

## 1. OBSERVATION (QUAN SAT THUC TE THEO TRU COT KIEN TRUC)

### 1.1 Executive Architecture Summary (Tom tat Kien truc Cap cao)
He thong Vibe-Trading la mot nen tang nghien cuu tai chinh dinh luong, kiem thu chien luoc (backtesting), tu dong hoa giao dich da thi truong (US, Hong Kong, Trung Quoc Dai Luc, Viet Nam, Brazil, Crypto, Forex) va dieu phoi da dac vu (Multi-Agent Swarm / AgentLoop ReAct).
Kien truc tong the duoc thiet ke theo mo hinh da tang (multi-tier decoupled architecture):
1. **Frontend Presentation Tier**: Ung dung Single Page Application (SPA) viet bang React 19 (19.3.0) + TypeScript 5.7, dong goi boi Vite 8.3.1, su dung React Router 8.4 (Data Router), Zustand 5.0 cho state management, ECharts 6.1 cho bieu do tai chinh, va Tailwind CSS cho styling. Ho tro chay duoi dang Desktop App qua Electron 32.
2. **API & Gateway Tier**: FastAPI (0.104.0+) chay tren Uvicorn (0.24.0+), cung cap RESTful API, Server-Sent Events (SSE) streaming va WebSocket endpoints. Tich hop co che xac thuc qua bearer token/API key, SSE tickets (`/auth/ticket`), loopback host guarding chong DNS rebinding, va he thong MCP Server (FastMCP 2.14+, mcp 1.30+) ho tro 3 loai transport: stdio, SSE va Streamable HTTP (`/mcp`).
3. **Core Business & Agent Intelligence Tier**:
   - `AgentLoop` (ReAct Engine): Quan ly hoi thoai thong minh, quan ly ngu canh 5 tang (Microcompact, Context Collapse, Auto Compact, Compact Tool, Iterative Update), co che xac thuc bang chung tai chinh (Financial Grounding Ledger) va stream suy luan LLM (Reasoning Delta Stream).
   - `Swarm Runtime`: Engine thuc thi do thi co huong khong chu trinh (DAG Multi-Agent Execution) theo cac tang to po (topological layers), song song trong cung mot tang va tuan tu giua cac tang.
   - `Live Trading Engine`: Bo dieu khien thuc thi lenh thuc (Live Runner), duoc bao ve boi he thong kiem soat uy quyen (Mandate Enforcement Engine), chot chan han muc ngay (Daily Count Locks), co che ngat khan cap (Kill Switch / Halt Flag), va cong dat lenh an toan (SDK Order Gate).
   - `Backtest & Quantitative Engine`: Trinh thuc thi chien luoc doc lap (`backtest/runner.py`), tich hop thu vien tai chinh dinh luong `quantlib` (attribution, copula, timeseries, GARCH, factor models, fund math) va he thong trinh nap du lieu da nguon (loaders).
   - `Vibe Report Engine`: Trinh xuat bao cao nghien cuu co ban va dinh luong cao cap (Research Report) sang cac dinh dang DOCX, PPTX va PDF (qua LibreOffice / PDF fallback), kem trinh render bieu do va preview tung trang qua PDFium.
4. **Data Persistence & Storage Tier**:
   - 15 co so du lieu SQLite doc lap theo tung mien nghiep vu (Portfolio, Paper Accounts, Forex, Strategies, Goals, Memory Vector/FTS5, Decision Budget, Research Artifacts, v.v.).
   - He thong luu tru tap tin phan cap (File-based JSON/CSV stores): `runs/<run_id>/` (chua `config.json`, `state.json`, `artifacts/` gom `metrics.csv`, `equity.csv`, `trades.csv`, `positions.csv`, `run_card.json`), `sessions/<session_id>/` (chua `session.json`, `messages.jsonl`, `attempts/`), va cac thu muc runtime duoi `~/.vibe-trading/`.
5. **External Connectivity Tier**:
   - 19 Broker Connectors: Binance, OKX, Alpaca, Interactive Brokers (IBKR), Futu, Tiger, Longbridge, MetaTrader 5 (MT5), Robinhood, Scalable Capital, Trading 212, Upbit, KIS, Toss, Dhan, Shoonya, mStock, Zerodha, eToro.
   - LLM Providers: OpenAI, Anthropic, DeepSeek, Google Gemini, GitHub Copilot SDK, QVeris, OpenRouter, OpenBB.
   - Financial Data APIs: YFinance, CCXT, Tushare, Akshare, Baostock, FRED Macro, Eastmoney, iWencai.
   - Multi-Channel Messaging: Telegram, Discord, Slack, DingTalk, Feishu, WeCom, WeChat (Weixin), WhatsApp, Matrix, Mochat, Microsoft Teams, QQ, Signal, Email (IMAP/SMTP), WebSocket.

---

### 1.2 Complete Technology Stack & Module Map (Ban do Cong nghe va Module)

#### Bang 1: Cong nghe va Thu vien Nen tang

| Phan he | Cong nghe / Thu vien | Phien ban | Vai tro kien truc |
|---|---|---|---|
| **Backend Runtime** | Python | >= 3.11, < 3.14 | Moi truong thuc thi backend chinh |
| **API Framework** | FastAPI, Starlette, Uvicorn | FastAPI >= 0.104, Uvicorn >= 0.24 | Web REST API, Async Event Loop, Middleware |
| **Data Validation** | Pydantic | >= 2.0.0 (v2) | Schema validation, Serializer, Settings Config |
| **Streaming & Events** | sse-starlette, websockets | websockets >= 15.0, sse-starlette >= 1.6 | Server-Sent Events va kenh WebSocket realtime |
| **MCP Protocol** | FastMCP, mcp | fastmcp >= 2.14.0 (<4.0), mcp >= 1.30.0 | Giao thuc Model Context Protocol (87 cong cu) |
| **AI / LLM Orchestration** | LangChain Core, LangGraph | langchain >= 1.3.9, langgraph >= 1.2.5 | Adapter LLM providers va graph checkpointing |
| **Data & Quant Math** | NumPy, SciPy, Pandas, DuckDB | pandas >= 2.0 (<3.0), duckdb >= 1.2, numpy >= 1.24 | Tinh toan ma tran, thong ke, Timeseries, SQL in-memory |
| **Econometrics (Optional)** | statsmodels, arch | statsmodels >= 0.14, arch >= 6.0 | Kiem dinh ADF, Cointegration, mo hinh GARCH |
| **Document Generation** | python-docx, python-pptx, pypdf, pypdfium2, reportlab | python-docx >= 1.1, pypdfium2 >= 4.0, reportlab >= 4.0 | Render van ban DOCX, slide PPTX, PDFium preview, PDF |
| **Plotting / Visuals** | Matplotlib, Pillow | matplotlib >= 3.7.0, Pillow >= 12.2.0 | Xuat anh bieu do tai chinh Agg |
| **Crypto & Broker SDKs** | ccxt, aiohttp, cryptography | ccxt >= 4.5.71, aiohttp >= 3.14.3 | Giao tiep san crypto va cac broker REST/WS |
| **Frontend Runtime** | Node.js | >= 22.22.0 | Moi truong build va dong goi frontend |
| **Frontend Framework** | React, React-DOM | 19.3.0 | Thu vien giao dien nguoi dung (Concurrent React) |
| **Frontend Routing** | react-router | 8.4.0 | Dieu huong SPA, Data Router |
| **State Management** | Zustand | 5.0.15 | Quan ly global state (Agent, Theme, Report preview) |
| **Data Visuals (UI)** | Apache ECharts | 6.1.0 | Bieu do equity curve, heatmap, attribution, options payoff |
| **Styling & Icons** | Tailwind CSS, Lucide-React, Sonner | tailwindcss 3.4.0, lucide-react 1.48, sonner 2.0.8 | Bento-grid UI, Iconography, Toast notifications |
| **Markdown & Math** | react-markdown, remark-gfm, remark-math, rehype-katex | react-markdown 9.0, rehype-katex 7.0 | Render cong thuc Toan LaTeX va van ban Markdown |
| **Desktop App** | Electron | 32.x (desktop/electron) | Dong goi ung dung Desktop tren Windows/macOS/Linux |

---

#### Bang 2: Ban do Chi tiet Module va Package Toan Du an

```
D:\Vibe-Trading\
├── agent\                               # Backend source root (Python)
│   ├── api_server.py                    # FastAPI entrypoint, middleware, assembly
│   ├── mcp_server.py                    # FastMCP Server (87 tools, stdio/sse/http)
│   ├── forex_mcp_server.py              # Forex standalone MCP bridge
│   ├── generate_fpt_report.py           # CLI tool xuat bao cao mau
│   ├── backtest\                        # Engine kiem thu chien luoc
│   │   ├── runner.py                    # Trinh thuc thi chinh cua backtest engine
│   │   ├── metrics.py                   # Tinh Sharpe, Sortino, Calmar, MaxDD, WinRate
│   │   ├── validation.py                # Kiem dinh thong ke, bootstrap, Monte Carlo
│   │   ├── loaders\                     # Registry va loaders nap OHLCV da thi truong
│   │   ├── engines\                     # Cac core engine tinh toan tai san
│   │   └── optimizers\                  # Bo toi uu danh muc (Mean-Variance, Risk Parity)
│   ├── cli\                             # Console CLI interface (vibe-trading)
│   ├── evals\                           # Test cases va harness danh gia agent
│   └── src\                             # Core business logic packages
│       ├── agent\                       # AgentLoop, context management, tool lifecycle
│       │   ├── loop.py                  # Vong lap ReAct chinh (1834 dong)
│       │   ├── context.py               # Xay dung system prompt va inject tools
│       │   ├── context_budget.py        # Can dong token va giam sat tran bo nho context
│       │   ├── context_compact.py       # 5 tang nen ngu canh hoi thoai
│       │   ├── tool_lifecycle.py        # Thuc thi cong cu doc/ghi, threadpool
│       │   └── grounding\               # Kiem chung bang chung tai chinh
│       ├── api\                         # 36 FastAPI route modules & handlers
│       │   ├── security.py              # Xac thuc API key, SSE tickets, CORS, host guard
│       │   ├── models.py                # Pydantic models dung chung (RunResponse, v.v.)
│       │   ├── state.py                 # Singletons quan ly SessionService, ChannelRuntime
│       │   ├── helpers.py               # Path validation, env helpers, directory anchors
│       │   ├── runs_routes.py           # /runs (detail, code, pine, preview, factor)
│       │   ├── live_routes.py           # /live (runner control, mandate commit, halt)
│       │   ├── sessions_routes.py       # /sessions (chat messages, turns, SSE events)
│       │   ├── swarm_routes.py          # /swarm (runs, presets, tasks, DAG events)
│       │   ├── portfolio_routes.py      # /api/portfolio (snapshot, sync, history, FX)
│       │   ├── paper_trade_routes.py    # /api/paper-accounts, /api/paper-trade/step
│       │   ├── reports_routes.py        # /api/reports (export jobs, preview PDFium)
│       │   ├── research_routes.py       # /api/research (vietnam, crypto, dcf)
│       │   ├── forex_routes.py          # /api/forex (experiments, runners, accounts)
│       │   ├── alpha_routes.py          # /api/alpha (zoo factor formulas, bench)
│       │   ├── options_routes.py        # /options (chains, pricing, payoff)
│       │   └── channels_routes.py       # /channels (pairing, messaging runtime)
│       ├── swarm\                       # Multi-Agent Swarm DAG orchestrator
│       │   ├── runtime.py               # SwarmRuntime, topological scheduler
│       │   ├── worker.py                # SwarmWorker, thuc thi sub-task doc lap
│       │   ├── store.py                 # SwarmStore luu run.json va task.json
│       │   ├── presets.py               # Load cac preset mau tu file YAML
│       │   └── models.py                # SwarmRun, SwarmTask, RunStatus models
│       ├── portfolio\                   # Quan ly danh muc, FX va vi tien
│       │   ├── service.py               # PortfolioService, tinh toan balance, PnL
│       │   ├── store.py                 # PortfolioStore (portfolio.sqlite3)
│       │   ├── fx.py                    # Ty gia ngoai te va quy doi tien te
│       │   └── imports.py               # Import CSV sao ke tai khoan
│       ├── live\                        # Live Trading & Mandate Enforcement
│       │   ├── order_guard.py           # MCP tool gate chan lenh
│       │   ├── sdk_order_gate.py        # Gate chan lenh cho Direct-SDK brokers
│       │   ├── enforcement.py           # Kiem tra gioi han mandate, notional cap
│       │   ├── halt.py                  # Kill switch logic (halt.flag)
│       │   ├── daily_count.py           # Dem so lenh trong ngay, file lock
│       │   └── runtime\                 # Live Runner execution loop, scheduler
│       ├── trading\                     # Connector adapters va order routing
│       │   ├── service.py               # TradingService, dang ky 19 connectors
│       │   ├── connectors\              # 19 broker connectors (binance, okx, ibkr, ...)
│       │   └── forex\                   # Forex execution store va pending orders
│       ├── tools\                       # 105 tools (market research, macro, filings, v.v.)
│       │   ├── backtest_tool.py         # Goi subprocess chay backtest engine
│       │   ├── paper_trade\             # Paper trading deterministic matching engine
│       │   └── vietnam_*.py             # Phan tich co phieu VN, DCF, comparables
│       ├── reporting\                   # Branded Document Generation Engine
│       │   ├── renderer.py              # Export DOCX, PPTX, PDF
│       │   ├── service.py               # ReportJobService, job staging
│       │   └── schema.py                # ResearchReport Pydantic schema
│       ├── session\                     # Quan ly phien hoi thoai nguoi dung
│       │   ├── service.py               # SessionService, attempt lifecycle
│       │   ├── store.py                 # Luu tru phien tren he thong file
│       │   ├── events.py                # EventBus SSE streaming pub/sub
│       │   └── search.py                # FTS5 full-text search SQLite
│       ├── providers\                   # LLM providers (chat.py, llm.py, capabilities.py)
│       ├── quantlib\                    # 20 module toan tai chinh cap cao
│       ├── channels\                    # 17 adapter kenh chat ngoai vi (Telegram, Discord, ...)
│       ├── strategy_store\              # Luu tru artifact chien luoc (sqlite_store.py)
│       └── shadow_account\              # Shadow trading backtest va attribution
├── frontend\                            # Web Frontend source root (React/TypeScript)
│   ├── package.json                     # Dependencies, scripts (Vite, React 19)
│   ├── vite.config.ts                   # Cau hinh Vite, dev proxy, build settings
│   └── src\
│       ├── main.tsx                     # React root mount, theme provider
│       ├── router.tsx                   # React Router v8 configuration
│       ├── lib\
│       │   ├── api.ts                   # Massive API client wrapper (2361 dong)
│       │   ├── apiAuth.ts               # Token authentication helpers
│       │   ├── formatters.ts            # Dinh dang so, ty le phan tram, tien te
│       │   └── research.ts              # Types va validate hop dong research
│       ├── stores\
│       │   ├── agent.ts                 # Zustand store quan ly chat va SSE
│       │   └── reportPreview.ts         # Zustand store quan ly preview bao cao
│       ├── pages\                       # 17 trang chuc nang (Agent, Portfolio, Reports, ...)
│       └── components\                  # Component giao dien theo tung nhom chuc nang
└── desktop\electron\                    # Electron desktop packaging container
```

---

#### Bang 3: Danh muc 15 Co so Du lieu SQLite trong He thong

| # | File Database | Module so huu | Muc dich luu tru | Bang du lieu chinh |
|---|---|---|---|---|
| 1 | `portfolio/portfolio.sqlite3` | `agent/src/portfolio/store.py` | Luu tru snapshot danh muc bat bien va cache ty gia FX | `portfolio_snapshots`, `portfolio_fx_quotes`, `portfolio_fx_cache` |
| 2 | `portfolio/imports.sqlite3` | `agent/src/portfolio/imports.py` | Luu tru file sao ke CSV va danh muc nhap ngoai | `imports` |
| 3 | `paper-trading/accounts.db` | `agent/src/tools/paper_trade/accounts.py` | So cai tai khoan giao dich giay (optimistic concurrency) | `accounts`, `steps` |
| 4 | `sessions.db` | `agent/src/session/search.py` | Chi muc tim kiem toan van FTS5 lich su chat | `sessions`, `messages`, `messages_fts` |
| 5 | `memory/memory.db` | `agent/src/memory/search_index.py` | Chi muc FTS5 tri nho dai han cua Agent | `memories`, `memories_fts` |
| 6 | `strategy_store.db` | `agent/src/strategy_store/sqlite_store.py` | Luu tru artifacts alpha, chien luoc va ket qua bench | `artifacts`, `bench_results` |
| 7 | `evidence.db` | `agent/src/strategy_discovery/evidence_store.py` | Luu tru bang chung thuc nghiem cua chien luoc | `evidence_rows` |
| 8 | `<broker>/runtime/decisions.sqlite3` | `agent/src/live/runtime/decision_budget.py` | Gioi han chi tieu token/chi phi va nhat ky quyet dinh Live | `settings`, `decisions`, `usage` |
| 9 | `forex/execution.db` | `agent/src/trading/forex/store.py` | Nhat ky lenh Forex, trang thai intent va ket noi broker | `connections`, `intents`, `executions` |
| 10 | `goals.db` | `agent/src/goal/store.py` | Luu tru cay muc tieu nghien cuu (Goals Tree) | `goals`, `milestones`, `evidence` |
| 11 | `research_artifacts.db` | `agent/src/research_artifacts/store.py` | So cai manifest bang chung nghien cuu da duyet | `manifests`, `attempts` |
| 12 | `pixel_office.db` | `agent/src/pixel_agents/office.py` | Trang thai va dac vu trong Pixel Office | `agents`, `tasks` |
| 13 | `taiwan_stock.db` | `agent/src/tools/taiwan_stock_data_tool.py` | Cache snapshot du lieu co phieu Dai Loan | `tw_stock_bars`, `metadata` |
| 14 | `crypto_derivatives.db` | `agent/src/tools/crypto_derivatives_archive.py` | Luu tru lich su open interest va funding rate crypto | `observations`, `instruments` |
| 15 | `br_data/market.db` | `agent/src/br_data/store.py` | Cache du lieu chung khoan Brazil | `br_market_bars`, `sync_status` |

---

### 1.3 End-to-End Data Flow Matrix (Ma tran Luong Du lieu Dau-Cuoi)

```
+---------------------------------------------------------------------------------------------------------+
|                                  MA TRAN LUONG DU LIEU TOAN HE THONG                                    |
+-------------------+--------------------+------------------------+-------------------+-------------------+
| Hanh dong UI (1)  | Client API (2)     | FastAPI Route (3)      | Core Service (4)  | DB / External (5) |
+-------------------+--------------------+------------------------+-------------------+-------------------+
| 1. Commit Mandate | api.commitMandate  | POST /mandate/commit   | commit_mandate()  | live/<broker>_    |
| (Phe duyet lenh)  | (api.ts:861)       | (live_routes.py:1005)  | (live/mandate/)   | mandate.json      |
+-------------------+--------------------+------------------------+-------------------+-------------------+
| 2. Start Live     | api.startLiveRunner| POST /live/runner/start| _drive_runner()   | Live Runner Task  |
| Runner (Giao dich)| (api.ts:889)       | (live_routes.py:1389)  | (live_routes.py)  | -> Broker SDK/API |
+-------------------+--------------------+------------------------+-------------------+-------------------+
| 3. Chay Backtest  | Agent Chat / Tool  | POST /sessions/{id}/msg| BacktestTool      | Subprocess Runner |
| (Kiem thu chien)  | (api.ts:793)       | (sessions_routes:793)  | (backtest_tool.py)| -> runs/<id>/csv  |
+-------------------+--------------------+------------------------+-------------------+-------------------+
| 4. Khoi chay Swarm| api.createSwarmRun | POST /swarm/runs       | SwarmRuntime      | swarm/runs/run.js |
| (DAG Multi-Agent) | (api.ts:744)       | (swarm_routes.py:91)   | (runtime.py:339)  | -> Parallel LLMs  |
+-------------------+--------------------+------------------------+-------------------+-------------------+
| 5. Paper Trade    | api.advanceAccount | POST /api/paper-       | PaperAccounts     | paper-trading/    |
| (Buoc giao dich)  | (api.ts:982)       | accounts/{id}/advance  | .advance()        | accounts.db       |
+-------------------+--------------------+------------------------+-------------------+-------------------+
| 6. Xuat Bao cao   | api.exportReport   | POST /api/reports/jobs | ReportJobService  | report_jobs/json  |
| (PDF/DOCX/PPTX)   | (api.ts:1015)      | (reports_routes.py:37) | (service.py:45)   | -> LibreOffice    |
+-------------------+--------------------+------------------------+-------------------+-------------------+
| 7. Chat Truc tiep | api.sendMessage    | POST /sessions/{id}/msg| AgentLoop.run()   | messages.jsonl    |
| (SSE Streaming)   | (api.ts:802)       | -> GET /events (SSE)   | (loop.py:650)     | -> LLM API Stream |
+-------------------+--------------------+------------------------+-------------------+-------------------+
```

#### Chi tiet Luong 1: Uy quyen va Thuc thi Giao dich That (Live Trade Execution)
1. **Frontend**: Nguoi dung tro chuyen trong giao dien `Agent.tsx`. AgentLoop goi cong cu `propose_mandate_tool`, tra ve cau truc de xuat uy quyen. Frontend hien thi the `MandateProposalCard.tsx`.
2. **Tuong tac UI**: Nguoi dung chon phuong an (`selected_ordinal`), tick dong y (`consent_ack = true`), chon tai khoan (`account_ref`), va nhan nut "Authorize & Commit".
3. **API Client**: `frontend/src/lib/api.ts` goi `api.commitMandate(payload)` gui yeu cau toi backend.
4. **FastAPI Route**: `agent/src/api/live_routes.py:1005` (`POST /mandate/commit`) tiep nhan:
   - Kiem tra quyen `require_auth`.
   - Goi `src.trading.accounts.choose_account` kiem tra tai khoan hop le.
   - Goi `src.live.mandate.commit.commit_mandate()`.
5. **Core Service & Luu tru**:
   - `commit_mandate()` ghi file `~/.vibe-trading/live/<broker>_mandate.json` va tao chung chi xac thuc ky so.
   - Phat su kien `mandate.committed` vao SSE EventBus qua `_emit_live_event()`.
6. **Khoi dong Live Runner**: Nguoi dung nhan "Start Runner" tren UI -> `api.startLiveRunner(broker)` -> `POST /live/runner/start` (`live_routes.py:1389`).
7. **Execution Loop & Broker Gate**:
   - Khoi tao `runner = _build_live_runner(broker)`.
   - Khoi tao task ngam: `asyncio.ensure_future(_drive_runner(runner))`.
   - Trong vong lap `runner.run_loop()`, khi co tin hieu dat lenh: goi `execute_live_order()` trong `agent/src/live/sdk_order_gate.py:62`.
   - Kiem tra 6 buoc: Mandate con han? Kill switch bat khong (`halt_flag_set`)? Notional hop le? Lay khoa dem lenh `daily_order_lock`?
   - Neu ALLOW: goi `connector_module.place_order(config, **place_kwargs)`.
8. **External Broker**: Connector tuong ung (Alpaca REST API, Binance CCXT, OKX WebSocket, IBKR TWS Bridge) thuc thi dat lenh toi san giao dich. Ket qua duoc ghi vao audit log `write_live_action()` va phat qua SSE `live.action`.

---

#### Chi tiet Luong 2: Kiem thu Chien luoc Tai chinh (Backtesting Flow)
1. **Frontend**: Nguoi dung yeu cau backtest trong chat hoac kich hoat playbook trong Scheduled.
2. **Agent / API**: Agent goi `backtest_tool` (`agent/src/tools/backtest_tool.py:193`).
3. **Validation & Sandbox Execution**:
   - Kiem tra ton tai cua `config.json` va `code/signal_engine.py` tai thu muc `runs/<run_id>/`.
   - `Runner.execute()` khoi chay mot process Python doc lap: `python agent/backtest/runner.py runs/<run_id>`.
4. **Data Loading & Simulation**:
   - `backtest/runner.py` doc cau hinh, xac dinh loader tuong ung (`yfinance`, `okx`, `tushare`, `akshare`, `baostock`).
   - Nap du lieu gia lich su (OHLCV), nap tap tin chien luoc `signal_engine.py` va tinh toan tin hieu vao/ra lenh.
   - Tinh toan bien dong tai san, slippage, phi giao dich, drawdown, Sharpe ratio trong `backtest/metrics.py`.
5. **Persistence of Artifacts**:
   - Luu ket qua xuong dia tai `runs/<run_id>/artifacts/`:
     * `metrics.csv`: cac chi so tai chinh chinh.
     * `equity.csv`: chuoi gia tri tai san theo thoi gian.
     * `trades.csv`: nhat ky khop lenh chi tiet.
     * `positions.csv`: ty trong nam giu theo ngay.
     * `run_card.json`: bang tong hop xac thuc Trust Layer.
     * `state.json`: trang thai hoan tat (ghi boi `RunStateStore`).
6. **UI Presentation**:
   - Nguoi dung mo trang `RunDetail.tsx`.
   - Frontend goi `api.getRun(runId)` (`GET /runs/{id}`).
   - Backend `agent/src/api/runs_routes.py:974` doc cac file artifacts va tra ve payload `RunResponse`.
   - UI render bieu do tuong tac bang Apache ECharts (`EquityChart`, `AttributionTab`, `ValidationPanel`).

---

#### Chi tiet Luong 3: Xuat Bao cao Nghien cuu (Branded Research & Document Export)
1. **Frontend / Agent**: Nguoi dung tai trang `Reports.tsx` hoac Agent goi `export_research_report`.
2. **API Endpoint**: `POST /api/reports/jobs` (`agent/src/api/reports_routes.py:37`).
3. **Core Reporting Service**:
   - `ReportJobService.create_job()` (`agent/src/reporting/service.py:45`):
     * Kiem tra tinh hop le cua schema `ResearchReport` (Pydantic).
     * Kiem chung nguon trich dan bang chung qua `validate_report_evidence()`.
     * Luu metadata job tai `~/.vibe-trading/report_jobs/<job_id>.json`.
4. **Document Rendering (`renderer.py`)**:
   - Docx: Tao van ban tieu chuan bao chi tai chinh bang `python-docx` voi bang bieu va typography thuong hieu.
   - Charts: Render cac bieu do chat luong cao qua Matplotlib Figure OOP (`FigureCanvasAgg`).
   - Pptx: Tao slide thuyet trinh qua `python-pptx`.
   - PDF: Chuyen doi tu DOCX sang PDF qua LibreOffice headless (`soffice --headless --convert-to pdf`), hoac su dung engine du phong thuan Python `reportlab` neu server thieu LibreOffice.
5. **Artifact Publishing & Preview**:
   - `publish_report_artifact()` dang ky file xuat ra tai thu muc luu tru artifact.
   - Nguoi dung xem truoc tren UI: `GET /api/reports/{id}/preview/{page_index}` doc file PDF qua `pypdfium2`, render bitmap va tra ve anh PNG 1200px voi lock serialized tranh race condition.

---

### 1.4 Architectural Vulnerabilities & Design Bottlenecks (Cac Lo hong Kien truc va Diem nghen Thiet ke)

Qua ra soat doc lap toan bo ma nguon, da xac dinh cac diem nghen va lo hong thiet ke kien truc voi vi tri file va dong cu the nhu sau:

#### Lo hong 1: Anti-pattern `_host()` va Circular Coupling giua `api_server` va Route Modules
- **Vi tri**:
  * `agent/src/api/live_routes.py:344-347, 992-997`
  * `agent/src/api/settings_routes.py:219-221`
  * `agent/src/api/qveris_routes.py:66-68`
  * `agent/src/api/channels_config_routes.py:115-117`
- **Quan sat thuc te**:
  Cac route module con truy cap cac dependency dung chung bang cach goi:
  ```python
  def _host() -> Any:
      return _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")
  ```
  Sau do goi truc tiep cac bien global tren `api_server`:
  `_host()._runner_tasks`, `_host()._get_session_service()`, `_host()._live_broker_adapter()`.
  Dong thoi, `api_server.py` lai import tat ca cac route module nay (`from src.api.live_routes import register_live_routes`).
- **Hau qua kien truc**:
  Tao ra su phu thuoc vong (circular coupling) va vi pham nguyen tac Inversion of Control. Cac route module khong the duoc kiem thu doc lap (isolated unit test) hoac tai su dung boi ung dung khac neu khong co file `api_server.py` nam san trong `sys.modules`. Khi chay unit test cho rieng `live_routes.py`, `_host()` tra ve `None`, gay loi runtime ngay lap tuc.

---

#### Lo hong 2: Crash va Deadlock khi Huy Swarm Run mo coi sau Server Restart
- **Vi tri**:
  * `agent/src/swarm/runtime.py:403-412`
  * `agent/src/api/swarm_routes.py:231-238`
- **Quan sat thuc te**:
  Trong `agent/src/swarm/runtime.py:405-407`:
  ```python
  # Orphaned run recovery after server restart
  try:
      run = self._store.get_run(run_id)
      if run is not None and run.status in (SwarmRunStatus.running, SwarmRunStatus.pending):
          run.status = SwarmRunStatus.cancelled
          self._store.save_run(run)
          return True
  except Exception as exc:
      logger.warning("Failed to cancel orphaned run %s: %s", run_id, exc)
  ```
  Trong khi do:
  1. Class `SwarmStore` trong `agent/src/swarm/store.py` **khong co phuong thuc nao ten la `get_run()`**, phuong thuc thuc te la `load_run(run_id)`.
  2. Module `agent/src/swarm/runtime.py` **khong he import `SwarmRunStatus`** (chi import `RunStatus` tai dong 31).
- **Hau qua kien truc**:
  Khi server bi khoi dong lai trong khi mot Swarm Run dang chay, `_cancel_events` trong RAM bi mat. Khi nguoi dung bam nut "Cancel Run" tren UI, backend goi `runtime.cancel_run(run_id)`. Doan code khoi phuc nem ngay `AttributeError: 'SwarmStore' object has no attribute 'get_run'` (hoac `NameError: name 'SwarmRunStatus' is not defined`), bi catch boi khoi except va log warning roi tra ve `False`.
  API `POST /swarm/runs/{run_id}/cancel` nhan ket qua `False` va nem `HTTPException(404, "No active run")`.
  Run mai mai bi ket o trang thai `running`, dong thoi API retry chan vi `status == running` khong cho retry. Nguoi dung bi khoa cung khong the thoat hay chay lai preset.

---

#### Lo hong 3: Blocking Synchronous I/O tren FastAPI Event Loop tai cac Route `async def`
- **Vi tri**:
  * `agent/src/api/sessions_routes.py:422-438, 441-455, 826-845`
  * `agent/src/api/runs_routes.py:881-899, 902-918`
  * `agent/src/api/swarm_routes.py:110-135`
- **Quan sat thuc te**:
  FastAPI co co che xu ly bat dong bo: neu mot route duoc khai bao la `def` thong thuong, FastAPI se tu dong day viec thuc thi vao threadpool rieng (`run_in_threadpool`). Tuy nhien, neu mot route duoc khai bao la `async def`, FastAPI se thuc thi no truc tiep tren Main Event Loop cua process.
  Cac route sau day duoc khai bao `async def` nhung lai goi I/O tap tin dong bo truc tiep:
  1. `sessions_routes.py:422`: `async def list_sessions(...)` goi `svc.list_sessions()` quet toan bo thu muc `sessions/` bang `Path.iterdir()` va doc cac file JSON.
  2. `sessions_routes.py:826`: `async def get_messages(...)` doc tung dong cua file `messages.jsonl` dong bo tren dia.
  3. `runs_routes.py:881`: `async def get_run_code(...)` goi `p.read_text(encoding="utf-8")`.
  4. `runs_routes.py:902`: `async def get_run_pine(...)` goi `pine_path.read_text(encoding="utf-8")`.
  5. `swarm_routes.py:111`: `async def list_swarm_runs(...)` quet thu muc runs va goi `reconcile_run(r, write=True)` ghi truc tiep xuong dia tren Main Event Loop.
- **Hau qua kien truc**:
  Event loop bi phong toa (stalled) trong thoi gian thuc hien disk I/O. Khi co nhieu nguoi dung cung luc hoac khi o dia cham, tat ca cac luong streaming Server-Sent Events (SSE) va WebSocket connection se bi ngat quang, gay giat lag nghiem trong cho UI.

---

#### Lo hong 4: Thread Safety Hazard voi Matplotlib State Machine toan cuc trong Shadow Reporting
- **Vi tri**:
  * `agent/src/shadow_account/reporter.py:187-204, 210-232, 250-265`
- **Quan sat thuc te**:
  Trong `agent/src/shadow_account/reporter.py`:
  ```python
  import matplotlib.pyplot as plt
  fig, ax = plt.subplots(figsize=(8, 3), dpi=150)
  ...
  fig.savefig(path, bbox_inches="tight")
  plt.close(fig)
  ```
  `matplotlib.pyplot` la mot state machine toan cuc (global state machine).
- **Hau qua kien truc**:
  Khi co 2 yeu cau phan tich shadow account hoac backtest chay dong thoi tren cac luong worker khac nhau cua threadpool, ca hai luong deu thao tac tren doi tuong figure toan cuc hien tai. Dan toi hinh anh bieu do cua yeu cau A bi ve de sang bieu do cua yeu cau B, hoac nem ngoai le runtime `ValueError: canvas is already being drawn` lam crash tien trinh xuat bao cao.
  (Trong khi do, module `src/reporting/renderer.py` da duoc chuyen sang OOP Figure `Figure()` va `FigureCanvasAgg` an toan).

---

#### Lo hong 5: Treo Luong vo han (Unbounded Thread Wait) trong Tool Lifecycle Execution
- **Vi tri**:
  * `agent/src/agent/tool_lifecycle.py:519-528`
- **Quan sat thuc te**:
  Khi thuc thi song song cac cong cu readonly trong AgentLoop:
  ```python
  with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(runnable), 8)) as pool:
      futures = [pool.submit(copy_context().run, _run, item) for item in runnable]
      results = []
      for i, f in enumerate(futures):
          try:
              results.append(f.result())
          except Exception as exc: ...
  ```
  Loi goi `f.result()` **hoan toan khong co tham so timeout** (`f.result(timeout=...)`).
- **Hau qua kien truc**:
  Neu mot tool ngoai vi bi treo do socket bi drop ma khong co keep-alive, deadlock trong database, hoac subprocess bi block I/O, loi goi `f.result()` se treo vo han. Khoi `with ThreadPoolExecutor` se khong the thoat ra, khoa cung luong AgentLoop cua phien lam viec do va lam ro ri luong worker trong he dieu hanh.

---

#### Lo hong 6: Thieu Bao ve Race Condition khi Dynamic Tool Discovery tren nhieu Luong
- **Vi tri**:
  * `agent/src/tools/__init__.py:42-73`
- **Quan sat thuc te**:
  Trong `_discover_subclasses()`:
  ```python
  global _SUBCLASSES_CACHE, _DISCOVERY_FAILURES
  if _SUBCLASSES_CACHE is not None:
      return _SUBCLASSES_CACHE
  ...
  for _, module_name, _ in pkgutil.iter_modules([pkg_dir]):
      importlib.import_module(f"src.tools.{module_name}")
  ...
  _SUBCLASSES_CACHE = classes
  ```
  Bien toan cuc `_SUBCLASSES_CACHE` va `_DISCOVERY_FAILURES` duoc doc va ghi ma **khong co bat ky `threading.Lock` nao bao ve**.
- **Hau qua kien truc**:
  Khi he thong vua khoi dong va co nhieu phien chat hoac API request den dong thoi cung mot thoi diem, nhieu luong se cung luc chay vao `pkgutil.iter_modules`, gay xung dot import (import collision), ghi de tu dien loi va lam mat mat mot so tool duoc dang ky trong registry.

---

#### Lo hong 7: Ro ri Bo nho do Tich luy Buffer EventBus va WebSocket khong gioi han TTL
- **Vi tri**:
  * `agent/src/session/events.py:79, 101-106, 289-293`
  * `agent/src/channels/websocket.py:1094-1110`
- **Quan sat thuc te**:
  1. Trong `agent/src/session/events.py`: `self._buffers[session_id]` tich luy toi 500 su kien cho moi session. Khi subscriber ngat ket noi (khoi `finally:` tai dong 289-293), chi co queue cua subscriber duoc go bo khoi `_subscribers`, nhung ban ghi trong `self._buffers[session_id]` **khong bao gio duoc don dep** tru khi nguoi dung gui request xoa phien `DELETE /sessions/{id}`.
  2. Trong `agent/src/channels/websocket.py`: `self._stream_text_buffers.setdefault(stream_key, []).append(delta)` chi duoc pop khi nhan su kien `_stream_end`. Neu client dot ngot ngat ket noi hoac LLM bi crash giua chung truoc khi kip ban `_stream_end`, buffer van nam nguyen trong RAM.
- **Hau qua kien truc**:
  Sau hang nghin luot tuong tac chat, bo nho RAM cua server tang dan deu dan (memory leak), khong the thu hoi boi Garbage Collector.

---

#### Lo hong 8: Tieu ton RAM khong kiem soat khi nap Artifacts Backtest trong RunResponse
- **Vi tri**:
  * `agent/src/api/models.py:78-86`
  * `agent/src/api/runs_routes.py:756-799`
- **Quan sat thuc te**:
  Moi khi nguoi dung truy van chi tiet mot Run (`GET /runs/{id}`), backend tu dong nap dong thoi 5 file CSV (`equity.csv`, `metrics.csv`, `trades.csv`, `positions.csv`, `target_positions.csv`) voi gioi han 5.000 dong/file vao RAM duoi dang cac Python `dict` va gan vao `RunResponse`.
- **Hau qua kien truc**:
  Moi request co the nap toi 25.000 dictionary object vao RAM chi de tra ve mot payload JSON khong lo qua HTTP, mac du phan lon giao dien frontend chi can xem thong tin tong quan va bieu do Preview. Gay qua tai bo nho va ap luc thu gom rac (GC pressure) khi co nhieu luot xem run cung luc.

---

#### Lo hong 9: Thieu Error Boundary cap con tren React Router gay Crash Layout toan ung dung
- **Vi tri**:
  * `frontend/src/router.tsx:92-118`
- **Quan sat thuc te**:
  Trong `router.tsx`, chi co route goc cap cha moi duoc gan `errorElement: <RouteErrorFallback />`. Cac route con ben trong (`/runs/:runId`, `/forex`, `/research`, `/reports`, `/paper-trading`, `/portfolio`) khong he co `errorElement` rieng.
- **Hau qua kien truc**:
  Khi mot component ben trong trang con bi loi (vi du: ECharts crash do du lieu null hoac loi toFixed/TypeError), loi se noi bot (bubble up) len tan root route. Toan bo Layout gom Sidebar, Thanh dieu huong, Va Header bi go bo (unmount), thay the bang mot trang loi trong tron. Nguoi dung bi mat hoan toan kha nang dieu huong va bat buoc phai tai lai toan bo trang web bang F5.

---

#### Lo hong 10: Endpoint API nhan truc tiep Raw `dict` ma khong qua Pydantic Schema Validation
- **Vi tri**:
  * `agent/src/api/research_routes.py:111, 138, 143`
  * `agent/src/api/paper_trade_routes.py:69`
  * `agent/src/api/swarm_routes.py:92`
- **Quan sat thuc te**:
  Cac endpoint sau day khai bao tham so dau vao la `payload: dict` hoac `body: dict` thuan tuy:
  * `POST /api/research/vietnam/dcf` (`research_routes.py:111`)
  * `POST /api/research/vietnam/reverse-dcf` (`research_routes.py:138`)
  * `POST /api/research/crypto/basis` (`research_routes.py:143`)
  * `POST /api/paper-trade/step` (`paper_trade_routes.py:69`)
  * `POST /swarm/runs` (`swarm_routes.py:92`)
- **Hau qua kien truc**:
  Bo qua hoan toan co che tu dong validate kieu du lieu, kiem tra do dai, gioi han bien tren duoi cua FastAPI/Pydantic. Ke tan cong hoac client loi co the truyen payload khong lo lam tran bo nho hoac truyen cac gia tri am, gay loi toan hoc (ArithmeticError / ZeroDivisionError) o tang sau.

---

#### Lo hong 11: Thieu Lifecycle Hook dong ket noi SQLite tren cac Singleton Stores
- **Vi tri**:
  * `agent/src/goal/store.py:118` (`GoalStore`)
  * `agent/src/strategy_store/sqlite_store.py:146` (`SqliteStrategyStore`)
  * `agent/src/br_data/store.py:132` (`init_db`)
- **Quan sat thuc te**:
  Cac lop `GoalStore` va `SqliteStrategyStore` khoi tao mot ket noi SQLite duy nhat `self._conn = sqlite3.connect(...)` khi khoi tao instance nhung **khong he cung cap phuong thuc `close()`** de dong ket noi khi dung xong. Dong thoi trong `agent/api_server.py`, lifespan handler (`_lifespan`) khong he dang ky teardown cho cac store nay.
  Tai `agent/src/br_data/store.py:132`, cú phap `with sqlite3.connect(target) as conn:` chi quan ly transaction, khong goi `conn.close()`.
- **Hau qua kien truc**:
  Tren he dieu hanh Windows, cac file handle cua SQLite bi giu chat trong suot vong doi tien trinh. Khi can don dep, di chuyen thu muc, hoac backup co so du lieu se gap loi `sqlite3.OperationalError: database is locked` hoac `PermissionError: The process cannot access the file because it is being used by another process`.

---

## 2. LOGIC CHAIN (CHUOI SUY LUAN CHUNG MINH KIEN TRUC)

Chuoi suy luan tu cac quan sat thuc te den cac ket luan kien truc:

1. **Tu Anti-pattern `_host()` den Rui ro Phan ra Module**:
   - *Quan sat*: `live_routes.py`, `settings_routes.py`, `qveris_routes.py` deu goi `_host()` tim module `api_server` trong `sys.modules`.
   - *Lap luan*: Khi mot he thong can phan tach thanh microservices hoac chay rieng le mot worker (nhu chay live runner doc lap khoi web server), cac module route khong the tach roi khoi `api_server`. Dieu nay chung minh he thong dang bi kien truc ngam (hidden tight coupling), can duoc chuyen doi sang Dependency Injection.

2. **Tu `get_run` vs `load_run` den Su sup do co che Phuc hoi Swarm**:
   - *Quan sat*: `runtime.py:405` goi `self._store.get_run()` va tham chieu `SwarmRunStatus`.
   - *Lap luan*: `SwarmStore` chi co `load_run()`. Khi server gap su co hoac khoi dong lai, tat ca cac Swarm Run dang do dang se khong the duoc cancel boi nguoi dung do loi AttributeError bi nuot. Dieu nay chung to thieu kiem thu hoi quy (regression tests) cho kich ban crash recovery cua Swarm.

3. **Tu `async def` den Ngen Main Event Loop**:
   - *Quan sat*: `list_sessions`, `get_messages`, `list_swarm_runs` duoc dinh nghia bang `async def` nhung goi truc tiep doc/ghi file dong bo ma khong co `run_in_threadpool`.
   - *Lap luan*: Trong mo hinh Event-Driven cua Node.js hoac Python Asyncio, viec giu Event Loop bang mot tac vu I/O dia dong bo se phong toa toan bo cac tac vu bat dong bo khac. Nguoi dung dang nghe SSE stream se cam thay text bi ngung giat cuc moi khi co ai do refresh danh sach phien chat hoac runs.

4. **Tu `matplotlib.pyplot` den Race Condition Hinh anh**:
   - *Quan sat*: `shadow_account/reporter.py` goi `plt.subplots()` va `plt.close()`.
   - *Lap luan*: Matplotlib duy tri mot bien toan cuc cho figure hien tai. Khi hai request backtest shadow duoc xu ly song song tren threadpool, mot luong se goi `plt.close()` trong khi luong kia dang ghi xuong dia, dan den loi mat bieu do hoac sai lech hinh anh giua cac bao cao.

5. **Tu Buffer EventBus den Ro ri Tai nguyen RAM**:
   - *Quan sat*: `EventBus._buffers` khong bao gio bi xoa tru khi co request xoa phien.
   - *Lap luan*: Cac phien hoi thoai thuc te co the keo dai hoac duoc tao moi thuong xuyen. Viec giu lai 500 su kien cho moi phien trong bien toan cuc cua tien trinh API khien bo nho tieu thu tang tuyen tinh theo thoi gian van hanh (O(N) memory growth), gay suy giam hieu nang cua may chu.

---

## 3. CAVEATS (CAC GIOI HAN VA PHAM VI CHUA KHAO SAT)

1. **Cac Broker phu thuoc phan cung / OS chuyen biet**:
   - Module `mt5` chi ho tro tren he dieu hanh Windows khi co san terminal MetaTrader 5 dang chay noi bo.
   - Module `ibkr` su dung `ib_async` yeu cau cong ket noi TWS hoac IB Gateway dang mo (cong 7496/7497/4001/4002).
   - Cac module nay duoc thiet ke fallback an toan (graceful degradation) va khong gay anh huong den runtime co ban neu thieu dependencies.
2. **Kha nang mo rong co so du lieu**:
   - Hien tai toan bo 15 co so du lieu deu la SQLite cuc bo. Kien truc nay phu hop tuyet voi cho moi truong desktop, edge, hoac may chu don le (single-instance). Neu he thong can mo rong theo chieu ngang (multi-replica horizontal scaling), cac SQLite database can duoc gom nhom hoac di chuyen sang PostgreSQL/MySQL nhu dinh huong tieu chuan cua anh Tu.
3. **Moi truong LibreOffice cho PDF Engine**:
   - Viec xuat PDF co do trung thuc cao (high fidelity) phu thuoc vao binary `soffice` cua LibreOffice cai dat tren he dieu hanh host. He thong da co ban fallback `reportlab` thuan Python, nhung chat luong trinh bay PDF cua fallback don gian hon so voi ban in LibreOffice.

---

## 4. CONCLUSION & CONCRETE RECOMMENDATIONS (KET LUAN VA KHUYEN NGHI KIEU MAU)

### Bang Tong hop Khuyen nghi theo Muc do Uu tien

| Ma ID | Phan loai | Vi tri Module | Muc do | Bien phap khac phuc de xuat |
|---|---|---|---|---|
| **REC-01** | Kien truc / Bug | `agent/src/swarm/runtime.py:405-407` | **CRITICAL** | Sua `self._store.get_run()` thanh `self._store.load_run()`, import `RunStatus` thay vi `SwarmRunStatus`. |
| **REC-02** | Hieu nang / Event Loop | `agent/src/api/sessions_routes.py:422, 826` | **HIGH** | Bọc cac loi goi I/O dia trong `run_in_threadpool(_sync_func, ...)` hoac chuyen route ve `def` thong thuong. |
| **REC-03** | Concurrency / Thread-Safe | `agent/src/shadow_account/reporter.py:187-250` | **HIGH** | Chuyen toan bo tu `matplotlib.pyplot` sang OOP Figure API: `Figure()` va `FigureCanvasAgg`. |
| **REC-04** | UI Architecture / Crash | `frontend/src/router.tsx:92-118` | **HIGH** | Bo sung `errorElement: <RouteErrorFallback />` cho tung route con de ngan chan unmount Layout. |
| **REC-05** | Kien truc / Decoupling | `agent/src/api/*_routes.py` & `api_server.py` | **HIGH** | Loai bo `_host()`. Su dung FastAPI Dependency Injection (`Depends`) truyen state va config. |
| **REC-06** | Concurrency / Hang | `agent/src/agent/tool_lifecycle.py:524` | **MEDIUM** | Dat `timeout=tool_timeout` cho `f.result()` va bao ve executor shutdown khong bi treo. |
| **REC-07** | Thread Safety / Discovery | `agent/src/tools/__init__.py:42-73` | **MEDIUM** | Bo sung `threading.Lock()` bao boc qua trinh quet va cache `_SUBCLASSES_CACHE`. |
| **REC-08** | Memory Leak / Cleanup | `agent/src/session/events.py:289` | **MEDIUM** | Bo sung co che don dep `_buffers` theo TTL hoac khi so luong subscriber giam ve 0. |
| **REC-09** | Memory Leak / Buffer | `agent/src/channels/websocket.py:1094` | **MEDIUM** | Don dep `_stream_text_buffers` trong ham cleanup connection khi client ngat ket noi dot ngot. |
| **REC-10** | Schema Validation / Security | `agent/src/api/research_routes.py:111-143` | **MEDIUM** | Thay the raw `dict` bang Pydantic BaseModels co rang buoc kieu va gioi han gia tri. |
| **REC-11** | Resource / Connection Leak | `agent/src/goal/store.py`, `strategy_store/sqlite_store.py` | **MEDIUM** | Bo sung ham `close()` cho cac singleton store va dang ky vao lifespan shutdown cua FastAPI. |
| **REC-12** | Memory / Payload Overhead | `agent/src/api/models.py:78-86`, `runs_routes.py:756` | **LOW** | Ap dung lazy loading hoac pagination cho cac file CSV lich su backtest thay vi nap ca 5 file. |

---

### Lo trinh Cai thien Kien truc Chi tiet (5 Buoc)

#### Buoc 1: Khac phuc cac Loi Concurrency va Crash khan cap (P0)
1. Trong `agent/src/swarm/runtime.py`:
   - Thay the dong 405: `run = self._store.load_run(run_id)`.
   - Thay the dong 406: `if run is not None and run.status in (RunStatus.running, RunStatus.pending):`.
   - Thay the dong 407: `run.status = RunStatus.cancelled`.
2. Trong `agent/src/shadow_account/reporter.py`:
   - Bo import `matplotlib.pyplot as plt`.
   - Tao figure bang: `fig = Figure(figsize=(8, 3), dpi=150)` va `canvas = FigureCanvasAgg(fig)`.
   - Luu file bang: `canvas.print_figure(path, bbox_inches="tight")` ma khong dong cham vao global state.

#### Buoc 2: Giai phong Ngen Main Event Loop cho FastAPI (P1)
1. Doi voi cac route `list_sessions`, `get_messages`, `get_run_code`, `get_run_pine`:
   - Ap dung `await run_in_threadpool(...)` cho cac ham doc ghi file.
   - Hoac doi khai bao thanh `def list_sessions(...)` (bo tu khoa `async`) de FastAPI tu dong dieu phoi vao worker threadpool cua Starlette.
2. Trong `swarm_routes.py:list_swarm_runs`:
   - Chuyen thao tac quet danh sach va goi `reconcile_run(r, write=True)` sang threadpool de giu do tre cua Event Loop duoi 5ms.

#### Buoc 3: Trien khai Dependency Injection de Loai bo `_host()` (P1)
1. Chuyen doi cac ham `_host()._runner_tasks`, `_host()._get_session_service()` thanh cac FastAPI Dependency providers trong `agent/src/api/state.py`.
2. Truy cap truc tiep qua `Depends(get_session_service)` hoac `Depends(get_runner_tasks)`.
3. Cho phep unit test co the de dang thay the cac dependency nay bang `app.dependency_overrides` chuan cua FastAPI thay vi monkeypatch len module `api_server`.

#### Buoc 4: Gia co An toan Bo nho va Vong doi Co so Du lieu (P2)
1. Thiet lap TTL eviction (vi du: 1 gio sau khi idle) cho `EventBus._buffers` trong `agent/src/session/events.py`.
2. Bo sung co che cleanup `_stream_text_buffers` trong `agent/src/channels/websocket.py` khi client ngat ket noi.
3. Bo sung phuong thuc `close()` cho `GoalStore` va `SqliteStrategyStore`, dong thoi goi `close()` trong `_lifespan` cua FastAPI khi shutdown server.

#### Buoc 5: Gia co Giao dien Nguoi dung va Chuan hoa Hop dong API (P2)
1. Trong `frontend/src/router.tsx`:
   - Them `errorElement: <RouteErrorFallback />` cho tung route con trong danh sach `children` cua `<Layout />`.
2. Thay the cac tham so raw `dict` trong `research_routes.py`, `paper_trade_routes.py`, `swarm_routes.py` bang cac lop Pydantic schema voi quy tac validate nghiem ngat.

---

## 5. VERIFICATION METHOD (PHUONG PHAP KIEM CHUNG DOC LAP)

Cac buoc kiem chung doc lap danh cho doi ngu audit va testing:

1. **Kiem chung Loi Orphaned Swarm Cancel**:
   - Tao mot file run gia lap tai `~/.vibe-trading/swarm/runs/test_orphan_run/run.json` voi status `running`.
   - Khoi dong API server.
   - Gui request: `curl -X POST http://localhost:8000/swarm/runs/test_orphan_run/cancel -H "Authorization: Bearer <key>"`.
   - *Dieu kien xac minh*: Kiem tra log backend co xuat hien `AttributeError: 'SwarmStore' object has no attribute 'get_run'` hay khong.
2. **Kiem chung Blocking I/O tren Event Loop**:
   - Mo ket noi SSE toi `http://localhost:8000/sessions/<sid>/events`.
   - Dong thoi gui 50 request lien tiep toi `GET /sessions` va `GET /runs`.
   - *Dieu kien xac minh*: Do thoi gian phan hoi (p99 latency) cua SSE heartbeat frame. Neu heartbeat bi cham tre qua 200ms chung to event loop dang bi nghen boi disk I/O.
3. **Kiem chung Matplotlib Thread Safety**:
   - Chay script gui 10 request dong thoi toi ham render cua `shadow_account/reporter.py`.
   - *Dieu kien xac minh*: Theo doi xem co xuat hien loi `ValueError: canvas is already being drawn` hoac hinh anh bi ghi de khong.
4. **Kiem chung UI Error Boundary**:
   - Truyen du lieu null/undefined vao mot component trong trang `RunDetail` hoac `Portfolio`.
   - *Dieu kien xac minh*: Xac nhan xem giao dien co giu nguyen duoc Sidebar va Header khong, hay toan bo man hinh bi go bo ve trang trang.
5. **Kiem chung Module Decoupling**:
   - Chay lenh kiem thu rieng le cho route: `pytest agent/tests/test_live_routes.py` ma khong import `api_server`.
   - *Dieu kien xac minh*: Xac nhan xem co bi nem loi `RuntimeError: register_live_routes: api_server module not in sys.modules` hay khong.
