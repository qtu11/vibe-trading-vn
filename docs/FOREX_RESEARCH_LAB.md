# Phòng lab Forex, EMA, chi phí và đường vốn OOS

Cập nhật **06/11/2026**. Trong menu **Nghiên cứu thị trường** (`/research`), chọn **Phòng lab Forex**. Luồng này không cần kết nối broker; dùng request nến đóng có nguồn do caller khai báo và evaluator train-only hiện có.

## Từ request đến kết quả

Chọn phương pháp **Walk-forward**, **Kiểm thử chi phí** hoặc **Bootstrap đường vốn OOS** rồi nhập file JSON tối đa 1 MB hoặc dán request vào editor. Nút **Nạp ví dụ tổng hợp** chỉ tạo 96 nến sin giả lập đã gắn `synthetic_web_example_not_market_data`; đây không phải giá XAUUSD lịch sử. Ví dụ chi phí bọc các nến vào `research` và khai báo đủ bốn thành phần phí; ví dụ đường vốn thêm seed, số lần mô phỏng và độ dài block. [Fixture SMA](examples/forex-walk-forward.example.json), [fixture EMA](examples/forex-ema-walk-forward.example.json), [fixture chi phí](examples/forex-cost-stress.example.json) và [fixture đường vốn](examples/forex-trade-paths.example.json) cũng là dữ liệu tổng hợp. Preview chỉ kiểm hình dạng có giới hạn và nhắc revision/cost; server vẫn kiểm toàn bộ OHLC, time, completeness, chronology và tham số.

**Tính nghiên cứu** gọi `/api/forex/walk-forward`, `/api/forex/cost-stress` hoặc `/api/forex/trade-paths` theo phương pháp đã chọn, không tự lưu. Output walk-forward giữ mọi trial/fold kể cả lỗi, train outcome availability, OOS window, frozen parameters, OOS net return theo **tỷ lệ**, hash và execution assumptions. Có fold lỗi thì aggregate OOS là null, không hiển thị 0 như đã tính thành công. Đổi input hoặc phương pháp sẽ hủy/loại kết quả tính toán cũ; cancellation của HTTP đọc không chứng minh server CPU đã dừng ngay.

**Lưu một lần nghiên cứu** chạy lại evaluator bằng đúng request đã tính và append toàn bộ request/engine/result vào registry. Có thể tạo experiment mới hoặc append vào ID được chọn. Không tự kích hoạt strategy; không tự retry thao tác ghi. Nếu transport timeout, commit có thể đã xảy ra: đọc lịch sử trước khi gửi lại. Luồng API write dùng settings-write auth như registry hiện hữu.

**Đọc / tải lại lịch sử** chỉ đọc khi bấm; danh sách experiment và attempt có paging 10. Mở từng run để xem dữ liệu/engine hashes/trials đầy đủ. `running` với `result: {}` vẫn là completion unknown; không dựng evaluation trống như kết quả hoàn tất. **Nạp đầu vào này vào ô soạn thảo** khôi phục cả phương pháp của request đã lưu, không tự tính/lưu. Phản hồi GET cũ không được ghi đè receipt vừa save.

## SMA và EMA là hai variant riêng

`WalkForwardRequest.strategy` nhận `sma_crossover` mặc định hoặc `ema_crossover`; cùng bộ `candidates: [{fast, slow}, ...]`. Bỏ field giữ nguyên output/config/hash SMA baseline. EMA có variant `ema_crossover_next_open_one_bar_v1` và `indicator_methodology` riêng; request được lưu chứa strategy chuẩn hóa.

EMA dùng `alpha = 2/(window+1)`, seed từ close đầu tiên trong dataset được cung cấp; chỉ có signal sau `slow+1` closes. State đi qua các fold, không reset tại ranh giới OOS. Crossover tại close t chỉ dùng prefix tới t; outcome dùng next open/close. Chọn fast/slow tối đa hóa net return **train** theo tie-break cố định; OOS không được dùng để refit cho chính fold đó. Source SHA của helper EMA được lưu trong engine manifest.

Đây vẫn là nghiên cứu giữ một nến, unlevered notional và round-trip bps cố định do caller giả định. Chưa mô phỏng bid/ask ticks, spread biến thiên, broker fills, swap, SL/TP, latency hoặc production-runner parity. Không chuyển kết quả OOS thành forecast/authorization live. Chưa có total tuning-budget, promotion gate hoặc kiểm soát tái dùng OOS xuyên các lần người dùng thử.

## Kiểm thử chi phí trên tín hiệu OOS đã khóa

[Evaluator chi phí](../agent/src/trading/forex/cost_stress.py) nhận `CostStressRequest`: `research` là `WalkForwardRequest` SMA hoặc EMA hiện hữu, cùng `spread_bps`, `commission_bps`, `slippage_bps`, `gap_bps`. Cả bốn field phải được khai báo, kể cả khi bằng 0; mỗi field là số hữu hạn không âm, tối đa 1.000 bps. Tổng bốn field phải khớp `research.round_trip_cost_bps` qua `math.isclose(rel_tol=1e-12, abs_tol=1e-12)`; tổng base vẫn chịu giới hạn 0–1.000 bps của walk-forward. Bars bắt buộc `price_basis: "mid"`, nên các phí được trừ một lần trên mỗi trade; không nhận bars bid/ask để cộng spread lần nữa.

Evaluator gọi walk-forward **một lần tại chi phí base**. Việc chọn tham số vẫn dùng nhãn train trước OOS của từng fold; sau đó khóa lựa chọn và chuỗi crossover/outcome OOS. Ba scenario cố định nhân **spread** lần lượt 1, 2, 3; commission, slippage và gap giữ nguyên. Khi spread bằng 0, cả ba mức tổng phí bằng nhau. Không refit theo scenario, không chọn scenario thắng để thay tham số và không dùng OOS để tối ưu phí. `frozen_oos_tape_hash` chung nhận diện dataset, fold, lựa chọn và gross outcome đã khóa; `config_hash` còn nhận diện cấu hình base và split phí.

Ví dụ base 2 bps được tách spread 1, commission 0,5, slippage 0,25 và gap 0,25 bps thì tổng phí ba scenario là **2 / 3 / 4 bps**. Các số này là giả định tổng hợp, không phải biểu phí broker. `gap_bps` chỉ là khoản trừ bất lợi cố định trên mỗi trade, chưa replay một bước nhảy giá hoặc thứ tự intrabar.

Mỗi scenario giữ trạng thái, metrics từng fold và OOS aggregate. Gross/net expectancy là **trung bình số học trên mỗi trade** theo bps; compounded `net_return` vẫn là tỷ lệ. `arithmetic_break_even_all_in_cost_bps` bằng gross expectancy; `arithmetic_break_even_spread_bps` trừ tiếp commission/slippage/gap cố định. Break-even spread âm được giữ nguyên: không có spread không âm đáp ứng ngưỡng số học đó. Đây không phải nghiệm hòa vốn của compounded equity, xác suất có lãi hoặc khẳng định broker sẽ khớp lệnh với mức phí ấy.

Không có OOS trade thì expectancy/break-even là null với `NO_OOS_TRADES`; net return 0 chỉ thể hiện không phát sinh trade. Nếu base thiếu fold hợp lệ, các scenario là `incomplete` và toàn bộ OOS aggregate là null; không bỏ fold lỗi để cộng phần còn lại. Nếu đầy đủ tape nhưng tăng phí làm một trade mất hết equity hoặc gây overflow, scenario là `incomplete`, compounded return là null; bằng chứng expectancy/break-even số học vẫn được giữ, kể cả âm.

Lưu cost stress chạy lại cùng evaluator và append request lồng nhau, mọi base trial, ba scenario, tape/config hashes và engine manifest vào registry schema 4 hiện hữu. Manifest có `experiment_kind: "frozen_oos_cost_stress"` và source SHA của module chi phí cùng các module walk-forward/indicator/accounting liên quan. Run cũ không bị thay thế; thất bại được lưu theo cơ chế registry hiện hữu. Có thể đọc mọi run bằng các route lịch sử chung, dù experiment chứa các loại attempt khác nhau.

## Bootstrap đường vốn từ các trade OOS đã khóa

[Evaluator đường vốn](../agent/src/trading/forex/trade_paths.py) bổ sung phần triển khai **`FX-162` partial**. Moving-block bootstrap lấy lại các block quan sát liên tiếp, có chồng lấn, bằng phép chọn có hoàn lại. Khác với lấy từng observation độc lập, cách này giữ được thứ tự ở bên trong mỗi block. Độ dài block và sự không ổn định của chuỗi vẫn ảnh hưởng đến diễn giải kết quả; phương pháp này không tự chứng minh độ tin cậy dự báo. Xem phần 3 và thảo luận giới hạn trong [Berkowitz & Kilian, Federal Reserve, 1996](https://www.federalreserve.gov/pubs/feds/1996/199645/199645pap.pdf).

Request chứa `research: WalkForwardRequest`, `seed` là integer 0–4.294.967.295, `simulations` là integer 100–2.000 và `block_length` là integer 2–64; không nhận bool hoặc chuỗi thay số. Đây là cùng request SMA/EMA, nến mid đã đóng, cost và chronology đã dùng ở hai phương pháp trước. Không đọc broker, model, account hoặc feed. Server fit walk-forward một lần ở base cost; tham số, crossover và gross OOS outcome được khóa trước khi mô phỏng. Cost cố định được trừ đúng một lần để tạo net trade return, không trừ lại khi resample.

Policy hiện hữu của evaluator đường vốn lấy mẫu **riêng trong từng fold**. Với `n` trade và block dài `l`, có `n-l+1` điểm bắt đầu, không nối vòng cuối–đầu. Mỗi lần mô phỏng chọn đều các điểm bắt đầu bằng RNG có seed, ghép các block rồi cắt block cuối để giữ nguyên `n` trade của fold. Các fold giữ thứ tự và số trade gốc; block không đi xuyên ranh giới refit. Khi nối lại các fold, đây vẫn là giả định lấy mẫu độc lập giữa các fold; không giữ toàn bộ phụ thuộc của thị trường. Đơn vị là **thứ tự trade**, không phải giờ/ngày, nên không mô phỏng thời gian không có vị thế.

Các fold không có trade được giữ là fold rỗng đã biết và không sinh block giả. Fold có trade nhưng ít hơn `block_length` làm toàn study `incomplete` với `INSUFFICIENT_FOLD_TRADES`; không tự hạ độ dài block hoặc loại fold. Base walk-forward lỗi cũng giữ nguyên trials và không sinh aggregate mô phỏng. Toàn bộ OOS không có trade trả `NO_OOS_TRADES`; không dựng các đường vốn phẳng như đã đủ bằng chứng. `possible_block_starts` được báo theo fold: nếu chỉ có một điểm bắt đầu, các mẫu có thể trùng nhau; dải hẹp không chứng minh chiến lược ổn định.

Mỗi đường vốn bắt đầu bằng 1 và compound các net return chưa leverage. `max_drawdown` là tỷ lệ lỗ dương so với running peak, bao gồm equity ban đầu, dùng primitive `quantlib.risk.drawdown_series`. Kiểm finite/positive xảy ra trước primitive để không bị bỏ qua observation không hợp lệ. Underflow, overflow hoặc trade mất hết equity là lỗi rõ ràng. Nếu bất kỳ simulation lỗi, output giữ số lượt hợp lệ/lỗi và tối đa 20 ví dụ lỗi, nhưng toàn bộ phân vị và biểu đồ mô phỏng là null; không lọc đường vốn xấu rồi báo phân vị trên phần sống sót.

Output có `actual_path` quan sát, `simulation_summary` với phân vị p05/p25/p50/p75/p95 của terminal net return và max drawdown. Đây là **phân vị thực nghiệm**, không phải confidence interval được hiệu chỉnh, p-value hoặc xác suất lợi nhuận tương lai. Không có Sharpe hay annualization cho chuỗi trade-index. Biểu đồ trong UI giữ tối đa 20 đường vốn mẫu và 100 bước hiển thị, có đường quan sát cùng median và dải p05–p95; thống kê dùng toàn bộ simulation. Phiên bản phương pháp, seed/block/n, source hashes, config hash và frozen tape hash được giữ để đối chiếu. RNG đi theo thứ tự simulation trước, fold sau; engine manifest giữ phiên bản NumPy để giới hạn ý nghĩa tái lập giữa môi trường.

Khi **Lưu một lần nghiên cứu**, toàn bộ nested request, base trials, fold evidence, sampling assumptions và result được append như các nghiên cứu trước. Manifest có `experiment_kind: "frozen_oos_moving_block_bootstrap"`, source SHA của evaluator và shared drawdown primitive. Không thay schema, kích hoạt strategy hay gửi lệnh. Phần này chưa mô hình hóa ký quỹ, stop-out, execution, đổi spread, swap, SL/TP hoặc bất định do tuning lại OOS qua nhiều lần người dùng thử.

## API và dedicated Forex MCP

| Thao tác | Route | Quyền |
| --- | --- | --- |
| Tính walk-forward | `POST /api/forex/walk-forward` | Read auth; không ghi registry |
| Tính cost stress | `POST /api/forex/cost-stress` | Read auth; không ghi registry |
| Tính đường vốn OOS | `POST /api/forex/trade-paths` | Read auth; không ghi registry |
| Lưu walk-forward mới / append | `POST /api/forex/experiments` / `POST /api/forex/experiments/{experiment_id}/runs` | Settings-write auth |
| Lưu cost stress mới / append | `POST /api/forex/cost-stress/experiments` / `POST /api/forex/cost-stress/experiments/{experiment_id}/runs` | Settings-write auth |
| Lưu đường vốn mới / append | `POST /api/forex/trade-paths/experiments` / `POST /api/forex/trade-paths/experiments/{experiment_id}/runs` | Settings-write auth |
| Đọc lịch sử / run | `GET /api/forex/experiments`, `GET /api/forex/experiments/{experiment_id}`, `GET /api/forex/experiments/{experiment_id}/runs/{run_id}` | Read auth |

Dedicated Forex MCP có `forex_walk_forward`, `forex_cost_stress` và `forex_trade_paths` là local read-only, `openWorldHint: false`. `forex_run_experiment`, `forex_run_cost_stress_experiment` và `forex_run_trade_paths_experiment` chỉ được đăng ký khi bật riêng `--allow-research-writes`; cả ba ghi evidence cục bộ, không gửi lệnh. Việc bật quyền nghiên cứu không tự bật `--allow-execution`. MCP process vẫn chọn một connection đã cấu hình khi khởi động; riêng ba evaluator supplied-data không gọi adapter, đọc account hay truy cập broker.

Với OANDA/Exness, schema mặc định có **13 tool read-only**; bật execution có **16 tool** (chỉ khi connection cho phép execution). Quyền ghi nghiên cứu bổ sung **3 tool** vào từng cấu hình đó: 16 hoặc 19. Connection MT5 bổ sung thêm **2 tool** research context/plan hiện hữu: 15 hoặc 18 khi chưa bật research writes; 18 hoặc 21 khi bật. Tool plan MT5 có thể gọi model được cấu hình và phát sinh phí; danh nghĩa read-only chỉ mô tả không gửi lệnh. Các con số này thuộc dedicated Forex server, không phải main MCP.

## Kiểm chứng và dữ liệu

[Test EMA](../agent/tests/test_forex_ema_research.py) kiểm seed/warmup/prefix invariance, OOS isolation, HTTP/MCP và temp registry; SMA baseline trước sửa được đối chiếu toàn output. [Test cost stress](../agent/tests/test_forex_cost_stress.py) kiểm một lần fit base, cùng tape giữa scenario, phí chỉ trừ một lần, spread không giảm, negative/null/bankruptcy, registry bất biến và actual in-memory MCP/HTTP bằng fixture không gọi broker. [Test đường vốn](../agent/tests/test_forex_trade_paths.py) kiểm block liên tiếp không vòng, per-fold sampling, seed, một lần fit, failures không bị bỏ, display bounds, shared drawdown parity và fixture/registry/HTTP/MCP thực thi cục bộ. [UI tests](../frontend/src/components/forex/__tests__/ForexResearchLab.test.tsx) cùng [helper/API tests](../frontend/src/lib/__tests__/forexResearch.test.ts) kiểm import, chọn phương pháp, late responses, load request đã lưu, save riêng, negative/null và uncertainty; chưa browser screenshot/visual acceptance.

Registry vẫn schema 4 của [đợt 4](IMPLEMENTATION_STATUS_2026-11-05_04.md#dữ-liệu-và-rollback); đợt 5–7 không đổi Forex DB schema. Các nến được lưu trong database hiện hữu; backup/downgrade phải giữ nhất quán ledger và reconcile execution phát sinh. Đừng xóa runs hoặc sửa user_version để downgrade. Mapping partial `FX-154`, `FX-160`, `FX-161`, `FX-162`, `FX-163` và `PLATFORM-062` trong [tracker](IMPLEMENTATION_TRACKER.md). Acceptance `FX-163` vẫn mở do chưa có broker-calibrated sweep, bid/ask ticks, phí động và price-gap replay; `FX-162` vẫn mở do chưa xác minh nguồn/broker terms, dependent-sampling adequacy hay execution/margin tails. Fixture/local tests không chứng minh execution thật.
