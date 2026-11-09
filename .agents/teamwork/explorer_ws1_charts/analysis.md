# BAO CAO KHIA CANH KIEN TRUC VA HIEU NANG HE THONG BIEU DO TAI CHINH (WORKSTREAM 1)

Ngay khao sat: 2026-11-08
Pham vi: He thong bieu do da chieu, pipeline tick-to-candlestick realtime cho Co phieu va XAU/USD, toi uu hoa vong doi va hieu nang Apache ECharts 6.1 trong d:\Vibe-Trading.

---

## MUC LUC
1. Tong quan kien truc bieu do tai chinh da chieu
2. Kiem toan chi tiet toan bo thanh phan bieu do frontend
   2.1. Nhom bieu do tron (Pie Charts & Allocation)
   2.2. Nhom bieu do cot (Bar Charts, PnL & Waterfalls)
   2.3. Nhom bieu do duong (Line Charts & Benchmark Comparisons)
   2.4. Nhom bieu do nen Nhat (Candlestick Charts & Forensic Panels)
3. Khao sat chuyen sau pipeline realtime tu Tick sang Nen (Tick-to-Candlestick Pipeline)
   3.1. So sanh co che du lieu: Co phieu (US, VN, HK, CN) vs Forex/Hang hoa (XAU/USD Gold)
   3.2. Cau truc du lieu: OHLCV, ticks, bid/ask spread, do chinh xac (precision), khoi luong va dinh dang thoi gian
   3.3. Khao sat cac kenh du lieu truc tiep tu broker cho XAU/USD (MT5, Exness, OANDA)
4. Danh gia hieu nang va vong doi Apache ECharts 6.1 (Performance & Lifecycle Profiling)
   4.1. Co che dem su kien WebSocket / SSE (Batch Updates vs Per-Tick Render)
   4.2. Dieu tiet requestAnimationFrame (rAF) va quan ly event loop
   4.3. Ve sinh DOM, giai phong bo nho (unmount hygiene, resize listeners, chong memory leak)
   4.4. Dong bo hoa con tro chu thap da khung thoi gian (Multi-Timeframe Crosshair Sync M1, M5, H1, D1)
5. Bang tong hop loi kien truc va de xuat nang cap san xuat

---

## 1. TONG QUAN KIEN TRUC BIEU DO TAI CHINH DA CHIEU

He thong frontend cua Vibe-Trading su dung Apache ECharts phien ban 6.1.0 (`frontend/package.json:21`) ket hop cung React 19 (`frontend/package.json:27`), TailwindCSS va Zustand.

Kien truc bieu do hien tai duoc chia thanh ba tang tieu thu ro ret:
- **Tang khoi tao loi he thong (`frontend/src/lib/echarts.ts`)**: Su dung co che Tree-shaking module ECharts Core (`echarts/core`), dang ky cac bieu do `CandlestickChart`, `LineChart`, `BarChart`, `HeatmapChart`, `PieChart`, `TreemapChart` (dong 2, 18) cung cac component tro giup nhu `GridComponent`, `TooltipComponent`, `DataZoomComponent`, `MarkLineComponent`, `MarkAreaComponent`, `VisualMapComponent`, `GraphicComponent` va `CanvasRenderer` (dong 4-25). Khai bao hang so nhom dong bo con tro toan cuc `CHART_GROUP = "quant-charts"` (dong 27) va ham ket noi `connectCharts()` (dong 31-36).
- **Tang Hook quan ly vong doi dung chung (`frontend/src/hooks/useChartLifecycle.ts`)**: Cung cap hook `useChartLifecycle` de dong bo viec khoi tao ECharts tren mot DOM `ref`, cap nhat option voi `{ notMerge: true }`, theo doi thay doi kich thuoc bang `ResizeObserver` ket hop `requestAnimationFrame`, va goi `chart.dispose()` khi unmount.
- **Tang thanh phan chuyen biet (Specialized Components)**: Nam tai `frontend/src/components/charts/` (phuc vu backtest run, phan tich nhan to factor, ma tran tuong quan, phan phoi xac suat, dinh gia options) va `frontend/src/components/forex/` (phuc vu phan tich thi truong ngoai hoi va vang XAU/USD thoi gian thuc tu MT5).

---

## 2. KIEM TOAN CHI TIET TOAN BO THANH PHAN BIEU DO FRONTEND

### 2.1. Nhom bieu do tron (Pie Charts & Allocation)

**1. `AllocationPie` trong `frontend/src/pages/Portfolio.tsx` (dong 606 - 637):**
- **Vi tri ma nguon**: `frontend/src/pages/Portfolio.tsx:606-637`.
- **Muc dich nghiep vu**: Hien thi ty trong phan bo danh muc theo tai khoan moi gioi (`brokerAllocation`, dong 304-311) va theo ma nam giu (`holdingAllocation`, dong 313-329).
- **Kieu bieu do**: ECharts Pie dang Donut (`series: [{ type: "pie", radius: ["46%", "70%"], center: ["50%", "43%"], padAngle: 2, itemStyle: { borderRadius: 5 } }]`, dong 627).
- **Diem quan sat kien truc**:
  - Khong co file component tach roi mang ten `AssetAllocationChart.tsx`; component nay duoc viet private inline duoi dang `function AllocationPie` ngay trong file page `Portfolio.tsx`.
  - Bieu do su dung graphic text o tam donut de hien thi tong gia tri danh muc (`centerLabel`, dong 628).
  - Mau sac duoc dong bo voi mau broker dinh san qua `BROKER_COLORS` hoac `HOLDING_COLORS` (dong 614-615).
  - Tich hop su kien click truc tiep `chart.on("click", select)` de filter bang holdings ben duoi (dong 631-633).
- **Loi vong doi va hieu nang phat hien**:
  - `AllocationPie` **khong su dung** hook `useChartLifecycle`.
  - Bieu do su dung `window.addEventListener("resize", resize)` (dong 633) thay vi `ResizeObserver`. Neu container thay doi kich thuoc do dong/mo sidebar ma kich thuoc cua so window khong doi, bieu do se khong resize.
  - Mang dependencies cua `useEffect` la `[data, centerLabel, onSelect, dark, instance.language]` (dong 635). Moi khi `data` thay doi (khi refresh tai khoan hoac nhan ket qua socket/polling), toan bo instance ECharts bi huy (`chart.dispose()`) va khoi tao lai tu dau (`echarts.init`), gay giat man hinh va tieu ton CPU khong can thiet thay vi chi goi `chart.setOption`.

---

### 2.2. Nhom bieu do cot (Bar Charts, PnL & Waterfalls)

**1. `AnnualReturnsChart.tsx` (`frontend/src/components/charts/AnnualReturnsChart.tsx:1-83`):**
- **Vi tri ma nguon**: `frontend/src/components/charts/AnnualReturnsChart.tsx:1-83`.
- **Muc dich nghiep vu**: Bieu thi loi nhuan hang nam (Annualized Returns) theo tung nam duoi dang cac cot duong/am.
- **Kien truc**: Su dung chuan `useChartLifecycle` (dong 15). Cot duong mang mau `t.upColor`, cot am mang mau `t.downColor` (dong 56). Co duong phan chia moc 0% bang `markLine: { data: [{ yAxis: 0 }] }` (dong 66-72).
- **Danh gia**: Dat chuan cach ly vong doi, co nhan truc ty le phan tram hop le.

**2. `AttributionWaterfallChart.tsx` (`frontend/src/components/charts/AttributionWaterfallChart.tsx:1-127`):**
- **Vi tri ma nguon**: `frontend/src/components/charts/AttributionWaterfallChart.tsx:1-127`.
- **Muc dich nghiep vu**: Bieu do thac nuoc (Waterfall) phan ra loi nhuan theo mo hinh Brinson-Fachler gom: Benchmark, Allocation Effect, Selection Effect, Interaction Effect, va Portfolio Return (dong 16-30).
- **Kien truc**: Su dung 2 series bar xep chong (`stack: "waterfall"`, dong 107, 117). Series dau tien la placeholder trong suot (`itemStyle: { color: "transparent" }`, dong 110) de nang chan cot hieu ung len do cao cua bar truoc do, tao hieu ung thac nuoc chuan toan hoc.
- **Danh gia**: Thuat toan `buildWaterfallBars` (dong 16-30) tinh toan chan de chinh xac; su dung `useChartLifecycle` dong bo.

**3. Bieu do PnL tung lenh trong `StrategyResearchDashboard.tsx` (`frontend/src/components/charts/StrategyResearchDashboard.tsx:188-197`):**
- **Vi tri ma nguon**: `frontend/src/components/charts/StrategyResearchDashboard.tsx:188-197`.
- **Muc dich nghiep vu**: Hien thi PnL loi nhuan/thua lo cua 60 lenh thoat vi the gan nhat.
- **Kien truc**: `type: "bar"`, mau xanh la (`GREEN = "#3b9b8f"`) cho lenh lai, mau cam (`ORANGE = "#ff8a3d"`) cho lenh lo.
- **Loi vong doi**: Khoi tao truc tiep 3 instance bieu do cung luc (`navChart, riskChart, tradeChart`) trong 1 hook `useEffect` (dong 140-209).

**4. `DistributionChart.tsx` (`frontend/src/components/charts/DistributionChart.tsx:1-110`):**
- **Vi tri ma nguon**: `frontend/src/components/charts/DistributionChart.tsx:1-110`.
- **Muc dich nghiep vu**: Bieu do histogram tan suat phan phoi mau mo phong Monte Carlo / Bootstrap Sharpe ratio kem duong danh dau gia tri thuc te (`markerValue`) va dai khoang tin cay (`bandFrom`, `bandTo`).
- **Loi hieu nang**: Dong 99: `const ro = new ResizeObserver(() => chart.resize()); ro.observe(ref.current!);`. Thieu `cancelAnimationFrame` va `requestAnimationFrame`, dan den layout thrashing khi resize lien tuc.

**5. `WalkForwardChart.tsx` (`frontend/src/components/charts/WalkForwardChart.tsx:1-108`):**
- **Vi tri ma nguon**: `frontend/src/components/charts/WalkForwardChart.tsx:1-108`.
- **Muc dich nghiep vu**: Bieu thi loi nhuan Out-of-Sample (OOS) tung cua so Walk-Forward dang cot kep voi duong Sharpe ratio (dong 72-94).
- **Loi hieu nang**: Dong 97 goi truc tiep `new ResizeObserver(() => chart.resize())` khong co rAF.

---

### 2.3. Nhom bieu do duong (Line Charts & Benchmark Comparisons)

**1. `EquityChart.tsx` (`frontend/src/components/charts/EquityChart.tsx:1-122`):**
- **Vi tri ma nguon**: `frontend/src/components/charts/EquityChart.tsx:1-122`.
- **Muc dich nghiep vu**: Bieu do duong cong von (Equity Curve) ket hop duong Drawdown% xep lop duoi hai he truc toa do rieng biet (Grid 0 tren va Grid 1 duoi).
- **Kien truc**:
  - He thong 2 grid: Grid 0 chiem 56% chieu cao (Equity), Grid 1 chiem 20% chieu cao (Drawdown), dong 59-62.
  - Tich hop vung do bong cac giai doan sut giam nghiem trong (`markArea`, dong 89-100) lay tu `drawdownZones`.
  - Tich hop duong `markLine` cho Max Drawdown tai Grid 1 (dong 107-111).
  - Su dung `useChartLifecycle` (dong 19) va `inside` dataZoom dong bo tren ca 2 truc X `xAxisIndex: [0, 1]` (dong 79).

**2. `RollingBetaAlphaChart.tsx` (`frontend/src/components/charts/RollingBetaAlphaChart.tsx:1-113`):**
- **Vi tri ma nguon**: `frontend/src/components/charts/RollingBetaAlphaChart.tsx:1-113`.
- **Muc dich nghiep vu**: Theo doi bien dong Rolling Beta va Rolling Alpha hang nam theo thoi gian so voi chi so chuan Benchmark.
- **Kien truc**: 1 Grid don nhung 2 truc Y doc lap (Truc Y0 cho Beta ben trai, Truc Y1 cho Alpha% ben phai, dong 65-80). Su dung `useChartLifecycle` (dong 16).

**3. `AttributionCumulativeChart.tsx` (`frontend/src/components/charts/AttributionCumulativeChart.tsx:1-102`):**
- **Vi tri ma nguon**: `frontend/src/components/charts/AttributionCumulativeChart.tsx`.
- **Muc dich nghiep vu**: So sanh duong cong tich luy giua Portfolio, Benchmark va Active Return.
- **Kien truc**: 3 duong rieng biet, dong bo itemStyle mau de swatch legend hien thi dung. Su dung `useChartLifecycle`.

**4. `EquityChartOverlay` trong `frontend/src/pages/Compare.tsx` (dong 120 - 220):**
- **Vi tri ma nguon**: `frontend/src/pages/Compare.tsx:120-220`.
- **Muc dich nghiep vu**: So sanh truc tiep hai chien luoc backtest hoac chien luoc so voi benchmark tren cung mot he truc toa do, co tuy chon quy chuan ve goc 100 (`rebase: boolean`, dong 142-143).
- **Kien truc**: Su dung `CHART_GROUP` va `connectCharts()` (dong 130-131). Co su dung `ResizeObserver` boc trong `requestAnimationFrame` (dong 214-220).

**5. `MonteCarloPathsChart.tsx` (`frontend/src/components/charts/MonteCarloPathsChart.tsx:1-140`):**
- **Vi tri ma nguon**: `frontend/src/components/charts/MonteCarloPathsChart.tsx:1-140`.
- **Muc dich nghiep vu**: Bieu do hinh quat (Fan Chart) ve hang tram duong mo phong Monte Carlo nhe (`opacity: 0.1`, dong 72) kem dai shaded percentiles P5-P95, P25-P75 bang ky thuat stacked area, duong trung vi P50 dashed, va duong thuc te actual dam net (dong 107-126).
- **Loi hieu nang**: Dong 129 goi `ResizeObserver` thieu rAF.

**6. `MiniEquityChart.tsx` (`frontend/src/components/charts/MiniEquityChart.tsx:1-59`):**
- **Vi tri ma nguon**: `frontend/src/components/charts/MiniEquityChart.tsx:1-59`.
- **Muc dich nghiep vu**: Sparkline thu nho (height 80px) hien thi tren the tom tat chien luoc, tu dong doi mau xanh/do dua vao diem dau va diem cuoi. Co rAF resize day du (dong 40-47).

**7. `RegimeTimeline.tsx` (`frontend/src/components/charts/RegimeTimeline.tsx:1-145`):**
- **Vi tri ma nguon**: `frontend/src/components/charts/RegimeTimeline.tsx:1-145`.
- **Muc dich nghiep vu**: Hien thi dong thoi gian che do thi truong (Correlation Regime Density) kem cac giai doan dong pha (Fused Episodes) bang `markArea`. Co rAF resize day du (dong 126-133).

---

### 2.4. Nhom bieu do nen Nhat (Candlestick Charts & Forensic Panels)

**1. `CandlestickChart.tsx` (`frontend/src/components/charts/CandlestickChart.tsx:1-354`):**
- **Vi tri ma nguon**: `frontend/src/components/charts/CandlestickChart.tsx:1-354`.
- **Muc dich nghiep vu**: Bieu do nen nhat da nang phuc vu phan tich ky thuat co phieu va danh gia ket qua backtest.
- **Kien truc noi bat**:
  - Day la component hoan thien nhat ve phan tich ky thuat trong he thong:
    - Overlay chi bao: MA5, MA10, MA20, MA60, EMA12, EMA26, Bollinger Bands (dong 17-25, 147-172).
    - Sub-charts tuy chon phia duoi: Volume, MACD (DIF, DEA, Histogram), RSI, KDJ (dong 200-224).
    - Trade Markers: Tich hop cac diem mua BUY ("B") va ban SELL ("S") truc tiep len nen bang `markPoint` co tooltip an toan chong XSS (`escapeHtml`, dong 176-186).
    - Backend custom indicators: Ho tro nhan chi bao dong tu backend va map O(1) qua JavaScript `Map` (dong 100-106).
  - Tuan thu quy uoc ECharts Candlestick: Map mang theo thu tu `[open, close, low, high]` (dong 81).
  - Gia lap timeframe zoom selector (1M, 3M, 6M, 1Y, ALL) bang ham `rangeStartIndex` (dong 30-46) dieu khien `dataZoom.startValue`.
  - Quan ly vong doi: Khoi tao `echarts.init`, gan `chart.group = CHART_GROUP`, goi `connectCharts()` (dong 111-114). Co co che `ResizeObserver` ket hop `requestAnimationFrame` va huy sach khi unmount (dong 116-130).
  - Khong destroy instance khi du lieu thay doi: `chart.setOption(..., true)` tren instance hien huu (dong 234-292).

**2. `ForexCandlePlot.tsx` (`frontend/src/components/forex/ForexCandlePlot.tsx:1-66`):**
- **Vi tri ma nguon**: `frontend/src/components/forex/ForexCandlePlot.tsx:1-66`.
- **Muc dich nghiep vu**: Ve nen nhat thoi gian thuc tu native MT5 terminal cho Forex va Vang XAU/USD.
- **Kien truc dac thu**:
  - Dat `useUTC: true` (dong 20) de dong bo gio quoc te cho giao dich ngoai hoi.
  - Phan tach ro ret nen da dong va nen dang hinh thanh (forming bar):
    - Nen dang hinh thanh co vien vien day va giam do mo: `itemStyle: b.complete ? undefined : { borderWidth: 2, opacity: .7 }` (dong 50).
  - Hien thi 2 duong gia Bid va Ask truc tiep tu broker qua `markLine` tren nen:
    - Duong Bid mau xanh/info (dong 53), duong Ask dashed mau vang/warning (dong 54).
  - Grid 0 cho Candlestick + EMA20 (dong 21, 55); Grid 1 cho Tick Volume bar (dong 21, 57-58).
  - Tooltip chuyen dung an toan: `forexCandleTooltip` (`frontend/src/lib/forexChart.ts:49-60`) giai ma du lieu nen va ngan chan HTML injection qua `escapeHtml`.
- **Cac diem yeu kien truc va hieu nang phat hien**:
  - **Khong tham gia `CHART_GROUP`**: Khong he co dong lenh `chart.group = CHART_GROUP` hay `connectCharts()`. Do do bieu do nay bi co lap hoan toan khoi co che crosshair sync toan he thong.
  - **ResizeObserver gay layout thrashing**: Dong 37: `const observer = new ResizeObserver(() => chart.resize());`. Thieu `requestAnimationFrame`.
  - **Khong dung React.memo**: Component bi re-render moi giay boi timer cua component cha `ForexLiveChart.tsx` (dong 15, 17).

**3. `ForexLiveChart.tsx` (`frontend/src/components/forex/ForexLiveChart.tsx:1-65`):**
- **Vi tri ma nguon**: `frontend/src/components/forex/ForexLiveChart.tsx:1-65`.
- **Muc dich nghiep vu**: Bọc ngoai `ForexCandlePlot`, quan ly ket noi MT5, lua chon khung thoi gian (5m, 1h, 4h, 1d), nut Pause/Resume, kiem tra do tuoi quote (`quoteAge <= max_age_seconds`), hien thi bang chung Price Action (cau truc swing HH/HL, ho tro/khang cu 20 bar, mau hinh Doji/Hammer/Engulfing) va bang OHLC tro giup tiep can (accessible table).
- **Kien truc**: Su dung hook `useForexChart` de polling du lieu MT5 moi ~3 giay.

**4. `ForexPlanChart.tsx` (`frontend/src/components/forex/ForexPlanChart.tsx:1-21`):**
- **Vi tri ma nguon**: `frontend/src/components/forex/ForexPlanChart.tsx:1-21`.
- **Muc dich nghiep vu**: Hien thi bieu do nen thu gon trong ket qua chat cua AI Agent, chi bat dau mount va polling khi nguoi dung nhan nut mo bieu do (`open === true`, dong 9, 18), giup tiet kiem ket noi MT5 va tai CPU.

**5. `ChartBlock.tsx` (`frontend/src/components/charts/ChartBlock.tsx:1-179`):**
- **Vi tri ma nguon**: `frontend/src/components/charts/ChartBlock.tsx:1-179`.
- **Muc dich nghiep vu**: Trinh thong dich Markdown code fence `chart` do AI Agent phat sinh qua cong cu `build_price_chart`. Parse du lieu JSON sang `PriceChartSpec`, kiem tra tinh toan ven hinh hoc OHLC (`low <= min(open, close) <= max(open, close) <= high`, dong 48), kiem tra gioi han 1.500 bars (dong 34, 86) va render qua `CandlestickChart`. Neu JSON chua hoan tat do dang stream SSE, bieu do se khong ve nua voi ma render trang thai cho hop le (dong 144-156).

---

## 3. KHAO SAT CHUYEN SAU PIPELINE REALTIME TU TICK SANG NEN (TICK-TO-CANDLESTICK PIPELINE)

### 3.1. So sanh co che du lieu: Co phieu (US, VN, HK, CN) vs Forex/Hang hoa (XAU/USD Gold)

| Dac tinh | Co phieu (US, VN, HK, CN) | Forex & Hang hoa (XAU/USD Gold) |
| :--- | :--- | :--- |
| **Co che cap nhat hien tai** | Batch Historical Loader & Snapshot API | HTTP Polling (3 giay/lan tu MT5) / WS Tick tai Exness |
| **Phien giao dich** | Phien co dinh (vi du VN: 9:00-15:00, US: 9:30-16:00 EST). Co nghi trua (CN, VN, HK). | Lien tuc 24/5 (Dong cua cuoi tuan tu toi thu Sau den chieu Chu Nhat). |
| **Khoang nghi (Market Gaps)** | Co qua dem (Overnight gap) va gio nghi trua. Khong tao nen gia chen vao khoang nghi. | Giao dich xuyen suot phien A, Au, My; gap chu yeu xuat hien dau tuan mo cua. |
| **Ban chat Khoi luong (Volume)** | Khoi luong khop lenh that (Exchanged traded volume - so co phieu) va gia tri giao dich. | **Tick Volume** (so lan thay doi bao gia tai broker), KHONG phai tong khoi luong toan cau. |
| **Bao gia (Quotes)** | Gia khop lenh gan nhat (Last traded price) + so lenh Level 2. | Cap gia hai chieu **Bid va Ask** lien tuc, co Chenh lech (Spread). |
| **Dinh dang gio** | Thuong tra ve gio dia phuong cua so giao dich (Local session time) hoac date string YYYY-MM-DD. | **UTC tuyet doi** theo chuan ISO-8601 (`YYYY-MM-DDTHH:mm:ssZ`). |
| **Nen 0 (Forming Bar)** | Thuong chi nap nen da dong (EOD bar). | Bat buoc phan tach nen 0 dang bien dong (`start_pos=0`) va cac nen da dong (`start_pos=1`). |

---

### 3.2. Cau truc du lieu: OHLCV, ticks, bid/ask spread, do chinh xac (precision), khoi luong va dinh dang thoi gian

#### 1. Quy uoc toa do ECharts vs Chuan Tai chinh Quoc te:
- Trong chuan tai chinh quoc te (ISO, FIX protocol, TradingView), thu tu OHLC la: `[Open, High, Low, Close]`.
- Trong Apache ECharts, thu tu quy dinh cho series `candlestick` la:
  `[Open, Close, Lowest, Highest]` (Chieu 0: Open, Chieu 1: Close, Chieu 2: Low, Chieu 3: High).
- **Kiem toan code**:
  - `frontend/src/components/charts/CandlestickChart.tsx:81`:
    `const candle = data.map(d => [d.open, d.close, d.low, d.high]);` -> Chuan xac theo ECharts `[open, close, low, high]`.
  - `frontend/src/components/forex/ForexCandlePlot.tsx:49`:
    `data: snapshot.bars.map(b => ({ value: [b.open, b.close, b.low, b.high], ... }))` -> Chuan xac theo ECharts.
  - `frontend/src/lib/forexChart.ts:56`:
    Khi doc nguoc tu tooltip: `const [open, close, low, high] = raw.slice(-4);` -> Chuan xac.

#### 2. Cau truc du lieu Tick va Spread cua XAU/USD:
Tai file `agent/src/trading/forex/adapters/mt5_worker.py:181-197`:
```python
def quote(self, symbol):
    info = self.instrument(symbol)
    tick = self.mt5.symbol_info_tick(symbol)
    stamp = getattr(tick, "time_msc", 0) / 1000 or tick.time
    return {
        "symbol": symbol,
        "bid": decimal_text(tick.bid),
        "ask": decimal_text(tick.ask),
        "timestamp": datetime.fromtimestamp(stamp, timezone.utc).isoformat(),
        "point": decimal_text(info.point),
        "price_step": decimal_text(getattr(info, "trade_tick_size", 0) or info.point),
        ...
    }
```
- **Do chinh xac (Precision)**: Voi XAU/USD (Vang), point thuong la `0.01` (2 chu so thap phan) hoac `0.001` (3 chu so tai mot so broker nhu Exness Pro). Do chinh xac nay duoc kiem soat bang `Decimal` trong Python va `Number.isFinite` tren frontend.
- **Spread**: Tinh bang `ask - bid`. Tren frontend duoc hien thi qua 2 duong MarkLine trong `ForexCandlePlot.tsx:52-54`.

#### 3. Cau truc du lieu Nen dang bien dong (Forming Bar):
Tai file `agent/src/trading/forex/chart.py:20-33`:
- Backend tinh toan trang thai hoan tat:
  `complete = stamp.timestamp() + SECONDS[timeframe] <= now.timestamp()`.
- Neu thoi gian hien tai chua vuot qua thoi luong cua khung gio (vi du 300 giay cho M5), nến mang co `complete: false`.
- Tong so nến `complete: false` trong cua so snapshot toi da chi duoc phep la 1 (dong 32: `sum(not b["complete"] for b in rows) > 1`). Neu lon hon 1, he thong quang loi `INVALID_CHART_DATA`.

---

### 3.3. Khao sat cac kenh du lieu truc tiep tu broker cho XAU/USD (MT5, Exness, OANDA)

#### 1. MetaTrader 5 (MT5):
- **Co che ket noi**: Subprocess worker chay Python SDK `MetaTrader5` tren Windows (`agent/src/trading/forex/adapters/mt5_worker.py`).
- **Co che doc nen**:
  - `start_pos=0`: Doc ca nến 0 dang hinh thanh cho chart (`mt5_worker.py:203`).
  - `start_pos=1`: Chi doc nến da dong cho research va chien luoc (`mt5_worker.py:200`).
- **Khoa truy cap (Concurrency Lock)**: Su dung `terminal_read_lock` (`mt5_worker.py:34-51`) voi thoi gian cho toi da 10 giay truoc khi attach SDK, giai quyet triet de tinh trang tranh chap tai nguyen terminal giua doc tai khoan va doc bieu do.
- **Han che hien tai**: Van la co che HTTP polling moi 3 giay tu frontend, chua phai mot streaming socket truc tiep day tick vao trinh duyet.

#### 2. Exness:
- **Co che ket noi**: `agent/src/trading/forex/adapters/exness.py`. Ket noi Exness Trader API qua HTTPS REST va WebSocket ticks (`wss://.../server-events/ws/ticks`, dong 178-185).
- **Ky xac thuc**: Su dung khoa bat doi xung Ed25519 (`exness_auth.py:15-16`) de ky moi request HTTP va WebSocket handshake.
- **Gioi han toc do (Rate Limiting)**: Tich hop san co che throttle request theo sliding window (`exness.py:57-80`).
- **Tiem nang Realtime**: Exness da co san websocket nhan tick su kien (`socket.recv()`, dong 188), la ung vien ly tuong nhat trong backend hien tai de chuyen doi sang streaming tick engine.

#### 3. OANDA:
- **Co che ket noi**: `agent/src/trading/forex/adapters/oanda.py`. Su dung OANDA v20 REST API (`https://api-fxtrade.oanda.com/v3/accounts/...`).
- **Lay nen**: Endpoint `/instruments/{symbol}/candles` voi `price=M` (mid price), dong 131-133.
- **Han che**: Adapter hien tai chi thuc hien REST call; OANDA Pricing Stream chua duoc tich hop thanh mot luong stream dai han (dong 69-70 tai `docs/FOREX_XAUUSD_LAB.md`).

---

## 4. DANH GIA HIEU NANG VA VONG DOI APACHE ECHARTS 6.1 (PERFORMANCE & LIFECYCLE PROFILING)

### 4.1. Co che dem su kien WebSocket / SSE (Batch Updates vs Per-Tick Render)

**Van de hien tai**:
Neu ket noi truc tiep WebSocket tick tu Exness hoac MT5 vao frontend, trong cac khung gio bien dong manh (nhu tin tuc Non-Farm Payrolls, CPI, chien tranh, gia vang XAU/USD co the nhan 30 - 60 ticks/giay):
- Neu moi tick nhan duoc deu goi ngay `chart.setOption(...)`, trinh duyet se bi treo hoan toan (UI freezing, frame drops duoi 10 FPS) do ECharts phai tinh toan lai canvas layout va ve lai toan bo path graphic.

**Kien truc dem du lieu (Event Buffering Engine) toi uu cho ECharts 6.1**:
1. **Ring Buffer tai Client Worker / Hook**:
   - Khi tick toi qua SSE/WebSocket, chi day tick vao mot mang bo dem bo nho cuc bo (`tickQueue.push(tick)`).
   - Tinh toan cap nhat nen hien tai trong bo nho:
     - `high = Math.max(currentBar.high, tick.price)`
     - `low = Math.min(currentBar.low, tick.price)`
     - `close = tick.price`
     - `volume += 1` (tang tick count)
2. **Co che Flush theo nhip rAF (Frame-locked Throttling)**:
   - Su dung co che dem micro-batch: khong cap nhat bieu do voi moi tick ma dong bo voi nhip quet man hinh 60Hz (~16.6ms) hoac throttle 100ms:
   - Su dung ECharts API toi uu: Thay vi truyen lai toan bo mang 200 nen qua `setOption({ series: [...] })`, chi cap nhat dung phan tu cuoi cung cua mang series candlestick bang `setOption` voi option merge cuc bo, hoac ve rieng mot graphic/markLine gia thoi gian thuc tren Canvas layer tren cung de tranh re-render toan bo cay du lieu.

---

### 4.2. Dieu tiet requestAnimationFrame (rAF) va quan ly event loop

Bang danh gia viec ap dung `requestAnimationFrame` tren toan bo codebase:

| Component / Hook | Su dung ResizeObserver? | Co cancelAnimationFrame + rAF? | Nguy co Layout Thrashing / Lag |
| :--- | :--- | :--- | :--- |
| `useChartLifecycle.ts:42-48` | Co | **Co** (Chuan mau) | Khong |
| `CandlestickChart.tsx:116-123`| Co | **Co** (Chuan mau) | Khong |
| `Compare.tsx:214-220` | Co | **Co** (Chuan mau) | Khong |
| `FactorResearchPanel.tsx:195-204`| Co | **Co** (Chuan mau) | Khong |
| `MiniEquityChart.tsx:40-47` | Co | **Co** (Chuan mau) | Khong |
| `RegimeTimeline.tsx:126-133` | Co | **Co** (Chuan mau) | Khong |
| `ForexCandlePlot.tsx:37` | Co | **KHONG** (`chart.resize()` truc tiep) | **CAO** (Lag khi thay doi kich thuoc tab) |
| `DistributionChart.tsx:99` | Co | **KHONG** (`chart.resize()` truc tiep) | **TRUNG BINH** |
| `WalkForwardChart.tsx:97` | Co | **KHONG** (`chart.resize()` truc tiep) | **TRUNG BINH** |
| `MonteCarloPathsChart.tsx:129`| Co | **KHONG** (`chart.resize()` truc tiep) | **TRUNG BINH** |
| `Portfolio.tsx:630` (`AllocationPie`)| Khong (dung window resize) | **KHONG** | **CAO** (Khong bat duoc resize container) |
| `Portfolio.tsx:662` (`HistoryChart`)| Khong (dung window resize) | **KHONG** | **CAO** |

---

### 4.3. Ve sinh DOM, giai phong bo nho (unmount hygiene, resize listeners, chong memory leak)

1. **Giai phong instance ECharts**:
   - Khi mot component chua ECharts unmount, neu khong goi `chart.dispose()`, instance do van ton tai trong bien toan cuc cua thu vien ECharts (`instances` map trong zrender) va cac canvas buffer van chiem dung GPU/RAM.
   - Kiem toan cho thay: Cac bieu do deu co goi `chart.dispose()` trong phan cleanup cua `useEffect`.
2. **Huy lang nghe su kien va observer**:
   - Trong `useChartLifecycle.ts:25-32`:
     ```ts
     const dispose = () => {
       const current = resource.current;
       if (!current) return;
       current.observer.disconnect();
       if (current.frame !== null) cancelAnimationFrame(current.frame);
       current.chart.dispose();
       resource.current = null;
     };
     ```
     Day la mau thiet ke chuan xac nhat trong du an.
3. **Loi tai tao instance lien tuc (Re-instantiation leak)** trong `Portfolio.tsx:635`:
   - `useEffect` phu thuoc vao `[data, centerLabel, onSelect, dark, instance.language]`. Moi khi nguoi dung nhap mot ky tu vao o tim kiem, hoac moi khi portfolio duoc polling lai, component xoa toan bo ECharts cu va tao ECharts moi. Day la hanh vi lang phi tai nguyen va co the gay memory leak neu trinh duyet chua kip thu gom bo nho (GC) cac canvas cu bi detach khoi DOM.

---

### 4.4. Dong bo hoa con tro chu thap da khung thoi gian (Multi-Timeframe Crosshair Sync M1, M5, H1, D1)

Trong phan tich ky thuat chuyen nghiep cho XAU/USD, trader can quan sat dong thoi 4 khung gio (M1, M5, H1, D1). Khi di chuot tai mot thoi diem tren bieu do M5, con tro chu thap (crosshair / axisPointer) phai dong thoi xuat hien tai dung moc thoi gian tuong ung tren bieu do M1, H1 va D1.

**Phan tich co che `CHART_GROUP` hien tai trong codebase**:
- Trong `frontend/src/lib/echarts.ts:27-36`:
  `CHART_GROUP = "quant-charts"`; `echarts.connect(CHART_GROUP);`.
- `CandlestickChart.tsx:112` va `EquityChartOverlay` trong `Compare.tsx:130` da gan `chart.group = CHART_GROUP`.
- **Nguyen nhan gay that bai khi dong bo da khung thoi gian (M1, M5, H1, D1)**:
  - Cac bieu do hien tai deu su dung truc X dang danh muc:
    `xAxis: { type: "category", data: dates }` (vi du `CandlestickChart.tsx:271`).
  - Khi truc X la `"category"`, ECharts `connect` thuc hien dong bo con tro chu thap theo **chi so chi muc (dataIndex)** hoac **chuoi ten category**.
  - Trong da khung thoi gian:
    - Bieu do M1 co 1.440 bars trong ngay.
    - Bieu do M5 chi co 288 bars.
    - Bieu do H1 chi co 24 bars.
    - Bieu do D1 chi co 1 bar.
  - Neu dong bo theo dataIndex: Di chuot vao bar thu 100 cua M1 (luc 01:40 sang) se khien bieu do M5 nhay den bar thu 100 (luc 08:20 sang), va bieu do H1 bi loi vi chi co 24 bar!
  - Neu dong bo theo ten chuoi: Chuoi thoi gian cua M1 la `2026-11-08 14:05:00`, trong khi chuoi cua H1 la `2026-11-08 14:00:00`. Chuoi khong khop nhau nen ECharts bo qua, con tro chu thap khong di chuyen.

**Giai phap kien truc cho Multi-Timeframe Crosshair Sync**:
1. **Phuong an A: Chuyen truc X sang `type: "time"` voi epoch milliseconds**:
   - Chuyen doi mang du lieu thanh `[timestamp_ms, open, close, low, high]`.
   - ECharts `axisPointer` se tu dong lien ket qua moc thoi gian thuc thay vi dataIndex.
2. **Phuong an B (Khai dung va khong bi loi gap cuoi tuan): Event-Driven Crosshair Synchronization Engine**:
   - Giu truc category de khong bi ve khoang trang vao cuoi tuan.
   - Xay dung mot Event Bus dong bo (hoac Zustand slice `useCrosshairStore`):
     - Lang nghe su kien `updateAxisPointer` tren bieu do dang co chuot hover.
     - Lay gia tri timestamp tai toa do hien tai: `hoverTime = dates[dataIndex]`.
     - Chuyen doi `hoverTime` thanh epoch timestamp.
     - Tren moi bieu do khac (M1, M5, H1, D1), dung tim kiem nhi phan (Binary Search O(log N)) de tim chi so bar co thoi gian gan nhat: `targetIndex`.
     - Chu dong phat lenh qua ECharts Action API:
       ```ts
       targetChart.dispatchAction({
         type: "showTip",
         seriesIndex: 0,
         dataIndex: targetIndex,
       });
       ```
   - Phuong an nay dam bao dong bo con tro chu thap chinh xac 100% tren moi khung gio bat ke so luong bar khac biet.

---

## 5. BANG TONG HOP LOI KIEN TRUC VA DE XUAT NANG CAP SAN XUAT

| STT | File & Dong code | Hien trang / Phat hien | Muc do rui ro | Kien nghi giai phap ky thuat |
| :--- | :--- | :--- | :--- | :--- |
| 1 | `frontend/src/components/forex/ForexCandlePlot.tsx:37` | `new ResizeObserver(() => chart.resize())` khong co rAF throttling | Cao | Chuyen sang hook `useChartLifecycle` hoac boc trong `cancelAnimationFrame` + `requestAnimationFrame`. |
| 2 | `frontend/src/components/forex/ForexCandlePlot.tsx:17-40` | Khong tham gia `CHART_GROUP`, co lap khoi crosshair sync | Trung binh | Gan `chart.group = CHART_GROUP` va goi `connectCharts()`. |
| 3 | `frontend/src/components/forex/ForexLiveChart.tsx:17` | `setInterval` 1s render lai component cha, gay re-render `ForexCandlePlot` | Trung binh | Boc `ForexCandlePlot` trong `React.memo` de chan re-render thua khi snapshot khong doi. |
| 4 | `frontend/src/pages/Portfolio.tsx:606-637` | `AllocationPie` khoi tao lai ECharts tu dau tren moi lan thay doi filter/data; dung window resize | Cao | Tach thanh `AssetAllocationChart.tsx`, su dung `useChartLifecycle`, chi goi `setOption` tren du lieu moi. |
| 5 | `frontend/src/components/charts/DistributionChart.tsx:99`, `WalkForwardChart.tsx:97`, `MonteCarloPathsChart.tsx:129` | ResizeObserver goi truc tiep `chart.resize()` khong co rAF | Trung binh | Dong bo toan bo ve su dung `useChartLifecycle` hoac them rAF throttling. |
| 6 | `frontend/src/hooks/useForexChart.ts:33` | Polling HTTP 3s/lan gay tre va tieu ton bang thong | Cao | Xay dung WebSocket/SSE Tick Engine ket noi tu Exness/MT5 sang frontend kem ring-buffer micro-batching. |
| 7 | `frontend/src/lib/echarts.ts:27-36` & `CandlestickChart.tsx:271` | Category axis khong the dong bo crosshair giua cac timeframe khac nhau (M1/M5/H1/D1) | Cao | Xay dung Crosshair Event Bus dung `dispatchAction({ type: 'showTip' })` voi tim kiem nhi phan timestamp. |
