# Tài liệu Vibe-Trading Multi-Market AI

**Cập nhật:** 05/11/2026. Bộ tài liệu đối chiếu master plan với source cục bộ `0.1.18`, nguồn chính thức và các sửa code local. Mục tiêu là đủ cụ thể để triển khai và nghiệm thu, đồng thời giữ rõ phần đang có, phần còn thiếu và phần chưa kiểm tra runtime.

Đọc [master plan đã đối chiếu](../VIBE_TRADING_MULTI_MARKET_MASTER_PLAN_V1.md), [265 đặc tả +54 scenarios +10 giai đoạn +16 quyết định](specs/README.md) và [đợt triển khai code đầu tiên](IMPLEMENTATION_STATUS_2026-11-05.md). Các ID/tiêu đề trong catalog được kiểm tra tự động khớp bản master gốc; trạng thái phê duyệt chương trình không tự thay đổi vì đã viết code local.

Đã có [đợt triển khai thứ hai](IMPLEMENTATION_STATUS_2026-11-05_02.md): [BCTC VN local qua tool/MCP](LOCAL_VN_FINANCIAL_STATEMENTS.md), định tuyến `.VN`, kiểm raw provider Forex và diagnostics/guard Crypto. Hướng dẫn gồm file JSON tổng hợp để thử schema; không có dữ liệu tài chính thật được xác minh trong mẫu.

## Bắt đầu ở đâu

| Nhu cầu | Tài liệu | Nội dung chính |
| --- | --- | --- |
| Cài và dùng bản hiện tại | [README dự án](../README.md) | Quick start, cấu trúc, capability và đường đọc tiếp |
| Biết source thực sự có gì | [Source baseline](SOURCE_BASELINE.md) | Data loaders, engines, currency/product boundaries, connector và tests |
| Thiết kế toàn hệ thống | [Multi-market architecture](MULTI_MARKET_ARCHITECTURE.md) | Domain ownership, control/data plane, Swarm, storage, risk và UI |
| Chốt semantics dữ liệu | [Data & evidence contracts](DATA_EVIDENCE_CONTRACTS.md) | Identity, timestamps, PIT, revisions, snapshots, null và failure states |
| Nghiên cứu cổ phiếu Việt Nam | [Vietnam Equity Research](VIETNAM_EQUITY_RESEARCH.md) | BCTC, nguồn gốc, định giá, HOSE/HNX/UPCoM và acceptance gates |
| Phát triển Forex/XAUUSD | [Forex & XAUUSD Lab](FOREX_XAUUSD_LAB.md) | Native data, closed bars, strategies, sizing, replay, OOS và execution gates |
| Phát triển Crypto | [Crypto Intelligence](CRYPTO_INTELLIGENCE.md) | Spot/perp, funding/OI, order book, on-chain và simulator fidelity |
| Chọn việc tiếp theo | [Implementation roadmap](IMPLEMENTATION_ROADMAP.md) | Milestones, dependencies, Definition of Done và brief cho coding agent |
| Xem phạm vi đã kiểm tra | [Documentation verification](DOCUMENTATION_VERIFICATION.md) | Backup, checks đã chạy, giới hạn và kết quả thật |

Nếu mới vào dự án, đọc README → baseline → kiến trúc → hợp đồng dữ liệu → một thị trường → roadmap. Nếu sửa code, xác minh lại source liên quan trước; tài liệu có ngày chụp trạng thái, không thay thế implementation hiện hành.

## Tài liệu Forex hiện hữu

Các tài liệu này giữ chi tiết tích hợp và bằng chứng lịch sử; phần cập nhật đầu trang phân biệt hiện trạng source ngày 04/11 với các kết quả runtime trước đó.

| Tài liệu | Vai trò |
| --- | --- |
| [Forex MCP implementation](FOREX_MCP_IMPLEMENTATION.md) | Cấu hình, contract, endpoint, policy và luồng đã triển khai |
| [Forex live candles](FOREX_LIVE_CANDLES.md) | Chart snapshot/polling, nguồn, nến và trạng thái kết nối |
| [Forex agentic research](FOREX_AGENTIC_RESEARCH.md) | Ngữ cảnh nghiên cứu, council và phân tích có điều kiện |
| [Exness integration research](EXNESS_FOREX_MCP_INTEGRATION_RESEARCH.md) | Nghiên cứu adapter/API và thiết kế gốc, có ghi rõ các phần lịch sử |
| [Context/memory/token audit](CONTEXT_MEMORY_TOKEN_AUDIT.md) | Khảo sát riêng về context/memory/token; chưa được audit lại trong đợt này |

## Những điều cần đọc đúng

- Loader có dữ liệu không chứng minh engine mô phỏng đúng toàn bộ sản phẩm hoặc quyền giao dịch của tài khoản.
- Prompt có vai trò On-chain Analyst không chứng minh đã tích hợp nguồn on-chain; prompt yêu cầu Risk Officer phủ quyết không thay order gate.
- Chart cập nhật và nến đang hình thành không thay tick stream/replay hoặc dữ liệu nến đóng cho strategy.
- Artifact active, backtest tốt và tín hiệu LONG/SHORT không tự cấp quyền live.
- Null, unavailable, rejected và insufficient data là trạng thái có ý nghĩa; tài liệu không dùng dữ liệu giả để lấp khoảng trống.

## Phạm vi xuất bản và bảo toàn

Theo [quy ước repository](../CONTRIBUTING.md#keep-internal-documents-local), `docs/` là tài liệu làm việc cục bộ; phần tài liệu công khai đặt trong `wiki/docs/`. Chưa commit, publish hoặc deploy. Đợt04/11 chỉ sửa tài liệu và đồng bộ count của sáu bản dịch; đợt05/11 có thay đổi source local theo yêu cầu code, phạm vi và bằng chứng được ghi trong biên bản triển khai. Không thay đổi chính sách CONTRIBUTING/SECURITY.

Trước khi viết lại, README và bốn tài liệu Forex được sao lưu dưới `.codex-backups/2026-11-04-multi-market-docs/`, giữ đường dẫn tương ứng. Xem manifest và kết quả kiểm tra trong [biên bản](DOCUMENTATION_VERIFICATION.md). Các ví dụ record/flow mới được gắn nhãn đề xuất; không phải endpoint hoặc tính năng đã được thêm bằng việc viết tài liệu.
