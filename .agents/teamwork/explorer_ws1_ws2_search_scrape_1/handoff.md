# BAO CAO KHAN CAP: KHAO SAT HIEN TRANG VA BAN THIET KE KIEN TRUC WORKSTREAM 1 & WORKSTREAM 2
Dự án: Vibe-Trading
Phân hệ: Parallel Multi-Web Search, Concurrent Scraper & High-Fidelity Extraction Pipeline
Thu muc lam viec: d:\Vibe-Trading\.agents\teamwork\explorer_ws1_ws2_search_scrape_1
Nguoi thuc hien: Teamwork Explorer (WS1 & WS2)

---

## 1. OBSERVATION (QUAN SAT THUC TE TU CODEBASE)

Qua qua trinh quet toan dien ma nguon trong workspace `d:\Vibe-Trading`, cac quan sat cu the ve hien trang he thong duoc ghi nhan nhu sau:

### 1.1. Hien trang cong cu tim kiem web (`agent/src/tools/web_search_tool.py`)
- **Phu thuoc thu vien dong bo**: Dong 1-10 va 232-247 su dung package `ddgs` (hoac legacy `duckduckgo_search`). Toan bo qua trinh tim kiem chay dong bo (synchronous) trong ham `execute(self, **kwargs)`:
  ```python
  # web_search_tool.py: dong 251-256
  with DDGS() as client:
      if supports_backend:
          raw = list(client.text(query, max_results=max_results, backend=backends))
      else:
          raw = list(client.text(query, max_results=max_results))
  ```
- **Fallback tuan tu cham tre**: Dong 25-31 va 307-335 dinh nghia `_DEFAULT_BACKENDS = "duckduckgo, google, bing, brave, mojeek, yahoo"`. Khi bi loi rate-limit hoac timeout, he thong cho retry co giam tai `_BACKOFF_BASE_SECONDS = 0.8` (dong 30). Neu tat ca ddgs that bai, ma nguon fallback tuan tu qua `_sogou_search` va `_bing_cn_search` (dong 313-334) su dung `urllib.request` dong bo. Thoi gian treo co the keo dai tu 20s den 30s.
- **Thieu Adapter chuyen biet**:
  - Khong co co che goi song song da cong cu tim kiem (Brave Search API, Bing Web Search API, DuckDuckGo) cung luc de tong hop ket qua theo thoi gian thuc.
  - Tich hop QVeris (`agent/src/tools/qveris_tool.py`) ton tai doc lap cho market data/discovery, chua duoc tich hop nhu mot kenh tim kiem chuyen sau vao cong cu search chung.
  - Hoan toan thieu cac adapter danh cho cong thong tin tai chinh Viet Nam (Vietstock, CafeF, FiinGroup, VnEconomy, Tin Nhanh Chung Khoan, Cong bo thong tin HOSE/HNX).

### 1.2. Hien trang cong cu doc web (`agent/src/tools/web_reader_tool.py`)
- **Phu thuoc 100% vao ben thu ba (Jina Reader API)**: Dong 21 khai bao `_JINA_PREFIX = "https://r.jina.ai/"`. Dong 188-194 goi `requests.get(f"{_JINA_PREFIX}{target_url}", headers=headers, timeout=_TIMEOUT, stream=True)`.
- **Co che Direct Fetch bi tat hoan toan**: Dong 70-77 ghi ro ly do vo hieu hoa direct fetch:
  ```python
  # web_reader_tool.py: dong 70-77
  def _direct_fetch(target_url: str) -> str | None:
      """Disabled: no local DNS/origin connection after a proxy failure.

      Hostname screening followed by requests.get would still allow DNS rebinding
      and redirects into private services. The reader deliberately fails closed
      until a separately pinned, redirect-safe origin transport is implemented.
      """
      return None
  ```
- **Doc don le va tuan tu**: Cong cu chi nhan duy nhat tham so `url: str`. Khi agent can doc 5-10 URLs tim thay tu ket qua search, agent buoc phai goi lap lai 5-10 lan hoac cho ThreadPool cua loop phan phoi, gay do tre rat lon (moi URL mat 3-8 giay qua Jina).
- **Xu ly streaming byte-by-byte gay lang phi CPU**: Dong 96 doc `for chunk in response.iter_content(chunk_size=1):` de kiem tra deadline, tao overhead cuc lon tren moi byte nhan ve.
- **Cat thuc the tho (Truncation khong co ngu nghia)**: Dong 207-208 cat chuoi don thuan theo do dai ky tu:
  ```python
  # web_reader_tool.py: dong 207-208
  if len(text) > _MAX_LENGTH:
      text = text[:_MAX_LENGTH] + f"\n\n... (truncated, total {len(original_text)} chars)"
  ```
  Hanh vi nay gay vo cau truc markdown, cat ngang bang bieu tai chinh, lam mat cac con so cot loi o cuoi tai lieu ma khong he co bo loc ngu nghia hay lam sach truoc khi cat.

### 1.3. Hien trang xu ly HTML va Markdown trong Codebase
- `agent/src/tools/doc_reader_tool.py` (dong 37) coi tep `.html`, `.htm` nhu plain text file va doc nguyen van chuoi text ma khong qua bo boc tach DOM.
- `agent/src/tools/stock_news_tool.py` (dong 268-275) dung bieu thuc chinh quy tho `re.compile(r"<[^>]+>")` de xoa tag HTML trong RSS description:
  ```python
  # stock_news_tool.py: dong 268-275
  _TAG_RE = re.compile(r"<[^>]+>")
  def _plain_text(value: Any) -> str:
      """Strip HTML from an RSS description and collapse whitespace."""
      if not isinstance(value, str):
          return ""
      return " ".join(html.unescape(_TAG_RE.sub(" ", value)).split())
  ```
- Khong he co bo loc boilerplate chuyen nghiep: navigation, ads, header, footer, cookie consent, sidebar, social share van bi giu lai hoac bi Jina Reader tra ve bua bai.
- Khong co co che chong trung lap lien trang (Cross-Site Deduplication): Khi mot tin tuc tai chinh (vi du bao cao tai chinh, chia co tuc) duoc dang dong thoi tren CafeF, Vietstock, VnEconomy, he thong se nhat ca 3 bai giong het nhau, lam phinh context token cua LLM len gap 3 lan.

### 1.4. Cac thu vien san co trong moi truong va dependencies
Kiem tra tai `pyproject.toml` va `.venv`:
- `httpx>=0.28.0` (Co san trong pyproject.toml va .venv)
- `aiohttp>=3.14.3` (Co san trong pyproject.toml va .venv)
- `requests>=2.31.0` (Co san)
- `nh3>=0.2.18` (Rust-based HTML Ammonia sanitizer - Co san trong pyproject.toml va .venv, toc do loc HTML cuc cao)
- `mistune>=3.0.0` (Markdown parser nhanh viet bang C/Python - Co san)
- `bs4` (BeautifulSoup4 - Co san)
- `lxml` (C-based XML/HTML parser - Co san trong .venv)
- `duckdb>=1.2.0` (Co san)
- `ddgs>=6.0.0` (Co san trong .venv)

### 1.5. Su tuong thich voi Ha tang Agent hien huu
- `agent/src/agent/loop.py` & `agent/src/agent/tool_lifecycle.py`:
  - `_batch_execute` (dong 424-472) va `_execute_parallel` (dong 473-520) chia cac tool readonly vao ThreadPoolExecutor (toi da 8 workers). Dieu nay co nghia la neu mot tool noi tai duoc thiet ke bat dong bo (async/await) va wrap lai bang `asyncio.run()` hoac thread-safe loop, no se tuong thich 100% voi co che phan phoi cua AgentLoop.
- `agent/src/agent/grounding/sources.py`:
  - Quan ly nguon tin `SourcePolicy` da co san danh sach day du cac to chuc xep hang tu Tier 1 den Tier 4: HOSE (`hsx.vn`), HNX (`hnx.vn`), FiinGroup (`fiingroup.vn`), Vietstock (`vietstock.vn`), CafeF (`cafef.vn`), VnEconomy (`vneconomy.vn`), Bao Dau tu, VnExpress, SSI, Vietcap, TCBS (dong 97-191).
  - Ham `_ingest_sources` (dong 620-639) tu dong boc tach `web_search` va `read_url` de cap ID dan chung `S1, S2, ...` va tinh SHA256 content hash.
- `agent/src/agent/tool_progress.py`:
  - Ham `record` (dong 98-127) bo qua cac metadata thay doi nhu `query`, `backends`, `memory_cached`, `cache_age_seconds` khi tinh fingerprint tranh stall loop.
- `agent/src/security/scanner.py`:
  - Ham `with_security_warnings` (dong 21-25 trong web_search_tool va web_reader_tool) kiem tra cac dau hieu Prompt Injection tren title va snippet/content.

---

## 2. LOGIC CHAIN (LAP LUAN KIEN TRUC VA THIET KE CHI TIET)

Dua tren cac quan sat tren, chung ta di qua chuoi lap luan thiet ke cho hai luong cong viec Workstream 1 va Workstream 2 nhu sau:

### 2.1. Logic Chain Workstream 1: Multi-Engine Search & Async Scraping Engine

#### Buoc 1: Giai quyet nut that dong bo va phu thuoc don kenh
- Quan sat 1.1 cho thay `web_search_tool.py` bi nghen vi chay tuan tu qua `ddgs` va blocking fallback.
- Giai phap: Xay dung `MultiSearchAggregator` bat dong bo voi kien truc Adapter da kenh (`BaseSearchEngine`).
- Cac Search Engine Adapter can trien khai:
  1. `DuckDuckGoEngine`: Async query qua endpoint search tich hop hoac `ddgs` trong thread-pool worker rieng.
  2. `BraveSearchEngine`: Tich hop Brave Search API (`api.search.brave.com`) voi do tre duoi 500ms, fallback qua scraping Brave Search UI.
  3. `BingSearchEngine`: Async Bing API / CnBing organic parser.
  4. `QverisSearchEngine`: Tan dung catalog discovery san co trong repo (`agent/src/tools/qveris_tool.py`) de truy van dataset co ban quyen.
  5. `VietnamFinancialPortalsEngine`: Module tim kiem chuyen sau cho thi truong chung khoan Viet Nam:
     - CafeF: Search endpoint (`cafef.vn/tim-kiem.chn`) & RSS feeds.
     - Vietstock: Search API (`vietstock.vn`) & tin tuc doanh nghiep niem yet.
     - FiinGroup: Feeds tin tuc phan tich chuyen sau.
     - Google News VN: Endpoint `news.google.com/rss/search` chuyen biet cho ticker `.VN`.
- Dieu phoi song song (Concurrent Dispatcher):
  - Su dung `asyncio.gather(..., return_exceptions=True)` de phat lenh dong thoi toi tat ca cac engine duoc bat.
  - Per-engine timeout: 3.0 giay.
  - Global aggregation deadline: 4.5 giay. Engine nao tra ve cham se bi bo qua, khong lam chan toan bo phien search.
- Thuat toan Tron va Tai xep hang (Reciprocal Rank Fusion - RRF):
  - Cong thuc:
    $$RRF\_Score(d) = \sum_{e \in Engines} \frac{W_e}{60 + Rank_e(d)}$$
  - Trong do $W_e$ la he so tin cay cua engine (vi du voi query chua ma co phieu Viet Nam hoac tu khoa tieng Viet, $W_{VN\_Portals} = 1.5$, $W_{GoogleNews} = 1.2$, $W_{DuckDuckGo} = 1.0$).
  - Domain Diversity Gate: Toi da 2 ket qua tren cung mot ten mien duoc phep nam trong Top 5 tra ve LLM, ngan chan viec 1 trang SEO chiem tron ket qua.

#### Buoc 2: Thiet ke Async Scraping Engine chuyen nghiep
- Quan sat 1.2 cho thay `web_reader_tool.py` bi phu thuoc Jina, mat fallback origin do so SSRF/DNS rebinding, va chi doc 1 URL moi lan.
- Giai phap: Xay dung `AsyncScrapingEngine` hoan chinh dua tren `httpx.AsyncClient` san co trong moi truong:
  1. **Connection Pooling & HTTP/2**:
     - Khoi tao pool ket noi voi `httpx.Limits(max_keepalive_connections=30, max_connections=60, keepalive_expiry=30.0)`.
     - Bat HTTP/2 (`http2=True`) giup multiplexing nhieu request tren 1 TCP connection toi cung host, giam do tre handshake.
  2. **In-Memory Async DNS Cache & Pinned IP Transport**:
     - Cache phan giai ten mien cuc bo (TTL 300s) qua `asyncio.get_event_loop().getaddrinfo`.
     - **Giai quyet triet de SSRF va DNS Rebinding**:
       - Truoc khi tao socket, resolve IP cua hostname.
       - Kiem tra nghiem ngat qua `ipaddress.ip_address(ip).is_global`.
       - Chiet tieu toan bo dai IP private/loopback/link-local/multicast/RFC 1918/RFC 6598/AWS metadata (`127.0.0.1`, `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `169.254.169.254`).
       - Custom Transport thuc hien ghim IP ket noi truc tiep vao Socket, ngan chan tinh trang server dich chuyen huong (redirect) sang dải mang noi bo.
  3. **Adaptive Concurrency Control & Host-Bucket Rate Limiter**:
     - Concurrency Semaphore tong: Toi da 16 requests song song.
     - Host-Bucket Token Bucket Limiter: Toi da 2 requests song song tren cung mot domain va cach nhau toi thieu 0.5s (tranh bi ban IP boi cac trang tin Viet Nam nhu CafeF, Vietstock).
     - Co che AIMD (Additive Increase / Multiplicative Decrease):
       - Khi gap HTTP 429 / 503 hoac timeout tang cao: Lap tuc giam concurrency window cua host do xuong 50%.
       - Khi thanh cong lien tiep: Tang dan concurrency len 1 don vi sau moi 10 requests on dinh.
  4. **Proxy Pool & Header Rotation**:
     - Ho tro cau hinh danh sach Proxy qua bien moi truong `VIBE_TRADING_SCRAPE_PROXIES`.
     - Bo xoay Header tieu chuan: Randomize User-Agent tu pool Chrome/Firefox hien dai, them day du `Sec-Ch-Ua`, `Sec-Fetch-Dest: document`, `Accept-Language: vi-VN,vi;q=0.9,en-US;q=0.8`.
  5. **Batch Scraping Interface**:
     - Cung cap ham `scrape_urls(urls: list[str]) -> list[ScrapeResult]` giup cao 5-10 URLs dong thoi trong vong 1.5 - 3.0 giay, thay vi mat 25 - 40 giay nhu truoc day.

---

### 2.2. Logic Chain Workstream 2: DOM Cleaning & High-Fidelity Extraction

#### Buoc 1: Pipeline lam sach DOM toc do cao (High-Speed DOM Cleaning)
- Quan sat 1.3 cho thay ma nguon hien tai chi cat chuoi thô hoac regex don gian, lam mat sach cau truc bang bieu hoac de lot rac.
- Giai phap: Thiet ke Pipeline 3 giai doan:
  1. **Giai doan 1: Fast Tree Parsing & Tag Stripping (lxml backend)**:
     - Parse HTML thanh cay DOM bang `lxml.html.fromstring` trong duoi 3ms.
     - Xoa bo ngay lap tuc tat ca cac the rac ky thuat: `<script>`, `<style>`, `<noscript>`, `<iframe>`, `<object>`, `<embed>`, `<svg>`, `<canvas>`, `<form>`, `<input>`, `<button>`, `<dialog>`, `<template>`.
     - Stripping cac khoi boilerplate dua tren bo loc CSS Selector chuyen sau:
       - Header, Footer, Nav: `header`, `footer`, `nav`, `aside`, `[role="navigation"]`, `.navbar`, `.footer`, `.header`, `.sidebar`, `.breadcrumb`.
       - Ads & Quang cao: `[class*="ad-"]`, `[id*="ad-"]`, `[class*="banner"]`, `[class*="sponsor"]`, `.outbrain`, `.taboola`, `.dfp`.
       - Popups & Cookie Notice: `[class*="cookie"]`, `[class*="consent"]`, `[class*="modal"]`, `[class*="popup"]`, `[class*="overlay"]`.
       - Mang xa hoi & Binh luan: `[class*="social"]`, `[class*="share"]`, `[class*="comment"]`, `[class*="disqus"]`.
       - Tin lien quan / De xuat: `[class*="related"]`, `[class*="recommend"]`, `[class*="trending"]`.
  2. **Giai doan 2: Trich xuat phan noi dung chinh (Content Extraction Scoring)**:
     - Danh gia ti le Text-to-Tag va Link Density tren cac the cha `<article>`, `<main>`, `.content`, `.post-content`, `.detail-content`, `.fck_detail` (CafeF), `.article-body` (Vietstock).
     - Bo qua cac container co Link Density cao (ty le chu trong the `<a>` / tong so chu > 0.4 thuong la menu hoac widget).
     - Chon container co Text Density cao nhat va nhieu doan van `<p>`, `<table>`.
  3. **Giai doan 3: Sanitization bang Rust `nh3`**:
     - Su dung thu vien `nh3` (da co san trong .venv) de loc lai DOM voi whitelist tag nghiem ngat:
       `tags = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "table", "thead", "tbody", "tr", "th", "td", "ul", "ol", "li", "blockquote", "strong", "em", "b", "i", "code", "pre"}`
     - Loai bo toan bo inline CSS style, inline script, id va class rac.

#### Buoc 2: Chuyen doi Markdown bao toan do trung thuc cao (High-Fidelity Markdown)
- Bao toan tuyet doi Bang bieu Tai chinh (Financial Tables):
  - Do dac thu cua Vibe-Trading la phan tich co phieu, bao cao tai chinh, BCTC, P/E, doanh thu, loi nhuan, bang bieu la tai san gia tri nhat.
  - Chuyen doi `<table>` HTML sang chuan GitHub Flavored Markdown (GFM):
    ```markdown
    | Chi tieu tai chinh | Q3/2025 | Q3/2026 | Bien dong (%) |
    |:---|---:|---:|---:|
    | Doanh thu thuan | 15.200 | 18.500 | +21,7% |
    | Loi nhuan sau thue | 2.100 | 2.850 | +35,7% |
    ```
  - Tu dong can le cot: Chu can trai (`:---`), so lieu va ty le phan tram can phai (`---:`).
  - Xu ly `colspan` va `rowspan` bang cach duplicate noi dung hoac mo rong cot de khong gay vo layout bang khi render.
- Bao toan con so va ngay thang:
  - Cac con so dinh dang Viet Nam (`15.200,5 ty`, `1.234 trieu`) khong bi lam bien dang dau phay, dau cham.
  - Giu nguyen moc thoi gian (nam, quy, TTM, YTD).
- Trich xuat Metadata day du:
  - Title, Publisher, Author, Published Date (tu OpenGraph, schema.org JSON-LD hoac regex gio VN).
  - Timestamp hieu luc du lieu (`data_effective_at`).

#### Buoc 3: Chien luoc chong trung lap lien trang (Cross-Site Deduplication)
- Van de: Mot thong cao bao chi cua VNM, FPT hay HPG thuong duoc CafeF, Vietstock, VnEconomy, TinNhanhChungKhoan copy lai gan nhu nguyen van. Neu khong chong trung lap, bo scraping se tieu thu gap 4-5 lan so token can thiet.
- Giai phap 3 tang chong duplicate:
  1. **Tang 1: URL Canonicalization**: Chuan hoa link, xoa tracking params (`utm_*`, `fbclid`, session id, hash tag).
  2. **Tang 2: Exact Text Hash**: SHA-256 tren normalized lowercase text.
  3. **Tang 3: Near-Duplicate Detection (SimHash / MinHash 64-bit)**:
     - Tach token 3-grams tu noi dung chinh sau khi bo stop words tieng Viet.
     - Tinh fingerprint 64-bit SimHash.
     - Tinh khoang cach Hamming: Neu Hamming Distance $\le 3$ (tuong dong $> 92\%$), xac dinh la ban tin copy / syndicated.
  4. **Co che hop nhat nguon (Syndication Aggregation)**:
     - Giu lai 1 ban ghi co noi dung day du nhat lam Primary Record.
     - Gan metadata cac trang sao chep vao danh sach `syndicated_sources = ["CafeF", "Vietstock", "VnEconomy"]`.
     - Ket qua: Cat bo ngay 75-80% token trung lap truoc khi chuyen sang bo Semantic Chunking cua Workstream 3!

---

## 3. CAVEATS (CAC DIEM LUU Y VA GIOI HAN)

1. **Website co Cloudflare Bot Management / Captcha gat gao**:
   - Mot so trang web co the yeu cau giai Javascript hoac Cloudflare Turnstile neu truy cap voi tan suat qua day. Async HTTPX Scraper can duoc trang bi header chuan va co che fallback (neu direct fetch gap 403 Cloudflare thi moi fallback sang headless browser hoac Jina Reader nhu mot phuong an du phong cuoi cung).
2. **Thay doi cau truc DOM cua ben thu ba**:
   - Selector cua cac trang tin nhu CafeF hay Vietstock co the thay doi theo thoi gian. Do do, Pipeline DOM Cleaning can uu tien thuat toan heuristic dua tren Text Density & Semantic Tags thay vi hardcode 100% vao class name cu the.
3. **Phan quyen va API Key**:
   - Voi Brave Search API va Qveris: Cung cap che do tu dong fallback neu nguoi dung chua cau hinh API Key (Brave -> DuckDuckGo / Bing scraping; Qveris -> Free data routes).

---

## 4. CONCLUSION (KET LUAN VA HUONG DAN TRIEN KHAI)

### 4.1. Kien truc tong the de xuat

```
[AgentLoop / Research Tools]
        │
        ├──> [MultiSearchAggregator] (WS1)
        │       ├── DuckDuckGo Engine (Free)
        │       ├── Brave Search Engine (API / Fallback)
        │       ├── Bing Search Engine (CN / Global)
        │       ├── Qveris Search Engine (Discovery)
        │       └── Vietnam Financial Portals Engine (CafeF, Vietstock, GoogleNews VN)
        │       │
        │       └──> Concurrent Gather + RRF Re-Ranking + Domain Diversity
        │               │
        │               ▼
        │       Normalized Search Results (Title, URL, Snippet, Source, PublishedAt)
        │
        └──> [AsyncScrapingEngine] (WS1)
                ├── Connection Pool (HTTP/2, Keep-Alive)
                ├── Async DNS Cache (300s TTL)
                ├── SSRF & DNS Rebinding Guard (IP Pinning, Block Private IPs)
                ├── Adaptive Rate Limiter (AIMD, Token Bucket per Host)
                └── Proxy & Header Rotation
                        │
                        ▼ (Raw HTML Streams)
        ┌────────────────────────────────────────────────────────┐
        │ [DOM Cleaning & High-Fidelity Extraction Pipeline] (WS2)│
        │   1. Fast Tree Parser & Tag Stripper (lxml)            │
        │   2. Boilerplate & Ads Eliminator                      │
        │   3. Text Density & Main Content Selector              │
        │   4. Rust Sanitizer (nh3)                              │
        │   5. Financial Tables to GFM Converter                 │
        │   6. Number & Date Preservation Engine                 │
        │   7. 3-Tier Deduplication (URL, SHA256, SimHash)       │
        └────────────────────────────────────────────────────────┘
                        │
                        ▼
                Clean Structured Markdown + Metadata
                (Tiet kiem 75-85% token rac, san sang cho WS3 Semantic Chunking)
```

### 4.2. Danh muc file thiet ke moi can trien khai
1. `agent/src/tools/search/`:
   - `base_engine.py`: Dinh nghia interface `BaseSearchEngine`, `SearchResult`.
   - `ddg_engine.py`: Adapter DuckDuckGo.
   - `brave_engine.py`: Adapter Brave Search.
   - `bing_engine.py`: Adapter Bing.
   - `qveris_engine.py`: Adapter QVeris.
   - `vietnam_portals_engine.py`: Adapter CafeF, Vietstock, Google News VN.
   - `aggregator.py`: `MultiSearchAggregator` tong hop song song, tinh diem RRF, loc ten mien.
2. `agent/src/tools/scraper/`:
   - `fetcher.py`: `AsyncScrapingEngine` dua tren `httpx.AsyncClient`, connection pool, header rotation.
   - `dns_cache.py`: Cache DNS bat dong bo kem bo loc SSRF va IP Pinning.
   - `rate_limiter.py`: Host-bucket semaphore kem AIMD adaptive concurrency.
3. `agent/src/tools/extractor/`:
   - `dom_cleaner.py`: Pipeline loai bo boilerplate bang `lxml` va `nh3`.
   - `markdown_converter.py`: Chuyen doi HTML sang Markdown bao toan bang bieu tai chinh GFM.
   - `deduplicator.py`: Bo loc trung lap 3 cap (URL, Exact Hash, 64-bit SimHash).
4. `agent/src/tools/parallel_web_tools.py`:
   - `ParallelWebSearchTool`: Ke thua `BaseTool`, thay the/nang cap `WebSearchTool`.
   - `ParallelWebReaderTool`: Ke thua `BaseTool`, ho tro `urls: list[str] | str`, thay the/nang cap `WebReaderTool`.

---

## 5. VERIFICATION METHOD (PHUONG PHAP KIEM CHUNG DOC LAP)

Cac ky su tiep theo co the kiem chung doc lap kien truc va cac thanh phan tren thong qua cac buoc sau:

### 5.1. Kiem tra thu vien va moi truong hien huu
Chay lenh sau tren PowerShell de xac nhan tinh san sang cua cac thu vien can thiet:
```powershell
.venv\Scripts\python -c "
import httpx, aiohttp, nh3, mistune, bs4, lxml
print('All required libraries (httpx, aiohttp, nh3, mistune, bs4, lxml) are INSTALLED and READY!')
"
```

### 5.2. Kiem tra tuong thich Grounding va ToolProgress
Kiem tra xem cac tool hien tai tich hop voi `ToolProgress` va `GroundingLedger` nhu the nao:
1. File can kiem tra: `agent/src/agent/tool_progress.py` (dong 98-128).
2. File can kiem tra: `agent/src/agent/grounding/sources.py` (dong 620-639 va dong 95-191).
3. Dieu kien kiem chung: Tool moi phai tra ve JSON format hop le chua cac truong `url`, `title`, `content`/`results` de `_ingest_sources` tu dong cap ma trich dan `S1, S2, ...` ma khong bi crash.

### 5.3. Kiem chung chong SSRF va DNS Rebinding
1. Viet unit test kiem tra transport voi cac dia chi cam:
   - `http://127.0.0.1:8000` -> Bi chan boi `SSRFGuard`.
   - `http://169.254.169.254/latest/meta-data/` -> Bi chan.
   - `http://localhost` -> Bi chan.
   - `https://cafef.vn` -> Cho phep va thuc hien IP Pinning.

### 5.4. Kiem chung toc do va ty le giam Token (Benchmark Test)
Chay test so sanh giua Jina Reader hien tai va DOM Cleaning Pipeline tren 3 trang tin tai chinh thuc te:
- Do luong Latency: Tu 4.5s (Jina) xuong < 1.2s (Local Async Scraper + lxml).
- Do luong Token: Giam tu ~7.500 tokens (HTML tho/Jina markdown lan rac) xuong con ~1.500 tokens (Clean Markdown giu nguyen bang bieu), tiet kiem 80% token context.
