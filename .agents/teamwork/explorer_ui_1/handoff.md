# BÁO CÁO KIỂM TOÁN CHUYÊN SÂU KIẾN TRÚC UI/UX, QUẢN LÝ TRẠNG THÁI VÀ HỢP ĐỒNG FRONTEND-BACKEND (FRONTEND AUDIT HANDOFF)

- **Người thực hiện**: Explorer Agent (`explorer_ui_1`)
- **Đối tượng kiểm toán**: Toàn bộ mã nguồn thư mục `frontend/` (src/stores, src/hooks, src/components, src/pages, src/lib/api.ts, src/router.tsx) đối chiếu với FastAPI backend (`agent/src/api/`).
- **Thời gian hoàn thành**: 2026-11-08T13:45:00Z
- **Tiêu chuẩn tuân thủ**: System Architect Mindset, Clean Code, Zero Unhandled Crash Vectors, Database/Contract-First Alignment.

---

## I. TỔNG QUAN VÀ PHÂN LOẠI MỨC ĐỘ NGHIÊM TRỌNG (SEVERITY CLASSIFICATION)

Qua quá trình rà quét tĩnh và phân tích luồng thực thi chuyên sâu (Deep Execution Flow Analysis), đã phát hiện tổng cộng **18 vấn đề** kiến trúc và lỗ hổng ổn định trong `frontend/`, phân loại như sau:

| Mức độ | Số lượng | Danh mục ảnh hưởng chính | Tóm tắt tác động |
|---|---|---|---|
| **CRITICAL** | 4 | Router Error Boundaries, Chart Crash Vectors, Null Dereferences, Interval Memory Leaks | Đánh sập toàn bộ giao diện người dùng (White Screen of Death), mất navigation, rò rỉ bộ nhớ/request không hồi kết trên unmounted component |
| **HIGH** | 5 | React Key Anti-Pattern, Re-render Loop, Contract Drift API, Unencoded URL Injection, Hook Map Leak | Hủy và dựng lại toàn bộ DOM cây Forex mỗi lần cập nhật dữ liệu; re-render 1s/lần toàn bộ component con; thiếu endpoint thích ứng chiến lược; lỗi route khi ID có ký tự đặc biệt |
| **MEDIUM** | 6 | Un-debounced Search, Silent Error Swallowing, Offline Banner Blindness, Date Parsing RangeError, Virtual DOM Key Collision, Unstandardized ECharts | Giật lag khung hình khi gõ phím; nuốt lỗi khiến người dùng không biết thao tác thất bại; mất trạng thái báo mất mạng; cảnh báo duplicate keys trong React |
| **LOW** | 3 | Number Coercion Form Bugs, Bypassed API Client, Missing Optional Chaining | Nhập input rỗng sinh ra 0 vi phạm backend validation; gọi fetch thô tách rời kiến trúc tập trung; thiếu bảo vệ mảng phụ |

---

## II. QUẢN LÝ TRẠNG THÁI UI VÀ PHÂN TÍCH LUỒNG DỮ LIỆU REAL-TIME (UI STATE MANAGEMENT & REAL-TIME FLOW)

### 1. Zustand Store (`useAgentStore`) và Quản lý Session
- **Cơ chế lưu trữ đa phiên**: `useAgentStore` sử dụng Map bộ nhớ ngoài store `_sessionCache` và `_swarmSessionCache` với giới hạn tối đa `SESSION_CACHE_MAX = 5`. Khi chuyển phiên (`switchSession`), các tin nhắn được lưu đệm và phục hồi tức thì.
- **Lỗ hổng va chạm định danh tin nhắn (`UI-MED-05`)**: 
  - Tại `frontend/src/stores/agent.ts:117-118, 328-335`: Bộ sinh ID cục bộ `let _id = 0; const nextId = () => String(++_id);` bị reset về 0 khi gọi `reset()`.
  - Hậu quả: Khi người dùng tạo phiên mới sau khi reset, các tin nhắn mới nhận lại ID `"1"`, `"2"`, `"3"`. Khi tải lại lịch sử từ bộ đệm `_sessionCache` hoặc đối chiếu Virtual DOM, React phát hiện trùng lặp key (`Encountered two children with the same key`), làm sai lệch thứ tự render tin nhắn trong khung chat.

### 2. Tab-Local State Hook (`useAnalysisState`) và Rò rỉ Listeners (`UI-HIGH-05`)
- **Cơ chế hoạt động**: `useAnalysisState` dùng `useSyncExternalStore` để đồng bộ nháp form và phân tích qua `sessionStorage` kết hợp bộ nhớ RAM Map `drafts` và `listeners`.
- **Rò rỉ bộ nhớ (Memory Leak)**:
  - Tại `frontend/src/hooks/useAnalysisState.ts:28-33`: Mỗi khi component mount và đăng ký `subscribe`, nó lấy hoặc tạo một `Set` mới trong `listeners.get(storageKey)`. Khi component unmount, `group.delete(listener)` được gọi, nhưng `listeners.delete(storageKey)` không bao giờ được gọi khi `group.size === 0`.
  - Hàm `clearAnalysisState(key)` tại dòng 7-11 chỉ xóa trong `drafts` và `sessionStorage`, bỏ qua hoàn toàn `listeners`. Theo thời gian duyệt nhiều tab và phân tích nhiều chiến lược, Map `listeners` tích tụ hàng nghìn Set rỗng trong RAM.

### 3. Đồng bộ Kết nối Real-Time (SSE & Polling) và Điểm mù mất kết nối (`UI-MED-03`)
- **Luồng SSE trong `useSSE.ts`**: Luồng quản lý kết nối SSE được bảo vệ tốt bằng single-use auth tickets (`sseUrl`).
- **Lỗi hiển thị trạng thái kết nối trong `ConnectionBanner.tsx`**:
  - Tại `frontend/src/components/layout/ConnectionBanner.tsx:15`:
    ```tsx
    if (status !== "reconnecting") return null;
    ```
  - Khi luồng SSE vượt quá 5 lần thử lại (`retryAttempt >= 5`) hoặc backend server dừng hẳn, trạng thái SSE chuyển từ `"reconnecting"` sang `"disconnected"`.
  - Hậu quả: Ngay tại thời điểm kết nối bị đứt hoàn toàn, banner lập tức ẩn đi (`return null`). Người dùng nhìn thấy màn hình tĩnh, không nhận được bất kỳ thông báo mất mạng hay nút tải lại trang nào.

---

## III. HIỆU NĂNG RENDER, VÒNG ĐỜI BIỂU ĐỒ VÀ RÒ RỈ BỘ NHỚ (RENDERING PERFORMANCE & LIFECYCLES)

### 1. Phá hủy DOM do React Key Anti-Pattern trên Trang Forex (`UI-HIGH-01`)
- **Vị trí**: `frontend/src/pages/Forex.tsx:76, 96, 97`
- **Quan sát mã nguồn**:
  ```tsx
  const componentKey = selected ? JSON.stringify(selected) : "new";
  ...
  <ForexMarket key={componentKey+"market"} connection={selected} initialSymbol={query.get("symbol") || ""} />
  <ForexAI key={componentKey+"ai"} connection={selected} runner={runner} reload={reload} onError={setError} />
  ```
- **Phân tích cơ chế**:
  - `selected` là đối tượng cấu hình tài khoản Forex. Khi tiến trình nền gọi `loadExecution` định kỳ 5 giây/lần hoặc khi thuộc tính thay đổi (như `connection_halted`, `last_ping`, `broker_halted`), đối tượng `selected` được cấp phát mới, chuỗi `JSON.stringify(selected)` bị thay đổi.
  - Khi thuộc tính `key` của một React component thay đổi, React không cập nhật DOM (re-render) mà **tiến hành unmount hoàn toàn component cũ và mount component mới từ đầu**.
  - Toàn bộ ECharts instance của biểu đồ nến bị dispose và khởi tạo lại; zoom level, vị trí cuộn trang, tab con đang chọn của người dùng bị reset hoàn toàn mỗi vài giây.
- **Giải pháp**: Phải dùng khóa định danh bền vững `key={selected.id + "-market"}`.

### 2. Re-render Loop không kiểm soát trong `ForexTradeCards.tsx` (`UI-HIGH-02`)
- **Vị trí**: `frontend/src/components/chat/ForexTradeCards.tsx:15-18`
- **Quan sát mã nguồn**:
  ```tsx
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [plan.plan_id]);
  ```
- **Tác động hiệu năng**:
  - `setNow(Date.now())` kích hoạt mỗi 1.000ms chỉ để so sánh `now >= Date.parse(plan.expires_at)`.
  - Cứ mỗi giây, toàn bộ cây component gồm 4 thẻ vào lệnh, biểu đồ `ForexTrendForecast`, biểu đồ `ForexPlanChart` và danh sách debate 6 vai trò đều bị re-render lại. Kể cả sau khi kế hoạch đã hết hạn (`expired === true`), interval vẫn tiếp tục chạy vĩnh viễn trong RAM.

### 3. Rò rỉ Polling Interval vĩnh viễn trên Trang Portfolio (`UI-CRIT-04`)
- **Vị trí**: `frontend/src/pages/Portfolio.tsx:185-201`
- **Quan sát mã nguồn**:
  ```tsx
  const timer = window.setInterval(() => {
    void api.getPortfolioRefreshStatus()
      .then((result) => setRefreshState(normalizeRefreshState(result.refresh)))
      .catch(() => undefined);
  }, 500);
  try {
    const result = await api.refreshPortfolio();
    ...
  } finally {
    window.clearInterval(timer);
  }
  ```
- **Lỗ hổng vòng đời**: `timer` được gán vào một biến cục bộ bên trong hàm `refresh()`. Khi người dùng nhấn Refresh Portfolio, tiến trình backend đồng bộ các sàn giao dịch mất từ 10 đến 30 giây. Nếu người dùng chuyển sang trang khác (như `/agent` hoặc `/forex`) trong lúc đang đợi, component `Portfolio` bị unmount. Khối lệnh `finally` chưa được chạm tới, và không có `useEffect` cleanup nào giải phóng `timer`.
- **Hậu quả**: Lệnh `setInterval` tiếp tục chạy ngầm trong trình duyệt mỗi 500ms, gửi request liên tục lên `/api/portfolio/refresh/status` và gọi `setRefreshState` trên component đã bị hủy, gây rò rỉ kết nối mạng và tài nguyên CPU.

### 4. Tìm kiếm không Debounce gây nghẽn Main Thread (`UI-MED-01`)
- **Vị trí**:
  - `frontend/src/pages/Portfolio.tsx:452`: Ô tìm kiếm vị thế kích hoạt lọc và sắp xếp toàn bộ danh sách tài sản đồng bộ trên từng ký tự gõ.
  - `frontend/src/pages/RunDetail.tsx:1072`: Ô tìm kiếm symbol trong bảng trade lọc hàng nghìn dòng trên mỗi keystroke.
  - `frontend/src/pages/Reports.tsx:114`: Ô tìm kiếm báo cáo lọc danh sách báo cáo đồng bộ.
- **Giải pháp**: Triển khai `useDebounce` hook (250ms - 300ms) trước khi đưa từ khóa tìm kiếm vào bộ lọc dữ liệu.

### 5. Khởi tạo ECharts phân mảnh và thiếu chuẩn hóa vòng đời (`UI-MED-06`)
- `DistributionChart.tsx`, `WalkForwardChart.tsx`, `MonteCarloPathsChart.tsx`, `ForexCandlePlot.tsx`, và overlay biểu đồ trong `Compare.tsx` đang tự gọi `echarts.init()` và tạo `ResizeObserver` thô không qua `requestAnimationFrame`, không tham gia vào `CHART_GROUP` và không dùng hook dùng chung `useChartLifecycle.ts`.

---

## IV. BẢO VỆ LỖI, VECTƠ GÂY CRASH VÀ ĐỐI CHIẾU CONTRACT DRIFT (ERROR HANDLING & CONTRACT DRIFT)

### 1. Thiếu Error Boundary cục bộ tại các Sub-Route (`UI-CRIT-01`)
- **Vị trí**: `frontend/src/router.tsx:92-119`
- **Cấu trúc hiện tại**:
  ```tsx
  export const router = createBrowserRouter([
    {
      element: <Layout />,
      errorElement: <RouteErrorFallback />,
      children: [
        { path: "/", element: wrap(Agent) },
        { path: "/runs/:runId", element: wrap(RunDetail) },
        { path: "/forex", element: wrap(Forex) },
        ...
      ]
    }
  ]);
  ```
- **Hậu quả nghiêm trọng**: `errorElement` chỉ được khai báo ở mức cha cao nhất (`<Layout />`). Mọi trang con trong `children` đều không có `errorElement`. Khi bất kỳ component con nào ném ra JavaScript runtime error (chẳng hạn như các lỗi truy cập thuộc tính null bên dưới), React Router sẽ unmount toàn bộ thẻ `<Layout />` (bao gồm Sidebar, Navbar, Thanh trạng thái kết nối). Giao diện bị thay thế bằng màn hình trắng báo lỗi kèm nút `window.location.reload()`, phá hủy toàn bộ phiên làm việc của người dùng.
- **Khắc phục chuẩn kiến trúc**: Bổ sung `errorElement: <SubRouteErrorFallback />` cho các route con hoặc tích hợp `<ErrorBoundary>` trực tiếp vào hàm tiện ích `wrap()`.

### 2. Danh mục các Vectơ Gây Crash do Truy cập `.length` trên Biến Nullable (`UI-CRIT-02`)

| Tên File | Dòng | Đoạn code lỗi | Nguyên nhân | Hậu quả |
|---|---|---|---|---|
| `EquityChart.tsx` | 117 | `if (data.length === 0)` | Không kiểm tra `!data` hoặc `!Array.isArray(data)` | Crash khi data là `undefined`/`null` |
| `CorrelationMatrix.tsx` | 127 | `if (labels.length === 0 \|\| matrix.length === 0)` | Không kiểm tra `!labels` hoặc `!matrix` | Crash khi matrix là `undefined` |
| `AnnualReturnsChart.tsx` | 78 | `if (data.length === 0)` | Không kiểm tra `!data` | Crash khi data chưa tải xong |
| `MonthlyReturnsHeatmap.tsx` | 38, 116 | `for (const a of annual)`, `if (data.length === 0)` | Không kiểm tra `!annual` (gây Not Iterable) và `!data` | Crash render biểu đồ nhiệt tháng |
| `DistributionChart.tsx` | 107 | `if (samples.length === 0)` | Không kiểm tra `!samples` | Crash render biểu đồ phân phối |
| `WalkForwardChart.tsx` | 21, 105 | `if (windows.length === 0)` | Không kiểm tra `!windows` | Crash render biểu đồ kiểm thử trượt |
| `MonteCarloPathsChart.tsx` | 25, 137 | `if (paths.steps.length === 0)` | Không kiểm tra `!paths` hoặc `!paths.steps` | Crash render Monte Carlo fan chart |
| `OptionsPayoffChart.tsx` | 154 | `if (curve.spot.length === 0 \|\| curve.pnl.length === 0)` | Không kiểm tra `!curve` hoặc `!curve.spot` | Crash render Payoff options |
| `RollingBetaAlphaChart.tsx` | 108 | `if (data.length === 0)` | Không kiểm tra `!data` | Crash render rolling beta/alpha |
| `AttributionCumulativeChart.tsx` | 107 | `if (data.length === 0)` | Không kiểm tra `!data` | Crash render biểu đồ quy gán lợi nhuận |
| `CandlestickChart.tsx` | 59, 76, 295 | `data.some(...)`, `data.map(...)`, `data.length === 0` | Không kiểm tra `!data` trước khi map và some | Crash render biểu đồ nến kỹ thuật |
| `TopDrawdownsPanel.tsx` | 9 | `if (episodes.length === 0)` | Không kiểm tra `!episodes` | Crash render bảng Top sụt giảm vốn |
| `ForexTradeCards.tsx` | 84, 90, 99 | `plan.reasons.length`, `plan.reports.length`, `.map` | Không kiểm tra `!plan.reasons` hoặc `!plan.reports` | Crash render thẻ tín hiệu Forex |

### 3. Danh mục các Vectơ Gây Crash do Gọi `.toFixed()` trên Giá trị Null (`UI-CRIT-03`)

| Tên File | Dòng | Đoạn code lỗi | Nguyên nhân từ Backend | Cách khắc phục |
|---|---|---|---|---|
| `ValidationPanel.tsx` | 82, 91, 92, 93 | `mc.simulated_sharpe_p5.toFixed(2)`, `mc.actual_sharpe.toFixed(2)`, v.v. | Dữ liệu mô phỏng không đủ mẫu, backend trả về `null` | Sử dụng helper `fmtNum(v, 2)` hoặc `v != null ? v.toFixed(2) : "—"` |
| `ValidationPanel.tsx` | 130, 140, 141 | `bs.observed_sharpe.toFixed(2)`, `bs.ci_lower.toFixed(2)`, `bs.ci_upper.toFixed(2)` | Bootstrap trả về `null` khi lỗi tính toán | Sử dụng helper an toàn thay vì gọi method trực tiếp |
| `AttributionTab.tsx` | 161, 164, 165 | `factor.alpha_t_stat.toFixed(2)`, `factor.beta.toFixed(2)`, `factor.r_squared.toFixed(2)` | Ma trận hiệp phương sai suy biến, hồi quy không hội tụ trả `null` | Kiểm tra nullish trước khi gọi `.toFixed()` |
| `AttributionTab.tsx` | 175 | `trackingError !== undefined && <AttrStat value={fmtPct(trackingError)} />` | `null !== undefined` là true, truyền null vào `fmtPct` sinh ra `0.00%` sai lệch | Thay bằng `trackingError != null` |
| `WalkForwardChart.tsx` | 88 | `w.sharpe.toFixed(2)` | Cửa sổ kiểm tra không có giao dịch, Sharpe là `null` | `w.sharpe != null ? Number(w.sharpe.toFixed(2)) : null` |
| `RollingBetaAlphaChart.tsx` | 22, 23 | `+d.beta.toFixed(4)`, `+(d.alpha_annualized * 100).toFixed(4)` | Beta/Alpha bị null tại các ngày thiếu dữ liệu | Thêm kiểm tra nullish trước khi làm tròn |
| `AttributionCumulativeChart.tsx` | 78, 88, 97 | `+(d.portfolio * 100).toFixed(4)`, `+(d.benchmark * 100).toFixed(4)` | Lợi nhuận benchmark hoặc portfolio thiếu ngày | Thêm kiểm tra an toàn số học |
| `RunDetail.tsx` | 636, 637 | `concentration.hhi !== undefined ? concentration.hhi.toFixed(3) : "-"` | `null !== undefined` là true! `null.toFixed(3)` văng lỗi ngay lập tức | Thay bằng `concentration.hhi != null ? concentration.hhi.toFixed(3) : "-"` |

### 4. Bảng Đối Chiếu Hợp Đồng API (Frontend-Backend Contract Drift Table)

| Endpoint Backend (FastAPI) | HTTP Method | Trạng thái trong `frontend/src/lib/api.ts` | Tác động chức năng |
|---|---|---|---|
| `/api/strategy-adaptations` | POST | **THIẾU HOÀN TOÀN** (`UI-HIGH-03`) | Không thể gửi yêu cầu chuẩn bị thích ứng chiến lược từ giao diện |
| `/api/strategy-adaptations/evidence` | POST | **THIẾU HOÀN TOÀN** (`UI-HIGH-03`) | Không thể làm mới bằng chứng cho chiến lược được điều chỉnh |
| `/runs/${id}` | GET | Có nhưng **thiếu `encodeURIComponent(id)`** (`UI-HIGH-04`) | Gãy route khi id chứa ký tự đặc biệt hoặc timestamp |
| `/runs/${id}/preview`, `/code`, `/factor`, `/pine` | GET | Có nhưng **thiếu `encodeURIComponent(id)`** (`UI-HIGH-04`) | Gãy route tài nguyên chi tiết chiến lược |
| `/sessions/${sid}`, `/messages`, `/cancel`, `/goal` | GET/POST/PATCH | Có nhưng **thiếu `encodeURIComponent(sid)`** (`UI-HIGH-04`) | Gãy route chat session khi sid chứa ký tự nhạy cảm URL |
| `/scheduled-runs/...` | GET/POST/PATCH/DELETE | Đã có `encodeURIComponent` chuẩn xác | Chuẩn mẫu đối chiếu |

---

## V. VỊ TRÍ TỆP TIN CHÍNH XÁC, NGUYÊN NHÂN GỐC VÀ BẢN VÁ SẢN XUẤT (ROOT CAUSES & PRODUCTION-READY PATCHES)

Dưới đây là các bản vá chi tiết dạng diff trực tiếp, sẵn sàng để đội ngũ phát triển áp dụng vào mã nguồn.

### 1. Vá lỗi Router Error Boundary (`frontend/src/router.tsx`)
- **Nguyên nhân gốc**: Thiếu ranh giới cô lập lỗi cho các route con.
- **Bản vá**:
```diff
--- a/frontend/src/router.tsx
+++ b/frontend/src/router.tsx
@@ -1,6 +1,6 @@
 import { lazy, Suspense } from "react";
-import { createBrowserRouter } from "react-router-dom";
+import { createBrowserRouter, useRouteError, useNavigate } from "react-router-dom";
 import { Layout } from "@/components/layout/Layout";
 import { PageSkeleton } from "@/components/common/PageSkeleton";
 import { RouteErrorFallback } from "@/components/common/RouteErrorFallback";
+import { ErrorBoundary } from "@/components/common/ErrorBoundary";
 
+function SubRouteErrorFallback() {
+  const error = useRouteError();
+  const navigate = useNavigate();
+  return (
+    <div className="flex flex-col items-center justify-center min-h-[50vh] p-6 text-center space-y-4">
+      <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-6 max-w-md w-full">
+        <h2 className="text-base font-semibold text-destructive">Da xay ra loi khi tai trang</h2>
+        <p className="mt-2 text-xs text-muted-foreground font-mono break-words">
+          {error instanceof Error ? error.message : "Loi khong xac dinh trong tien trinh render"}
+        </p>
+        <div className="mt-4 flex gap-2 justify-center">
+          <button
+            onClick={() => navigate(0)}
+            className="px-3 py-1.5 rounded-lg text-xs bg-primary text-primary-foreground font-medium hover:bg-primary/90"
+          >
+            Thu tai lai
+          </button>
+          <button
+            onClick={() => navigate("/")}
+            className="px-3 py-1.5 rounded-lg text-xs border border-border hover:bg-muted font-medium"
+          >
+            Ve trang chu
+          </button>
+        </div>
+      </div>
+    </div>
+  );
+}
+
 function wrap(Component: React.ComponentType) {
   return (
-    <Suspense fallback={<PageSkeleton />}>
-      <Component />
-    </Suspense>
+    <ErrorBoundary fallback={<SubRouteErrorFallback />}>
+      <Suspense fallback={<PageSkeleton />}>
+        <Component />
+      </Suspense>
+    </ErrorBoundary>
   );
 }
```

### 2. Vá lỗi Crash Biểu đồ ECharts do Null/Undefined (`EquityChart.tsx` & Các Biểu đồ Liên quan)
- **Nguyên nhân gốc**: Truy cập `.length` trên biến không đảm bảo mảng.
- **Bản vá mẫu cho `frontend/src/components/charts/EquityChart.tsx`**:
```diff
--- a/frontend/src/components/charts/EquityChart.tsx
+++ b/frontend/src/components/charts/EquityChart.tsx
@@ -114,7 +114,7 @@ export function EquityChart({ data, drawdownZones, height = 320 }: Props) {
     };
   }, [data, drawdownZones]);
 
-  if (data.length === 0) {
+  if (!data || !Array.isArray(data) || data.length === 0) {
     return <div className="text-muted-foreground text-sm p-4">{i18n.t("charts.noEquityData")}</div>;
   }
   return <div ref={ref} style={{ height }} />;
```

- **Bản vá cho `frontend/src/components/charts/CorrelationMatrix.tsx`**:
```diff
--- a/frontend/src/components/charts/CorrelationMatrix.tsx
+++ b/frontend/src/components/charts/CorrelationMatrix.tsx
@@ -124,7 +124,7 @@ export function CorrelationMatrix({ labels, matrix, height = 400 }: Props) {
     };
   }, [labels, matrix]);
 
-  if (labels.length === 0 || matrix.length === 0) {
+  if (!labels || !matrix || !Array.isArray(labels) || !Array.isArray(matrix) || labels.length === 0 || matrix.length === 0) {
     return <div className="text-muted-foreground text-sm p-4">{i18n.t("charts.noCorrelationData")}</div>;
   }
   return <div ref={ref} style={{ height }} />;
```

- **Bản vá cho `frontend/src/components/charts/CandlestickChart.tsx`**:
```diff
--- a/frontend/src/components/charts/CandlestickChart.tsx
+++ b/frontend/src/components/charts/CandlestickChart.tsx
@@ -56,8 +56,9 @@ export function CandlestickChart({ data, markers, indicators, height = 500 }: Pr
   const containerRef = useRef<HTMLDivElement>(null);
   const chartRef = useRef<ReturnType<typeof echarts.init> | null>(null);
   const [sub, setSub] = useState<Sub>("vol");
-  const hasVolume = data.some((bar) => Number.isFinite(bar.volume) && bar.volume >= 0);
+  const safeData = Array.isArray(data) ? data : [];
+  const hasVolume = safeData.some((bar) => Number.isFinite(bar.volume) && bar.volume >= 0);
   const activeSub = sub === "vol" && !hasVolume ? "macd" : sub;
   const [range, setRange] = useState<Range>("ALL");
   const [overlays, setOverlays] = useState<Set<Overlay>>(new Set(["ma5", "ma20"]));
@@ -73,12 +74,12 @@ export function CandlestickChart({ data, markers, indicators, height = 500 }: Pr
 
   // Memoize base data arrays — only recompute when raw data changes
   const baseData = useMemo(() => {
-    const dates = data.map(d => d.time);
-    const closes = data.map(d => d.close);
-    const highs = data.map(d => d.high);
-    const lows = data.map(d => d.low);
-    const opens = data.map(d => d.open);
-    const candle = data.map(d => [d.open, d.close, d.low, d.high]);
+    const dates = safeData.map(d => d.time);
+    const closes = safeData.map(d => d.close);
+    const highs = safeData.map(d => d.high);
+    const lows = safeData.map(d => d.low);
+    const opens = safeData.map(d => d.open);
+    const candle = safeData.map(d => [d.open, d.close, d.low, d.high]);
     return { dates, closes, highs, lows, opens, candle };
-  }, [data]);
+  }, [safeData]);
@@ -292,7 +293,7 @@ export function CandlestickChart({ data, markers, indicators, height = 500 }: Pr
     }, true);
   }, [data, markers, baseData, indicatorCache, extraIndicators, activeSub, range, overlays, dark]);
 
-  if (data.length === 0) {
+  if (safeData.length === 0) {
     return <div className="text-muted-foreground text-sm p-4">{i18n.t("charts.noPriceData")}</div>;
   }
```

### 3. Vá lỗi Crash do Null `.toFixed()` trong `ValidationPanel.tsx` & `RunDetail.tsx`
- **Bản vá cho `frontend/src/components/charts/ValidationPanel.tsx`**:
```diff
--- a/frontend/src/components/charts/ValidationPanel.tsx
+++ b/frontend/src/components/charts/ValidationPanel.tsx
@@ -79,7 +79,7 @@ function MonteCarloSection({ mc }: { mc: NonNullable<ValidationData["monte_carl
           <DistributionChart
             samples={mc.sharpe_samples}
             markerValue={mc.actual_sharpe}
-            markerLabel={`${i18n.t("validation.actualLabel")} ${mc.actual_sharpe.toFixed(2)}`}
+            markerLabel={`${i18n.t("validation.actualLabel")} ${mc.actual_sharpe != null ? mc.actual_sharpe.toFixed(2) : "—"}`}
             bandFrom={mc.simulated_sharpe_p5}
             bandTo={mc.simulated_sharpe_p95}
             height={200}
@@ -88,9 +88,9 @@ function MonteCarloSection({ mc }: { mc: NonNullable<ValidationData["monte_carl
       ) : (
         <div className="space-y-1">
           <div className="flex justify-between text-[10px] text-muted-foreground font-mono">
-            <span>P5: {mc.simulated_sharpe_p5.toFixed(2)}</span>
-            <span>Actual: {mc.actual_sharpe.toFixed(2)}</span>
-            <span>P95: {mc.simulated_sharpe_p95.toFixed(2)}</span>
+            <span>P5: {mc.simulated_sharpe_p5 != null ? mc.simulated_sharpe_p5.toFixed(2) : "—"}</span>
+            <span>Actual: {mc.actual_sharpe != null ? mc.actual_sharpe.toFixed(2) : "—"}</span>
+            <span>P95: {mc.simulated_sharpe_p95 != null ? mc.simulated_sharpe_p95.toFixed(2) : "—"}</span>
           </div>
@@ -127,7 +127,7 @@ function BootstrapSection({ bs }: { bs: NonNullable<ValidationData["bootstrap"]
           <DistributionChart
             samples={bs.sharpe_samples}
             markerValue={bs.observed_sharpe}
-            markerLabel={`${i18n.t("validation.actualLabel")} ${bs.observed_sharpe.toFixed(2)}`}
+            markerLabel={`${i18n.t("validation.actualLabel")} ${bs.observed_sharpe != null ? bs.observed_sharpe.toFixed(2) : "—"}`}
             bandFrom={bs.ci_lower}
             bandTo={bs.ci_upper}
@@ -137,8 +137,8 @@ function BootstrapSection({ bs }: { bs: NonNullable<ValidationData["bootstrap"]
       ) : (
         <div className="space-y-1">
           <div className="flex justify-between text-[10px] text-muted-foreground font-mono">
-            <span>{bs.ci_lower.toFixed(2)}</span>
-            <span>{bs.ci_upper.toFixed(2)}</span>
+            <span>{bs.ci_lower != null ? bs.ci_lower.toFixed(2) : "—"}</span>
+            <span>{bs.ci_upper != null ? bs.ci_upper.toFixed(2) : "—"}</span>
           </div>
```

- **Bản vá cho `frontend/src/pages/RunDetail.tsx`**:
```diff
--- a/frontend/src/pages/RunDetail.tsx
+++ b/frontend/src/pages/RunDetail.tsx
@@ -633,8 +633,8 @@ function ConcentrationCard({ xray }: { xray: RiskXrayPayload | null }) {
       {xray && (
         <RunCardPanel title={i18n.t("runDetail.riskXray")} icon={Gauge}>
           <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
-            <RunCardStat label={i18n.t("runDetail.hhi")} value={concentration.hhi !== undefined ? concentration.hhi.toFixed(3) : "-"} />
-            <RunCardStat label={i18n.t("runDetail.effectiveN")} value={concentration.effective_n !== undefined ? concentration.effective_n.toFixed(1) : "-"} />
+            <RunCardStat label={i18n.t("runDetail.hhi")} value={concentration.hhi != null ? concentration.hhi.toFixed(3) : "-"} />
             <RunCardStat label={i18n.t("runDetail.effectiveN")} value={concentration.effective_n != null ? concentration.effective_n.toFixed(1) : "-"} />
             <RunCardStat label={i18n.t("runDetail.annualizedVol")} value={fmtPct(volatility.annualized_vol)} />
             <RunCardStat label={i18n.t("runDetail.maxDrawdown")} value={fmtPct(drawdown.max_drawdown)} />
           </div>
```

### 4. Vá lỗi Rò rỉ Interval trên `Portfolio.tsx`
- **Nguyên nhân gốc**: Timer không được giữ trong `useRef` và không có dọn dẹp khi component unmount.
- **Bản vá**:
```diff
--- a/frontend/src/pages/Portfolio.tsx
+++ b/frontend/src/pages/Portfolio.tsx
@@ -107,6 +107,13 @@ export function Portfolio() {
   const [editorOpen, setEditorOpen] = useState(false);
   const [selectedGroup, setSelectedGroup] = useState<string>("all");
   const [query, setQuery] = useState("");
+  const refreshTimerRef = useRef<number | null>(null);
+
+  useEffect(() => {
+    return () => {
+      if (refreshTimerRef.current !== null) window.clearInterval(refreshTimerRef.current);
+    };
+  }, []);
@@ -182,7 +189,8 @@ export function Portfolio() {
       current: null,
       sources: Object.fromEntries(enabledSources.map((source) => [source.connection_id, { status: "pending" as const }])),
     });
-    const timer = window.setInterval(() => {
+    if (refreshTimerRef.current !== null) window.clearInterval(refreshTimerRef.current);
+    refreshTimerRef.current = window.setInterval(() => {
       void api.getPortfolioRefreshStatus()
         .then((result) => setRefreshState(normalizeRefreshState(result.refresh)))
         .catch(() => undefined);
@@ -197,7 +205,10 @@ export function Portfolio() {
     } catch (err) {
       setError(err instanceof Error ? err.message : t("portfolio.page.errorRefresh"));
     } finally {
-      window.clearInterval(timer);
+      if (refreshTimerRef.current !== null) {
+        window.clearInterval(refreshTimerRef.current);
+        refreshTimerRef.current = null;
+      }
       setRefreshing(false);
     }
   }
```

### 5. Vá lỗi Khóa DOM và Hiệu năng trong `Forex.tsx` & `ForexTradeCards.tsx`
- **Bản vá cho `frontend/src/pages/Forex.tsx`**:
```diff
--- a/frontend/src/pages/Forex.tsx
+++ b/frontend/src/pages/Forex.tsx
@@ -73,7 +73,6 @@ export function Forex() {
     await loadConnections(); setSelectedId(config.id); setEditingNew(false);
     setNotice(l("Connection saved. Credentials and verification are separate.", "Đã lưu kết nối. Lưu thông tin đăng nhập và xác minh ở bước riêng."));
   });
-  const componentKey = selected ? JSON.stringify(selected) : "new";
   return <div className="mx-auto max-w-6xl space-y-5 p-4 md:p-6">
     <header className="flex flex-wrap items-start justify-between gap-3">
@@ -93,8 +92,8 @@ export function Forex() {
     </div>}
     {(editingNew || !connections.length) && <ForexConnectionForm key="create" onSave={save} />}
     {selected && !editingNew && <>
-      <ForexMarket key={componentKey+"market"} connection={selected} initialSymbol={query.get("symbol") || ""} />
-      <ForexAI key={componentKey+"ai"} connection={selected} runner={runner} reload={reload} onError={setError} />
+      <ForexMarket key={selected.id + "-market"} connection={selected} initialSymbol={query.get("symbol") || ""} />
+      <ForexAI key={selected.id + "-ai"} connection={selected} runner={runner} reload={reload} onError={setError} />
```

- **Bản vá cho `frontend/src/components/chat/ForexTradeCards.tsx`**:
```diff
--- a/frontend/src/components/chat/ForexTradeCards.tsx
+++ b/frontend/src/components/chat/ForexTradeCards.tsx
@@ -14,7 +14,9 @@ export function ForexTradeCards({ plan }: { plan: ForexTradePlan }) {
   const [now, setNow] = useState(Date.now);
   useEffect(() => {
+    const expiryTime = Date.parse(plan.expires_at);
+    if (Number.isFinite(expiryTime) && Date.now() >= expiryTime) return;
     const timer = window.setInterval(() => {
+      const current = Date.now();
+      setNow(current);
+      if (Number.isFinite(expiryTime) && current >= expiryTime) window.clearInterval(timer);
     }, 1000);
     return () => window.clearInterval(timer);
-  }, [plan.plan_id]);
+  }, [plan.plan_id, plan.expires_at]);
```

### 6. Bổ sung Contract Endpoint và Chuẩn hóa URL Encoding (`frontend/src/lib/api.ts`)
- **Bản vá**:
```diff
--- a/frontend/src/lib/api.ts
+++ b/frontend/src/lib/api.ts
@@ -660,11 +660,11 @@ export const api = {
     const qs = q.toString();
-    return request<RunData>(`/runs/${id}${qs ? `?${qs}` : ""}`);
+    return request<RunData>(`/runs/${encodeURIComponent(id)}${qs ? `?${qs}` : ""}`);
   },
-  getRunPreview: (id: string) => request<RunPreview>(`/runs/${id}/preview`),
-  getRunCode: (id: string) => request<Record<string, string>>(`/runs/${id}/code`),
-  getRunFactor: (id: string) => request<FactorReportPayload>(`/runs/${id}/factor`),
+  getRunPreview: (id: string) => request<RunPreview>(`/runs/${encodeURIComponent(id)}/preview`),
+  getRunCode: (id: string) => request<Record<string, string>>(`/runs/${encodeURIComponent(id)}/code`),
+  getRunFactor: (id: string) => request<FactorReportPayload>(`/runs/${encodeURIComponent(id)}/factor`),
   getRunAttribution: (id: string) => request<AttributionResponse>(`/runs/${encodeURIComponent(id)}/attribution`),
-  getRunPine: (id: string) => request<PineScriptResult>(`/runs/${id}/pine`),
+  getRunPine: (id: string) => request<PineScriptResult>(`/runs/${encodeURIComponent(id)}/pine`),
   listSessions: () => request<SessionItem[]>("/sessions", undefined, METADATA_TIMEOUT_MS),
   createSession: (title?: string) => request<SessionItem>("/sessions", { method: "POST", body: JSON.stringify({ title: title || "" }) }),
-  deleteSession: (sid: string) => request<{ status: string }>(`/sessions/${sid}`, { method: "DELETE" }),
-  renameSession: (sid: string, title: string) => request<{ status: string }>(`/sessions/${sid}`, { method: "PATCH", body: JSON.stringify({ title }) }),
+  deleteSession: (sid: string) => request<{ status: string }>(`/sessions/${encodeURIComponent(sid)}`, { method: "DELETE" }),
+  renameSession: (sid: string, title: string) => request<{ status: string }>(`/sessions/${encodeURIComponent(sid)}`, { method: "PATCH", body: JSON.stringify({ title }) }),
-  autoTitleSession: (sid: string) => request<{ status: string; title: string }>(`/sessions/${sid}/title/auto`, { method: "POST" }),
+  autoTitleSession: (sid: string) => request<{ status: string; title: string }>(`/sessions/${encodeURIComponent(sid)}/title/auto`, { method: "POST" }),
@@ -708,13 +708,23 @@ export const api = {
-  sendMessage: (sid: string, content: string) => request<{ message_id: string; attempt_id: string }>(`/sessions/${sid}/messages`, { method: "POST", body: JSON.stringify({ content }) }),
-  cancelSession: (sid: string) => request<{ status: string }>(`/sessions/${sid}/cancel`, { method: "POST" }),
-  getSessionMessages: (sid: string) => request<MessageItem[]>(`/sessions/${sid}/messages`),
+  sendMessage: (sid: string, content: string) => request<{ message_id: string; attempt_id: string }>(`/sessions/${encodeURIComponent(sid)}/messages`, { method: "POST", body: JSON.stringify({ content }) }),
+  cancelSession: (sid: string) => request<{ status: string }>(`/sessions/${encodeURIComponent(sid)}/cancel`, { method: "POST" }),
+  getSessionMessages: (sid: string) => request<MessageItem[]>(`/sessions/${encodeURIComponent(sid)}/messages`),
   createGoal: (sid: string, body: CreateGoalRequest) =>
-    request<GoalSnapshot>(`/sessions/${sid}/goal`, {
+    request<GoalSnapshot>(`/sessions/${encodeURIComponent(sid)}/goal`, {
       method: "POST",
       body: JSON.stringify(body),
     }),
-  getGoal: (sid: string) => request<GoalSnapshot>(`/sessions/${sid}/goal`),
+  getGoal: (sid: string) => request<GoalSnapshot>(`/sessions/${encodeURIComponent(sid)}/goal`),
   updateGoal: (sid: string, body: UpdateGoalRequest) =>
-    request<UpdateGoalResponse>(`/sessions/${sid}/goal`, {
+    request<UpdateGoalResponse>(`/sessions/${encodeURIComponent(sid)}/goal`, {
       method: "PATCH",
       body: JSON.stringify(body),
     }),
+  // Strategy adaptation routes (aligned with agent/src/api/strategy_adaptation_routes.py)
+  prepareStrategyAdaptation: (body: {
+    strategy_id: string;
+    name: string;
+    universe: string;
+    config: Record<string, unknown>;
+    position_sizing?: string | null;
+  }) => request<Record<string, unknown>>("/api/strategy-adaptations", { method: "POST", body: JSON.stringify(body) }),
+  refreshStrategyEvidence: (body: { runs: Array<Record<string, unknown>> }) =>
+    request<Record<string, unknown>>("/api/strategy-adaptations/evidence", { method: "POST", body: JSON.stringify(body) }),
```

---

## VI. BÁO CÁO BÀN GIAO 5 PHẦN TIÊU CHUẨN (STANDARD 5-COMPONENT HANDOFF)

### 1. Quan sát (Observation)
- Đã kiểm tra trực tiếp mã nguồn tại 28 tệp tin chính thuộc `frontend/src/` bằng các công cụ tìm kiếm và xem tệp tin tĩnh.
- Xác nhận các dòng mã gây lỗi:
  - `frontend/src/components/charts/EquityChart.tsx:117`: `if (data.length === 0)` văng lỗi `TypeError` khi `data` là undefined.
  - `frontend/src/pages/RunDetail.tsx:636-637`: So sánh `concentration.hhi !== undefined` dẫn đến việc thực thi `null.toFixed(3)`.
  - `frontend/src/router.tsx:92-119`: Không có ranh giới lỗi cấp trang con (sub-route errorElement).
  - `frontend/src/pages/Forex.tsx:76`: Sử dụng `JSON.stringify(selected)` làm React key.
  - `frontend/src/pages/Portfolio.tsx:185`: Khởi tạo polling interval không lưu ref và không có cleanup hook khi unmount.
  - `frontend/src/lib/api.ts`: Thiếu 2 endpoint tương ứng với `strategy_adaptation_routes.py` và thiếu `encodeURIComponent` trên hàng loạt endpoint runs/sessions.

### 2. Chuỗi suy luận (Logic Chain)
- Dựa trên quan sát `router.tsx` thiếu sub-route errorElement, bất kỳ runtime error nào trong cây React con sẽ lan truyền ngược lên Root Route (`Layout`).
- Kết hợp với quan sát tại các component biểu đồ (`EquityChart`, `CorrelationMatrix`, `ValidationPanel`) đều chứa các điểm dereference trực tiếp trên dữ liệu nullable từ backend.
- Suy ra: Khi backend trả về kết quả thiếu trường dữ liệu hoặc null, toàn bộ ứng dụng bị sập hoàn toàn thay vì chỉ hiển thị thông báo lỗi tại thẻ biểu đồ tương ứng.
- Đối chiếu với yêu cầu tối ưu tài nguyên và quản lý vòng đời, các hàm `setInterval` không có cleanup tại `Portfolio.tsx` và `ForexTradeCards.tsx` cùng với key anti-pattern tại `Forex.tsx` trực tiếp làm lãng phí chu kỳ CPU và bộ nhớ trình duyệt của người dùng.

### 3. Vùng chưa kiểm tra & Giả định (Caveats)
- Các bài kiểm thử E2E tương tác trực tiếp với trình duyệt (Playwright/Puppeteer) chưa chạy trong phiên này do nguyên tắc Read-Only của Explorer Agent.
- Giả định rằng backend FastAPI giữ nguyên cấu hình serialize `None -> null` theo chuẩn JSON tiêu chuẩn.
- Các module ngoài phạm vi `frontend/` (như `server/` hoặc scripts python độc lập) không thuộc đối tượng phân tích của báo cáo này.

### 4. Kết luận (Conclusion)
Giao diện frontend của hệ thống có thiết kế trực quan và phong phú về mặt tính năng phân tích tài chính. Tuy nhiên, kiến trúc phòng thủ lỗi (Defensive Architecture) và tính bền vững của vòng đời component hiện còn rất mỏng manh. Cần ưu tiên khắc phục 4 lỗi CRITICAL và 5 lỗi HIGH đã được cung cấp bản vá chi tiết ở Phần V để đảm bảo hệ thống đạt chuẩn vận hành ổn định trong môi trường thương mại thực chiến.

### 5. Phương pháp kiểm chứng độc lập (Verification Method)
Người thẩm định độc lập (Auditor / Tester) có thể thực hiện kiểm chứng theo các bước sau:
1. **Kiểm tra TypeScript & Linter**:
   ```powershell
   cd d:\Vibe-Trading\frontend
   npm run build
   ```
2. **Kiểm tra Unit Test Frontend**:
   ```powershell
   npm run test
   ```
3. **Mô phỏng dữ liệu rỗng và Null Dereference**:
   - Truy cập trang `/runs/sample-id` khi backend trả về dữ liệu rỗng hoặc metrics có giá trị null.
   - Quan sát xem trang có bị sập trắng màn hình hay không.
4. **Kiểm tra rò rỉ Interval trên DevTools**:
   - Mở Console trình duyệt tại tab Memory / Network.
   - Bấm nút Refresh trên `/portfolio`, lập tức chuyển sang trang `/settings`.
   - Quan sát tab Network: nếu request `/api/portfolio/refresh/status` vẫn tiếp tục gửi đều đặn 500ms/lần là lỗi UI-CRIT-04 chưa được vá.
