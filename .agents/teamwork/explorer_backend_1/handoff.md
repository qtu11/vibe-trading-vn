# BÁO CÁO KIỂM TOÁN CHUYÊN SÂU BACKEND VÀ HẠ TẦNG THỰC THI (M1)

Báo cáo kiểm toán kỹ thuật toàn diện cho hệ thống Backend của Vibe-Trading, bao gồm các tuyến API FastAPI, vòng đời thực thi AgentLoop và Swarm runtime, công cụ xuất báo cáo và biểu đồ reporting, hệ thống MCP tools và công cụ tích hợp.

---

## 1. OBSERVATION

Dưới đây là các quan sát thực tế được thu thập trực tiếp từ mã nguồn hệ thống thông qua việc kiểm tra cấu trúc mã, luồng điều khiển và phân tích tĩnh:

### 1.1. Lỗi bế tắc điều khiển Swarm Run khi Server khởi động lại (Uncancellable Stale Run Deadlock)
- **Tệp tin**: `agent/src/api/swarm_routes.py` (dòng 231-238)
- **Tệp tin**: `agent/src/swarm/runtime.py` (dòng 388-402)
- **Tệp tin**: `agent/src/swarm/store.py` (dòng 365-383)
- **Đoạn mã quan sát**:
  Trong `agent/src/swarm/runtime.py`:
  ```python
  def cancel_run(self, run_id: str) -> None:
      event = self._cancel_events.get(run_id)
      if event is None:
          raise KeyError(f"Run {run_id} is not running")
      event.set()
  ```
  Trong `agent/src/api/swarm_routes.py`:
  ```python
  @app.post("/swarm/runs/{run_id}/cancel")
  def cancel_swarm_run(run_id: str) -> dict[str, Any]:
      try:
          runtime.cancel_run(run_id)
      except KeyError as exc:
          raise HTTPException(status_code=404, detail=str(exc)) from exc
  ```
  Trong `agent/src/api/swarm_routes.py`:
  ```python
  @app.post("/swarm/runs/{run_id}/retry")
  def retry_swarm_run(run_id: str) -> dict[str, Any]:
      reconciled = store.reconcile_stale_run(run)
      if reconciled.status == RunStatus.running:
          raise HTTPException(
              status_code=409,
              detail="Cannot retry a running run. Cancel it first.",
          )
  ```

### 1.2. Tranh chấp tài nguyên không an toàn đa luồng trong Matplotlib Pyplot (Race Condition & Crash)
- **Tệp tin**: `agent/src/reporting/renderer.py` (dòng 16-19, dòng 280-302)
- **Đoạn mã quan sát**:
  ```python
  import matplotlib
  matplotlib.use("Agg")
  import matplotlib.pyplot as plt
  ...
  def create_price_chart(points: Sequence[dict[str, Any]], *, output_path: Path) -> Path | None:
      ...
      fig, ax = plt.subplots(figsize=(10.4, 2.8), dpi=155)
      ...
      fig.savefig(output_path, bbox_inches="tight", pad_inches=0.15)
      plt.close(fig)
  ```

### 1.3. Lỗi đổ vỡ tiến trình xuất báo cáo khi thiếu LibreOffice và rò rỉ ổ đĩa thư mục Staging
- **Tệp tin**: `agent/src/reporting/renderer.py` (dòng 476-497, 499-516)
- **Tệp tin**: `agent/src/reporting/service.py` (dòng 80-105)
- **Tệp tin**: `agent/src/api/reports_routes.py` (dòng 21, 30-42)
- **Đoạn mã quan sát**:
  Trong `agent/src/api/reports_routes.py`:
  ```python
  class ReportExportRequest(BaseModel):
      formats: list[str] = Field(default_factory=lambda: ["docx", "pdf"])
  ```
  Trong `agent/src/reporting/renderer.py`:
  ```python
  def convert_pdf(docx_path: Path, output_pdf_path: Path) -> Path:
      binary = _resolve_libreoffice_binary()
      if not binary:
          raise RuntimeError("LibreOffice binary not found; PDF export unavailable")
  ```
  Trong `agent/src/reporting/service.py`:
  ```python
  class ReportJobService:
      _JOBS_CACHE: dict[str, dict[str, Any]] = {}
      ...
      staging_dir = self.storage_root / "staging" / job_id
      staging_dir.mkdir(parents=True, exist_ok=True)
  ```
  Thư mục `staging_dir` sau khi hoàn thành tạo DOCX/PDF không có lệnh dọn dẹp (cleanup/unlink) để xóa các tệp tin tạm thời.

### 1.4. Nghẽn Event Loop do thao tác đọc ghi ổ đĩa đồng bộ trong hàm bất đồng bộ `list_runs`
- **Tệp tin**: `agent/src/api/runs_routes.py` (dòng 1037-1136)
- **Đoạn mã quan sát**:
  ```python
  @app.get("/runs", response_model=RunListResponse)
  async def list_runs(limit: int = 20):
      runs_dir = get_runs_dir()
      ...
      for child in sorted(runs_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
          ...
          state_path = child / "state.json"
          if state_path.exists():
              with open(state_path, "r", encoding="utf-8") as f:
                  data = json.load(f)
          ...
          req_path = child / "req.json"
          if req_path.exists():
              with open(req_path, "r", encoding="utf-8") as f:
                  req = json.load(f)
  ```

### 1.5. Tiêu tốn bộ nhớ RAM không kiểm soát khi tải Artifacts của Backtest lớn
- **Tệp tin**: `agent/src/api/runs_routes.py` (dòng 756-797, dòng 806-813)
- **Tệp tin**: `agent/src/api/models.py` (dòng 78-86)
- **Đoạn mã quan sát**:
  ```python
  def _build_response_from_run_dir(run_dir: Path, include_code: bool = True) -> RunResponse:
      ...
      artifacts_trades_csv = _load_csv_records(run_dir / "trades.csv")
      artifacts_positions_csv = _load_csv_records(run_dir / "positions.csv")
      artifacts_target_positions_csv = _load_csv_records(run_dir / "target_positions.csv")
  ```
  Hàm `_load_csv_records` đọc toàn bộ dòng dữ liệu từ tệp CSV vào mảng Python dictionaries mà không giới hạn số dòng.

### 1.6. Lỗ hổng Server-Side Request Forgery (SSRF) tiềm ẩn trong cấu hình QVeris
- **Tệp tin**: `agent/src/api/qveris_routes.py` (dòng 102-106, 149-177)
- **Tệp tin**: `agent/src/tools/qveris_tool.py` (dòng 228-245)
- **Đoạn mã quan sát**:
  Trong `agent/src/api/qveris_routes.py`:
  ```python
  def _validate_base_url(base_url: str) -> str:
      value = (base_url or DEFAULT_BASE_URL).strip().rstrip("/")
      if not value.startswith(("http://", "https://")):
          raise HTTPException(status_code=422, detail="base_url must be http(s)")
      return value
  ```
  Khi người dùng gọi `GET /qveris/status`, hệ thống khởi tạo `QVerisClient(cfg).get_usage()`, gửi yêu cầu HTTP tới `cfg.base_url` mà không qua kiểm tra địa chỉ mạng nội bộ.

### 1.7. Tuyến API nhận trực tiếp tham số Dictionary không qua kiểm thực Pydantic
- **Tệp tin**: `agent/src/api/research_routes.py` (dòng 111, 138, 142)
- **Tệp tin**: `agent/src/api/paper_trade_routes.py` (dòng 67-73)
- **Tệp tin**: `agent/src/api/swarm_routes.py` (dòng 92)
- **Đoạn mã quan sát**:
  ```python
  @app.post("/research/vietnam-dcf")
  async def vietnam_dcf(payload: dict = Body(...)):
  
  @app.post("/paper-trade/step")
  async def paper_step(body: dict = Body(...)):
  
  @app.post("/swarm/runs")
  def create_swarm_run(payload: dict):
  ```

### 1.8. Nguy cơ treo luồng không giới hạn thời gian trong thực thi công cụ song song tại AgentLoop
- **Tệp tin**: `agent/src/agent/tool_lifecycle.py` (dòng 516-525)
- **Đoạn mã quan sát**:
  ```python
  with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(runnable), 8)) as pool:
      futures = [pool.submit(copy_context().run, _run, item) for item in runnable]
      results = []
      for i, f in enumerate(futures):
          try:
              results.append(f.result())
          except Exception as exc:
              tc = runnable[i][0]
              results.append((tc, json.dumps({"status": "error", "error": str(exc)}), 0))
  ```
  Phương thức `f.result()` được gọi mà không truyền tham số `timeout`.

### 1.9. Thiếu ràng buộc định dạng Regex cho các tham số đường dẫn (Path Parameter Sanitization)
- **Tệp tin**: `agent/src/api/forex_routes.py` (dòng 73, 85, 97, 105, 109, 132, 270)
- **Tệp tin**: `agent/src/api/paper_trade_routes.py` (dòng 50, 56, 63)
- **Tệp tin**: `agent/src/api/portfolio_routes.py` (dòng 197)
- **Đoạn mã quan sát**:
  ```python
  @app.get("/trading/forex/sessions/{identifier}")
  @app.post("/trading/forex/experiments/{experiment_id}/retry")
  @app.get("/paper-trade/accounts/{account_id}/positions")
  ```
  Các biến `identifier`, `experiment_id`, `account_id` nhận kiểu `str` thuần túy, không có regex kiểm duyệt ký tự đặc biệt.

---

## 2. LOGIC CHAIN

Từ các bằng chứng quan sát trực tiếp ở trên, chuỗi lập luận kỹ thuật được thiết lập như sau:

### 2.1. Chuỗi lập luận về Lỗi bế tắc Swarm Run
1. *Căn cứ Mục 1.1*: `_cancel_events` là một cấu trúc dữ liệu `dict[str, threading.Event]` nằm hoàn toàn trong bộ nhớ RAM của tiến trình `SwarmRuntime`.
2. Khi server gặp sự cố hoặc được khởi động lại (restart/deploy), toàn bộ dữ liệu trong `_cancel_events` bị xóa sạch.
3. Tuy nhiên, trạng thái của run trên đĩa (`run.json`) vẫn giữ giá trị `RunStatus.running`.
4. Khi client hoặc người dùng gửi yêu cầu `POST /swarm/runs/{run_id}/cancel`, `runtime.cancel_run(run_id)` không tìm thấy `run_id` trong `_cancel_events`, dẫn đến ném ra lỗi `KeyError` và trả về mã lỗi HTTP 404 "Run is not running".
5. Khi người dùng cố gắng gọi `POST /swarm/runs/{run_id}/retry` để chạy lại, endpoint này kiểm tra `reconciled.status == RunStatus.running`. Vì chưa vượt ngưỡng stale threshold (ví dụ 300 giây) hoặc hàm reconcile chưa chuyển trạng thái, hệ thống trả về mã lỗi HTTP 409 "Cannot retry a running run. Cancel it first."
6. *Kết luận*: Người dùng rơi vào tình trạng bế tắc hoàn toàn (deadlock): không thể hủy tác vụ và cũng không thể thực thi lại tác vụ.

### 2.2. Chuỗi lập luận về Lỗi tranh chấp đa luồng trong Matplotlib Pyplot
1. *Căn cứ Mục 1.2*: Module `matplotlib.pyplot` là một State Machine toàn cục (Global State Machine).
2. Khi hai hoặc nhiều yêu cầu xuất báo cáo phân tích hoặc xuất biểu đồ cổ phiếu diễn ra đồng thời, các hàm này chạy trên các luồng worker trong threadpool.
3. Việc gọi `plt.subplots()` đồng thời trên nhiều luồng sẽ làm biến đổi đối tượng hình ảnh hiện hành (current figure/axes) của Matplotlib.
4. Điều này dẫn tới hiện tượng dữ liệu biểu đồ của mã cổ phiếu A bị vẽ đè lên biểu đồ của mã cổ phiếu B, hoặc Matplotlib ném ngoại lệ nghiêm trọng `ValueError: canvas is already being drawn`, làm sụp đổ hoàn toàn tiến trình xuất báo cáo của người dùng.

### 2.3. Chuỗi lập luận về Đổ vỡ tiến trình Reporting và Rò rỉ đĩa Staging
1. *Căn cứ Mục 1.3*: Lớp `ReportExportRequest` cấu hình mặc định xuất cả hai định dạng `["docx", "pdf"]`.
2. Khi hệ điều hành máy chủ (hoặc container) chưa cài đặt LibreOffice, hàm `convert_pdf` ném ngoại lệ `RuntimeError`.
3. Toàn bộ hàm xử lý `create_job` bị văng ngoại lệ và trả về mã lỗi HTTP 500 cho phía frontend, mặc dù tệp tin `.docx` đã được khởi tạo hoàn tất và chính xác.
4. Thư mục `staging_dir` chứa các ảnh và tệp tạm trong quá trình sinh tài liệu không có cơ chế dọn dẹp sau khi tác vụ kết thúc, dẫn đến việc tích tụ rác và làm cạn kiệt dung lượng ổ đĩa theo thời gian.

### 2.4. Chuỗi lập luận về Tắc nghẽn Event Loop trong `list_runs`
1. *Căn cứ Mục 1.4*: Tuyến `/runs` được định nghĩa là một hàm bất đồng bộ (`async def list_runs`).
2. Trong hàm này, tiến trình duyệt thư mục `runs_dir.iterdir()` và thực hiện mở, giải mã hàng loạt tệp tin JSON/CSV đồng bộ bằng `with open(...)`.
3. Khi số lượng phiên giao dịch tăng lên (hàng trăm thư mục runs), toàn bộ thời gian I/O đĩa diễn ra trực tiếp trên Main Event Loop của asyncio.
4. Hậu quả là tất cả các request API khác của người dùng gửi tới máy chủ trong thời điểm đó đều bị chặn (blocking), gây gia tăng đột biến độ trễ (latency spike) của toàn bộ hệ thống.

### 2.5. Chuỗi lập luận về Tiêu tốn bộ nhớ RAM trong nạp Artifacts
1. *Căn cứ Mục 1.5*: Khi truy xuất chi tiết một run thông qua `_build_response_from_run_dir`, toàn bộ các tệp `trades.csv`, `positions.csv`, `target_positions.csv` đều được nạp đầy đủ vào bộ nhớ.
2. Với các chiến lược giao dịch tần suất cao (HFT) hoặc backtest trên khoảng thời gian dài nhiều năm, số lượng bản ghi có thể lên tới 50.000 - 200.000 dòng.
3. Việc nạp toàn bộ dữ liệu này vào bộ nhớ và tuần tự hóa sang JSON sẽ tiêu tốn từ vài chục đến hàng trăm Megabytes RAM cho mỗi lượt truy vấn, dễ dẫn đến hiện tượng Out-Of-Memory (OOM) khi có nhiều truy vấn đồng thời.

### 2.6. Chuỗi lập luận về Lỗ hổng SSRF trong cấu hình QVeris
1. *Căn cứ Mục 1.6*: Hàm `_validate_base_url` chỉ xác thực tiền tố `http://` hoặc `https://`.
2. Khi quản trị viên hoặc kẻ tấn công có quyền cấu hình gửi yêu cầu cập nhật `base_url` trỏ về các địa chỉ nội bộ như `http://169.254.169.254/latest/meta-data/` (AWS Metadata) hoặc `http://127.0.0.1:8000/internal-admin`.
3. Khi hệ thống kiểm tra trạng thái tại `GET /qveris/status`, `QVerisClient` sẽ thực thi lệnh HTTP GET trực tiếp tới các địa chỉ này từ chính máy chủ Backend.
4. Đây là một lỗ hổng SSRF điển hình, có thể làm rò rỉ thông tin nhạy cảm của hạ tầng đám mây.

---

## 3. CAVEATS

1. **Phạm vi kiểm toán tĩnh**: Toàn bộ các phát hiện dựa trên phân tích mã nguồn và kiểm tra đường dẫn logic. Chưa tiến hành gửi request trực tiếp trên môi trường production đang hoạt động để tránh ảnh hưởng đến dữ liệu thực tế.
2. **Phiên bản LibreOffice**: Sự cố không xuất được PDF phụ thuộc vào sự tồn tại của LibreOffice binary trên hệ điều hành máy chủ. Nếu máy chủ đã có sẵn LibreOffice trong PATH, lỗi này sẽ không xảy ra, nhưng cấu hình mặc định thiếu fallback vẫn là một rủi ro kiến trúc lớn.
3. **Môi trường đơn tiến trình vs Đa tiến trình**: Các biến cờ in-memory (như `_cancel_events` trong Swarm hay `_JOBS_CACHE` trong Reporting) hiện chỉ hỗ trợ mô hình đơn tiến trình (single process). Nếu hệ thống chạy dưới mô hình Uvicorn nhiều workers (`--workers > 1`), việc điều khiển trạng thái in-memory sẽ không đồng bộ giữa các worker.

---

## 4. CONCLUSION

Hệ thống Backend của Vibe-Trading sở hữu cấu trúc mô-đun hóa phong phú, có khả năng tích hợp sâu rộng giữa LLM, các công cụ phân tích thị trường tài chính và các giao thức IM/Web. Tuy nhiên, hệ thống tồn tại các vấn đề cần khắc phục phân loại theo cấp độ nghiêm trọng như sau:

| Mã | Phân loại | Tệp tin & Dòng | Mức độ | Tóm tắt sự cố |
|---|---|---|---|---|
| **ISSUE-01** | Swarm Concurrency | `swarm_routes.py:231`, `runtime.py:388`, `store.py:365` | **HIGH** | Deadlock trạng thái Swarm Run khi server restart (không thể cancel hoặc retry). |
| **ISSUE-02** | Reporting Thread-Safety | `renderer.py:16-19, 280-302` | **HIGH** | Race condition và crash rendering biểu đồ do sử dụng Matplotlib Pyplot toàn cục. |
| **ISSUE-03** | Reporting Fault-Tolerance | `renderer.py:476-497`, `service.py:80-105` | **HIGH** | Crash toàn bộ export khi thiếu LibreOffice và rò rỉ dung lượng đĩa tại thư mục staging. |
| **ISSUE-04** | Async Performance | `runs_routes.py:1037-1136` | **MEDIUM** | Thao tác I/O đĩa đồng bộ gây nghẽn Main Event Loop trong endpoint `/runs`. |
| **ISSUE-05** | Memory Consumption | `runs_routes.py:756-797`, `models.py:78-86` | **MEDIUM** | Tải toàn bộ CSV lịch sử giao dịch vào RAM gây quá tải bộ nhớ khi dữ liệu lớn. |
| **ISSUE-06** | Security (SSRF) | `qveris_routes.py:102-106`, `qveris_tool.py:228` | **MEDIUM** | Nguy cơ Server-Side Request Forgery qua tham số `base_url` chưa được kiểm tra địa chỉ mạng riêng. |
| **ISSUE-07** | Input Validation | `research_routes.py:111`, `paper_trade_routes.py:67` | **MEDIUM** | Nhận raw `dict` không qua Pydantic schema validation ở tầng API gateway. |
| **ISSUE-08** | Tool Lifecycle Timeout | `tool_lifecycle.py:516-525` | **MEDIUM** | `ThreadPoolExecutor.result()` không có timeout, có thể treo vĩnh viễn worker khi tool bị kẹt. |
| **ISSUE-09** | Path Sanitization | `forex_routes.py:73`, `paper_trade_routes.py:50` | **LOW** | Thiếu ràng buộc định dạng Regex cho các tham số định danh đường dẫn (Path parameters). |
| **ISSUE-10** | Tool Registry Concurrency | `tools/__init__.py:12-40` | **LOW** | Thiếu khóa bảo vệ thread lock khi đăng ký dynamic tools trong môi trường đa luồng. |
| **ISSUE-11** | MCP Stdio Transport | `agent/mcp_server.py:80-140` | **LOW** | Xuất dữ liệu lớn qua Stdio pipe không chunking có thể làm tràn bộ đệm I/O trên Windows. |

### Đề xuất bản sửa lỗi chi tiết (Actionable Patches)

#### Bản sửa lỗi ISSUE-01: Khắc phục Deadlock Swarm Run khi Server Restart
Tại `agent/src/swarm/runtime.py`:
```python
def cancel_run(self, run_id: str) -> None:
    event = self._cancel_events.get(run_id)
    if event is not None:
        event.set()
        return

    # Fallback cho trường hợp server vừa restart: kiểm tra trực tiếp trong store
    loaded = self._store.load_run(run_id)
    if loaded is None:
        raise KeyError(f"Run {run_id} not found")
    if loaded.status == RunStatus.running:
        self._store.update_run_status(run_id, RunStatus.cancelled, error="Cancelled by user after server restart")
        return
    raise KeyError(f"Run {run_id} is not currently running (status: {loaded.status.value})")
```

#### Bản sửa lỗi ISSUE-02: Chuyển đổi Matplotlib sang Object-Oriented Figure API
Tại `agent/src/reporting/renderer.py`:
```python
# Thay thế việc sử dụng matplotlib.pyplot bằng matplotlib.figure.Figure độc lập
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg

def create_price_chart(points: Sequence[dict[str, Any]], *, output_path: Path) -> Path | None:
    ...
    fig = Figure(figsize=(10.4, 2.8), dpi=155)
    canvas = FigureCanvasAgg(fig)
    ax = fig.subplots()
    ...
    # Vẽ các thành phần trên ax bình thường
    ...
    fig.savefig(output_path, bbox_inches="tight", pad_inches=0.15)
    # Không cần gọi plt.close(fig) vì Figure không gắn vào global state machine
    return output_path
```

#### Bản sửa lỗi ISSUE-03: Cơ chế Partial Success khi thiếu LibreOffice và Dọn dẹp Staging
Tại `agent/src/reporting/service.py`:
```python
try:
    for fmt in job_spec.formats:
        if fmt == "docx":
            ...
        elif fmt == "pdf":
            try:
                convert_pdf(docx_path, pdf_path)
            except RuntimeError as exc:
                logger.warning("PDF export skipped due to missing LibreOffice: %s", exc)
                warnings.append("PDF export skipped: LibreOffice is not installed on the server.")
finally:
    # Tự động dọn dẹp thư mục staging
    if staging_dir.exists():
        import shutil
        shutil.rmtree(staging_dir, ignore_errors=True)
```

#### Bản sửa lỗi ISSUE-04: Đưa thao tác I/O Filesystem vào Threadpool
Tại `agent/src/api/runs_routes.py`:
```python
from starlette.concurrency import run_in_threadpool

def _sync_list_runs(runs_dir: Path, limit: int) -> RunListResponse:
    # Toàn bộ logic duyệt thư mục và đọc tệp tin đồng bộ được chuyển vào đây
    ...

@app.get("/runs", response_model=RunListResponse)
async def list_runs(limit: int = 20):
    runs_dir = get_runs_dir()
    return await run_in_threadpool(_sync_list_runs, runs_dir, limit)
```

#### Bản sửa lỗi ISSUE-06: Ngăn chặn SSRF cho QVeris Base URL
Tại `agent/src/api/qveris_routes.py`:
```python
from src.providers.endpoint_guard import is_non_public_address
import socket
from urllib.parse import urlsplit

def _validate_base_url(base_url: str) -> str:
    value = (base_url or DEFAULT_BASE_URL).strip().rstrip("/")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(status_code=422, detail="base_url must be a valid http(s) URL with hostname")
    
    hostname = parsed.hostname.lower()
    if hostname in {"localhost", "localhost.localdomain", "metadata.google.internal"}:
        raise HTTPException(status_code=422, detail="base_url cannot target local or metadata services")
    
    try:
        results = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
        for result in results:
            address = ipaddress.ip_address(result[4][0])
            if is_non_public_address(address, resolved=True):
                raise HTTPException(status_code=422, detail="base_url resolves to a private or loopback IP")
    except socket.gaierror as exc:
        raise HTTPException(status_code=422, detail="base_url hostname could not be resolved") from exc
        
    return value
```

---

## 5. VERIFICATION METHOD

Để kiểm chứng độc lập các phát hiện và hiệu quả của các bản sửa lỗi đề xuất, tiến hành thực hiện các bước sau:

### 5.1. Kiểm chứng ISSUE-01 (Swarm Uncancellable Stale Run)
1. Khởi tạo một swarm run giả lập có trạng thái `running` trực tiếp trong tệp `run.json` tại thư mục storage.
2. Khởi động lại API server để xóa sạch `_cancel_events` trong RAM.
3. Thực thi lệnh:
   ```powershell
   Invoke-RestMethod -Uri "http://localhost:8000/swarm/runs/{test_run_id}/cancel" -Method Post -Headers @{"Authorization"="Bearer test_key"}
   ```
4. *Điều kiện phủ định*: Nếu endpoint trả về 404 "Run is not running", lỗi được tái hiện thành công. Sau khi áp dụng bản vá, endpoint trả về 200 OK và trạng thái trong `run.json` được cập nhật thành `cancelled`.

### 5.2. Kiểm chứng ISSUE-02 (Matplotlib Pyplot Race Condition)
1. Viết một kịch bản kiểm thử đa luồng gọi hàm `create_price_chart` đồng thời với 10 threads trong `concurrent.futures.ThreadPoolExecutor`.
2. Chạy kịch bản kiểm thử:
   ```powershell
   python -m pytest tests/test_reporting_concurrency.py
   ```
3. *Điều kiện phủ định*: Nếu Matplotlib phát sinh ngoại lệ `ValueError` hoặc đồ thị bị xáo trộn dữ liệu giữa các mã cổ phiếu, lỗi được xác nhận. Với Figure API độc lập, toàn bộ 10 threads hoàn thành mà không có lỗi.

### 5.3. Kiểm chứng ISSUE-04 (Event Loop Latency Spike)
1. Tạo 50 thư mục run mẫu trong thư mục dữ liệu runs.
2. Đo thời gian phản hồi của endpoint `/health` đồng thời trong khi gửi yêu cầu tới `/runs`:
   ```powershell
   Measure-Command { Invoke-RestMethod -Uri "http://localhost:8000/runs?limit=50" -Headers @{"Authorization"="Bearer test_key"} }
   ```
3. *Điều kiện phủ định*: Sau khi chuyển logic sang `run_in_threadpool`, endpoint `/health` phản hồi tức thì dưới 5ms mà không bị nghẽn bởi I/O của `/runs`.

### 5.4. Kiểm chứng bộ kiểm thử hiện tại của hệ thống
Thực thi toàn bộ bộ kiểm thử tự động của dự án liên quan đến backend:
```powershell
pytest agent/tests/ -v -k "api or swarm or reporting or tools"
```
Đảm bảo tất cả các ca kiểm thử hồi quy tiếp tục vượt qua thành công sau khi áp dụng các khuyến nghị trên.
