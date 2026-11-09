# Audit logic toàn bộ Vibe-Trading — đang thực hiện

Mục tiêu giữ nguyên: audit toàn bộ source, luồng xử lý, giao diện và kết quả kiểm thử. Tài liệu này ghi phạm vi đã kiểm chứng và phần còn mở; không dùng một nhóm test xanh để kết luận toàn sản phẩm hoàn tất.

## Phạm vi và bằng chứng

Inventory từ source hiện tại nằm ở `artifacts/full-source-audit-20261108/inventory.json`: 1.475 file source và 1.162 file test trong các cây ứng dụng được quét. Đã loại `node_modules`, `dist`, cache Python và công cụ Office đóng gói khỏi số file source. Inventory chỉ là danh mục, không chứng minh mọi file đã được đọc hoặc mọi hành vi đã được kiểm tra.

Worktree có thay đổi/commit song song trong lúc audit (`71ee28a5` → `68c07feb`), gồm version desktop/locale, composer, cấu hình provider và các template cũ. Các thay đổi đó được giữ lại; kết quả test phải gắn với thời điểm chạy, không tự suy ra bản đóng gói đã chứa tất cả sửa đổi.

| Khu vực | Luồng đã lần theo / bằng chứng | Trạng thái và phần còn mở |
| --- | --- | --- |
| Định danh và dữ liệu thị trường | Resolve → khóa mã/sàn → loader → provenance → evidence; captures FPT/VCB/HPG và MBB | Chặn AKShare dùng A-share cho mã thị trường khác; fallback sang nguồn kế tiếp giữ provenance. Đã phân biệt quote raw và nến điều chỉnh. Chưa audit hết 47 loader và mọi thị trường/cache/error path |
| Số và nguồn | Ledger → citation → định dạng Việt/Anh → sửa tham chiếu → final release | Đã sửa mất số có nguồn, sửa cục bộ bị bỏ, chart JSON bị phá, đoạn/hàng bảng mất số nhưng còn kết luận. Số xuất hiện trong nguồn chưa chứng minh đúng chỉ tiêu/kỳ |
| Chart trong chat | Tool lifecycle → payload quan sát → final gate → SSE → MarkdownContent → ECharts | Có phát lại 53 nến MBB qua renderer thật, URL/cơ sở điều chỉnh, khoảng ngày lịch, volume/MACD thiếu giữ khoảng trống |
| Model và context | Metadata theo provider/endpoint/model, budget, schema tokens, output reserve, compaction và telemetry | Cache từ chối reasoning/Responses đã tách theo endpoint/model/provider; mức bị từ chối không còn được báo là đang áp dụng. Kiểm lại transactional compaction giữ context/checkpoint khi lỗi. Metadata fallback không được coi là cửa sổ thật |
| Chat và SSE | Gửi → ACK → stream → complete/failed/cancelled → history/reload | Sửa kết quả muộn ghi nhầm chat/attempt, kể cả tạo/tiếp tục goal và goal đọc cũ ghi đè goal vừa tạo; failed không thành succeeded khi reload. Các tác vụ bất đồng bộ khác vẫn cần audit |
| Checkpoint và phục hồi | ResponseCheckpoint → transcript → attempt → xóa checkpoint → search index | Đã sửa mất nội dung khi cancel/fail/exception; giữ checkpoint nếu ghi transcript thất bại; FTS lỗi không đổi kết quả đã lưu thành failed |
| Report evidence/định giá | Structured facts → nguồn thu thập → quote/unit/basis → rating → render | Chặn mục tiêu tính toán chỉ có con số và lời mô tả DCF; yêu cầu công thức/đầu vào rồi tính lại. Kiểm chứng đầy đủ chiều đơn vị và ngữ nghĩa mọi chỉ tiêu vẫn mở |
| DOCX/PDF/PPTX | Service → renderer → publish → durable receipt → authenticated preview/download | Sửa lookup index tuần hoàn; kiểm package OOXML và đọc cấu trúc PDF; chặn PDF giả, rỗng hoặc mã hóa. Mặc định tool/API sâu 24 trang, đo PDF thật, giữ file và trạng thái partial khi thiếu độ dài |
| UI/sidebar | Artifact card → job → canonical PDF → PNG preview → ba nút tải | Có test API/UI và các ảnh đã chụp. Chưa nghiệm thu mọi màn hình trong Electron đóng gói hiện tại |
| Backtest/quant/factors | Engines, metrics, optimization, factor purity, lookahead | Bộ kiểm thử offline rộng đang chạy; cần đọc kết quả và probes theo hợp đồng trước khi kết luận |
| Paper/live/broker/risk | Tách research, paper, connector, mandate, kill switch, audit ledger | Chỉ kiểm source/mocks/fixture; chưa thực hiện giao dịch hoặc cấp quyền broker trong audit |
| Portfolio/shadow/revisions | Sổ trạng thái, số dư, định giá, revision và restart | Bỏ USD/VND=25400 tự sinh/gắn nguồn Frankfurter, làm sạch rate giả trong cache, valuation v5 yêu cầu refresh snapshot cũ (vẫn giữ dữ liệu trên đĩa). Chưa hoàn tất source-to-runtime audit từng nhánh |
| Swarm/goal/scheduled/channels/MCP | Lập lịch, failure/resume, dedup/idempotency, transport | Còn mở; không suy ra toàn bộ được nghiệm thu từ test chat thường |
| API/auth/files/secrets | Auth boundary, endpoint guard, artifacts và path scope | Có các test hiện hữu; audit toàn bộ route/IPC và các cửa ngõ khác còn mở |
| Desktop/build/update | Backend resolution, credentials, updater, packaged runtime | Chưa kiểm tra lại bộ cài. Đang có khác biệt version desktop `0.3.2` và package backend `0.1.18` cần phân định trước khi sửa gate |
| CLI/wiki/CI/dependencies | Entrypoints, package locks, optional extras, workflows | Đã đọc đường CI và sandbox test; chưa hoàn tất mọi lệnh/route/phụ thuộc tùy chọn |

## Các lỗi có kiểm thử tái hiện và bản sửa

1. **Chart JSON hỏng sau grounding:** số đếm `53` trong payload thực bị thay bằng marker. Bảo vệ đúng payload first-party, thay chart do model chép bằng kết quả quan sát, đặt chart sau đoạn mở đầu và đồng bộ lại SSE.
2. **Báo cáo có nguồn vẫn bị lược số:** thiếu kế thừa citation inline; một dòng khai báo sai kéo theo mất khai báo hợp lệ; tham chiếu tool-name không trỏ call duy nhất. Sửa có kiểm chứng lại; nguồn của hàng khác không được dùng để cứu số trong hàng hiện tại.
3. **Kết luận sống sót sau khi số bị loại:** rút cả đoạn/tiêu đề hoặc hàng bảng phụ thuộc, hiện thông báo thiếu dữ liệu. Bỏ frontend che marker/cảnh báo.
4. **Dữ liệu chart chưa có bị biến thành giá trị:** không suy O/H/L từ close; volume thiếu và MACD warmup giữ `null`/khoảng trống. Số không thực vẫn là số không.
5. **Một tháng thành 22 tuần:** bộ chọn ngày dùng số nến cố định. Đã chuyển sang mốc ngày lịch từ nến cuối, giữ clock/offset và xử lý cuối tháng.
6. **Kết quả A ghi nhầm B:** preview, send ACK/rejection, cancel và completion polling trả về sau khi đổi chat/attempt. Đã thêm ràng buộc connection/session/attempt và test Promise trả muộn; failed/cancelled/interrupted không tạo thẻ thành công khi reload.
7. **Hủy hoặc lỗi làm mất phần đã viết:** đọc checkpoint trước khi kết thúc, lưu rõ trạng thái chưa hoàn tất/chưa kiểm chứng. Xóa checkpoint sau transcript và attempt; lỗi ghi giữ cơ hội phục hồi khi khởi động lại.
8. **FTS lỗi biến completed thành failed:** index là projection phụ trợ; lỗi index được ghi log và giữ kết quả transcript làm nguồn sự thật.
9. **Job lookup đệ quy:** artifact index trỏ job không tồn tại hoặc vòng tham chiếu làm preview lỗi. Chỉ đọc receipt trực tiếp từ index; kiểm lại artifact thuộc job.
10. **Khuyến nghị dựa vào giá mục tiêu chưa tính:** giá target dạng derived cần biểu thức, input_keys đúng, hệ số giả định công khai và kết quả tính lại khớp. Chưa có đủ quote/basis/evidence vẫn không xếp hạng.
11. **File ZIP giả được coi DOCX/PPTX:** kiểm XML part và content type của package thay cho chỉ bốn byte magic.
12. **24 trang chỉ được kiểm ở CLI:** thêm minimum_pages và pdf_pages qua tool/API/service/receipt/parser UI; thiếu trang hoặc không đo được không trả succeeded. Generic service cho phép note ngắn khi gọi rõ yêu cầu thấp hơn.
13. **README đưa số mẫu thành dữ liệu hiện tại:** gỡ khuyến nghị FPT/định giá không có chứng cứ kèm liên kết PDF không tồn tại; chuyển sang bằng chứng phát lại có receipt và giới hạn rõ ràng. Snapshot README trước sửa ở `.codex-backups/2026-11-08-source-audit/`.
14. **Goal trả muộn ghi nhầm chat:** bảo vệ tạo session/goal, ACK/lỗi của bước tiếp tục bằng đúng session và mã pending duy nhất. Request đọc goal cũ không được xóa goal vừa tạo; callback edit/cancel cũ không đổi goal của chat khác.
15. **Tỷ giá giả có nguồn thật:** `build_rates` tự thêm VND=25400; feed Frankfurter cũng gắn giá cố định này dù request chỉ lấy CNY/HKD/EUR. Bỏ giá tự sinh ở dữ liệu mới và cache; tỷ giá truyền rõ ràng vẫn kiểm tra bình thường.
16. **Sai mã vẫn trả OHLCV thành công:** AKShare dùng A-share như fallback cho mã không nhận diện, có thể trả dữ liệu Trung Quốc cho `.VN` hoặc forex không hỗ trợ. Chỉ mặc định A-share cho mã đại lục sáu chữ số; nguồn không hỗ trợ trả miss để loader kế tiếp xử lý.
17. **SHA256 không khớp file trên Windows:** text-mode ghi LF thành CRLF trong khi receipt băm chuỗi LF. Ghi nguyên byte UTF-8, so byte khi dùng lại artifact, thêm kiểm tra hash multiline và phát hiện file bị sửa.
18. **Một endpoint thay đổi khả năng của endpoint khác:** cache từ chối `reasoning_effort` và buộc Responses chỉ khóa theo tên model. Tách theo provider/endpoint/model; lỗi giá trị effort không bị đổi âm thầm sang mặc định. Snapshot cuối phản ánh effort đã bị bỏ khỏi request.
19. **Popup và nút kéo bị co/mất kích thước:** class `w-68`, `h-7.5`, `h-5.5` không được Tailwind 3.4 tạo CSS. Dùng kích thước hợp lệ: popup 272 px, thanh 30 px, thumb 24 px. Trình duyệt đo được 272 × 116 px; ở viewport 320 px popup nằm trong màn hình và `scrollWidth=320`. Ảnh: `artifacts/ui-review/composer-latest-dark-20261108.png` và `composer-latest-mobile-20261108.png`; fixture ghi rõ không gọi provider.
20. **Inventory phân phối lệch source:** child process cô lập ghi nhận 121 agent tools, 87 MCP tools, 91 skills, 31 presets. Đồng bộ manifest và bảy README; phân loại export report là thao tác ghi artifact riêng, giữ các chặn đặt/hủy lệnh qua MCP.

## Kiểm thử đã chạy và giới hạn của kết quả

- Frontend toàn bộ sau nhóm sửa session/report: **123 file / 1.121 test đạt**. Bổ sung goal async sau đó: **26 test / 3 file đạt**. Popup được kiểm bằng browser tại desktop và 320 px sau khi sửa CSS. Cần gắn kết quả với thời điểm chạy vì worktree vẫn có thay đổi song song.
- Grounding + chart + report-evidence + replay: **1.264 đạt, 2 bỏ qua**. Một nhóm rộng trước đó đạt 1.349; không cộng số test trùng nhau.
- Session lifecycle/restart/tool-trail sau fault injection: **30 đạt**. Các test trước sửa chứng minh mất checkpoint, mất partial trên exception và completed bị đổi thành failed vì FTS.
- Report depth/integrity/preview/CLI/định dạng file và shadow account: **157 đạt**. Tests đếm trang dùng PDF tổng hợp được ghi rõ là fixture, không phải báo cáo đầu tư thật.
- Provider/model/context sau cache isolation và effort rejection: **186 đạt**. Compaction/accounting độc lập: **112 đạt, 1 bỏ qua**; năm failure cũ xuất phát fixture/assertion không còn phản ánh hợp đồng transactional mới, không nới runtime để khớp test.
- AKShare/fallback, tỷ giá/portfolio, artifact hash và concurrency: **221 đạt, 1 bỏ qua**; XML `loader-portfolio-artifact-followup.xml`. Manifest/MCP/tài liệu: **187 đạt, 1 bỏ qua**; XML `manifest-after.xml`. Không cộng các test trùng nhau giữa các nhóm.
- Baseline backend `-m unit`, chặn kết nối ra ngoài loopback: **2.106 đạt, 73 bỏ qua, 1 thất bại**, còn 19.631 deselected. Thất bại là gate locale version so `v0.3.2` với package `v0.1.18`; chưa tự đổi version của các thay đổi song song để làm test xanh.
- Baseline rộng `-m "not integration"`, loại E2E model thật, chặn kết nối ngoài loopback: **21.529 đạt, 70 thất bại, 208 bỏ qua, 17 deselected**, 959 giây. Đây là baseline trước các follow-up nêu trên, chưa phải kết quả cuối. XML `backend-offline.xml`; chi tiết từng failure: `backend-failures.json`.
- Ruff đạt cho các mô-đun session/report và các phần loader/portfolio vừa sửa. Frontend TypeScript + Vite build đạt sau nhóm session/goal/report; có cảnh báo chart bundle lớn hơn 500 kB. Desktop build và kiểm tra resolution/locales/packaging/update safety đạt bằng fixture; chưa chạy bộ cài Electron thật.

Các bộ test dùng runtime root riêng trong thư mục tạm. Không gọi model trả phí, đặt lệnh, deploy, cấp quyền tài khoản hoặc ghi credentials thật. `pytest-socket` đã có trong dev dependencies được cài vào venv để chạy baseline với hạn chế mạng.

## Điều kiện chưa đạt

Audit chưa hoàn tất. Cần đọc kết quả baseline rộng, xử lý lỗi thực thay vì nới assertion, kiểm tra các khu vực còn mở trong ma trận và nghiệm thu runtime phù hợp với phạm vi từng yêu cầu. Nguồn BCTC `.VN` cho phiên MBB chưa được cấu hình; bảy lần đọc URL của phiên gốc cũng thất bại. Không thể dùng việc sửa renderer, số trang hay màu sắc để kết luận dữ liệu tài chính đã đủ cho khuyến nghị đáng tin cậy.

Không có báo cáo đầu tư mới 24 trang với BCTC gốc được xác minh trong đợt này. Không tuyên bố chứng nhận CFA, mức sinh lời hoặc khả năng dự đoán từ kết quả kiểm thử phần mềm.
