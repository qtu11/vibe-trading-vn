# Nghiên cứu regime Forex từ nến đóng

Cập nhật **06/11/2026**. Trong **Nghiên cứu thị trường** (`/research`), chọn **Phòng lab Forex**, rồi chọn quy trình **Phát lại regime nhân quả**. Quy trình **Nghiên cứu walk-forward** cũ vẫn là mặc định. Nghiên cứu regime nhận dữ liệu do người dùng cung cấp, tính một mô tả lịch sử và trả bằng chứng có thể đối chiếu; không gọi broker, feed, model hoặc account và không gửi lệnh.

## Dữ liệu và cách sử dụng

Nhập file JSON tối đa 1 MB hoặc dán request vào ô soạn thảo. [Ví dụ](examples/forex-regime.example.json) gồm 96 nến **tổng hợp**, cùng nội dung với [fixture đóng gói trong frontend](../frontend/src/data/research/forex-regime.example.json). Các giá trong ví dụ không phải dữ liệu XAUUSD lịch sử. Danh tính nguồn, revision và thời điểm nến có thể được biết đều chưa được xác minh từ nhà cung cấp.

Nút **Phát lại regime** chỉ gọi `POST /api/forex/regime`, dùng read auth hiện hữu. Không tự chạy khi mở trang, đổi quy trình, nhập file hoặc nạp ví dụ. Đổi input, hủy yêu cầu, đổi quy trình hoặc rời trang sẽ abort HTTP và loại phản hồi cũ khỏi UI; abort không chứng minh CPU phía server đã dừng ngay. Lỗi đọc được hiển thị và không tự retry.

Server kiểm tra toàn bộ dữ liệu theo [hợp đồng nến dùng chung](../agent/src/trading/forex/research_dataset.py):

| Trường | Ràng buộc |
| --- | --- |
| `source`, `dataset_revision` | Chuỗi dài 1–120 ký tự, do caller khai báo |
| `symbol` | Symbol Forex theo hợp đồng hiện hữu |
| `timeframe` | `1m`, `5m`, `15m`, `30m`, `1h`, `4h`, `1d` |
| `price_basis` | Bắt buộc `mid` |
| `bars` | 32–2.000 nến; mỗi nến có `time`, OHLC và `complete: true` |
| Time và OHLC | Time có timezone, chuẩn hóa UTC; nến liên tiếp đúng interval, tăng dần, không trùng; OHLC hữu hạn, dương, đúng thứ tự; nến cuối đã đóng theo đồng hồ server |
| `sma_window`, `atr_period` | Integer nghiêm ngặt 2–200 |
| `slope_bars` | Integer nghiêm ngặt 1–100 |
| `train_end_index` | Integer nghiêm ngặt, inclusive, 1–1.998; phải còn ít nhất một nến evaluation sau nó |
| `entry_quantile` | Số hữu hạn từ 0,5 đến 0,99 |
| `exit_quantile` | Số hữu hạn từ 0,01 đến 0,8; nhỏ hơn `entry_quantile` |
| `min_dwell_bars` | Integer nghiêm ngặt 1–200 |
| `offset`, `limit` | Offset 0–2.000, mặc định 0; limit 1–100, mặc định 50 |

Bool không được chấp nhận thay số. Các tham số integer nghiêm ngặt không nhận chuỗi; OHLC và quantile đi qua bộ kiểm decimal hữu hạn hiện hữu nên có thể nhận biểu diễn số bằng chuỗi. Preview frontend chỉ kiểm object, giới hạn byte và số nến; preview hợp lệ chưa có nghĩa mọi OHLC, thời gian hoặc tham số đã hợp lệ.

## Feature nhân quả và hiệu chỉnh train

[Evaluator](../agent/src/trading/forex/regime.py) dùng SMA trailing, không centered window. Với `L = slope_bars`, feature tại nến đóng `t` là:

```text
normalized_slope[t] = ((SMA[t] - SMA[t-L]) / L) / ATR[t]
```

ATR dùng true range `max(high-low, abs(high-previous_close), abs(low-previous_close))`. Nến đầu dùng `high-low`. [Helper ATR](../agent/src/trading/forex/research_indicators.py) tái dùng Wilder average có seed SMA của [module indicator hiện hữu](../agent/src/shadow_account/indicators.py): lấy trung bình `atr_period` true range đầu, rồi recursion với alpha `1 / atr_period`. Không dùng ADX hoặc mã ví dụ trong skill.

Chỉ các feature hữu hạn, ATR dương, từ index 0 đến `train_end_index` mới được đưa vào hiệu chỉnh. Lấy trị tuyệt đối của chúng, rồi tính linear quantile để có ngưỡng vào và ngưỡng ra. Phải có ít nhất **8 feature train dùng được**, và kết quả phải thỏa `entry_threshold > exit_threshold > 0`.

Thiếu feature trả `incomplete` với `INSUFFICIENT_CALIBRATION_FEATURES`. Ngưỡng suy biến trả `DEGENERATE_CALIBRATION_THRESHOLDS`. Trong cả hai trường hợp, ngưỡng là null và mọi nến evaluation giữ `unknown`; không chuyển thành neutral hoặc tự chọn ngưỡng dự phòng. Các nến train luôn có `regime: unknown`, `reason: training_only`, kể cả khi feature của nến đó đã tính được.

Hai ngưỡng được khóa trước evaluation. Thêm hoặc sửa nến sau train không được thay đổi calibration; thay nến tương lai không được thay feature, trạng thái hoặc hash của quyết định trước nến đó. Hiện chỉ có một initial training prefix, chưa có tái hiệu chỉnh rolling hoặc adaptive regime.

## Trạng thái, hysteresis và thời gian giữ

Evaluation bắt đầu từ nến ngay sau `train_end_index`, ở trạng thái `unknown`. Với feature khả dụng và calibration hợp lệ:

| Trạng thái trước | Điều kiện đề xuất trạng thái mới |
| --- | --- |
| `unknown` hoặc `neutral` | Feature ≥ ngưỡng vào → `uptrend`; feature ≤ âm ngưỡng vào → `downtrend`; còn lại → `neutral` |
| `uptrend` | Feature ≤ âm ngưỡng vào → `downtrend`; nếu chưa đảo chiều nhưng feature ≤ ngưỡng ra → `neutral`; còn lại giữ nguyên |
| `downtrend` | Feature ≥ ngưỡng vào → `uptrend`; nếu chưa đảo chiều nhưng feature ≥ âm ngưỡng ra → `neutral`; còn lại giữ nguyên |

`min_dwell_bars` đếm **số khoảng nến đóng đã trôi qua kể từ lần chuyển trạng thái**, không đếm số lần API được gọi. Nếu chưa đủ dwell, đề xuất chuyển bị giữ lại với `minimum_dwell_hold`. Sau khi đủ dwell, có thể chuyển trực tiếp từ uptrend sang downtrend hoặc ngược lại; không bắt buộc đi qua neutral. Không chuyển thì có `hysteresis_hold`.

Warmup hoặc ATR không dương đưa trạng thái về `unknown` ngay, bất kể dwell. Mỗi nến có `reason`, `transition`, `dwell_remaining` để giải thích kết quả. `neutral` chỉ mô tả việc chưa vượt ngưỡng theo heuristic này; chưa xác nhận thị trường sideway bằng cấu trúc đỉnh đáy, thanh khoản hoặc phương pháp độc lập.

## Availability, hash và trang kết quả

`time` là thời điểm mở nến caller cung cấp. `available_at` được suy ra bằng `time + timeframe`, nghĩa là **giả định có thể biết sau lúc đóng nến**. Đây không phải timestamp ingest đã kiểm chứng; chưa có mô hình độ trễ hoặc revision dữ liệu thực. Kết quả ghi rõ `caller_supplied_unverified` và methodology availability.

Calibration giữ thời điểm train cuối và quyết định evaluation đầu, số feature, ngưỡng, `fit_input_hash` và `threshold_hash`. Kết quả còn có `config_hash`, `dataset_hash`, source hashes của producer, prefix hash từng nến và chuỗi `state_hash`. Hash giúp phát hiện thay đổi đầu vào hoặc logic, không xác minh tính đúng của nguồn dữ liệu. Hash nến train không chứa ngưỡng được fit từ các nến train xuất hiện sau nó.

Server replay toàn bộ lịch sử được cung cấp rồi mới cắt trang timeline. `summary` luôn tổng hợp toàn bộ evaluation; `latest` luôn là trạng thái nến cuối, dù trang timeline đang xem là các nến đầu. Đổi `offset` hoặc `limit` không đổi calibration, summary, latest, config/dataset hashes hoặc nội dung của cùng một nến. UI giữ nguyên request và chỉ thay offset khi chuyển trang.

**Xuất JSON đầu vào và trang kết quả này** tạo file cục bộ `forex-regime-replay.json` với `schema_version: 1` và `export_scope: request_and_one_returned_timeline_page`. File chứa toàn bộ request và **đúng trang timeline đã nhận** cùng summary/latest/calibration của response đó. Không tự fetch trang còn lại, không tuyên bố đây là toàn timeline và không lưu vào registry. Để dựng toàn timeline, caller cần lấy đủ các trang với cùng request và kiểm hash.

## API, MCP và giới hạn triển khai

`POST /api/forex/regime` và tool dedicated Forex MCP `forex_regime` đều chỉ tính dữ liệu đã cung cấp. MCP tool có `readOnlyHint: true`, `openWorldHint: false`; không có tool ghi regime hoặc kích hoạt strategy. Dedicated server vẫn chọn một connection đã cấu hình khi khởi động, nhưng evaluator này không gọi adapter hoặc account.

Với OANDA/Exness, dedicated Forex MCP hiện có **14 tool read-only**, hoặc **17 tool** khi bật execution và connection cho phép. `--allow-research-writes` bổ sung **3 tool** nghiên cứu hiện hữu, thành 17 hoặc 20; không thêm writer regime. Connection MT5 bổ sung **2 tool** research context/plan hiện hữu, thành 16 hoặc 19 trước research writes, 19 hoặc 22 khi bật research writes. Tool plan MT5 có thể gọi model được cấu hình; các con số này không thuộc main MCP.

Phần này triển khai một phần `FX-147` và `PLATFORM-016`. Chưa có ADX, swing confirmation, đồng thuận đa timeframe, news/fundamental inputs, tín hiệu mua bán, PnL, dự báo regime tương lai hoặc execution. Không chuyển trạng thái thành xác suất có lãi hay khuyến nghị đặt lệnh. Chưa xác minh độ phù hợp thống kê của heuristic hoặc độ nhạy trên dữ liệu broker thực; acceptance còn mở.

Việc tách dataset chung giữ hợp đồng và output walk-forward hiện hữu; source manifest mới nhận diện module được tách. Không đổi Forex DB schema 4 và không di trú hay sửa run cũ. Rollback code cần giữ database/ledger hiện hữu theo quy trình [Forex lab](FOREX_RESEARCH_LAB.md); file JSON xuất là dữ liệu local do người dùng tự quản lý, không có side effect broker để rollback.

## Kiểm chứng

[Backend tests](../agent/tests/test_forex_regime.py) kiểm ATR seed và gap, train-only quantile, availability, prefix invariance, future mutation, state hash, hysteresis/dwell, unknown/null/flat, strict validation, paging, fixture frontend đồng nhất và actual HTTP/MCP không gọi broker/store. [UI tests](../frontend/src/components/forex/__tests__/ForexRegimeLab.test.tsx) kiểm tính toán chủ động, negative/zero/null, insufficient calibration, bounded import, file/read race, cancel/unmount, paging và file xuất đúng trang. [Market research tests](../frontend/src/pages/__tests__/MarketResearch.test.tsx) kiểm quy trình mặc định và chuyển quy trình loại phản hồi muộn. Đây là kiểm chứng local; chưa có browser screenshot hoặc nghiệm thu visual.
