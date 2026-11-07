# BAO CAO TONG HOP KIEM TOAN TOAN DIEN HE THONG VIBE-TRADING (MASTER AUDIT REPORT)

- Co quan thuc hien: Master Orchestrator Teamwork
- Pham vi kiem toan: Toan bo kho ma nguon Vibe-Trading (Backend FastAPI, AgentLoop, Swarm, MCP Tools, Reporting Engine, Frontend React/TypeScript, Security & Precision)
- Ngay hoan thanh: 2026-11-06

---

## 1. OBSERVATION (QUAN SAT THUC TE THEO TRU COT)

Qua qua trinh dieu phoi 3 dac vu kiem toan doc lap chuyen sau (explorer_backend_1, explorer_frontend_1, explorer_security_1), he thong da xac minh 39 diem phat hien ky thuat, duoc tinh gon va tong hop thanh 24 van de loi duy nhat khong trung lap:

### Nhom 1: Backend Architecture, Concurrency & API Layer
1. **Loi Race Condition kich hoat Live Runner (RES-02)**:
   - Vi tri: `agent/src/api/live_routes.py` (dong 1396-1422).
   - Hien tuong: Endpoint `POST /live/runner/start` thieu khoa `asyncio.Lock`, cho phep 2 request dong thoi cung kiem tra `tasks.get(broker)` thay None, cung khoi tao va chay `_drive_runner(runner)`. Dan toi rui ro giao dich trung lap tien that va tao task mo coi.
2. **Loi Deadlock trang thai Swarm Run khi Server Restart (ISSUE-01)**:
   - Vi tri: `agent/src/api/swarm_routes.py` (dong 231-238), `agent/src/swarm/runtime.py` (dong 388-402), `agent/src/swarm/store.py` (dong 365-383).
   - Hien tuong: `_cancel_events` la in-memory dict. Khi server restart, dict nay bi xoa sach nhung file `run.json` van giu status `running`. Endpoint cancel nem 404 KeyError, endpoint retry chan 409 Conflict. Nguoi dung bi khoa cung khong the cancel hay retry.
3. **Loi Matplotlib Global State Machine gay Race Condition trong Reporting (ISSUE-02)**:
   - Vi tri: `agent/src/reporting/renderer.py` (dong 16-19, 280-302).
   - Hien tuong: Su dung `matplotlib.pyplot` toan cuc trong threadpool. Khi xuat nhieu bieu do song song, hinh anh cua ma co phieu nay de len ma co phieu khac hoac nem `ValueError: canvas is already being drawn`.
4. **Loi Crash xuat bao cao khi thieu LibreOffice va ro ri o dia Staging (ISSUE-03 / TRV-01)**:
   - Vi tri: `agent/src/reporting/renderer.py` (dong 476-497), `agent/src/reporting/service.py` (dong 80-105).
   - Hien tuong: Mac dinh xuat ca DOCX va PDF. Khi server thieu LibreOffice binary, nem `RuntimeError` lam crash toan bo request ke ca khi DOCX da tao xong. Thu muc `staging` khong bao gio duoc don dep sau khi copy sang reports directory.
5. **Ngen Main Event Loop trong API `list_runs` (ISSUE-04)**:
   - Vi tri: `agent/src/api/runs_routes.py` (dong 1037-1136).
   - Hien tuong: Route `async def list_runs` thuc hien I/O file dong bo `open()`, `json.load()` truc tiep tren Main Event Loop, gay gia tang do tre cho toan bo he thong khi co nhieu thu muc runs.
6. **Tieu ton RAM khong kiem soat khi nap Artifacts Backtest (ISSUE-05)**:
   - Vi tri: `agent/src/api/runs_routes.py` (dong 756-797), `agent/src/api/models.py` (dong 78-86).
   - Hien tuong: `_load_csv_records` nap toan bo CSV hang chuc nghin dong vao RAM ma khong co phan trang hay limit dong.
7. **Treo luong vinh vien trong Tool Lifecycle Execution (ISSUE-08)**:
   - Vi tri: `agent/src/agent/tool_lifecycle.py` (dong 516-525).
   - Hien tuong: `ThreadPoolExecutor` goi `f.result()` khong co tham so `timeout`. Neu mot tool bi treo I/O hoac deadlock, luong worker bi phong toa vo han.

### Nhom 2: Frontend Client, React Components & Contract Drifts
8. **Crash UI do goi `.toFixed()` tren gia tri null/undefined (F-01)**:
   - Vi tri: `frontend/src/components/charts/ValidationPanel.tsx` (dong 45-95) va `frontend/src/components/charts/AttributionTab.tsx` (dong 171).
   - Hien tuong: Goi truc tiep `actual_sharpe.toFixed(2)` hay `metrics.information_ratio.toFixed(2)` khi backend tra ve null. Phep so sanh `null !== undefined` tra ve true, gay crash `TypeError: Cannot read properties of null (reading 'toFixed')`.
9. **Crash UI do parse Date va cat chuoi tren gia tri rong (F-02)**:
   - Vi tri: `frontend/src/components/chat/ForexTradeCards.tsx` (dong 36, 93, 95).
   - Hien tuong: `new Date(value).toISOString()` nem `RangeError: Invalid time value` neu `quote_at` rong; goi `.join()` tren `evidence_refs` va `.slice()` tren `evidence_hash` khi bien undefined gay TypeError.
10. **Crash UI tren the MandateProposalCard (F-03)**:
    - Vi tri: `frontend/src/components/chat/MandateProposalCard.tsx` (dong 40, 46).
    - Hien tuong: Goi `leverage.toLowerCase()` va `universe.replace()` khong kiem tra null/undefined.
11. **Crash cac bieu do ECharts khi props du lieu rong/undefined (F-04)**:
    - Vi tri: `EquityChart.tsx`, `CorrelationMatrix.tsx`, `AnnualReturnsChart.tsx`, `MonthlyReturnsHeatmap.tsx`, `DistributionChart.tsx`, `OptionsPayoffChart.tsx`.
    - Hien tuong: Hook `useChartLifecycle` chay `.map()` va `.length` ngay trong callback ma khong kiem tra `!data || !Array.isArray(data)`.
12. **Thieu Error Boundary tai cac Route con trong Router (F-05)**:
    - Vi tri: `frontend/src/router.tsx` (dong 1-85).
    - Hien tuong: Cac route `/market-research`, `/forex`, `/runs/:id` khong co `errorElement`. Khi component con crash, toan bo ung dung bi go bo ve man hinh loi toan cuc, lam mat Sidebar va Navbar.
13. **Nuot loi am tham va hien sai trang thai thanh cong (F-06)**:
    - Vi tri: `frontend/src/components/chat/ReportArtifactCard.tsx` (dong 42-50, 107).
    - Hien tuong: Khoi catch download bao cao rong hoan toan, khong bao loi; the bao cao luon hien tick xanh thanh cong ke ca khi backend job tra ve `status === "failed"`.
14. **Contract Drift giua TypeScript va FastAPI Pydantic (F-07)**:
    - Vi tri: `frontend/src/lib/research.ts` (dong 40-52) vs `agent/src/api/research_routes.py` (dong 144-162).
    - Hien tuong: `CryptoRequest.period` o frontend la `string`, trong khi backend la `Literal["5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d"]` va `extra="forbid"`. Nguoi dung gui gia tri ngoai danh sach se nhan ngay loi 422 Unprocessable Entity.
15. **Thieu cac API Wrapper trong `frontend/src/lib/api.ts` (F-08, F-09, F-10)**:
    - Vi tri: `frontend/src/lib/api.ts` (dong 1860-2252).
    - Hien tuong: Thieu cac endpoint Scheduled Runs playbooks & status (`/scheduled-runs/playbooks`, `/scheduled-runs/status`), thieu GET `/live/runner/settings`, thieu paper trade account details & step execution, thieu Strategy Adaptations API.

### Nhom 3: Bao mat, Do chinh xac so hoc & Ro ri tai nguyen
16. **Ro ri File Descriptor va Ket noi SQLite trong Portfolio (RES-01)**:
    - Vi tri: `agent/src/portfolio/store.py` (dong 49-55, 87, 116) va `imports.py` (dong 38-44).
    - Hien tuong: Cú phap `with sqlite3.connect(...) as conn:` chi quan ly Transaction, khong goi `conn.close()`. Moi truy van tao ket noi moi bo ngo file descriptor, dan den `sqlite3.OperationalError: database is locked`.
17. **Nguy co SSRF qua tham so `base_url` trong cau hinh LLM va QVeris (SEC-01 / ISSUE-06)**:
    - Vi tri: `agent/src/api/settings_routes.py` (dong 753-764) va `agent/src/api/qveris_routes.py` (dong 102-106).
    - Hien tuong: Khong kiem tra dia chi IP mang noi bo (RFC 1918, loopback, cloud metadata `169.254.169.254`), cho phep ke tan cong tro toi ha tang noi bo.
18. **Loi sap Portfolio Refresh tren thi truong Viet Nam do thieu ty gia VND (NUM-01)**:
    - Vi tri: `agent/src/portfolio/fx.py` (dong 30-36) va `agent/src/portfolio/compatibility.py` (dong 238-243).
    - Hien tuong: Bang ty gia chi ho tro USD/CNY/HKD. Khi tai khoan co tien te `VND`, ham nem `PortfolioContractError`, lam endpoint `POST /api/portfolio/refresh` tra ve HTTP 503 lam te liet Portfolio Dashboard tai Viet Nam.
19. **Loi troi so hoc va dinh dang NaN tren Frontend (NUM-02)**:
    - Vi tri: `frontend/src/lib/formatters.ts` (dong 54-67).
    - Hien tuong: Nhan `v * 100` tren float IEEE 754 khong check `Number.isFinite(v)`, hien thi `NaN%` va lam tron khong chinh xac. Thieu menh gia tien te ro rang (VND vs USD).
20. **Loi lech don vi nghin/trieu/ty trong nghien cuu tai chinh Viet Nam (NUM-03)**:
    - Vi tri: `agent/src/tools/vietnam_research_tool.py` (dong 133-143).
    - Hien tuong: Thieu chuan hoa scale factor khi tinh Free Cash Flow (`cfo - capex`). Neu CFO la trieu VND con Capex la nghin VND se sai lech 1.000 lan.
21. **Thieu URL Encoding gay nguy co Path Parameter Injection (SEC-04)**:
    - Vi tri: `frontend/src/lib/api.ts` (dong 612-650).
    - Hien tuong: Ghep truc tiep `${id}` va `${sid}` vao chuoi URL ma khong qua `encodeURIComponent`.
22. **Ro ri bo nho trong ReportJobService, EventBus va WebSocket (RES-03, RES-04, RES-05)**:
    - Vi tri: `service.py:31`, `events.py:79-106`, `websocket.py:300, 1094-1110`.
    - Hien tuong: `_JOBS_CACHE` khong co LRU/TTL; `EventBus._buffers` luu 500 event/session khong tu huy; `_stream_text_buffers` khong duoc giai phong khi client ngat ket noi dot ngot truoc khi nhan `_stream_end`.
23. **API nhan raw Dict khong qua Pydantic Schema Validation (SEC-02 / ISSUE-07)**:
    - Vi tri: `swarm_routes.py:91`, `research_routes.py:111`, `paper_trade_routes.py:67`.
    - Hien tuong: Khong kiem soat kieu va gioi han gia tri (vi du `max_llm_calls` co the am hoac cuc lon).
24. **Thieu bao ve luong trong ToolRegistry va Stdio Chunking trong MCP Server (ISSUE-10, ISSUE-11)**:
    - Vi tri: `agent/src/tools/__init__.py:12-40`, `agent/mcp_server.py:80-140`.
    - Hien tuong: Dang ky tool dong thieu lock; xuat payload lon qua Stdio transport khong chunking gay tran pipe buffer Windows.

---

## 2. LOGIC CHAIN

Toan bo cac phat hien deu duoc xac minh qua chuoi lap luan ky thuat nghiem ngat:
- **Ve do on dinh giao dich tien that**: Su thieu vang cua `asyncio.Lock` tai `live_routes.py:1396` ket hop voi co che bat dong bo cua FastAPI tao ra cua so race condition ly tuong de tao hai background worker cung dat lenh vao broker.
- **Ve do tin cay cua he thong bao cao**: Matplotlib su dung global state qua `pyplot`. Khi nhieu request dong thoi goi qua threadpool, cac luong ghi de doi tuong `FigureCanvasAgg` toan cuc, lam sai lech do thi hoac crash rendering.
- **Ve su song con cua UI**: React Router thieu `errorElement` o cap con khien moi loi TypeError/RangeError do null dereference o cac component ECharts va Forex/AttributionCards bi phong dai len root, danh sap toan bo menu va layout cua nguoi dung.
- **Ve tai nguyen va he dieu hanh**: Viec nham lan giua Transaction context manager va Resource context manager cua `sqlite3.connect` khien file descriptor tren Windows/Linux bi giu lai vinh vien, dan den loi `database is locked`.

---

## 3. CAVEATS

1. Bao cao duoc lap tren co so khao sat ma nguon tinh toan dien, doi chieu hop dong API giua client va server, va kiem tra luong thuc thi phan tich doc lap.
2. Cac thu vien ngoai vi nhu LibreOffice phu thuoc vao moi truong cai dat tren he dieu hanh host. He thong can co co che Graceful Degradation de van tra ve DOCX khi PDF unavailable.
3. Cac gia tri ti gia ngoai te can ho tro co che ti gia dong tu broker hoac fallback cho thi truong noi dia Viet Nam.

---

## 4. CONCLUSION & CLASSIFIED FINDINGS TABLE

| ID | Phan loai | File & Dong | Muc do | Nguyen nhan goc re | Bien phap khac phuc de xuat |
|---|---|---|---|---|---|
| **RES-02** | Concurrency / Real Money | `agent/src/api/live_routes.py:1396-1422` | **CRITICAL** | Thieu `asyncio.Lock` khi check va spawn live runner task | Ap dung `async with self._runner_lock:` bao boc toan bo doan check `tasks.get(broker)` va `ensure_future`. |
| **F-01** | Crash / TypeError | `frontend/src/components/charts/ValidationPanel.tsx:45` & `AttributionTab.tsx:171` | **CRITICAL** | Goi `.toFixed()` tren gia tri null/undefined ma khong kiem tra an toan | Tao helper `fmtNum(v, d)` kiem tra `Number.isFinite(v)` truoc khi format. |
| **F-02** | Crash / RangeError | `frontend/src/components/chat/ForexTradeCards.tsx:36, 93, 95` | **CRITICAL** | `new Date(v).toISOString()` nem RangeError neu chuoi rong; `.join()` va `.slice()` tren undefined | Bọc Date trong try/catch va su dung optional chaining `?.slice()`, `?.join()`. |
| **RES-01** | Resource / Handle Leak | `agent/src/portfolio/store.py:49-55` & `imports.py:38-44` | **HIGH** | `with sqlite3.connect` chi quan ly transaction, khong dong ket noi (`close()`) | Dinh nghia contextmanager co `try ... finally: conn.close()`. |
| **ISSUE-01** | Concurrency / Deadlock | `agent/src/api/swarm_routes.py:231`, `runtime.py:388`, `store.py:365` | **HIGH** | `_cancel_events` in-memory bi xoa khi server restart, run.json van la running | Bo sung co che kiem tra va huy truc tiep trong store neu khong tim thay event trong RAM. |
| **ISSUE-02** | Thread Safety / Crash | `agent/src/reporting/renderer.py:16-19, 280-302` | **HIGH** | Dung `matplotlib.pyplot` state machine toan cuc trong moi truong da luong | Chuyen sang OOP Figure API: `Figure()` va `FigureCanvasAgg`. |
| **ISSUE-03** | Fault Tolerance | `agent/src/reporting/renderer.py:476`, `service.py:80-105` | **HIGH** | Crash ca export khi thieu LibreOffice va bo quen thu muc staging | Bọc try/catch cho PDF export de tra ve DOCX va cleanup staging trong finally. |
| **SEC-01** | Security / SSRF | `agent/src/api/settings_routes.py:753-764` | **HIGH** | `base_url` cua LLM provider thuong khong duoc validate dia chi noi bo | Tich hop `_validate_model_base_url` chan IP private va cloud metadata. |
| **NUM-01** | Logic / Availability | `agent/src/portfolio/fx.py:30-36`, `compatibility.py:238-243` | **HIGH** | Bang ty gia chi ho tro USD/CNY/HKD, nem loi lam sap 503 khi co VND | Bo sung ty gia USD/VND va cho phep fallback linh hoat cho thi truong VN. |
| **F-04** | Crash / Charts | `EquityChart.tsx`, `CorrelationMatrix.tsx`, `AnnualReturnsChart.tsx`, etc. | **HIGH** | `useChartLifecycle` chay `.map()` khi props bi undefined/null | Thuc hien early guard `if (!data || !Array.isArray(data)) return {};` trong callback. |
| **F-05** | UI Architecture | `frontend/src/router.tsx:1-85` | **HIGH** | Thieu `errorElement` tai cac route con lam sap toan bo App ve trang trang | Bo sung `errorElement: <RouteErrorFallback />` cho tung route con trong Router. |
| **F-06** | UI Silent Failure | `frontend/src/components/chat/ReportArtifactCard.tsx:42-50, 107` | **HIGH** | Nuot loi download va luon hien tick xanh ke ca khi job failed | Hien `toast.error()` trong catch va render canh bao that bai neu job failed. |
| **ISSUE-04** | Async Latency | `agent/src/api/runs_routes.py:1037-1136` | **MEDIUM** | Doc ghi file dong bo tren Main Event Loop trong async route `list_runs` | Chuyen thao tac I/O sang threadpool bang `starlette.concurrency.run_in_threadpool`. |
| **ISSUE-05** | Memory Overhead | `agent/src/api/runs_routes.py:756-797`, `models.py:78` | **MEDIUM** | Nap toan bo CSV lich su giao dich hang chuc nghin dong vao RAM | Bo sung phan trang hoac gioi han so dong nap ban ghi trades/positions. |
| **ISSUE-06** | Security / SSRF | `agent/src/api/qveris_routes.py:102-106`, `qveris_tool.py:228` | **MEDIUM** | `base_url` cua QVeris khong chan private IP | Su dung `is_non_public_address` de chan loopback va private subnet. |
| **ISSUE-07** | Input Validation | `research_routes.py:111`, `paper_trade_routes.py:67`, `swarm_routes.py:92` | **MEDIUM** | Nhap raw `dict` khong qua Pydantic schema validation | Dinh nghia Pydantic BaseModel co rang buoc kieu va gioi han gia tri ro rang. |
| **ISSUE-08** | Concurrency / Timeout | `agent/src/agent/tool_lifecycle.py:516-525` | **MEDIUM** | `ThreadPoolExecutor.result()` khong truyen timeout gay nguy co treo luong | Dat `timeout=tool_timeout` cho loi goi `f.result()`. |
| **F-07** | Contract Drift | `frontend/src/lib/research.ts:40-52` vs `research_routes.py:144-162` | **MEDIUM** | `CryptoRequest.period` o frontend la `string`, backend la `Literal` | Chuyen period sang Union Literal `5m"|"15m"|"30m"|"1h"|...` tren TypeScript. |
| **F-08** | Missing API | `frontend/src/lib/api.ts:1930-2005` | **MEDIUM** | Thieu API Scheduled Runs playbooks va status | Bo sung day du cac ham wrapper goi backend routes. |
| **SEC-04** | Security / Path | `frontend/src/lib/api.ts:612-650` | **MEDIUM** | Ghep chuoi ID truc tiep vao URL khong qua `encodeURIComponent` | Bọc `${encodeURIComponent(id)}` cho toan bo cac route URL. |
| **NUM-02** | Precision / Formatting | `frontend/src/lib/formatters.ts:54-67` | **MEDIUM** | Float `v*100` trôi số, hien thi `NaN%`, thieu ky hieu menh gia | Kiem tra `Number.isFinite(v)`, dung phep lam tron an toan va them menh gia. |
| **NUM-03** | Financial Precision | `agent/src/tools/vietnam_research_tool.py:133-143` | **MEDIUM** | Thieu scale factor chuan hoa don vi nghin/trieu/ty khi tinh FCF | Kiem tra va quy doi dong nhat ve cung mot scale truoc khi tru CFO - Capex. |
| **RES-03** | Memory Leak | `agent/src/reporting/service.py:31` | **MEDIUM** | `_JOBS_CACHE` class-level dict khong co gioi han va TTL | Su dung LRU cache hoac co che TTL eviction. |
| **RES-04** | Memory Leak | `agent/src/session/events.py:79-106, 289-293` | **MEDIUM** | `EventBus._buffers` tich luy 500 event/session khong tu huy | Don dep key session khi subscriber cuoi cung ngat ket noi va them TTL. |
| **RES-05** | Memory Leak | `agent/src/channels/websocket.py:300, 1094-1110` | **MEDIUM** | WebSocket delta text buffer khong duoc giai phong khi client ngat giua chung | Bo sung cleanup buffer trong ham `_cleanup_connection`. |
| **SEC-03** | Input Validation | `agent/src/api/channels_routes.py:18-23` | **LOW** | Thieu regex va do dai cho channel pairing command | Bo sung Field(..., max_length=50, pattern="^[a-zA-Z0-9_-]+$"). |
| **ISSUE-09** | Path Sanitization | `forex_routes.py:73`, `paper_trade_routes.py:50` | **LOW** | Thieu regex validation cho path parameters | Bọc Field(..., pattern="^[a-zA-Z0-9_-]+$"). |
| **ISSUE-10** | Concurrency | `agent/src/tools/__init__.py:12-40` | **LOW** | Thieu lock khi register dynamic tools | Bo sung threading lock khi ghi vao dictionary tool registry. |
| **ISSUE-11** | Transport | `agent/mcp_server.py:80-140` | **LOW** | Stdio output payload lon khong chunking tren Windows | Thuc hien chunking theo block 64KB khi ghi vao stdout pipe. |

---

## 5. VERIFICATION METHOD

Quy trinh kiem thu xac minh doc lap gom 4 buoc cu the:
1. **Kiem chung Live Runner Race Condition**: Gui 10 request song song toi `POST /live/runner/start` cung broker de chung minh chi co duy nhat 1 task duoc khoi tao sau khi ap dung `asyncio.Lock`.
2. **Kiem chung SQLite Connection Leak**: Chay vong lap 1.000 truy van danh muc lien tiep de xac minh khong con loi `sqlite3.OperationalError: database is locked` va so luong open file handles khong tang vot.
3. **Kiem chung UI Error Boundary & Crashes**: Thuc hien test case render `AttributionTab` va `ForexTradeCards` voi du lieu null/empty de xac minh khong gay crash cay ung dung.
4. **Kiem chung TypeScript Typecheck**: Chay `npm run typecheck` tren thu muc frontend de dam bao khong con sai lech kieu hop dong voi FastAPI.
