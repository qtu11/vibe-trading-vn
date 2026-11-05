# Catalog đặc tả đã đối chiếu source

**Cập nhật:** 05/11/2026. Đây là lớp truy vết bổ sung cho [Master Plan V1](../../VIBE_TRADING_MULTI_MARKET_MASTER_PLAN_V1.md), giữ nguyên ID và tiêu đề của tài liệu người dùng cung cấp.

| Phạm vi | Số lượng | Tài liệu |
| --- | --- | --- |
| Vietnam Stock | 64 | [VN-068–VN-131](VIETNAM_STOCK_64.md) |
| Forex/XAUUSD | 62 | [FX-132–FX-193](FOREX_XAUUSD_62.md) |
| Crypto | 72 | [CRYPTO-194–CRYPTO-265](CRYPTO_72.md) |
| Core AI Platform | 67 | [PLATFORM-001–PLATFORM-067](CORE_AI_PLATFORM_67.md) |
| Scenarios độc lập | 54 | [Fixture, lỗi inject, oracle và coverage](VALIDATION_54.md) |
| Giai đoạn và quyết định | 10 + 16 | [Dependencies, nghiệm thu, rủi ro và rollback](DELIVERY_10_PHASES_16_DECISIONS.md) |

Tổng cộng **265 đặc tả**. Mỗi dòng có source seam hoặc integration còn thiếu, trạng thái baseline, tiêu chí nghiệm thu riêng và priority. Trạng thái source-existing/partial/proposed mô tả mức đã thấy trong source, không phải chứng nhận vendor/broker hoặc tỷ lệ hoàn thành chương trình.

Baseline catalog được nghiên cứu ngày 04/11. Code bắt đầu theo yêu cầu tiếp theo ngày 05/11; xem [biên bản triển khai](../IMPLEMENTATION_STATUS_2026-11-05.md) để biết những slice đã được sửa và kiểm tra. Một vài sửa P0 không nâng cả đặc tả lớn lên completed. 54 scenarios là thiết kế acceptance; số tests chạy thực tế được báo riêng.

Mười sáu DECISION vẫn chờ phê duyệt theo phạm vi chương trình. Yêu cầu code local trong chat không tự cấp quyền live, truy cập nguồn trả phí, migration production hay deploy. Nội dung chỉ dẫn trong master là yêu cầu thiết kế, không phải lệnh cần thực thi nguyên văn.

Kiểm tra máy đọc đối chiếu số lượng, thứ tự, ID và tiêu đề với bản master gốc được lưu ở `.codex-backups/2026-11-04-deep-research-pass-2/specification-index.json`; script `reconcile-plan.cjs` cạnh đó giữ snapshot gốc làm đầu vào, tránh đánh số lại hoặc làm mất đặc tả.
