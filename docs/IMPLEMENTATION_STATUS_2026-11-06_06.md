# Triển khai đợt6: định giá, stress chi phí và research revisions

**Ngày:** 06/11/2026. **Checkout thực tế:** `D:/Vibe-Trading`, baseline commit `f072a046a6ad047835fd1cc2bfc5ebee52c9af6b`. Tiếp tục các thay đổi local chưa commit; không thay thế chúng bằng bản baseline. Yêu cầu chat cho phép code local, không tự phê duyệt live trading, triển khai production hoặc toàn bộ master plan.

Snapshot và bằng chứng kiểm thử đặt tại `.codex-backups/2026-11-06-implementation-6/`. [Tracker265 ID](IMPLEMENTATION_TRACKER.md) hiện có **37 partial_delivered /228 baseline_only**, toàn bộ acceptance vẫn mở. Bốn ID mới có phần thực hiện là `VN-117`, `FX-163`, `PLATFORM-033`, `VN-130`; còn các ID giao nhau giữ phạm vi bổ sung riêng. `baseline_only` không chứng minh toàn bộ capability chưa có source.

## Những luồng đã nối

| Luồng | Source và hành vi | Phần chưa được chứng minh |
| --- | --- | --- |
| VN DCF/sensitivity | [Adapter](../agent/src/tools/vietnam_dcf.py) dùng lại quantlib DCF, full equity bridge và sensitivity; API read-auth và [Web valuation lab](../frontend/src/components/research/VietnamValuationLab.tsx) nối DCF cùng comparables hiện có | Nguồn, forecast, identity/share basis do caller khai; chưa tự thu thập hay xác minh doanh nghiệp thật |
| Forex cost stress | [Evaluator](../agent/src/trading/forex/cost_stress.py) fit walk-forward một lần, khóa OOS tape, spread1×/2×/3× với explicit phí khác giữ nguyên; HTTP, dedicated MCP, registry và UI | Mid-bar, giữ một nến, chi phí giả định; chưa broker-calibrated spread/fees, ticks, swap, SL/TP hoặc gap replay |
| Research revisions | [Service](../agent/src/research_artifacts/service.py) chỉ dispatch3 engine cố định, chạy lại input rồi append request/result/producer/source/facts hashes vào [SQLite store](../agent/src/research_artifacts/store.py) riêng | Snapshot một page/scenario; chưa AI narrative/PDF, failed-refresh stale ledger, idempotency hoặc narrative claim graph |
| Delta và review | API/Web xem lịch sử, parent, field diff và affected VN ratio dependencies; append acknowledged/changes_requested với note và self-reported operator label | Review chưa có danh tính người thật/role separation hoặc xác minh nguồn độc lập; verification luôn user_supplied_unverified |

[Hướng dẫn DCF/sensitivity](VN_DCF_SENSITIVITY.md), [Forex lab/cost stress](FOREX_RESEARCH_LAB.md), [revision API/storage/review](RESEARCH_REVISIONS.md) và [luồng tổng hợp](MULTI_MARKET_RESEARCH_USAGE.md) mô tả request và fixture thực tế. Các ví dụ đều là synthetic; nạp ví dụ không tự gọi API, tính không tự lưu.

## Các ranh giới tính toán và lưu

DCF chỉ nhận consolidated non-financial FCFF bằng VND. Scale chỉ nhân tiền; shares là actual count. Forecast1–10 năm tương đối đủ năm, assumptions có basis/source IDs, debt/cash/restricted cash/minority/preferred/associates tách riêng. Restricted cash không cộng vào equity. Hai trục tối đa9×9; `g >= WACC` cho null/reason. Grid luôn perpetuity-growth kể cả base chọn exit multiple; không gán xác suất. Bridge/scale/DCF parity được kiểm qua engine hiện có, không dựng một công thức định giá khác trong UI.

Forex yêu cầu spread/commission/slippage/gap cộng đúng base round-trip cost. Chỉ spread nhân1/2/3; không fit/rerank lại tín hiệu cho từng scenario. Shared tape hash nhận diện cùng gross outcomes. Expectancy và break-even là trung bình số học bps, có thể âm; không gọi là nghiệm compounded equity. Không trade thì expectancy null/reason; base thiếu fold thì aggregate null; bankruptcy khi tăng phí giữ arithmetic evidence nhưng compounded return null. `gap_bps` chỉ fixed adverse charge.

Research store chỉ lưu kết quả server `ok: true`, không nhận client result, tool name hoặc path tùy ý. Parent và diff phải cùng kind/scope. Listing/read không tạo database; append và review dùng writer transaction. SQL triggers chặn update/delete; đọc kiểm hash/binding. Người có toàn quyền sửa database và tính lại hashes vẫn có thể giả mạo dữ liệu; chưa có chữ ký nguồn hay tenant ACL.

Review event không sửa snapshot/created_at của revision. VN `affected_metrics` truyền thay đổi qua dependencies ratio đã ghi, giữ null khác0; không chứng nhận các narrative claim khác. Failed refresh không thay bản trước, nhưng chưa có stale status/failed-attempt ledger bền vững. Write chưa có idempotency; timeout cần kiểm lịch sử trước khi gửi lại.

UI có en/vi/tr; chín locale còn lại dùng English fallback cho phần mới. Editor/import/phương pháp/phân trang cùng luồng bị khóa khi ghi; read/upload cũ bị loại khi lựa chọn hoặc write thay đổi. Đã sửa race diff đổi revision trước, upload hoàn tất sau khi khóa editor và paging BCTC trong lúc save. Request đọc hủy ở browser không chứng minh CPU server đã dừng hoặc write đã rollback.

## Kiểm chứng đã chạy

Hồi quy backend cuối: **2.150 passed, 8 skipped, 63 warnings /92 file**. Danh sách tại `regression-tests.json`, JUnit `final-regression.xml`. Bao gồm quantlib/comparables/DCF, HTTP/auth, revisions/integrity/concurrency, Forex walk-forward/cost stress/registry/MCP, Crypto archive/replay, Swarm/DAG/budget và các regression các đợt trước liên quan. Không cộng số scoped runs vào tổng vì có test trùng.

Một skip do optional statsmodels chưa cài, bảy skip do thiếu quyền symlink trên Windows. Không coi những skip này là bằng chứng pass cho host có quyền symlink. Warnings chủ yếu deprecation NumPy/pandas ở loaders và fixtures hiện hữu; chưa sửa ngoài phạm vi tính năng này.

Frontend cuối: **170 passed /11 file**, JUnit `frontend-tests.xml`; kiểm thêm3 file component research, bản dịch, API wire/auth, navigation/layout và các trang liên quan. Production build `tsc -b && vite build` qua sau sửa UI cuối. Còn cảnh báo vendor-charts742,71kB, Vite config dùng `__dirname` và `act` từ Layout tests hiện hữu.

Trong lúc phát triển, hai test cố ý tái hiện pending upload/save đã fail trước fix rồi pass sau fix; báo cáo giữ tại `forex/save-freeze-before.xml` và `forex/save-freeze-after.xml`. Lượt HTTP đầu có hai kỳ vọng test sai về fixture và tuple→JSON list; đã sửa kỳ vọng theo contract, không bỏ test. Backend hồi quy cuối không có failure.

`checks.json`/`manifest.json` giữ kiểm UTF-8, new whitespace, local Markdown links, snapshots/hashes và canonical counts; `verification.json` tổng hợp kết quả. Tracker generator kiểm đủ265 ID/titles theo master/catalog, giữ54 scenarios,10 phases và16 decisions. Main tools không thêm ở đợt6: **117 keyless agent tools /85 main MCP**. Quantlib có310 public exports/24 modules, trong đó234 callable entries được tool expose; đã sửa tóm tắt tám README để không gọi cả310 là functions callable qua tool. Script inventory dùng runtime tạm trong repo, registry hiện hữu tạo memory/sessions scaffolding tại đó, không dùng user runtime. Dedicated Forex MCP hiện **12 read-only /15 execution**, research writes thêm2, MT5 thêm2; read-only vẫn có tool plan có thể gọi model khi operator yêu cầu, không suy thành không phát sinh phí.

Chưa chạy full repository suite, browser screenshot/visual acceptance, nguồn thị trường/tài khoản/broker/model thật hoặc production deployment. Ruff chưa có trong `.venv`; không cài dependency chỉ để lint. TestClient/FastMCP in-memory, fixture và jsdom không thay bằng chứng broker hay browser thật.

## Dữ liệu và rollback

Forex vẫn schema4; không migration execution ledger trong đợt6. [Quy trình backup/reconcile/downgrade đợt4](IMPLEMENTATION_STATUS_2026-11-05_04.md#dữ-liệu-và-rollback) tiếp tục áp dụng. Không restore database cũ lên execution mới chưa reconcile. Attempt mới giữ input/actual evaluator hashes; không restamp run cũ để khớp source mới.

Research revisions có file riêng `<get_runtime_root()>/research/artifacts.sqlite`, `user_version=1`, application ID `0x56524152`. Test chỉ dùng temp DB, không tạo file trong user runtime. Khi rollback code, ngừng save/review và khôi phục các file iteration6 từ snapshot hoặc bỏ module mới theo manifest, bảo toàn các thay đổi khác. Giữ database mới để phiên bản cũ bỏ qua; không xóa revisions/reviews, sửa hashes/user_version hoặc restore backup đè lên các ghi mới hơn chưa đánh giá.

Backup SQLite nhất quán bằng backup API hoặc dừng writer trước khi copy, giữ journal liên quan. Không restore từng file giữa transaction. Crypto archive đợt5 được giữ nguyên; không đổi path/capture để vượt giới hạn. Chưa commit, publish, deploy hoặc gửi lệnh giao dịch.
