# Model, context và luồng xuất nghiên cứu — 07/11/2026

## Hành vi sau sửa

- Ô chat có nút chọn model/mức suy nghĩ và chỉ báo context. Lựa chọn áp dụng cho lượt tiếp theo; không đổi cấu hình giữa lượt đang chạy.
- Chat mới và chat cũ đều dò `/settings/llm/context` trước khi đọc context của session. Refresh yêu cầu đọc lại metadata.
- Giới hạn được gắn với đúng provider, endpoint và ID model, kể cả ID có tiền tố hoặc hậu tố phiên bản. Đổi endpoint không dùng lại metadata của gateway khác.
- Thứ tự ngân sách: cấu hình người vận hành, giới hạn học từ lỗi provider, metadata tường minh, catalog có phạm vi endpoint, rồi giới hạn dự phòng. Danh sách chỉ có ID không chứng minh cửa sổ context.
- Giao diện ghi rõ nguồn/độ xác nhận; chưa có prompt thì không suy ra phần trăm sử dụng. Tổng token tính phí không được dùng làm mức chiếm context hiện tại.
- Trước request, ngân sách tính cả system prompt, schema tool, lịch sử và phần dành cho đầu ra; nén tự động theo ngân sách. Khi tóm tắt thất bại, giữ nguyên lịch sử và không gửi một prompt đã biết vượt giới hạn.
- Mức suy nghĩ được giới hạn theo adapter/model; cấu hình mà adapter bỏ qua không được quảng bá là đang áp dụng. Custom gateway chưa xác nhận hỗ trợ dùng mặc định provider. Runtime lấy mức thực sự truyền qua adapter.

## Báo cáo và dữ liệu

- Giá giao dịch cuối cùng tách khỏi OHLC đã điều chỉnh. Quan sát phải có mã, sàn, đơn vị, thời điểm, cơ sở điều chỉnh và URL.
- Sổ bằng chứng gắn cả chuỗi OHLC và quan sát giá với nội dung công cụ đã thu thập. Công cụ xuất chỉ nhận sổ của lượt đang gọi qua `ContextVar`; JSON không tự cấp được bằng chứng tin cậy bằng `run_id` hoặc nhãn `verified`.
- Mọi bề mặt số liệu có attribution: chỉ tiêu, điểm nhấn, văn bản, bảng/ô, chuỗi biểu đồ, kịch bản và sự kiện. DOCX/PDF/PPTX có liên kết nguồn ngay sau dữ liệu; danh mục cuối tài liệu ghi URL đầy đủ.
- Dữ liệu tính toán/giả định có nhãn, phương pháp và đầu vào. Đường tỷ lệ của biểu đồ chuyên đề được máy chủ tính từ chuỗi có nguồn, không chấp nhận số gõ tự do mang nhãn suy ra.
- Không tự chèn bảng hoặc giá trị riêng cho FPT. Renderer lấy số liệu từ báo cáo đã qua kiểm tra. Không đặt giá mục tiêu thô lên chuỗi giá điều chỉnh khác cơ sở hoặc đơn vị.
- `omitted※`, NaN/Inf, số liệu thiếu URL, giá sai mã/sàn/đơn vị/ngày và nguồn chưa được thu thập trong lượt bị chặn. Xuất khuyến nghị mua/bán cần đủ bằng chứng giá và cơ sở định giá; không chỉ đổi nhãn trong khi vẫn xuất một khuyến nghị thiếu căn cứ.
- Đầu ra giữ trạng thái dự thảo; không tự tuyên bố được CFA chứng nhận hay chuyên viên phê duyệt.
- Công cụ mặc định xuất DOCX, PDF và PPTX từ cùng dữ liệu. Job và liên kết tải tồn tại qua lần khởi tạo lại service. Một định dạng lỗi không làm mất file khác đã xuất.
- Bấm DOCX/thẻ tài liệu mở sidebar. PDF cùng bộ tài liệu được dựng thành PNG từng trang để hoạt động trong WebView không có PDF plugin. Tải file gốc ở ba nút bên dưới; preview có xác thực, kiểm tra số trang và giới hạn kích thước ảnh.
- CLI có tên lịch sử `generate_fpt_report.py` nhận template bắt buộc cho bất kỳ mã nào, xuất ba định dạng và kiểm tra tối thiểu 24 trang theo mặc định. Không lấy FPT tĩnh làm dữ liệu mặc định. Template thiếu hợp đồng bằng chứng mới phải được bổ sung trước khi xuất.

## Bằng chứng kiểm tra

- `artifacts/market-data-audit-20261107/validation_summary.json`: ba HTTP request thật, tắt cache loader; FPT.VN 50.800 VND, VCB.VN 53.600 VND, HPG.VN 21.200 VND. Quan sát thuộc phiên 06/11/2026, thu thập ngày 07/11/2026. Đây là snapshot có thời điểm, không phải cam kết giá trực tiếp.
- `tmp/report-evidence-smoke/verification.json`: phát lại chính ba snapshot trên qua sổ bằng chứng và service; mỗi mã xuất đủ DOCX/PDF/PPTX, giữ đúng giá và nguồn. Mỗi bản kiểm chứng có 3 trang PDF và 7 slide; chúng là kiểm tra luồng, không phải báo cáo nghiên cứu 24 trang.
- `artifacts/model-context-metadata-20261107.json`: đã nạp cấu hình dotenv và thực hiện dò metadata với custom model `deepseek-ai/deepseek-v4.1-flash-1017`. Request không báo lỗi nhưng không cung cấp giới hạn được nhận diện cho đúng ID này; kết quả là ngân sách dự phòng 128.000, không phải xác nhận cửa sổ thực của model. Không gọi completion.
- Đã mở ảnh render từ DOCX/PDF và chuyển PPTX qua LibreOffice để kiểm tra bố cục, logo, giá, biểu đồ và liên kết nguồn. Kiểm tra ZIP/relationships xác nhận DOCX và PPTX có URL bấm được.
- Nhóm model/settings/adapter: 221 passed, 7 skipped do adapter tùy chọn. Các kiểm tra context budget, compaction identity và session cũng đã chạy đạt trong đợt kiểm tra riêng.
- Grounding và dữ liệu giá: 1.170 passed, 2 skipped; không có lỗi sau khi bổ sung nguồn cho OHLC.
- Nhóm schema/evidence/renderer/service/preview/CLI/context công cụ: 89 passed; 35 kiểm thử trên hai file chịu ảnh hưởng cũng đạt sau khi bổ sung kiểm tra biểu đồ trong PPTX và nhãn cơ sở điều chỉnh.
- Frontend: 72 kiểm thử liên quan đạt; production build đạt. Xem `artifacts/ui-review/README.md` và ảnh tại đó: 320, 390 và 1280 px; dữ liệu UI được ghi rõ là giả lập.
- Ruff trên phạm vi Python đã thay đổi và `git diff --check` đạt.

## Giới hạn cần giữ rõ

Không gọi model trả phí, không đặt lệnh và không khởi động lại tiến trình giao dịch. Chưa nghiệm thu provider thật cho nén context hoặc bản desktop đóng gói. Số token prompt vẫn là ước lượng có hiệu chỉnh từ usage, không phải tokenizer chính thức cho mọi model.

Endpoint chỉ trả ID không cho phép phát hiện chính xác cửa sổ hoặc mức suy nghĩ; hệ thống dùng giới hạn dự phòng minh bạch. Giá quá 72 giờ bị coi là cũ; kỳ nghỉ dài cần lịch giao dịch riêng. Kiểm tra số hiện diện trong nguồn không chứng minh đầy đủ ngữ nghĩa chỉ tiêu/kỳ kế toán; chất lượng khuyến nghị vẫn cần dữ liệu tài chính, mô hình định giá và thẩm định nội dung.

Các bản FPT tĩnh và file đã xuất từ trước không tự trở thành dữ liệu hiện tại sau khi sửa code. Không dùng chúng làm minh chứng giá mới hoặc khuyến nghị đã được phê duyệt.
