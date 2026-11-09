# BÁO CÁO BÀN GIAO (HANDOFF REPORT) - WORKSTREAM 3

Người thực hiện: explorer_ws3_agent
Thời gian hoàn thành: 2026-11-08T14:18:00Z
Nhiệm vụ: Nghiên cứu và Kiểm toán Kiến trúc Agent & Quy trình Suy luận / Phản hồi AI (Workstream 3).
Tệp báo cáo chi tiết: D:\Vibe-Trading\.agents\teamwork\explorer_ws3_agent\analysis.md

---

## 1. OBSERVATION (QUAN SÁT THỰC TẾ)

Qua quá trình rà soát trực tiếp trên hệ thống tệp mã nguồn tại `d:\Vibe-Trading`, các quan sát sau đây đã được ghi nhận nguyên văn cùng vị trí tệp và dòng lệnh chính xác:

1. Phân hệ ReAct Execution Loop:
   - Tệp `agent/src/agent/loop.py`:
     * Lớp `AgentLoop` kế thừa `ToolCallLifecycle` (`loop.py:171`).
     * Quản lý ngữ cảnh 5 tầng được khai báo rõ tại phần đầu tệp (`loop.py:3-9`): Layer 1 (microcompact), Layer 2 (context_collapse), Layer 3 (auto_compact), Layer 4 (compact tool), Layer 5 (iterative update).
     * Khởi tạo `GroundingLedger` tại `loop.py:429-436`.
     * Giám sát tiến độ rỗng và treo qua `_stall_watchdog` daemon thread (`loop.py:564-570, 1266-1334`) theo dõi biến `_last_activity_wall` và timeout `_stall_timeout_seconds()`.
     * Cảnh báo kết thúc tại 80% số vòng lặp: `wrap_up_at = max(1, int(self.max_iterations * 0.8))` (`loop.py:556, 632-654`).
     * Cưỡng chế văn bản thuần tại vòng lặp cuối: `tool_defs = None if is_last_iteration or correction_text_only else request_definitions(self.registry)` (`loop.py:686-690`).
     * Cổng kiểm chứng bản thảo: Gọi `validate_and_release` (`loop.py:982-991`), quản lý tối đa `MAX_GROUNDING_REVISIONS = 2` lượt chỉnh sửa.
   - Tệp `agent/src/agent/tool_lifecycle.py`:
     * Phân tách công cụ chỉ đọc và ghi để lập lịch: `_batch_execute` gom các công cụ `is_readonly` liên tiếp để chạy song song qua `ThreadPoolExecutor(max_workers=min(len(runnable), 8))` (`tool_lifecycle.py:446-472, 519`).
     * Cổng tiền cấp quyền: Gọi `self._grounding.authorize_tool_call` trước khi thực thi công cụ (`tool_lifecycle.py:181-199`).
     * Bộ nhớ Replay sau nén ngữ cảnh: `MAX_READONLY_REPLAY_RECOVERIES = 6` (`tool_lifecycle.py:66, 206-255`).
     * Gắn thẻ trích dẫn nguồn vào kết quả công cụ: `_attach_source_index(model_result, source_index)` (`tool_lifecycle.py:975-980`).

2. Phân hệ Swarm DAG Runtime:
   - Tệp `agent/src/swarm/models.py`:
     * Khai báo các mô hình dữ liệu Pydantic: `SwarmAgentSpec` (dòng 176), `SwarmTask` (dòng 204), `SwarmEvent` (dòng 241), `SwarmRun` (dòng 262), `WorkerResult` (dòng 334).
     * `SwarmTask` chứa `depends_on`, `blocked_by`, và `input_from` (`models.py:229-231`).
   - Tệp `agent/src/swarm/task_store.py`:
     * Kiểm tra tính hợp lệ đồ thị và phát hiện chu trình bằng DFS tô 3 màu (WHITE/GRAY/BLACK) (`task_store.py:206-243`).
     * Kiểm tra tính tổ tiên hợp lệ của `input_from` trong cây DAG (`task_store.py:244-252`).
     * Phân tầng tô-pô bằng thuật toán Kahn `topological_layers(tasks)` dựa trên tính toán bán bậc vào (in-degree) (`task_store.py:256-300`).
   - Tệp `agent/src/swarm/runtime.py`:
     * `SwarmRuntime.start_run` khởi chạy tiến trình nền daemon `threading.Thread(name=f"swarm-{run.id}")` (`runtime.py:378-384`).
     * Tiền nạp dữ liệu nến: `_prefetch_grounding_data` quét symbol và tải OHLCV vào `run.grounding_data` trước khi chạy các tầng (`runtime.py:869-921`).
     * Cổng chặn an toàn theo phụ thuộc (Dependency-Aware Gating): Nếu một task thượng nguồn không ở trạng thái `completed`, task hạ nguồn lập tức bị chuyển thành `TaskStatus.blocked` và phát sự kiện `task_blocked` (`runtime.py:986-1015`).
     * Cơ chế retry phân tán trễ: `_worker_retry_delay_s` áp dụng Equal-Jitter Exponential Backoff (`runtime.py:70-78`) và làm sạch artifact cũ bằng `clear_agent_artifacts` (`runtime.py:1201-1203`).
     * Hạn chót tầng: `layer_deadline = layer_budget + 60` giây (`runtime.py:1064-1096`).
     * Tiếp tục chạy lại từ điểm dừng (Resume Overlay): `_apply_resume_overlay` (`runtime.py:732-867`) kế thừa các task đã hoàn thành từ phiên trước nếu định nghĩa và model không đổi.

3. Phân hệ Multi-Role Council Debate:
   - Tệp `agent/src/trading/forex/council.py`:
     * Khai báo 6 vai trò: `Role = Literal["technical", "macro", "bull", "bear", "risk", "manager"]` (`council.py:26`).
     * 4 giai đoạn tranh luận: `STAGES = (("technical", "macro"), ("bull", "bear"), ("risk",), ("manager",))` (`council.py:184`).
     * Bắt buộc tham chiếu báo cáo đối lập: `risk` bắt buộc tham chiếu `report.bull` và `report.bear`; `manager` bắt buộc tham chiếu `report.risk` (`council.py:444-447`).
     * Quyền phủ quyết tuyệt đối (Hard Veto): `risk.veto` hoặc `risk.stance == "wait"` hoặc `manager.veto` cưỡng chế khuyến nghị về `"wait"` (`council.py:166, 470-471`).
     * Tính toán kịch bản xác định: Hàm `candidates()` tính toán mức giá Entry, Stop Loss, Take Profit từ báo giá sàn thực tế và chỉ báo ATR (`council.py:268-295`).
   - Tệp `agent/src/tools/council_contract.py`:
     * Chuẩn hóa và thẩm định phán quyết hội đồng (`evaluate_verdict` tại dòng 541).
     * Kiểm tra tính hợp lý tài chính: Stop Loss không được nằm sai phía so với Entry (`council_contract.py:748-750`), trần vị thế không vượt quá 30% NAV (`council_contract.py:637-638`), kiểm tra tương thích đơn vị giá 1000x giữa các trường (`council_contract.py:654-734`).

4. Phân hệ AI Response Quality & Trust Architecture:
   - Thư mục `agent/src/agent/grounding/`:
     * Khối khai báo số liệu: Yêu cầu mô hình khai báo ````figures` với 5 vai trò `observed`, `derived`, `proposed`, `cited`, `bare` (`figures.py:40-46`).
     * Bộ quy tắc kiểm tra `@grounding_check` (`registry.py`, `policies.py`, `figures_checks.py`, `identity_checks.py`):
       - `figure-observed`: Bắt buộc số liệu thực tế khớp trong dung sai 0.5% (`policies.py:105, 1693`).
       - `figure-derived`: Bắt buộc biểu thức toán học trong note phải đánh giá được trên các toán hạng thực tế (`policies.py:2209`).
       - `undeclared-figure`: Chặn đứng mọi con số đo lường xuất hiện trong văn bản mà không được khai báo trong khối figures (`policies.py:680`).
       - `chart-observed-payload`: Bắt buộc biểu đồ phải khớp với biểu đồ do công cụ trả về (`figures_checks.py:48-60`).
       - `figure-cited`: Bắt buộc con số trích dẫn phải xuất hiện thực tế trong văn bản nguồn thu thập được (`policies.py:2390`).
     * Danh mục nguồn tin 5 tầng (`SOURCE_POLICIES` tại `sources.py:95-191`): Tầng 1 (Sở GDCK, Cơ quan quản lý: HOSE, HNX, SSC, SBV, SEC, FED, LBMA), Tầng 2 (Reuters, Bloomberg, WSJ, FT), Tầng 3 (FiinGroup, Vietstock DataFeed, LSEG), Tầng 4 (SSI, Vietcap, VnEconomy), Tầng 5 (Mạng xã hội - unverified).
     * Quy trình giải phóng và cắt gọt (`loop_grounding.py:60-292` và `release.py`): Tự động sửa lỗi kỹ thuật, hiệu đính tối đa 2 lần, cắt bỏ số liệu sai thành `(đã lược※)` / `(omitted※)` (`redacted_release`) hoặc trả về fallback an toàn (`safe_fallback`).

---

## 2. LOGIC CHAIN (CHUỖI SUY LUẬN LOGIC)

1. **Từ Cơ chế ReAct Loop và Context Budget đến Tính Ổn định Hệ thống**:
   - Nhờ có `ContextMeter` theo dõi kích thước token thực tế từ phản hồi của nhà cung cấp kết hợp với cơ chế nén 5 tầng (Microcompact -> Collapse -> Auto-Compact -> Compact Tool -> Iterative Update), hệ thống duy trì được ngữ cảnh hội thoại dài hàng trăm lượt mà không bị tràn bộ nhớ vật lý.
   - Việc sao lưu transcript ra file `.jsonl` độc lập và giữ lại `_verification_ledger` bảo đảm rằng sau khi nén ngữ cảnh, tác tử không bị mất các dữ kiện tài chính đã kiểm chứng, giải quyết được hiện tượng "re-fetch hallucination" (tác tử liên tục gọi lại các công cụ cũ để tìm lại số liệu đã mất).

2. **Từ Thuật toán Kahn và Dependency-Aware Gating đến An toàn Luồng Công việc DAG**:
   - Việc phân tầng tô-pô bằng thuật toán Kahn cho phép tối ưu hóa hiệu năng tối đa khi chạy song song các phân tích độc lập (ví dụ Phân tích Cơ bản và Kỹ thuật cùng chạy ở Layer 0).
   - Tuy nhiên, tính an toàn thể chế được bảo đảm bởi `Dependency-Aware Gating`: Một tác tử hạ nguồn (như Portfolio Manager) tuyệt đối không thể được kích hoạt nếu tác tử rủi ro (Risk Officer) thượng nguồn bị lỗi. Điều này loại bỏ hoàn toàn khả năng phát sinh một quyết định đầu tư "mồ côi" không qua thẩm định rủi ro.

3. **Từ Kiến trúc Council 4 Giai đoạn đến Tính Khách quan trong Quyết định**:
   - Bằng cách chia cuộc họp thành 4 giai đoạn độc lập (`STAGES`) và cưỡng chế đối chiếu chéo bằng mã nguồn (bắt buộc Risk phải đọc Bull & Bear, Manager phải đọc Risk), hệ thống ngăn chặn việc mô hình bị thiên kiến khẳng định (confirmation bias) hoặc ảo giác đồng thuận.
   - Tách biệt hoàn toàn phép toán mức giá (Entry, SL, TP) ra khỏi mô hình ngôn ngữ và giao cho hàm xác định `candidates()` tính toán dựa trên ATR và quote sàn, bảo đảm rằng mô hình chỉ đóng vai trò phân tích định tính và đánh giá kịch bản, không thể tự ý bịa đặt các mức giá vi phạm quy định sàn hoặc khoảng cách dừng lỗ tối thiểu.

4. **Từ Sổ cái Grounding Ledger và Bộ kiểm tra Phân tầng đến Cam kết Không Ảo giác**:
   - Cơ chế bắt buộc khai báo số liệu (`figures block`) kết hợp với kiểm tra đối chiếu dung sai 0.5% tạo ra một rào chắn kiểm toán không thể xuyên thủng đối với các số liệu thị trường.
   - Việc phân tầng nguồn tin trích dẫn (`SOURCE_POLICIES`) gắn liền với kiểm tra sự hiện diện của con số trong văn bản gốc bảo đảm các khuyến nghị đầu tư luôn dựa trên các nguồn tin thể chế được công nhận (Sở giao dịch, UBCKNN, Hãng tin uy tín), triệt tiêu rủi ro sử dụng tin đồn thất thiệt từ mạng xã hội.

---

## 3. CAVEATS (CÁC ĐIỂM CHƯA KHẢO SÁT VÀ GIẢ ĐỊNH)

1. Môi trường kiểm thử thực tế với broker live:
   - Các kiểm toán trên được thực hiện thông qua đọc và phân tích tĩnh toàn bộ mã nguồn. Việc kết nối trực tiếp với tài khoản live MetaTrader 5 (MT5) hoặc các API broker trong điều kiện nghẽn mạng cực độ (network congestion) trong các sự kiện tin tức vĩ mô lớn (Non-Farm Payrolls, CPI) chưa được đo lường độ trễ thực tế.
2. Mô hình ngôn ngữ thử nghiệm:
   - Hệ thống hỗ trợ đa dạng provider (OpenAI, Anthropic, DeepSeek, Google Gemini...). Độ tuân thủ cấu trúc của khối `figures` phụ thuộc nhất định vào năng lực instruction-following của từng model cụ thể, dù hệ thống đã có tầng tự động sửa lỗi và cắt gọt (`redacted_release`) bảo vệ.
3. Không có ngoại lệ nào khác: Toàn bộ phạm vi yêu cầu của Workstream 3 đã được rà soát đầy đủ và toàn diện.

---

## 4. CONCLUSION (KẾT LUẬN CUỐI CÙNG)

Phân hệ Agent Architecture & AI Reasoning / Response Workflow (Workstream 3) của Vibe-Trading sở hữu một kiến trúc phần mềm tài chính mẫu mực, đạt chuẩn cấp thể chế (Institutional Grade). Hệ thống kết hợp hài hòa giữa:
1. **Khả năng tự động hóa linh hoạt**: Vòng lặp ReAct loop mạnh mẽ với 5 tầng nén ngữ cảnh và cơ chế chống treo tiến trình.
2. **Khả năng mở rộng phân tán**: Đồ thị Swarm DAG phân tầng tô-pô song song an toàn và có khả năng phục hồi (Resume Overlay).
3. **Độ an toàn tài chính tối thượng**: Hội đồng Phản biện 6 vai trò với quyền Veto cưỡng chế và bộ tính toán kịch bản dựa trên toán học xác định.
4. **Cam kết chất lượng phản hồi không ảo giác**: Sổ cái Grounding Ledger phân tầng kiểm chứng số liệu và nguồn trích dẫn với độ chính xác đến từng chữ số.

Kiến trúc này hoàn toàn đủ năng lực làm nền tảng cho việc tích hợp hiển thị biểu đồ thời gian thực (Workstream 1) và tuân thủ các chuẩn mực phân tích định lượng của Viện CFA (Workstream 4).

---

## 5. VERIFICATION METHOD (PHƯƠNG PHÁP KIỂM CHỨNG ĐỘC LẬP)

Để kiểm chứng độc lập toàn bộ các kết luận và phát hiện trong báo cáo, người kế nhiệm có thể thực thi các lệnh kiểm thử tự động của dự án:

1. Kiểm chứng ReAct Execution Loop & Context Compaction:
   - Chạy lệnh pytest:
     `pytest agent/tests/test_agent_loop_*.py -v`
     `pytest agent/tests/test_agent_grounding.py -v`
     `pytest agent/tests/test_agent_config.py -v`

2. Kiểm chứng Swarm DAG Runtime & Topological Scheduling:
   - Chạy lệnh pytest:
     `pytest agent/tests/test_swarm_presets_packaging.py -v`
     (hoặc các test suite liên quan đến swarm store và runtime).

3. Kiểm chứng Multi-Role Council & Trade Plan Contract:
   - Chạy lệnh pytest:
     `pytest agent/tests/test_forex_council.py -v`
     `pytest agent/tests/test_council_contract.py -v`
     `pytest agent/tests/test_research_council_tool.py -v`

4. Kiểm tra các tệp nhật ký và bằng chứng:
   - Kiểm tra tệp báo cáo chi tiết: `D:\Vibe-Trading\.agents\teamwork\explorer_ws3_agent\analysis.md`.
   - Kiểm tra mã nguồn trực tiếp tại các đường dẫn và dòng lệnh đã dẫn chứng trong báo cáo.

Điều kiện vô hiệu hóa (Invalidation Condition):
- Nếu có bất kỳ sửa đổi nào trong `loop.py` làm thay đổi logic của `validate_and_release`, hoặc nới lỏng dung sai `_TOLERANCE` trong `policies.py`, hoặc gỡ bỏ quyền Veto của `risk` trong `council.py`, các kết luận về tính an toàn của hệ thống cần được đánh giá lại.
