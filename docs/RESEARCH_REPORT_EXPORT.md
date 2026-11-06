# Xuất Markdown từ research revision đã lưu

Cập nhật **2026-11-06**, đợt 8. Export tạo một bản nháp định lượng tiếng Việt từ dữ liệu có sẵn trong research revision. Nó không gọi AI để viết nhận định, không chạy lại engine, không fetch nguồn hoặc cập nhật timestamp/trạng thái xác minh. Các giá trị đã thiếu, không hợp lệ, ngoài bracket hoặc ngoài trang vẫn giữ nguyên trạng thái và lý do.

Đây là phần triển khai local của `VN-128` — Research Report Generator và `PLATFORM-064` — Report Publishing Pipeline, dựa trên `PLATFORM-033` — Research Artifact Revision Store. Không phải `VN-129` — Watchlist Alert Engine. Chức năng chưa publish, gửi báo cáo, giải quyết quyền phân phối hay chứng nhận nguồn; acceptance tổng thể vẫn mở trong [tracker](IMPLEMENTATION_TRACKER.md).

## Dùng trên Web và HTTP

Trong `/research`, chạy và lưu một kịch bản, hoặc mở một revision từ lịch sử theo [hướng dẫn revisions](RESEARCH_REVISIONS.md). Panel của revision có thao tác lấy bản Markdown, xem nội dung rồi tải xuống. Input để xuất là revision đã được server đọc từ kho, không phải result đang chỉnh sửa trong browser.

Web gọi đúng một endpoint có quyền đọc:

```text
GET /api/research/artifacts/{revision_id}/report
```

Response là `text/markdown; charset=utf-8`, có `Content-Disposition: attachment; filename="research-<revision_id>.md"`, `Cache-Control: no-store` và `X-Content-Type-Options: nosniff`. ID được giới hạn/đối chiếu qua API và store; tên tệp không lấy từ symbol, source URL, locator hay một đường dẫn caller cung cấp. Bearer authentication theo cơ chế API hiện có; không đưa API key vào download URL.

Preview và nút download dùng **cùng chuỗi response đã tải**. Browser tạo Blob UTF-8 từ chuỗi đó, không gọi lại engine hay endpoint để dựng một báo cáo khác khi bấm tải. Preview không thực thi raw HTML hoặc tải ảnh nhúng từ nguồn. Muốn lấy thêm review mới, cần chủ động tải lại snapshot/report; nội dung đang preview không âm thầm đổi theo thời gian.

Read này không khởi tạo một DB/report directory, migrate schema hoặc ghi PDF/stage file vào hệ thống report publishing hiện hữu. Reader của kho chấp nhận schema database 1 hoặc 2; export không nâng schema 1 lên 2. Revision không tồn tại giữ lỗi `404 REVISION_NOT_FOUND` của kho. Nếu export đầy đủ vượt giới hạn, API trả **413** với `REPORT_TOO_LARGE`; hình dạng revision không được hỗ trợ trả **422** với `INVALID_REPORT_REVISION`. Lỗi renderer bất ngờ trả **503 RESEARCH_REPORT_UNAVAILABLE** với thông báo an toàn, không trả exception riêng hoặc một báo cáo rỗng thành công. Lỗi integrity/storage khi đọc revision giữ contract lỗi của kho.

## Contract của renderer

[report.py](../agent/src/research_artifacts/report.py) cung cấp:

```python
render_revision_markdown(revision: dict) -> str
ReportExportError  # ValueError có .code
MAX_REPORT_BYTES = 262144
REPORT_FORMAT_VERSION = 1
```

Đầu vào là object revision đầy đủ do store trả về, gồm request/result, scope, content scope, created time, parent, hashes, producer, review state/history và limitations. API chịu trách nhiệm auth và kiểm tra integrity khi đọc kho. Renderer không thay thế store validation hoặc xác thực chữ ký; một dictionary tùy ý không trở thành kết quả đã được server chứng nhận chỉ nhờ render được.

Renderer chỉ hỗ trợ năm kind hiện hữu, `result.ok=true` và outer `verification_status="user_supplied_unverified"`. Kind/status không phù hợp, JSON không hữu hạn, object không thể serialize hoặc field không hỗ trợ tạo lỗi an toàn. Không sửa trạng thái sai thành verified hay tự đóng dấu đã duyệt.

Kết quả xác định với **cùng object đầu vào và cùng phiên bản renderer**: không có exported-at lấy từ clock và không sinh thêm ID. `created_at` và cutoff là giá trị đã lưu; báo cáo không dùng thời điểm download để làm dữ liệu có vẻ mới. Review là lịch sử append riêng; một lần đọc revision sau khi thêm review có thể trả thêm review và tạo body khác, trong khi request/result/base created time và các hash gốc vẫn không đổi. Timestamp của review là timestamp của event đã ghi. Tất cả review được store trả về trong lần đọc đều nằm trong phụ lục, không khẳng định renderer đã tải lịch sử bên ngoài phạm vi đó. Sau khi preview, download dùng body đang giữ; review thêm sau đó chỉ xuất hiện nếu chủ động tải lại report.

Review `acknowledged` hoặc `changes_requested` là nhãn và quyết định do operator tự khai. Nó không xác nhận issuer, nguồn, forecast, khả năng giao dịch hoặc người review có quyền phê duyệt; export luôn giữ `user_supplied_unverified`. Report không tải attempt/refresh state và không coi một revision thành công trong quá khứ là giá hay dữ liệu hiện tại. Đọc [attempt history](RESEARCH_REVISIONS.md#idempotency-attempt-và-refresh-state) riêng để biết lần refresh sau có thất bại hoặc chưa rõ kết quả hay không.

## Nội dung báo cáo

Mọi báo cáo bắt đầu bằng nhãn bản nháp, nguồn chưa xác minh và chưa publish/gửi đi. Metadata giữ revision ID, kind, created time, cutoff, parent, scope, content scope, review state và historical-reconstruction flag nếu có. Hash nhận diện nội dung/producer đã ghi, không được gọi là chữ ký nguồn hoặc bằng chứng ngày công bố thật.

| Kind | Phần trình bày định lượng |
|---|---|
| `vietnam` | Chỉ tiêu từng kỳ BCTC đã trả về, đơn vị, reason, recorded inputs, evidence IDs và balance checks; không tự annualize hoặc tính lại ratios |
| `vietnam_comparables` | Target/peer của trang, giá/EPS/BVPS VND/cổ phiếu, P/E/P/B, exclusions, distribution đã tính trên toàn set và các giá kịch bản theo quantile |
| `vietnam_dcf` | EV/equity/per-share, WACC assumptions/basis/source IDs, declared forecast/scale/capital/equity bridge, restricted-cash exclusion và sensitivity cells/reasons |
| `vietnam_reverse_dcf` | Cùng bridge/assumptions đã ghi, target/share basis, bracket/WACC, solver status/reason/endpoints, residual Decimal và số vòng; không đổi thất bại thành nghiệm |
| `crypto_basis` | Spot/policy, danh tính/expiry từng contract, thời gian còn lại, accepted/rejected/reasons, gross mid basis và annualized bid/ask bounds theo đúng đơn vị fraction |

Các chi tiết dưới đây có ý nghĩa khi đọc phần tóm tắt:

- `null` hiển thị “Chưa có / null”, khác `0`, `"0"`, tỷ lệ âm và giá âm. Không lấy endpoint hoặc điểm thử cuối thay implied growth null của reverse DCF.
- Reverse DCF chỉ có nghiệm đạt tolerance khi status `solved`. Các trạng thái `outside_bracket`, `non_identifiable`, `iteration_limit` được nêu rõ; việc xuất không nới tolerance hoặc giải lại bài toán.
- Crypto giữ các dòng rejected, gồm perpetual/expiry/stale/skew/identity reasons. Gross quoted basis không được đổi thành executable yield, carry PnL, funding forecast hoặc kết quả sau phí/vay/vốn.
- Forecast/bridge DCF theo money scale của request; EV/equity là VND đầy đủ, shares/target/tolerance per-share không nhân scale. Báo cáo không tự scale lại hay bỏ debt/minority/preferred/associate claims.
- Với BCTC, evidence IDs chỉ có nghĩa trong từng kỳ. Quan hệ nguồn được đi theo recorded inputs/metric dependencies trong snapshot, kể cả dependency gián tiếp của cash conversion cycle; không dựng một narrative claim graph mới.

## Trang, coverage và nguồn

Nếu có `paging`, báo cáo giữ `offset`, `returned`, `total`, `next_offset`, `complete` và aggregate scope đã ghi. `complete` khác true có cảnh báo rõ. Một trang BCTC rỗng vẫn là trang rỗng, không trở thành dữ liệu zero hoặc kết luận doanh nghiệp không có hoạt động. Comparables có thể giữ aggregate toàn peer set nhưng chỉ trình bày chi tiết peer của trang; báo cáo không tải các trang còn lại.

Phần nguồn nêu context/path, evidence ID nếu có, URL/source ref, locator/instrument, revision/document hash và published/event/available/retrieved times đã khai báo. Với comparables, nguồn trong toàn bộ request vẫn được giữ và có context target/peer cụ thể, kể cả peer không nằm ở trang hiển thị. Không tự tạo external citation ID cho một nguồn vốn không có ID.

Các links chỉ mở tới URL HTTP(S) hợp lệ, không credentials/control/whitespace/backslash; tham chiếu khác được trình bày dạng text và ghi không tạo liên kết. Renderer không fetch, resolve, kiểm entitlement, xác minh issuer hoặc suy ra publication time. Một link mở được hay hash đúng định dạng chưa chứng minh tài liệu thật hoặc số liệu đáng tin cậy.

## Phụ lục JSON đầy đủ và an toàn hiển thị

Phụ lục là JSON của **toàn bộ revision đã truyền vào**, bao gồm full request/result và mọi field metadata/review được store trả về. Không có file attachment ngoài tài liệu Markdown và không tạo đường dẫn nguồn giả. Parse code block JSON khôi phục nguyên giá trị JSON; đây là cách kiểm tra summary với snapshot, không chỉ dựa vào văn xuôi.

Text caller cung cấp trong tiêu đề ô, locator, basis, review hoặc limitations được escape Markdown/HTML; newline/tab không được biến thành heading, row hoặc block tùy ý. Control/bidi/surrogate characters được hiển thị theo escape. Link destinations được encode để dấu ngoặc, quote hoặc backtick không thoát khỏi cú pháp Markdown.

JSON dùng Unicode escapes và escape `<`, `>` và `&`; fence dài hơn mọi chuỗi backtick trong nội dung để ngăn source/review đóng code block. Các escapes phục vụ hiển thị, không redaction hay sửa request/result. Không đưa raw HTML hoặc remote image từ input vào preview.

Giới hạn là **262.144 byte UTF-8 (256 KiB)** cho toàn báo cáo, gồm summary và JSON. Khi vượt giới hạn, không cắt JSON, không bỏ nguồn/review âm thầm và không trả một tài liệu không hoàn chỉnh có vẻ thành công. Một revision hợp lệ nhưng có nhiều nội dung có thể không xuất được trong budget này; dữ liệu gốc vẫn còn trong kho/API revision.

## Kiểm chứng và giới hạn còn lại

[Tests renderer](../agent/tests/test_research_report_export.py) tạo revision thật từ cả năm engine bằng synthetic fixtures/temp store; kiểm deterministic/no mutation, full JSON round-trip, paging/empty coverage, null/zero/negative/unsolved, transitive recorded evidence, units/bridge/exclusions, review receipts, HTML/Markdown/fence/URL injection, finite shape và giới hạn output. Các test purity chặn engine, store, filesystem và network khi render. [HTTP tests đợt 8](../agent/tests/test_research_iteration8_routes.py) dùng TestClient và kho tạm thực, kiểm auth, body UTF-8 đúng renderer, current review, headers, đọc không ghi database/sidecar, lỗi 413/422 và thông báo 503 an toàn. [Web tests](../frontend/src/components/research/__tests__/ResearchReportExport.test.tsx) kiểm manual preview, download cùng body không fetch lần hai, URL/ảnh không an toàn, hủy response cũ và lỗi. Không suy ra browser visual acceptance từ unit tests/build.

Các guide phương pháp giữ giới hạn tương ứng: [VN BCTC](LOCAL_VN_FINANCIAL_STATEMENTS.md), [VN comparables](VN_COMPARABLES.md), [VN DCF](VN_DCF_SENSITIVITY.md), [reverse DCF](VN_REVERSE_DCF.md), [Crypto basis](CRYPTO_BASIS_CURVE.md). Export không bổ sung quyền với dữ liệu gốc hoặc biến nguồn chưa xác minh thành báo cáo đã kiểm chứng độc lập. Đây là phép trình bày snapshot định lượng; không tự đọc bộ PDF mẫu, tổng hợp tin tức/dòng tiền, phân tích chart nến hoặc sinh khuyến nghị mua/bán/ATO/MTL. Chưa có AI narrative, PDF export cho schema này, rights/redaction/citation-resolution gate, ký số, email/webhook delivery hoặc publishing receipt.

Rollback bằng việc bỏ endpoint/control/module export của đợt 8; không xóa database, revision, review hoặc attempt history. Báo cáo đã tải là bản sao local của snapshot khi lấy, không bị thay đổi bởi rollback code hay các revision mới.
