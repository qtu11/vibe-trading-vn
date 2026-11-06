# Kế hoạch: nguồn uy tín, sửa lỗi "(omitted※)" và Hội đồng nghiên cứu

**Ngày:** 06/11/2026. **Trạng thái:** đã triển khai (xem §8); tài liệu này giữ
nguyên bối cảnh thiết kế và ghi rõ phần đã làm/khác kế hoạch ban đầu.
**Phạm vi:** chat agent (backend + frontend), grounding gate, nguồn dữ liệu Việt Nam và đa thị trường.

## 1. Vấn đề quan sát được

Ảnh chụp phiên "Nghiên cứu FPT HOSE" cho thấy:

1. Toàn bộ số liệu trong bảng bị thay bằng `(omitted※)`; cuối câu trả lời ghi
   "137 figure(s) ... were omitted".
2. `get_stock_news` trả `unsupported market for code 'FPT.VN'`.
3. Báo cáo trích "TCBS Research", "HSC" nhưng không có bằng chứng nguồn nào
   được hệ thống thu thập trong phiên.
4. Không có phần so sánh chéo nguồn, không có chart, không có hội đồng
   tranh luận, không có khuyến nghị có điều kiện.

## 2. Nguyên nhân gốc (root cause)

`(omitted※)` không phải lỗi hiển thị. Đây là hành vi fail-closed của
**grounding gate** (`agent/src/agent/grounding/release.py`):

- Gate chỉ coi một con số là `observed` khi con số đó nằm trong payload JSON
  của một tool call trong phiên (`EvidenceLedger._ingest_generic_numeric`).
- Số liệu lấy từ web/báo cáo/bài viết dạng **văn bản** không được trích thành
  `EvidenceRecord`, nên không thể là `observed`.
- Muốn dùng số liệu ngoài, model phải khai báo role `cited`. Nhưng `_check_cited`
  yêu cầu token nguồn xuất hiện **trên chính dòng của con số**
  (`citation_not_visible`). Trong bảng markdown, dòng dữ liệu chỉ có số, còn
  nguồn nằm ở caption phía trên → mọi ô bảng bị loại.
- Khi hết lượt sửa, `redacted_release` cắt các figure bị loại và thay bằng
  marker; đó là 137 figure trong ảnh.

Kết luận: không được nới lỏng gate. Phải **đưa nguồn ngoài thành bằng chứng
có thể kiểm chứng** và **cho phép citation hiển thị theo bảng/footnote**.

## 3. Mục tiêu

| ID | Mục tiêu | Tiêu chí nghiệm thu |
| --- | --- | --- |
| G1 | Số liệu từ nguồn uy tín hiển thị được, có dẫn nguồn | Bảng TCBS/HSC hiện số, mỗi bảng có `Nguồn: [S1]`; không còn `(omitted※)` cho số đã thu thập |
| G2 | Phân biệt rõ quan sát / trích dẫn / suy ra / đề xuất | Figures block v2; UI hiển thị nhãn nguồn và mức tin cậy |
| G3 | Phát hiện xung đột giữa các nguồn | Hai nguồn lệch nhau → cảnh báo `EVIDENCE_CONFLICT`, không tự chọn một |
| G4 | Tin tức Việt Nam hoạt động | `get_stock_news(code="FPT.VN")` trả tin, không lỗi unsupported market |
| G5 | Chart nền trong câu trả lời | Fenced block `chart` render ECharts candlestick + volume + MA |
| G6 | Hội đồng tranh luận có cấu trúc | Bull / Bear / Risk / PM; có verdict, confidence, entry/stop, invalidation |
| G7 | Đánh giá và lời khuyên có kỷ luật | Mọi khuyến nghị kèm horizon, điều kiện, rủi ro, nguồn; không hứa lợi nhuận |

## 4. Kiến trúc đề xuất

```
web_search / read_url / doc_reader / get_research_reports / get_stock_news
        │
        ▼
SourceCollector  ──►  SourceRegistry (tier, domain, license)
        │                    │
        ▼                    ▼
SourceRecord + EvidenceRecord(status=cited/observed, quote, url, tier)
        │
        ▼
Grounding gate v2:
  - observed: payload tool (như cũ)
  - cited: source record + quote khớp + citation visible (inline/table/footnote)
  - conflict: cùng metric/kỳ nhưng lệch → EVIDENCE_CONFLICT
        │
        ▼
Figures block v2 + source ledger trong context
        │
        ├──► ChartSpec (deterministic từ OHLC đã quan sát)
        └──► Council run (swarm preset) → verdict JSON + report
```

### 4.1. Source registry

File mới: `agent/src/agent/grounding/sources.py`

```python
@dataclass(frozen=True)
class SourcePolicy:
    source_id: str          # "hose", "fiingroup", "cafef", ...
    display_name: str
    domains: tuple[str, ...]
    tier: int               # 1 official, 2 wire, 3 licensed data/research,
                            # 4 broker/media, 5 social/unknown
    market: tuple[str, ...] # VN, US, CN, FX, CRYPTO, GLOBAL
    kinds: tuple[str, ...]  # filing, price, fundamentals, news, research
    cite_allowed: bool
    redistribute: bool
    terms_url: str | None
```

Bộ nguồn tối thiểu (theo danh sách người dùng cung cấp):

- **Tier 1 – chính thức:** SSC, HOSE/HSX, HNX, VSDC, SBV, NSO/GSO, MoF, SEC
  EDGAR, FED, FRED, BLS, BEA, ECB, BoE, BoJ, CFTC, CME, LBMA, World Gold
  Council, CNINFO, SSE, SZSE, HKEX, CSRC, PBOC, NBS.
- **Tier 2 – hãng tin:** Reuters, Bloomberg, FT, WSJ, CNBC, Barron's, Caixin,
  SCMP.
- **Tier 3 – dữ liệu/nghiên cứu:** FiinGroup/FiinPro X, Vietstock DataFeed,
  LSEG, FactSet, S&P Capital IQ, Wind, Trading Economics, Koyfin, Morningstar,
  CoinGecko, CoinGlass, Glassnode, CryptoQuant, DefiLlama, Dune, Token Terminal.
- **Tier 4 – broker/báo chí VN:** SSI Research, Vietcap, VCBS, TCBS, HSC, MBS,
  BSC, VNDirect, Mirae Asset, KIS, DSC; CafeF, VnEconomy, Báo Đầu tư,
  VnExpress Kinh doanh, NDH, Vietstock news, The Saigon Times, VietnamNews.
- **Tier 5 – social/unknown:** mặc định; chỉ dùng khi người dùng chỉ định rõ,
  và phải hiển thị nhãn "chưa xác minh".

Quy tắc: `cite_allowed` cho tier 1–4; tier 5 cần cảnh báo. Không tự động coi
bài viết lại một thông cáo là xác nhận độc lập (xem `DATA_EVIDENCE_CONTRACTS.md`
§5).

### 4.2. Thu thập bằng chứng từ nguồn ngoài

Sửa `agent/src/agent/grounding/evidence.py`:

- Thêm `SourceRecord` (url, publisher, title, published_at, retrieved_at,
  call_id, sha256, tier, quote, locator).
- `_ingest_sources(tool_name, payload, call_id)` cho các tool:
  `web_search`, `read_url`, `doc_reader`, `get_research_reports`,
  `get_stock_news`, `research_papers`.
- Trích số từ text có ngữ cảnh: mỗi số phải có quote ±120 ký tự, nhãn gần nhất
  (doanh thu, LNST, EPS, P/E...), đơn vị và kỳ. Bỏ năm, số trang, số hiệu văn
  bản, số điện thoại.
- Chuẩn hóa số Việt Nam: `1.234,5` và `1,234.5`; đơn vị `tỷ/nghìn/triệu`;
  giữ raw quote để đối chiếu.
- Ghi `EvidenceRecord(status="cited", ...)`; không trộn với `observed`.
- Bounded: tối đa N số/nguồn, M nguồn/phiên; ghi rõ phần bị cắt.

### 4.3. Citation contract v2

Giữ cú pháp figures block cũ, mở rộng `ref` cho `cited`:

```
12,345 | cited | TCBS Research Q3/2026 | [S1]
```

- `ref` phải là `[S1]` hoặc `S1`, trỏ tới `SourceRecord` của phiên.
- Giá trị phải xuất hiện trong quote đã lưu (sau chuẩn hóa); nếu không →
  `citation_value_not_in_source`.
- Nguồn phải `cite_allowed`; nếu tier 5 → `citation_source_unverified`.
- Hiển thị: chấp nhận một trong ba
  (a) `[S1]` trên dòng của figure,
  (b) caption `Nguồn: ...` / `Source: ...` trong cùng bảng markdown,
  (c) footnote definition `[S1]: ...` ở cuối tài liệu.
- Bảng: caption cách header tối đa 2 dòng, hoặc ngay dưới bảng.
- Xung đột: cùng `(symbol, metric, period)` mà hai `SourceRecord` lệch quá
  tolerance → `EVIDENCE_CONFLICT`; câu trả lời phải nêu cả hai hoặc nói rõ
  nguồn nào được chọn và vì sao.

### 4.4. Source ledger cho model

- Mỗi tool nguồn trả thêm `sources: [{id: "S1", publisher, title, url, tier}]`.
- Thêm tool read-only `list_sources` trả danh sách nguồn đã thu thập trong phiên.
- System prompt: "Trước khi viết số liệu ngoài, gọi `list_sources`; chỉ trích
  nguồn có trong danh sách; dùng `[S1]`."

### 4.5. Sửa `get_stock_news` cho Việt Nam

`agent/src/tools/stock_news_tool.py`:

- Thêm `.VN` vào routing.
- Provider theo thứ tự:
  1. Google News RSS (`hl=vi&gl=VN&ceid=VN:vi`) — không cần key.
  2. CafeF RSS (`cafef.vn/thi-truong-chung-khoan.rss`) lọc theo ticker.
  3. Vietstock news page (scrape có kiểm soát).
- Trả `market="vietnam"`, `source="google_news"`/`"cafef"`, kèm `published_at`.
- Lỗi từng provider không làm hỏng cả tool; ghi `partial=true`.
- Test mock HTTP cho 3 nhánh.

### 4.6. Chart nền

Tool mới `agent/src/tools/price_chart_tool.py`:

```json
{
  "ok": true,
  "chart": {
    "type": "candlestick",
    "symbol": "FPT.VN",
    "venue": "HOSE",
    "currency": "VND",
    "source": "yahoo",
    "as_of": "...",
    "bars": [{"t": "...", "o": 0, "h": 0, "l": 0, "c": 0, "v": 0}],
    "ma": {"ma20": [...], "ma50": [...]},
    "levels": [{"price": 0, "label": "hỗ trợ", "kind": "observed"}]
  }
}
```

- Dữ liệu lấy từ loader đã có; mọi số vào evidence như bình thường.
- Agent chèn fenced block ` ```chart ` (JSON) vào câu trả lời.
- Frontend: `components/charts/ChartBlock.tsx` render ECharts; fallback bảng
  nếu parse lỗi.

### 4.7. Hội đồng nghiên cứu (debate)

Preset mới `agent/src/swarm/presets/vietnam_equity_council.yaml`:

| Vai | Nhiệm vụ | Đầu ra bắt buộc |
| --- | --- | --- |
| Fundamental analyst | BCTC, chất lượng lợi nhuận, dòng tiền, peer | 5 luận điểm + số liệu có nguồn |
| Technical analyst | Xu hướng, MA, RSI, ATR, hỗ trợ/kháng cự | Chart spec + levels |
| Bull advocate | Lập luận mua, catalyst, định giá | 5 luận điểm, target, invalidation |
| Bear advocate | Lập luận bán/tránh, rủi ro | 5 luận điểm, downside |
| Risk officer | VaR, drawdown, thanh khoản, sizing | Position cap, stop, stress |
| PM / Judge | Tổng hợp, phản biện chéo | Verdict JSON + lời khuyên |

Quy tắc tranh luận:
- Mỗi bên phải trích `[S1]`/tool call; không được bịa số.
- PM phải nêu điểm nào bị bác và vì sao.
- Verdict gồm: `stance` (MUA/THÊM/GIỮ/CHỜ/TRÁNH/BÁN), `horizon`,
  `confidence`, `fair_value_range`, `entry_zone`, `stop`, `position_cap`,
  `catalysts`, `risks`, `invalidation`, `sources`, `chart`.
- Không dùng ngôn ngữ hứa hẹn lợi nhuận; nêu giả định và kịch bản.

Tool `run_research_council` (wrapper `run_swarm` + chuẩn hóa đầu ra) để chat
gọi một lần; preset vẫn dùng được trực tiếp.

### 4.8. Đánh giá & lời khuyên

- Bộ kiểm tra `council_contract.py`: bắt buộc đủ trường; `entry_zone` phải
  nằm trong biên độ quan sát hoặc có công thức; `stop` phải thấp hơn entry
  với stance mua; `position_cap` phải kèm % NAV và giả định rủi ro.
- Tính deterministic: R/R ratio, ATR stop, size theo risk 1%/2%.
- UI hiển thị "Đánh giá" và "Lời khuyên" tách khỏi "Dữ kiện".

## 5. Phases triển khai

### Phase 0 — Nghiên cứu & chốt hợp đồng (0.5 ngày)
- Đọc code grounding, swarm, frontend (đang chạy).
- Chốt `SourcePolicy`, `SourceRecord`, figures v2.
- Viết test fixtures cho bảng có caption nguồn.

### Phase 1 — Sửa "(omitted※)" (2–3 ngày)
1. `sources.py` + registry tier 1–5.
2. `SourceCollector` + ingest web/doc/news.
3. `_check_cited` v2: ref, quote match, tier, table/footnote visibility.
4. `list_sources` tool + prompt.
5. Tests: cited pass, quote mismatch, table caption, conflict, tier 5.

### Phase 2 — Tin tức VN + chart (1–2 ngày)
1. `.VN` routing + Google News/CafeF providers.
2. `price_chart_tool` + `chart` fenced block.
3. Frontend chart renderer.
4. Tests HTTP mock + component test.

### Phase 3 — Hội đồng & lời khuyên (3–4 ngày)
1. Preset `vietnam_equity_council`.
2. `run_research_council` + contract validator.
3. Frontend council report (bull/bear columns, verdict card, sources, chart).
4. Tests: preset loads, contract validation, no-advice-without-evidence.

### Phase 4 — Kiểm chứng (1–2 ngày)
- Chạy pytest scoped + frontend vitest + build.
- Chạy lại đúng kịch bản FPT trong ảnh; so sánh trước/sau.
- Ghi docs + changelog.

## 6. Rủi ro & kiểm soát

| Rủi ro | Kiểm soát |
| --- | --- |
| Nới gate làm tăng hallucination | Chỉ chấp nhận cited khi có quote khớp; observed giữ nguyên |
| Nguồn tier 5 giả danh | Registry theo domain; unknown → cảnh báo, không mặc định tin |
| Số Việt Nam 1.234,5 vs 1,234.5 | Lưu raw + normalized + quote; test cả hai |
| Bảng lớn làm chậm gate | Bounded N số/nguồn; cache theo content hash |
| Swarm tốn thời gian/chi phí | `run_research_council` có budget, timeout, fallback single-agent |
| Lời khuyên bị hiểu là cam kết | Template bắt buộc disclaimer, điều kiện, invalidation |

## 7. Câu hỏi cần chốt với người dùng

1. Có chấp nhận gọi Google News RSS/CafeF (không key) cho tin VN không?
2. Có cần lưu toàn văn nguồn hay chỉ quote + hash (bản quyền)?
3. Hội đồng chạy mặc định cho mọi câu hỏi cổ phiếu, hay chỉ khi người dùng
   chọn "Hội đồng"?
4. Ngưỡng tin cậy tối thiểu để hiển thị số cited: tier 1–4 hay chỉ 1–3?

**Đã chốt:** (1) có, Google News RSS trước và CafeF dự phòng, không cần key;
(2) chỉ lưu quote + hash + excerpt có giới hạn, không lưu toàn văn; (3) chỉ chạy
khi người dùng yêu cầu hội đồng hoặc model gọi `run_research_council`; (4) chấp
nhận tier 1–4, tier 5 vẫn hiển thị nhưng gắn nhãn `unverified`.

*(Kế hoạch này sẽ được cập nhật sau khi có báo cáo code-map.)*

## 8. Trạng thái triển khai (06/11/2026)

### 8.1. Đã triển khai

| Hạng mục | Vị trí | Ghi chú |
| --- | --- | --- |
| Source registry tier 1–5 | `agent/src/agent/grounding/sources.py` | `SOURCE_POLICIES`, `SOCIAL_DOMAINS`, `policy_for_url`, nhãn tier |
| `SourceRecord` + ledger | `sources.py`, `ledger.py` | URL dedupe/upsert, giữ `S#`, `grounding_evidence.json` |
| Thu thập nguồn | `sources.py` | `web_search`, `read_url`, `read_document`/`doc_reader`, `get_stock_news` |
| Citation contract v2 | `policies.py` (`_check_cited`), `release.py` | `[S#]` phải resolve; giá trị phải có trong nguồn; caption bảng kế thừa; fallback tên nguồn cũ |
| Source index cho model | `agent/src/agent/tool_lifecycle.py` | Chèn `_sources` vào kết quả tool khi có nguồn |
| Tin tức Việt Nam | `agent/src/tools/stock_news_tool.py` | Google News RSS (`hl=vi&gl=VN`) trước, CafeF RSS sau; `publisher_url`, `partial`, `provider_errors` |
| Chart deterministic | `agent/src/tools/price_chart_tool.py` | `build_price_chart`, `build_chart_spec`, `chart_fence`; OHLCV từ loader |
| Chart UI | `frontend/src/components/charts/ChartBlock.tsx` | Fence `chart`, fallback `<pre>` khi spec lỗi; MA5/MA20 tính ở client |
| Hội đồng | `agent/src/swarm/presets/vietnam_equity_council.yaml` | 6 vai: fundamental, technical, bull, bear, risk, PM/judge |
| Council tool | `agent/src/tools/research_council_tool.py` | `run_research_council`, nhận ticker trần (`FPT` → `FPT.VN`), trả fence `council` |
| Council contract | `agent/src/tools/council_contract.py` | Chuẩn hóa verdict, kiểm tra stop/target/unit, R/R, sizing 1%/2% NAV |
| Council UI | `frontend/src/components/charts/CouncilReport.tsx` | Bull/Bear, Facts/Evaluation/Advice, sources, chart, PM report |
| Nguồn trong reply | `agent/src/agent/loop.py`, `agent/src/session/service.py`, `frontend/src/components/chat/SourceEvidence.tsx` | `reply.metadata.sources` + panel hiển thị tier, verification, published/data-effective/retrieved |

### 8.2. Thời gian hiệu lực của dữ liệu

Mỗi `SourceRecord` có:

- `published_at`: thời điểm nhà xuất bản công bố.
- `data_effective_at`: thời điểm dữ liệu có hiệu lực (kỳ báo cáo, ngày chốt).
- `data_effective_basis`: `explicit` nếu provider cung cấp (`data_effective_at`,
  `effective_at`, `as_of`), hoặc `published_at` nếu phải dùng ngày công bố làm
  fallback. UI ghi rõ `(publication fallback)` trong trường hợp sau.
- `retrieved_at`: thời điểm tool lấy dữ liệu.

Việc một trang nói một con số **không** làm con số đó thành ground truth. Vì vậy
`verification` vẫn là `unverified` cho mọi nguồn trang; `reported_by_council`
chỉ dùng cho nguồn do hội đồng tự khai và không được nhập vào ledger chính.

### 8.3. Khác kế hoạch ban đầu

- **`list_sources` chưa làm thành tool riêng.** Ledger chèn index nguồn trực
  tiếp vào kết quả của từng tool nguồn; model dùng `[S#]` ngay trong ngữ cảnh
  đó. Cách này tránh thêm một tool và tránh model phải nhớ gọi nó.
- **Chưa có bộ phát hiện `EVIDENCE_CONFLICT` tự động.** Gate vẫn kiểm tra từng
  giá trị theo nguồn và cho phép trích cả hai nguồn; việc kết luận nguồn nào
  đúng vẫn là nhiệm vụ của hội đồng/người đọc, không phải của gate.
- **Chart không trả `ma`/`levels` từ backend.** Bars là dữ liệu quan sát; MA5/MA20
  do `CandlestickChart` tính khi render. Mức hỗ trợ/kháng cự do hội đồng nêu
  trong verdict và không được nhập vào evidence ledger.
- **Hội đồng không chạy mặc định.** Chỉ chạy khi model gọi
  `run_research_council` (hoặc người dùng chọn hội đồng), vì chi phí LLM và độ
  trễ.
- **Chỉ chấp nhận cổ phiếu Việt Nam** trong `run_research_council`; preset vẫn
  có thể dùng cho thị trường khác nếu gọi `run_swarm` trực tiếp.

### 8.4. Tiêu chí nghiệm thu

| ID | Trạng thái | Ghi chú |
| --- | --- | --- |
| G1 | Đạt | Số có `[S#]`/caption bảng hợp lệ không còn bị `(omitted※)` |
| G2 | Một phần | Figures + source panel có tier/verification/timestamps; confidence chi tiết chỉ có trong council verdict |
| G3 | Chưa tự động | Hai nguồn lệch nhau vẫn hiển thị được; chưa có cảnh báo xung đột tự động |
| G4 | Đạt | `get_stock_news("FPT.VN")` dùng Google News/CafeF |
| G5 | Đạt | Fence `chart` render candlestick + volume + MA |
| G6 | Đạt | Preset 6 vai + verdict JSON + contract |
| G7 | Đạt | Entry/stop/target/horizon/invalidation/sources + disclaimer; blocked nếu thiếu nguồn |

### 8.5. Kiểm chứng đã chạy

- `python -m pytest tests/test_grounding_sources.py tests/test_grounding_release.py
  tests/test_grounding_figures_contract.py tests/test_grounding_figures_ref_parser.py
  tests/test_grounding_language_parity.py tests/test_stock_news_tool.py
  tests/test_research_council_tool.py tests/test_council_contract.py
  tests/test_price_chart_tool.py tests/test_session_reply_runtime_metadata.py
  tests/test_session_tool_trail.py -q` → **365 passed**.
- `python -m pytest tests/test_agent_grounding.py -q` → **187 passed**.
- `python -m ruff check` trên toàn bộ file Python mới/sửa → sạch.
- `npx tsc -b --pretty false` → passed.
- Vitest các suite mới (`SourceEvidence`, `MessageBubble`, `ChartBlock`,
  `ChartFence`, `CouncilReport`, `CouncilFence`) → **20 passed**.
- Chạy toàn bộ Vitest: **1010 passed / 1026**. 16 lỗi còn lại nằm ngoài phạm vi
  thay đổi này và không chạm component mới:
  - 11 lỗi parity i18n do `en.json` đã có 66 khoá mới (`researchRevision.*`,
    `researchAttempt.*`, `forexRegime.*`) nhưng 12 locale khác chưa có — công
    việc đang làm dở trong working tree;
  - 3 lỗi định dạng số (`25,5%` thay vì `25.5%`, `1.300` thay vì `1,300`) do
    locale hệ thống của máy chạy test là tiếng Việt, không phải lỗi code;
  - 1 lỗi `AgentAvatar` do `BrandMark` đang được sửa dở;
  - 1 lỗi `CryptoBasisLab` do chữ ký `saveResearchRevision` đang thêm tham số
    revision key trong tính năng research-revision chưa hoàn tất.
- Một test copy-action của `MessageBubble` có thể timeout khi chạy chung nhiều
  suite dưới tải cao; chạy riêng thì pass (14/14).

### 8.6. Giới hạn môi trường

- `fastmcp` là dependency đã khai báo trong `pyproject.toml` và
  `agent/requirements.txt`. Sau khi cài, `src.swarm` import được, registry không
  còn `import_failures`, và preset được validate bằng DAG validator thật:
  `inspect_preset("vietnam_equity_council")` → `valid: true`, 6 agent, 6 task,
  4 layer đúng thiết kế. Các test trước đây bị chặn bởi import giờ chạy được
  (`test_model_tool_result_redaction.py`, `test_swarm_grounding.py`,
  `test_research_council_tool.py`, `test_council_contract.py`,
  `test_price_chart_tool.py` → **101 passed**).
- `test_model_tool_result_redaction.py` đọc `messages.json` không chỉ định
  encoding, nên lỗi trên Windows (locale không phải UTF-8); đã sửa test sang
  `encoding="utf-8"` cho khớp với writer. Đây là lỗi portability của test, không
  phải của sản phẩm.
- Chưa chạy lại đúng kịch bản FPT trong ảnh với LLM thật; các hợp đồng đã được
  khóa bằng test offline. Chạy end-to-end vẫn cần cấu hình provider.
- Smoke test mạng thật ngày 2026-11-06 (không dùng mock):
  - `get_stock_news("FPT.VN")` → `ok: true`, `market: vietnam`,
    `source: google_news`, 5 bài thật từ Người Quan Sát, Tuổi Trẻ, CafeF,
    Nghệ An, VietnamNet; không còn lỗi `unsupported market`.
  - `build_price_chart("FPT.VN", max_bars=36)` → 36 nến thật, `VND`,
    `as_of 2026-11-06`, `last_close 50.900`.
  - `GroundingLedger` nạp kết quả tin thật rồi validate bảng có `4.0%` và
    `23.0` với caption `[S1]` → `valid: true`, không redact.
  - `evaluate_verdict` trên snapshot thật → `actionable: true`, R/R `3.2`,
    giá được chuẩn hoá đúng đơn vị.
- Registry bổ sung các đầu báo VN xuất hiện trong smoke test nhưng trước đó bị
  xếp tier 5: `nguoiquansat.vn`, `vietnamnet.vn`, `dantri.com.vn`,
  `bnews.vn` (tier 4). Đầu báo địa phương như `baonghean.vn` vẫn để tier 5 và
  hiển thị nhãn `unverified` — đúng thiết kế "không mặc định tin".
