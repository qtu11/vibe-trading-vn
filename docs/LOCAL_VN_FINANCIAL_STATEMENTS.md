# Đọc BCTC Việt Nam local qua tool và MCP

Triển khai ngày **05/11/2026**, trên tool `get_financial_statements` hiện có. Luồng đọc `.VN` dùng file JSON do người vận hành chuẩn bị, có nguồn, đơn vị và lịch sử phiên bản. Không thêm dependency, tool mới hoặc kết nối SSI. `get_fundamentals` và factor panels vẫn là đường SEC riêng; dữ liệu này chưa tự đi vào backtest.

## Cấu hình và gọi thử

Thêm vào cấu hình Data Bridge `~/.vibe-trading/data-bridge/config.yaml`, giữ các mục `sources` đang dùng:

```yaml
financial_statements:
  - symbol: VIC.VN
    path: D:/research/authorized-statements.json
```

`path` phải là đường dẫn tuyệt đối, chỉ người vận hành cấu hình. Tool không nhận đường dẫn từ lời gọi của model. Chưa cấu hình, file lỗi hoặc symbol không khớp đều trả `ok: false`; không chuyển sang một nguồn mạng khác. Không cần thông tin xác thực cho bước đọc local này.

File [JSON ví dụ](examples/vn-financial-statements.example.json) có số liệu, URL, hash và revision **giả lập** để kiểm tra schema; không phải BCTC của VIC. Thay toàn bộ nội dung bằng dữ liệu được phép sử dụng trước khi nghiên cứu thực tế. Trong MCP, gọi tool hiện có với arguments:

```json
{
  "code": "VIC.VN",
  "statement": "income",
  "period": "quarter",
  "as_of": "2025-05-01T00:00:00Z",
  "offset": 0
}
```

Trong Python, sau khi kích hoạt môi trường dự án và chuyển vào `agent/`:

```python
from src.tools.financial_statements_tool import FinancialStatementsTool

print(FinancialStatementsTool().execute(
    code="VIC.VN", statement="income", period="quarter",
    as_of="2025-05-01T00:00:00Z",
))
```

## Hợp đồng file phiên bản 1

Root gồm `schema_version: 1`, `symbol` khớp cấu hình, `venue` là `HOSE`, `HNX` hoặc `UPCOM`, và danh sách `records`. Venue là thông tin được khai báo cho tài liệu; reader không xác minh lịch sử niêm yết hoặc bổ sung engine HNX/UPCoM.

Mỗi record chứa đúng các trường trong ví dụ:

| Trường | Ý nghĩa và kiểm tra |
| --- | --- |
| `statement` | `balance`, `income`, `cashflow` hoặc `indicators`; không tự tính chỉ tiêu thiếu |
| `period` | `annual` hoặc `quarter` |
| `period_start`, `period_end` | `YYYY-MM-DD`, đầu kỳ không sau cuối kỳ |
| `period_basis` | `standalone`, `year_to_date` hoặc `instant`; balance phải instant với hai ngày bằng nhau; income/cashflow phải là kỳ dòng tiền/kết quả |
| `consolidation` | `consolidated` hoặc `separate`; không gộp hai phạm vi |
| `published_at` | Timestamp có timezone, ngày công bố không trước cuối kỳ theo ngày địa phương đã khai báo |
| `available_at` | Tùy chọn; mặc định bằng publication. Là thời điểm khả dụng được khai báo, không trước publication |
| `retrieved_at` | Timestamp thu thập, không trước availability |
| `source_url`, `locator` | URL HTTP(S) không chứa credentials và vị trí trong tài liệu |
| `document_sha256` | 64 ký tự hex của tài liệu nguồn do người cung cấp khai báo; reader không tải tài liệu để đối chứng hash |
| `revision` | Nhãn phiên bản, không rỗng và không lặp trong cùng phạm vi kỳ |
| `facts` | Map tên chỉ tiêu → `{value, unit, scale}`; 1–100 chỉ tiêu |

`value` là chuỗi thập phân hữu hạn hoặc `null`. Giữ nguyên độ chính xác, dấu âm và thiếu dữ liệu; không chuyển sang float hoặc thay bằng 0. `unit` bắt buộc; `scale` là số nguyên dương tối đa `10^12`. Ví dụ `"100"`, `"VND"`, `1000000` là 100 triệu VND; reader trả cả ba trường, không tự đổi đơn vị. EPS, phần trăm và giá trị tiền có thể khai báo đơn vị khác nhau ở từng fact.

Reader chặn file trên 2 MB, trên 1000 record, JSON trùng key, metadata sai và một record vượt ngân sách kết quả. Khi record quá rộng, giảm số chỉ tiêu trong bộ dữ liệu cho truy vấn đó; không tạo nhiều record cùng scope/revision để chia nhỏ vì sẽ bị coi là xung đột. Không cắt bớt facts âm thầm.

## Chọn phiên bản theo thời điểm

`as_of` phải có timezone; bỏ qua thì dùng UTC hiện tại. Chỉ những record có publication/availability không muộn hơn cutoff được chọn. Với mỗi tổ hợp statement, cadence, đầu/cuối kỳ, basis và consolidation, reader chọn nguyên record có availability mới nhất. Không trộn chỉ tiêu giữa các revision, không suy quý riêng từ YTD, không chọn ngẫu nhiên khi hai phiên bản có cùng timestamp. Toàn bộ file được kiểm schema trước lựa chọn, kể cả các record chưa đến thời điểm công bố.

`retrieved_at` có thể muộn hơn `as_of`: đây là dựng lại lịch sử dựa trên thời gian được khai báo trong file hiện tại, không chứng minh hệ thống đã ghi nhận dữ liệu vào ngày đó. Hash và timestamps cũng không chứng nhận nội dung đúng với bản gốc.

Response giữ envelope/paging hiện có, `market: "vn"`, `source: "local_financial_statements"`. Trong `data[code]` có cutoff UTC, venue, `source_file_sha256`, `verification_status: "user_supplied_unverified"` và `periods`. Mỗi period có `REPORT_DATE` cùng metadata và `facts`. Không xuất đường dẫn file local. Khi đọc trang tiếp, truyền lại `as_of` nhận từ trang đầu và `paging.next_offset`; giữ file không đổi để kết quả nhất quán.

Các nguồn ngoài `.VN` chưa hỗ trợ cutoff này và trả lỗi nếu truyền `as_of`. Luồng US/UK/Brazil/A-share/HK không thay nguồn vì có thêm reader local.

## Kiểm thử và rollback

[Regression local](../agent/tests/test_local_financial_statements.py) dùng file tạm và ví dụ tổng hợp; kiểm revision, timezone, availability, scope/YTD, số âm/null/độ chính xác, schema lỗi, giới hạn, paging và FastMCP. Xem [kết quả đợt 2](IMPLEMENTATION_STATUS_2026-11-05_02.md).

Bỏ mục `financial_statements` sẽ làm tool trả lỗi chưa cấu hình và không xóa file. Muốn hoàn tác code, phục hồi cả helper/tool/MCP và tài liệu từ snapshot của đợt 2; giữ nguyên datasets, audit và báo cáo cũ.
