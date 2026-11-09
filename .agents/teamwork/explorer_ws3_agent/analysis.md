# BÁO CÁO NGHIÊN CỨU VÀ ĐÁNH GIÁ KIẾN TRÚC AGENT VÀ QUY TRÌNH SUY LUẬN AI (WORKSTREAM 3)

Thực hiện bởi: explorer_ws3_agent
Thời gian thực hiện: 2026-11-08T14:16:00Z
Đối tượng khảo sát: Toàn bộ hệ thống Agent Core, Swarm DAG Runtime, Council Debate Mechanism, và Grounding & Trust Architecture trong kho mã nguồn Vibe-Trading.

---

## TỔNG QUAN HỆ THỐNG

Kiến trúc AI của Vibe-Trading được thiết kế theo mô hình phòng vệ theo chiều sâu (defense-in-depth) chuyên biệt cho lĩnh vực phân tích tài chính và giao dịch tự động. Thay vì phụ thuộc vào các thư viện trừu tượng hóa nặng nề như LangChain AgentExecutor thông thường, hệ thống tự xây dựng một lõi ReAct loop tùy biến hoàn toàn (`AgentLoop`), kết hợp một hệ thống thực thi đồ thị có hướng không chu trình (`SwarmRuntime`), cơ chế tranh luận đa vai trò có quyền phủ quyết (`Council`), và tầng bảo vệ chống ảo giác nghiêm ngặt (`GroundingLedger`).

Báo cáo này phân tích chi tiết 4 phân hệ cốt lõi dựa trên bằng chứng trực tiếp từ mã nguồn:
1. ReAct Execution Loop (`agent/src/agent/loop.py`, `tool_lifecycle.py`, `context_compact.py`, `context_budget.py`).
2. Swarm DAG Runtime (`agent/src/swarm/runtime.py`, `models.py`, `task_store.py`, `worker.py`, `store.py`).
3. Multi-Role Council Debate Mechanism (`agent/src/trading/forex/council.py`, `council_context.py`, `agent/src/tools/council_contract.py`, `research_council_tool.py`, `agent/src/swarm/presets/vietnam_equity_council.yaml`).
4. AI Response Quality & Trust Architecture (`agent/src/agent/grounding/ledger.py`, `evidence.py`, `figures.py`, `policies.py`, `sources.py`, `release.py`, `loop_grounding.py`).

---

## 1. REACT EXECUTION LOOP

### 1.1. Cấu trúc tổng thể và Vòng đời lặp
Tệp nguồn chính: `agent/src/agent/loop.py` (1834 dòng) và `agent/src/agent/tool_lifecycle.py` (1029 dòng).
Lớp cốt lõi: `AgentLoop(ToolCallLifecycle)` kế thừa từ `ToolCallLifecycle`.

Vòng lặp ReAct hoạt động qua hàm `AgentLoop._run_bound` (`agent/src/agent/loop.py:367-1264`):
- Khởi tạo phiên làm việc với LLM: `bind_llm_session_id(session_id)` bảo đảm định danh phiên ổn định qua ContextVar (`loop.py:361-365`).
- Tạo thư mục thực thi: `RunStateStore.create_run_dir` tạo thư mục tại `.runs/{run_id}` để lưu trữ toàn bộ vết thực thi (`trace.jsonl`), trạng thái (`state.json`), nhật ký ngữ cảnh (`request_context.json`) và chứng cứ kiểm chứng (`artifacts/grounding_evidence.json`).
- Khởi tạo thực thể Grounding: `GroundingLedger` được kích hoạt ngay đầu phiên (`loop.py:429-436`) để bám sát toàn bộ chuỗi suy luận và kết quả công cụ.
- Tạo nhật ký nguồn gốc (`run_manifest.json`): Lưu băm (SHA-256) của system prompt, phiên bản gói phần mềm, danh sách công cụ đã đăng ký (`loop.py:289-345`) phục vụ kiểm toán độc lập.

### 1.2. Cơ chế xây dựng Prompt và Đăng ký Tool Schema
- Quản lý ngữ cảnh qua `ContextBuilder` (`agent/src/agent/context.py`):
  * Tích hợp System Prompt nền tảng, các kỹ năng tĩnh/động (`skills`), mục tiêu đang kích hoạt (`active_goal_id`), bộ nhớ phiên (`WorkspaceMemory`), bộ nhớ dài hạn (`PersistentMemory`), và lịch sử hội thoại.
  * Nếu có mục tiêu nghiên cứu (`active_goal_id`), bọc yêu cầu của người dùng trong khối `<goal-context>` và `<user-message>` (`loop.py:440-446`).
- Đăng ký công cụ động (`request_definitions`):
  * Được tính toán qua `request_definitions(self.registry)` (`loop.py:575-578`).
  * Đo lường chi phí token của Tool Schema: `self._tool_schema_tokens = estimate_tokens(request_definitions(self.registry))`. Số token này được hạch toán ngang hàng với System Prompt trong hạn mức ngữ cảnh vật lý của mô hình (`loop.py:414-416`).
  * Cưỡng chế văn bản thuần (Text-Only Mode): Tại vòng lặp cuối cùng (`iteration == self.max_iterations`) hoặc trong các lượt hiệu đính kiểm chứng (`grounding_correction_text_only`), `tool_defs` bị gán về `None` (`loop.py:686-691`). Điều này tước bỏ hoàn toàn định nghĩa công cụ gửi sang LLM, ép buộc mô hình phải trả lời bằng ngôn ngữ tự nhiên thuần túy mà không thể tiếp tục gọi công cụ vô tận.

### 1.3. Chu kỳ Thought - Action - Observation và Xử lý Luồng Stream
- Luồng streaming hai kênh (Reasoning và Text):
  * Lớp `TurnStream` (`agent/src/agent/loop_streaming.py`) nhận các đoạn dữ liệu `on_text_chunk`, `on_reasoning_chunk` và `on_waiting_chunk` từ client LLM (`loop.py:712-724`).
  * Suy nghĩ nội tâm (Thinking/Reasoning) được thu thập vào `stream.thinking_chunks` và ghi nhận độc lập vào `trace.jsonl` dưới nhãn `{"type": "thinking"}` (`loop.py:817-824`).
  * Kiểm soát an toàn luồng Text: Nếu `stream.buffer_text_output` kích hoạt (hoặc khi phát hiện số liệu thị trường), luồng văn bản ra màn hình bị chặn một phần thông qua `self._grounding.streamable_length(text)` (`loop.py:831-835, 1087-1097`) nhằm ngăn chặn việc hiển thị các con số giả mạo ra ngoài trước khi được kiểm chứng.
- Đóng gói lời gọi công cụ:
  * Lời gọi công cụ từ mô hình được định dạng qua `context.format_assistant_tool_calls` và gắn nhãn chữ ký tư duy qua `_attach_tool_call_thought_signatures` (`loop.py:1098-1105`).

### 1.4. Phân nhóm và Thực thi Công cụ (Read/Write Batching)
Tệp nguồn: `agent/src/agent/tool_lifecycle.py:424-532`.
Hệ thống triển khai cơ chế phân tách và thực thi công cụ thông minh:
- Phân tích tính chất công cụ (`is_readonly`):
  * Các công cụ chỉ đọc (Readonly) liên tiếp được gom vào nhóm song song (`mode == "parallel"`).
  * Các công cụ ghi (Write) hoặc có tác dụng phụ được tách thành nhóm tuần tự (`mode == "serial"`).
- Thực thi song song an toàn qua ThreadPoolExecutor:
  * Trong `_execute_parallel` (`tool_lifecycle.py:473-532`), nhóm công cụ chỉ đọc được gửi vào `ThreadPoolExecutor(max_workers=min(len(runnable), 8))` cùng với `copy_context()`.
  * Mỗi tiến trình con sở hữu một bộ hẹn giờ Heartbeat độc lập (`HeartbeatTimer`) phát tín hiệu định kỳ mỗi 5 giây (`_heartbeat_interval_s()`).
- Bắt buộc kiểm tra tiền quyền (Authorization Gate):
  * Trước khi đưa vào thực thi, từng lời gọi công cụ bắt buộc phải vượt qua `self._grounding.authorize_tool_call` (`tool_lifecycle.py:181-199`). Nếu mã giao dịch (symbol) chưa được xác thực danh tính, lệnh gọi bị chặn lập tức và trả về thông báo lỗi cấu trúc mà không kích hoạt logic bên dưới.

### 1.5. Bộ nhớ đệm lặp lại và Bảo vệ chống kẹt (Deduplication & Replay)
- Khóa định danh công cụ duy nhất (`_identical_call_key`): Được tính toán từ tên công cụ và chuỗi JSON đã chuẩn hóa của tham số đầu vào (`tool_lifecycle.py:822-838`).
- Chặn lặp lại công cụ đã thành công: Nếu một lời gọi công cụ không lặp lại (`not is_repeatable`) với tham số giống hệt đã thực thi thành công trước đó trong cùng phiên, hệ thống chặn lại và trả về thông báo bỏ qua (`skipped: True`) (`tool_lifecycle.py:257-280`).
- Bộ nhớ đệm xác định (`_called_identical`): Áp dụng cho các công cụ tính toán toán học thuần túy (`deterministic == True`, ví dụ `financial_rigor`). Kết quả được trả về ngay từ cache thay vì tính toán lại nhiều lần (`tool_lifecycle.py:288-314`).
- Bộ nhớ Replay sau khi nén ngữ cảnh (`_readonly_replay_cache`): Khi ngữ cảnh bị nén (Compaction) làm mất kết quả quan sát cũ, nếu mô hình gọi lại chính xác truy vấn đó, hệ thống khôi phục trực tiếp từ bộ đệm Replay mà không cần gọi lại nguồn mạng bên ngoài (`tool_lifecycle.py:206-255`). Số lần khôi phục bị giới hạn nghiêm ngặt bởi `MAX_READONLY_REPLAY_RECOVERIES = 6`.

### 1.6. Hệ thống giám sát và Giới hạn dừng lặp (Watchdog & Max Iteration Guards)
- Giới hạn lặp tối đa: `max_iterations = 50` (mặc định).
- Cảnh báo chuẩn bị kết thúc (Wrap-up Nudge):
  * Tại ngưỡng 80% số vòng lặp (`wrap_up_at = max(1, int(self.max_iterations * 0.8))`): hệ thống tự động chèn thông điệp hệ thống yêu cầu mô hình dừng phân tích mới, hoàn tất việc ghi file và chuyển sang kết luận (`loop.py:632-654`).
- Cưỡng chế ghi file (Pending Write Directive):
  * Tại vòng lặp áp chót (`iteration == self.max_iterations - 1`): hệ thống kiểm tra các tệp mục tiêu yêu cầu trong đề bài chưa được ghi, từ đó chèn chỉ thị cưỡng chế mô hình phải ghi tệp ngay (`loop.py:661-673`).
- Stall Watchdog (Chống Zombie Run):
  * Một tiến trình nền `_stall_watchdog` (`loop.py:564-570, 1266-1334`) theo dõi mốc thời gian hoạt động thực tế cuối cùng (`_last_activity_wall`).
  * Nếu không có phản hồi LLM hoặc kết quả công cụ nào trong khoảng thời gian `_stall_timeout_seconds()` (mặc định 300s): watchdog phát cảnh báo `stall_warning`, sau đó ghi trạng thái thất bại vào `trace.jsonl` và `state.json`, kích hoạt `_cancel_event` để dập tắt vòng lặp. Tín hiệu Heartbeat không được tính là tiến độ thực sự.
- Ngắt mạch bộ lọc nội dung (Content Filter Circuit Breaker):
  * Nếu phản hồi từ nhà cung cấp liên tiếp kích hoạt bộ lọc nội dung đạt `MAX_CONSECUTIVE_CONTENT_FILTER_SKIPS`, hệ thống ngắt phiên chạy (`loop.py:843-859`).
- Giám sát phản hồi rỗng: Nếu LLM trả về kết quả rỗng không có text và tool call, hệ thống nhắc nhở tối đa 1 lần (`MAX_CONSECUTIVE_EMPTY_RESPONSE_SKIPS = 1`) trước khi dừng phiên (`loop.py:919-932`).
- Phát hiện cú pháp Tool Call lẫn trong văn bản: Nếu mô hình xả mã XML/DSML tool call vào văn bản ở vòng lặp text-only, hệ thống chặn lại và bắt buộc viết lại bằng văn xuôi hoặc trả về fallback an toàn (`loop.py:940-981`).

### 1.7. Kiến trúc Quản lý Ngữ cảnh 5 Tầng (Five-Layer Context Management)
Tệp nguồn: `agent/src/agent/context_compact.py` và `agent/src/agent/context_budget.py`.
Hệ thống theo dõi chặt chẽ hạn mức ngữ cảnh thực tế của mô hình (`CompactionBudget`) và điều phối 5 tầng nén:
1. Tầng 1 - Microcompact (`_microcompact_and_unblock`):
   * Kích hoạt khi token vượt ngưỡng `budget.micro_at` (`loop.py:1459-1471`).
   * Cắt tỉa nội dung chi tiết của các kết quả công cụ cũ nhất, chỉ giữ lại phần tóm tắt và mở lại khóa cho các truy vấn chỉ đọc bị mất.
2. Tầng 2 - Context Collapse (`_context_collapse`):
   * Kích hoạt khi token vượt ngưỡng `budget.collapse_at`.
   * Gập các khối văn bản dài mà không tốn chi phí gọi LLM (zero-cost folding).
3. Tầng 3 - Auto Compact (`_auto_compact`):
   * Kích hoạt khi token vượt `budget.compact_at` (`loop.py:1610-1806`).
   * Tiến hành nén giao dịch (Transactional Summarization): Toàn bộ lịch sử hội thoại được sao lưu ra `transcript_{timestamp}.jsonl`.
   * Mô hình tóm tắt phần đầu (Head) theo từng đoạn ngắn (`SUMMARY_CHUNK_CHARS`), lưu lại `compaction_state.json`.
   * Đặc biệt: Lưu giữ toàn bộ chứng cứ kiểm chứng qua `_verification_ledger(head)` và trạng thái bộ nhớ hiện tại `self.memory.to_summary()`.
   * Giữ lại phần đuôi gần nhất (`tail`) theo ngân sách `TAIL_TOKEN_BUDGET`.
4. Tầng 4 - Compact Tool:
   * Mô hình chủ động gọi công cụ `compact` kèm tham số `focus_topic` để tự kích hoạt quá trình nén Tầng 3 có định hướng chủ đề (`tool_lifecycle.py:122-153`).
5. Tầng 5 - Iterative Update:
   * Trong các lần nén kế tiếp, hệ thống sử dụng prompt `_ITERATIVE_UPDATE_PROMPT` để cập nhật bản tóm tắt cũ với các lượt hội thoại mới, thay vì tóm tắt lại từ đầu từ số không (`loop.py:1705-1707`).

---

## 2. SWARM DAG RUNTIME

### 2.1. Cấu trúc Mô hình Dữ liệu và DAG Node
Tệp nguồn chính: `agent/src/swarm/models.py` (373 dòng) và `agent/src/swarm/task_store.py` (301 dòng).
Mô hình hóa nhiệm vụ trong Swarm:
- `SwarmAgentSpec`: Định nghĩa vai trò của từng tác tử gồm `id`, `role`, `system_prompt`, danh sách trắng công cụ (`tools`), kỹ năng (`skills`), số vòng lặp tối đa (`max_iterations`), thời gian timeout (`timeout_seconds`), và số lần thử lại (`max_retries`).
- `SwarmTask`: Đại diện cho một node trong đồ thị DAG:
  * `depends_on`: Danh sách cố định các task ID thượng nguồn mà task này phụ thuộc vào.
  * `blocked_by`: Danh sách động các task ID thượng nguồn chưa hoàn thành (thu hẹp dần trong quá trình chạy).
  * `input_from`: Bản đồ ánh xạ dữ liệu đầu vào từ task thượng nguồn, ví dụ: `{"fundamental_report": "task-fundamental"}`.
  * `status`: Trạng thái nhiệm vụ (`pending`, `blocked`, `in_progress`, `completed`, `failed`, `cancelled`).
- `SwarmRun`: Thực thể aggregate root quản lý toàn bộ phiên chạy, lưu trữ tại `.swarm/runs/{run_id}/run.json`.

### 2.2. Thuật toán DAG và Phân tầng Tô-pô (Topological Layering)
Tệp nguồn: `agent/src/swarm/task_store.py:158-300`.
- Kiểm tra tính hợp lệ của đồ thị (`validate_dag`):
  * Kiểm tra tính duy nhất của Task ID và Agent ID.
  * Kiểm tra toàn vẹn tham chiếu: Các task trong `depends_on` và `input_from` bắt buộc phải tồn tại trong danh sách task.
  * Phát hiện chu trình (Cycle Detection): Sử dụng thuật toán DFS duyệt đồ thị theo phương pháp tô 3 màu (WHITE = 0, GRAY = 1, BLACK = 2). Nếu gặp một đỉnh màu GRAY, chu trình được phát hiện và ném ngoại lệ kèm theo đường đi chi tiết của chu trình (`task_store.py:222-239`).
  * Kiểm tra quan hệ tổ tiên chặt chẽ (Ancestor Validation): Mọi nguồn dữ liệu khai báo trong `input_from` bắt buộc phải là tổ tiên thực sự trong cây phụ thuộc (`ancestors[task.id]`), ngăn chặn việc lấy dữ liệu chéo giữa các nhánh độc lập (`task_store.py:244-252`).
- Phân tầng Tô-pô bằng thuật toán Kahn (`topological_layers`):
  * Tính bán bậc vào (in-degree) cho tất cả các task.
  * Đưa các task có bán bậc vào bằng 0 vào hàng đợi tầng 1 (`layer 0`).
  * Lần lượt giải phóng các cạnh phụ thuộc để tạo thành các tầng (`layers`) kế tiếp (`task_store.py:256-300`).
  * Kết quả trả về danh sách các tầng: Các task trong cùng một tầng hoàn toàn độc lập và được phép chạy song song; các tầng thực thi tuần tự.

### 2.3. Lập lịch và Thực thi Bất đồng bộ (Asynchronous Scheduling)
Tệp nguồn: `agent/src/swarm/runtime.py:460-717, 922-1104`.
- Luồng điều phối nền: `SwarmRuntime.start_run` khởi chạy tiến trình nền daemon `threading.Thread(name="swarm-{run.id}")` và trả về đối tượng `SwarmRun` ngay lập tức cho caller (`runtime.py:378-386`).
- Thực thi song song trong từng tầng:
  * Trong `_execute_layer`, hệ thống sử dụng `ThreadPoolExecutor(max_workers=self._max_workers)` (`runtime.py:963`).
  * Các task trong tầng được submit đồng thời vào executor.
- Truyền trạng thái giữa các node (`input_from`):
  * Khi một task hoàn thành, bản tóm tắt kết quả được lưu vào bộ nhớ `task_summaries[tid] = result.summary`.
  * Trước khi điều phối task hạ nguồn, hệ thống trích xuất bản tóm tắt tương ứng theo cấu hình `task.input_from`:
    ```python
    upstream: dict[str, str] = {}
    for context_key, source_task_id in task.input_from.items():
        if source_task_id in task_summaries:
            upstream[context_key] = task_summaries[source_task_id]
    ```
  * Dữ liệu này được chuyển cho `run_worker`, ghép trực tiếp vào biến `{upstream_context}` của System Prompt hoặc Prompt Template của tác tử hạ nguồn.

### 2.4. Cô lập Thất bại và Cổng Chặn Phụ thuộc (Failure Containment & Gating)
Tệp nguồn: `agent/src/swarm/runtime.py:977-1015`.
- Cơ chế Dependency-Aware Gating (Phòng vệ an toàn tối quan trọng):
  * Trước khi dispatch một task, hệ thống quét toàn bộ các task trong `task.depends_on`.
  * Nếu có bất kỳ task thượng nguồn nào không ở trạng thái `completed` (bị lỗi, bị hủy, hoặc timeout), task hiện tại lập tức bị đánh dấu `TaskStatus.blocked` và phát sự kiện `task_blocked` (`runtime.py:997-1014`).
  * Task này tuyệt đối không được gửi sang worker. Điều này ngăn chặn tình huống một task hạ nguồn (ví dụ: Portfolio Manager) tự ý ra quyết định mà thiếu mất báo cáo của cơ quan rủi ro (Risk Officer) thượng nguồn.
  * Các task độc lập khác trong cùng tầng không phụ thuộc vào nhánh lỗi vẫn tiếp tục chạy bình thường.
- Cơ chế Thử lại Tác tử có phân tán độ trễ (Retry with Equal-Jitter Exponential Backoff):
  * Mỗi task được cấu hình `max_retries` (mặc định 1 đến 2 lần).
  * Hàm `_worker_retry_delay_s` (`runtime.py:70-78`) áp dụng công thức Equal-Jitter:
    `delay = random.uniform(ceiling / 2, ceiling)` với `ceiling = min(base * 2^(retry-1), max_delay)`.
  * Cơ chế này làm tản đều áp lực gọi API giữa các worker chạy song song khi gặp sự cố mạng hoặc rate-limit.
  * Xóa sạch thư mục artifact trước khi thử lại (`clear_agent_artifacts` tại `runtime.py:1201-1203`) nhằm loại bỏ hoàn toàn các tệp rác hoặc tệp báo cáo dở dang do lần chạy trước để lại.
- Hạn chót tầng cứng (Hard Layer-Level Deadline):
  * `layer_deadline = layer_budget + 60` giây (`runtime.py:1064-1096`). Nếu một tiến trình worker bị treo trong mã C hoặc socket không giải phóng, `FuturesTimeoutError` sẽ kích hoạt hủy bỏ future và gắn nhãn `timeout`, ngăn ngừa toàn bộ Swarm bị treo vô thời hạn.

### 2.5. Checkpoint, Lưu trữ và Khôi phục (Resume Overlay)
Tệp nguồn: `agent/src/swarm/store.py` và `agent/src/swarm/runtime.py:732-867`.
- Lưu trữ nguyên tử (Atomic File Writing): Mọi thao tác ghi tệp `task-{id}.json` và `run.json` đều ghi ra tệp tạm `.tmp` có gắn chuỗi UUID ngẫu nhiên trước khi thay thế (`replace_with_retry`), chống tranh chấp ghi đồng thời (`task_store.py:60-64`).
- Đồng bộ định kỳ (Snapshot Sync): Tại mỗi ranh giới tầng (`layer boundary`), toàn bộ trạng thái của các task được nạp và cập nhật ngược vào `run.json` (`runtime.py:682, 718-731`).
- Tính năng phục hồi và tiếp tục chạy tiếp (Resume Overlay):
  * Khi gọi `start_run(..., resume_from=prior_run)`:
  * Hệ thống so sánh định nghĩa của từng task và agent spec (`_task_definition_changed` tại `runtime.py:221-265`).
  * Nếu một task đã hoàn thành ở lần chạy trước và không có sự thay đổi nào về code, system prompt, công cụ, model, hoặc dependency: kết quả, bản tóm tắt và toàn bộ tệp artifact của task đó được copy sang run mới (`_rehome_artifact_paths` tại `runtime.py:114-198`).
  * Hệ thống chỉ thực thi lại các task bị lỗi, bị hủy hoặc các task hạ nguồn bị ảnh hưởng, tiết kiệm chi phí token và thời gian tính toán.
- Tiền nạp dữ liệu nền tảng (Grounding Pre-fetch): Trước khi chạy các tầng, hệ thống quét mã chứng khoán trong biến người dùng (`extract_symbols_from_user_vars`) và tải trước dữ liệu nến OHLCV gần nhất gắn vào `run.grounding_data` (`runtime.py:869-921`), chuyển thành khối văn bản "Ground Truth" cho toàn bộ worker.

---

## 3. MULTI-ROLE COUNCIL DEBATE MECHANISM

Hệ thống triển khai cơ chế Hội đồng đa vai trò (Council) ở hai phân hệ:
1. Giao dịch Ngoại hối/Hàng hóa (Forex/Gold XAU/USD): `agent/src/trading/forex/council.py` và `council_context.py`.
2. Đầu tư Cổ phiếu Việt Nam: `agent/src/swarm/presets/vietnam_equity_council.yaml` kết hợp `agent/src/tools/council_contract.py` và `research_council_tool.py`.

### 3.1. Sáu Vai trò Hội đồng Cốt lõi (Council Roles)
Được chuẩn hóa nghiêm ngặt theo đặc tả tài chính thể chế:

| Tên vai trò (Forex) | Tên vai trò (Cổ phiếu VN) | Trách nhiệm chuyên môn cốt lõi | Quyền Veto |
|---|---|---|---|
| `technical` | `technical_analyst` | So sánh đa khung thời gian (M5, H1, H4, D1), xác định hỗ trợ/kháng cự, xu hướng, chỉ báo động lượng (RSI, ATR, MA), mô hình nến đã đóng. Không được bịa đặt mô hình. | Tư vấn (Advisory) |
| `macro` | `fundamental_analyst` | Định giá cơ bản, phân tích báo cáo tài chính, doanh thu, lợi nhuận, dòng tiền, định giá P/E, P/B; hoặc phân tích DXY, lợi suất thực trái phiếu Mỹ (Real Yields), dòng tiền ETF vàng (GLD). | Tư vấn (Advisory) |
| `bull` | `bull_advocate` | Xây dựng luận điểm mua (BUY/LONG) mạnh nhất có thể bảo vệ được kèm theo bằng chứng cụ thể; xác định chất xúc tác (catalyst) và điều kiện vô hiệu hóa (invalidation). | Tư vấn (Advisory) |
| `bear` | `bear_advocate` | Tấn công luận điểm mua, tìm kiếm lỗ hổng dữ liệu, xây dựng luận điểm bán/tránh (SELL/AVOID), định lượng rủi ro sụt giảm (downside scenarios). | Tư vấn (Advisory) |
| `risk` | `risk_officer` | Phản biện độc lập cả hai bên Bull và Bear. Định lượng VaR, CVaR, Max Drawdown, biến động, kiểm tra trượt giá và chênh lệch spread. Phủ quyết nếu bằng chứng yếu hoặc tín hiệu mâu thuẫn. | **Cưỡng chế Tuyệt đối (Hard Veto)** |
| `manager` | `portfolio_manager` | Tổng hợp toàn bộ các báo cáo, giải trình phản biện của giám đốc rủi ro, đưa ra quyết định cuối cùng (BUY, SELL hoặc WAIT). Không được ép buộc đồng thuận hoặc vượt quyền Veto. | **Cưỡng chế Tuyệt đối (Hard Veto)** |

### 3.2. Cấu trúc Tranh luận và Thứ tự Lượt (Turn Order & Rebuttal Cycles)
Tệp nguồn: `agent/src/trading/forex/council.py:176-184, 403-468`.
Quy trình phản biện được chia thành 4 giai đoạn bắt buộc:
```
STAGES = (
    ("technical", "macro"),    # Giai đoạn 1: Phân tích độc lập song song
    ("bull", "bear"),          # Giai đoạn 2: Tranh luận đối kháng song song
    ("risk",),                 # Giai đoạn 3: Phản biện & Kiểm soát rủi ro độc lập
    ("manager",)               # Giai đoạn 4: Tổng hợp & Phán quyết cuối cùng
)
```

1. Giai đoạn 1 (Thu thập bằng chứng khách quan):
   - `technical` và `macro` chạy song song (`max_workers=2`).
   - Hai vai trò này chỉ quan sát dữ liệu thị trường thực tế (OHLCV, sổ lệnh, dữ liệu vĩ mô) và đưa ra các đánh giá kỹ thuật/cơ bản độc lập.
2. Giai đoạn 2 (Tranh biện đối kháng):
   - `bull` và `bear` chạy song song (`max_workers=2`).
   - Cả hai vai trò đều được nạp báo cáo từ Giai đoạn 1 (`report.technical`, `report.macro`).
   - Từng bên xây dựng 5 luận điểm đối trọng nhau, bảo đảm không bên nào bỏ qua các dữ kiện bất lợi.
3. Giai đoạn 3 (Phản biện và Kiểm soát Rủi ro):
   - `risk` chạy tuần tự sau khi có báo cáo của Bull và Bear.
   - Kiểm tra mã nguồn ép buộc: Báo cáo rủi ro bắt buộc phải trích dẫn tham chiếu cả hai báo cáo `report.bull` và `report.bear`:
     `if role == "risk" and not {"report.bull", "report.bear"} <= set(opinion.evidence_refs): raise RoleOutputError("INVALID_EVIDENCE_REFS")` (`council.py:444-445`).
   - Vai trò rủi ro đánh giá tính tương thích của thời điểm vào lệnh (`market` vs `limit`), rủi ro tin tức và độ tin cậy của bằng chứng.
4. Giai đoạn 4 (Phán quyết và Tổng hợp):
   - `manager` chạy tuần tự cuối cùng.
   - Bắt buộc phải tham chiếu báo cáo rủi ro:
     `if role == "manager" and "report.risk" not in opinion.evidence_refs: raise RoleOutputError("INVALID_EVIDENCE_REFS")` (`council.py:446-447`).
   - Cân nhắc toàn diện và đưa ra phán quyết.

### 3.3. Giao thức Đồng thuận, Bỏ phiếu và Xử lý Xung đột
Tệp nguồn: `agent/src/trading/forex/council.py:161-173, 468-477` và `agent/src/tools/council_contract.py:541-850`.
Hệ thống loại bỏ hoàn toàn cơ chế bỏ phiếu đa số giản đơn (Simple Majority Voting) vì nguy cơ "ảo giác tập thể". Thay vào đó, áp dụng cơ chế Cổng kiểm soát phân tầng (Hierarchical Gated Consensus):
- Quyền phủ quyết của Risk Officer:
  * Nếu `risk.veto == True` hoặc `risk.stance == "wait"`: Khuyến nghị cuối cùng lập tức bị cưỡng chế thành `"wait"`, bất kể các vai trò khác đều bỏ phiếu Mua hay Bán (`council.py:470-471`).
- Ràng buộc giữa Quản lý và Rủi ro:
  * Nếu `manager` chọn lệnh thị trường (`entry_mode == "market"`) nhưng `risk` chỉ phê duyệt lệnh chờ (`entry_mode == "limit"`): Kế hoạch bị từ chối với lý do `ENTRY_TIMING_NOT_APPROVED` và chuyển về `wait` (`council.py:472-475`).
  * Nếu `manager.stance` mâu thuẫn với `risk.stance` (khi risk không ở trạng thái wait): Kế hoạch không thể ở trạng thái `ready`.
- Tính toàn vẹn 100% của Hội đồng:
  * Nếu bất kỳ vai trò nào trong 6 vai trò gặp lỗi (lỗi mạng, sai schema, JSON hỏng, quá dài, hoặc trích dẫn bằng chứng không hợp lệ), task đó được ghi nhận vào `failures` và kế hoạch bị chuyển sang trạng thái `blocked` (`council.py:461-467, 519`). Không chấp nhận một kế hoạch thiếu vắng bất kỳ tiếng nói phản biện nào.
- Tính toán Kịch bản bằng Thuật toán Mã nguồn (Deterministic Scenario Generation):
  * Mô hình ngôn ngữ tuyệt đối không được tự bịa ra mức giá Entry, Stop Loss, hay Take Profit.
  * Hàm `candidates()` (`council.py:268-295`) sử dụng giá Bid/Ask thực từ sàn và biên độ nến ATR (`atr_14`) trên khung M5 để tính toán tự động 4 kịch bản chuẩn (`buy_market`, `buy_limit`, `sell_market`, `sell_limit`).
  * Tỷ lệ Reward/Risk được ép buộc tối thiểu 2.0 (`reward >= loss * 2`).
  * Mức giá SL/TP bắt buộc phải làm tròn chuẩn xác theo bước giá của sàn (`price_step`) và vượt khoảng cách dừng tối thiểu (`minimum_stop_distance`).

### 3.4. Cơ chế Ghi nhận Ý kiến Bất đồng (Dissent Recording)
- Mọi ý kiến phản biện và kịch bản đối lập đều được lưu giữ vĩnh viễn:
  * Trong `TradePlan`, trường `reports` lưu trữ đầy đủ toàn bộ 6 báo cáo chi tiết của từng vai trò, bao gồm cả các luận điểm chống đối (`counterargument`), căn cứ bằng chứng (`evidence_refs`), và dự báo (`forecast`).
  * Trường `scenarios` luôn luôn lưu trữ cả 2 kịch bản: Kịch bản khuyến nghị và Kịch bản đối lập (Opposing scenario). Kịch bản đối lập luôn được cấu hình dưới dạng lệnh chờ có điều kiện (`limit`), giúp nhà đầu tư chuẩn bị sẵn kế hoạch phòng ngừa khi thị trường đi ngược kỳ vọng.
  * Tệp `artifacts/forex_trade_plan.json` và `artifacts/forex_council_evidence.json` được ghi nhận lại toàn bộ chứng cứ để kiểm tra sau phiên.

---

## 4. AI RESPONSE QUALITY & TRUST ARCHITECTURE

Phân hệ độ tin cậy và kiểm soát chất lượng phản hồi nằm tại `agent/src/agent/grounding/` (11 tệp, hơn 400KB mã nguồn), đóng vai trò là "Cổng kiểm soát an toàn" (Safety Gate) cuối cùng trước khi bất kỳ ký tự nào được phát hành đến người dùng.

### 4.1. Sổ cái Kiểm chứng (Grounding Ledger)
Tệp nguồn: `agent/src/agent/grounding/ledger.py` (477 dòng).
`GroundingLedger` là một Facade tích hợp các Mixin:
- `_IdentityMixin` (`identity.py`): Quản lý máy trạng thái danh tính thực thể (Symbol/Company identity).
- `_EvidenceMixin` (`evidence.py`): Quản lý bằng chứng số liệu thu thập từ các công cụ.
- `_PolicyMixin` (`policies.py`): Triển khai các quy tắc kiểm tra tính hợp lệ của số liệu.
- `_SourceMixin` (`sources.py`): Quản lý danh bạ nguồn tin và cơ chế gán nhãn trích dẫn `[S#]`.
- `_ReleaseMixin` (`release.py`): Quản lý quy trình giải phóng phản hồi, tự động sửa lỗi và cắt gọt số liệu không kiểm chứng.

Quy trình vận hành:
1. Nạp bằng chứng nguyên bản: Mỗi khi một công cụ thực thi xong, `AgentLoop` gọi `ingest_tool_result()` chuyển toàn bộ kết quả thô vào `GroundingLedger` trước khi kết quả đó bị cắt ngắn cho LLM xem.
2. Lưu trữ vết kiểm toán nguyên tử: Toàn bộ sổ cái được ghi vào `artifacts/grounding_evidence.json` (`ledger.py:448-477`), lưu giữ đầy đủ mã băm SHA-256 của từng bản thảo câu trả lời, danh sách kiểm tra đã kích hoạt, các số liệu vi phạm và các số liệu được thông qua (`passed_figures`).

### 4.2. Cơ chế Truy xuất Nguồn gốc Trích dẫn (Citation Traceability)
Tệp nguồn: `agent/src/agent/grounding/sources.py` (978 dòng).
Hệ thống thiết lập một hệ thống danh mục nguồn uy tín phân tầng tĩnh (`SOURCE_POLICIES`):
- Tầng 1 (Official Exchanges, Regulators, Central Banks):
  * Việt Nam: Sở Giao dịch Chứng khoán TP.HCM (HOSE - `hsx.vn`, `hose.vn`), Sở Giao dịch HNX (`hnx.vn`), UPCoM, Ủy ban Chứng khoán Nhà nước (UBCKNN - `ssc.gov.vn`), Tổng công ty Lưu ký và Bù trừ Chứng khoán (VSDC - `vsdc.vn`), Ngân hàng Nhà nước Việt Nam (SBV - `sbv.gov.vn`), Tổng cục Thống kê (NSO/GSO - `nso.gov.vn`), Bộ Tài chính (`mof.gov.vn`).
  * Toàn cầu & Mỹ: SEC EDGAR (`sec.gov`), Cục Dự trữ Liên bang Mỹ (Federal Reserve), CSDL Kinh tế FRED (`fred.stlouisfed.org`), Cục Thống kê Lao động Mỹ (BLS), Cục Phân tích Kinh tế (BEA), ECB, BOE, BOJ, CFTC, CME Group, Hiệp hội Vàng Luân Đôn (LBMA), Hội đồng Vàng Thế giới (World Gold Council).
  * Trung Quốc & Hồng Kông: CNINFO, Sở GDCK Thượng Hải (SSE), Sở GDCK Thâm Quyến (SZSE), Sở GDCK Hồng Kông (HKEX), CSRC, PBOC, Tổng cục Thống kê TQ (NBS).
- Tầng 2 (Wire Services & Flagship Financial Press):
  * Reuters, Bloomberg, Financial Times, Wall Street Journal, CNBC, Barron's, Caixin, South China Morning Post (SCMP), Associated Press, Nikkei, The Economist.
- Tầng 3 (Licensed Financial Data & Institutional Research):
  * FiinGroup/FiinPro X (`fiingroup.vn`), Vietstock DataFeed (`data.vietstock.vn`), LSEG, FactSet, S&P Global, Wind, Trading Economics, Koyfin, Morningstar, CoinGecko, CoinGlass, Glassnode, CryptoQuant, DefiLlama, Dune, Token Terminal.
- Tầng 4 (Brokerage Research & Established Financial Media):
  * Bộ phận Nghiên cứu của các Công ty Chứng khoán hàng đầu: SSI Research, Vietcap, VCBS, TCBS, HSC, MBS, BSC, VNDirect, Mirae Asset, KIS Vietnam, DSC.
  * Cơ quan báo chí kinh tế tài chính chính thống: VnEconomy, CafeF, Người Quan Sát, Báo Đầu tư, VnExpress, VietnamNet, Dân trí, Bnews, Vietstock, Thời báo Kinh tế Sài Gòn, Báo Đầu tư Chứng khoán.
  * Quốc tế: Eastmoney, Sina Finance, MarketWatch, Yahoo Finance, Forbes, Investing.com.
- Tầng 5 (Unverified / Unknown / Social Media):
  * Mạng xã hội: X/Twitter, Reddit, Facebook, Telegram, YouTube, Medium, Substack... Mọi thông tin từ đây bắt buộc bị dán nhãn "unverified" và không bao giờ được coi là nguồn chứng thực độc lập.

Quy trình gán nhãn và kiểm tra trích dẫn:
- Khi một công cụ đọc web hoặc tin tức trả về nội dung, hệ thống trích xuất URL, phân giải tên miền vào danh mục `SOURCE_POLICIES`, tạo bản ghi `SourceRecord` kèm băm nội dung và cấp mã định danh duy nhất `[S1]`, `[S2]`...
- Mã này được gắn vào trường `_sources` trong kết quả công cụ trả về cho LLM (`tool_lifecycle.py:975-980`).
- Khi LLM viết câu trả lời, mô hình trích dẫn `[S#]`.
- Tại cổng kiểm chứng, hàm `_validate_figures` kiểm tra quy tắc `figure-cited`: Số liệu được trích dẫn bắt buộc phải xuất hiện thực tế trong văn bản của nguồn tin đó (`value_in_source`). Nghiêm cấm việc mô hình tự bịa ra một con số rồi gắn thẻ `[S1]` giả mạo.

### 4.3. Rào chắn Chống Ảo giác và Kiểm tra Tính Hợp lý Số học (Anti-Hallucination Guardrails)
Tệp nguồn: `agent/src/agent/grounding/figures.py` và `agent/src/agent/grounding/policies.py`.
Hệ thống sử dụng cơ chế Khối Khai báo Số liệu (Figures Declaration Block):
- Khi hoàn thành phân tích, LLM bắt buộc phải chèn một khối khai báo ở cuối câu trả lời theo cú pháp:
  ```
  ```figures
  value | role | note | ref
  ```
  ```
- Định nghĩa 5 vai trò số liệu (`role`):
  1. `observed`: Con số quan sát trực tiếp từ thị trường (ví dụ giá đóng cửa, khối lượng). Cổng kiểm tra bắt buộc giá trị này phải khớp với bảng số liệu thực tế trong dung sai cho phép 0.5% (`_TOLERANCE = 0.005`) (`policies.py:105, 1693`).
  2. `derived`: Con số được tính toán thông qua công thức (ví dụ tỷ lệ Sharpe, phần trăm thay đổi, P/E). Mô hình bắt buộc phải ghi rõ biểu thức số học trong cột `note` (ví dụ: `(63000 - 60000) / 60000`). Cổng kiểm chứng phân tích biểu thức toán học qua bộ AST parser và đối chiếu các toán hạng với số liệu thực tế đã quan sát (`policies.py:2209`).
  3. `proposed`: Mức giá đề xuất giao dịch (Entry, Stop Loss, Take Profit). Cổng kiểm tra đối chiếu với các kịch bản hợp lệ của hệ thống và các quy tắc quản trị rủi ro (`policies.py:2274`).
  4. `cited`: Số liệu trích dẫn từ bài báo hoặc báo cáo phân tích bên ngoài. Bắt buộc phải có mã nguồn hợp lệ trong cột `note` và con số phải tồn tại trong văn bản nguồn thu thập được (`policies.py:2390`).
  5. `bare`: Các số đếm, số nguyên thông thường hoặc chu kỳ (ví dụ "chu kỳ 20 phiên").
- Các bài kiểm tra độc lập đăng ký qua `@grounding_check`:
  * `undeclared-figure`: Quét toàn bộ văn bản câu trả lời bằng Regex để tìm các con số có hình dạng đo lường (giá cả, phần trăm, tỷ lệ). Nếu phát hiện một con số xuất hiện trong văn bản mà không được khai báo trong khối `figures`, bản thảo bị đánh trượt ngay với lỗi `figure_undeclared` (`policies.py:680`).
  * `unsourced-symbol-figures`: Phát hiện một con số đo lường đi kèm một mã chứng khoán mà phiên chạy chưa từng thu thập dữ liệu (`figures_checks.py:63-100`).
  * `chart-observed-payload`: Nếu câu trả lời có chứa khối biểu đồ ````chart ... ````, nội dung payload bắt buộc phải khớp 100% với một trong các biểu đồ do công cụ thị trường trả về (`_trusted_chart_payloads`). Ngăn chặn hoàn toàn việc mô hình tự bịa tọa độ nến biểu đồ (`figures_checks.py:48-60`).
  * `listed-identity-relabelled-private`: Ngăn chặn việc mô hình tự ý tuyên bố một công ty niêm yết là công ty tư nhân chưa niêm yết (`identity_checks.py:25-56`).
  * `provenance-checks`: Ép buộc câu trả lời tài chính bắt buộc phải thể hiện rõ: Mã chứng khoán chuẩn hóa (`canonical-symbol-surfaced`), Nguồn cung cấp dữ liệu (`data-source-surfaced`), và Đơn vị tiền tệ niêm yết (`quote-currency-surfaced`).

### 4.4. Quy trình Tự động Sửa lỗi, Hiệu đính và Cắt gọt Phản hồi (Correction, Repair & Redaction)
Tệp nguồn: `agent/src/agent/grounding/release.py` và `agent/src/agent/loop_grounding.py`.
Khi một bản thảo câu trả lời bị từ chối bởi cổng kiểm chứng, hệ thống thực thi chu trình xử lý có ngân sách nghiêm ngặt:
1. Tự động sửa lỗi xác định (Deterministic Repair):
   * Trước khi từ chối, hệ thống thử tự động sửa lỗi kỹ thuật nhỏ: tự động bổ sung tham chiếu trường (`repair_unique_field_refs`), tự động bổ sung trích dẫn nguồn trên cùng dòng (`repair_citation_visibility`), hoặc tự động chèn chú thích nguồn/tiền tệ bị thiếu (`repair_provenance`) (`loop_grounding.py:77-98`).
2. Lượt hiệu đính mô hình (Model Revision Round):
   * Ngân sách tối đa: `MAX_GROUNDING_REVISIONS = 2` lượt.
   * Lần vi phạm đầu tiên: Bản thảo bị giữ lại. Hệ thống tạo một System Prompt hiệu đính (`correction_prompt` tại `release.py:181-187`), liệt kê chi tiết:
     - Các con số đã vượt qua kiểm định (yêu cầu giữ nguyên).
     - Các con số bị lỗi, lý do sai phạm cụ thể và dải giá trị thực tế quan sát được trong cơ sở dữ liệu.
   * Mô hình được cấp một lượt chạy văn bản thuần (`grounding_correction_text_only = True`) để chỉnh sửa lại số liệu dựa trên bằng chứng đã có.
3. Giải phóng cắt gọt có kiểm soát (Redacted Release - Cứu nguy bản thảo):
   * Nếu sau 2 lượt hiệu đính mà mô hình vẫn không khắc phục hết các lỗi số liệu, hệ thống không vứt bỏ toàn bộ phân tích công phu của mô hình.
   * Hàm `redacted_release()` (`release.py:223-252`) tự động rà quét và cắt bỏ các con số vi phạm, thay thế bằng dấu ký hiệu lược bỏ địa phương hóa:
     - Tiếng Việt: `(đã lược※)`
     - Tiếng Anh: `(omitted※)`
     - Tiếng Trung: `（略※）`
   * Kèm theo một chú thích chân trang duy nhất giải thích rằng các con số trên đã bị hệ thống lược bỏ vì không vượt qua được kiểm chứng độc lập với dữ liệu sàn.
   * Bản thảo sau khi cắt gọt được đưa qua cổng kiểm định lại (`revalidate`). Nếu hợp lệ, phản hồi được giải phóng ra ngoài.
4. Fallback An toàn Tuyệt đối (Safe Fallback):
   * Nếu việc cắt gọt vẫn thất bại hoặc vi phạm danh tính thực thể, hệ thống trả về phản hồi từ chối chuẩn mực (`safe_fallback`), ngăn chặn 100% việc để lọt thông tin giả mạo đến người dùng hoặc gửi tín hiệu giao dịch rủi ro.

---

## 5. BẢNG TỔNG HỢP SO SÁNH VÀ ĐÁNH GIÁ CHUYÊN SÂU

| Tiêu chí Đánh giá | Trạng thái Hiện tại | Bằng chứng Mã nguồn | Đánh giá Mức độ Thể chế (CFA / Institutional Grade) |
|---|---|---|---|
| Ngăn chặn Vòng lặp Vô hạn (Infinite Loop) | Rất mạnh | `loop.py:574, 632, 1266` (Max iterations, wrap-up at 80%, Stall watchdog) | Đạt chuẩn Production. Ngăn ngừa hoàn toàn rủi ro tiêu hao token hoặc treo tiến trình. |
| Quản lý Hạn mức Ngữ cảnh | Xuất sắc | `loop.py:1457-1489`, `context_compact.py` (5-layer compaction, transactional summary) | Đạt chuẩn hàng đầu. Lưu giữ transcript và verification ledger khi nén ngữ cảnh. |
| Độ tin cậy Thực thi Đồ thị DAG | Rất mạnh | `runtime.py:977`, `task_store.py:206` (Kahn topological sort, 3-color DFS, dependency gating) | Đạt chuẩn thể chế. Task hạ nguồn tự động khóa (`blocked`) nếu task thượng nguồn gặp lỗi. |
| Phản biện Đa chiều và Quyền Phủ quyết | Xuất sắc | `council.py:161, 184, 468` (4 stages, 6 roles, Risk & Manager hard veto) | Đạt chuẩn Hội đồng Đầu tư thực tế. Loại bỏ cơ chế bỏ phiếu đa số ngây thơ. |
| Tách biệt Tính toán và Suy luận | Hoàn hảo | `council.py:268` (`candidates()` dùng ATR và quote sàn, mô hình chỉ chọn kịch bản) | Tuân thủ tuyệt đối quy tắc: Mã nguồn làm toán, AI làm nhận định định tính. |
| Kiểm soát Ảo giác Số liệu Thị trường | Xuất sắc | `ledger.py:418`, `policies.py:1693` (Figures block declaration, 0.5% tolerance) | Đạt chuẩn kiểm toán tài chính nghiêm ngặt nhất hiện nay trên các nền tảng Trading AI. |
| Truy vết Nguồn gốc và Trích dẫn | Rất mạnh | `sources.py:95` (Danh mục nguồn 5 tầng: Sở GDCK, Cơ quan quản lý, Hãng tin, CTCK) | Đạt chuẩn CFA Institute về việc trích dẫn nguồn dữ liệu chính thống. |

---

## 6. ĐIỂM YẾU, RỦI RO TIỀM ẨN VÀ ĐỀ XUẤT NÂNG CẤP KIẾN TRÚC

Qua quá trình rà soát chi tiết từng dòng lệnh, các rủi ro kỹ thuật sau đây cần được lưu ý và khắc phục:

1. **Rủi ro Đồng bộ Trạng thái khi có Hủy bỏ (Cancellation Race Condition)**:
   - Vị trí: `agent/src/swarm/runtime.py:1071-1096`.
   - Phân tích: Khi lệnh `cancel_run()` được phát động hoặc xảy ra `FuturesTimeoutError`, hàm `executor.shutdown(wait=False, cancel_futures=True)` được gọi. Tuy nhiên, các luồng Python đang chạy dở bên trong worker thread không thể bị cưỡng chế dừng ngay lập tức nếu đang chờ socket mạng I/O chặn (blocking network I/O).
   - Đề xuất: Bổ sung cờ kiểm tra `cancel_event.is_set()` thường xuyên hơn bên trong các adapter gọi mạng (network connectors) và client LLM (`ChatLLM.stream_chat`), tương tự như cơ chế hợp tác đã làm ở `AgentLoop`.

2. **Dung sai Số liệu Cố định (Fixed 0.5% Tolerance)**:
   - Vị trí: `agent/src/agent/grounding/policies.py:105` (`_TOLERANCE = 0.005`).
   - Phân tích: Mức dung sai 0.5% là lý tưởng cho cổ phiếu thị giá thông thường. Tuy nhiên, đối với các loại tài sản có bước giá lớn (như hợp đồng tương lai chỉ số VN30F hoặc hàng hóa), hoặc các cổ phiếu penny giá thấp (ví dụ cổ phiếu giá 2.000 VND thì 0.5% chỉ là 10 VND, bằng đúng 1 bước giá), việc làm tròn của mô hình có thể vô tình kích hoạt lỗi từ chối số liệu.
   - Đề xuất: Cho phép cấu hình dung sai thích ứng (`adaptive tolerance`) dựa trên thuộc tính `tick_size / price` của từng công cụ cụ thể.

3. **Cơ chế Hồi phục sau Nén cho Công cụ Có Tham số (Replay Cache Parametrization)**:
   - Vị trí: `agent/src/agent/loop.py:257-268` và `tool_lifecycle.py:206-255`.
   - Phân tích: Cơ chế Replay sau khi nén ngữ cảnh hoạt động rất tốt với các lời gọi công cụ đơn lẻ, nhưng giới hạn `MAX_READONLY_REPLAY_RECOVERIES = 6` có thể bị cạn kiệt nếu một phiên phân tích so sánh danh mục chứa hơn 10 mã chứng khoán đồng thời.
   - Đề xuất: Nâng ngưỡng ngân sách hồi phục tỷ lệ thuận với số lượng mã chứng khoán được yêu cầu trong đề bài (`session_symbols`).

---

## 7. KẾT LUẬN

Kiến trúc Agent và Quy trình Suy luận AI của Vibe-Trading thể hiện tư duy thiết kế hệ thống cấp cao (System Architect Grade), giải quyết triệt để các bài toán khó nhất của AI trong tài chính:
1. Đập tan vấn đề ảo giác số liệu bằng Cổng kiểm chứng hai lớp (Khối khai báo + Xác thực sổ cái).
2. Kiểm soát chặt chẽ ngân sách ngữ cảnh và chu kỳ sống của tác tử bằng Vòng lặp ReAct 5 tầng và Stall Watchdog.
3. Bảo đảm an toàn giao dịch thể chế bằng Hội đồng Phản biện 6 vai trò có quyền Phủ quyết thực thi và tách rời hoàn toàn phép toán giá ra khỏi mô hình ngôn ngữ.

Toàn bộ hệ thống sẵn sàng đáp ứng các tiêu chuẩn khắt khe của CFA Institute và sẵn sàng cho việc mở rộng sang các luồng dữ liệu thời gian thực cho Equities và Hàng hóa (XAU/USD).
