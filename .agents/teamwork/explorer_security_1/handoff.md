# BÁO CÁO BÀN GIAO KIỂM TOÁN BẢO MẬT, LỖ HỔNG LOGIC VÀ ĐỘ CHÍNH XÁC SỐ HỌC (HANDOFF REPORT)

- **Agent thực hiện**: `explorer_security_1` (Vai trò: Chuyên viên Kiểm toán Bảo mật, Lỗ hổng Logic & Độ chính xác Số học)
- **Thư mục làm việc**: `D:\Vibe-Trading\.agents\teamwork\explorer_security_1`
- **Mã định danh tác vụ**: Milestone M3 - Security, Logic & Numeric Precision Audit
- **Ngày hoàn thành**: 2026-11-06
- **Đối tượng nhận báo cáo**: Orchestrator / Parent Agent (`b19f31d6-a4a9-4d1a-9241-abc25f754066`) và ban kỹ thuật dự án Vibe-Trading.

---

## 1. OBSERVATION (QUAN SÁT THỰC NGHIỆM CHI TIẾT)

Qua quá trình rà soát toàn diện mã nguồn backend FastAPI, AgentLoop, Swarm, MCP tools, engine báo cáo tài chính và frontend React/Next.js, ghi nhận 14 phát hiện cụ thể tại các đường dẫn và dòng mã nguồn sau:

### Trụ cột 1: Xử lý mã HTTP & Kiểm thực dữ liệu đầu vào (Input Validation)

#### Quan sát SEC-01 (Mức độ: High)
- **Vị trí**: `agent/src/api/settings_routes.py`, dòng 753-764 (`update_llm_settings`).
- **Mã nguồn thực tế**:
  ```python
  753:         base_url = (
  754:             payload.base_url if payload.base_url is not None else provider.default_base_url
  755:         ).strip()
  756:         if provider.auth_type == "oauth":
  757:             try:
  758:                 from src.providers.openai_codex import validate_codex_base_url
  759: 
  760:                 base_url = validate_codex_base_url(base_url)
  761:             except ValueError as exc:
  762:                 raise HTTPException(
  763:                     status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
  764:                 ) from exc
  765:         updates: Dict[str, str] = {
  766:             "LANGCHAIN_PROVIDER": provider.name,
  767:             "LANGCHAIN_MODEL_NAME": model_name,
  768:             provider.base_url_env: base_url,
  ```
- **Hiện tượng quan sát**: Hàm chỉ kiểm tra `validate_codex_base_url` đối với provider dạng `oauth`. Các provider khác (như OpenAI, Anthropic, DeepSeek, Ollama, custom providers) cho phép người dùng truyền bất kỳ `base_url` nào (kể cả địa chỉ IP mạng nội bộ như `http://192.168.1.1`, `http://10.0.0.1` hoặc cloud metadata service `http://169.254.169.254/latest/meta-data/`). Giá trị này sau đó được lưu trực tiếp vào cấu hình `.env` thông qua `_write_settings_env_updates`.

#### Quan sát SEC-02 (Mức độ: Medium)
- **Vị trí**: `agent/src/api/swarm_routes.py`, dòng 91-108 (`create_swarm_run`).
- **Mã nguồn thực tế**:
  ```python
  91:     @app.post("/swarm/runs", dependencies=[Depends(require_auth)])
  92:     async def create_swarm_run(payload: dict, http_request: Request):
  93:         """Start a swarm run: body must include preset_name and user_vars."""
  94:         runtime = _get_swarm_runtime()
  95:         preset_name = payload.get("preset_name", "")
  96:         user_vars = payload.get("user_vars", {})
  97:         try:
  98:             run = runtime.start_run(
  99:                 preset_name,
  100:                 user_vars,
  101:                 include_shell_tools=_host_shell_tools_enabled_for_request(http_request),
  102:                 **({"max_llm_calls": payload["max_llm_calls"]} if payload.get("max_llm_calls") is not None else {}),
  103:             )
  ```
- **Hiện tượng quan sát**: Endpoint nhận tham số `payload: dict` hoàn toàn phi kiểu (untyped), không thông qua Pydantic schema validation. Thuộc tính `max_llm_calls` không được ràng buộc kiểu số nguyên hay giới hạn trên/dưới (`ge=1`, `le=500`), có thể nhận giá trị âm, chuỗi ký tự hoặc giá trị khổng lồ gây kiệt quệ tài nguyên.

#### Quan sát SEC-03 (Mức độ: Low)
- **Vị trí**: `agent/src/api/channels_routes.py`, dòng 18-23, 107-115 (`channels_pairing_command`).
- **Mã nguồn thực tế**:
  ```python
  18: class ChannelPairingCommandRequest(BaseModel):
  19:     """Pairing command payload for IM channel sender pairing."""
  20: 
  21:     channel: str
  22:     command: str
  ...
  107:     @app.post("/channels/pairing/command", dependencies=[Depends(require_auth)])
  108:     async def channels_pairing_command(payload: ChannelPairingCommandRequest):
  113:             "channel": payload.channel,
  114:             "reply": handle_pairing_command(payload.channel, payload.command),
  ```
- **Hiện tượng quan sát**: Trường `channel` và `command` là `str` tự do không có giới hạn độ dài (`max_length`) hay regex whitelist định danh kênh hợp lệ (`telegram`, `discord`, `slack`).

#### Quan sát SEC-04 (Mức độ: Medium)
- **Vị trí**: `frontend/src/lib/api.ts`, dòng 612-618, 621-622, 625, 648-650, 652-660, 1020.
- **Mã nguồn thực tế**:
  ```typescript
  612: return request<RunData>(`/runs/${id}${qs ? `?${qs}` : ""}`);
  614: getRunPreview: (id: string) => request<RunPreview>(`/runs/${id}/preview`),
  615: getRunCode: (id: string) => request<Record<string, string>>(`/runs/${id}/code`),
  616: getRunFactor: (id: string) => request<FactorReportPayload>(`/runs/${id}/factor`),
  618: getRunPine: (id: string) => request<PineScriptResult>(`/runs/${id}/pine`),
  621: deleteSession: (sid: string) => request<{ status: string }>(`/sessions/${sid}`, { method: "DELETE" }),
  622: renameSession: (sid: string, title: string) => request<{ status: string }>(`/sessions/${sid}`, { method: "PATCH", body: JSON.stringify({ title }) }),
  625: autoTitleSession: (sid: string) => request<{ status: string; title: string }>(`/sessions/${sid}/title/auto`, { method: "POST" }),
  648: sendMessage: (sid: string, content: string) => request<{ message_id: string; attempt_id: string }>(`/sessions/${sid}/messages`, { method: "POST", body: JSON.stringify({ content }) }),
  649: cancelSession: (sid: string) => request<{ status: string }>(`/sessions/${sid}/cancel`, { method: "POST" }),
  ```
- **Hiện tượng quan sát**: Trái ngược với dòng 617 (`/runs/${encodeURIComponent(id)}/attribution`) và dòng 632 (`/scheduled-runs/${encodeURIComponent(id)}`), các endpoint trên ghép chuỗi trực tiếp `${id}` và `${sid}` mà không qua `encodeURIComponent`. Nếu định danh chứa ký tự đặc biệt như `/`, `#`, `?`, URL bị bẻ gãy hoặc lệch định tuyến (Path Splitting).

---

### Trụ cột 2: Độ chính xác số học, đơn vị tiền tệ VND & Phép toán tài chính

#### Quan sát NUM-01 (Mức độ: High)
- **Vị trí**: `agent/src/portfolio/fx.py`, dòng 30-36, 40-60 và `agent/src/portfolio/compatibility.py`, dòng 238-243.
- **Mã nguồn thực tế**:
  ```python
  30: def build_rates(usd_cny: Decimal, usd_hkd: Decimal) -> dict[str, Decimal]:
  31:     """Build the production rates map, anchored on one USD."""
  32:     return {
  33:         "USD": Decimal("1"),
  34:         "CNY": _validated_rate("USD/CNY", usd_cny),
  35:         "HKD": _validated_rate("USD/HKD", usd_hkd),
  36:     }
  ...
  238:     if rates is not None:
  239:         missing = sorted(code for code in currencies if rates.get(code) is None)
  240:         if missing:
  241:             raise PortfolioContractError(
  242:                 "portfolio FX conversion is not available for: " + ", ".join(missing)
  243:             )
  ```
- **Hiện tượng quan sát**: Bảng tỷ giá của `PortfolioService` chỉ hỗ trợ cố định USD, CNY, và HKD. Khi hệ thống tích hợp các tài khoản hoặc vị thế chứng khoán Việt Nam sử dụng tiền tệ `VND` (hoặc `EUR`, `KRW`), hàm `ensure_supported_currencies` bắt buộc kiểm tra `missing` và ném ra ngoại lệ `PortfolioContractError: portfolio FX conversion is not available for: VND`. Endpoint `POST /api/portfolio/refresh` lập tức chuyển lỗi này thành HTTP 503, khiến toàn bộ tính năng tổng hợp danh mục bị tê liệt.

#### Quan sát NUM-02 (Mức độ: Medium)
- **Vị trí**: `frontend/src/lib/formatters.ts`, dòng 54-67 (`formatMetricVal`).
- **Mã nguồn thực tế**:
  ```typescript
  54: export function formatMetricVal(k: string, v: number): string {
  55:   if (PCT_KEYS.includes(k)) {
  56:     const sign = v > 0 ? "+" : "";
  57:     return `${sign}${(v * 100).toFixed(2)}%`;
  58:   }
  59:   if (RATIO_KEYS.includes(k)) {
  60:     const sign = v > 0 ? "+" : "";
  61:     return `${sign}${v.toFixed(2)}`;
  62:   }
  63:   if (INT_KEYS.includes(k)) return String(Math.round(v));
  64:   if (k === "final_value") return v.toLocaleString(undefined, { maximumFractionDigits: 0 });
  65:   if (k === "avg_holding_days") return v.toFixed(1);
  66:   return v.toFixed(4);
  67: }
  ```
- **Hiện tượng quan sát**:
  1. Không kiểm tra tính hợp lệ của số học (`Number.isFinite(v)`). Nếu `v` là `NaN` hoặc `Infinity` hoặc `undefined`, hàm trả về `"NaN%"` hoặc ném `TypeError`.
  2. Nhân trực tiếp `v * 100` trên số thực chuẩn IEEE 754 gây ra hiện tượng trôi số học (floating-point precision error), ví dụ `0.07 * 100` ra `7.000000000000001`. Cơ chế làm tròn `toFixed(2)` của JavaScript áp dụng quy tắc làm tròn nửa chẵn không đồng nhất cho các số nhị phân hữu hạn (như `1.005.toFixed(2)` cho kết quả `"1.00"` thay vì `"1.01"`).
  3. Giá trị `final_value` hiển thị định dạng số không có ký hiệu tiền tệ. Khi danh mục thuộc thị trường Việt Nam (hàng trăm triệu hoặc tỷ VND) đặt cạnh USD/CNY, người dùng không thể phân biệt được mệnh giá hiển thị.

#### Quan sát NUM-03 (Mức độ: Medium)
- **Vị trí**: `agent/src/tools/vietnam_research_tool.py`, dòng 133-143.
- **Mã nguồn thực tế**:
  ```python
  133:         with localcontext() as ctx:
  134:             ctx.prec = 320 if unit == "VND" else 28
  135:             computed = compute(*values) if reason is None else None
  136:         metrics[name] = {"value": _display(computed), "unit": unit, "inputs": names, "reason": reason}
  137: 
  138:     metric("net_margin", ["income.net_income", "income.revenue"], lambda n, r: n / r, positive=(1,))
  141:     metric("free_cash_flow", ["cashflow.cfo", "cashflow.capex"], lambda c, k: c - k, "VND", nonnegative=(1,))
  142:     metric("balance_residual", ["balance.total_assets", "balance.total_liabilities", "balance.total_equity"],
  143:            lambda a, l, e: a - l - e, "VND")
  ```
- **Hiện tượng quan sát**: Các báo cáo tài chính Việt Nam từ các bên cung cấp (như Vietstock, CafeF, FiinGroup) thường công bố số liệu theo đơn vị nghìn đồng (thousand VND), triệu đồng (million VND) hoặc tỷ đồng (billion VND). Mã nguồn tính toán giả định tất cả đầu vào đã là đơn vị đồng tuyệt đối (`unit == "VND"`). Nếu luồng agent trích xuất từ 2 nguồn có đơn vị khác nhau (ví dụ CFO tính bằng triệu VND nhưng Capex tính bằng nghìn VND), phép trừ `c - k` sẽ sai lệch hàng nghìn lần mà không có bước chuẩn hóa tỷ lệ (scale factor normalization).

---

### Trụ cột 3: Lưu trữ & Quản lý tệp tin rò rỉ (Storage & File Management)

#### Quan sát TRV-01 (Mức độ: Medium)
- **Vị trí**: `agent/src/reporting/service.py`, dòng 81-93 và `agent/src/tools/report_artifacts.py`, dòng 61-66.
- **Mã nguồn thực tế**:
  ```python
  # agent/src/reporting/service.py
  81:             render_dir = self.storage_root / "staging"
  82:             render_dir.mkdir(parents=True, exist_ok=True)
  83:             result = export_report(report=report, root=render_dir, formats=fmt_list)
  84: 
  85:             artifacts = []
  86:             for fmt in fmt_list:
  87:                 file_path_str = result.get(fmt)
  88:                 if not file_path_str:
  89:                     continue
  90:                 file_path = Path(file_path_str)
  91:                 artifact_meta = publish_report_artifact(file_path, format=fmt)
  92:                 artifacts.append(artifact_meta)
  ```
  ```python
  # agent/src/tools/report_artifacts.py
  61:     report_id = uuid.uuid4().hex
  62:     directory = reports_root() / report_id
  63:     directory.mkdir(parents=True, exist_ok=True)
  64:     destination = directory / path.name
  65:     shutil.copyfile(path, destination)
  ```
- **Hiện tượng quan sát**: `export_report` sinh tệp `.docx` và `.pdf` vào thư mục `staging`. Sau đó `publish_report_artifact` thực hiện sao chép tệp sang `reports_root() / <report_id> / ...` bằng lệnh `shutil.copyfile`. Tệp gốc tại `staging` không bao giờ được xóa sau khi copy. Theo thời gian, toàn bộ các bản render trung gian bị bỏ quên và tích tụ vĩnh viễn trên ổ cứng.

#### Quan sát TRV-02 (Mức độ: Low)
- **Vị trí**: `agent/vibe_report_engine/api.py`, dòng 17, 30-37.
- **Mã nguồn thực tế**:
  ```python
  17: OUTPUT_ROOT = Path(os.environ.get("VIBE_REPORT_OUTPUT_DIR", str(Path(__file__).parent / "outputs")))
  ...
  30: def render(report: ResearchReport, fmt: Literal["docx", "pdf"]):
  31:     result = export_report(report, OUTPUT_ROOT, formats=(fmt,))
  32:     filename = Path(result[fmt]).name
  ```
- **Hiện tượng quan sát**: Endpoint kết xuất tài liệu độc lập lưu trực tiếp tệp kết quả vào `OUTPUT_ROOT` mà không có cơ chế dọn dẹp theo thời gian hết hạn (retention pruning) hoặc giới hạn dung lượng tối đa (disk quota).

---

### Trụ cột 4: Rò rỉ tài nguyên, luồng dữ liệu & Điều kiện chạy đua (Race Conditions)

#### Quan sát RES-01 (Mức độ: High)
- **Vị trí**: `agent/src/portfolio/store.py`, dòng 49-55, 87, 116, 136, 167 và `agent/src/portfolio/imports.py`, dòng 38-44, 55, 106, 117.
- **Mã nguồn thực tế**:
  ```python
  # agent/src/portfolio/store.py
  49:     def _connect(self) -> sqlite3.Connection:
  50:         connection = sqlite3.connect(self.path)
  51:         connection.row_factory = sqlite3.Row
  52:         return connection
  53: 
  54:     def _init_schema(self) -> None:
  55:         with self._connect() as db:
  ...
  87:         with self._connect() as db:
  116:        with self._connect() as db:
  136:        with self._connect() as db:
  ```
- **Hiện tượng quan sát**: Trong Python thư viện chuẩn `sqlite3`, cú pháp `with sqlite3.connect(...) as conn:` **chỉ** quản lý context cho Database Transaction (tự động `commit` khi thành công, `rollback` khi có ngoại lệ), **hoàn toàn không đóng kết nối** (`conn.close()` không được gọi). Mỗi lần gọi `self._connect()` sinh ra một kết nối mới và bỏ ngỏ file handle trên hệ điều hành cho tới khi garbage collector thu gom. Khi có nhiều request song song truy vấn danh mục, điều này dẫn đến cạn kiệt file descriptor và gặp lỗi `sqlite3.OperationalError: database is locked`.

#### Quan sát RES-02 (Mức độ: Critical)
- **Vị trí**: `agent/src/api/live_routes.py`, dòng 1396-1422 (`start_runner_endpoint`) và 1446-1454 (`stop_runner_endpoint`).
- **Mã nguồn thực tế**:
  ```python
  1396:         h = _host()
  1397:         tasks = h._runner_tasks
  1398: 
  1399:         existing = tasks.get(broker)
  1400:         if existing is not None and not existing.done():
  1401:             return {"broker": broker, "started": False, "already_running": True}
  ...
  1412:             runner = h._build_live_runner(broker)
  ...
  1418:         task = asyncio.ensure_future(h._drive_runner(runner))
  1419:         tasks[broker] = task
  1420:         task.add_done_callback(
  1421:             lambda t, b=broker: tasks.pop(b, None) if tasks.get(b) is t else None
  1422:         )
  ```
- **Hiện tượng quan sát**: Endpoint kích hoạt bot giao dịch tiền thật (`live runner`) không có khóa đồng bộ hóa (`asyncio.Lock`). Khi có hai request gửi đồng thời tới `POST /live/runner/start` với cùng một broker:
  1. Cả hai luồng kiểm tra `existing = tasks.get(broker)` và đều thấy `None`.
  2. Cả hai luồng cùng khởi tạo runner và cùng gọi `asyncio.ensure_future(h._drive_runner(runner))`.
  3. Hai tác vụ runner chạy ngầm cùng gửi lệnh giao dịch thực tế vào cùng một tài khoản broker (Double Execution / Real-Money Exposure).
  4. Biến `tasks[broker]` bị ghi đè bởi task thứ hai, khiến task thứ nhất trở thành tác vụ mồ côi (orphaned task) không thể kiểm soát hay dừng lại qua lệnh `POST /live/runner/stop`.

#### Quan sát RES-03 (Mức độ: Medium)
- **Vị trí**: `agent/src/reporting/service.py`, dòng 31, 77 (`ReportJobService`).
- **Mã nguồn thực tế**:
  ```python
  28: class ReportJobService:
  29:     """Manages document export jobs and registers private artifacts."""
  30: 
  31:     _JOBS_CACHE: dict[str, dict[str, Any]] = {}
  ...
  77:         self._JOBS_CACHE[job_id] = job_record
  ```
- **Hiện tượng quan sát**: `_JOBS_CACHE` là một biến từ điển cấp lớp (class-level dict) lưu trữ toàn bộ lịch sử các tác vụ xuất báo cáo trực tiếp trong RAM. Bộ nhớ đệm này không có giới hạn số lượng mục tối đa (capacity limit) và không có cơ chế hết hạn (TTL eviction). Trên môi trường production chạy liên tục, dung lượng RAM sử dụng sẽ tăng dần theo thời gian.

#### Quan sát RES-04 (Mức độ: Medium)
- **Vị trí**: `agent/src/session/events.py`, dòng 79-80, 101-106, 289-293 (`EventBus`).
- **Mã nguồn thực tế**:
  ```python
  79:         self._buffers: Dict[str, List[SSEEvent]] = {}
  80:         self._subscribers: Dict[str, List[asyncio.Queue]] = {}
  ...
  101:         with self._lock:
  102:             if session_id not in self._buffers:
  103:                 self._buffers[session_id] = []
  104:             buffer = self._buffers[session_id]
  105:             buffer.append(event)
  106:             if len(buffer) > self.max_buffer_size:
  107:                 self._buffers[session_id] = buffer[-self.max_buffer_size:]
  ...
  289:         finally:
  290:             with self._lock:
  291:                 subs = self._subscribers.get(session_id, [])
  292:                 if queue in subs:
  293:                     subs.remove(queue)
  ```
- **Hiện tượng quan sát**:
  1. Trong khối `finally` của hàm `subscribe`, khi hàng đợi client bị hủy đăng ký, nếu danh sách `subs` rỗng (`len(subs) == 0`), khóa `session_id` vẫn tồn tại vĩnh viễn trong `self._subscribers` với giá trị là mảng rỗng `[]`.
  2. Bộ đệm sự kiện `self._buffers[session_id]` lưu tối đa 500 sự kiện cho mỗi session. Nếu người dùng không gọi tường minh endpoint xóa phiên (`DELETE /api/sessions/{id}` - nơi gọi `event_bus.clear(session_id)`), các session cũ sẽ lưu giữ hàng nghìn sự kiện trong RAM vĩnh viễn.

#### Quan sát RES-05 (Mức độ: Medium)
- **Vị trí**: `agent/src/channels/websocket.py`, dòng 300, 1094-1110 (`WebSocketChannel`).
- **Mã nguồn thực tế**:
  ```python
  300:         self._stream_text_buffers: dict[tuple[str, str], list[str]] = {}
  ...
  1094:         stream_key = (chat_id, str(meta.get("_stream_id") or ""))
  1095:         if meta.get("_stream_end"):
  1096:             body: dict[str, Any] = {"event": "stream_end", "chat_id": chat_id}
  1097:             buffered = self._stream_text_buffers.pop(stream_key, [])
  ...
  1110:             self._stream_text_buffers.setdefault(stream_key, []).append(delta)
  ```
- **Hiện tượng quan sát**: Dữ liệu delta streaming được tích lũy vào `self._stream_text_buffers`. Bộ đệm chỉ được giải phóng khi sự kiện mang cờ `_stream_end` được gửi đến. Nếu kết nối WebSocket bị đứt giữa chừng, client đóng trình duyệt, hoặc model gặp lỗi sập trước khi phát `_stream_end`, hàm dọn dẹp `_cleanup_connection` không hề chạm tới `self._stream_text_buffers`. Các khối chuỗi văn bản bị kẹt lại trong bộ nhớ không có TTL dọn dẹp.

---

## 2. LOGIC CHAIN (CHUỖI LÝ LUẬN VÀ SUY DIỄN NGUYÊN NHÂN - HẬU QUẢ)

```
[QUAN SÁT THỰC NGHIỆM]                   [CƠ CHẾ LỖI TIỀM ẨN]                    [HẬU QUẢ HỆ THỐNG]
SEC-01: Thiếu validate base_url      ──> SSRF tới địa chỉ nội bộ             ──> Rò rỉ metadata cloud/nội bộ
SEC-02: Payload swarm untyped        ──> max_llm_calls không chặn biên       ──> DoS / Vòng lặp vô hạn LLM
SEC-04: Ghép chuỗi URL frontend      ──> Ký tự đặc biệt không encode         ──> Bẻ gãy routing / Path injection
NUM-01: rates chỉ có USD/CNY/HKD     ──> Thiếu VND trong Portfolio fx        ──> Sập 503 khi refresh danh mục VN
NUM-02: Format float JS thô          ──> v*100 trôi số, NaN không bắt        ──> UI hiển thị NaN%, lỗi tỷ lệ
NUM-03: VN metric không scale unit   ──> CFO (triệu) trừ Capex (nghìn)       ──> Sai số tài chính hàng nghìn lần
TRV-01: Staging file không xóa       ──> shutil.copyfile bỏ quên file gốc    ──> Tràn dung lượng lưu trữ đĩa
RES-01: with sqlite3 không close     ──> File descriptor không giải phóng    ──> Database locked, cạn socket OS
RES-02: live runner start thiếu Lock ──> Race condition khi 2 request cùng lúc ──> Nhân đôi lệnh tiền thật (CRITICAL)
RES-03: Cache jobs trong biến class  ──> Không có LRU / TTL eviction         ──> Rò rỉ RAM theo thời gian
RES-04: SSE Buffer không tự hủy      ──> Lưu 500 event/session vô thời hạn   ──> Phình to bộ nhớ EventBus
RES-05: Stream buffer websocket treo ──> Mất kết nối bỏ sót buffer delta     ──> Rò rỉ RAM trên kết nối lỗi
```

1. **Chuỗi suy luận cho RES-02 (Live Runner Race Condition - Critical)**:
   - Điểm vào: Client gọi `POST /live/runner/start`.
   - Tiến trình: FastAPI chạy trên môi trường bất đồng bộ `asyncio`. Khi 2 request tới gần như đồng thời (ví dụ do người dùng click đúp trên UI hoặc bot tự động kích hoạt song song), cả hai luồng xử lý đều đọc `tasks.get(broker)` tại dòng 1399 trước khi bất kỳ luồng nào kịp gán `tasks[broker] = task` tại dòng 1419.
   - Hệ quả: Hai luồng đều vượt qua điều kiện kiểm tra `existing is not None`, đều gọi `_build_live_runner(broker)` và kích hoạt hai coroutine `_drive_runner(runner)` riêng biệt. Cả hai instance cùng theo dõi dữ liệu thị trường và cùng đẩy lệnh mua/bán tiền thật vào sàn giao dịch, gây thiệt hại tài chính trực tiếp và nghiêm trọng.
   - Kết luận: Bắt buộc phải có khóa tương hỗ `asyncio.Lock` bao bọc toàn bộ chu trình kiểm tra và đăng ký runner theo broker.

2. **Chuỗi suy luận cho RES-01 (SQLite Handle Leak - High)**:
   - Điểm vào: Các hàm `create`, `list_valid`, `append`, `latest`, `history` trong `PortfolioStore` và `ExtraEtfImportsStore`.
   - Tiến trình: Đoạn mã sử dụng `with self._connect() as db:`. Trong Python standard library, context manager của đối tượng `sqlite3.Connection` được thiết kế để quản lý Transaction (`COMMIT` khi thoát bình thường, `ROLLBACK` khi có Exception), chứ **không phải** quản lý vòng đời tài nguyên (Resource Lifetime). Phương thức `close()` không bao giờ được gọi.
   - Hệ quả: Mỗi truy vấn API sinh ra một kết nối SQLite mới để mở file `portfolio.sqlite3`. Mối liên kết file descriptor trên hệ điều hành Windows/Linux vẫn ở trạng thái mở cho đến khi bộ gom rác Python (GC) chạy chu kỳ quét. Khi tần suất truy vấn tăng cao, số lượng file handles vượt quá giới hạn hệ thống, đồng thời các kết nối mở ngăn cản tiến trình ghi thực hiện khóa độc quyền, phát sinh ngoại lệ `sqlite3.OperationalError: database is locked`.
   - Kết luận: Phải triển khai cơ chế `try ... finally: connection.close()` hoặc bọc qua `@contextmanager` generator.

3. **Chuỗi suy luận cho NUM-01 (Portfolio FX Failure on VND - High)**:
   - Điểm vào: `agent/src/portfolio/fx.py` và `agent/src/portfolio/compatibility.py`.
   - Tiến trình: Hàm `build_rates` khởi tạo từ điển rates cứng chỉ gồm `{"USD": 1, "CNY": ..., "HKD": ...}`. Hàm `ensure_supported_currencies` duyệt danh sách tất cả các loại tiền tệ có mặt trong danh mục tài sản. Khi người dùng nạp dữ liệu tài khoản chứng khoán Việt Nam (có mã tiền tệ `VND`), dòng 239 lọc ra `missing = ['VND']`. Dòng 241 lập tức ném lỗi `PortfolioContractError`.
   - Hệ quả: Endpoint `/api/portfolio/refresh` bắt lỗi này và trả về HTTP 503 Service Unavailable. Toàn bộ tính năng Portfolio Dashboard không thể tải được tổng tài sản đối với nhà đầu tư tại thị trường Việt Nam.
   - Kết luận: Bổ sung tỷ giá `USD/VND` vào bộ nạp tỷ giá `build_rates` và cho phép cấu hình fallback tỷ giá tĩnh/động cho thị trường Việt Nam.

4. **Chuỗi suy luận cho SEC-01 (SSRF via LLM Settings - High)**:
   - Điểm vào: `POST /api/settings/llm`.
   - Tiến trình: Người dùng truyền `base_url` tùy ý. Hàm chỉ áp dụng bộ lọc regex an toàn nếu `provider.auth_type == "oauth"`. Đối với các provider API thông thường, giá trị được ghi thẳng vào tệp `.env`.
   - Hệ quả: Khi hệ thống thực thi tác vụ Agent hoặc kiểm tra mô hình, backend sẽ gửi HTTP request chứa header ủy quyền hoặc dữ liệu nội bộ tới địa chỉ `base_url` do kẻ tấn công chỉ định. Kẻ tấn công có thể quét cổng mạng nội bộ, tấn công dịch vụ Redis/Database nội bộ, hoặc trích xuất IAM token từ AWS/GCP Instance Metadata.
   - Kết luận: Tái sử dụng hàm `_validate_model_base_url` (đã có sẵn trong `settings_routes.py:126-155`) cho mọi loại provider.

---

## 3. CAVEATS (GIỚI HẠN PHẠM VI VÀ CÁC GIẢ ĐỊNH)

1. **Giới hạn phạm vi thẩm định**:
   - Quá trình kiểm toán tập trung vào mã nguồn nội tại của repository `D:\Vibe-Trading` (Backend Python, Frontend TypeScript). Các thư viện bên ngoài của bên thứ ba (LangChain, ReportLab, Playwright, Pandas, NumPy) được giả định là tuân thủ bảo mật ở phiên bản mới nhất.
   - Các broker kết nối trực tiếp (ví dụ IBKR Gateway, Binance API, SSI FastConnect) chưa được giả lập kết nối live với tài khoản thực, mà được kiểm tra thông qua cấu trúc xử lý dữ liệu và sandbox mock.

2. **Giả định**:
   - Giả định hệ điều hành máy chủ đích có thể là Windows hoặc Linux (hành vi xử lý file handle của SQLite trên Windows nghiêm ngặt hơn Linux: Windows khóa tệp hoàn toàn khi còn handle mở).
   - Tỷ giá USD/VND biến động quanh mức 25,000 VND/USD; việc chuyển đổi giá trị lớn đòi hỏi kiểu số `Decimal` với độ chính xác cao để tránh tràn số hoặc mất mát hàng đơn vị.

3. **Ghi nhận không có lỗ hổng (Negative Findings)**:
   - Cơ chế bảo vệ Path Traversal trong `agent/src/tools/path_utils.py` rất chặt chẽ: sử dụng `safe_path`, `_contained_path`, kiểm tra `resolve()`, cấm ký tự UNC (`\\\\`, `//`) và chống bypass Symlink hiệu quả.
   - Các endpoint tải artifact chính trong `agent/src/api/run_artifacts.py` sử dụng regex whitelist `_REPORT_ARTIFACT_RE` khắt khe, không phát hiện lỗ hổng tùy tiện đọc file hệ thống qua tham số tệp.

---

## 4. CONCLUSION (KẾT LUẬN & ĐỀ XUẤT BẢN VÁ CHI TIẾT)

Tổng hợp mức độ nghiêm trọng của 14 phát hiện:
- **Critical (Nghiêm trọng)**: 1 phát hiện (`RES-02`: Live runner race condition).
- **High (Cao)**: 3 phát hiện (`RES-01`: SQLite connection leak, `SEC-01`: LLM settings SSRF, `NUM-01`: Thiếu tiền tệ VND trong portfolio FX).
- **Medium (Trung bình)**: 7 phát hiện (`SEC-02`, `SEC-04`, `NUM-02`, `NUM-03`, `TRV-01`, `RES-03`, `RES-04`, `RES-05`).
- **Low (Thấp)**: 2 phát hiện (`SEC-03`, `TRV-02`).

### Đề xuất bản vá chi tiết (Actionable Patch Recommendations)

#### 1. Vá RES-02 (Khóa đồng bộ hóa Live Runner)
- **Tệp**: `agent/src/api/live_routes.py`
- **Mã sửa đổi đề xuất**:
  ```python
  # Khởi tạo khóa ở cấp module hoặc trong HostState
  _RUNNER_START_LOCK = asyncio.Lock()

  @app.post("/live/runner/start", dependencies=[Depends(require_auth)])
  async def start_runner_endpoint(payload: LiveRunnerControlRequest):
      broker = payload.broker.strip().lower()
      if not broker:
          raise HTTPException(status_code=400, detail="broker must not be blank")

      async with _RUNNER_START_LOCK:
          h = _host()
          tasks = h._runner_tasks
          existing = tasks.get(broker)
          if existing is not None and not existing.done():
              return {"broker": broker, "started": False, "already_running": True}

          mandate = h._active_mandate_state(broker)
          if mandate is None or mandate.expired:
              raise HTTPException(status_code=409, detail="invalid or expired mandate")

          runner = h._build_live_runner(broker)
          task = asyncio.ensure_future(h._drive_runner(runner))
          tasks[broker] = task
          task.add_done_callback(
              lambda t, b=broker: tasks.pop(b, None) if tasks.get(b) is t else None
          )
          return {"broker": broker, "started": True, "already_running": False}
  ```

#### 2. Vá RES-01 (Đóng kết nối SQLite tự động qua Context Manager)
- **Tệp**: `agent/src/portfolio/store.py` và `agent/src/portfolio/imports.py`
- **Mã sửa đổi đề xuất**:
  ```python
  from contextlib import contextmanager
  from typing import Iterator

  @contextmanager
  def _connect(self) -> Iterator[sqlite3.Connection]:
      connection = sqlite3.connect(self.path)
      connection.row_factory = sqlite3.Row
      try:
          yield connection
      finally:
          connection.close()
  ```

#### 3. Vá NUM-01 (Bổ sung VND vào Portfolio FX Rates)
- **Tệp**: `agent/src/portfolio/fx.py`
- **Mã sửa đổi đề xuất**:
  ```python
  def build_rates(
      usd_cny: Decimal,
      usd_hkd: Decimal,
      usd_vnd: Decimal | None = None,
  ) -> dict[str, Decimal]:
      """Build the production rates map, anchored on one USD."""
      vnd_rate = usd_vnd if usd_vnd is not None else Decimal("25400") # Fallback reference rate
      return {
          "USD": Decimal("1"),
          "CNY": _validated_rate("USD/CNY", usd_cny),
          "HKD": _validated_rate("USD/HKD", usd_hkd),
          "VND": _validated_rate("USD/VND", vnd_rate),
      }
  ```

#### 4. Vá SEC-01 (Validate toàn diện `base_url` trong Settings)
- **Tệp**: `agent/src/api/settings_routes.py`
- **Mã sửa đổi đề xuất**:
  ```python
  # Tại dòng 756 của update_llm_settings:
  base_url = (
      payload.base_url if payload.base_url is not None else provider.default_base_url
  ).strip()
  try:
      # Áp dụng kiểm tra chung cho toàn bộ provider
      base_url = _validate_model_base_url(provider, base_url)
  except ValueError as exc:
      raise HTTPException(
          status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
      ) from exc
  ```

#### 5. Vá SEC-02 (Khai báo Pydantic Model cho Swarm Run)
- **Tệp**: `agent/src/api/swarm_routes.py`
- **Mã sửa đổi đề xuất**:
  ```python
  class CreateSwarmRunRequest(BaseModel):
      model_config = ConfigDict(extra="forbid")
      preset_name: Annotated[str, Field(min_length=1, max_length=100)]
      user_vars: dict[str, Any] = Field(default_factory=dict)
      max_llm_calls: Annotated[int, Field(ge=1, le=500)] | None = None

  @app.post("/swarm/runs", dependencies=[Depends(require_auth)])
  async def create_swarm_run(payload: CreateSwarmRunRequest, http_request: Request):
      runtime = _get_swarm_runtime()
      extra = {"max_llm_calls": payload.max_llm_calls} if payload.max_llm_calls is not None else {}
      run = runtime.start_run(
          payload.preset_name,
          payload.user_vars,
          include_shell_tools=_host_shell_tools_enabled_for_request(http_request),
          **extra,
      )
      return {"id": run.id, "status": run.status.value, "preset_name": run.preset_name}
  ```

#### 6. Vá SEC-04 (Mã hóa tham số URL ở Frontend API)
- **Tệp**: `frontend/src/lib/api.ts`
- **Mã sửa đổi đề xuất**:
  ```typescript
  getRun: (id: string, params: RunDetailParams = {}) => {
    const q = new URLSearchParams();
    if (params.chart_symbol) q.set("chart_symbol", params.chart_symbol);
    const qs = q.toString();
    return request<RunData>(`/runs/${encodeURIComponent(id)}${qs ? `?${qs}` : ""}`);
  },
  getRunPreview: (id: string) => request<RunPreview>(`/runs/${encodeURIComponent(id)}/preview`),
  getRunCode: (id: string) => request<Record<string, string>>(`/runs/${encodeURIComponent(id)}/code`),
  deleteSession: (sid: string) => request<{ status: string }>(`/sessions/${encodeURIComponent(sid)}`, { method: "DELETE" }),
  renameSession: (sid: string, title: string) => request<{ status: string }>(`/sessions/${encodeURIComponent(sid)}`, { method: "PATCH", body: JSON.stringify({ title }) }),
  sendMessage: (sid: string, content: string) => request<{ message_id: string; attempt_id: string }>(`/sessions/${encodeURIComponent(sid)}/messages`, { method: "POST", body: JSON.stringify({ content }) }),
  ```

#### 7. Vá NUM-02 (Chuẩn hóa số học và tiền tệ trên Frontend Formatter)
- **Tệp**: `frontend/src/lib/formatters.ts`
- **Mã sửa đổi đề xuất**:
  ```typescript
  export function formatMetricVal(k: string, v: number): string {
    if (typeof v !== "number" || !Number.isFinite(v)) return "--";
    if (PCT_KEYS.includes(k)) {
      const sign = v > 0 ? "+" : "";
      const val = Math.round((v * 100) * 100) / 100;
      return `${sign}${val.toFixed(2)}%`;
    }
    if (RATIO_KEYS.includes(k)) {
      const sign = v > 0 ? "+" : "";
      return `${sign}${v.toFixed(2)}`;
    }
    if (INT_KEYS.includes(k)) return String(Math.round(v));
    if (k === "final_value") return v.toLocaleString("vi-VN", { maximumFractionDigits: 2 });
    if (k === "avg_holding_days") return v.toFixed(1);
    return v.toFixed(4);
  }
  ```

#### 8. Vá TRV-01 (Tự động xóa tệp trung gian sau khi publish)
- **Tệp**: `agent/src/reporting/service.py`
- **Mã sửa đổi đề xuất**:
  ```python
  # Tại dòng 93 sau khi publish artifact:
  for fmt in fmt_list:
      file_path_str = result.get(fmt)
      if file_path_str:
          file_path = Path(file_path_str)
          artifact_meta = publish_report_artifact(file_path, format=fmt)
          artifacts.append(artifact_meta)
          # Xóa bỏ tệp staging gốc sau khi đã sao chép an toàn vào storage
          try:
              file_path.unlink(missing_ok=True)
          except OSError:
              pass
  ```

#### 9. Vá RES-03, RES-04 & RES-05 (Dọn dẹp bộ nhớ đệm Cache & EventBus)
- **Tệp `agent/src/reporting/service.py`**:
  Thay thế `_JOBS_CACHE: dict` bằng `collections.OrderedDict` với giới hạn tối đa 500 mục gần nhất (`if len(self._JOBS_CACHE) > 500: self._JOBS_CACHE.popitem(last=False)`).
- **Tệp `agent/src/session/events.py`**:
  Trong khối `finally` của `subscribe`, xóa khóa rỗng:
  ```python
  subs = self._subscribers.get(session_id, [])
  if queue in subs:
      subs.remove(queue)
  if not subs:
      self._subscribers.pop(session_id, None)
  ```
- **Tệp `agent/src/channels/websocket.py`**:
  Trong `_cleanup_connection(connection)`:
  Quét và dọn dẹp các stream buffer thuộc `chat_ids` bị ngắt kết nối mà chưa phát `_stream_end`:
  ```python
  keys_to_remove = [k for k in self._stream_text_buffers if k[0] in chat_ids]
  for k in keys_to_remove:
      self._stream_text_buffers.pop(k, None)
  ```

---

## 5. VERIFICATION METHOD (PHƯƠNG THỨC KIỂM THỬ VÀ XÁC MINH ĐỘC LẬP)

Để kiểm chứng độc lập các phát hiện và đảm bảo hệ thống không bị lỗi hồi quy (regression) sau khi áp dụng bản vá, các kiểm thử viên có thể thực hiện theo quy trình sau:

### Lệnh thực thi kiểm thử tổng thể

```powershell
# Chạy toàn bộ test suite cho API server và các module liên quan
cd D:\Vibe-Trading\agent
pytest tests/ -k "test_live or test_portfolio or test_settings or test_swarm or test_reporting" -v
```

### 1. Kiểm thử xác minh RES-02 (Live Runner Race Condition)
- **Tạo kịch bản kiểm thử**: `agent/tests/test_live_runner_concurrency.py`
- **Cách thức**: Sử dụng `asyncio.gather` gửi 5 request đồng thời tới `POST /live/runner/start` với cùng `broker="alpaca"`.
- **Điều kiện đạt (Pass)**: Chỉ có đúng 1 request trả về `started=True, already_running=False`. 4 request còn lại phải trả về `already_running=True` và danh sách tác vụ `_runner_tasks` chỉ chứa đúng 1 task duy nhất.
- **Lệnh chạy**:
  ```powershell
  pytest tests/test_live_runner_concurrency.py -v
  ```

### 2. Kiểm thử xác minh RES-01 (SQLite File Handle Leak)
- **Tạo kịch bản kiểm thử**:
  Thực hiện vòng lặp gọi `store.latest()` và `store.history()` 1,000 lần liên tiếp.
- **Kiểm tra**: Sử dụng module `psutil` để đếm số file descriptor mở của tiến trình Python trước và sau vòng lặp:
  ```python
  proc = psutil.Process()
  initial_handles = len(proc.open_files())
  for _ in range(1000):
      store.latest()
  assert len(proc.open_files()) == initial_handles
  ```
- **Điều kiện đạt (Pass)**: Số lượng file handle không tăng lên theo số lần truy vấn.

### 3. Kiểm thử xác minh NUM-01 (Portfolio VND Currency Support)
- **Thực thi**:
  Gửi request `POST /api/portfolio/refresh` với payload chứa vị thế có `currency: "VND"`.
- **Điều kiện đạt (Pass)**: Không xuất hiện ngoại lệ `PortfolioContractError: portfolio FX conversion is not available for: VND`. Hệ thống chuyển đổi thành công tổng giá trị sang USD/VND và trả về mã HTTP 200 OK.

### 4. Kiểm thử xác minh SEC-01 (SSRF Prevention in Settings)
- **Thực thi**:
  Gửi request `POST /api/settings/llm` với `base_url="http://169.254.169.254/latest/meta-data/"` hoặc `base_url="http://127.0.0.1:8080/admin"`.
- **Điều kiện đạt (Pass)**: API server trả về HTTP 400 Bad Request kèm thông báo lỗi từ chối URL mạng nội bộ/metadata.

---
*Báo cáo được hoàn thành độc lập và cung cấp đầy đủ bằng chứng mã nguồn cho toàn bộ nhóm phát triển Vibe-Trading.*
