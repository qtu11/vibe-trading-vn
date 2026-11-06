# Archive cục bộ cho Open Interest và Funding

Cập nhật **06/11/2026**. `crypto_derivatives` giữ mặc định `mode="live"` chỉ đọc public Binance USD-M response hiện tại. `capture` ghi phản hồi mới vào kho cục bộ; `archive` đọc lịch sử capture theo `as_of` mà không gọi exchange. Tất cả chỉ hỗ trợ linear USDT perpetual với symbol `BASE-USDT-PERP`; chưa là dịch vụ collector tự động.

## Cấu hình và quyền

Quản trị viên thêm mục sau vào Data Bridge `~/.vibe-trading/data-bridge/config.yaml`, giữ các mục hiện có:

```yaml
crypto_derivatives_archive:
  path: D:/research/crypto-derivatives.sqlite
```

Path phải tuyệt đối, chỉ nằm trong cấu hình quản trị; tool/API không nhận file path. Đợt triển khai và test không tạo/sửa cấu hình hoặc database home của người dùng. Không trỏ archive này vào database Forex hay một database ứng dụng khác. Ghi yêu cầu explicit capture; live không đọc config archive. Đọc archive thiếu/sai file trả lỗi, không tạo hoặc migrate.

Agent tool nhận `mode: live|capture|archive`, được gắn `is_readonly=False` vì có nhánh ghi; không được gom capture vào batch parallel reads. Main MCP chỉ nhận `live|archive`; `capture` bị chặn trước registry. API POST `/api/research/crypto` có read-auth và chỉ hai mode đọc. API POST `/api/research/crypto/captures` có settings-write auth và browser-origin gate, nhận symbol/metric/period/limit, không nhận `as_of` hoặc path.

Trong `/research`, chọn Crypto, nhập symbol. **Tải và lưu capture mới** fetch một phản hồi mới có giới hạn rồi append; không lưu ngầm kết quả đang xem. **Kho capture cục bộ** đọc theo mốc ghi nhận ISO có timezone. Thao tác ghi không tự retry; lỗi transport có thể chưa xác định commit, cần kiểm kho trước khi gửi lại. Quyền ghi API này không cấp quyền giao dịch.

## Nội dung giữ lại

Một capture gồm market metadata, **parsed CCXT payload** đầy đủ, normalized observations, normalization version, retrieval time và actual local recording time. `ccxt_payload_sha256` là hash object đã parse/canonicalize, không phải hash raw HTTP bytes. Receipt có capture ID, hashes và recorded timestamp. SQLite dùng append-only tables/triggers; rollback của một append lỗi không phát hành receipt giả. Output được chừa budget receipt trước khi commit.

Archive giữ các capture trùng/overlap như các lần quan sát riêng; mỗi event identity giữ các revision đã thấy. Funding phân biệt timestamp **và rate_type**; OI phân biệt sampling period. Không gộp `Regular`/`Special` khi cùng timestamp, không giả định funding8h, không dùng current mark thay historical mark và không forward fill lịch sử thiếu.

## Semantics cutoff và integrity

`as_of` là **mốc ghi nhận cục bộ**: chỉ capture `recorded_at <= as_of` và event đủ điều kiện mới hiện. Chọn revision được ghi gần nhất cho mỗi identity. `first_observed_at`, số revision khác nhau, selected capture và supporting capture counts có provenance. Hai giá trị khác nhau cùng latest recording time trả `ARCHIVE_CONFLICT`; không tạo aggregate từ một winner tùy ý. Local clock lùi so với capture trước trả `ARCHIVE_CLOCK_REGRESSION`, không ghi revision mới vào quá khứ.

Query mở SQLite read-only và kiểm toàn bộ capture manifest/index trong scope nhìn thấy trước khi chọn events. Checksum sai, scope/timestamp khác manifest, index thiếu/thừa/đổi dữ liệu hoặc mất toàn bộ index của capture trả `ARCHIVE_INVALID`. Giới hạn kiểm **512 captures /20MB payload /20.000 observations**; vượt trả `ARCHIVE_QUERY_TOO_LARGE`, cần cutoff sớm hơn hoặc partition do operator quản lý. Đây là giới hạn công việc thật, không bỏ âm thầm lịch sử revision để vừa budget. Output summary/hash bao selected latest limit2–100 events, display tối đa10, có cờ omission/coverage.

Capture time chỉ chứng minh thời điểm hệ thống ghi nhận theo local clock, **không chứng minh exchange đã công bố đúng thời điểm event**. `historical_available_at` vẫn null. Hash/triggers hỗ trợ phát hiện inconsistency cục bộ; chưa có chữ ký nguồn hoặc cơ chế tamperproof chống người có quyền sửa toàn database và hashes. Không gọi archive là nguồn PIT exchange đã được xác minh.

## Vận hành và rollback

Chưa có scheduler collector, retention policy, tự chia partition hoặc operator recovery UI. Giữ backup SQLite nhất quán trước bảo trì; dùng SQLite backup API hoặc dừng writers/checkpoint đúng quy trình, không copy riêng main DB khi còn WAL chưa xử lý. Rollback code không cần xóa captures: giữ nguyên file và vô hiệu luồng capture, phục hồi source/config trước đó phù hợp. Không sửa timestamps/hash, drop triggers hoặc xóa observations để làm query vượt giới hạn có vẻ thành công.

Phạm vi partial `CRYPTO-200`, `CRYPTO-201`, `PLATFORM-007`, `PLATFORM-010`. [Tests](../agent/tests/test_crypto_derivatives_archive.py) dùng fixture/temp SQLite, kiểm cutoff/revisions/corruption/clock/concurrency và không gọi exchange thật.
