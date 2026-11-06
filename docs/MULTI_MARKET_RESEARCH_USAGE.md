# Chạy các luồng nghiên cứu đã triển khai

Cập nhật **06/11/2026**, checkout hiện tại `D:/Vibe-Trading`, gồm đợt8. Các ví dụ JSON tài chính và nến là **dữ liệu tổng hợp**, không phải kết quả kinh doanh, dự báo hoặc giá XAUUSD thật. Ví dụ nền được kiểm bởi [test_research_examples.py](../agent/tests/test_research_examples.py); các guide phương pháp/fixture tiếp theo có [VN comparables](VN_COMPARABLES.md), [Forex EMA/lab](FOREX_RESEARCH_LAB.md) và [regime replay](FOREX_REGIME_RESEARCH.md). Các PDF mẫu người dùng cung cấp được phân tích riêng trong [đối chiếu FPT](REPORT_SAMPLE_FINDINGS.md), không được gọi là synthetic fixtures hoặc nguồn đã xác minh độc lập.

## 1. Nghiên cứu BCTC Việt Nam

Sao chép [company fixture](examples/vn-company-research.example.json) vào thư mục dữ liệu thử, rồi thêm vào Data Bridge `~/.vibe-trading/data-bridge/config.yaml`, giữ các cấu hình cũ:

```yaml
financial_statements:
  - symbol: CASE.VN
    path: D:/research/vn-company-research.example.json
```

`CASE.VN` là mã giả lập. Thay bằng bộ dữ liệu được phép sử dụng cho doanh nghiệp thật khi nghiên cứu thực tế. Reader và quy tắc timestamp/revision vẫn theo [hợp đồng local](LOCAL_VN_FINANCIAL_STATEMENTS.md).

Tool registry và main MCP có tool `vietnam_research`:

```json
{"code":"CASE.VN","as_of":"2025-08-01T00:00:00Z","period":"quarter","consolidation":"consolidated","offset":0}
```

Trong Python, chạy từ `agent/` với môi trường dự án:

```python
from src.tools.vietnam_research_tool import VietnamResearchTool
print(VietnamResearchTool().execute(
    code="CASE.VN", as_of="2025-08-01T00:00:00Z",
    period="quarter", consolidation="consolidated",
))
```

Fixture Q1 doanh thu 200 triệu và 6T doanh thu 470 triệu cho quý 2 **270 triệu VND**. CFO 6T140−Q1 60=80 triệu, capex25−10=15 triệu, FCF quý2=**65 triệu VND**. Balance sheet là số dư tại ngày, không trừ lũy kế hoặc cộng bốn quý. Các phép tính trả chuỗi decimal, mỗi input có nguồn trong `evidence`; số tiền dùng precision320 để giữ residual trong miền đầu vào được hỗ trợ, tỷ số/ngày dùng precision28.

Canonical facts:

| Báo cáo | Tên fact được nhận bởi lớp phân tích |
| --- | --- |
| Income | `revenue`, `gross_profit`, `net_income`, `cogs` |
| Cashflow | `cfo`, `capex` |
| Balance | `total_assets`, `total_liabilities`, `total_equity`, `current_assets`, `current_liabilities`, `accounts_receivable`, `inventories`, `accounts_payable` |

Facts dùng đơn vị `VND` và `scale` khai báo ở từng fact. `cogs` và `capex` là độ lớn dương của chi phí/chi đầu tư; dấu âm không được tự đảo. Fact sai đơn vị hoặc thiếu giữ `null` cùng reason. Reader thô vẫn giữ các fact khác; tool nghiên cứu không đoán alias hoặc taxonomy ngành.

Quarter mode nhận các kỳ lịch đủ tháng: quý3 tháng, lũy kế6/9 tháng và năm12 tháng. Với lũy kế, phải có kỳ liền trước cùng đầu năm, scope, statement và nhãn revision tương thích; nếu không thì giữ unknown và trích cả nguồn gây xung đột. Annual standalone12 tháng có thể làm tổng năm để suy quý4 nếu có 9T phù hợp. Fiscal stub/geometry chưa hỗ trợ trả lỗi rõ; không giả định lịch năm tài chính hoặc suy EPS từ lũy kế. Một statement/end có nhiều basis cạnh tranh phải được curate trước, không tự chọn số đẹp hơn.

Report có kiểm `A−L−E` chính xác, net/gross margin, cash conversion, FCF, liabilities/assets, current ratio, ROA/ROE, accruals, DSO/DIO/DPO và cash conversion cycle. Các chỉ tiêu cần average balances chỉ chạy khi có số dư đầu kỳ và cuối kỳ; số ngày theo kỳ thực, không annualize. Mẫu số không dương giữ undefined theo phương pháp đã chọn. Phương pháp dành cho doanh nghiệp phi tài chính; **không tự phân loại doanh nghiệp**, không áp bộ tỷ số này cho ngân hàng/bảo hiểm.

Đọc `paging.next_offset` và truyền lại cutoff trả về để lấy tiếp kỳ; giữ file không đổi giữa các trang. `source_file_sha256` xác định file hiện tại, không phải chứng nhận dữ liệu hoặc immutable historical archive. Không có target price hay khuyến nghị giao dịch được sinh từ tool này.

## 2. DCF qua JSON và main MCP

Module DCF/WACC hiện có được gọi bằng `quantlib_call`, không tạo engine thứ hai. [Fixture DCF](examples/dcf-scenario.example.json) là bộ arguments hoàn chỉnh có hai năm forecast **giả định**. Chạy từ `agent/`:

```python
import json
from pathlib import Path
from src.tools.quantlib_tool import QuantlibCallTool

request = json.loads(Path("../docs/examples/dcf-scenario.example.json").read_text(encoding="utf-8"))
print(QuantlibCallTool().execute(**request))
```

Qua MCP gọi `quantlib_call` với nguyên object của file. Terminal growth/exit multiple dùng envelope cố định:

```json
{"__assumption__":{"name":"terminal_growth","value":0.02,"basis":"Lý do lựa chọn giả định","source":"Nguồn hoặc người lập giả định"}}
```

Bridge chỉ tạo kiểu `Assumption` đã cho phép, không nhận tên class/module tùy ý. Toàn bộ monetary inputs phải cùng currency/scale; shares là số cổ phiếu. Caller phải giữ evidence và lý do cho forecasts/capital structure/discounting/terminal method; engine không cung cấp các đầu vào đó. Thiếu input làm model không chạy, không dùng default để tạo giá. Preset `fundamental_research_team` đã được nối tới các tool này; kiểm thử preset là kiểm tra cấu hình, chưa phải một run AI/model thật.

## 3. Walk-forward Forex qua API và Forex MCP

`POST /api/forex/walk-forward` và tool riêng `forex_walk_forward(payload=...)` dùng cùng request schema. Xem [96 nến tổng hợp](examples/forex-walk-forward.example.json); payload gồm:

```json
{
  "source":"synthetic_fixture", "symbol":"XAUUSD", "timeframe":"1h",
  "price_basis":"mid", "dataset_revision":"fictional-96-bars-v1",
  "bars":["dùng các OHLC objects từ file mẫu"],
  "candidates":[{"fast":2,"slow":4},{"fast":3,"slow":5}],
  "n_blocks":4, "round_trip_cost_bps":2
}
```

Đoạn trên minh họa các trường; `bars` string là placeholder, không phải request hợp lệ. File mẫu chứa OHLC objects đầy đủ. Từ Python trong `agent/` có thể gọi trực tiếp, không cần broker/account/model:

```python
from pathlib import Path
from src.trading.forex.walk_forward import WalkForwardRequest, walk_forward

request = WalkForwardRequest.model_validate_json(
    Path("../docs/examples/forex-walk-forward.example.json").read_text(encoding="utf-8")
)
result = walk_forward(request)
```

32–2000 nến hoàn tất, liên tục, cùng timeframe; 1–16 cặp fast/slow, 2–8 block thời gian. Block đầu chỉ train; `n_blocks=4` tạo3 OOS folds. Chọn SMA theo compounded net return trên train, giữ tham số cho test kế tiếp, rồi mở rộng train và chọn lại. Purge theo horizon một nến; embargo bằng0 vì train chỉ nằm trước test, không giả vờ có embargo sau test.

Signal tại close t, vào open t+1 và thoát close t+1. Output ghi timestamp là bar-open và `outcome_available_at` tại close của outcome bar. Mỗi trade trừ một lần chi phí round trip cố định do caller khai báo; đây là **biến thể nghiên cứu riêng**, không phải simulator tick, SL/TP/swap hay bằng chứng parity với production runner. Fold/trial lỗi được giữ và aggregate OOS hoàn chỉnh bị giữ lại khi chưa đủ folds hợp lệ. Config, dữ liệu, boundary và trial outcomes đều có trong kết quả; endpoint tính không tự lưu. Registry persistent có thao tác write riêng tại mục7.

## 4. Crypto Funding và Open Interest

Main MCP/tool registry có `crypto_derivatives`:

```json
{"symbol":"BTC-USDT-PERP","metric":"open_interest","period":"1h","limit":30}
```

Đổi `metric` thành `funding` để đọc settlement thực tế. Tool chỉ hỗ trợ Binance USD-M **linear USDT perpetual** với symbol rõ product; từ chối spot/inverse/metadata không khớp. Không yêu cầu account/key cho public data, nhưng độ sẵn có phụ thuộc provider và điều kiện truy cập.

OI giữ amount theo base và value theo USDT; implied price là value/amount, không tự gọi là mark price. Phân rã quantity/price chỉ là đẳng thức giữa hai đầu kỳ, không kết luận bullish/causal. Funding cash minh họa cho một base unit chỉ dùng mark gắn với historical settlement; thiếu mark thì cash giữ null. `Regular`, `Special` và unknown được giữ riêng, kể cả cùng timestamp. Semantics historical mark và funding type đối chiếu [Binance market-data documentation](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data#get-funding-rate-history).

Limit2–100; summary/hash bao toàn bộ quan sát trả về, phần hiển thị chỉ10 mới nhất có cờ sampled. Coverage/actual intervals không chứng minh lịch funding đầy đủ hoặc cố định8h. Default live là latest bounded history; [capture/archive cục bộ](CRYPTO_DERIVATIVES_ARCHIVE.md) đã bổ sung riêng theo thời gian ghi nhận thực, vẫn chưa chứng minh exchange historical publication time hoặc portfolio funding ledger. Không thay giá trị thiếu bằng0 hoặc lấy current mark thay historical mark.

## 5. DAG và theo dõi phần chưa hoàn tất

Preset inspect và runtime dùng chung validator: chặn ID trùng/rỗng, agent không tồn tại, dependency thiếu/cycle và `input_from` không thuộc upstream. Dependency bắc cầu hợp lệ được chấp nhận. Invalid request bị từ chối trước khi ghi run/reap/thread; custom preset từng tham chiếu task ngoài dependency nay cần sửa graph.

[Tracker 265 ID](IMPLEMENTATION_TRACKER.md) ghi phần đã bàn giao và gate còn mở; [biên bản đợt3](IMPLEMENTATION_STATUS_2026-11-05_03.md) ghi lệnh test, skips và rollback. Các acceptance về broker, license, dữ liệu thật, UI và vận hành vẫn phải được hoàn tất trong phạm vi tương ứng.

## 6. Trang nghiên cứu trên Web

Selector có **Phòng lab Forex**: [cách nhập JSON, chạy/lưu và đọc mọi attempt](FOREX_RESEARCH_LAB.md), thêm workflow [regime replay chỉ đọc](FOREX_REGIME_RESEARCH.md) ở đợt8. Crypto có lựa chọn live/archive và nút capture write riêng; [semantics recording cutoff/quyền](CRYPTO_DERIVATIVES_ARCHIVE.md). VN có editor [so sánh P/E–P/B](VN_COMPARABLES.md), DCF và reverse DCF riêng; xem mục10/mục12.

Khởi động lại backend/frontend từ source mới rồi chọn **Nghiên cứu thị trường** trong menu, hoặc vào `/research` trên Web UI đang chạy. Trang chỉ đọc dữ liệu sau khi bấm **Chạy nghiên cứu**. Chọn thị trường VN và nhập mã đã cấu hình trong mục1; với fixture dùng `CASE.VN`, cutoff `2025-08-01T00:00:00Z`. Trang hiển thị số thập phân chính xác, giá trị chưa xác định/lý do, revisions/evidence, file hash và cutoff. Các kỳ tiếp theo giữ nguyên cutoff; không gộp các file revision khác nhau thành lịch sử immutable.

Crypto dùng `BTC-USDT-PERP`, chọn Open Interest hoặc Funding. Sampling interval chỉ dùng cho OI; Funding dùng thời điểm settlement thực. UI giữ summary toàn bộ phản hồi bounded và hiển thị tối đa10 observations; kiểm coverage/unknown thay vì đọc latest history như PIT archive. Đổi query/market hoặc hủy sẽ bỏ kết quả cũ. Các evidence URL chỉ mở HTTP(S) không có credentials.

API tương ứng là POST `/api/research/vietnam` và `/api/research/crypto`, có read authentication giống phần còn lại của app. Request không nhận arbitrary tool/path/credentials. Chúng dùng đúng tool đã mô tả ở mục1/4, không có engine tính toán thứ hai trên frontend. Chưa có browser screenshot/visual acceptance cho trang mới.

## 7. Lưu mọi lần thí nghiệm Forex

POST `/api/forex/experiments` với **toàn bộ** request [fixture Forex](examples/forex-walk-forward.example.json) tạo experiment và attempt đầu; response có `experiment_id` và `id` của run. POST `/api/forex/experiments/{experiment_id}/runs` với request đầy đủ khác sẽ append attempt mới. Các route ghi có settings-write auth và browser-origin gate hiện có. Endpoint `/api/forex/walk-forward` vẫn là tính toán tạm thời, không tự lưu.

GET `/api/forex/experiments?limit=20&offset=0` liệt kê experiment; GET `/api/forex/experiments/{experiment_id}?limit=20&offset=0` trả các run summary mới nhất; GET `/api/forex/experiments/{experiment_id}/runs/{run_id}` đọc request/engine/result đầy đủ. Trạng thái run là `running`, `ok`, `incomplete` hoặc `error`; process chết giữ `running`, chưa có recovery suy đoán. Failed trials vẫn nằm trong result; completed run không bị ghi đè và không tự kích hoạt strategy.

Forex MCP có sẵn `forex_list_experiments`, `forex_get_experiment`, `forex_get_experiment_run`. Operator cần thêm `--allow-research-writes` khi khởi động Forex MCP để xuất hiện `forex_run_experiment(request, experiment_id=None)`, `forex_run_cost_stress_experiment` và `forex_run_trade_paths_experiment`. Flag này độc lập `--allow-execution`; không bật quyền gửi lệnh. Sau đợt8, OANDA/Exness surface có **14 tool read-only**, hoặc **17 tool khi bật execution**; research-write cộng **3**. MT5 thêm **2** research tools hiện hữu. `forex_regime` không thêm writer. Xem [count và phạm vi hiện tại](FOREX_REGIME_RESEARCH.md#api-mcp-và-giới-hạn-triển-khai).

Store dùng schema4 trong database Forex cũ, lưu cả nến cung cấp. Đọc [backup/rollback](IMPLEMENTATION_STATUS_2026-11-05_04.md#dữ-liệu-và-rollback) trước khi mở database đang dùng; không downgrade bằng cách chỉ thay source hoặc xóa attempts. Chưa có tổng ngân sách tuning hay promotion/OOS reuse gate.

## 8. Replay Order Book từ sự kiện được cung cấp

Tool registry và main MCP dùng cùng `orderbook_depth` hiện có; mode replay không fetch. Request mẫu **tổng hợp**:

```json
{
  "symbol": "BTC-USDT", "exchange": "binance", "levels": 5,
  "replay": {
    "protocol": "binance_usdm_depth_v1",
    "events": [
      {"type": "snapshot", "lastUpdateId": 100, "bids": [["99", "2"]], "asks": [["101", "2"]]},
      {"type": "delta", "e": "depthUpdate", "s": "BTCUSDT", "U": 100, "u": 102, "pu": 99, "b": [], "a": []}
    ]
  }
}
```

Input theo receive order; snapshot cần bridge trước feature, sau đó `pu` phải bằng `u` đã nhận. Gap, crossed/locked hoặc nonfinite làm invalid cho đến snapshot+bridge mới; duplicate/stale không tạo thêm thay đổi, zero quantity xóa level. Có giới hạn input200 events/1000 level changes mỗi side/event/5000 retained levels mỗi side, trace20 mới nhất có counts toàn bộ và output budget10k. Thiếu `E` giữ timestamp null. Nguồn `caller_supplied_unverified`; không được gọi đây là live WebSocket recorder, OKX implementation hoặc bản ghi sàn đã xác minh. Quy tắc theo [Binance USD-M](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/websocket-market-streams/How-to-manage-a-local-order-book-correctly).

## 9. Giới hạn lượt gọi Swarm

Main MCP `run_swarm(preset_name, variables, max_llm_calls=12)` hoặc agent tool `run_swarm(prompt=..., max_llm_calls=12)` nhận positive integer cap; REST POST `/swarm/runs` có field `max_llm_calls` cạnh `preset_name` và `user_vars`. Bỏ field hoặc null giữ hành vi không cap. Cap được kiểm trước khi persist/run dispatch; lỗi input không tạo run.

Mỗi invocation `stream_chat` do Swarm điều phối cần một reservation dùng chung cho cả DAG, kể cả stream/worker retries. Response/run JSON có `max_llm_calls`, `llm_calls_started`, `llm_calls_unknown_usage`, `budget_stop_reason`; events có `llm_call_reserved` và `llm_call_usage`. Usage thiếu hoặc call chết giữa chừng là unknown; metadata provider có trên response bị hủy vẫn được cộng. Old run chưa có ledger giữ counters null.

Đây là cap **logical stream_chat invocations**, chưa là token/dollar/HTTP-request cap: SDK retries và fallback invoke bên trong provider wrapper có thể làm nhiều HTTP operations trong một slot. Cap không bao phủ AgentLoop ngoài Swarm. Retry/resume qua API/MCP/CLI tạo run mới với cùng cap và counters mới, không dùng đây làm tổng ngân sách tuning xuyên mọi run.

## 10. Định giá VN, độ nhạy và phiên bản nghiên cứu

Trong `/research`, chọn Việt Nam → **Phòng lab định giá Việt Nam**. Chọn so sánh P/E–P/B hoặc DCF; nhập JSON/file tối đa64000 byte, hoặc nạp ví dụ tổng hợp có nhãn rõ. Nạp không tự tính; tính không tự lưu. [Contract DCF/sensitivity](VN_DCF_SENSITIVITY.md) nêu VND scale, actual shares, restricted cash, WACC/g grid, base exit-multiple khác grid perpetuity và invalid cell giữ null/reason. Comparables dùng [contract riêng](VN_COMPARABLES.md), không lấy mặc định EPS/share basis từ biểu mẫu.

**Chạy và lưu phiên bản** thực thi lại input trên server, append request/result/hashes/producer vào kho SQLite riêng. Đọc lịch sử để mở revision, chọn revision trước và xem JSON Pointer diff. Với BCTC, `affected_metrics` chỉ ra ratios phụ thuộc input/evidence đổi; chưa là narrative claim graph. Review ghi nhãn người thao tác tự khai với trạng thái đã đọc/yêu cầu sửa; nguồn vẫn `user_supplied_unverified`. Xem [API, scope, quyền ghi và rollback](RESEARCH_REVISIONS.md).

Một revision chỉ là một trang research hoặc một kịch bản bounded. Không tự lưu toàn lịch sử, tạo PDF, xác minh tài liệu hoặc cấp quyền giao dịch. Khi timeout write, đọc attempt theo key trước bước tiếp theo; không có auto retry. Gửi lại có chủ đích cùng key/body lấy lại kết quả/trạng thái đã nhận, không chạy engine lần nữa. Giao diện khóa editor/phương pháp/phân trang của luồng khi đang ghi, bỏ qua read/upload cũ khi lựa chọn đổi.

## 11. Stress chi phí Forex trên OOS cố định

Trong lab Forex chọn **Stress chi phí trên OOS cố định**, nhập [fixture tổng hợp](examples/forex-cost-stress.example.json) hoặc request cùng schema. `research` chứa toàn bộ walk-forward; bốn khoản phí explicit phải cộng bằng base round-trip cost. Evaluator fit base một lần rồi áp spread1×/2×/3× lên cùng OOS tape. Không fit lại để chọn tham số có lợi cho scenario.

Kết quả có shared tape hash, compounded OOS return, net expectancy và arithmetic break-even spread; số âm không bị cắt về0, invalid/insufficient giữ null/reason. `gap_bps` là fixed charge, chưa price-gap replay. Tính dùng read-auth; lưu lại qua registry schema4 dùng write-auth, không activate strategy. [Hướng dẫn đầy đủ](FOREX_RESEARCH_LAB.md) ghi API/dedicated MCP, phí giả định, giới hạn và backup.

## 12. Reverse DCF, trade paths và dated-futures basis

Việt Nam có workflow **Reverse DCF: tăng trưởng hàm ý từ giá**: [fixture](examples/vn-reverse-dcf.example.json) chứa DCF đầy đủ, target VND/share, price evidence, share-basis note và bracket/tolerance rõ. Chỉ trạng thái solved có implied growth; ngoài bracket/không nhận diện/đụng giới hạn số học giữ null. Không tăng bracket hoặc nới tolerance tự động. [Guide](VN_REVERSE_DCF.md) giải thích fixed model, Decimal residual và API `/api/research/vietnam/reverse-dcf`.

Forex lab thêm phương pháp **Bootstrap đường vốn OOS**, [fixture](examples/forex-trade-paths.example.json) gồm `research`, `seed`, `simulations`, `block_length`. Chọn tham số từ train một lần, sample các block liên tiếp trong từng fold OOS. Fan và phân vị là thực nghiệm trên trade-index; không quy đổi năm, không phải xác suất lãi tương lai. Nút tính gọi `/api/forex/trade-paths`, nút lưu gọi registry write riêng. [Chi tiết](FOREX_RESEARCH_LAB.md#bootstrap-đường-vốn-từ-các-trade-oos-đã-khóa).

Crypto có workflow **Basis hợp đồng tương lai có kỳ hạn**, [fixture](examples/crypto-basis.example.json) khai spot và tối đa12 futures cùng bid/ask/expiry/availability/source/age-skew policy. `/api/research/crypto/basis` trả full curve; agent/main MCP `crypto_basis_curve(payload, offset)` page3 contract, summary/hash cùng phạm vi toàn request. Perpetual, stale, currency mismatch hoặc expiry sai bị loại với null/reason; signed gross basis giữ âm/zero. [Guide](CRYPTO_BASIS_CURVE.md) nêu day count và các chi phí/rủi ro còn thiếu.

Research revisions có năm kind, gồm `vietnam_reverse_dcf` và `crypto_basis` với request không bọc `payload`. Ý định lưu mới dùng quyền ghi riêng, server chạy engine và giữ immutable snapshot. Từ đợt8 Research SQLite writer dùng **schema2**, đọc schema1/2 và chỉ nâng1→2 khi write; Forex vẫn schema4. Backup trước lần write nâng schema, giữ database khi rollback và không hạ `user_version`. Không tạo report AI/PDF, tự kết nối sàn hoặc nâng source verification bằng review. Khởi động lại backend và nạp lại giao diện build mới để các route/schema mới có hiệu lực.

## 13. Refresh attempts và Markdown từ revision đã lưu

Panel revision sinh `idempotency_key` cho một ý định save và giữ bản sao input/parent. Sau lỗi hoặc mất kết nối, dùng **lịch sử attempt** để đọc theo kind, parent hoặc key; việc đọc không gọi engine và không tạo storage. `succeeded` có revision để mở, `failed` có safe error, `in_flight_unknown` không khẳng định đã thất bại hoặc chưa commit. Key chỉ ở state của panel, chưa persist qua browser reload. Một key mới là ý định mới; review hiện chưa có idempotency.

`GET /api/research/artifacts/attempts` có filters/paging và refresh state theo admission order. Failed refresh không sửa last-good revision; successful refresh tạo child để chủ động mở. [Hợp đồng đầy đủ](RESEARCH_REVISIONS.md#idempotency-attempt-và-refresh-state) phân biệt trạng thái refresh với độ mới thực tế của tài liệu/giá nguồn.

Mở revision rồi bấm lấy Markdown, xem preview và tải xuống. `GET /api/research/artifacts/{revision_id}/report` dùng read auth, trả tối đa **262144 byte UTF-8**, có `no-store`/`nosniff`. Preview/download cùng body đã tải, không fetch lần hai khi download. Renderer hỗ trợ đúng năm kind, giữ toàn bộ JSON/request/result/review trong phụ lục; thiếu/null/rejected không biến thành zero hoặc kết quả khả dụng. Vượt bound trả413, shape không phù hợp trả422; không cắt âm thầm. [Guide export](RESEARCH_REPORT_EXPORT.md) giải thích current review history, content hashes và giới hạn: bản nháp định lượng này chưa phải bài phân tích AI/PDF hoặc publishing.

## 14. Replay regime Forex nhân quả

Trong **Phòng lab Forex**, giữ workflow walk-forward cũ hoặc chọn **Phát lại regime nhân quả**. Nạp [fixture96 nến tổng hợp](examples/forex-regime.example.json) chỉ điền input; bấm replay mới gọi `POST /api/forex/regime`. Dedicated Forex MCP có `forex_regime(payload)` cùng evaluator, read-only. Không dùng thêm broker/account/model hoặc lưu experiment cho workflow này.

Feature là slope SMA chia ATR Wilder từ nến đã đóng. Entry/exit thresholds chỉ fit trên initial train prefix; hysteresis và min dwell áp dụng sau train. Warmup/ATR0/thiếu feature/ngưỡng suy biến giữ unknown. Kết quả có calibration, prefix/state/producer hashes, summary/latest toàn evaluation và một trang timeline. Nút xuất JSON giữ đúng request+một trang response, không gọi thêm trang hoặc tuyên bố đã có toàn timeline. [Guide](FOREX_REGIME_RESEARCH.md) nêu bounds, availability giả định từ close time, tests chống future leakage và giới hạn: heuristic chưa phải ADX, tín hiệu giao dịch hoặc xác suất lãi.

## 15. Học cách phân tích từ bộ mẫu FPT

[Đối chiếu PDF mẫu](REPORT_SAMPLE_FINDINGS.md) ghi kiểu trả lời, số liệu/trang/basis đã đọc và những điểm cần kiểm tra tiếp. [Phương pháp cơ bản sâu + nến](VIETNAM_DEEP_RESEARCH_METHOD.md) chuyển thành workflow: kết luận doanh nghiệp và timing riêng; bằng chứng → cơ chế → giả định → định giá → pullback/breakout/breakdown có điều kiện. Tách CFO/capex/vốn lưu động khỏi dòng tiền giao dịch ngoại/tự doanh và proxy volume/OBV; bộ tool fund-flow CN/HK/US không được dùng để giả dòng tiền Việt Nam.

Skill `vietnam-deep-research` đã được nối vào chat routing và hướng dẫn/allowlist các vai `vietnam_equity_council`. Khi chỉ yêu cầu phân tích sâu, agent dùng phương pháp và các tool phù hợp; không tự chạy swarm nếu chưa yêu cầu hội đồng. Khi chạy `run_research_council`, chart chỉ là OHLCV được lấy từ loader và nguồn council vẫn `reported_by_council`. Wrapper luôn `execution_ready=false`: chưa lấy live quote, order book, trạng thái phiên hoặc settled holdings. Với SELL, thiếu vị thế có thể bán làm verdict non-actionable và bỏ phép tính short-style risk/reward/sizing; không suy ra đang nắm cổ phiếu từ yêu cầu phân tích.

ATO/MTL và các loại lệnh là điều kiện thực thi cần nguồn quy tắc phiên/sàn, quote mới và khả năng broker; phương pháp không dự đoán giá khớp bằng nến ngày hoặc mục tiêu môi giới cũ. Khi thiếu, trả CHỜ/thiếu dữ liệu và kịch bản nghiên cứu có hạn hiệu lực. Các cảnh báo bất thường cần số liệu so sánh, khả năng giải thích khác và bước kiểm tiếp, không tự kết luận gian lận/thao túng. Xem [trạng thái đợt8](IMPLEMENTATION_STATUS_2026-11-06_08.md) cho kiểm chứng local và phần còn mở.
