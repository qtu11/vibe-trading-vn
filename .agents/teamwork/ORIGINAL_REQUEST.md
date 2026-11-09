# Original User Request

## Approved Task Prompt — 2026-11-08T14:38:21Z

Phê duyệt thực thi toàn diện không cần phỏng vấn thêm. Chi tiết yêu cầu kỹ thuật:

1. Phạm vi mục tiêu:
- Xây dựng công cụ Parallel Multi-Web Search & Concurrent Scraper tối ưu hóa token cho Vibe-Trading.
- Tìm kiếm đồng thời từ nhiều nguồn (DuckDuckGo, Brave Search, Bing, Qveris, Vietnam Financial Portals).
- Cào nội dung song song (Async HTTPX/AioHTTP) kèm connection pooling, DNS caching, rate limiter và adaptive concurrency control.
- Pipeline làm sạch HTML thành clean Markdown/text, bóc tách cấu trúc, loại bỏ boilerplate, nav, footer, scripts, ads.
- Lọc ngữ nghĩa (Semantic Chunking & Relevance Filtering với BM25/Lexical scoring) để cắt bỏ 75-90% token rác, chỉ giữ lại thông tin liên quan trực tiếp đến query của agent.
- Luồng Map-Reduce / Structured Synthesis tổng hợp dữ liệu song song trước khi nạp vào context của LLM hoặc AgentLoop.
- Đo kiểm benchmark latency và token consumption so với luồng hiện tại.

2. Triển khai ngay lập tức 5 Workstreams (WS1 -> WS5), phân tích hiện trạng mã nguồn trong d:\Vibe-Trading, lập Master Blueprint và báo cáo kết quả chi tiết.


## Follow-up — 2026-11-08T14:38:38Z

Xác nhận phê duyệt triển khai ngay theo toàn bộ nội dung yêu cầu đã nhận mà không cần phỏng vấn.

Bản đặc tả nhiệm vụ chuẩn hóa:
1. Mục tiêu cốt lõi:
- Nghiên cứu và thiết kế công cụ tìm kiếm và đọc nhiều website song song đồng thời (Concurrent Parallel Multi-Web Search & Scraper).
- Tối ưu hóa triệt để lượng token tiêu thụ khi gọi công cụ và tổng hợp dữ liệu (Token Pruning, Boilerplate stripping, Semantic Chunking & Relevance Scoring), giảm 75-90% token rác.
- Tăng tốc độ phản hồi (giảm latency) và nâng cao chất lượng dữ liệu tổng hợp so với luồng hiện tại trong agent/src/tools/web_search_tool.py và web_reader_tool.py.

2. Phân chia 5 luồng công việc:
- WS1 (Multi-Engine & Parallel Scraping Architecture): Async HTTPX/AioHTTP fetcher, connection pool, semaphore rate-limits, DNS cache, multi-source search.
- WS2 (DOM Cleaning & High-Fidelity Extraction): Chuyển đổi HTML sang Clean Markdown, loại bỏ scripts/styles/nav/ads/cookies banners, chống duplicate giữa các site.
- WS3 (Semantic Token Optimization & Adaptive Context Pruning): Phân mảnh thông minh (chunking), lọc đoạn liên quan qua BM25/Lexical Scoring theo user query, nén context.
- WS4 (Map-Reduce & Structured Synthesis Engine): Luồng tổng hợp thông tin phân tầng (Map trích xuất insight song song -> Reduce tổng hợp kết quả chuẩn JSON/Markdown), tích hợp vào tools và AgentLoop.
- WS5 (Benchmark & Empirical Verification): Thiết lập bộ kiểm thử thực nghiệm đo lường độ trễ, mức tiết kiệm token, và độ chính xác dữ liệu.

Tiến hành thực thi ngay lập tức và lập báo cáo Master Blueprint toàn diện.
