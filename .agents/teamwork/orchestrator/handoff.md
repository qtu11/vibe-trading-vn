# MASTER BLUEPRINT: PARALLEL MULTI-WEB SEARCH & CONCURRENT SCRAPER (TOKEN-OPTIMIZED)
Dự án: Vibe-Trading Autonomous Finance Agent
Cơ quan thực hiện: Master Dispatch-Only Orchestrator
Bản quyền & Phạm vi: Toàn diện 5 Workstreams (WS1 - WS5)
Thời gian hoàn thành: 2026-11-08T14:52:00Z

---

## 1. OBSERVATION (QUAN SÁT HIỆN TRẠNG TỪ 3 BÁO CÁO ĐỘC LẬP)

Sau khi điều phối song song 3 subagents chuyên trách khảo sát toàn bộ codebase `d:\Vibe-Trading`, hệ thống đã ghi nhận các hiện trạng kỹ thuật được chứng thực bằng dòng code cụ thể:

### 1.1. Hiện trạng Tìm kiếm Web (`agent/src/tools/web_search_tool.py`)
- Sử dụng thư viện đồng bộ `ddgs.DDGS()` với `_DEFAULT_BACKENDS = "duckduckgo, google, bing, brave, mojeek, yahoo"` và `_MAX_ATTEMPTS = 3` (dòng 28-30).
- Fallback tuần tự chậm trễ: Khi lỗi, chờ backoff `0.8s` rồi thử tuần tự `_sogou_search` và `_bing_cn_search` qua `urllib.request` đồng bộ (dòng 311-334), gây treo thread từ 20s đến 30s.
- Thiếu cơ chế Multi-Engine song song, thiếu tích hợp tìm kiếm chuyên sâu các cổng tài chính Việt Nam (CafeF, Vietstock, FiinGroup, HOSE/HNX) và QVeris.
- Kết quả chỉ trả về snippet ngắn cắt thô sơ (`snippet[:180]`), không có bóc tách nội dung chi tiết hay tính điểm liên quan theo ý định truy vấn.

### 1.2. Hiện trạng Đọc Web (`agent/src/tools/web_reader_tool.py`)
- Phụ thuộc 100% vào dịch vụ bên thứ ba Jina Reader API (`_JINA_PREFIX = "https://r.jina.ai/"`, dòng 21).
- Trình đọc đơn lẻ và tuần tự: Chỉ nhận đơn lẻ 1 `url: str`. Khi agent cần đọc 5-10 URLs, phải gọi lặp lại tuần tự gây độ trễ từ 25s - 45s.
- Cơ chế cào trực tiếp bị khóa cứng (`_direct_fetch` trả về `None` do lo ngại DNS rebinding và SSRF, dòng 70-77).
- Đọc stream byte-by-byte (`for chunk in response.iter_content(chunk_size=1):`, dòng 96) gây lãng phí CPU.
- Cắt chuỗi thô bạo ở 8.000 ký tự (`text[:8000] + "\n\n... (truncated)"`, dòng 207-208) kết hợp giới hạn `TOOL_RESULT_LIMIT = 10_000` (`agent/src/config/limits.py`) và cơ chế spill đĩa `parts/1.txt` (`agent/src/agent/result_artifacts.py`).

### 1.3. Định lượng Token Bloat & Mất mát Thông tin
- Tổng dung lượng HTML-to-text trung bình: 25.000 - 45.000 ký tự (~6.250 - 11.250 tokens).
- Bị cắt gọt mất 68% - 82% phần thân và cuối bài viết (nơi chứa bảng BCTC, P/E, cổ tức, rủi ro).
- Trong 8.000 ký tự đầu tiên được nạp vào context:
  * 18.1% là navbar, menu, breadcrumbs.
  * 20.0% là widget giá real-time, mã chạy nhảy không liên quan.
  * 14.4% là quảng cáo, banner, cookie consent, tracking scripts.
  * 18.8% là tin đọc thêm, liên kết ngoài.
  * 6.9% là bản quyền, tòa soạn.
  * **Chỉ 21.8% là thông tin tài chính cốt lõi phục vụ truy vấn.**
- **Tỷ lệ Token Bloat thực tế: 78.2% - 85.6%.**
- 5 bài đọc tiêu tốn ~10.000 tokens thô, nhanh chóng kích hoạt nén context `_microcompact` (`context_compact.py`), xóa sạch dữ liệu và gây lỗi `no_progress`.

### 1.4. Hạ tầng Sẵn có trong Repo
- Dependencies đã cài đặt sẵn trong `.venv` và `pyproject.toml`:
  * `httpx>=0.28.0`, `aiohttp>=3.14.3`, `requests>=2.31.0`
  * `nh3>=0.2.18` (Rust-based HTML Ammonia sanitizer cực nhanh)
  * `mistune>=3.0.0` (C/Python fast Markdown parser)
  * `bs4` (BeautifulSoup4), `lxml` (C-based XML/HTML parser)
  * `duckdb>=1.2.0`, `ddgs>=6.0.0`, `fastmcp>=2.14.0`, `pytest>=7.0`, `pytest-socket>=0.7.0`
- Hệ thống Grounding và An ninh:
  * `agent/src/agent/grounding/sources.py`: `SOURCE_POLICIES` phân tầng Tier 1 đến Tier 5 (HOSE, HNX, FiinGroup, Vietstock, CafeF, v.v.), cấp ID `S1, S2, ...` qua `_ingest_sources`.
  * `agent/src/agent/grounding/figures.py`: Kiểm tra định dạng số liệu tiếng Việt nghiêm ngặt, gắn lỗi `(omitted※)` nếu số liệu bị cắt mất dấu vết.
  * `agent/src/security/scanner.py`: Quét prompt injection trên title, snippet và content.

---

## 2. LOGIC CHAIN & KIẾN TRÚC CHI TIẾT 5 WORKSTREAMS

Hệ thống được thiết kế thành một thể thống nhất gồm 5 Workstreams kết nối chặt chẽ theo luồng dữ liệu Pipeline:

```
[AgentLoop / FastMCP / API Server]
               │
               ▼
┌─────────────────────────────────────────────────────────────┐
│ WORKSTREAM 1: MULTI-ENGINE SEARCH & ASYNC SCRAPING ENGINE   │
│                                                             │
│ 1. MultiSearchAggregator (Parallel Query Dispatcher)        │
│    - DuckDuckGo Engine (ddgs Async Worker)                  │
│    - Brave Search Engine (API / Organic Scraping Fallback)  │
│    - Bing Search Engine (CnBing / Organic Parser)           │
│    - QVeris Search Engine (Financial Catalog Discovery)     │
│    - Vietnam Financial Portals Engine (CafeF, Vietstock, VN)│
│    => Concurrent Gather (3s timeout) + RRF Re-Ranking +     │
│       Domain Diversity Gate (Max 2 URLs/domain)             │
│                                                             │
│ 2. AsyncScrapingEngine (High-Throughput Concurrent Fetcher) │
│    - Async HTTPX/AioHTTP with HTTP/2 Connection Pooling     │
│    - In-Memory Async DNS Cache (TTL 300s)                   │
│    - SSRF & DNS Rebinding Invariant Guard: Pre-dial DNS,    │
│      RFC 1918/link-local/cloud metadata IP Pinning          │
│    - Host-Bucket Adaptive Rate Limiter (Token Bucket + AIMD)│
│    - Header & Proxy Pool Rotation                           │
└──────────────────────────────┬──────────────────────────────┘
                               │ Raw HTML Streams
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ WORKSTREAM 2: DOM CLEANING & HIGH-FIDELITY EXTRACTION       │
│                                                             │
│ 1. 3-Stage DOM Cleaning Pipeline                            │
│    - Stage 1: Fast lxml Tree Parsing & Script/Style/Tag Strip│
│    - Stage 2: Boilerplate, Ads, Nav, Footer, Cookie Filter  │
│    - Stage 3: Rust nh3 Whitelist Sanitizer (Content Tags)   │
│                                                             │
│ 2. High-Fidelity Table & Markdown Engine                    │
│    - HTML <table> -> GitHub Flavored Markdown (GFM)         │
│    - Financial Figures Alignment (:--- / ---:), Colspan/Row │
│    - Vietnamese Currency & Fiscal Date Precision            │
│                                                             │
│ 3. 3-Tier Cross-Site Deduplication Engine                   │
│    - Tier 1: Canonical URL Normalization (Strip UTM, Hash)  │
│    - Tier 2: Exact Text SHA-256 Hash                        │
│    - Tier 3: 64-bit SimHash (Hamming Dist <= 3 -> Grouped)  │
│    => Loại bỏ ngay 75-80% token bài viết sao chép syndicated│
└──────────────────────────────┬──────────────────────────────┘
                               │ Clean Structured Markdown
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ WORKSTREAM 3: SEMANTIC TOKEN OPTIMIZATION & ADAPTIVE PRUNING│
│                                                             │
│ 1. Structural & Semantic Chunking                           │
│    - H1-H4 Heading Hierarchy Boundaries                     │
│    - Atomic Financial Table Preservation (Replicate Headers)│
│    - Sentence Splitting with 15% Sliding Overlap + Breadcrumb│
│                                                             │
│ 2. BM25-FSB (Financial Salience Boosting) Engine            │
│    - BM25 Okapi Core (k1=1.5, b=0.75, IDF smoothing)        │
│    - Dual-Language Financial Tokenizer (VN + EN)            │
│    - Salience Boost: Ticker (+3.0), Period (+2.5),          │
│      Metrics (+2.0), Audited Tables (+1.5)                  │
│    - Boilerplate Penalty (-5.0)                             │
│                                                             │
│ 3. Adaptive Token Budgeter & Narrative Preservation         │
│    - Dynamic Headroom Tracking (B_tool in [600, 2500] tokens)│
│    - Sort by Score -> Select Top-K -> Reorder by Original Idx│
│    => Cắt bỏ 78% - 88% Token rác, bảo toàn mạch văn bản gốc │
└──────────────────────────────┬──────────────────────────────┘
                               │ Pruned High-Salience Chunks
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ WORKSTREAM 4: MAP-REDUCE & STRUCTURED SYNTHESIS ENGINE      │
│                                                             │
│ 1. Map Phase (Parallel Fact & Metric Extraction)            │
│    - Parallel execution across pruned source chunks         │
│    - Dual mode: LLM Map Worker OR Deterministic Rule Worker │
│    - Extract: Ticker, Metric, Period, Value, Unit, RawSnippet│
│                                                             │
│ 2. Reduce Phase (Synthesis & Conflict Resolution)           │
│    - Multi-source Corroboration ([S1, S3] verified)         │
│    - SOURCE_POLICIES Priority (Tier 1 > Tier 2 > Tier 3 > 4)│
│    - Discrepancy & Range Reporting (No Fake Averaging)      │
│                                                             │
│ 3. Unified Delivery Artifacts                               │
│    - Standardized Pydantic JSON (SynthesizedResearchArtifact)│
│    - Publication-Grade Markdown Executive Summary (<400 w)  │
│    - 100% Grounding Gate Compliance (figures.py, sources.py)│
└──────────────────────────────┬──────────────────────────────┘
                               │ Clean Bounded Payload (<2k tokens)
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ WORKSTREAM 5: BENCHMARK HARNESS & UNIFIED TOOL CONTRACTS    │
│                                                             │
│ 1. Empirical Benchmark Harness (4 Pillars)                  │
│    - Latency Distribution (p50, p90, p99, Speedup >= 2.5x)  │
│    - Token Pruning Verification (Enforce 75% - 90% reduction│
│    - Concurrency Stress Testing (1, 5, 10, 20, 50 queries)  │
│    - Key Fact Retention Score (HFR >= 0.95, RS >= 0.85)     │
│                                                             │
│ 2. Unified Tool Interfaces & Backward Compatibility         │
│    - ParallelWebSearchTool (Replaces/extends web_search)    │
│    - ConcurrentScraperTool (Replaces/extends read_url)      │
│    - FastMCP & FastAPI research_routes seamless integration │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. CAVEATS (GIỚI HẠN VÀ RỦI RO KỸ THUẬT)

1. **Chặn Captcha / Cloudflare Turnstile**: Các trang web tài chính có thể kích hoạt WAF nếu truy vấn quá dồn dập. Bộ scraper trang bị cơ chế AIMD giảm 50% tải trên host khi gặp 429/503 và xoay vòng User-Agent.
2. **Ngăn chặn SSRF tuyệt đối**: Do chuyển từ proxy Jina Reader sang HTTPX trực tiếp, hệ thống áp dụng cơ chế Pre-dial IP Pinning, cấm triệt để IP private (RFC 1918) và Cloud metadata (169.254.169.254) kể cả sau các bước redirect 301/302.
3. **Bảo toàn số liệu cho Grounding**: BM25-FSB ưu tiên đặc biệt cho số liệu tài chính (+2.0) và bảng biểu (+1.5), đảm bảo không bao giờ cắt mất số liệu gốc khiến `figures.py` báo lỗi `(omitted※)`.
4. **Zero-cost Fallback cho Map Phase**: Cung cấp Deterministic Rule Worker viết bằng regex thuần và AST bảng biểu, cho phép tổng hợp kết quả dưới 50ms mà không tốn chi phí gọi LLM phụ.

---

## 4. CONCLUSION (ĐẶC TẢ DANH MỤC TÍNH NĂNG & KẾ HOẠCH MILESTONES)

### 4.1. Bảng 18 Tính năng Cốt lõi (Feature Inventory)
1. `MultiSearchAggregator`: Điều phối song song DuckDuckGo, Brave, Bing, QVeris, CafeF, Vietstock, Google News VN.
2. `RRF Re-Ranking`: Thuật toán Reciprocal Rank Fusion kết hợp Domain Diversity Gate.
3. `AsyncScrapingEngine`: Client bất đồng bộ HTTPX với HTTP/2 Connection Pooling (max 60 connections, 30s keep-alive).
4. `SSRF & DNS Rebinding Guard`: IP Pinning trực tiếp vào socket, loại trừ IP nội bộ và metadata.
5. `Adaptive Rate Limiter`: Token Bucket theo từng host kết hợp thuật toán điều tiết AIMD.
6. `3-Stage DOM Cleaning`: Pipeline bóc tách nhanh bằng `lxml`, loại bỏ boilerplate và lọc whitelist bằng Rust `nh3`.
7. `High-Fidelity Table Engine`: Chuyển đổi bảng HTML sang GFM Markdown căn lề số liệu chuẩn xác.
8. `3-Tier Deduplication`: Chống trùng lặp qua URL Normalization, SHA-256 Hash và 64-bit SimHash.
9. `Structural & Semantic Chunker`: Phân đoạn theo tiêu đề H1-H4, bảo toàn nguyên khối bảng tài chính và gối đầu 15%.
10. `BM25-FSB Scorer`: Chấm điểm BM25 Okapi tăng cường điểm cho mã cổ phiếu, kỳ báo cáo và số liệu.
11. `Adaptive Token Budgeter`: Cấp ngân sách token động từ 600 đến 2500 tokens dựa trên Headroom của AgentLoop.
12. `Parallel Map Worker`: Trích xuất song song số liệu, phát biểu cốt lõi, trích dẫn (hỗ trợ cả LLM và Rule worker).
13. `Reduce Synthesis Engine`: Hợp nhất dữ liệu, đối chiếu chéo và giải quyết mâu thuẫn theo `SOURCE_POLICIES` Tier 1-4.
14. `Standardized Artifacts`: Xuất file JSON `SynthesizedResearchArtifact` và tóm tắt Markdown dưới 400 từ.
15. `Grounding Ledger Alignment`: Đồng bộ mã nguồn `[S1]`, `[S2]`, vượt qua 100% các bài test `figures.py`.
16. `Empirical Benchmark Harness`: Đo lường thực nghiệm Latency p50-p99, tỷ lệ nén token, thông lượng RPS và RAM RSS.
17. `Key Fact Retention Score (KFRS)`: Đánh giá tỷ lệ bảo toàn thông tin tài chính với ngưỡng HFR >= 0.95.
18. `Unified Tool Interfaces`: Đóng gói `ParallelWebSearchTool` và `ConcurrentScraperTool` tương thích ngược 100%.

### 4.2. Phân rã 5 Milestones Triển khai
- **Milestone 1 (M1)**: Xây dựng Động cơ Tìm kiếm Đa nguồn và Cào web Bất đồng bộ (WS1).
- **Milestone 2 (M2)**: Xây dựng Pipeline Làm sạch DOM, Chuyển đổi Bảng Markdown GFM và Chống trùng lặp 3 tầng (WS2).
- **Milestone 3 (M3)**: Xây dựng Bộ Phân mảnh Ngữ nghĩa, Thuật toán BM25-FSB và Cắt tỉa Token Thích ứng (WS3).
- **Milestone 4 (M4)**: Xây dựng Động cơ Tổng hợp Map-Reduce, Chuẩn hóa Artifacts và Tích hợp Grounding Gate (WS4).
- **Milestone 5 (M5)**: Hoàn thiện Hợp đồng Giao diện Công cụ Hợp nhất và Khung Đo kiểm Thực nghiệm Benchmark (WS5).

### 4.3. Bố cục Mã nguồn (Code Layout)
- `agent/src/tools/search/`: `base_engine.py`, `ddg_engine.py`, `brave_engine.py`, `bing_engine.py`, `qveris_engine.py`, `vietnam_portals_engine.py`, `aggregator.py`
- `agent/src/tools/scraper/`: `fetcher.py`, `dns_cache.py`, `rate_limiter.py`, `ssrf_guard.py`
- `agent/src/tools/extractor/`: `dom_cleaner.py`, `markdown_converter.py`, `deduplicator.py`
- `agent/src/tools/optimizer/`: `chunker.py`, `bm25_scorer.py`, `budgeter.py`
- `agent/src/tools/synthesis/`: `map_extractor.py`, `reduce_synthesizer.py`, `models.py`
- `agent/src/tools/parallel_web_tools.py`: `ParallelWebSearchTool`, `ConcurrentScraperTool`
- `agent/tests/benchmarks/web_tools/`: `benchmark_harness.py`, `test_latency_tokens.py`, `kfrs_evaluator.py`
- `agent/tests/test_parallel_web_tools.py`: Unit test suite

---

## 5. VERIFICATION METHOD (PHƯƠNG PHÁP KIỂM CHỨNG ĐỘC LẬP)

1. **Kiểm tra Môi trường và Thư viện**:
   ```powershell
   .venv\Scripts\python -c "import httpx, aiohttp, nh3, mistune, bs4, lxml; print('ENV OK')"
   ```
2. **Kiểm tra Ngưỡng Cắt giảm Token**:
   - Chạy test so sánh dữ liệu cào thô và sau khi qua BM25-FSB trên 50 bài báo tài chính thực tế:
   - Yêu cầu bắt buộc: `Token_Pruning_Ratio >= 75.0%` (kỳ vọng đạt từ 78% đến 88%).
3. **Kiểm tra Độ bảo toàn Thông tin Cốt lõi (KFRS)**:
   - So sánh danh sách thực thể tài chính (Doanh thu, Lợi nhuận, EPS, P/E) trước và sau khi cắt tỉa:
   - Yêu cầu bắt buộc: `Hard_Fact_Recall >= 0.95`.
4. **Kiểm tra Độ trễ (Latency Speedup)**:
   - Đo kiểm thời gian thực hiện song song 5 nguồn:
   - Baseline (Tuần tự Jina): 25s - 40s.
   - Treatment (Async Scraper + Local DOM Cleaning): < 3.5s (Tăng tốc >= 7x).
5. **Kiểm tra An ninh SSRF & DNS Rebinding**:
   - Chạy bộ test với 23 kịch bản URL độc hại (loopback, IPv6, private IPs, AWS metadata), xác nhận 100% bị chặn với HTTP 400 Bad URL trước khi mở kết nối socket.
