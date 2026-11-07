# Rà soát logic grounding và báo cáo FPT — 07/11/2026

Đã sửa đường kiểm tra bằng chứng, kiểm tra đầu vào báo cáo và đường xuất/tải tài liệu. Giữ nguyên các thay đổi khác đang có trong workspace. Không thực hiện lệnh giao dịch, không gọi mô hình trả phí và không thay đổi cấu hình giao dịch.

## Lỗi grounding đã tái hiện và sửa

| Lỗi | Hành vi sau sửa |
| --- | --- |
| Phần số thô cho phép nhầm triệu thành tỷ | So khớp giá trị tại đúng hệ số đơn vị đã viết. |
| Dung sai gần 0 chấp nhận sai dấu hoặc sai nhiều lần | Dùng dung sai tương đối, giữ ranh giới dấu và giá trị 0. |
| Tràn số thành Infinity vượt kiểm tra nguồn | Loại giá trị không hữu hạn ở lúc trích xuất và so khớp. |
| Nguồn hiển thị không liên quan che nguồn thực sự hỗ trợ số | Chính nguồn chứa giá trị phải hiện cạnh câu hoặc trong caption bảng. |
| Mất mã doanh nghiệp khi chỉ có dữ liệu tài chính | Giữ định danh từ bằng chứng tài chính có kiểu. |
| Header năm chưa giới hạn kỳ dữ liệu | Ràng buộc năm, quý và ngày ISO của cột. |
| Số cổ phiếu hợp lệ bị loại khi đổi cách viết tỷ/triệu/nghìn | Chấp nhận cách viết tương đương, vẫn chặn sai đơn vị tiền, hệ số và dấu. |

Các trường hợp này có 21 ca hồi quy trong `agent/tests/test_grounding_deep_regressions.py`.

## Lỗi báo cáo và xuất tài liệu

- Không xóa `(omitted※)` để che số liệu thiếu; từ chối payload và yêu cầu sửa bằng chứng. Kiểm tra cả section Pydantic lồng nhau. Ghi chú hợp lệ bắt đầu bằng `※` được giữ lại.
- Chặn NaN/Infinity, metric trùng key, giá không dương, ngày metric vượt ngày chốt, đơn vị giá không đồng nhất và upside sai công thức. Dung sai làm tròn không tự tăng theo độ lớn của số.
- Payload không thể tự nâng trạng thái lên `certified`; dữ liệu giả lập có trạng thái riêng và được ghi rõ trên giao diện.
- Job được lưu bằng JSON thay thế nguyên tử trong đúng runtime root; liên kết không biến mất khi khởi tạo lại service hoặc cache đầy.
- Dọn đúng thư mục staging do job sở hữu. Khi PDF thiếu hoặc một lần lưu artifact thất bại, giữ tài liệu đã tạo được và trả trạng thái `partial` cùng lỗi.
- Tool/CLI không báo thành công trọn vẹn cho job thiếu định dạng. Frontend chấp nhận tải phần đã sẵn sàng và hiện cảnh báo; không coi dữ liệu giả lập là báo cáo chính thức.
- Chuyển DOCX sang PDF trong thư mục đầu ra tạm riêng; không nhận nhầm PDF cũ nếu LibreOffice không sinh file mới.
- Sửa chart âm/zero, target bị cắt khỏi trục, màu downside, đơn vị giá, thanh volume chồng nhau và volume thiếu. Caption giữ ghi chú nguồn của chuỗi.
- Mục lục lấy từ nội dung thật; chapter có ngắt trang, PDF có bookmark. Tách ngày giá tham chiếu khỏi ngày lập báo cáo, dùng đúng nhãn định giá do nội dung cung cấp.
- Đóng gói kèm logo PNG và template JSON cho bản cài đặt Python.

## Nội dung FPT

Hai template đã được thay bằng bản dựa trên tài liệu có nguồn. Bản chuyên sâu có 24 chuyên đề riêng, không lặp các đoạn phụ lục để kéo dài. Những giá/chuỗi giá, chuyên viên và mô hình DCF không có căn cứ đã được loại bỏ.

Đối chiếu trực quan bản quét BCTC: trang in 6 xác nhận lợi nhuận, EPS và lợi ích không kiểm soát; trang 7 cung cấp số cùng phạm vi hợp nhất; trang 9 xác nhận CFO và CAPEX. LNST tổng thấp hơn LNST cổ đông mẹ là hợp lý khi lợi ích không kiểm soát âm, không phải tự động là xung đột nguồn.

Giá 50.400 đồng trong tài liệu tham khảo thuộc ngày 03/11/2026. EPS dự phóng 5.624 đồng thuộc tài liệu bên thứ ba; P/E 8/11/14 là giả định phân tích, cho các giá trị 44.992/61.864/78.736 đồng. Bản nháp nêu chưa mua mới khi thiếu giá xác nhận; vùng mua có điều kiện không quá 49.000 đồng chỉ được dùng khi các cổng EPS, đơn hàng và tiền thu được đáp ứng. BÁN/GIẢM phụ thuộc việc luận điểm hỏng hoặc giá vượt giá trị mô hình chưa nâng. Các ngưỡng phải cập nhật theo dữ liệu và sự kiện doanh nghiệp.

## Kiểm chứng

- Grounding: **1.359 passed, 2 skipped** trên toàn bộ file kiểm thử grounding tường minh, bằng Python 3.12 trong `.venv`.
- Service/schema/renderer/CLI báo cáo: **57 passed**.
- Các đường báo cáo nghiên cứu, artifact, PDF và runtime root liên quan: **89 passed**.
- Frontend report validator/card và các màn hình xuất báo cáo/hội đồng liên quan: **21 passed**.
- `npm run build`: thành công. Ruff cho các file sửa trong phạm vi này: sạch.
- PDF xuất cuối: **30 trang**, có 33 bookmark; kiểm tra text, logo, DOCX và ảnh render toàn bộ trang. Xác nhận không có marker lược số hay ký tự thay thế trong text xuất.

Tái tạo báo cáo bằng môi trường đã có LibreOffice:

```powershell
.\.venv\Scripts\python.exe -X utf8 agent\generate_fpt_report.py
```

CLI mặc định dùng template chuyên sâu, kiểm tra tối thiểu 24 trang PDF trước khi sao chép cả PDF và Word vào `output/pdf`. Có thể truyền `--output-dir` hoặc `--template` khi cần.

## Giới hạn

Không chạy toàn bộ bộ kiểm thử backend/frontend, không kiểm tra bản desktop đóng gói, không xác nhận báo giá có thể khớp lệnh hiện tại hoặc kết quả đầu tư thật. Kiểm tra trích dẫn chỉ chứng minh một con số xuất hiện trong nguồn thu được; không chứng minh nguồn đó độc lập, chính xác tuyệt đối hoặc phản ánh đúng ngữ nghĩa của mọi chỉ tiêu. Báo cáo giữ trạng thái `draft_unverified`.
