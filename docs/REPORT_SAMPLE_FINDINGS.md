# Đọc mẫu báo cáo FPT: cách lập luận, chất lượng dữ liệu và chuyển thành kịch bản giao dịch

Ngày rà soát: 06/11/2026. Đây là phân tích phương pháp từ bốn PDF người dùng cung cấp trong `docs/mau-baocao`, phục vụ thiết kế Vibe Trading. Các nhận định dưới đây về FPT là ví dụ lịch sử theo ngày tài liệu, không phải chỉ thị giao dịch tại thị trường hiện tại.

## 1. Phạm vi bằng chứng và giới hạn xác thực

Tên đơn vị phát hành trong tài liệu được ghi theo nội dung PDF. Chưa đối chiếu bản tải từ website của tổ chức phát hành, chưa xác minh chữ ký số, chứng thư, hay lịch sử sửa đổi bên ngoài. Logo, tên file, PDF metadata và dấu/chữ ký hiển thị không tự chứng minh tính xác thực của nhà phát hành. Các thông tin vĩ mô, quan hệ đối tác, số liệu khối ngoại và giá thị trường trong báo cáo môi giới cũng chưa được xác nhận độc lập.

Quy ước trích dẫn: **trang PDF là chỉ số trang bắt đầu từ 1**, khác số trang in trong báo cáo. Ví dụ, PDF BCTC Q3 trang 8 in số trang 7; BCTN trang PDF 164 in số 163.

| ID | Tài liệu cục bộ | Kỳ/ngày trong tài liệu | Trang | Cách đọc và vai trò |
| --- | --- | --- | ---: | --- |
| S1 | [Cập nhật KQKD Q3/2026](mau-baocao/20261104_FPT_Bao_cao_cap_nhat_KQKD_Q3_2026.pdf) | Tự ghi TCBS, 04/11/2026; giá tham chiếu báo cáo ngày 03/11/2026 | 8 | Trích văn bản từng trang; đọc phân tích và phụ lục. Dùng để học cách nối kết kết quả kinh doanh, ngành, tiền và định giá. |
| S2 | [Báo cáo phân tích FPT](mau-baocao/bao_cao_phan_tich_fpt.pdf) | Tự ghi VCBS; thị giá ngày 27/01/2026; metadata cũng ghi 27/01/2026 | 11 | Trích văn bản từng trang; đối chiếu ảnh trang 1–3, 9–10. Dùng để học luận điểm đầu tư và SOTP; phát hiện lỗi cần đối soát. |
| S3 | [Báo cáo thường niên 2025](mau-baocao/BCTN_2025_ad403f779b.pdf) | Năm 2025; phần kiểm toán ký ngày 19/03/2026 | 232 | Trích toàn bộ văn bản, đọc sâu các trang 10, 12, 60, 163–164, 169–172, 175, 217. Không tuyên bố đã kiểm tra mọi đoạn của 232 trang. |
| S4 | [BCTC hợp nhất Q3/2026](mau-baocao/FPT_Baocaotaichinh_Q3_2026_Hopnhat.pdf) | Chốt số liệu 30/09/2026; biểu ký 22/10/2026; công văn công bố 28/10/2026 | 54 | **Toàn bộ 54 trang không có lớp văn bản trích xuất được.** Đã render và đọc ảnh trang 1–10; chưa OCR/đọc đầy đủ thuyết minh trang 11–54. |

Đã chạy pypdf cho 305 trang. Có 251 trang thuộc ba tài liệu đầu có văn bản trích xuất, nhưng điều đó không tương đương xác minh 251 trang. S4 có 0 ký tự trích xuất, nên các số liệu S4 dưới đây là **đọc ảnh thủ công các trang được nêu**, cần người kiểm tra thứ hai trước khi nạp vào sản phẩm quyết định tài chính.

Bằng chứng cục bộ gồm [manifest trích xuất](../.codex-backups/2026-11-06-report-methodology/extraction-manifest.json), [các phép tính](../.codex-backups/2026-11-06-report-methodology/calculations.json), văn bản từng trang và ảnh kiểm tra. Manifest giữ SHA-256 của từng PDF, từng trang văn bản, số ký tự và cờ cần đọc ảnh. Việc giữ bản trích xuất phục vụ kiểm tra nội bộ, không cấp quyền tái xuất bản báo cáo.

## 2. Họ trả lời như thế nào?

### 2.1. S2: Kết luận trước, rồi dựng luận điểm và mô hình định giá

Trang 1 đặt khuyến nghị, giá mục tiêu, mức sinh lời kỳ vọng, thị giá và ba nhóm luận điểm ở đầu. Phần thân đi theo trình tự: kết quả thực hiện → diễn giải nguyên nhân → tín hiệu đi trước như hợp đồng ký mới → giả định năm tới → định giá từng mảng → tổng giá trị cổ phiếu. Trang 8 tách một số giả định doanh thu theo thị trường; trang 9–10 cho người đọc thấy cách cộng các bộ phận bằng SOTP.

Đơn vị phân tích không chỉ báo doanh thu tăng. Họ tách Nhật, Mỹ, APAC, châu Âu; nối chi tiêu CNTT, tỷ giá, hợp đồng và điểm rơi ghi nhận doanh thu với tăng trưởng; xem riêng viễn thông, giáo dục và AI Factory. Trang 6 có ý kiến thận trọng về mức sử dụng AI Factory và cạnh tranh, dù kết luận chung vẫn là mua. Đây là cách trình bày hữu ích: luận điểm tích cực phải đi cùng phần có thể làm luận điểm thất bại.

Tuy nhiên, kết luận mạnh không khắc phục được lỗi dữ liệu bên dưới. Những chênh lệch số học và nhãn chỉ tiêu ở mục 6 cần được chặn trước khi AI kế thừa định giá.

Trang 11 quy định hệ thống khuyến nghị theo **khả năng sinh lời trong 6 tháng**, mặc định gồm tăng giá đã điều chỉnh và cổ tức dự kiến. Vì vậy, chữ MUA trong S2 không có nghĩa là mua bằng mọi giá ngay trong phiên, càng không tự chỉ định ATO hay MTL.

### 2.2. S1: Đánh giá chất lượng tăng trưởng, chứ không chỉ so giá mục tiêu

Trang 1 trả lời trực tiếp trạng thái: định giá đã thấp nhưng tài liệu cho rằng chưa nên giải ngân, do hợp đồng mới chậm lại và áp lực bán. Trang 2 phân tích chất lượng lợi nhuận; trang 3 nối vĩ mô, ngành, tỷ giá và thông tin AI; trang 4–5 phân tích biên lợi nhuận, chi phí, phải thu và dòng tiền; trang 6–7 đưa phụ lục số liệu và giả định.

Mỗi đoạn thường có ba tầng: **quan sát có số → cơ chế giải thích → hệ quả/rủi ro cần theo dõi**. Ví dụ, ký mới giảm tốc không trực tiếp làm doanh thu quý vừa qua sụt, nhưng có thể ảnh hưởng doanh thu tương lai. Tài liệu nêu mức tăng ký mới riêng Q3 chỉ 3,6%, khác mức tăng lũy kế 9 tháng 23,1%; đây là việc tách xu hướng gần nhất khỏi con số lũy kế đẹp hơn.

Điểm đáng học là câu trả lời có điều kiện: chỉ ra điều gì cần thay đổi để đánh giá chuyển hướng. Điểm cần cải thiện là giữ thống nhất phạm vi hợp nhất và loại lợi nhuận khi chuyển từ tiêu đề sang đồ thị/phụ lục.

### 2.3. S3 và S4: Nguồn số liệu và cách trình bày của doanh nghiệp

BCTN chia chiến lược, thị trường, quản trị, ESG, kết quả hoạt động và BCTC. Phần điều hành lý giải theo mảng kinh doanh; phần kiểm toán và thuyết minh đặt giới hạn cho các suy diễn từ phần truyền thông. Phải đọc cả hai, thay vì chỉ lấy thông điệp lãnh đạo để coi như kết luận đầu tư.

S3 trang 164 có ý kiến kiểm toán về BCTC 2025 và một vấn đề cần nhấn mạnh về cơ sở hợp nhất FTEL; chính tài liệu nói ý kiến không bị ảnh hưởng bởi vấn đề này. Không đổi nhãn vấn đề nhấn mạnh thành ý kiến ngoại trừ, cũng không bỏ qua nó chỉ vì ý kiến kiểm toán không sửa đổi.

S4 trang 8 đặc biệt hữu ích: doanh nghiệp đưa cả so sánh công bố và bảng kỳ trước điều chỉnh cùng phương pháp kế toán. Hệ thống AI nên giữ được hai cơ sở này thay vì chọn một con số tăng trưởng rồi loại bỏ con số còn lại.

## 3. Một quy trình phân tích cơ bản sâu rút ra từ mẫu

| Lớp phân tích | Câu hỏi phải trả lời | Số liệu/nguồn cần nối | Sai sót cần chặn |
| --- | --- | --- | --- |
| Chất lượng nguồn | Dữ liệu này do ai công bố, lúc nào đã có thể biết, có sửa đổi không? | Nguồn gốc, URL, kỳ, thời điểm công bố, bản sửa đổi, trang, hash, tình trạng kiểm toán | Lấy PDF mới để suy luận quyết định trong quá khứ; biến metadata thành bằng chứng xác thực |
| Ngành và tin tức | Tin thay đổi doanh số, giá, chi phí hay rủi ro nào? Khi nào tác động? | Thông cáo gốc, khách hàng/đối tác, chi tiêu ngành, tỷ giá, văn bản pháp lý | Coi ký hợp tác là doanh thu đã ghi nhận; đếm nhiều báo đăng lại như nhiều nguồn độc lập |
| Cầu và hợp đồng | Đơn hàng có thật, quy mô, tốc độ ký và thời gian chuyển thành doanh thu? | Ký mới, backlog, tỷ lệ hủy, khách hàng tập trung, hợp đồng theo khu vực | Cộng ký mới với doanh thu; suy ra quy mô bình quân từ hai ngưỡng hợp đồng khi thiếu phân bố |
| Kết quả kinh doanh | Tăng trưởng đến từ sản lượng, giá, tỷ giá, mua bán công ty hay thay đổi hợp nhất? | Doanh thu từng mảng, gross/net, reported/comparable, QoQ/YoY, biên gộp và chi phí | Gộp số quý với lũy kế; coi tăng trưởng kế toán là tăng trưởng hữu cơ |
| Lợi nhuận | Bao nhiêu đến từ vận hành lặp lại, tài chính, liên kết, hoàn nhập hay bán tài sản? | LNST hợp nhất, LNST cổ đông mẹ, NCI, lãi liên kết, lãi tỷ giá và thuyết minh | Trộn LNST mẹ với tổng LNST; tự loại hết lãi liên kết như một lần mà chưa xét mô hình kinh doanh |
| Tiền của doanh nghiệp | Lợi nhuận chuyển thành tiền ra sao? Tiền có thực sự tự do sử dụng không? | CFO, capex, phải thu, tồn kho, trả trước, phải trả, cổ tức từ liên kết, tiền gửi hạn chế | Gọi CFO-capex là FCFF/FCFE hoàn chỉnh; coi lãi tiền gửi/cổ tức nhận gộp là cổ tức riêng FTEL |
| Tiền trên thị trường | Ai đang giao dịch, trong thời gian nào và ở loại giao dịch nào? | Khớp lệnh/thỏa thuận, ngoại/tự doanh/quỹ, lượng/giá trị, tỷ trọng, thanh khoản | Đồng nhất bán ròng với tất cả dòng tiền rút khỏi doanh nghiệp; coi mua chủ động là ý định chắc chắn của nhà đầu tư |
| Định giá | Giá trị phụ thuộc giả định nào? Kịch bản nào đã phản ánh vào giá? | PE/PB/DCF/SOTP, cơ sở EPS/BVPS, WACC/Ke, g, nợ-tiền, số cổ phiếu | Trộn mô hình FCFF với Ke/FCFE với WACC; cộng trùng liên kết trong SOTP; dùng EPS khác cơ sở điều chỉnh |
| Phản biện | Dữ liệu nào trái luận điểm? Điều kiện nào khiến bỏ kịch bản? | Mâu thuẫn nguồn, ngành, giá, tiền, vận hành | Ép mọi thông tin thành câu chuyện tăng giá; nâng tương quan thành nguyên nhân |

Đặc biệt cần tách ba khái niệm thường đều được gọi là dòng tiền: **tiền từ kinh doanh của doanh nghiệp**, **luồng giao dịch cổ phiếu theo nhóm nhà đầu tư**, và **cung cầu/khớp lệnh rất ngắn hạn**. Mỗi lớp có dữ liệu, kỳ và ý nghĩa khác nhau. Một doanh nghiệp có CFO tốt vẫn có thể bị bán mạnh; một phiên giá tăng không chứng minh tiền kinh doanh cải thiện.

## 4. Ví dụ FPT: đọc lại cùng số liệu nhưng giữ đúng mẫu số

Các số trong bảng quy đổi về **tỷ VND**, làm tròn trình bày; dữ liệu đầy đủ ở bằng chứng. Đây là số trong bộ mẫu chưa xác thực bên ngoài.

| Chỉ tiêu | Số liệu được đọc | Vị trí và ý nghĩa |
| --- | ---: | --- |
| Doanh thu thuần Q3/2026 | 13.754,159 | S4 trang 7. Không phải số lũy kế. |
| Tăng trưởng doanh thu Q3 so với báo cáo 2025 nguyên trạng | -20,1% | S4 trang 8, bảng trên; khác phạm vi hợp nhất FTEL. |
| Tăng trưởng doanh thu Q3 trên cơ sở 2025 được điều chỉnh cùng phương pháp | +12,1% | S4 trang 8, bảng dưới. Phản ánh khác biệt cơ sở so sánh, không phải hai quan sát độc lập. |
| Tăng trưởng doanh thu 9 tháng cùng cơ sở điều chỉnh | +12,4% | S4 trang 8, bảng dưới. |
| LNST hợp nhất Q3/2026 | 2.729,314 | S4 trang 7; tăng +13,2% theo bảng điều chỉnh S4 trang 8, nhưng -5,9% theo kỳ trước nguyên trạng. |
| LNST cổ đông mẹ Q3/2026 | 2.723,123 | S4 trang 7; khác tổng LNST 2.729,314. |
| LNST hợp nhất 9 tháng | 7.776,442 | S4 trang 7. |
| LNST cổ đông mẹ 9 tháng | 7.778,081 | S4 trang 7; NCI là khoản lỗ khoảng -1,639, nên phần mẹ nhỉnh hơn tổng không tự là lỗi. |
| CFO 9 tháng | 951,978 | S4 trang 10, dòng mã 20. |
| Tiền chi mua sắm, xây dựng TSCĐ và tài sản dài hạn khác 9 tháng | 2.028,801 | S4 trang 10, mã 21, dòng chi âm trong báo cáo; chưa tách capex duy trì/tăng trưởng. |
| Lãi hoạt động đầu tư điều chỉnh khỏi CFO | 3.541,026 | S4 trang 10, mã 05. Đây là nhãn gộp; chưa đọc đủ thuyết minh để phân bổ toàn bộ cho một khoản liên kết. |
| Tiền thu lãi cho vay, cổ tức và lợi nhuận được chia | 1.245,974 | S4 trang 10, mã 27. Không phải bằng chứng rằng riêng cổ tức liên kết là 1.245,974. |

Từ những số trên, CFO/LNST mẹ 9 tháng xấp xỉ **0,1224 lần**; nếu dùng tổng LNST thì khoảng **0,1224 lần** nhưng cần ghi rõ mẫu số. CFO cùng phạm vi doanh nghiệp hợp nhất chia tổng LNST hợp nhất có tính tương ứng tốt hơn cho phân tích chất lượng tiền; CFO/LNST mẹ vẫn có thể là một chỉ báo bổ sung nếu nhãn và giới hạn rõ ràng.

Phép tính giản lược **CFO trừ dòng tiền chi mua sắm TSCĐ/tài sản dài hạn khác = -1.076,823 tỷ VND**. Gọi là chỉ báo tiền còn lại sau dòng chi này; không tự thay thế FCFF hay FCFE đã chuẩn hóa. Cần kiểm tra thay đổi phạm vi hợp nhất, biến động vốn lưu động, tính mùa vụ, tiền hạn chế sử dụng, lãi vay/thuế, tài sản dài hạn khác và nhu cầu đầu tư. CFO thấp trong một kỳ là tín hiệu cần giải thích, chưa chứng minh lợi nhuận không có thật hoặc doanh nghiệp có gian lận.

Khoản lãi liên doanh/liên kết trên S4 trang 7 là khoảng 796,904 tỷ trong Q3 và 2.220,303 tỷ trong 9 tháng. Nó khác dòng lãi đầu tư 3.541,026 tỷ điều chỉnh trên báo cáo tiền. Vì vậy không gắn toàn bộ số 3.541,026 cho riêng lãi liên kết mà chưa có reconciliation từ thuyết minh. Cũng không lấy chênh lệch 3.541,026 trừ 1.245,974 để gọi là số tiền chắc chắn còn phải thu của các công ty liên kết.

Về thời điểm, S2 có thị giá ngày 27/01/2026 trong khi phần kiểm toán BCTN chỉ ký 19/03/2026. Khi đánh giá lại quyết định tháng 1, không được dùng nhận định kiểm toán tháng 3 như thông tin đã biết ở tháng 1. S3 trang 175 sau đó giải thích cơ sở chuyển FTEL từ hợp nhất toàn bộ sang phương pháp vốn chủ trong năm 2026; S4 trang 8 cụ thể hóa việc so sánh lại kỳ trước. Hai báo cáo phải được lưu thành các phiên bản có thời điểm, không ghi đè một bản duy nhất.

## 5. Giá trị của hai kết luận môi giới khác nhau

S2 lấy thị giá 101.100 VND/cp ngày 27/01/2026, mục tiêu 121.909 VND/cp, tăng giá khoảng 20,6%, và sử dụng SOTP. S1 lấy giá 50.400 VND/cp ngày 03/11/2026 và đánh giá thận trọng dù PE dự phóng khoảng 9 lần. Các mốc này **không phải báo giá hiện tại**. Không thể chuyển thẳng mục tiêu cũ sang giá mới mà bỏ qua thời hạn 6 tháng của S2, thay đổi số cổ phiếu, cổ tức/quyền, mức giá đã điều chỉnh và cơ sở lợi nhuận.

Chênh lệch hai kết luận không tự chứng minh bên nào đúng. Tập thông tin, thời hạn, phương pháp và rủi ro thay đổi. Một cách trả lời tốt của Vibe Trading là nêu rõ: luận điểm nào còn giữ, luận điểm nào đã yếu đi, thông tin mới nào giải thích sự thay đổi, dữ kiện nào vẫn chưa đối soát. Không tính xác suất thắng hay dự báo khớp lệnh chỉ từ chênh lệch giữa hai giá mục tiêu.

## 6. Sổ mâu thuẫn và bất thường phải hiện ra cho người dùng

Các mục này là yêu cầu kiểm chứng dữ liệu, **không phải kết luận có gian lận hoặc tài liệu giả**. Chênh lệch có thể do lỗi nhập, làm tròn, cập nhật một phần, nhãn khác cơ sở hoặc nội dung mẫu chưa chuẩn. Đọc ảnh giúp loại bớt lỗi do trích xuất nhưng không thay thế kiểm tra nguồn gốc.

| Mã | Quan sát có thể kiểm tra | Vị trí | Hệ quả khi AI trả lời |
| --- | --- | --- | --- |
| A01 | Cùng doanh thu Q3 có -20,1% reported nhưng +12,1% comparable sau thay đổi FTEL | S4 trang 8; S1 trang 1, 6 | Phải hiển thị hai cơ sở. Không nói doanh thu kinh doanh hữu cơ sụt 20,1%. |
| A02 | S1 tiêu đề dùng LNST mẹ 2.723 tỷ/+11,8%; đồ thị và phụ lục dùng tổng LNST khoảng 2.729 tỷ/-5,9% | S1 trang 1–2, 6; đối chiếu S4 trang 7–8 | Không dùng hai số như một chỉ tiêu. Tách owner, basis và comparator. |
| A03 | CFO 9 tháng chỉ khoảng 12,24% LNST; chỉ báo CFO trừ dòng chi mua TSCĐ âm khoảng 1.076,823 tỷ | S4 trang 7, 10 | Giải thích tiền/vốn lưu động/phạm vi, không chuyển thành phán quyết bán tự động. |
| A04 | S1 diễn giải lãi đầu tư 3.541 tỷ như lãi liên kết chưa thu; S4 chỉ ghi dòng điều chỉnh gộp, còn lãi liên kết trên KQKD là 2.220 tỷ | S1 trang 2, 5; S4 trang 7, 10 | Yêu cầu cầu nối thuyết minh; hạn chế độ chắc chắn của nhận định. |
| A05 | CAPM hiển thị Rf 3%, phần bù 8,35%, beta 1,39 nhưng Ke ghi 10,8%; tính trực tiếp ra 14,6065% | S2 trang 9, đã đọc ảnh | Định giá chưa tái lập được với thông số hiển thị. Chặn dùng Ke đó trong mô hình kiểm chứng cho đến khi giải thích. |
| A06 | Tiêu đề định giá viễn thông ghi FCFF nhưng đầu bảng ghi FCFE; WACC 8,1% được nêu | S2 trang 9, đã đọc ảnh | Xác định đúng dòng tiền và hệ số chiết khấu, làm rõ cầu nối EV sang vốn chủ. |
| A07 | Giá trị vốn chủ viễn thông hiển thị 72.437 tỷ nhân sở hữu 45,66% là khoảng 33.074,734 tỷ, khác giá trị mảng 36.435 tỷ | S2 trang 9, đã đọc ảnh | Cần cầu nối điều chỉnh khác/tỷ lệ khác; không tự sửa cho khớp. |
| A08 | PV phần tăng trưởng vĩnh viễn 71.241 tỷ chiếm khoảng 77,06% tổng hai PV 21.205 + 71.241 tỷ | S2 trang 9 | Đây là độ nhạy mô hình, không phải lỗi số học; phải thử WACC/g và kịch bản tăng trưởng. |
| A09 | Tổng bốn giá trị SOTP hiển thị 207.612 tỷ, bảng ghi 207.611 tỷ; cổ phiếu chỉ hiển thị 1,7 tỷ | S2 trang 10 | Chênh 1 tỷ có thể do làm tròn; yêu cầu số chính xác trước khi gắn cờ nghiêm trọng. Không coi mọi lệch nhỏ là bất thường trọng yếu. |
| A10 | Bảng S2 trang 2 hiển thị doanh thu Q4 từ 20.258 xuống 17.651 nhưng ghi YoY +14,7%; trang 1 lại nêu Q4/2025 20.225 tỷ | S2 trang 1–2, đã đọc ảnh trang 2 | Không tự chọn một ô; đối soát kỳ, thứ tự cột, gross/net và nguồn doanh nghiệp. |
| A11 | Bảng quốc tế S2 Q4 ghi 13.525 tỷ, trùng số mảng công nghệ ở trang 2; bốn vùng liệt kê cộng thành 9.808 tỷ | S2 trang 2–3, đã đọc ảnh | Có thể thiếu vùng/khác phạm vi/nhầm nhãn; chưa đủ cơ sở tổng hợp hoặc dự phóng tự động. |
| A12 | S2 ghi LNST 2025 khoảng 11.226 tỷ; S3 bản sau ghi 11.232,339 tỷ và LNST mẹ 9.376,128 tỷ | S2 trang 1; S3 trang 170 | Có thể là số sơ bộ trước kiểm toán so với bản sau. Giữ phiên bản, không hồi tố biết trước kết quả kiểm toán. |
| A13 | S3 EPS 2025 là 5.216 VND; S1 phụ lục ghi EPS 2025 là 5.504 VND theo cách dựng bảng riêng | S3 trang 10, 170; S1 trang 7 | Chưa thống nhất cơ sở EPS, trích quỹ, số cổ phiếu bình quân/cuối kỳ và điều chỉnh quyền. Không lấy PE/EPS từ hai cơ sở để so trực tiếp. |
| A14 | S2 nhãn KLGD là triệu cổ phiếu nhưng ô ghi 8.025.267; giá mục tiêu ô tóm tắt 121,91 trong khi nội dung ghi 121.909 VND | S2 trang 1 | Bắt buộc chuẩn hóa unit và thang đo. Không đọc 8 triệu thành 8 triệu triệu, hay 121,91 VND thành 121.909 VND không có quy tắc. |
| A15 | Giá, giao dịch ngoại, hợp tác AI và vĩ mô chủ yếu xuất hiện trong nguồn môi giới, không có bộ dữ liệu độc lập kèm theo | S1 trang 1–3, 5 | Gắn nhãn theo báo cáo cung cấp; không trình như feed hiện tại hay tin đã xác minh đa nguồn. |

Các số A05/A07 là kiểm tra tính nhất quán **nội bộ theo ô hiển thị**; chúng không chứng minh giá trị thực của FPT. A08 là rủi ro độ nhạy; A09 có thể là làm tròn. Hệ thống phải phân biệt loại cảnh báo thay vì cho mọi cảnh báo cùng một mức độ.

## 7. Phần chart nến và giao dịch còn thiếu trong bộ mẫu

Đã xem trực tiếp S2 trang 1: hình diễn biến giá là **đường giá và cột khối lượng**, không có OHLC mỗi nến, mốc thời gian đủ để tái dựng, sổ lệnh hay giá khớp dự kiến phiên định kỳ. S1 chủ yếu có đường chỉ số thị trường và biểu đồ kinh doanh. BCTN/BCTC là tài liệu tài chính. Bộ mẫu không cung cấp dữ liệu nến có cấu trúc, giao dịch realtime hoặc trạng thái tài khoản.

Do đó không thể từ bộ này xác nhận một mẫu nến, tính ATR/VWAP đúng dữ liệu, phát hiện phân kỳ giá-volume, định mức mua/bán trong phiên, dự đoán giá mở cửa, hay kết luận một lệnh ATO/MTL sẽ khớp ở giá cụ thể. Các mức 101.100; 121.909; 50.400; đáy/đỉnh 52 tuần trong báo cáo chỉ là số lịch sử/định giá theo nguồn, **không tự trở thành hỗ trợ, kháng cự hay vùng chờ đặt lệnh hiện tại**.

Để bổ sung phần này, mỗi bản phân tích cần tối thiểu:

1. OHLCV và giá trị giao dịch có nguồn, thời gian, timezone, độ trễ; cờ nến đóng/chưa đóng; dữ liệu intraday nếu nói về phiên.
2. Lịch corporate actions và hệ số điều chỉnh; giữ bản giá thô cho thực thi và giá điều chỉnh cho phân tích dài hạn.
3. Lịch giao dịch, sàn, mã, trạng thái giao dịch, giá tham chiếu/trần/sàn, bước giá/lô và tập lệnh được hỗ trợ có phiên bản theo ngày.
4. Quote/bid/ask và độ sâu có timestamp, khi cần đánh giá spread/thanh khoản/trượt giá; indicative auction price/volume nếu nguồn có và được phép dùng cho phiên định kỳ.
5. Quy mô dự kiến, tiền khả dụng, cổ phiếu được phép bán, phí/thuế và các giới hạn của người dùng trước khi tính khối lượng cụ thể.

Không lấp dữ liệu thiếu bằng một chỉ số có vẻ hợp lý. Nếu chỉ có ảnh chart thì có thể nhận xét hình học thận trọng, nhưng phải ghi độ tin cậy đọc ảnh và không biến nó thành chuỗi OHLC chính xác.

## 8. Cách chuyển phân tích thành câu trả lời có thể hành động

Nên kết thúc bằng một bảng kịch bản, chứ không chỉ một chữ MUA/BÁN. Mỗi kịch bản có **điều kiện, vùng giá có cơ sở, điều kiện hủy, thời hạn, chi phí và hạn chế dữ liệu**. Nếu chưa đủ đầu vào, ô giá/loại lệnh là chưa xác định, không tự tạo số.

| Trạng thái gợi ý | Điều kiện cần có | Cách diễn đạt đúng mức bằng chứng |
| --- | --- | --- |
| Cân nhắc mua tại vùng thị trường hiện tại | Luận điểm cơ bản hợp lệ; định giá đủ hấp dẫn theo khoảng giả định; tín hiệu giá/tiền xác nhận; quote còn mới và đủ thanh khoản; rủi ro phù hợp | Ghi thời điểm quote, khoảng giá tham chiếu, giá tối đa chấp nhận, lý do có thể khớp khác dự kiến; chưa có các điều kiện này thì không đưa kết luận mua ngay. |
| Chờ mua ở vùng thấp hơn | Có vùng hỗ trợ hoặc mức định giá được tính từ dữ liệu; biết điều kiện phản ứng giá để tránh đợi trong một luận điểm đã gãy | Đợi vùng X–Y nếu điều kiện C xuất hiện; hủy nếu luận điểm/điểm vô hiệu I bị vi phạm; phân biệt chạm giá và xác nhận. |
| Chờ xác nhận bứt phá | Nền giá, biến động, volume/giá trị giao dịch và điểm xác nhận đo được từ nến đóng | Điều kiện kích hoạt dựa trên dữ liệu; tránh dùng nến đang chạy như đã xác nhận. Không hứa bứt phá sẽ thành công. |
| Cân nhắc giảm/bán vị thế | Phân tích xấu đi, vùng rủi ro vi phạm hoặc giá đã phản ánh quá nhiều kịch bản thuận lợi; biết lượng được phép bán | Tách chốt lời, giảm rủi ro và luận điểm bị phá vỡ; nêu tác động phí/thuế và thanh khoản. |
| Đứng ngoài/kiểm chứng thêm | Nguồn mâu thuẫn, thiếu chart/quote hoặc điểm vào không đủ bù rủi ro | Nêu đúng dữ liệu cần bổ sung và điều kiện đổi trạng thái; không ép có lệnh trong mọi báo cáo. |

Loại lệnh phải được chọn **sau** chiến lược/giá và kiểm tra quy tắc sàn, không phải từ chữ MUA của báo cáo. ATO là tham gia cơ chế xác định giá mở cửa; MTL là chỉ dẫn xử lý lệnh thị trường theo quy tắc tương ứng; chúng không phải mô hình dự đoán. Danh sách lệnh, phiên được dùng, thứ tự ưu tiên, khả năng hủy/sửa và cách xử lý phần dư cần tra quy tắc hiện hành của đúng sàn/sản phẩm/broker trước khi áp dụng. Tài liệu này không khẳng định quy tắc giao dịch hiện hành chỉ dựa trên các PDF mẫu.

Trường hợp cần chờ một giá cụ thể, hệ thống phải xét loại lệnh giới hạn và khả năng được hỗ trợ, thay vì diễn đạt ATO là mua được đúng giá mong muốn. Khi có nhu cầu khớp nhanh, phải đánh giá thanh khoản và mức giá tối đa/tối thiểu chấp nhận, không dùng một hình nến để cam kết giá khớp.

## 9. Mẫu câu trả lời áp dụng cho đúng bộ mẫu đang có

> Trạng thái nghiên cứu: cần kiểm chứng thêm và chưa đủ dữ liệu để đưa giá/loại lệnh trong phiên. Theo bộ PDF cung cấp, doanh thu FPT Q3/2026 là khoảng 13.754 tỷ VND. Mức giảm 20,1% là so với kỳ trước có phạm vi hợp nhất khác; bảng doanh nghiệp điều chỉnh cùng phương pháp cho mức tăng 12,1%. LNST và tiền không tăng đồng đều: CFO 9 tháng khoảng 952 tỷ VND, xấp xỉ 12,24% LNST; chỉ báo CFO trừ dòng chi mua TSCĐ/tài sản dài hạn khác khoảng âm 1.077 tỷ VND. Cần đọc đủ thuyết minh để tách lãi liên kết, lãi đầu tư và tiền thực nhận.
>
> Luận điểm tích cực trong tài liệu là tăng trưởng một số mảng CNTT và mức định giá thấp theo nguồn môi giới. Điểm cần theo dõi là ký mới riêng Q3 chậm lại, khả năng thu hồi vốn lưu động và sức bán của nhóm nước ngoài theo số liệu chưa đối chiếu độc lập. Mô hình SOTP cũ có các ô CAPM và tỷ lệ sở hữu chưa tái lập được từ thông số hiển thị, nên chưa dùng mục tiêu cũ làm chuẩn giá vào lệnh.
>
> Chưa có nến OHLCV và quote hiện tại, nên chưa xác định vùng mua/bán, mức chờ, điểm vô hiệu hoặc ATO/MTL phù hợp. Giá 50.400 VND trong báo cáo là mốc 03/11/2026, không phải báo giá đang giao dịch. Bước tiếp theo là xác thực tài liệu/số liệu mâu thuẫn, bổ sung chuỗi giá đã điều chỉnh và giá thô, dòng giao dịch có thời điểm, rồi dựng các kịch bản mua tại vùng hiện tại/chờ điều chỉnh/chờ xác nhận/giảm vị thế với điều kiện rõ ràng.

Mẫu này minh họa phương pháp trả lời trung thực với đầu vào đang có; không phải khuyến nghị giao dịch trực tiếp. Khi bổ sung chart và nguồn thị trường, phải viết lại phần kịch bản theo thời điểm dữ liệu mới thay vì chỉ thay tên mã hoặc chèn một con số giá.

## 10. Yêu cầu đầu ra cho Vibe Trading

Một báo cáo cuối cùng nên có: kết luận/trạng thái và độ mới dữ liệu; tóm tắt luận điểm thuận-nghịch; cầu nối kinh doanh–lợi nhuận–tiền; định giá dạng khoảng/kịch bản và giả định; biểu đồ/điểm giá có nguồn; bảng hành động theo điều kiện; sổ bất thường; danh mục bằng chứng và giới hạn.

Mỗi khẳng định định lượng cần mang `source_id`, `page_or_locator`, `published_at`, `available_at`, `period_start/end`, `scope`, `unit`, `actual_or_forecast`, `reported_or_comparable`, `revision` và cách tính khi có. Mỗi kịch bản giao dịch cần liên kết tới các bằng chứng đó và phiên bản bộ quy tắc giao dịch, có hiệu lực đến thời điểm nào và điều gì làm nó hết hiệu lực.

Khi hai nguồn mâu thuẫn, giữ cả hai và trạng thái chưa đối soát; khi một giá trị null, giữ lý do null. Không biến báo cáo môi giới thành dữ kiện công ty đã kiểm toán, dự phóng thành kết quả thực hiện, chart cũ thành realtime, tự đánh giá thành thẩm định độc lập, hay bản nháp nghiên cứu thành lệnh đã được thực thi.
