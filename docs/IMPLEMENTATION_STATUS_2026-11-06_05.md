# Triển khai đợt 5: VN comparables, Forex lab/EMA và Crypto archive

Cập nhật **06/11/2026**, checkout `D:/Vibe-Trading`, Git base `f072a046a6ad047835fd1cc2bfc5ebee52c9af6b`. Tiếp tục yêu cầu code từ master; giữ toàn bộ thay đổi local trước đó. Snapshot và bằng chứng ở `.codex-backups/2026-11-06-implementation-5/`, chia root/vn/forex/crypto. Không thêm dependency, không ghi database/config home của người dùng trong kiểm thử, không commit/publish/deploy.

## Phần đã bàn giao

| Luồng | Caller/hành vi đã có | Giới hạn nghiệm thu |
| --- | --- | --- |
| [VN annual P/E và observed P/B](VN_COMPARABLES.md) | `vietnam_comparables` qua agent registry/main MCP/read-auth API; quantlib dùng đúng weighted EPS và book-snapshot BVPS. Strict period/cutoff/price instant/share basis, exclusions và nguồn; hash/summary bao toàn peer set, output có paging. Preset valuation analyst đã nối. | Chưa xác minh nguồn/issuer/corporate actions, justified P/B–ROE, quarterly TTM/calendarization hoặc forecast/report AI có human review. |
| [EMA và Forex Web lab](FOREX_RESEARCH_LAB.md) | Shared request có strategy riêng; EMA causal prefix, seed/warmup và hash rõ, train-only theo fold. `/research` có nhập JSON/file/synthetic example, calculate riêng/save riêng và đọc history/attempts có paging. | Vẫn one-bar mid-price/cost giả định, chưa tick/broker/SL/TP/swap parity hoặc promotion/OOS reuse gate; chưa browser visual acceptance. |
| [Crypto local capture archive](CRYPTO_DERIVATIVES_ARCHIVE.md) | SQLite append-only cấu hình qua Data Bridge; giữ parsed CCXT payload, normalized hashes, record/retrieval time và revisions. Query read-only theo local cutoff kiểm toàn scope manifests/index, conflict/corruption/clock regression fail closed. Có API capture write-auth và UI action riêng. | Local observation time chưa là exchange historical publication time; chưa automated collector, retention/partition service, signed source hoặc raw HTTP archive. |

Main inventory hiện **117 keyless agent tools /85 main MCP tools**; quantlib count theo exported names **310 /24 modules**. Forex MCP riêng giữ **11 read-only /14 execution opt-in**, research-write opt-in cộng1; MT5 có thêm hai tools nghiên cứu hiện hữu. Không cộng các surface thành một inventory.

Tracker có **33 ID partial_delivered /232 baseline_only**, vẫn đủ265 canonical IDs,54 scenarios,10 phases và16 decisions. Tất cả `acceptance_status` vẫn open; baseline_only không có nghĩa không tồn tại code. Các ID mới có phần bổ sung là `VN-110`, `VN-111`, `PLATFORM-007`; các ID còn lại mở rộng delivery hiện có.

## Quyền và những lỗi đã xử lý

Crypto domain tool có `capture`, nên `is_readonly=False`: agent scheduler không được gom nó vào batch parallel reads. Main MCP là wrapper giới hạn `mode: live|archive`, từ chối capture trước registry. Test read-only red line giữ nguyên danh sách sandbox writers; bổ sung kiểm riêng cho wrapper đọc bị giới hạn mode, gồm exact wire enum, direct rejection và FastMCP Client rejection. Không thêm capture vào danh sách mutating tools được xuất qua MCP.

API capture dùng settings-write auth + cross-site gate. UI capture chỉ gửi khi bấm, không dùng read cancellation để giả vờ rollback hoặc tự retry transport failure. Forex save cũng là write riêng; request input bị khóa trong lúc save, lỗi chưa xác định nhắc kiểm history. Đọc archive không tạo/migrate file và không gọi exchange.

Rà soát chéo đã sửa: `{}` của attempt đang running không còn hiện thành evaluation hoàn tất; GET cũ không ghi đè receipt/destination vừa save; tính toán cũ bị hủy/bỏ khi input đổi. API client hiển thị tối đa8 lỗi validation có field path/message bounded, không hiện raw input field của lỗi Pydantic. Archive kiểm cả capture cũ và toàn index trước khi tính first-observed/revision counts, gồm trường hợp index của capture bị mất hoàn toàn.

## Kiểm chứng

Frontend **114 passed /8 file**, gồm lab/import/API client, trang research/capture/archive, Forex hiện hữu, navigation/layout/i18n. `frontend-tests.xml` giữ kết quả. `npm run build` qua TypeScript và Vite; cảnh báo vendor-charts lớn hơn500kB, Vite config và `act` của Layout vẫn còn.

Hồi quy backend cuối dùng **88 file**: **1.960 passed, 8 skipped, 63 warnings**. Danh sách và JUnit tại `regression-tests.json` / `final-regression.xml`. Một skip do optional statsmodels chưa cài, bảy skip do quyền symlink không có trên Windows; chưa coi những ca đó là đã chứng minh bảo vệ filesystem trên host có quyền symlink. Các lượt scoped VN167/1skip, Forex55, Crypto204/121, root API151 và MCP projection123 có test trùng; không cộng thành tổng riêng.

Lượt rộng đầu có1957 passed/1 failed/8 skipped: gate cũ suy quyền MCP chỉ từ cờ domain tool, chưa nhận wrapper chỉ đọc live/archive. Báo cáo lỗi giữ `initial-regression.xml`; gate được bổ sung bằng proof whitelist/rejection thay vì cho phép capture ghi qua MCP. Lượt inventory đầu cũng bắt count quantlib310 và chữ số MCP trong Korean README chưa đồng bộ; đã sửa các README, không bỏ assertion.

Chưa chạy toàn repository suite, broker/account/feed/model thật, browser screenshot hoặc production deployment. Ruff chưa có trong `.venv`, không cài thêm chỉ để lint. Kiểm riêng UTF-8/whitespace/internal links/tracker drift/canonical counts bằng script snapshot; nguồn financial/replay/capture vẫn có giới hạn xuất xứ được nêu rõ.

## Rollback và dữ liệu

Đợt5 không đổi Forex Store schema4; [quy trình backup/reconcile/downgrade đợt4](IMPLEMENTATION_STATUS_2026-11-05_04.md#dữ-liệu-và-rollback) vẫn áp dụng. Không restore DB cũ nếu đã có execution mới chưa reconcile. Registry giữ request strategy chuẩn hóa và source hashes của evaluator/helper từng attempt; không ghi lại attempt cũ chỉ để khớp source mới.

Crypto archive là file riêng do operator cấu hình, không chung Forex DB. Backup SQLite nhất quán trước bảo trì; không sửa hashes/timestamps hoặc xóa captures/index để vượt query bound. Rollback code có thể giữ nguyên archive và ngừng capture; không tự xóa dữ liệu người dùng. Hash/append triggers chưa chống được người có quyền sửa toàn database/hashes. VN comparables không ghi artifact hoặc fetch nguồn; rollback tool/API/preset theo snapshot, giữ phần thay đổi khác của người dùng.
