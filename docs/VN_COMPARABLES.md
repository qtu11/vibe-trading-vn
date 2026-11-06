# So sánh P/E và P/B của doanh nghiệp Việt Nam

Cập nhật **06/11/2026**. Tool `vietnam_comparables` là phép tính trên đầu vào do caller cung cấp; không tự tải giá/BCTC hoặc xác minh doanh nghiệp. [Fixture tổng hợp](examples/vn-comparables.example.json) dùng `CASE.VN` và ba peer giả lập, không phải định giá doanh nghiệp thật.

## Gọi qua agent, MCP hoặc API

Agent registry và main MCP nhận `vietnam_comparables(payload, offset=0)`. `payload` là toàn bộ object trong fixture, không phải đường dẫn file. REST POST `/api/research/vietnam/comparables` nhận `{"payload": <object>, "offset": 0}` và có read authentication. Preset `fundamental_research_team` đã cấp tool cho valuation analyst với yêu cầu giữ nguồn và giả định.

Payload giới hạn64kB, gồm `schema_version: 1`, `as_of` có timezone, một kỳ năm đủ12 tháng, `consolidation`, target và1–12 peers. Mỗi công ty có symbol/venue/sector, lý do chọn peer, thời điểm giá, share basis và note, giá VND, PATMI, weighted-average shares, parent common equity, book-snapshot common shares và hai nhóm evidence tài chính/giá. Tiền theo VND đầy đủ, shares theo số cổ phần đầy đủ, số là decimal string hoặc null; không tự đoán scale.

Evidence giữ HTTP(S) URL không có credentials, SHA256 tài liệu, locator, published/available/retrieved timestamps. Đây đều là khai báo chưa được xác minh. Published ≤ available ≤ retrieved; cutoff xét availability khai báo. Retrieval sau cutoff có thể là tái dựng nguồn được khai báo đã công bố trước đó, không chứng minh hệ thống đã nhìn thấy nguồn lúc ấy. Giá phải cùng một thời điểm quan sát giữa target và peers; price publication/availability cũng phải đủ điều kiện. Kỳ/scope là một contract chung, chưa có TTM hay calendarization.

## Công thức và cơ sở cổ phần

`EPS = PATMI / weighted_average_shares`; `BVPS = parent_common_equity / current_common_shares`. Field `current_common_shares` ở đây phải là số common shares khớp **snapshot vốn chủ cuối kỳ** đã cung cấp, trên basis tương đương giá sau các corporate actions khai báo; không dùng count phát hành muộn hơn mà giữ nguyên equity cũ. Parent equity phải loại NCI/preferred; PATMI phải có common-claim basis phù hợp. Tool chưa tự reconcile preferred dividends/basic/diluted hoặc xác minh corporate actions.

Fixture cố ý dùng weighted shares5 triệu và book shares10 triệu: PATMI10 tỷ tạo EPS2.000 VND, parent common equity100 tỷ tạo BVPS10.000 VND. Peer median P/E10× hoặc P/B2× tạo **scenario có điều kiện**20.000 VND. Đó là kết quả công thức trên dữ liệu tổng hợp, không phải forecast/khuyến nghị hay xác nhận fair value. Không dùng một denominator shares cho cả EPS và BVPS để làm số khớp.

Missing và denominator không dương tạo null/exclusion reason; EPS≤0 không sinh P/E hợp lệ. Target không nằm trong peer distribution. Peer quantile dùng toàn bộ tập hợp hợp lệ và giữ phương pháp interpolation của quantlib hiện có. Sector mismatch được liệt kê; caller-selected peers và lựa chọn basis chưa được hệ thống chứng nhận là comparable. Mẫu ít peer cần đọc cảnh báo, không biến median nhỏ thành thống kê thị trường vững chắc.

## Đọc kết quả

`distribution.pe/pb` chứa thống kê cross-section; `target.scenarios` áp multiple vào EPS/BVPS với cơ sở và giới hạn nêu rõ. `input_sha256` bao toàn bộ payload chuẩn hóa. Peer rows có evidence và exclusions; output giới hạn10k ký tự, paging tối đa3 peer/page. Dùng `paging.next_offset` để đọc tiếp; distribution/hash vẫn bao toàn bộ tập supplied peers.

Đây chưa là justified P/B–ROE cho ngân hàng, historical percentile, mô hình tăng trưởng hay báo cáo AI được human review. Mapping partial `VN-110`, `VN-111`, `VN-128`; [tracker](IMPLEMENTATION_TRACKER.md) giữ acceptance đầy đủ còn mở. Kiểm thử tại [test_vietnam_comparables.py](../agent/tests/test_vietnam_comparables.py) gồm registry, JSON Schema và FastMCP client trong bộ nhớ; chưa dùng nguồn/model thật.
