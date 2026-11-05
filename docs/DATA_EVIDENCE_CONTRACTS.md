# Hợp đồng dữ liệu, evidence và kết quả nghiên cứu

**Ngày:** 04/11/2026. **Trạng thái:** contract mục tiêu để mở rộng code `0.1.18`; các tên record/field mới dưới đây chưa phải schema hay endpoint đã phát hành. Contract hiện có của Swarm, Strategy Store, Forex và paper trading vẫn là nguồn chuẩn khi gọi API thật.

Tài liệu này làm rõ những chi tiết khiến hai báo cáo nhìn giống nhau nhưng có ý nghĩa khác: giá của sản phẩm nào, ở thời điểm nào, điều chỉnh ra sao, ai trích xuất, bằng chứng nào được biết khi quyết định và đơn vị của con số. Liên hệ [kiến trúc](MULTI_MARKET_ARCHITECTURE.md) và [baseline](SOURCE_BASELINE.md).

## 1. Nguyên tắc chung

1. Giữ raw payload/bản gốc hoặc content identity được phép lưu; normalized record luôn liên kết raw.
2. Thiếu khác với 0. Giá trị không tính được dùng `null` kèm lý do, không serialize NaN/Infinity như số hợp lệ.
3. Phân biệt quan sát, trích xuất, giả định, dự báo và diễn giải. LLM không được tự “hoàn thiện” input còn thiếu.
4. UTC có offset cho lưu trữ; giữ timezone/lịch phiên gốc cho diễn giải. Không tự gán timezone cho timestamp mơ hồ.
5. Mỗi adapter khai báo units, precision, coverage, price type, auth/license và policy fallback.
6. Schema, parser, strategy, source policy và market rules có version. Sửa dữ liệu tạo revision mới.

## 2. InstrumentIdentity

| Field đề xuất | Ý nghĩa | Validation |
| --- | --- | --- |
| `instrument_id` | ID nội bộ ổn định | Không dùng ticker trần làm khóa toàn hệ thống |
| `market` | VN_EQUITY / FOREX / CRYPTO và domain khác khi có | Enum mapping rõ với market IDs hiện tại |
| `venue` | HOSE/HNX/UPCOM, broker/server, exchange hoặc chain | Bắt buộc khi semantics phụ thuộc venue |
| `native_symbol` | Mã chính xác vendor/broker nhận | Giữ suffix và case có ý nghĩa |
| `product_type` | Equity, spot, CFD, linear_perpetual, inverse_perpetual... | Không suy duy nhất từ tên symbol |
| `base_currency`, `quote_currency` | Hai phía của quote khi áp dụng | Không đồng nhất quote với account/settlement currency |
| `settlement_currency` | Tiền định giá nghĩa vụ/PnL | Phải rõ trước khi gộp kết quả |
| `contract_multiplier` | Quy mô hợp đồng | Có nguồn/spec version và ngày hiệu lực |
| `tick_size` hoặc `price_increment_rule`, `volume_step`, `min_volume` | Bước giá/khối lượng và minimum | Scalar chỉ khi bước giá cố định; thị trường có tick theo vùng giá cần bảng/rule và spec reference có version |
| `valid_from`, `valid_to` | Thời gian định danh/spec có hiệu lực | Symbol rename/contract rollover không ghi đè lịch sử |

`FPT.VN`, `XAUUSD` và `BTC-USDT-PERP` chỉ là ví dụ định dạng. Không coi `.VN` là bằng chứng mọi sàn Việt Nam đã được hỗ trợ; không suy mọi `XAUUSD` có cùng lot; không route `BTC-USDT` và perpetual vào một sổ kế toán mà thiếu product mapping.

## 3. Thời gian và point-in-time

| Timestamp | Câu hỏi trả lời |
| --- | --- |
| `event_at` | Sự kiện/quote xảy ra khi nào theo nguồn? |
| `period_end` | Số liệu tài chính thuộc kỳ nào? |
| `published_at` | Nguồn công bố phiên bản này lúc nào? |
| `available_at` | Theo bằng chứng, dữ liệu có thể được biết/sử dụng từ lúc nào? |
| `received_at` | Hệ thống nhận được lúc nào? |
| `parsed_at` | Parser tạo extraction lúc nào? |
| `computed_at` | Feature, định giá hoặc signal được tính lúc nào? |
| `analysis_as_of` | Điểm cắt dữ liệu của báo cáo/backtest? |
| `recorded_at` | Version được đưa vào kho nội bộ lúc nào? |

`period_end <= analysis_as_of` chưa đủ cho PIT. Điều kiện tối thiểu của dữ kiện dùng trong mô phỏng là phiên bản đã công bố và `available_at <= decision_at`. Nếu không biết giờ công bố, phải lưu mức chính xác `date_only`/`unknown`; policy bảo thủ về phiên giao dịch tiếp theo cần được ghi và kiểm định, không tự chọn một giờ thuận lợi.

Tách hai chế độ nghiên cứu:

- **Historical reconstruction:** dùng bằng chứng về thời điểm thông tin từng có công khai; ngày ingest hiện tại không ngăn nghiên cứu quá khứ, nhưng phải chứng minh lịch sử publication/revision.
- **Recorded replay:** chỉ dùng record có mặt trong log tại thời điểm mô phỏng; kiểm tra thêm `received_at`/ingest cutoff và snapshot membership.

BCTC điều chỉnh năm sau không thay thế bản đã biết trong backtest năm trước. Giá qfq tính từ corporate actions tương lai cũng cần policy riêng cho feature và fill; không lấy chuỗi điều chỉnh làm execution price mặc định.

## 4. SourceRecord và DocumentVersion

| Nhóm | Field mục tiêu |
| --- | --- |
| Định danh | `source_id`, canonical URL, document ID, issuer, title, language, mime type |
| Quyền sử dụng | license/terms URL, access class, entitlement reference, storage/redistribution policy |
| Lịch sử | published/available/retrieved times, revision ID, supersedes, correction reason |
| Nội dung | raw content hash, raw storage reference, size, response metadata cần thiết |
| Xử lý | parser/OCR name+version, extraction time, warnings, content hash sau chuẩn hóa |
| Phạm vi | instrument/company IDs, kỳ kế toán, báo cáo hợp nhất/riêng lẻ, kiểm toán/soát xét |

URL là locator, không phải content identity: cùng URL có thể trả bản sửa đổi. Nếu không được phép lưu full text, giữ metadata/hash và phần trích được phép; report phải nói rõ giới hạn khả năng tái đọc. Không chuyển `read_url` thành cam kết được cấp phép crawl/redistribute toàn bộ portal.

## 5. EvidenceFact

| Field đề xuất | Quy tắc |
| --- | --- |
| `evidence_id`, `document_version_id` | Truy được về đúng revision |
| `source_type` | Filing, audited_statement, broker_estimate, news, exchange_feed, onchain... |
| `locator` | Trang PDF + bảng/hàng/cột; HTML selector/section; tx hash/log index khi on-chain |
| `exact_quote` hoặc raw cell | Giữ đoạn/bảng hỗ trợ trực tiếp, trong phạm vi quyền sử dụng |
| `reported_value`, `normalized_value` | Tách giá trị nguyên bản với giá trị đã chuẩn hóa |
| `unit`, `scale`, `currency`, `sign` | Ví dụ nghìn/triệu/tỷ phải biểu diễn rõ |
| `period`, `consolidation`, `accounting_basis` | Không trộn số quý lẻ với lũy kế hoặc riêng lẻ với hợp nhất |
| `fact_kind` | reported / derived / estimate / assumption |
| `verification_status` | unverified / extracted / cross_checked / human_reviewed / disputed |
| `derivation` | Công thức, input evidence IDs, code/function version |
| `warnings` | OCR mơ hồ, thiếu trang, xung đột, đơn vị suy đoán, timestamp thiếu |

`extracted` không có nghĩa đã xác minh đúng. Hai báo trích cùng một thông cáo là hai bản sao của một nguồn gốc, không phải hai xác nhận độc lập. Một PDF có chữ ký kiểm toán không làm mọi dự báo của analyst trở thành số đã kiểm toán.

Mô hình entity/activity/agent trong [W3C PROV-DM](https://www.w3.org/TR/prov-dm/) là tài liệu tham khảo cho lineage. Các field ở đây là thiết kế của dự án, chưa phải implementation PROV đầy đủ.

## 6. MarketObservation và Candle

| Nhóm | Contract mục tiêu |
| --- | --- |
| Identity | Instrument ID, venue, native symbol, connection/account khi broker-bound |
| Event | Event ID, source sequence/cursor nếu có, event_at, received_at |
| Giá | bid/ask/last/mid/mark/index riêng; quote currency, tick size, precision |
| Volume | value + unit: shares/base/quote/contracts/tick count; không tráo loại |
| Nến | interval, bar_open_at, bar_close_at, OHLCV, is_closed, completeness, source |
| Chất lượng | stale/gap/duplicate/out_of_order/session_closed/unknown, reason codes |
| Reproducibility | snapshot ID, raw refs, normalization version, correction version |

Không ghép OHLC của nguồn A với volume nguồn B rồi gọi cùng một candle. Nến đang hình thành dùng được để xem chart nếu nhãn rõ; strategy close-based chỉ nhận nến đã đóng. Sau reconnect, phải backfill/reconcile khoảng trống trước khi đánh giá tín hiệu mới.

Tính freshness bằng cả source age và receive age; cần kiểm tra clock skew để timestamp tương lai không vượt qua gate. Khi thị trường đóng cửa, quote cũ có thể là last session hợp lệ để xem, nhưng chưa phải quote đủ điều kiện mở lệnh.

### Chính sách fallback

Historical loader `auto` hiện có fallback riêng; tham khảo [registry](../agent/backtest/loaders/registry.py). Contract mở rộng cần thêm provenance cho nguồn được chọn, lý do nguồn trước thất bại và coverage thực nhận. Không suy rằng fallback thành công nghĩa là dữ liệu tương đương.

Với native broker-bound Forex, mất nguồn phải trả lỗi đúng context. Không đổi tự động sang Yahoo để sizing hoặc đặt lệnh trên tài khoản MT5. Với VN delayed price hoặc nguồn tổng hợp, giữ nhãn delayed/unverified cho đến khi chứng minh được freshness và entitlement.

## 7. SnapshotManifest và BacktestRun

Snapshot là tập record/version được khóa cho một lần tính, không chỉ tên file CSV.

| Thành phần run mục tiêu | Nội dung tối thiểu |
| --- | --- |
| Input identity | Universe tại thời điểm đó, instrument/spec/calendar versions, snapshot manifest hash |
| Dữ liệu | Chosen sources, date coverage, gaps, adjustment policy, extraction/PIT policy |
| Phương pháp | Hypothesis, strategy/artifact ID+version, code hash, params, feature definitions |
| Môi trường | Package versions, engine/version, config, random seed khi có ngẫu nhiên |
| Execution model | Signal timing, fill timing, bid/ask, costs, slippage, borrow/funding/swap, liquidity assumptions |
| Validation | Train/validation/OOS windows, embargo/purge nếu cần, số lần thử, benchmark, failure rules |
| Output | Trades/fills, equity curve, metrics với units và null reasons, warnings, validation evidence |

Tái lập kết quả định lượng bằng inputs cố định và tolerance công bố. Không hứa tái lập nguyên văn LLM từ prompt hash: model/provider có thể đổi và generation có thể không xác định; lưu actual outputs và provider metadata khi có.

Giữ hai trục: performance của strategy và fidelity của simulator. Sharpe cao trên engine sai currency/specs không đủ để nâng validation state. Backtest trên OHLC không tái tạo được thứ tự intrabar khi cả SL và TP bị chạm; phải công bố fill policy và kiểm tra sensitivity hoặc dùng dữ liệu phù hợp hơn.

## 8. Strategy lifecycle: mở rộng trạng thái có sẵn

[Strategy Store models](../agent/src/strategy_store/models.py) có `created`, `benching`, `active`, `monitoring`, `decayed`, `disabled` và trục validation riêng `unvalidated`, `in_validation`, `validated`, `approved`, `rejected`. Không tạo registry thứ hai chỉ để đổi tên các trạng thái này.

Mở rộng đề xuất: thêm immutable version identity, validation scope theo market/product/source/cost model, input/run refs, reviewer evidence, monitoring window và promotion history. Mọi thay đổi rule/parameter trọng yếu cần version mới và đánh giá lại. `active` là lifecycle artifact, không cấp quyền giao dịch.

## 9. ResearchResult và SignalCandidate

Ví dụ sau là **shape minh họa**, không có giá hay metric thị trường và không phải payload API đang chạy:

```yaml
schema_version: proposed-1
research_run_id: example-run
market: FOREX
instrument_id: example-broker-gold
analysis_as_of: null
data_snapshot_id: null
status: INSUFFICIENT_DATA
facts: []
estimates: []
assumptions: []
evidence_ids: []
thesis:
  bullish: []
  bearish: []
  unresolved: [Thiếu quote và symbol specification đã xác minh]
decision:
  action: WAIT
  entry_conditions: []
  invalidation_conditions: []
  actionable: false
validation:
  strategy_id: null
  strategy_version: null
  backtest_run_id: null
  out_of_sample_status: not_run
limitations: [Ví dụ contract, không phải tín hiệu thực tế]
```

`status` mô tả chất lượng/kết quả nghiên cứu; `action` mô tả hướng phân tích. `HOLD` nghĩa là tiếp tục giữ một exposure đã có context, khác `WAIT` chưa mở exposure mới. `SHORT` với cổ phiếu cơ sở không được coi là một order hợp lệ khi market/account không hỗ trợ.

SignalCandidate cần thêm evaluated_at, expires_at, source quote IDs, strategy version, required account context và rejection reasons. Không dùng một cờ `human_approval` boolean làm toàn bộ ủy quyền: authorization phải liên kết actor, phạm vi, tài khoản, thời hạn, policy version và mandate ID.

## 10. Chuẩn lỗi và chất lượng

Các mã dưới đây là **vocabulary đề xuất**, không thay thế error codes đã có của Forex/API:

| Mã | Tình huống | Hành vi mong đợi |
| --- | --- | --- |
| `IDENTITY_AMBIGUOUS` | Chưa rõ venue/product | Yêu cầu giải quyết identity, không tự chọn |
| `SOURCE_UNAVAILABLE` | Nguồn lỗi hoặc thiếu quyền | Giữ nguyên lỗi nguồn, fallback chỉ theo policy |
| `DATA_STALE` / `DATA_GAP` | Quote cũ hoặc thiếu đoạn | Chặn tín hiệu mới, cho xem lịch sử có nhãn |
| `UNIT_UNRESOLVED` | Thiếu scale/currency/contracts | Không tính metric phụ thuộc |
| `EVIDENCE_CONFLICT` | Hai bản tài liệu bất đồng | Lưu cả hai và chờ review |
| `PIT_UNVERIFIED` | Không chứng minh thời điểm công bố | Không dùng cho claim backtest PIT-safe |
| `VALIDATION_REQUIRED` | Strategy chưa đạt đúng scope | Research/backtest; không promotion tự động |
| `AUTHORIZATION_REQUIRED` | Chưa có quyền/tài khoản phù hợp | Không gọi order path |
| `EXECUTION_UNKNOWN` | Timeout chưa rõ broker nhận lệnh | Reconcile trước retry |

API trả được response không có nghĩa toàn run thành công. Nếu ba nguồn chỉ một nguồn thành công, UI phải thể hiện partial coverage và missing-data list; không trộn error thành chuỗi số liệu 0.

## 11. Trust boundaries và riêng tư

Không lưu credentials trong evidence, prompt, report hoặc source URL có token. Secret reference đi qua store/connection hiện có; audit chỉ giữ định danh cần thiết đã che thông tin phù hợp. Tách quyền đọc báo cáo nội bộ của khách hàng với quyền đọc nguồn công khai.

PDF/HTML/RAG có thể chứa prompt injection; parser trả nội dung và locator, không cấp quyền công cụ. Tool registry và authorization phải kiểm tra đối số thực tế độc lập với text của agent. [OWASP LLM Prompt Injection Prevention](https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html)

## 12. Acceptance fixtures tối thiểu cho contract mới

| Fixture đề xuất | Kết quả bắt buộc |
| --- | --- |
| BCTC cùng kỳ có bản sửa năm sau | Backtest cũ giữ revision đã biết, báo cáo mới thấy bản sửa |
| PDF cùng URL đổi nội dung | Hai DocumentVersion, hash và lineage khác nhau |
| Số âm trong ngoặc, đơn vị tỷ VND | Parse đúng dấu/scale, giữ raw cell và locator |
| Ticker trùng ở hai venue | Identity không collision, không fallback chéo |
| Nến bar 0 đang chạy và bar 1 đóng | Close strategy chỉ dùng bar đóng |
| Quote tương lai do clock skew | Không được gắn nhãn fresh tự động |
| Spot và perp cùng base asset | Product/price/funding accounting tách riêng |
| Một báo cáo chỉ đọc abstract/metadata | Không gắn nhãn verified full text |
| Order timeout rồi nhận response muộn | Không gửi trùng; reconcile state |
| Null metric do mẫu quá ít | Giữ null + reason, không đổi thành 0 |

Đây là danh sách test cần bổ sung khi code contract được triển khai; không phải báo cáo các test này đã có hoặc đã pass.
