# Triển khai P0: dữ liệu Việt Nam, funding Crypto và Forex preflight

**Ngày:** 05/11/2026, Asia/Saigon. **Base version:** `0.1.18` với thay đổi local, chưa phát hành package. Đây là đợt code đầu theo yêu cầu sau khi nghiên cứu master; không phải triển khai xong 265 đặc tả.

## 1. Phạm vi đã code

| Slice | Hành vi trước | Hành vi sau và điểm tích hợp |
| --- | --- | --- |
| Local VN reference | Loader bỏ cột giá tham chiếu dù dataset có cung cấp | [local_loader.py](../agent/backtest/loaders/local_loader.py) giữ `pre_close`/column mapping, normalize, cache và resample; HOSE engine nhận reference qua đường loader hiện tại |
| Price basis | Không có declaration rõ cho bộ local VN; giá điều chỉnh có thể nhìn giống execution price | Data Bridge nhận `adjustment` hợp lệ; không khai báo giữ default theo market hiện có. VN chưa khai báo raw có cảnh báo fidelity, không tự chứng nhận giá |
| Run-card warning | Market engine sao chép config làm warning runtime có thể không đến file report | [base.py](../agent/backtest/engines/base.py) gộp/loại trùng caliber warnings từ config đầu vào và runtime engine; dùng `run_card.json` hiện có |
| Funding completeness | Intersection funding/bar timestamps có thể làm mất settlement nằm trong coarse bar | [ccxt_loader.py](../agent/backtest/loaders/ccxt_loader.py) từ chối events không nằm đúng bar-open grid; hướng dẫn interval nhỏ hơn thay bỏ sự kiện hoặc cộng rate sai |
| Funding minute grid/cache | Required funding mask dùng hour nên có thể đòi settlement ở từng phút; cache cũ còn dữ liệu thiếu | Chỉ required tại đúng giờ settlement chuẩn; cho observed events bổ sung khi aligned; source revision riêng cho perpetual invalidates cache cũ, spot cache giữ nguyên semantics |
| Forex assessment quote | Quote shape/time/number sai có thể ném lỗi Python không theo contract preflight | [risk.py](../agent/src/trading/forex/risk.py) trả `INVALID_QUOTE` hoặc `QUOTE_TIME_UNKNOWN`, chặn trước send và giữ lỗi trong luồng service/API hiện có |

Các đường gọi được tái sử dụng: `fetch_data_map` → loader → engine/composite → run card; `ForexService.preview/submit` → policy/risk → native adapter. Không tạo registry, engine hoặc service song song, không thêm dependency.

## 2. Cách khai báo local VN data

Trong cấu hình Data Bridge mà người dùng đang dùng, một nguồn có thể khai báo:

```yaml
sources:
  - symbol: VIC.VN
    type: csv
    path: D:/research/authorized-hose-bars.csv
    adjustment: raw
    columns:
      date: Date
      pre_close: Reference
```

File cần OHLCV theo mapping hiện có; `Reference` là cột nguồn chứa reference cho chính bar đó. Ví dụ là cấu hình mẫu, không phải file dữ liệu đã có hoặc giá thị trường thật. `adjustment` chấp nhận `raw`, `split`, `split_dividend`, `split_dividend_additive`, `unknown`; omitted không ghi đè default của các market khác. `raw` là declaration do nguồn cung cấp, không xác minh license hoặc corporate actions.

Khi downsample, reference lấy hàng mở đầu kể cả khi thiếu; không lấy giá reference xuất hiện sau đó để lấp đầu bar. Cache key gồm declaration và normalization revision. Reference không dương/không hữu hạn được coi là thiếu. Engine vẫn giữ previous-close fallback và hành vi mô phỏng cũ nếu không có reference; warning/run card thể hiện giới hạn đó, không gọi mọi run là HOSE-fidelity verified.

## 3. Những gì funding guard bảo đảm

MarketRiskFrame hiện biểu diễn một settlement ở bar open; engine xử lý theo vị thế và mark tại frame đó. Gộp ba rates thành một rate trên daily bar không đúng nếu position/notional/mark thay đổi giữa các events. Vì vậy thay đổi hiện tại **reject grids không biểu diễn đủ events đã nhận**, thay vì dựng một intrabar simulator giả.

Standard eight-hour required-slot check vẫn được giữ để tương thích; nó chỉ chạy ở timestamp đầu giờ đúng00/08/16 UTC. Events ngoài lịch đó được giữ nếu nằm trên grid. Điều này không chứng minh arbitrary-cadence completeness khi vendor thiếu event, historical mark-at-settlement parity, durable funding journal hoặc inverse accounting. Các khả năng đó còn nằm trong [Crypto catalog](specs/CRYPTO_72.md).

## 4. Phạm vi của Forex fix

Validation áp dụng với `assessment.quote` đi tới risk gate: object, timestamp có timezone/UTC-convertible, bid/ask/point hữu hạn và dương. Naive/malformed/extreme timestamp không biến thành lỗi parser ngoài contract. Crossed quote, stale/future quote, tradeable, spread và các risk caps hiện hữu tiếp tục được kiểm tra.

OANDA/Exness có phép tính trong `prepare()` trước gate; đợt này không chuẩn hóa mọi lỗi raw provider ở các phép tính đó. Không thay quyền execution, không tăng limit, không giải quyết toàn bộ race giữa kiểm halt và broker send, không thay close ownership hoặc tự flatten exposure.

## 5. Tests và regression

Tests mới dùng fake SDK/broker hoặc local data, không truy cập tài khoản thật:

- [Local/Vietnam reference](../agent/tests/test_local_vietnam_reference.py): mapping, finite reference, missing opening value, calendar gaps, cache identity, caliber defaults, composite và backtest/run-card thật.
- [CCXT perpetual contract](../agent/tests/test_ccxt_perpetual_loader.py): funding events trên1H/4H, coarse/off-grid rejection, minute boundary và cache cũ.
- [Forex preflight](../agent/tests/test_forex_execution.py): malformed object/time/numeric values, UTC overflow, không broker send và intent giữ trạng thái trước gửi.

Kết quả regression cuối và lệnh chạy được ghi trong [biên bản kiểm tra](DOCUMENTATION_VERIFICATION.md). Các lượt trước khi code có 245 passed và229 passed/1 skipped chỉ là baseline nghiên cứu, không cộng lại thành số test riêng của release này.

Regression tích hợp: **728 passed, 3 skipped**. Nhóm local/cache/run-card chạy lại sau thay đổi tương thích cuối: **138 passed, 3 skipped**; không cộng hai nhóm vì có test trùng. Ba skip liên quan optional Parquet reader chưa có trong môi trường. Đây không phải full repository suite hoặc xác nhận broker thật.

## 6. Backup, rollout và rollback

Source gốc trước sửa nằm tại `.codex-backups/2026-11-05-implementation/`, giữ đường dẫn tương ứng. Không sửa credentials, file cấu hình tài khoản, package version, live mandate hoặc halt flags.

Deploy local code cùng test/contract updates; lỗi funding mới có thể làm backtest coarse trước đây chạy được nay bị từ chối. Đó là hành vi có chủ đích để ngăn silent data loss; chọn interval biểu diễn được settlement hoặc chưa dùng strict historical funding cho grid đó. Schema/cache revisions làm entries cũ không được dùng cho logic mới; không cần xóa cả cache hoặc runtime data.

Rollback theo đúng snapshot file và dependency/caller tương ứng, giữ datasets, run cards và audit/journal. Không downgrade cache validation để làm mất warning hoặc làm một backtest sai trở lại chạy xanh. Những source đã có declaration mới cần được review khi quay reader cũ.

## 7. Chưa triển khai

SSI OAuth/data adapter, pipeline BCTC VN đầy đủ, HNX/UPCoM rules, historical tick recorder/replay, complete spot/inverse/perpetual accounting, end-to-end RAG/tenant platform và live trading gates toàn chương trình vẫn chưa được triển khai bởi đợt này. Các quyết định nguồn/license/tài khoản/production trong master vẫn phải xử lý đúng phạm vi trước rollout tương ứng.
