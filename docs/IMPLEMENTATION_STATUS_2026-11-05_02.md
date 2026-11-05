# Triển khai đợt 2: BCTC VN local và kiểm định dữ liệu thị trường

**Ngày:** 05/11/2026, Asia/Saigon. Tiếp nối [P0](IMPLEMENTATION_STATUS_2026-11-05.md), triển khai trong workspace `0.1.18`, chưa phát hành. Đây là các phần triển khai có giới hạn của master, không đánh dấu hoàn tất 265 đặc tả hoặc phê duyệt giao dịch thật.

## Hành vi đã thay đổi

| Phần | Kết quả và điểm tích hợp |
| --- | --- |
| BCTC Việt Nam local | [Helper](../agent/src/tools/local_financial_statements.py) đọc JSON được cấu hình qua Data Bridge; [tool](../agent/src/tools/financial_statements_tool.py) và [MCP](../agent/mcp_server.py) nhận `.VN` và `as_of`. Chọn latest eligible revision theo disclosure/availability, giữ phạm vi riêng/hợp nhất, YTD/quý, nguồn/locator/hash, số âm/null và đơn vị chính xác |
| Hồ sơ `.VN` | [stock_profile_tool.py](../agent/src/tools/stock_profile_tool.py) gắn `market: vn`, giữ currency/exchange do Yahoo cung cấp hoặc null; không tự sinh metadata hoặc chứng nhận độ phủ |
| Forex raw data | [OANDA](../agent/src/trading/forex/adapters/oanda.py) và [Exness](../agent/src/trading/forex/adapters/exness.py) kiểm raw account/quotes/instrument/positions/conversions trước assessment. Lỗi có mã ổn định; giá trị tiền không hữu hạn/ngoài giới hạn bị chặn; Exness kiểm tuổi tick định giá vị thế đang mở |
| Crypto model identity | [crypto.py](../agent/backtest/engines/crypto.py) ghi rõ perpetual accounting, legacy funding assumptions và liquidation price model qua diagnostics → metrics/run card; spot OHLCV không tự biến engine thành cash-spot |
| Strict composite | [composite.py](../agent/backtest/engines/composite.py) từ chối strict crypto lifecycle chưa được hỗ trợ trong shared pool, tránh báo cáo strict trong khi chạy legacy hooks |

Tái sử dụng tool registry, paging, Data Bridge config, Forex error contract và diagnostics hook hiện có. Không thêm dependency hoặc tool; inventory vẫn được kiểm bằng test. Tham khảo [hướng dẫn và JSON mẫu BCTC](LOCAL_VN_FINANCIAL_STATEMENTS.md).

## Điều kiện và giới hạn

BCTC local là dữ liệu do người vận hành cung cấp, mang `user_supplied_unverified`; reader không thu thập/đối chiếu báo cáo gốc hoặc chứng thực availability lịch sử. `as_of` ngoài `.VN` bị từ chối. Chưa nối BCTC này thành factor panels, giá trị định giá hoặc báo cáo AI đầu cuối. SSI, OCR, coverage toàn thị trường, license và live feed vẫn cần các đợt riêng.

Crypto legacy tiếp tục dùng per-bar funding rate nếu có, nếu không dùng configured fixed rate, với slots 8h/bar-span/daily fallback. Strict inputs không chứng minh completeness hoặc thứ tự liquidation của sàn. Composite strict crypto bị chặn trước engine loading/execution; main runner có thể đã nạp dữ liệu công khai trước khi tạo composite. Chưa xây cash-spot accounting hoặc strict composite lifecycle.

Forex chỉ sửa decode/valuation boundaries; không sửa submit/reconcile, ambiguous-send handling, mandate hoặc halt. Phản hồi nến/discovery và các hành vi ngoài phạm vi trên chưa được harden toàn bộ. Không có kiểm tra token, socket hoặc broker thật trong đợt này.

## Kiểm chứng

Các nhóm đã chạy riêng: financial/local/MCP/paging **78 passed** trước các regression giới hạn và ví dụ cuối; Crypto **119 passed**; Forex adapters/execution/surfaces **93 passed**. Không cộng các lượt này vì có phần trùng với regression tích hợp. Các test mới đã được đối chiếu với hành vi cũ bằng lượt đỏ hoặc adapter snapshot.

Regression tích hợp cuối: **548 passed, 0 failed, 0 skipped** trên **24 file test**, 48,00 giây. Có 63 deprecation warnings chủ yếu từ NumPy/pandas timedelta hiện có; pytest-asyncio cũng nhắc cấu hình fixture scope. JUnit: [final-regression.xml](../.codex-backups/2026-11-05-implementation-2/final-regression.xml); [lệnh chạy và phạm vi kiểm chứng](../.codex-backups/2026-11-05-implementation-2/verification.json). Đây là test offline bằng fixture/mock, không chứng nhận tài khoản hay lợi nhuận.

Kiểm tra tài liệu: **23 file thay đổi**, **33 Markdown**, **1142 liên kết nội bộ**; UTF-8, code fences, anchors và whitespace mới hợp lệ. IDs/tiêu đề giữ đúng **265 đặc tả /54 scenarios /10 phases /16 quyết định pending**, `implementation_approved: false` không đổi. Xem [checks.json](../.codex-backups/2026-11-05-implementation-2/checks.json) và [manifest hash trước/sau](../.codex-backups/2026-11-05-implementation-2/manifest.json). Không kiểm lại reachability của các URL ngoài trong đợt code này.

Chưa chạy full repository suite, frontend build, Ruff hoặc broker/feed/model thật. Ruff không có trong môi trường hiện tại; không cài thêm dependency để phục vụ đợt này. Các kiểm tra source liên quan và inventory README/MCP đã nằm trong regression ở trên.

## Snapshot và rollback

Snapshot trước sửa nằm trong `.codex-backups/2026-11-05-implementation-2/`, gồm các nhóm `root`, `crypto-model-identity`, `forex-provider-validation` và snapshot theo đường dẫn của stock profile/skills. File mới được liệt kê trong manifest của đợt này. Không thay credentials, config tài khoản, package version, dữ liệu người dùng hoặc audit/journal.

Rollback phục hồi đúng các file cùng caller/test/schema liên quan; bỏ helper mới nếu quay về tool/MCP cũ. Có thể tắt riêng nguồn BCTC bằng cách bỏ mục cấu hình mà giữ file dữ liệu. Giữ guard nếu chưa có giải pháp thay thế chứng minh strict composite hoạt động đúng; không bỏ guard chỉ để backtest chạy xanh.
