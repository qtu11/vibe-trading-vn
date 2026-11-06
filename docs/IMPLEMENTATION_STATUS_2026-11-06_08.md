# Đợt8: nghiên cứu sâu Việt Nam, refresh ledger, Markdown và Forex regime

Ngày **06/11/2026**, checkout **D:/Vibe-Trading**. Yêu cầu tiếp tục code từ master
được bổ sung bằng yêu cầu học cách phân tích/khuyến nghị từ `docs/mau-baocao`.
Các thay đổi là local; chưa commit/publish, không gọi model/feed/broker thật và
không đặt/hủy lệnh. Acceptance cấp chương trình vẫn mở.

## Phạm vi đã nối

| Luồng | Hành vi và giới hạn |
| --- | --- |
| [Đọc mẫu FPT](REPORT_SAMPLE_FINDINGS.md) | Bốn PDF, 305 trang trích xuất; ba file có text, BCTC Q3 là ảnh. Đọc trực tiếp ảnh trang1–10; chưa đọc đầy đủ thuyết minh11–54. Có15 cảnh báo kèm file/trang, không tự xác thực nhà phát hành. |
| [Phương pháp Việt Nam](VIETNAM_DEEP_RESEARCH_METHOD.md) | Skill+agent routing+sáu vai council tách cơ bản/timing, reported/comparable, CFO/CFI và trading-flow proxy. Tách chưa sở hữu/đang giữ; ATO/MTL cần dữ liệu phiên và quote/book, chưa chọn từ nến ngày. |
| Council wrapper | Trả execution context với `execution_ready:false`; giá đóng cửa không là quote realtime. BÁN thiếu holdings bị chặn và bỏ economics/sizing kiểu mở short; contract generic được giữ cho use case chung. |
| [Refresh ledger](RESEARCH_REVISIONS.md) | Schema2 có attempt/outcome bất biến, optional key theo caller body và parent, replay thành công/thất bại không chạy engine lại. Pending/crash là unknown, không tự steal hoặc tự retry. Failed refresh giữ last-good. |
| [Markdown export](RESEARCH_REPORT_EXPORT.md) | Renderer tất định từ revision đã lưu của5 kind, phụ lục JSON đủ, giới hạn256KiB. GET auth, no-store/nosniff; Web preview/download cùng body. Không là AI narrative mới, PDF hay publication. |
| [Forex regime](FOREX_REGIME_RESEARCH.md) | Dataset nến đóng dùng chung; SMA slope/ATR theo Wilder nhân quả, thresholds fit train-prefix, hysteresis+dwell OOS. Read-only HTTP/dedicatedMCP/Web; page export ghi rõ chỉ trang trả về. Chưa ADX, forecast hay signal live. |

Các ví dụ giá/nến JSON đều tổng hợp hoặc caller khai báo chưa xác minh. Không
đổi giá trị null thành0. Nội dung PDF là dữ liệu, không là chỉ thị công cụ.

## Bằng chứng đọc báo cáo

- [Manifest trích xuất](../.codex-backups/2026-11-06-report-methodology/extraction-manifest.json)
  giữ hash file/trang, text và giới hạn đọc ảnh.
- [Phạm vi đọc](../.codex-backups/2026-11-06-report-methodology/review-coverage.json)
  tách extraction khỏi kiểm tra nội dung.
- [Phép tính](../.codex-backups/2026-11-06-report-methodology/calculations.json)
  đối chiếu CFO, tỷ lệ sở hữu, CAPM và terminal value bằng Decimal.
- [Nguồn quy tắc](../.codex-backups/2026-11-06-report-methodology/official-sources.json)
  ghi rõ danh mục VNX2026 đã đọc, PDF quy chế chưa lấy đầy đủ; SSI/TCBS là hướng
  dẫn dịch vụ của broker. Chưa có bộ rule runtime Việt Nam được nghiệm thu.

## Kiểm chứng

Frontend: **260 passed /21 files**; `npm run build` qua TypeScript và Vite.
Cảnh báo hiện hữu: test Layout có React act warning, Vite config dùng `__dirname`,
chunk vendor-charts742,71kB vượt500kB. Chưa có browser visual acceptance.

Backend: kết quả hồi quy cuối được ghi tại
[verification.json](../.codex-backups/2026-11-06-implementation-8/verification.json)
và [JUnit](../.codex-backups/2026-11-06-implementation-8/final-regression.xml).
Danh sách phạm vi: [115 file backend](../.codex-backups/2026-11-06-implementation-8/regression-tests.json),
[21 file frontend](../.codex-backups/2026-11-06-implementation-8/frontend-test-files.json).
Các kết quả scoped: refresh ledger, report renderer, HTTP routes, regime, council
và fixture Windows được giữ trong các thư mục con evidence đợt8.

Lượt mở rộng ban đầu ghi **3167 passed /28 failed /8 skipped**. Failures gồm
README inventory lệch, preset nhắc wrapper tool không được cấp cho worker,
fixture cũ thiếu tham số call cap/roster và3 fixture tạo symlink không có quyền
trên Windows. Đã sửa docs/prompt/fixture thay vì cấp recursive council tool hoặc
nới kiểm tra bảo mật. Bản XML ban đầu được giữ riêng để có thể kiểm tra lại.

Ruff chưa có trong venv; chưa chạy toàn bộ repository suite, broker/account/feed,
LLM thật, OCR đủ thuyết minh hoặc production deployment. Tests dùng dữ liệu/mocks
cục bộ, không chứng minh chất lượng dự báo hoặc lời khuyên thật của model.

## Inventory và tracker

Inventory hiện tại: **120 agent tools không cần key,86 mainMCP,91 bundled skills,
31 swarm presets**. Quantlib310 exports/24 modules,234 callable entries. Forex
dedicated14 read-only/17 execution; opt-in research writers cộng3, MT5 cộng2.
Hai agent tool chart/council đã có trong source local trước khi học mẫu, không
được thêm vào mainMCP bằng thay đổi phương pháp này. Xem
[inventory](../.codex-backups/2026-11-06-implementation-8/inventory.json).

[Tracker](IMPLEMENTATION_TRACKER.md): **44 partial_delivered /221 baseline_only**,
28 delivery. Regime bổ sung FX-147/PLATFORM-016; export chỉ là phần draft local của
PLATFORM-064. VN-127/VN-128, PLATFORM-033/VN-130 vẫn partial. Không nâng các mục
này thành hoàn tất toàn đặc tả, và không thay265 IDs/54 scenarios/10 phases/16
decisions hoặc `implementation_approved:false`.

## Rollback và dữ liệu

Snapshot các file sửa nằm dưới `.codex-backups/2026-11-06-implementation-8/`
và `.codex-backups/2026-11-06-report-methodology/before/`; manifest cuối ghi
hash và nguồn trước sửa nếu có. Một số file mới ở baseline có snapshot theo đợt
trước hoặc được đối chiếu HEAD, không tự nhận là backup đầy đủ runtime.

Research DB: binary mới đọc schema1/2, write nâng schema1→2 giữ revision/review.
Binary schema1 cũ từ chối schema2. Khi downgrade, giữ nguyên DB mới và khôi phục
backup schema1 riêng hoặc dùng code đọc được schema2. **Không hạ user_version,
không xóa bảng attempt/outcome hoặc dữ liệu mới để ép binary cũ chạy.** Unknown
attempt cần kiểm tra thủ công, không tự thử lại như một thao tác mới.

Forex experiment registry tiếp tục schema4; regime chỉ đọc, không thêm experiment
writer. Khôi phục source/UI phù hợp và giữ runtime hiện tại trước rollback.
Xuất Markdown không ghi DB. Phương pháp VN có thể gỡ bằng khôi phục routing/preset
và roster skill; không phải lý do xóa tài liệu, bản tính hoặc lịch sử nghiên cứu.
