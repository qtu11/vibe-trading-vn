# Triển khai đợt 4: nghiên cứu Web, thí nghiệm, Order Book và ngân sách Swarm

Cập nhật **05/11/2026**, checkout `D:/Vibe-Trading`, base Git `f072a046a6ad047835fd1cc2bfc5ebee52c9af6b`. Thực hiện theo yêu cầu tiếp tục code từ master; giữ nguyên các thay đổi local trước đó. Snapshot trước sửa nằm trong `.codex-backups/2026-11-05-implementation-4/`, chia nhóm root/forex/crypto/platform. Không thêm dependency, không commit/publish/deploy.

## Phạm vi đã nối vào caller

| Phần | Hành vi và bằng chứng | Acceptance còn mở |
| --- | --- | --- |
| Web research | Menu → `/research` → hai POST read-auth cố định `/api/research/vietnam`, `/api/research/crypto` → tool hiện có. Có metrics, null/reason, evidence/revision/hash/cutoff, coverage, giới hạn nguồn; paging giữ cutoff và query đổi hủy request/loại kết quả cũ. Bản dịch copy mới en/vi/tr; chín locale còn lại dùng English fallback. | Chưa báo cáo AI có human review/PDF/version workflow, browser visual/runtime acceptance hoặc dữ liệu thật được xác minh. |
| Forex experiment registry | Dùng lại Store SQLite schema4; attempt append-only có request đầy đủ, cost/config/dataset, evaluator/dependency/source hashes thực, kết quả mọi trial/fold/lỗi. API ghi có settings-write auth; MCP mutation chỉ xuất hiện với `--allow-research-writes`. | Chưa total tuning-budget, promote/OOS reuse gate, generic multi-strategy registry hoặc tự recover process chết. |
| Crypto Order Book | Tool `orderbook_depth` và mirrored MCP có offline Binance USD-M snapshot/delta replay. Kiểm snapshot bridge, `pu`, duplicate/stale/delete/cross/nonfinite; invalid không sinh features trước khi có snapshot+bridge mới. Giới hạn 200 events, trace20 mới nhất, status counts đầy đủ và budget output10k. | Chưa WebSocket recorder/reconnect thật, OKX semantics/checksum hoặc archive. Replay là `caller_supplied_unverified`. |
| Swarm call budget | `max_llm_calls` optional qua API/agent tool/main MCP; shared lock cấp slot trước mỗi Swarm `stream_chat`, gồm worker/stream retries. Persist trước dispatch; missing usage giữ unknown, failed/cancelled provider usage vẫn tính. Retry/resume giữ cap nhưng tạo allowance mới cho run mới; legacy counters null. | Chưa giới hạn SDK HTTP retries/internal invoke fallback, token/dollar ceiling, platform AgentLoop hoặc model routing theo benchmark. |

Order Book theo [protocol USD-M chính thức của Binance](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/websocket-market-streams/How-to-manage-a-local-order-book-correctly), đối chiếu ngày05/11: bridge `U <= lastUpdateId <= u`, sau đó `pu == prior u`; quantity là số lượng tuyệt đối, zero xóa level. Không áp dụng nhầm quy tắc spot vào USD-M.

Main inventory giữ **116 keyless agent tools /84 main MCP tools**. Forex MCP OANDA/Exness riêng có **11 read-only**, **14 khi opt-in execution**; research-write opt-in thêm1 độc lập. MT5 có thêm hai research tools hiện hữu. Count theo từng surface, không cộng thành một inventory chung.

Tracker sau đợt này có **30 ID partial_delivered /235 baseline_only**, vẫn đủ265 ID và tất cả acceptance còn mở. `baseline_only` không có nghĩa code hoàn toàn chưa tồn tại. [Tracker](IMPLEMENTATION_TRACKER.md) và [hướng dẫn chạy](MULTI_MARKET_RESEARCH_USAGE.md) nêu phần còn thiếu theo delivery.

## Kiểm chứng

- Hồi quy tích hợp **84 file**: **1.783 passed, 8 skipped, 63 warnings**, artifact `final-regression.xml` và danh sách `regression-tests.json` trong snapshot đợt4. Bao gồm VN/DCF, Crypto, toàn nhóm Forex và Swarm/CLI liên quan, API auth và README inventory; không phải toàn repository suite.
- Frontend **73 passed /4 file**, gồm10 case trang nghiên cứu,7 navigation,10 layout,46 i18n. Artifact `frontend-tests.xml`. Có cảnh báo `act` của Layout và Vite config hiện hữu.
- `npm run build`: TypeScript và Vite production build qua; cảnh báo chunk vendor-charts lớn hơn500kB vẫn còn.
- Tám skip: một optional statsmodels, bảy case symlink không có quyền trên Windows. Năm test mới gặp lỗi quyền được sửa setup để skip đúng `WinError1314`; security assertions giữ nguyên và cần chạy trên host có quyền symlink.
- Rà soát rộng ban đầu phát hiện8 failures: allowlist schema cần chấp nhận cap mới, reader test cần UTF-8, năm setup symlink và lỗi rename đồng thời TaskStore trên Windows. TaskStore nay dùng lại `_replace_with_retry` hiện có của SwarmStore; test concurrent writers qua. Kết quả lỗi ban đầu vẫn giữ tại `platform/regression-tests.xml`, không thay bằng tuyên bố đã qua.
- Các lượt scoped Forex300, Crypto137, Swarm65/84 và API16 trùng phạm vi hồi quy cuối; không cộng vào tổng1.783. Một lượt red test replay đầu tiên chưa mock fetch đủ và đã chạm public REST; final replay/integration dùng fixture, không được mô tả cả phiên là hoàn toàn offline.

Chưa kiểm broker/account/model thật, feed thật, browser screenshot, toàn repository suite hoặc production deployment. Chưa viết vào runtime database/home của người dùng trong kiểm thử. Nguồn BCTC và replay vẫn chưa được xác minh; API Crypto khi người dùng bấm chạy phụ thuộc public provider.

Ruff chưa cài trong `.venv`, nên chưa chạy lint bằng Ruff; không cài thêm dependency cho đợt này. UTF-8/whitespace, internal links, tracker drift và canonical counts được kiểm riêng bằng script local.

## Dữ liệu và rollback

Registry lưu toàn bộ nến caller cung cấp trong Store Forex hiện có `runtime/forex/execution.db`; cần giữ quyền truy cập file đúng người dùng. Đọc Store bằng phiên bản mới có thể nâng schema3→4. Trước chạy trên dữ liệu đang dùng, dừng writers và tạo backup SQLite nhất quán bằng backup API hoặc công cụ tương đương; không copy riêng main DB khi còn WAL đang ghi.

Code cũ từ chối schema4. Rollback registry cần khôi phục backup DB trước upgrade cùng source phù hợp, hoặc migration downgrade đã kiểm thử; thay file source đơn thuần không đủ. Không khôi phục DB cũ nếu đã có broker execution mới kể từ backup mà chưa reconcile: việc đó có thể mất ledger trạng thái lệnh. Không tự drop table/reset user_version hoặc xóa attempt để làm downgrade có vẻ thành công.

Các thay đổi Web/replay/budget có thể review và hoàn nguyên theo snapshot từng file; giữ phần sửa khác của người dùng. Old run JSON được đọc với counters null, cap mặc định None. Không nâng trạng thái phê duyệt của master hay tự cấp quyền live.
