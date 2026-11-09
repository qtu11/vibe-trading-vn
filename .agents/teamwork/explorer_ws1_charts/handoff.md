# BAO CAO BAN GIAO KIEM TOAN KIEN TRUC (HANDOFF REPORT) - WORKSTREAM 1

Ngay lap: 2026-11-08
Nguoi thuc hien: Explorer Subagent (explorer_ws1_charts)
Muc tieu: Workstream 1: Multi-Dimensional Financial Chart Architecture & Real-Time Candlestick Engines
Tai lieu phan tich chi tiet: D:\Vibe-Trading\.agents\teamwork\explorer_ws1_charts\analysis.md

---

## 1. OBSERVATION (QUAN SAT THUC TE)

### 1.1. Danh muc va kien truc thanh phan bieu do:
- **ECharts Core Initialization**: File `frontend/src/lib/echarts.ts:1-39` khai bao tree-shaking voi `CandlestickChart`, `LineChart`, `BarChart`, `HeatmapChart`, `PieChart`, `TreemapChart` (dong 2, 18), `CanvasRenderer` (dong 24), hang so `CHART_GROUP = "quant-charts"` (dong 27) va ham `connectCharts()` (dong 31-36).
- **Hook vong doi chuan**: File `frontend/src/hooks/useChartLifecycle.ts:18-56` quan ly `ResizeObserver` boc trong `requestAnimationFrame` (dong 42-48), cap nhat voi `{ notMerge: true }` (dong 53), va `chart.dispose()` khi unmount (dong 25-32).
- **Bieu do tron (Pie/Allocation)**:
  - Khong co file doc lap `AssetAllocationChart.tsx`.
  - Bieu do phan bo danh muc duoc viet inline trong `frontend/src/pages/Portfolio.tsx:606-637` (`function AllocationPie`), su dung `series: [{ type: "pie", radius: ["46%", "70%"] }]` va `window.addEventListener("resize", resize)` (dong 633). Moi lan `data` thay doi, component dispose va khoi tao lai instance ECharts tu dau (dong 613, 634-635).
- **Bieu do cot (Bar/Waterfall/PnL)**:
  - `frontend/src/components/charts/AnnualReturnsChart.tsx:1-83`: Su dung `useChartLifecycle`, hien thi loi nhuan hang nam dang cot xanh/do co `markLine` tai yAxis=0 (dong 66-72).
  - `frontend/src/components/charts/AttributionWaterfallChart.tsx:1-127`: Su dung `buildWaterfallBars` (dong 16-30) voi 2 series bar xep chong (`stack: "waterfall"`, dong 107, 117), series co so trong suot de tao hieu ung thac nuoc loi nhuan Brinson.
  - `frontend/src/components/charts/DistributionChart.tsx:1-110`: Histogram mau mo phong Monte Carlo; tai dong 99 su dung `new ResizeObserver(() => chart.resize())` khong co rAF.
  - `frontend/src/components/charts/WalkForwardChart.tsx:1-108`: Cot OOS returns kem duong Sharpe; tai dong 97 su dung `new ResizeObserver(() => chart.resize())` khong co rAF.
  - `frontend/src/components/charts/StrategyResearchDashboard.tsx:188-197`: Bar chart PnL cho 60 lenh thoat vi the gan nhat.
- **Bieu do duong (Line/Equity/Beta/Alpha/Benchmark)**:
  - `frontend/src/components/charts/EquityChart.tsx:1-122`: He thong 2 Grid (Grid 0 cho Equity, Grid 1 cho Drawdown%), co `markArea` vung sut giam (dong 89-100) va `markLine` Max Drawdown (dong 107-111).
  - `frontend/src/components/charts/RollingBetaAlphaChart.tsx:1-113`: 1 Grid, 2 truc Y doc lap (Y0 cho Beta, Y1 cho Alpha% hang nam).
  - `frontend/src/components/charts/AttributionCumulativeChart.tsx:1-102`: 3 duong so sanh Portfolio, Benchmark va Active Return.
  - `frontend/src/pages/Compare.tsx:120-220` (`EquityChartOverlay`): So sanh 2 duong cong loi nhuan co rebase ve moc 100, ket noi `CHART_GROUP` va co rAF resize (dong 130, 214-220).
  - `frontend/src/components/charts/MiniEquityChart.tsx:1-59`: Sparkline thu nho 80px co rAF resize.
  - `frontend/src/components/charts/RegimeTimeline.tsx:1-145`: Duong mat do che do thi truong kem cac dot khung hoang.
  - `frontend/src/components/charts/MonteCarloPathsChart.tsx:1-140`: Hang tram duong mo phong nhe ket hop vung shaded percentile P5-P95, P25-P75. Dong 129 goi `ResizeObserver` truc tiep khong co rAF.
- **Bieu do nen Nhat (Candlestick)**:
  - `frontend/src/components/charts/CandlestickChart.tsx:1-354`: Day du overlay MA5/10/20/60, EMA12/26, BOLL; sub-charts Vol, MACD, RSI, KDJ; trade markers BUY/SELL co `escapeHtml`; timeframe range filter; dung `echarts.init`, `chart.group = CHART_GROUP`, `connectCharts()` va rAF resize.
  - `frontend/src/components/forex/ForexCandlePlot.tsx:1-66`: Nen realtime MT5, `useUTC: true` (dong 20), nen dang hinh thanh giam opacity va vien day (`borderWidth: 2, opacity: .7`, dong 50), 2 duong Bid/Ask markLine (dong 52-54), Grid 1 cho Tick count (dong 57-58). Nhung tai dong 37 goi `ResizeObserver` thieu rAF, va khong gan `chart.group = CHART_GROUP`.
  - `frontend/src/components/forex/ForexLiveChart.tsx:1-65`: Polling du lieu MT5 moi ~3 giay qua hook `useForexChart.ts`, co timer 1 giay gay re-render.
  - `frontend/src/components/forex/ForexPlanChart.tsx:1-21`: Lazy-mount chart khi nguoi dung mo accordion.
  - `frontend/src/components/charts/ChartBlock.tsx:1-179`: Parse Markdown code fence `chart` do AI Agent sinh ra, kiem tra hinh hoc OHLC va render qua `CandlestickChart`.

### 1.2. Pipeline Realtime va Du lieu Broker XAU/USD:
- **MT5 Adapter** (`agent/src/trading/forex/adapters/mt5_worker.py:181-228`):
  - Doc tick: `mt5.symbol_info_tick(symbol)` tra ve `bid`, `ask`, `time_msc`, `point`.
  - Doc nen: `_rates(..., start_pos=0)` cho chart gom nen dang chay; `_rates(..., start_pos=1)` cho research chi gom nen dong.
  - Khoa: `terminal_read_lock` cho toi da 10 giay, ngan ngua xung dot voi lenh dat/sua vi the.
- **Exness Adapter** (`agent/src/trading/forex/adapters/exness.py:170-190`):
  - Ky Ed25519; ho tro doc tick thoi gian thuc qua WebSocket `wss://.../server-events/ws/ticks` (dong 178-185).
- **OANDA Adapter** (`agent/src/trading/forex/adapters/oanda.py:80-140`):
  - REST API `/v3/accounts/.../pricing` va `/candles`, tra ve mid/bid/ask; gioi han 4 cap nhat/giay.

---

## 2. LOGIC CHAIN (CHUOI LAP LUAN TU QUAN SAT DEN KET LUAN)

1. **Tu Quan sat ve `AllocationPie` trong `Portfolio.tsx:613, 634-635`**:
   - `AllocationPie` khoi tao `echarts.init` moi khi `data` hoac `instance.language` thay doi.
   - Khi tai khoan duoc lam moi hoac loc, toan bo canvas ECharts bi xoa va tao moi thay vi cap nhat option.
   - Dong thoi dung `window.resize` thay vi `ResizeObserver`.
   - **Suy luan**: Gay lang phi tai nguyen bo nho GPU, giat giao dien va khong tu dong co gian khi nguoi dung mo rong panel hoac thanh ben.

2. **Tu Quan sat ve viec thieu `requestAnimationFrame` trong `ForexCandlePlot.tsx:37`, `DistributionChart.tsx:99`, `WalkForwardChart.tsx:97`, `MonteCarloPathsChart.tsx:129`**:
   - Cac component nay dang ky `new ResizeObserver(() => chart.resize())` va goi `chart.resize()` dong bo ngay trong callback.
   - Trinh duyet khi thay doi kich thuoc cua so co the phat sinh hang chuc su kien resize trong mot frame 16ms.
   - **Suy luan**: Goi `chart.resize()` dong bo gay hien tuong layout thrashing nghiem trong, lam giam FPS va gay lag giao dien. Trong khi do, `useChartLifecycle.ts:42-48` da co san co che `cancelAnimationFrame` + `requestAnimationFrame` chuan xac nhung chua duoc tai su dung o cac file tren.

3. **Tu Quan sat ve `useForexChart.ts:33` va `agent/src/trading/forex/chart.py`**:
   - Luong bieu do Forex/XAU/USD hien tai van la HTTP Polling moi ~3 giay (`timer = setTimeout(poll, 3000)`).
   - Moi lan polling tra ve snapshot gom toi da 200 - 300 nến va bao gia quote moi nhat.
   - **Suy luan**: Day la kien truc an toan va de kiem soat cho giai doan dau, nhung khong phai la real-time tick streaming thuc thu. Neu chuyen sang nhan tick tu Exness WS hoac MT5 stream voi toc do 30-60 ticks/giay ma khong co bo dem micro-batch, trinh duyet se bi khoa cung boi cac lenh `setOption` lien tuc.

4. **Tu Quan sat ve `CHART_GROUP = "quant-charts"` va `CandlestickChart.tsx:271`**:
   - Cac bieu do hien tai dung `xAxis.type = "category"` voi du lieu la mang chuoi thoi gian `dates`.
   - Ham `echarts.connect(CHART_GROUP)` chi dong bo duoc giua cac bieu do co cung so luong phan tu va cung chi so index category (hoac cung chuoi category).
   - Khi mo bo 4 bieu do da khung thoi gian (M1, M5, H1, D1): M1 co 1440 bars, H1 chi co 24 bars.
   - **Suy luan**: Dong bo con tro chu thap mat dinh cua ECharts se bi lech moc thoi gian hoac loi index vuot bien, khong dap ung duoc yeu cau phan tich da khung thoi gian chuyen nghiep cua trader.

---

## 3. CAVEATS (CAC DIEM CHUA KHAO SAT VA GIA DINH)

- **Cac diem chua khao sat sau**:
  - Chua kiem tra runtime truc tiep tren thiet bi dong ket noi MT5 Terminal thuc te (do moi truong hien tai la Agent moi truong khong co Terminal MT5 dang chay).
  - Chua benchmark GPU memory foot-print tren cac thiet bi di dong / man hinh cam ung Retina do phan giai cao (2x, 3x pixel ratio).
- **Gia dinh**:
  - Gia dinh rang cac broker MT5 va Exness van duy tri on dinh cau truc du lieu tick va nến nhu da khai bao trong cac test fixtures cua repository.

---

## 4. CONCLUSION (KET LUAN VA DE XUAT HANH DONG)

He thong bieu do cua Vibe-Trading da duoc xay dung rat cong phu, tuan thu tot cac quy tac ve an toan du lieu (chong XSS bang `escapeHtml`), su dung tree-shaking ECharts 6.1 sach se, va co hook `useChartLifecycle` duoc thiet ke chuan mau.

Tuy nhien, de tro thanh mot he thong bieu do tai chinh da chieu thoi gian thuc dat chuan institutional-grade, can thuc hien 4 nang cap kien truc sau:
1. **Dong bo hoa toan bo cac bieu do ve `useChartLifecycle`**:
   - Sua `ForexCandlePlot.tsx`, `DistributionChart.tsx`, `WalkForwardChart.tsx`, `MonteCarloPathsChart.tsx` de su dung `useChartLifecycle` hoac them co che `cancelAnimationFrame` + `requestAnimationFrame`.
   - Tach `AllocationPie` trong `Portfolio.tsx` thanh component doc lap `AssetAllocationChart.tsx` va loai bo viec re-init instance ECharts khi du lieu thay doi.
2. **Bo sung React.memo cho `ForexCandlePlot.tsx`**:
   - Ngan ngua re-render thua moi giay tu timer 1s cua `ForexLiveChart.tsx`.
3. **Thiet ke Dual-Tier Event Buffering cho Realtime Tick Engine**:
   - Xay dung bo dem Ring Buffer tai frontend hook de gom nhieu tick thanh mot nhip render duy nhat tren moi frame rAF (16ms) khi ket noi luong stream XAU/USD.
4. **Xay dung Engine Dong bo Con tro chu thap da khung thoi gian (Crosshair Event Bus)**:
   - Su dung co che Event-driven: bat su kien `updateAxisPointer` tren bieu do nguon, lay timestamp epoch, tim kiem nhi phan `targetIndex` tren cac bieu do dich (M1, M5, H1, D1) va phat lenh `chart.dispatchAction({ type: 'showTip', dataIndex: targetIndex })`.

---

## 5. VERIFICATION METHOD (PHUONG PHAP KIEM CHUNG DOC LAP)

1. **Kiem tra Unit Test va Consistency cua cac bieu do**:
   Chay lenh kiem thu tren PowerShell tai thu muc `frontend`:
   ```powershell
   cd d:\Vibe-Trading\frontend
   npm test -- src/components/charts/__tests__/ChartOptionConsistency.test.tsx
   npm test -- src/hooks/__tests__/useChartLifecycle.test.tsx
   npm test -- src/hooks/__tests__/useForexChart.test.tsx
   ```
2. **Kiem tra Lint va Typecheck**:
   ```powershell
   cd d:\Vibe-Trading\frontend
   npx tsc --noEmit
   ```
3. **Kiem tra khong con ResizeObserver thieu rAF**:
   Chay lenh tim kiem de kiem tra cac file con goi truc tiep `chart.resize()` trong ResizeObserver:
   ```powershell
   cd d:\Vibe-Trading\frontend
   Select-String -Path "src\components\*.tsx", "src\pages\*.tsx" -Pattern "ResizeObserver\(\(\) =>.*resize\(\)\)"
   ```
   Dieu kien vo hieu hoa (Invalidation Condition): Neu bat ky bieu do nao van goi `chart.resize()` dong bo ma khong qua rAF, he thong van con ton tai nguy co layout thrashing.
