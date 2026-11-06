# Triển khai đợt7: reverse DCF, bootstrap OOS và Crypto basis

**Ngày:** 06/11/2026. **Checkout thực tế:** `D:/Vibe-Trading`, baseline commit `f072a046a6ad047835fd1cc2bfc5ebee52c9af6b`. Tiếp tục source local chưa commit theo yêu cầu chat; không phê duyệt live trading, deploy hoặc nghiệm thu toàn chương trình.

[Tracker265 ID](IMPLEMENTATION_TRACKER.md) có **39 partial_delivered /226 baseline_only**, mọi acceptance vẫn mở. Hai ID mới có bổ sung là `FX-162` và `CRYPTO-202`; reverse DCF mở rộng phần đã có ở `VN-117`, không đếm lại thành ID mới. Snapshot, JUnit, danh sách test và manifest nằm trong `.codex-backups/2026-11-06-implementation-7/`.

## Phạm vi code đã nối

| Luồng | Implementation và caller | Ranh giới |
| --- | --- | --- |
| Reverse DCF VN | [Solver](../agent/src/tools/vietnam_reverse_dcf.py), shared input bridge của [DCF](../agent/src/tools/vietnam_dcf.py), Web, read API và revision riêng | Giải growth trong bracket từ giá supplied, cố định FCFF/WACC/bridge; không tạo forecast hoặc xác minh giá |
| Bootstrap Forex | [Trade paths](../agent/src/trading/forex/trade_paths.py), service/registry, HTTP, dedicated Forex MCP và phương pháp thứ ba trong Web lab | Moving blocks trong từng fold OOS đã khóa, không retune; phân vị thực nghiệm chưa là xác suất lãi tương lai |
| Crypto basis | [Domain](../agent/src/tools/crypto_basis.py), [tool](../agent/src/tools/crypto_basis_tool.py), main MCP, read API, Web và revision riêng | Quote supplied spot/dated futures, gross basis có expiry/availability; chưa feed hay net executable carry |
| Revision integration | Kho schema1 thêm hai kind cố định `vietnam_reverse_dcf`, `crypto_basis`, read-only no-create và parent/diff/review hiện hữu | Không nhận client-certified result, tool/path tùy ý hoặc nâng nguồn unverified bằng review |

Hướng dẫn cụ thể: [VN reverse DCF](VN_REVERSE_DCF.md), [Forex lab/trade paths](FOREX_RESEARCH_LAB.md#bootstrap-đường-vốn-từ-các-trade-oos-đã-khóa), [Crypto basis](CRYPTO_BASIS_CURVE.md), [research revisions](RESEARCH_REVISIONS.md). Ba fixture mới là synthetic; bản VN/Crypto trong docs và frontend được đối chiếu byte. Khởi động lại backend/nạp giao diện mới để áp dụng route và schema tool mới; build/test không chứng minh app đang chạy đã reload.

## Hợp đồng và phép tính

Reverse DCF nhận DCF consolidated non-financial VND hiện hữu, target và tolerance dạng decimal VND/cổ phiếu thực, price observation/evidence, share-basis note và bracket growth explicit. Chỉ dùng perpetuity-growth; không giải growth cho exit multiple. Mỗi lần repricing gọi sensitivity engine với cùng FCFF và full enterprise→equity bridge. Restricted cash vẫn bị loại; price và shares không nhân money scale. Bracket phải cách fixed WACC hơn1e-12, tối đa128 vòng, không extrapolate hay tự nới tolerance. Ngoài khoảng, zero terminal FCFF hoặc hết precision trả trạng thái/reason với implied growth null.

Đã sửa hai lỗi precision tìm qua review độc lập: chuyển target sang float có thể làm giá khác nhau thành bằng nhau; `abs(Decimal)` có thể làm tròn residual sát ngưỡng theo context mặc định. Convergence hiện so JSON-visible engine price với target decimal ở precision80, dùng `copy_abs()` không làm tròn; residual là decimal string. Engine giá vẫn floating point, không hứa đáp ứng tolerance quá nhỏ hoặc exact accounting. Tests giữ cả target lớn và trường hợp residual chỉ vừa vượt tolerance.

Forex fit base walk-forward một lần, lấy gross outcomes OOS đã khóa và trừ base round-trip cost đúng một lần. Sampling unit là thứ tự trade trong từng fold, không phải bar/calendar time. Block noncircular liên tiếp, start chọn đều có hoàn lại; cắt block cuối để giữ đúng số trade. Fold không trade giữ known-empty, fold dương nhưng ít hơn block length làm study incomplete. Bất kỳ path lỗi nonfinite/bankruptcy cũng làm null toàn bộ quantiles; không bỏ path lỗi rồi thống kê survivors. PCG64 seed và NumPy version được lưu; fan tối đa20 samplepaths/100 steps, phân vị dùng mọi simulation. Không annualize trade-index Sharpe hoặc gán future-profit probability.

Crypto giới hạn64k UTF-8/12 contracts, bid/ask decimal dương, expiry/time có timezone, explicit age/skew budgets. Dùng quantlib ACT/365F calendar-day count cùng fractional UTC seconds; basis âm/backwardation và0 giữ nguyên. Perpetual, expiry đã qua, stale/skew/future availability, currency/settlement/nonlinear mismatch bị loại từng dòng với null/reason. API/snapshot giữ full curve; tool/main MCP page3 dòng nhưng full summary/hash không đổi. Gross mid/bid-ask basis chưa tính fee, financing/borrow, margin, depth/fills hay settlement; USDT không tự đổi sang USD.

Web phân biệt các workflow, nạp ví dụ không tự gọi API, tính không tự lưu. Write dùng auth riêng, khóa input/phương pháp và selector liên quan, bỏ read/import cũ, không tự retry khi outcome chưa xác định. Copy mới có en/vi/tr, chín locale khác giữ English fallback. SVG fan trong Forex có sample/actual/bands theo trade index; chưa browser visual acceptance.

## API, tools và storage

| Thao tác | Endpoint hoặc tool | Side effect |
| --- | --- | --- |
| Reverse DCF | `POST /api/research/vietnam/reverse-dcf` | Read-auth; không lưu |
| Crypto basis | `POST /api/research/crypto/basis`, `crypto_basis_curve(payload, offset)` | Read-auth/API hoặc read-only agent/main MCP; không fetch/ghi |
| Bootstrap paths | `POST /api/forex/trade-paths`, `forex_trade_paths` | Read-only local supplied data |
| Lưu bootstrap | `POST /api/forex/trade-paths/experiments` hoặc `/api/forex/trade-paths/experiments/{id}/runs`; `forex_run_trade_paths_experiment` | Registry write; MCP cần `--allow-research-writes` riêng |
| Lưu VN/Crypto | `POST /api/research/artifacts` với kind mới, request bare | Server chạy lại; immutable revision write |

Inventory đã đo trong subprocess có runtime tạm: **118 keyless agent tools /86 main MCP tools**, quantlib **310 public exports /24 modules**, tool expose234 callable entries. Dedicated Forex **13 read-only /16 execution**; bật research writes thêm3 tool, MT5 thêm2. Không đổi whitelist broker mutation hoặc cho phép lệnh live qua main MCP.

Research SQLite vẫn schema1/application ID `0x56524152`, Forex schema4; không migration ledger. Source manifest bootstrap giữ dependency/code hashes và NumPy version. Revision nguồn cũ và run cũ không bị restamp. Parent scope Crypto chỉ base/quote; diff theo vị trí row có thể thay nhiều field khi đổi sort/expiry, chưa là contract-aware claim graph. Crypto facts hash giữ normalized request gồm source declarations/policy, nên source-only change có thể đổi cả source/facts flags; không dùng cờ đó chứng minh giá đã thay.

## Kiểm chứng và bằng chứng

Hồi quy backend cuối trên **98 file** gồm các đợt trước cùng valuation, fixed-income/risk, Crypto, Forex, HTTP/MCP/revisions, Swarm và README inventory. Kết quả **2.644 passed, 8 skipped, 63 warnings** tại `final-regression.xml`; danh sách `regression-tests.json`. Không cộng scoped runs vì có test trùng. Một skip do optional statsmodels thiếu; bảy skip do quyền symlink trên Windows. Không coi những ca này là pass trên host có symlink privileges.

Frontend: **209 passed /13 file** tại `frontend-tests.xml`, gồm hai lab mới, third Forex method, chart, input/save race guards, API wire/auth, routing, locale parity và regression hiện hữu. Production build `tsc -b && vite build` qua sau sửa tuple typing cho translation keys. Còn cảnh báo Vite native config `__dirname`, Layout `act` và vendor-charts742,71kB hiện hữu.

Lượt rộng đầu giữ `initial-regression.xml`:2600 passed/42 failed/8 skipped;42 lỗi đều ở README counts/list/badge chưa đồng bộ. Đã thêm tool Crypto mới vào danh mục, cập nhật118/86 và tách số callable234 ra khỏi badge chỉ dành cho exports/modules, giữ assertion tests nguyên vẹn. Các lượt sau bao gồm regression precision mới và source đã chốt. Lỗi fixture zero-FCFF ban đầu được sửa để còn EBITDA dương như contract engine yêu cầu; không bỏ ca non-identifiable. Bằng chứng Decimal riêng tại `root/decimal-fix.xml`.

`checks.json` và `manifest.json` kiểm UTF-8, new whitespace, local links/anchors, source snapshot/hash, fixture parity và master counts265/54/10/16; `verification.json` tổng hợp JUnit/build/inventory. Tool inventory khởi tạo registry trong subprocess để SQLite handles được giải phóng trước cleanup trên Windows; không dùng user runtime hoặc credentials thật. Không cài thêm dependency.

Chưa chạy full repository suite, browser runtime/screenshots, quote/contract/source thật, broker/account/model/feed, paper/live orders hoặc deployment. Ruff chưa có trong `.venv`. In-memory TestClient/FastMCP, jsdom và fixtures không thay bằng chứng thực thi ngoài hệ thống. Review ghi nhãn người thao tác tự khai vẫn không phải independent evidence review.

## Rollback và phần còn mở

Backup SQLite nhất quán trước bảo trì; không copy một file đang ghi mà bỏ journal, không restore DB cũ đè các run/revision/execution mới chưa đánh giá. Rollback source theo snapshot đợt7 và manifest, giữ thay đổi khác; không xóa data hoặc sửa hashes/timestamps/user_version. Forex downgrade tiếp tục theo [quy trình schema4](IMPLEMENTATION_STATUS_2026-11-05_04.md#dữ-liệu-và-rollback); research schema1 không đổi nhưng bản cũ chỉ nhận kind/filter cũ, vì vậy giữ các kind mới để bản hỗ trợ đọc lại sau.

Chưa hoàn tất forecast/model doanh nghiệp thật, broker-calibrated costs/ticks, bootstrap stationarity/block calibration, OOS reuse/tuning gate, net basis strategy, narrative AI/PDF, stale/failed-refresh ledger, idempotency, verified reviewer/tenant ACL hoặc signed evidence. Tracker giữ các gate này mở. Chưa commit, publish, deploy, cấp quyền tài khoản hoặc gửi lệnh giao dịch.
