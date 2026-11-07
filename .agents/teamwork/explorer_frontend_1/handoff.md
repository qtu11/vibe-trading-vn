# BAO CAO BAN GIAO DIEU TRA TOAN DIEN FRONTEND (M2)

Nguoi thuc hien: explorer_frontend_1
Ngay thuc hien: 2026-11-06
Pham vi: Frontend Client (frontend/src/lib/api.ts), TypeScript Types (frontend/src/types/), React UI Components, Charts, Error Boundaries, Toast & Network Fallbacks.

---

## 1. OBSERVATION (QUAN SAT THUC TE)

### 1.1. Missing Endpoints va Sai lech URL/Method trong frontend/src/lib/api.ts

Quan sat 1.1.1: Scheduled Runs Playbooks va Status Endpoints bi thieu hoan toan trong api.ts
- File Backend: `agent/src/api/scheduled_routes.py`
  - Dong 125: `@router.get("/status") async def scheduler_status(): ...` (Mount tai `/scheduled-runs/status`)
  - Dong 133: `@router.get("/playbooks") async def list_research_playbooks(): ...` (Mount tai `/scheduled-runs/playbooks`)
  - Dong 140: `@router.get("/playbooks/{slug}") async def get_research_playbook(slug: str): ...` (Mount tai `/scheduled-runs/playbooks/{slug}`)
  - Dong 149: `@router.post("/playbooks/{slug}") async def create_scheduled_run_from_playbook(slug: str, ...): ...`
  - Dong 192: `@router.get("/{job_id}") async def get_scheduled_run(job_id: str): ...`
- File Frontend: `frontend/src/lib/api.ts` (Dong 1930 - 2005)
  - `api` object chi cung cap: `listScheduledRuns`, `createScheduledRun`, `updateScheduledRun`, `deleteScheduledRun`, `triggerScheduledRun`, `getScheduledRunHistory`.
  - Khong co bat ky phuong thuc nao de goi `GET /scheduled-runs/status`, `GET /scheduled-runs/playbooks`, `GET /scheduled-runs/playbooks/{slug}`, `POST /scheduled-runs/playbooks/{slug}`, va `GET /scheduled-runs/{job_id}`.

Quan sat 1.1.2: Thieu Endpoint GET /live/runner/settings trong api.ts
- File Backend: `agent/src/api/live_routes.py`
  - Dong 131: `@router.get("/runner/settings") async def get_runner_settings(broker: Optional[str] = None): ...`
  - Dong 140: `@router.put("/runner/settings") async def update_runner_settings(body: RunnerSettingsUpdate): ...`
- File Frontend: `frontend/src/lib/api.ts` (Dong 1860 - 1875)
  - Chi co ham `saveRunnerSettings: (settings: RunnerSettings) => request<RunnerSettings>("/live/runner/settings", { method: "PUT", body: JSON.stringify(settings) })`.
  - Thieu hoan toan ham `getRunnerSettings` de khoi tao gia tri cau hinh runner ban dau cho nguoi dung.

Quan sat 1.1.3: Thieu Endpoint Paper Trading Account Details va Step Execution
- File Backend: `agent/src/api/paper_trade_routes.py`
  - Dong 34: `@router.get("/api/paper-accounts/{account_id}") async def get_paper_account(account_id: str): ...`
  - Dong 67: `@router.post("/api/paper-trade/step") async def step_paper_trading(req: StepRequest): ...`
- File Frontend: `frontend/src/lib/api.ts` (Dong 2245 - 2252)
  - `paperApi` chi dinh nghia: `listAccounts`, `createAccount`, `advanceAccount`, `getAccountHistory`.
  - Thieu phuong thuc `getAccount(accountId)` va `stepPaperTrade(req)`.

Quan sat 1.1.4: Thieu toan bo Strategy Adaptation API Endpoints
- File Backend: `agent/src/api/strategy_adaptation_routes.py`
  - Dong 42: `@router.post("/api/strategy-adaptations") async def create_strategy_adaptation(...)`
  - Dong 66: `@router.post("/api/strategy-adaptations/evidence") async def submit_adaptation_evidence(...)`
- File Frontend: `frontend/src/lib/api.ts`
  - Tim kiem khong tim thay bat ky dinh nghia nao cho `/api/strategy-adaptations`.

Quan sat 1.1.5: Thieu Endpoint Doi ten Connection
- File Backend: `agent/src/api/connection_routes.py`
  - Dong 98: `@router.put("/api/connections/{connection_id}") async def rename_connection(connection_id: str, ...)`
- File Frontend: `frontend/src/lib/api.ts` (Dong 2200 - 2240)
  - Chi dinh nghia: `listConnections`, `createConnection`, `testConnection`, `deleteConnection`. Thieu `renameConnection`.

Quan sat 1.1.6: Su dung Fetch truc tiep bo qua apiClient va trung lap logic
- File Frontend: `frontend/src/components/chat/ContextMemoryPanel.tsx`
  - Dong 38: `const res = await fetch(`/sessions/${encodeURIComponent(sessionId)}/memory`);`
  - Dong 53: `const res = await fetch(`/sessions/${encodeURIComponent(sessionId)}/context`);`
  - Goi truc tiep `fetch()` thay vi su dung client tap trung `api.ts`, bo qua co che xu ly header, base URL, va parse loi dong nhat.
- File Frontend: `frontend/src/components/settings/QVerisSettings.tsx`
  - Dong 47-66: Tu viet ham `requestJson()` cuc bo voi `fetch()` toi `/qveris/config`, `/qveris/status`, `/qveris/test` thay vi tich hop vao `api.ts`.

---

### 1.2. Contract Drift giua TypeScript Types va FastAPI Pydantic Models

Quan sat 1.2.1: CryptoRequest period va limit bi lech kieu nghiem ngat
- File Frontend: `frontend/src/lib/research.ts` (Dong 40 - 52)
```typescript
export interface CryptoRequest {
  symbol: string;
  period?: string;
  limit?: number;
  include_funding?: boolean;
  include_orderbook?: boolean;
}
```
- File Backend: `agent/src/api/research_routes.py` (Dong 144 - 162)
```python
class _CryptoResearchBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str = Field(..., min_length=2, max_length=20)
    period: Literal["5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d"] = "1h"
    limit: int = Field(default=30, ge=2, le=100)
    include_funding: bool = True
    include_orderbook: bool = True
```
- Sai lech: Frontend cho phep `period?: string`. Neu nguoi dung truyen chuoi bat ky nhu `"1m"`, `"1w"`, `"1M"`, FastAPI se lap tuc tra loi `HTTP 422 Unprocessable Entity` vi backend co `extra="forbid"` va rang buoc `Literal[...]`. Truong `limit` o frontend la `number`, backend yeu cau `ge=2, le=100`.

Quan sat 1.2.2: VietnamRequest thieu tinh linh hoat cua cac truong tuy chon
- File Frontend: `frontend/src/lib/research.ts` (Dong 18 - 25)
```typescript
export interface VietnamRequest {
  symbol: string;
  period: "quarter" | "annual";
  consolidation: "consolidated" | "separate";
  offset: number;
}
```
- File Backend: `agent/src/api/research_routes.py` (Dong 88 - 97)
```python
class VietnamResearchRequest(BaseModel):
    symbol: str = Field(...)
    period: Literal["quarter", "annual"] = "quarter"
    consolidation: Literal["consolidated", "separate"] = "consolidated"
    offset: int = Field(default=0, ge=0)
```
- Sai lech: Frontend bat buoc truyen ca 4 truong (`period`, `consolidation`, `offset`), trong khi backend cho phep mac dinh.

Quan sat 1.2.3: RunData va RunResponse thieu truong dong bo
- File Frontend: `frontend/src/lib/api.ts` (Dong 28 - 48)
  - `RunData` thieu cac truong: `reason?: string`, `planner_output?: unknown`, `strategy_spec?: unknown`, `rag_selection?: unknown`.
- File Backend: `agent/src/api/models.py` (Dong 35 - 55)
  - `RunResponse` thieu truong `chart_symbols: Optional[List[str]] = None`, mac du trong `agent/src/api/runs_routes.py` (Dong 74), backend thuc te chen `chart_symbols` vao dict phan hoi.

Quan sat 1.2.4: ScheduledRun delivery_format khong khop kieu du lieu
- File Frontend: `frontend/src/lib/api.ts` (Dong 120): `delivery_format: "html" | "pdf" | null`
- File Backend: `agent/src/api/scheduled_routes.py` (Dong 37): `delivery_format: Optional[Literal["html", "pdf"]] = None`.

---

### 1.3. Error Boundaries, Toast Notifications va Fallback Xu ly Mang

Quan sat 1.3.1: Thieu Error Boundary o cap Router / Route
- File Frontend: `frontend/src/main.tsx` (Dong 20 - 25)
  - Chi boc `<ErrorBoundary>` ngoai cung bao ve toan bo `<App />`.
- File Frontend: `frontend/src/router.tsx` (Dong 1 - 85)
  - Cac route con (`/`, `/market-research`, `/forex`, `/options-lab`, `/runs/:id`) hoan toan khong co thuoc tinh `errorElement`.
  - Hau qua: Khi bat ky component nao o trang con gap loi Javascript runtime (nhu TypeError, null pointer), toan bo ung dung bi go bo (unmount), dua nguoi dung ve man hinh ErrorBoundary toan cuc mau trang va lam mat toan bo thanh Sidebar / Navbar dieu huong.

Quan sat 1.3.2: Nuot loi am tham (Silent Failure) va sai trang thai tai ReportArtifactCard.tsx
- File Frontend: `frontend/src/components/chat/ReportArtifactCard.tsx`
  - Dong 42 - 50:
```typescript
  async function handleDownload(artifact: ReportArtifact) {
    try {
      setDownloadingId(artifact.report_id);
      await downloadGeneratedReport(artifact.report_id, artifact.filename);
    } catch {
      // Error is caught and surfaced via notification or fallback
    } finally {
      setDownloadingId(null);
    }
  }
```
  - Thuc te: Khoi `catch` hoan toan trong rong, khong co loi goi `toast.error()` nao de bao cho nguoi dung biet tai file that bai (vi du loi 404, token het han, mang rot).
  - Dong 107: Luon hien thi `<CheckCircle2 className="h-4 w-4 text-[#17B978]" />` (bieu tuong tick xanh thanh cong) ngay ca khi `job.status === "failed"`. Khi `job.status === "failed"`, mang `job.artifacts` rong, the hien thi tieu de thanh cong nhung khong co nut tai nao va khong giai thich ly do that bai.

Quan sat 1.3.3: Thieu Loading State va Toast bao loi mang trong ContextMemoryPanel.tsx
- File Frontend: `frontend/src/components/chat/ContextMemoryPanel.tsx` (Dong 35 - 65)
  - Ham `refreshContext` thuc hien 2 lenh goi `fetch` lien tiep nhung khong cap nhat loading state cho nut Refresh va khong bat loi mang de hien thi toast thong bao loi cho nguoi dung.

---

### 1.4. Undefined Property Access va Nguy co Sap Render Component

Quan sat 1.4.1: useChartLifecycle chay truoc kiem tra du lieu rong tren cac bieu do ECharts
- File Frontend:
  - `frontend/src/components/charts/EquityChart.tsx` (Dong 18 - 45)
  - `frontend/src/components/charts/CorrelationMatrix.tsx` (Dong 25 - 50)
  - `frontend/src/components/charts/AnnualReturnsChart.tsx` (Dong 15 - 55, Dong 69)
  - `frontend/src/components/charts/MonthlyReturnsHeatmap.tsx` (Dong 20 - 45)
  - `frontend/src/components/charts/DistributionChart.tsx` (Dong 33 - 45, Dong 104)
  - `frontend/src/components/charts/OptionsPayoffChart.tsx` (Dong 19 - 30, Dong 154)
- Bieu hien:
  - Cac component tren tuan thu Hook rules bang cach dat `useChartLifecycle` truoc menh de kiem tra `if (data.length === 0) return ...`.
  - Tuy nhien, ben trong callback cua `useChartLifecycle`, code thuc hien ngay cac thao tac `data.map(...)`, `matrix.map(...)`, `curve.spot.map(...)`, `samples.length` ma khong kiem tra `data` co ton tai hay khong (`if (!data || data.length === 0)`).
  - Neu props `data`, `matrix`, `curve` bi `undefined` hoac `null` (khi API dang tai hoac phan hoi rong), ung dung lap tuc nem loi: `TypeError: Cannot read properties of undefined (reading 'map')` hoac `reading 'length'`.
  - Tai `EquityChart.tsx`: `Math.min(...drawdown.map(Number))` khi mang `drawdown` rong se danh gia thanh `Math.min(...[]) = Infinity`.

Quan sat 1.4.2: Goi truc tiep .toFixed() tren cac truong so co the null/undefined
- File Frontend: `frontend/src/components/charts/ValidationPanel.tsx` (Dong 45 - 95)
  - Code goi truc tiep: `mc.actual_sharpe.toFixed(2)`, `bs.observed_sharpe.toFixed(2)`, `bs.ci_lower.toFixed(2)`, `bs.ci_upper.toFixed(2)`, `wf.sharpe_mean.toFixed(2)`, `w.sharpe.toFixed(2)` ma khong co kiem tra an toan `typeof val === "number" && !isNaN(val)`.
  - Neu backend tra ve ket qua Monte Carlo hoac Walk-forward bi that bai hoac gia tri null, toan bo tab kiem dinh se bi sap render lap tuc.
- File Frontend: `frontend/src/components/charts/AttributionTab.tsx` (Dong 171)
  - Dong 171: `metrics?.information_ratio !== undefined ? metrics.information_ratio.toFixed(2) : "-"`
  - Neu `metrics.information_ratio` la `null` (thuong gap khi backend tra ve null trong JSON), phep so sanh `null !== undefined` tra ve `true`, dan den lenh goi `(null).toFixed(2)` nem loi `TypeError: Cannot read properties of null (reading 'toFixed')`.

Quan sat 1.4.3: Loi parse Date va cat chuoi trong ForexTradeCards.tsx
- File Frontend: `frontend/src/components/chat/ForexTradeCards.tsx`
  - Dong 36: `const utc = (value: string) => new Date(value).toISOString().replace("T", " ").replace(/\.\d+Z$/, " UTC");`
    - Neu `plan.quote_at` hoac `plan.expires_at` la chuoi rong hoac gia tri khong hop le, `new Date(value).toISOString()` se nem loi nghiem trong: `RangeError: Invalid time value`.
  - Dong 93: `r.provider} / {r.model} · {r.evidence_refs.join(", ")}`
    - Neu `r.evidence_refs` bi `undefined` hoac `null`, lenh goi `.join()` nem `TypeError`.
  - Dong 95: `plan.evidence_hash.slice(0, 16)`
    - Neu `plan.evidence_hash` bi `undefined` hoac `null`, lenh goi `.slice()` nem `TypeError`.

Quan sat 1.4.4: Loi ep kieu chuoi trong MandateProposalCard.tsx
- File Frontend: `frontend/src/components/chat/MandateProposalCard.tsx`
  - Dong 40: `const lowered = leverage.toLowerCase();`
    - Ham `formatLeverage` chi kiem tra `typeof leverage === "number"`. Neu `leverage` la `undefined` hoac `null`, lenh goi `leverage.toLowerCase()` nem loi `TypeError: Cannot read properties of undefined (reading 'toLowerCase')`.
  - Dong 46: `return universe.replace(/_/g, " ");`
    - Ham `formatUniverse` chi kiem tra `Array.isArray(universe)`. Neu `universe` la `undefined` hoac `null`, lenh goi `universe.replace(...)` nem loi `TypeError`.

Quan sat 1.4.5: Loi kiem tra mang trong TopDrawdownsPanel.tsx
- File Frontend: `frontend/src/components/charts/TopDrawdownsPanel.tsx`
  - Dong 9: `if (episodes.length === 0)`
    - Neu prop `episodes` truyen vao la `undefined` hoac `null`, phep truy cap `.length` nem loi `TypeError`.

---

## 2. LOGIC CHAIN (CHUOI LAP LUAN TU QUAN SAT DEN KET LUAN)

1. **Tu Quan sat 1.1.1 - 1.1.5:**
   - Backend he thong (`scheduled_routes.py`, `live_routes.py`, `paper_trade_routes.py`, `strategy_adaptation_routes.py`, `connection_routes.py`) da phat trien cac API quan trong ve quan ly Playbooks, trang thai Scheduler, thiet lap Runner khoi diem, quan ly tai khoan Paper Trading chi tiet, dieu chinh chien luoc (Strategy Adaptations) va doi ten Connection.
   - Tuy nhien, `frontend/src/lib/api.ts` duoc viet thieu dong bo, khong export cac ham nay. Do do, bat ky UI view nao muon su dung cac tinh nang nay hoac la khong the thuc hien duoc, hoac phai tu viet `fetch()` cuc bo (nhu Quan sat 1.1.6). Dieu nay dan den sai lech kien truc, thieu tap trung hoa logic goi API va gay kho khan cho viec bao tri, ghi log va dinh danh loi.

2. **Tu Quan sat 1.2.1 - 1.2.4:**
   - FastAPI su dung Pydantic voi co che validate rat nghiem ngat (`extra="forbid"`, `Literal[...]`, `ge`, `le`).
   - TypeScript o Frontend dinh nghia cac kieu du lieu long leo (`period?: string`, `limit?: number`). Khi UI component truyen gia tri chuoi tuy y khong nam trong tap hop hop le cua `Literal`, backend se ngay lap tuc tra ve loi 422 Unprocessable Entity. Nguoi dung nhin thay yeu cau nghien cuu bi loi ma khong hieu nguyen nhan vi Frontend khong canh bao hoac rang buoc kieu truoc khi gui.
   - Ngoai ra, viec `RunData` thieu cac truong metadata (`reason`, `planner_output`, `strategy_spec`) khien frontend bi thieu du lieu khi hien thi chi tiet phan tich cua Agent.

3. **Tu Quan sat 1.3.1 - 1.3.3:**
   - React 18/19 hoat dong theo co che cay component. Khi mot loi Javascript runtime xay ra trong qua trinh render (vi du TypeError), neu khong co Error Boundary gan nhat bat lai, loi se tiep tuc lan truyen len root.
   - Vi `router.tsx` khong co `errorElement` o cap route, bat ky loi render nao tai cac trang nghien cuu (`MarketResearch`, `Forex`, `OptionsLab`) deu se danh sap toan bo cay DOM cua ung dung ve `main.tsx`. Dieu nay gay trai nghiem nguoi dung rat kem vi mat het ca menu dieu huong, buoc phai F5 lai trang.
   - Dong thoi, viec nuot loi am tham (silent catch) tai `ReportArtifactCard.tsx` lam nguoi dung bam vao nut tai bao cao ma khong he co phan hoi gi khi co loi mang, va bieu tuong tick xanh gay hieu lam rang bao cao da san sang mac du tac vu backend da that bai (`status === "failed"`).

4. **Tu Quan sat 1.4.1 - 1.4.5:**
   - Toan bo he thong bieu do ECharts va cac the thong tin giao dich deu phu thuoc vao du lieu bat dong bo tu API. Trong thuc te mang hoac khi pipeline chay gap ngoai le, du lieu tra ve co the bi thieu, rong hoac null o mot so truong chi so (`actual_sharpe`, `information_ratio`, `quote_at`, `evidence_refs`, `leverage`).
   - Viec goi truc tiep cac ham `.toFixed()`, `.map()`, `.toLowerCase()`, `.replace()`, `.slice()`, `.toISOString()` ma khong co kiem tra an toan (null-safety / optional chaining / default fallback) la nguyen nhan goc re dan den cac loi sập ung dung (crash) dot ngot tren giao dien nguoi dung.

---

## 3. CAVEATS (CAC DIEM LUU Y VA GIOI HAN)

- **Gioi han dieu tra Read-Only**: Cuoc khao sat duoc thuc hien hoan toan duoi che do doc (read-only), khong sua doi truc tiep ma nguon ung dung.
- **Moi truong chay thuc te**: Cac kich ban loi runtime duoc danh gia va xac minh thong qua phan tich tinh ma nguon (static code analysis), luong du lieu tuong tac giua Frontend va Backend routes, chu khong chay trinh duyet headless (Playwright/Puppeteer) trong luot danh gia nay de dam bao an toan cho moi truong hien tai.
- **Kha nang mo rong**: Mot so endpoint thieu trong `api.ts` co the da duoc mot vai component goi rieng bang `fetch()` tam thoi ma chua duoc thong ke het neu khong nam trong cac thu muc component chinh.

---

## 4. CONCLUSION (KET LUAN VA DANH GIA MUC DO UU TIEN)

### Bang Tong hop Loi va Muc do Uu tien

| ID | Phan loai | File va Dong | Muc do | Nguyen nhan goc re | Huong khac phuc de xuat |
|---|---|---|---|---|---|
| F-01 | Crash / TypeError | `frontend/src/components/charts/ValidationPanel.tsx:45-95` & `AttributionTab.tsx:171` | **CRITICAL** | Goi `.toFixed()` tren gia tri `null` hoac `undefined` ma khong kiem tra an toan | Tao ham tien ich an toan `fmtNum(v, d)` tra ve `"-"` khi `v == null` hoac `!Number.isFinite(v)`. |
| F-02 | Crash / RangeError | `frontend/src/components/chat/ForexTradeCards.tsx:36, 93, 95` | **CRITICAL** | `new Date(value).toISOString()` nem RangeError neu chuoi khong hop le; `.join()` va `.slice()` tren truong undefined | Su dung ham wrap parse date co try/catch hoac kiem tra `isNaN(Date.parse(value))`; dung `plan.evidence_hash?.slice(0, 16) ?? "—"`, `(r.evidence_refs ?? []).join(", ")`. |
| F-03 | Crash / TypeError | `frontend/src/components/chat/MandateProposalCard.tsx:40, 46` | **HIGH** | `leverage.toLowerCase()` va `universe.replace()` tren bien undefined/null | Kiem tra `if (!leverage) return i18n.t("mandate.noLeverage");` va `if (!universe) return "—";`. |
| F-04 | Crash / ECharts | `frontend/src/components/charts/EquityChart.tsx`, `CorrelationMatrix.tsx`, `AnnualReturnsChart.tsx`, `MonthlyReturnsHeatmap.tsx`, `DistributionChart.tsx`, `OptionsPayoffChart.tsx` | **HIGH** | `useChartLifecycle` chay `.map()` va `.length` khi props bi undefined/null | Thuc hien early guard ben trong callback cua hook: `if (!data || !Array.isArray(data) || data.length === 0) return {};`. |
| F-05 | UI / UX Fragility | `frontend/src/router.tsx:1-85` | **HIGH** | Thieu `errorElement` o cap Route con, khien toan bo App bi unmount ve man hinh loi goc khi mot component con bi loi | Bo sung `errorElement: <RouteErrorFallback />` cho root layout va cac route nhanh con trong `createBrowserRouter`. |
| F-06 | Silent Failure | `frontend/src/components/chat/ReportArtifactCard.tsx:42-50, 107` | **HIGH** | Nuot loi download trong khoi catch rong; luon hien tick xanh thanh cong ke ca khi job failed | Goi `toast.error("Không thể tải báo cáo...")` trong catch; kiem tra `job.status === "failed"` de render UI canh bao that bai kem ly do thay vi tick xanh. |
| F-07 | Contract Drift | `frontend/src/lib/research.ts:40-52` vs `agent/src/api/research_routes.py:144-162` | **MEDIUM** | `CryptoRequest.period` la `string` thay vi `Literal`, `limit` thieu rang buoc so | Chuyen `period?: "5m" | "15m" | "30m" | "1h" | "2h" | "4h" | "6h" | "12h" | "1d"`, rang buoc UI input limit tu 2 den 100. |
| F-08 | Missing API | `frontend/src/lib/api.ts:1930-2005` | **MEDIUM** | Thieu cac API Scheduled Runs: status, playbooks, playbook details, tao run tu playbook | Bo sung cac phuong thuc: `getScheduledRunsStatus()`, `getResearchPlaybooks()`, `getResearchPlaybook(slug)`, `createScheduledRunFromPlaybook(slug, body)`. |
| F-09 | Missing API | `frontend/src/lib/api.ts:1860-1875` | **MEDIUM** | Thieu `getRunnerSettings` (chi co PUT `saveRunnerSettings`) | Bo sung `getRunnerSettings: (broker?: string) => request<RunnerSettings>(...)`. |
| F-10 | Missing API | `frontend/src/lib/api.ts:2245-2252` | **MEDIUM** | Thieu `getAccount` va `stepPaperTrade` trong `paperApi` | Bo sung day du cac phuong thuc paper trade tuong ung voi `paper_trade_routes.py`. |
| F-11 | Architecture Drift | `frontend/src/components/chat/ContextMemoryPanel.tsx:38, 53` & `QVerisSettings.tsx:47-66` | **LOW** | Goi `fetch()` truc tiep bo qua `apiClient` tap trung | Tich hop cac endpoint vao `api.ts` va su dung thong nhat qua doi tuong `api`. |

---

## 5. VERIFICATION METHOD (PHUONG PHAP XAC MINH DOC LAP)

Cac ky su lap trinh va kiem thu co the xac minh doc lap cac phat hien tren thong qua cac buoc sau:

### 5.1. Kiem tra Tinh hop le kieu TypeScript (Static Type Check)
Chay lenh kiem tra TypeScript tren thu muc `frontend`:
```powershell
cd D:\Vibe-Trading\frontend
npm run typecheck # hoac npx tsc --noEmit
```
Ket qua ky vong: Cac file nhu `research.ts` cho phep truyen string vao `period` ma trinh bien dich khong canh bao, nhung khi chay API thuc te voi period bat ky ngoai danh sach Literal se nhan ma loi HTTP 422 tu backend.

### 5.2. Kiem tra Unit Test va Snapshot hien co
Chay bo kiem thu frontend voi Vitest:
```powershell
cd D:\Vibe-Trading\frontend
npx vitest run src/components/charts/__tests__/AttributionTab.test.tsx
npx vitest run src/components/charts/__tests__/CorrelationMatrix.test.tsx
```

### 5.3. Kiem tra Test case tai lap loi Crashes (Reproduction Test Snippet)
De tai lap loi crash F-01 va F-02, them mot test case render component voi prop gia lap:
```typescript
// Test case tai lap loi AttributionTab khi information_ratio = null
render(<AttributionTab metrics={{ information_ratio: null } as any} />);
// Ket qua: Nem loi TypeError: Cannot read properties of null (reading 'toFixed')

// Test case tai lap loi ForexTradeCards khi quote_at = ""
render(<ForexTradeCards plan={{ quote_at: "", expires_at: "invalid" } as any} />);
// Ket qua: Nem loi RangeError: Invalid time value
```

### 5.4. Dieu kien vo hieu hoa ket luan (Invalidation Conditions)
Ket luan trong bao cao nay se bi vo hieu hoa neu:
1. `ValidationPanel.tsx` va `AttributionTab.tsx` duoc boc boi cac ham filter san du lieu truoc khi truyen vao props o toan bo cac noi su dung.
2. FastAPI backend bo cau hinh `ConfigDict(extra="forbid")` va chuyen `period` sang chap nhan moi chuoi `str`.
3. Tat ca cac bieu do ECharts duoc dam bao 100% khong bao gio nhan gia tri `undefined` hoac mang rong tu state cua component cha.
