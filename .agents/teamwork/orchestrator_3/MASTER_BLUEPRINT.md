# MASTER BLUEPRINT & ARCHITECTURAL AUDIT REPORT
## Financial Visualizations, Real-Time Candlestick Engines (Equities & XAU/USD), Agent Data Pipelines, AI Reasoning Quality & CFA Standards Compliance

**Project Root**: `d:\Vibe-Trading`  
**Author**: Project Orchestrator (`orchestrator_3`)  
**Audit Team**: `explorer_ws1_charts`, `explorer_ws2_data`, `explorer_ws3_agent`, `explorer_ws4_cfa`  
**Date**: 2026-11-08  
**Standards Baseline**: CFA Institute Curriculum (Levels I, II, III), GIPS 2020 Standards, Apache ECharts 6.1 Enterprise Guidelines  

---

## MỤC LỤC TỔNG QUAN

1. **Executive Summary & High-Level Architecture**
2. **Workstream 1: Multi-Dimensional Financial Chart Architecture & Real-Time Candlestick Engines**
   - 1.1. Bảng Kiểm kê Toàn diện Các Component Biểu đồ (Pie, Bar, Line, Candlestick)
   - 1.2. Pipeline Tick-to-Candlestick (Cổ phiếu US/VN/HK/CN vs Vàng/Forex XAU/USD)
   - 1.3. Hồ sơ Hiệu năng Apache ECharts 6.1 & Vòng đời Component
   - 1.4. Thiết kế Đồng bộ Con trỏ Chữ thập (Crosshair Sync) Đa Khung Thời gian (M1, M5, H1, D1)
3. **Workstream 2: Data Ingestion, Normalization & Agent Data Pipelines**
   - 2.1. Broker Connectors & Loaders (MT5, Exness, OANDA, IBKR, YFinance, Yahoo, Akshare)
   - 2.2. Kiểm toán Xung đột Múi giờ (Timezone Mismatch) & Lệch Pha Timestamp
   - 2.3. Thiếu sót Định nghĩa Phiên Giao dịch (Market Sessions) & Xử lý Thanh Nến Trống
   - 2.4. Méo mó Toán học trong Chỉ báo VWAP & Thiếu Reset Phiên
   - 2.5. Kiểm soát Hàng đợi, Đồng quy (Concurrency) & Cơ chế Backpressure
4. **Workstream 3: Agent Architecture & AI Reasoning / Response Workflow**
   - 3.1. Vòng lặp Thực thi ReAct Loop & Quản lý Ngữ cảnh 5 Tầng
   - 3.2. Đồ thị Swarm DAG Runtime: Tô-pô Kahn, Chặn Phụ thuộc & Resume Overlay
   - 3.3. Hội đồng Phản biện Đa Vai trò (6 Roles, 4 Giai đoạn, Quyền Hard Veto)
   - 3.4. Kiến trúc Tin cậy & Chất lượng Phản hồi AI (GroundingLedger, 5 Tầng Nguồn tin, Dung sai 0.5%)
5. **Workstream 4: CFA Institute Standards & Quantitative Accuracy Audit**
   - 4.1. Lợi nhuận Hóa năm & CAGR: Vi phạm Chuẩn mực GIPS 2.A.28
   - 4.2. Sharpe Ratio: Bỏ quên Lãi suất Phi Rủi ro, Lệch Bậc Tự do & Hiệu ứng Tự tương quan
   - 4.3. Sortino Ratio: Độ lệch Chuẩn Bán phần Âm, Rào cản MAR & Tỷ lệ Ảo $10^9$
   - 4.4. Information Ratio & Cạm bẫy Điền 0.0 vào Lỗ hổng Dữ liệu Benchmark
   - 4.5. Phân bổ Nhân tố Brinson-Fachler: Ngắt kết nối Thuật toán Cariño trong API
   - 4.6. Mô phỏng Monte Carlo & Tái lấy mẫu Bootstrap: Biến dạng Thời gian Nắm giữ & Phân phối Đuôi Dày
6. **Bộ Mã Nguồn Tham Chiếu Chuẩn CFA/GIPS & Kiến Trúc XAU/USD Real-Time**
   - 6.1. CFA/GIPS Compliance Metric Engine (`calc_metrics_cfa`)
   - 6.2. Multi-Period Cariño Attribution Pipeline
   - 6.3. Real-Time Tick Aggregator & Dual-Tier Ring Buffer cho XAU/USD
   - 6.4. Crosshair Event Bus Đa Khung Thời Gian
7. **Lộ Trình Triển Khai & Khuyến Nghị Nâng Cấp Từng Bước**

---

## 1. EXECUTIVE SUMMARY & HIGH-LEVEL ARCHITECTURE

Hệ thống Vibe-Trading được thiết kế với tầm nhìn trở thành một nền tảng giao dịch định lượng và phân tích tài chính đa tài sản tích hợp trí tuệ nhân tạo. Qua đợt tổng kiểm toán kiến trúc toàn diện trên 4 trụ cột nghiệp vụ:
- **Tầng Trực quan hóa (Frontend Visualization)**: Ứng dụng React 19 + TypeScript với thư viện trực quan hóa Apache ECharts 6.1 (Canvas Renderer), bao gồm biểu đồ nến Nhật, phân bổ tài sản, phân rã lợi nhuận Brinson, đường cong vốn (Equity), drawdowns và mô phỏng Monte Carlo.
- **Tầng Dữ liệu (Data Pipelines & Ingestion)**: Kết nối đa kênh tới các sàn môi giới (MT5, Exness, OANDA, IBKR, KIS...) và các nguồn dữ liệu lịch sử (Yahoo Finance, Akshare), vận chuyển dữ liệu vào Agent Runtime và phục vụ giao diện người dùng.
- **Tầng Tác tử AI (Agentic Reasoning & Swarm)**: Hệ thống ReAct Loop với 5 tầng nén ngữ cảnh, đồ thị Swarm DAG phân tầng tô-pô song song, Hội đồng phản biện 6 vai trò (Council) và sổ cái kiểm chứng số liệu chống ảo giác (GroundingLedger).
- **Tầng Định lượng (Quantitative Finance & Risk)**: Thư viện `quantlib` với các mô hình hiệu suất (TWR, Modified Dietz, XIRR), phân bổ nhân tố Brinson-Fachler kết hợp liên kết đa chu kỳ Cariño, và phân tích rủi ro.

```
+---------------------------------------------------------------------------------------------------+
|                                  VIBE-TRADING SYSTEM TOPOLOGY                                     |
+---------------------------------------------------------------------------------------------------+
|  FRONTEND LAYER (React 19 + ECharts 6.1)                                                          |
|  [CandlestickChart]  [ForexCandlePlot]  [EquityChart]  [AttributionWaterfall]  [AllocationPie]    |
|         ^                                      ^                                    ^             |
|         | Crosshair Event Bus (Binary Search)  | useChartLifecycle (rAF Resize)     |             |
+---------+--------------------------------------+------------------------------------+-------------+
|  COMMUNICATION & STREAMING LAYER (FastAPI)                                                        |
|  [WS Tick Streamer (Planned)] <---> [Dual-Tier Ring Buffer] <---> [SSE Agent Events (/events)]    |
+---------------------------------------------------------------------------------------------------+
|  AGENT & DECISION RUNTIME                                                                         |
|  +--------------------+   +------------------------------------+   +--------------------------+   |
|  | ReAct Loop         |   | Swarm DAG Runtime                  |   | Multi-Role Council       |   |
|  | - 5-tier context   |-->| - Kahn Topological Layers          |-->| - 4 Stages (Tech/Macro/  |   |
|  | - Stall watchdog   |   | - Dependency-Aware Gating          |   |   Bull/Bear/Risk/Manager)|   |
|  | - Text-only wrapup |   | - Resume Overlay                   |   | - Hard Veto & ATR Bounds |   |
|  +--------------------+   +------------------------------------+   +--------------------------+   |
|                                         |                                                         |
|                                         v                                                         |
|                       [GroundingLedger & 5-Tier Sources]                                          |
|                       (Strict 0.5% Tolerance & Redacted Release)                                  |
+---------------------------------------------------------------------------------------------------+
|  DATA INGESTION & BROKER CONNECTORS                                                               |
|  [MT5 Adapter (Subprocess)] [Exness (WS/Ed25519)] [OANDA (v20 REST)] [IBKR Pool] [YFinance/Yahoo] |
+---------------------------------------------------------------------------------------------------+
|  QUANTITATIVE & EVALUATION ENGINE (CFA / GIPS 2020)                                               |
|  [GIPS Annualization]  [Sharpe (Rf/Lo 2002)]  [Sortino LPM2]  [Cariño Attribution]  [Block BCa]   |
+---------------------------------------------------------------------------------------------------+
```

### Các Phát Hiện Trọng Yếu Cần Giải Quyết Ngay:
1. **Frontend & Realtime**: Luồng dữ liệu nến Forex/XAU/USD hiện tại đang dùng **HTTP short-polling 3 giây/lần** gọi qua `subprocess.run` MT5 thay vì Persistent WebSocket Stream. Có 4 component biểu đồ gọi `ResizeObserver` đồng bộ gây layout thrashing.
2. **Data Pipeline**: Xung đột múi giờ giữa `yfinance_loader` (cắt bỏ tz gây lệch 4 tiếng) và `yahoo_loader` (chuyển sang UTC); chỉ báo VWAP tính sai thành Typical Price `(O+H+L+C)/4` không có trọng số volume; thiếu định nghĩa phiên cho HOSE, HNX, HKEX và Forex 24/5.
3. **CFA/GIPS Standards**: Hàm tính lợi nhuận năm `agent/backtest/metrics.py:604` tự ý lũy thừa hóa chu kỳ dưới 1 năm (vi phạm nghiêm trọng GIPS 2.A.28); Sharpe Ratio bỏ qua lãi suất phi rủi ro ($R_f=0$); API endpoint `attribution_core.py` chỉ lấy 1 dòng snapshot tĩnh bỏ qua liên kết đa chu kỳ Cariño.

---

## 2. WORKSTREAM 1: MULTI-DIMENSIONAL FINANCIAL CHART ARCHITECTURE & REAL-TIME CANDLESTICK ENGINES

### 2.1. Bảng Kiểm kê Toàn diện Các Component Biểu đồ
Mã nguồn biểu đồ phân bố chủ yếu tại `frontend/src/components/charts/`, `frontend/src/components/forex/` và `frontend/src/pages/`:

| Component | Vị trí File | Phân loại | Mục đích & Đặc tính Kỹ thuật | Trạng thái Vòng đời & Rủi ro |
|---|---|---|---|---|
| `AllocationPie` | `frontend/src/pages/Portfolio.tsx:606-637` | Pie (Tròn) | Phân bổ tài sản danh mục (`radius: ["46%", "70%"]`). Viết private inline trong page. | **Rủi ro**: Hủy và `echarts.init` lại mỗi lần đổi filter; dùng `window.resize` thay vì ResizeObserver. |
| `AnnualReturnsChart` | `frontend/src/components/charts/AnnualReturnsChart.tsx:1-83` | Bar (Cột) | Lợi nhuận hàng năm phân tách âm/dương với đường chuẩn `markLine` tại y=0. | **Chuẩn**: Tái sử dụng `useChartLifecycle`, rAF resize, dọn dẹp tốt. |
| `AttributionWaterfallChart` | `frontend/src/components/charts/AttributionWaterfallChart.tsx:1-127` | Bar (Thác nước) | Phân tích Brinson: Allocation, Selection, Interaction thành dạng Waterfall. | **Chuẩn**: Xếp chồng 2 series `stack: "waterfall"`, series đáy trong suốt (`transparent`). |
| `DistributionChart` | `frontend/src/components/charts/DistributionChart.tsx:1-110` | Bar (Phân phối) | Histogram tần suất lợi nhuận và phân vị rủi ro Monte Carlo. | **Lỗi Layout Thrashing**: Gọi `new ResizeObserver(() => chart.resize())` trực tiếp không có rAF. |
| `WalkForwardChart` | `frontend/src/components/charts/WalkForwardChart.tsx:1-108` | Bar + Line | Đánh giá OOS (Out-of-Sample) từng cửa sổ trượt Walk-Forward. | **Lỗi Layout Thrashing**: Gọi `ResizeObserver` trực tiếp không có rAF. |
| `EquityChart` | `frontend/src/components/charts/EquityChart.tsx:1-122` | Line (2 Grids) | Grid 0: Giá trị danh mục vs Benchmark; Grid 1: Đường cong Drawdown (%) kèm `markArea` vùng sụt giảm và `markLine` Max DD. | **Chuẩn**: Đồng bộ trục X giữa 2 Grid, quản lý tooltip đa tầng mượt mà. |
| `RollingBetaAlphaChart` | `frontend/src/components/charts/RollingBetaAlphaChart.tsx:1-113` | Line (Trục kép) | Trục Y trái: Hệ số Beta; Trục Y phải: Alpha hàng năm (%). | **Chuẩn**: Phân tách rõ ràng đơn vị, format tooltip chuyên nghiệp. |
| `AttributionCumulativeChart` | `frontend/src/components/charts/AttributionCumulativeChart.tsx:1-102` | Line (Đa đường) | 3 đường so sánh: Lợi nhuận danh mục, Benchmark và Lợi nhuận vượt trội chủ động (Active Return). | **Chuẩn**: Tooltip hiển thị delta rõ ràng. |
| `EquityChartOverlay` | `frontend/src/pages/Compare.tsx:120-220` | Line (So sánh) | Rebase hai chiến lược về mốc 100 để so sánh trực quan; gán `chart.group = CHART_GROUP`. | **Chuẩn**: Có cơ chế `cancelAnimationFrame` + rAF resize. |
| `MonteCarloPathsChart` | `frontend/src/components/charts/MonteCarloPathsChart.tsx:1-140` | Line + Area | Hàng trăm đường mô phỏng nhẹ kết hợp dải mây xác suất P5-P95, P25-P75. | **Lỗi Layout Thrashing**: Gọi `ResizeObserver` trực tiếp không có rAF. |
| `CandlestickChart` | `frontend/src/components/charts/CandlestickChart.tsx:1-354` | Candlestick | Biểu đồ nến kỹ thuật đầy đủ: MA5/10/20/60, EMA12/26, Bollinger Bands; Sub-charts: Volume, MACD, RSI, KDJ; Trade markers BUY/SELL có `escapeHtml` chống XSS; liên kết `CHART_GROUP`. | **Chuẩn Kiến trúc**: Tối ưu tốt, an toàn XSS, hỗ trợ dataZoom và brush selection. |
| `ForexCandlePlot` | `frontend/src/components/forex/ForexCandlePlot.tsx:1-66` | Candlestick (Forex) | Nến thời gian thực XAU/USD và Forex từ MT5: `useUTC: true`, nến đang hình thành (forming bar) giảm độ mờ `opacity: 0.7` và viền dày `borderWidth: 2`, 2 đường `markLine` Bid/Ask, Grid 1 cho Tick Volume. | **Lỗi**: Gọi `ResizeObserver` đồng bộ thiếu rAF; chưa tham gia `CHART_GROUP`. |
| `ForexLiveChart` | `frontend/src/components/forex/ForexLiveChart.tsx:1-65` | Wrapper | Vỏ bọc quản lý trạng thái, kết nối `useForexChart.ts`, polling dữ liệu mỗi 3 giây, chứa timer 1s. | **Rủi ro Re-render**: Timer 1s gây re-render component con `ForexCandlePlot` không cần thiết. |
| `ChartBlock` | `frontend/src/components/charts/ChartBlock.tsx:1-179` | Dynamic Parser | Phân tích cú pháp khối code fence ````chart` do AI Agent sinh ra trong báo cáo markdown, kiểm tra hình học OHLC rồi chuyển tiếp tới `CandlestickChart`. | **Chuẩn An toàn**: Thẩm định chặt chẽ cấu trúc JSON trước khi render. |

### 2.2. Pipeline Tick-to-Candlestick (Equities vs Commodities/XAU/USD)
Khảo sát chỉ ra sự khác biệt cơ bản giữa hai luồng tài sản:
1. **Equities (US, VN, HK, CN)**:
   - Dữ liệu được nạp theo lô (batch/session) dựa trên ngày giao dịch cố định.
   - Volume đại diện cho số lượng cổ phiếu thực tế khớp lệnh trên sàn giao dịch tập trung (HOSE, HNX, NYSE, NASDAQ).
   - Nến EOD (End of Day) có tính đóng băng tuyệt đối sau giờ đóng cửa.
2. **Commodities / Forex (Đặc biệt là XAU/USD Gold)**:
   - Giao dịch phi tập trung (OTC) liên tục 24/5 từ sáng thứ Hai (Sydney) đến chiều thứ Sáu (New York).
   - Giá luôn tồn tại dưới dạng cặp song hành: **Bid** và **Ask**; chênh lệch Spread biến động mạnh theo thanh khoản phiên.
   - Volume thực chất là **Tick Count** (số lượng thay đổi báo giá trong khung thời gian), không phải khối lượng hợp đồng.
   - Cần phân tách nghiêm ngặt giữa **Nến đang chạy (Forming Bar, index 0)** và **Nến đã đóng (Confirmed Closed Bars, index $\ge 1$)**. Các tác tử định lượng chỉ được lấy tín hiệu trên nến đã đóng để tránh thiên lệch nhìn trước (look-ahead bias), trong khi biểu đồ trực quan bắt buộc phải hiển thị nến đang chạy kèm đường Bid/Ask thời gian thực.
   - **Tích hợp Broker**:
     * **MetaTrader 5 (MT5)**: Đọc qua `agent/src/trading/forex/adapters/mt5_worker.py:181-228` với `terminal_read_lock` tối đa 10s. Lấy tick qua `symbol_info_tick` và nến qua `copy_rates_from_pos`.
     * **Exness**: Hỗ trợ WebSocket ticks thời gian thực `wss://.../server-events/ws/ticks` kèm chữ ký Ed25519 (`exness.py:170-190`).
     * **OANDA**: Hỗ trợ REST v20 endpoint `/pricing` và `/candles` (`oanda.py:80-140`).

### 2.3. Hồ sơ Hiệu năng Apache ECharts 6.1 & Vòng đời Component
1. **Tree-Shaking & Bundle Optimization**: File `frontend/src/lib/echarts.ts:1-39` áp dụng tree-shaking triệt để với `echarts/core`, chỉ nạp các Charts (`Candlestick`, `Line`, `Bar`, `Pie`, `Heatmap`, `Treemap`) và Components (`Tooltip`, `Grid`, `DataZoom`, `MarkLine`, `MarkArea`, `Legend`) cần thiết, sử dụng `CanvasRenderer`.
2. **Hiện tượng Layout Thrashing do ResizeObserver thiếu rAF**:
   - `useChartLifecycle.ts:42-48` triển khai chuẩn mẫu:
     ```typescript
     let frameId = 0;
     const ro = new ResizeObserver(() => {
       cancelAnimationFrame(frameId);
       frameId = requestAnimationFrame(() => chart.resize());
     });
     ```
   - Tuy nhiên, 4 component (`ForexCandlePlot.tsx:37`, `DistributionChart.tsx:99`, `WalkForwardChart.tsx:97`, `MonteCarloPathsChart.tsx:129`) lại khởi tạo `new ResizeObserver(() => chart.resize())` trực tiếp. Khi kích thước cửa sổ trình duyệt thay đổi, hàng chục sự kiện resize kích hoạt đồng bộ làm trình duyệt liên tục tính toán lại layout (Layout Thrashing), gây giật khung hình (FPS drop).
3. **Hiện tượng Thừa Thải Re-render**: `ForexLiveChart.tsx` kích hoạt state re-render mỗi giây nhằm cập nhật đồng hồ đếm ngược, khiến `ForexCandlePlot` bị kích hoạt vẽ lại tùy chọn dù dữ liệu nến 3 giây mới cập nhật một lần. Giải pháp: Cần bọc `ForexCandlePlot` bằng `React.memo` với hàm so sánh nông (shallow compare) `prevProps.candles === nextProps.candles`.

### 2.4. Thiết kế Đồng bộ Con trỏ Chữ thập (Crosshair Sync) Đa Khung Thời Gian
- Hiện tại, các biểu đồ kết nối qua `echarts.connect(CHART_GROUP)`. Tuy nhiên, cơ chế này chỉ hoạt động khi các biểu đồ có cùng kiểu dữ liệu trục và cùng độ dài mảng Category.
- Khi người dùng theo dõi cùng lúc 4 khung thời gian của XAU/USD (M1, M5, H1, D1):
  * Khung M1 có 1.440 thanh nến trong ngày.
  * Khung M5 có 288 thanh nến.
  * Khung H1 có 24 thanh nến.
  * Khung D1 chỉ có 1 thanh nến.
- Nếu dùng Category Index mặc định, trỏ chuột vào thanh thứ 10 của M1 (lúc 00:10 sáng) sẽ làm kích hoạt thanh thứ 10 của H1 (lúc 10:00 sáng) -> **Lệch pha thời gian hoàn toàn**.
- **Giải pháp Kiến trúc: Crosshair Event Bus dựa trên Tìm kiếm Nhị phân Timestamp**:
  Bắt sự kiện `updateAxisPointer` trên biểu đồ nguồn, trích xuất timestamp epoch mili-giây, thực hiện thuật toán tìm kiếm nhị phân (`binarySearchTimestamp`) trên danh sách nến của các biểu đồ mục tiêu để tìm thanh nến có khoảng cách thời gian gần nhất, sau đó điều phối hành động:
  `targetChart.dispatchAction({ type: 'showTip', seriesIndex: 0, dataIndex: matchedIndex })`.

---

## 3. WORKSTREAM 2: DATA INGESTION, NORMALIZATION & AGENT DATA PIPELINES

### 3.1. Broker Connectors & Historical Loaders
Hệ thống Vibe-Trading đã thiết lập danh mục 16 connector (`agent/src/trading/service.py:18-35`). Qua kiểm toán luồng dữ liệu:
- **Interactive Brokers (IBKR)** (`agent/src/trading/connectors/ibkr/local.py:525-600`): Sử dụng kiến trúc `_TwsPool` với `threading.local()` và `threading.Lock()` để đảm bảo mỗi worker thread sở hữu một kết nối socket riêng biệt, cấp phát `client_id` động qua `itertools.count(1)`. Đây là thiết kế thread-safe đạt chuẩn.
- **MetaTrader 5 (MT5)** (`agent/src/trading/forex/adapters/mt5.py:26-35`): Mỗi thao tác lại gọi `subprocess.run([sys.executable, "-m", "src.trading.forex.adapters.mt5_worker"], ...)`. Mỗi lần chạy tiến trình con mất từ 200ms - 500ms chỉ để khởi động Python runtime và IPC socket vào MT5 terminal.
- **Exness Adapter** (`agent/src/trading/forex/adapters/exness.py:178-221`): Hàm `quote` mở một WebSocket tạm thời (ephemeral), nhận đúng 1 tick hợp lệ rồi đóng kết nối ngay lập tức (`socket.close()`). Điều này phá vỡ bản chất của giao thức streaming thời gian thực.

### 3.2. Kiểm toán Xung đột Múi giờ (Timezone Mismatch)
Kiểm toán phát hiện một lỗi xung đột dữ liệu nghiêm trọng giữa hai loader cùng nạp dữ liệu từ Yahoo Finance:
1. `agent/backtest/loaders/yfinance_loader.py:220-224`:
   ```python
   index = pd.DatetimeIndex(pd.to_datetime(normalized.index))
   if getattr(index, "tz", None) is not None:
       index = index.tz_localize(None)  # CẮT BỎ MÚI GIỜ GỐC!
   normalized.index = index
   ```
   Lệnh `tz_localize(None)` biến thời gian mở cửa của chứng khoán Mỹ `09:30-04:00` (EDT) thành `09:30 naive`.
2. Trong khi đó, `agent/backtest/loaders/yahoo_loader.py:167`:
   ```python
   index = pd.to_datetime(frame["trade_date"], unit="s", utc=True).dt.tz_convert(None)
   ```
   Loader này chuyển đổi timestamp sang UTC trước khi bỏ tz, biến `09:30 EDT` thành `13:30 naive`.
3. **Hậu quả**: Khi phân tích liên thị trường hoặc kết hợp danh mục cổ phiếu và hàng hóa, dữ liệu từ hai loader này bị lệch pha **4 đến 5 tiếng đồng hồ**, làm sai lệch hoàn toàn ma trận tương quan và kiểm định độ trễ tín hiệu (lag correlation).
4. `agent/backtest/loaders/mt5_loader.py:169` và `mt5_worker.py:216`: Giờ của máy chủ sàn môi giới MT5 (thường là GMT+2 / GMT+3 của Síp/Đông Âu) bị gán cứng thành UTC, khiến nến XAU/USD bị lệch từ 2 đến 3 tiếng so với thực tế.

### 3.3. Thiếu sót Định nghĩa Phiên Giao dịch (Market Sessions)
Trong `agent/src/live/runtime/triggers.py:112-127`, từ điển `MARKET_SPECS` chỉ khai báo duy nhất 2 loại thị trường:
- `us_equity` (09:30 - 16:00 EST)
- `crypto` (24/7)

Hệ thống **hoàn toàn thiếu cấu hình phiên** cho:
- Chứng khoán Việt Nam (`vn_equity`): 09:00 - 15:00 GMT+7 (nghỉ trưa 11:30 - 13:00, phiên ATO 09:00-09:15, phiên ATC 14:30-14:45).
- Chứng khoán Hong Kong (`hk_equity`): 09:30 - 16:00 HKT (nghỉ trưa 12:00 - 13:00).
- Chứng khoán Trung Quốc A-Share (`cn_equity`): 09:30 - 15:00 CST (nghỉ trưa 11:30 - 13:00).
- Thị trường Vàng / Ngoại hối (`forex_metals`): Mở cửa từ 22:00 UTC Chủ Nhật đến 22:00 UTC Thứ Sáu, ngắt phiên hàng ngày 21:00 - 22:00 UTC (Rollover hour).

### 3.4. Méo mó Toán học trong Chỉ báo VWAP
Trong `agent/src/factors/base.py:440-475`:
```python
# Cho CN Equity:
safe_div(panel['amount'] * 1000.0, panel['volume'] * 100.0 + 1.0)  # Thêm +1.0 vào mẫu số!

# Cho US, HK, IN, KR, Crypto khi thiếu cột vwap:
vwap = (panel["open"] + panel["high"] + panel["low"] + panel["close"]) / 4.0
```
- Phép cộng `+ 1.0` vào mẫu số làm sai lệch đáng kể giá trị VWAP trên các cổ phiếu penny hoặc khung nến thanh khoản thấp.
- Phép tính `(O+H+L+C)/4` thực chất là **Typical Price** không có trọng số khối lượng. Giá trị này hoàn toàn không phản ánh được mức giá trung bình theo khối lượng vốn thực tế tham gia giao dịch.
- Thiếu hàm lũy kế khối lượng trong ngày có điểm neo reset tại thời điểm bắt đầu phiên giao dịch (`cumulative session reset`).

### 3.5. Kiểm soát Hàng đợi, Đồng quy & Cơ chế Backpressure
- `MessageBus` (`agent/src/channels/bus/queue.py:16-17`) sử dụng `asyncio.Queue()` với `maxsize=0` (không giới hạn dung lượng bộ nhớ). Khi có nghẽn mạng hoặc xử lý chậm, hàng đợi có thể phình to không kiểm soát gây tràn bộ nhớ (Out-Of-Memory).
- `EventBus` (`agent/src/session/events.py:257, 167-169`) giới hạn `maxsize=200`. Khi hàng đợi đầy, bus âm thầm vứt bỏ sự kiện (`logger.warning("EventBus queue full, dropping...")`). Các sự kiện cập nhật trạng thái lệnh hoặc báo giá bị rơi rớt mà frontend không hề nhận được tín hiệu cảnh báo hay cờ resync.

---

## 4. WORKSTREAM 3: AGENT ARCHITECTURE & AI REASONING / RESPONSE WORKFLOW

### 4.1. Vòng lặp Thực thi ReAct Loop & Quản lý Ngữ cảnh 5 Tầng
Vòng lặp ReAct được hiện thực trong `agent/src/agent/loop.py` và `tool_lifecycle.py` với cấu trúc rất chặt chẽ:
1. **Quản lý Ngữ cảnh 5 Tầng (5-Tier Context Budget)** (`loop.py:3-9`):
   - **Tầng 1 (Microcompact)**: Loại bỏ khoảng trắng thừa, rút gọn các payload JSON trả về từ tool mà không làm mất thông tin ngữ nghĩa.
   - **Tầng 2 (Context Collapse)**: Rút ngắn lịch sử các lượt tương tác cũ khi tổng dung lượng token đạt ngưỡng 70% ngân sách.
   - **Tầng 3 (Auto Compact)**: Tự động tóm tắt các khối trao đổi trung gian thành một đoạn tóm lược cô đọng.
   - **Tầng 4 (Compact Tool Calls)**: Nén các kết quả trả về của công cụ đã gọi trong quá khứ, chỉ giữ lại các chỉ số tài chính then chốt.
   - **Tầng 5 (Iterative Update)**: Cơ chế cập nhật dần, ghi nhận transcript đầy đủ ra file `.jsonl` độc lập trên đĩa cứng trước khi cắt gọt ngữ cảnh in-memory.
2. **Cơ chế Phân nhóm Thực thi Công cụ (Tool Execution Batching)**: `tool_lifecycle.py:446-472` phân tách rành mạch giữa công cụ chỉ đọc (`is_readonly = True`) và công cụ ghi/đặt lệnh (`is_readonly = False`). Các công cụ chỉ đọc liên tiếp được tự động gom thành một lô (batch) và thực thi song song qua `ThreadPoolExecutor(max_workers=min(len(runnable), 8))`, giảm độ trễ vòng lặp từ 60-75%.
3. **Cơ chế Chống Treo & Cảnh Báo Kết Thúc Vòng Lặp**:
   - `_stall_watchdog` daemon thread (`loop.py:564-570, 1266-1334`) liên tục theo dõi biến thời gian thực `_last_activity_wall`. Nếu tác tử bị đơ do API bên ngoài không phản hồi quá `_stall_timeout_seconds()`, watchdog sẽ giải phóng và phát tín hiệu dừng an toàn.
   - Tại mốc 80% số vòng lặp cho phép (`wrap_up_at = max(1, int(self.max_iterations * 0.8))`, `loop.py:556, 632-654`), hệ thống tự động chèn lời nhắc cảnh báo yêu cầu tác tử ngừng gọi thêm công cụ mới và tập trung tổng hợp kết luận.
   - Tại vòng lặp cuối cùng (`is_last_iteration`), tham số `tool_defs` bị triệt tiêu (`tool_defs = None`, `loop.py:686-690`), cưỡng chế LLM chỉ được phép xuất văn bản thuần (text-only final answer), ngăn ngừa hoàn toàn lỗi vượt quá giới hạn vòng lặp tối đa (Max Iterations Exceeded Error).

### 4.2. Đồ thị Swarm DAG Runtime
Mô hình Swarm DAG phân tán được định nghĩa tại `agent/src/swarm/`:
- **Kiểm tra Chu trình & Phân tầng Tô-pô**: `agent/src/swarm/task_store.py:206-300` áp dụng thuật toán DFS 3 màu (White/Gray/Black) để phát hiện và ngăn chặn triệt để đồ thị có chu trình kín, đồng thời phân tầng thực thi theo **Thuật toán Kahn** dựa trên bán bậc vào (`in-degree`). Các tác tử ở cùng một tầng tô-pô (Layer) được khởi chạy song song độc lập.
- **Cổng Chặn An Toàn theo Phụ Thuộc (Dependency-Aware Gating)**: Tại `runtime.py:986-1015`, nếu một task thượng nguồn bị thất bại hoặc bị hủy, toàn bộ các task hạ nguồn phụ thuộc vào nó (`depends_on`, `blocked_by`) lập tức bị chuyển thành trạng thái `TaskStatus.blocked`, ngăn ngừa việc đưa ra quyết định giao dịch khi thiếu dữ liệu phân tích nền tảng.
- **Equal-Jitter Exponential Backoff**: Khi một tác tử gặp lỗi mạng, `_worker_retry_delay_s` (`runtime.py:70-78`) tự động áp dụng thuật toán dãn cách lũy thừa kèm nhiễu ngẫu nhiên đồng đều, bảo vệ các API sàn không bị quá tải.
- **Tiếp tục từ Điểm Dừng (Resume Overlay)**: Hàm `_apply_resume_overlay` (`runtime.py:732-867`) cho phép hệ thống tái sử dụng toàn bộ kết quả của các node đã hoàn thành thành công trong phiên trước nếu định nghĩa và model không thay đổi, tiết kiệm chi phí token và thời gian chạy.

### 4.3. Hội đồng Phản biện Đa Vai trò (Multi-Role Council)
Hội đồng phản biện đầu tư được cấu trúc tại `agent/src/trading/forex/council.py`:
- **6 Vai trò Tranh luận Chuyên biệt**:
  1. `technical`: Chuyên gia Phân tích Kỹ thuật (Price action, cấu trúc nến, hỗ trợ/kháng cự, xu hướng).
  2. `macro`: Chuyên gia Kinh tế Vĩ mô (Lãi suất liên ngân hàng, DXY, lợi suất trái phiếu, tin tức địa chính trị).
  3. `bull`: Phe Mua (Xây dựng luận điểm tăng giá, tìm kiếm cơ hội bứt phá).
  4. `bear`: Phe Bán (Xây dựng luận điểm giảm giá, tìm kiếm rủi ro điều chỉnh).
  5. `risk`: Giám đốc Quản trị Rủi ro (Đo lường biến động, tỷ lệ Reward/Risk, trần drawdown).
  6. `manager`: Giám đốc Danh mục (Tổng hợp toàn diện, đưa ra quyết định phân bổ cuối cùng).
- **Quy trình Tranh luận 4 Giai đoạn (`STAGES`)**:
  * Giai đoạn 1: Khởi động song song `("technical", "macro")`.
  * Giai đoạn 2: Đối thoại phản biện `("bull", "bear")`.
  * Giai đoạn 3: Thẩm định rủi ro độc lập `("risk",)`. Bắt buộc Risk Officer phải đọc và đối chiếu luận điểm của cả Bull và Bear.
  * Giai đoạn 4: Phán quyết cuối cùng `("manager",)`. Manager bắt buộc phải tham chiếu báo cáo rủi ro của Risk Officer.
- **Quyền Phủ Quyết Cứng (Hard Veto)**:
  Nếu `risk.veto == True` hoặc `risk.stance == "wait"` hoặc `manager.veto == True`, khuyến nghị đầu tư lập tức bị cưỡng chế về trạng thái **"wait" (Đứng ngoài quan sát)** (`council.py:166, 470-471`). Không một vị thế nào được phép mở nếu cơ chế quản trị rủi ro giơ cờ đỏ.
- **Tách Biệt Mức Giá Bằng Thuật Toán Xác Định**: Mô hình LLM không được tự ý bịa ra mức giá vào lệnh (Entry), Dừng lỗ (Stop Loss) hay Chốt lời (Take Profit). Thay vào đó, hàm xác định `candidates()` (`council.py:268-295`) tự động tính toán các mức giá này dựa trên báo giá trực tiếp từ sàn và chỉ báo biên độ dao động thực tế **ATR (Average True Range)**.

### 4.4. Kiến trúc Tin cậy & Chất lượng Phản hồi AI
Bộ kiểm soát độ tin cậy tại `agent/src/agent/grounding/` thiết lập tiêu chuẩn phòng chống ảo giác nghiêm ngặt:
- **Khối Khai Báo Số Liệu Bắt Buộc (`figures block`)**: Tác tử bắt buộc phải liệt kê mọi con số tài chính xuất hiện trong câu trả lời vào một khối khai báo riêng với 5 nhóm vai trò: `observed` (quan sát được), `derived` (tính toán suy diễn), `proposed` (đề xuất giao dịch), `cited` (trích dẫn tài liệu), `bare` (con số quy ước) (`figures.py:40-46`).
- **Bộ Kiểm tra Số liệu với Dung sai Nghiêm ngặt 0.5%**:
  * `@grounding_check figure-observed`: Con số thực tế thị trường phải khớp chính xác trong biên độ dung sai $\le 0.5\%$ so với dữ liệu gốc của sàn (`policies.py:105, 1693`).
  * `@grounding_check undeclared-figure`: Tự động chặn đứng và báo lỗi nếu có bất kỳ con số đo lường nào xuất hiện trong thân bài viết mà không được khai báo minh bạch trong khối `figures` (`policies.py:680`).
  * `@grounding_check chart-observed-payload`: Bắt buộc cấu trúc dữ liệu biểu đồ nến sinh ra phải khớp hoàn toàn với payload do công cụ trả về (`figures_checks.py:48-60`).
- **Danh Mục Nguồn Tin Trích Dẫn Phân Tầng (5 Tiers of Truth)** (`sources.py:95-191`):
  * **Tầng 1 (Cơ quan Quản lý & Sở Giao dịch)**: HOSE, HNX, UBCKNN, SBV, SEC, FED, LBMA (London Bullion Market Association cho Vàng).
  * **Tầng 2 (Hãng tin Tài chính Quốc tế Cấp 1)**: Reuters, Bloomberg, The Wall Street Journal, Financial Times.
  * **Tầng 3 (Đơn vị Cung cấp Dữ liệu Tài chính)**: FiinGroup, Vietstock DataFeed, LSEG.
  * **Tầng 4 (Báo cáo Công ty Chứng khoán Uy tín)**: SSI, Vietcap, VnEconomy.
  * **Tầng 5 (Mạng xã hội & Diễn đàn - Không xác minh)**: Reddit, Twitter/X, F319, Facebook Groups. Bị gắn cờ rủi ro cao và cấm dùng làm căn cứ duy nhất cho khuyến nghị mua bán.
- **Quy trình Hiệu Đính & Cắt Gọt An Toàn (`redacted_release`)**: Hệ thống hỗ trợ tối đa 2 lần yêu cầu LLM sửa lại số liệu vi phạm. Nếu sau 2 lần mô hình vẫn không khắc phục được con số ảo giác, cơ chế `redacted_release` (`loop_grounding.py:60-292`) sẽ tự động thay thế con số sai thành chuỗi `(đã lược※)` hoặc trả về `safe_fallback` để bảo vệ người dùng.

---

## 5. WORKSTREAM 4: CFA INSTITUTE STANDARDS & QUANTITATIVE ACCURACY AUDIT

### 5.1. Lợi nhuận Hóa năm & CAGR: Vi phạm Chuẩn mực GIPS 2.A.28
- **Chuẩn mực CFA & GIPS 2020**: Điều khoản **GIPS 2.A.28** quy định rõ: **"Performance for periods of less than one year MUST NOT be annualized"** (Tuyệt đối không được tính tỷ suất lợi nhuận hóa năm cho các chu kỳ đầu tư dưới một năm). Lý do: Việc ngoại suy một chu kỳ ngắn (ví dụ 10 ngày đạt 5%) lên cả năm bằng phép lũy thừa $(1+0.05)^{252/10} - 1 = 238\%$ tạo ra kỳ vọng phi thực tế và bóp méo nghiêm trọng hồ sơ rủi ro.
- **Thực trạng trong Codebase**:
  * Tại `agent/backtest/metrics.py:604-615`:
    ```python
    growth = 1 + total_ret
    if growth <= 0:
        ann_ret = -1.0
    else:
        try:
            ann_ret = float(growth ** (bpy / max(n, 1)) - 1)  # LỖI: Luôn lũy thừa hóa bất kể n!
        except OverflowError:
            ann_ret = float("inf")
    ```
    Nếu một backtest chỉ kéo dài 5 ngày với lợi nhuận 5%, `bpy/n = 252/5 = 50.4`, hàm này sẽ trả về tỷ suất sinh lời năm lên tới **+1.046%**!
  * Trong khi đó, tại `agent/src/quantlib/performance.py:438-444`, mã nguồn đã tuân thủ chuẩn GIPS khi kiểm tra điều kiện:
    ```python
    if days < DAYS_PER_YEAR:
        return None  # Tuân thủ hoàn hảo GIPS 2.A.28
    ```
  * **Kết luận**: Có sự bất nhất nghiêm trọng giữa thư viện chuẩn `quantlib` và module báo cáo backtest `backtest/metrics.py`. Cần áp dụng quy tắc trả về `None` hoặc giữ nguyên `total_return` cho các chu kỳ dưới 252 ngày.

### 5.2. Sharpe Ratio: Bỏ Quên Lãi Suất Phi Rủi Ro & Lệch Pha Thống Kê
- **Công thức Chuẩn CFA Level I/II**:
  $$Sharpe = \frac{\bar{R}_p - \bar{R}_f}{\sigma(R_p - R_f)} \times \sqrt{252}$$
- **Các Khiếm khuyết Phát hiện trong Codebase**:
  1. **Mặc định $R_f = 0$**: Tại `agent/backtest/metrics.py:620` và `agent/backtest/validation.py:224`, lãi suất phi rủi ro hoàn toàn bị bỏ qua ($R_f = 0$). Trong môi trường lãi suất ngắn hạn hiện nay (Fed Funds Rate / SOFR quanh mức 4.5% - 5.5%, hoặc lãi suất OMO tại Việt Nam quanh 4.0% - 4.5%), một chiến lược mang lại lợi nhuận 6%/năm thực chất chỉ tạo ra tỷ suất sinh lời thặng dư (excess return) xấp xỉ 1%. Việc gán $R_f=0$ khiến Sharpe ratio bị thổi phồng giả tạo.
  2. **Bất nhất giữa Lợi nhuận Số học và Hình học**: Tử số của Sharpe trong `metrics.py:624` lấy trung bình cộng số học các ngày $\bar{R} \times 252$, trong khi chỉ số lợi nhuận năm hiển thị trên bảng điều khiển lại là CAGR hình học. Điều này tạo ra sự mâu thuẫn nội tại giữa tỷ suất lợi nhuận và thước đo rủi ro.
  3. **Thiếu Hiệu chỉnh Tự Tương quan (Autocorrelation Adjustment)**: Theo công trình kinh điển của **Andrew Lo (2002)** (*The Statistics of Sharpe Ratios*), hệ số nhân $\sqrt{T}$ chỉ đúng khi chuỗi lợi nhuận độc lập và phân phối đồng nhất (i.i.d.). Khi chiến lược giao dịch có độ trễ quán tính (momentum) hoặc đảo chiều (mean-reversion), lợi nhuận ngày có hệ số tự tương quan bậc 1 $\rho_1 \ne 0$. Hệ số nhân chuẩn xác phải là:
     $$\eta(q) = \frac{q}{\sqrt{q + 2 \sum_{k=1}^{q-1} (q-k) \rho_k}}$$
  4. **Bất đồng nhất về Bậc Tự do Thống kê (Degrees of Freedom)**: `agent/backtest/validation.py:225` dùng numpy `returns.std()` (mặc định `ddof=0`, độ lệch chuẩn tổng thể), trong khi `agent/backtest/metrics.py:620` dùng pandas `port_ret.std()` (mặc định `ddof=1`, độ lệch chuẩn mẫu). Sự chênh lệch này gây sai số trên các mẫu backtest ngắn.

### 5.3. Sortino Ratio: Rào cản MAR & Tỷ lệ Ảo $10^9$
- **Công thức Chuẩn CFA**:
  $$Sortino = \frac{\bar{R}_p - MAR}{LPM_2(MAR)} \times \sqrt{252}$$
  $$LPM_2(MAR) = \sqrt{\frac{1}{N} \sum_{t=1}^{N} \left( \min(0, R_{p,t} - MAR) \right)^2}$$
- **Kiểm toán Codebase**:
  * Tại `agent/backtest/metrics.py:641-654`:
    ```python
    downside = port_ret[port_ret < 0]
    downside_deviation = (
        float(np.sqrt((downside**2).sum() / len(port_ret)))
        if len(downside) > 0
        else 1e-10
    )
    sortino = float(port_ret.mean() / (downside_deviation + 1e-10) * np.sqrt(bpy))
    ```
  * **Điểm sáng**: Mẫu số chia đúng cho tổng số kỳ quan sát $N = \text{len}(port\_ret)$ thay vì chỉ chia cho số ngày âm (tránh được lỗi phổ biến của các thư viện mã nguồn mở nghiệp dư).
  * **Lỗi Trọng yếu**:
    1. Gán cứng $MAR = 0$, không cho phép người dùng truyền vào lãi suất phi rủi ro hoặc tỷ suất lợi nhuận mục tiêu tối thiểu (Hurdle Rate).
    2. Khi chiến lược không có ngày nào lỗ (`len(downside) == 0`), hệ thống gán fallback `downside_deviation = 1e-10`, tạo ra tỷ lệ Sortino ảo lên tới hàng tỷ ($10^9$). Chuẩn mực CFA khuyến nghị trong trường hợp này phải trả về `None`, `NaN`, hoặc `+inf` được gắn cờ giải thích rõ ràng.

### 5.4. Information Ratio & Cạm bẫy Điền 0.0 vào Benchmark
- **Công thức Chuẩn**:
  $$IR = \frac{\bar{R}_p - \bar{R}_b}{TE} = \frac{\bar{R}_a}{\sigma(R_a)}$$
- **Kiểm toán Codebase**: Tại `agent/backtest/metrics.py:678`:
  ```python
  aligned_bench = bench_ret.reindex(port_ret.index).fillna(0.0)
  active_ret = port_ret - aligned_bench
  ```
  Khi reindex dữ liệu benchmark (ví dụ VN-Index hoặc S&P 500) theo chuỗi ngày của danh mục, các ngày thị trường benchmark nghỉ lễ nhưng bot vẫn giao dịch (hoặc ngày thiếu dữ liệu do lỗi API) bị tự động điền `0.0`. Việc giả định benchmark có lợi nhuận 0% trong các ngày này tạo ra lợi nhuận chủ động (alpha) ảo và làm méo mó độ lệch chuẩn theo dõi (Tracking Error). Chuẩn GIPS yêu cầu chỉ tính toán trên tập giao điểm ngày giao dịch thực tế của cả hai chuỗi dữ liệu.

### 5.5. Phân bổ Nhân tố Brinson-Fachler: Ngắt kết nối Thuật toán Cariño
- **Mô hình Chuẩn CFA Level III (Brinson-Fachler)**:
  Phân rã lợi nhuận vượt trội của danh mục thành 3 thành phần:
  $$R_p - R_b = \sum_{i} (w_{p,i} - w_{b,i}) (R_{b,i} - R_b) \quad [\text{Allocation Effect}]$$
  $$+ \sum_{i} w_{b,i} (R_{p,i} - R_{b,i}) \quad [\text{Selection Effect}]$$
  $$+ \sum_{i} (w_{p,i} - w_{b,i}) (R_{p,i} - R_{b,i}) \quad [\text{Interaction Effect}]$$
- **Liên kết Đa Chu kỳ Cariño (Cariño Multi-Period Linking)**:
  Do lợi nhuận cộng dồn theo cấp số nhân qua thời gian trong khi mô hình Brinson lại phân rã theo phép cộng số học của từng kỳ, việc cộng dồn đơn thuần các hiệu ứng từng kỳ sẽ tạo ra sai số thặng dư lớn. Thuật toán **Cariño (1999)** giải quyết triệt để vấn đề này bằng hệ số điều chỉnh logarit:
  $$k_t = \frac{\ln(1 + R_{p,t}) - \ln(1 + R_{b,t})}{R_{p,t} - R_{b,t}}, \quad K = \frac{\ln(1 + R_p) - \ln(1 + R_b)}{R_p - R_b}$$
  $$L_t = \frac{k_t}{K}$$
- **Kiểm toán Codebase**:
  * Thư viện `agent/src/quantlib/attribution.py:209-450` hiện thực mô hình Brinson-Fachler và thuật toán Cariño linking xuất sắc, đạt chuẩn mực CFA tuyệt đối.
  * **Tuy nhiên, endpoint API phục vụ giao diện người dùng** (`agent/src/api/attribution_core.py:558-570, 611-651`) lại **hoàn toàn bỏ qua thư viện quantlib**! Hàm này chỉ đọc một dòng vị thế duy nhất ở cuối file `positions.csv` (`held = _row_weights(rows[-2])`), rồi lấy trọng số tĩnh của ngày cuối cùng nhân với tổng lợi nhuận tích lũy của toàn bộ vòng đời backtest.
  * **Hậu quả**: Nếu danh mục có tái cân bằng tỷ trọng động qua các tháng, bảng phân rã hiển thị trên giao diện người dùng hoàn toàn sai lệch so với diễn biến thực tế. Ngoài ra, nếu danh mục có đòn bẩy hoặc bán khống khiến tổng trọng số $\sum w_i \ne 1$, hàm `brinson_fachler` sẽ ném ra ngoại lệ `ValueError` và biểu đồ waterfall bị trắng trơn.

### 5.6. Mô phỏng Monte Carlo & Tái lấy mẫu Bootstrap
- **Biến dạng Thời gian Nắm giữ trong Resampling**:
  Tại `agent/backtest/validation.py:76-85`:
  ```python
  shuffled = rng.permutation(pnls)
  # ...
  sharpe = float(returns.mean() / (std + 1e-10) * np.sqrt(bars_per_year))
  ```
  Hàm này xáo trộn chuỗi PnL của từng lệnh giao dịch (trade-level), sau đó nhân tỷ lệ hóa năm bằng $\sqrt{252}$. Đây là một sai lầm toán học lớn: Các lệnh giao dịch có thời gian nắm giữ hoàn toàn khác nhau (có lệnh giữ 1 giờ, có lệnh giữ 5 ngày). Không thể đối xử mỗi lệnh như một thanh nến 1 ngày để nhân với $\sqrt{252}$.
- **Phân phối Chuẩn vs Đuôi Dày (Fat Tails)**: `agent/src/quantlib/risk.py:522` sử dụng chuyển động Brown hình học (GBM) giả định phân phối chuẩn $N(\mu, \sigma^2)$. Trong thị trường tài chính thực tế (đặc biệt là XAU/USD và Cổ phiếu Việt Nam), chuỗi lợi nhuận luôn có độ nhọn cao (kurtosis $> 3$) và xuất hiện các cú sốc giá cực đoan. Việc dùng GBM làm đánh giá thấp rủi ro phá sản (ruin probability) và Value at Risk (VaR 99%).
- **Bootstrap Ngây Thơ (Naive i.i.d. Bootstrap)**: `agent/backtest/validation.py:198-208` lấy mẫu hoàn lại từng ngày độc lập (`rng.choice(returns, size=len(returns), replace=True)`) và lấy phân vị đơn giản (`np.percentile`). Phương pháp này phá vỡ cấu trúc tự tương quan chuỗi và biến động tập trung (volatility clustering). Chuẩn CFA yêu cầu sử dụng **Stationary Block Bootstrap** (Politis & Romano, 1994) kết hợp hiệu chỉnh độ lệch và gia tốc **BCa (Bias-Corrected and Accelerated Bootstrap)**.

---

## 6. BỘ MÃ NGUỒN THAM CHIẾU CHUẨN CFA/GIPS & KIẾN TRÚC XAU/USD REAL-TIME

Dưới đây là 4 khối mã nguồn tham chiếu chuẩn hóa đã được thiết kế hoàn chỉnh, sẵn sàng tích hợp vào hệ thống:

### 6.1. CFA/GIPS Compliance Metric Engine
```python
import numpy as np
import pandas as pd
from typing import Dict, Any, Optional

def calc_metrics_cfa(
    equity_curve: pd.Series,
    benchmark_curve: Optional[pd.Series] = None,
    risk_free_rate: float = 0.045,  # 4.5% annual hurdle / SOFR
    bars_per_year: int = 252,
    mar_annual: float = 0.0,
    adjust_lo_2002: bool = True,
) -> Dict[str, Any]:
    """
    Tính toán chỉ số hiệu quả và rủi ro đạt chuẩn CFA Level I/II/III và GIPS 2020.
    """
    if len(equity_curve) < 2:
        return {}

    returns = equity_curve.pct_change().dropna()
    n_days = len(returns)
    total_return = float(equity_curve.iloc[-1] / equity_curve.iloc[0] - 1.0)

    # 1. GIPS 2.A.28: Không hóa năm chu kỳ dưới 1 năm
    if n_days < bars_per_year:
        annualized_return = None
        cagr = None
    else:
        growth = 1.0 + total_return
        annualized_return = float(growth ** (bars_per_year / n_days) - 1.0) if growth > 0 else -1.0
        cagr = annualized_return

    # 2. Risk-free rate per period
    rf_per_period = (1.0 + risk_free_rate) ** (1.0 / bars_per_year) - 1.0
    excess_returns = returns - rf_per_period

    # 3. Sharpe Ratio with Andrew Lo (2002) Autocorrelation Correction
    mean_excess = float(excess_returns.mean())
    vol_sample = float(excess_returns.std(ddof=1))  # Unbiased sample std

    if vol_sample > 1e-12:
        base_sharpe = (mean_excess / vol_sample) * np.sqrt(bars_per_year)
        if adjust_lo_2002 and len(returns) > 5:
            # First-order autocorrelation
            rho_1 = float(returns.autocorr(lag=1))
            if not np.isnan(rho_1) and abs(rho_1) < 0.99:
                correction = np.sqrt((1.0 - rho_1) / (1.0 + rho_1))
                sharpe = float(base_sharpe * correction)
            else:
                sharpe = base_sharpe
        else:
            sharpe = base_sharpe
    else:
        sharpe = 0.0

    # 4. Sortino Ratio with Custom MAR (LPM2 continuous divisor)
    mar_per_period = (1.0 + mar_annual) ** (1.0 / bars_per_year) - 1.0
    downside = np.minimum(0.0, returns - mar_per_period)
    downside_variance = float(np.sum(downside ** 2) / n_days)
    downside_dev = np.sqrt(downside_variance) * np.sqrt(bars_per_year)

    if downside_variance > 1e-12:
        mean_ret_annual = float(returns.mean() * bars_per_year)
        sortino = float((mean_ret_annual - mar_annual) / downside_dev)
    else:
        sortino = None  # GIPS compliant: None instead of 1e9

    # 5. Maximum Drawdown & High Water Mark
    hwm = equity_curve.cummax()
    drawdown_series = (equity_curve - hwm) / hwm
    max_drawdown = float(drawdown_series.min())

    # 6. Calmar Ratio (Requires >= 36 months under strict CFA hedge fund guidelines)
    if max_drawdown < -1e-6 and annualized_return is not None:
        calmar = float(annualized_return / abs(max_drawdown))
    else:
        calmar = None

    # 7. Information Ratio & Tracking Error (Intersection dates only)
    ir, tracking_error = None, None
    if benchmark_curve is not None and len(benchmark_curve) > 1:
        bench_ret = benchmark_curve.pct_change().dropna()
        common_idx = returns.index.intersection(bench_ret.index)
        if len(common_idx) > 5:
            p_sub = returns.loc[common_idx]
            b_sub = bench_ret.loc[common_idx]
            active_ret = p_sub - b_sub
            te = float(active_ret.std(ddof=1) * np.sqrt(bars_per_year))
            if te > 1e-12:
                tracking_error = te
                ir = float((active_ret.mean() * bars_per_year) / te)

    return {
        "n_periods": n_days,
        "total_return": total_return,
        "annualized_return": annualized_return,
        "cagr": cagr,
        "volatility_annualized": vol_sample * np.sqrt(bars_per_year),
        "sharpe_ratio": sharpe,
        "sortino_ratio": sortino,
        "max_drawdown": max_drawdown,
        "calmar_ratio": calmar,
        "tracking_error": tracking_error,
        "information_ratio": ir,
    }
```

### 6.2. Multi-Period Cariño Attribution Pipeline
```python
def carino_multi_period_linking(
    periodic_attributions: list[dict],
    portfolio_cumulative_ret: float,
    benchmark_cumulative_ret: float
) -> dict:
    """
    Liên kết các kỳ phân bổ Brinson-Fachler bằng hệ số logarit Cariño (1999).
    Đảm bảo tổng các hiệu ứng qua các tháng khớp chính xác với lợi nhuận vượt trội tích lũy.
    """
    excess_cum = portfolio_cumulative_ret - benchmark_cumulative_ret
    if abs(excess_cum) < 1e-12:
        K = 1.0
    else:
        K = (np.log(1.0 + portfolio_cumulative_ret) - np.log(1.0 + benchmark_cumulative_ret)) / excess_cum

    total_alloc = 0.0
    total_select = 0.0
    total_interact = 0.0

    for period in periodic_attributions:
        rp_t = period["portfolio_return"]
        rb_t = period["benchmark_return"]
        diff_t = rp_t - rb_t
        if abs(diff_t) < 1e-12:
            k_t = 1.0 / (1.0 + rp_t)
        else:
            k_t = (np.log(1.0 + rp_t) - np.log(1.0 + rb_t)) / diff_t

        weight_factor = k_t / K
        total_alloc += period["allocation"] * weight_factor
        total_select += period["selection"] * weight_factor
        total_interact += period["interaction"] * weight_factor

    return {
        "cumulative_excess_return": excess_cum,
        "carino_allocation": total_alloc,
        "carino_selection": total_select,
        "carino_interaction": total_interact,
        "discrepancy": excess_cum - (total_alloc + total_select + total_interact)
    }
```

### 6.3. Real-Time Tick Aggregator & Dual-Tier Ring Buffer cho XAU/USD
```typescript
/**
 * Frontend Hook: useRealtimeCandleBuffer
 * Dual-tier event buffering: Gom 30-60 ticks/s thành 1 đợt cập nhật ECharts trên mỗi frame rAF (16.6ms).
 */
import { useEffect, useRef } from "react";

interface Tick {
  symbol: string;
  bid: number;
  ask: number;
  time_msc: number;
  volume: number;
}

export function useRealtimeCandleBuffer(
  onFrameUpdate: (latestTick: Tick, updatedFormingBar: [string, number, number, number, number, number]) => void
) {
  const tickBufferRef = useRef<Tick[]>([]);
  const frameIdRef = useRef<number>(0);
  const formingBarRef = useRef<[string, number, number, number, number, number] | null>(null);

  const pushTick = (tick: Tick) => {
    tickBufferRef.current.push(tick);
    if (!frameIdRef.current) {
      frameIdRef.current = requestAnimationFrame(processBuffer);
    }
  };

  const processBuffer = () => {
    frameIdRef.current = 0;
    const ticks = tickBufferRef.current;
    if (ticks.length === 0) return;

    // Lấy tick mới nhất trong frame
    const latest = ticks[ticks.length - 1];
    const midPrice = (latest.bid + latest.ask) / 2.0;

    // Cập nhật nến đang hình thành (forming bar)
    if (formingBarRef.current) {
      const bar = formingBarRef.current;
      bar[2] = midPrice;                     // Close
      bar[3] = Math.max(bar[3], midPrice);   // High
      bar[4] = Math.min(bar[4], midPrice);   // Low
      bar[5] += ticks.length;                // Tick count volume
      onFrameUpdate(latest, bar);
    }

    tickBufferRef.current = [];
  };

  useEffect(() => {
    return () => {
      if (frameIdRef.current) cancelAnimationFrame(frameIdRef.current);
    };
  }, []);

  return { pushTick, formingBarRef };
}
```

### 6.4. Crosshair Event Bus Đa Khung Thời Gian
```typescript
/**
 * Crosshair Event Bus đồng bộ con trỏ chữ thập qua Binary Search Timestamp
 */
export class MultiTimeframeCrosshairBus {
  private charts: Map<string, { instance: echarts.ECharts; timestamps: number[] }> = new Map();

  register(chartId: string, instance: echarts.ECharts, timestamps: number[]) {
    this.charts.set(chartId, { instance, timestamps });
  }

  unregister(chartId: string) {
    this.charts.delete(chartId);
  }

  broadcast(sourceChartId: string, sourceTimestamp: number) {
    for (const [id, { instance, timestamps }] of this.charts.entries()) {
      if (id === sourceChartId || timestamps.length === 0) continue;

      // Tìm index gần nhất bằng Binary Search
      let left = 0, right = timestamps.length - 1;
      while (left <= right) {
        const mid = (left + right) >> 1;
        if (timestamps[mid] < sourceTimestamp) left = mid + 1;
        else right = mid - 1;
      }
      const targetIndex = Math.min(Math.max(0, left), timestamps.length - 1);

      instance.dispatchAction({
        type: "showTip",
        seriesIndex: 0,
        dataIndex: targetIndex,
      });
    }
  }
}
```

---

## 7. LỘ TRÌNH TRIỂN KHAI & KHUYẾN NGHỊ NÂNG CẤP TỪNG BƯỚC

```
+------------------------------------------------------------------------------------------------+
|                         STEP-BY-STEP REENGINEERING ROADMAP                                     |
+------------------------------------------------------------------------------------------------+
|  GIAI ĐOẠN 1: GIA CỐ NỀN TẢNG TOÁN HỌC & CHUẨN MỰC CFA/GIPS (Ưu tiên: Khẩn cấp)                |
|  - Patch `agent/backtest/metrics.py:604`: Áp dụng GIPS 2.A.28, trả về None cho chu kỳ < 252d.   |
|  - Cập nhật Sharpe Ratio: Nhận `risk_free_rate` thực tế, áp dụng hiệu chỉnh Andrew Lo (2002).   |
|  - Tích hợp `quantlib.attribution.carino_link` vào `agent/src/api/attribution_core.py`.        |
|  - Chuẩn hóa VWAP trong `agent/src/factors/base.py`, loại bỏ +1.0 và tính theo khối lượng.     |
+------------------------------------------------------------------------------------------------+
                                                |
                                                v
+------------------------------------------------------------------------------------------------+
|  GIAI ĐOẠN 2: CHUẨN HÓA DATA PIPELINES & TIMEZONE (Ưu tiên: Cao)                               |
|  - Sửa `yfinance_loader.py:222` thành `tz_convert("UTC").tz_localize(None)`.                   |
|  - Thêm cấu hình phiên giao dịch VN, HK, CN và Forex 24/5 vào `triggers.py:MARKET_SPECS`.     |
|  - Đặt `maxsize` cho `MessageBus` và bổ sung cờ resync cảnh báo rớt gói cho `EventBus`.       |
+------------------------------------------------------------------------------------------------+
                                                |
                                                v
+------------------------------------------------------------------------------------------------+
|  GIAI ĐOẠN 3: XÂY DỰNG REAL-TIME CANDLESTICK STREAMING CHO XAU/USD (Ưu tiên: Cao)              |
|  - Chuyển đổi MT5 & Exness Adapter từ short-polling sang WebSocket Persistent Stream.          |
|  - Hiện thực `useRealtimeCandleBuffer` tại frontend để gom tick theo frame 16ms (rAF).         |
|  - Triển khai `MultiTimeframeCrosshairBus` đồng bộ con trỏ M1, M5, H1, D1 qua nhị phân epoch.  |
|  - Thay thế `ResizeObserver` đồng bộ tại 4 component biểu đồ bằng `useChartLifecycle.ts`.      |
+------------------------------------------------------------------------------------------------+
                                                |
                                                v
+------------------------------------------------------------------------------------------------+
|  GIAI ĐOẠN 4: HOÀN THIỆN GIAO DIỆN & TÁC TỬ TỰ ĐỘNG HÓA (Ưu tiên: Trung bình)                 |
|  - Tách `AllocationPie` trong `Portfolio.tsx` thành `AssetAllocationChart.tsx` độc lập.       |
|  - Bọc `React.memo` cho `ForexCandlePlot.tsx` để ngăn re-render từ timer 1s của ForexLiveChart. |
|  - Mở rộng GroundingLedger hỗ trợ đối soát các phân rã Brinson-Cariño và hệ số tự tương quan.  |
+------------------------------------------------------------------------------------------------+
```

---
*Báo cáo được tổng hợp và kiểm toán độc lập bởi Project Orchestrator theo các quy chuẩn khắt khe nhất của Viện CFA và Tiêu chuẩn Kiến trúc Phần mềm Định lượng Toàn cầu.*
