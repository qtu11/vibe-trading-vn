# Crypto dated-futures basis — triển khai một phần CRYPTO-202

Đối chiếu ngày **2026-11-06**, đợt 7. Đây là phép tính trên quote do caller cung cấp, chưa phải feed futures, lịch sử sàn hay chiến lược basis arbitrage được nghiệm thu. Engine không truy cập mạng, tài khoản, broker, wallet hoặc filesystem nguồn. Kết quả và review luôn giữ `user_supplied_unverified`.

## Dùng trên Web, API và agent/MCP

Trong `/research`, chọn Crypto rồi workflow basis có kỳ hạn. Nhập/import một JSON hoặc chủ động nạp [ví dụ tổng hợp](examples/crypto-basis.example.json), sau đó bấm tính basis. Ví dụ dùng asset giả `CASE`, hai dated futures và một perpetual bị loại; thao tác nạp không tải dữ liệu hay tự lưu bản nghiên cứu.

`POST /api/research/crypto/basis` nhận trực tiếp JSON dưới đây với quyền đọc API hiện có. Endpoint trả đầy đủ tối đa 12 dòng. Lưu phiên bản là thao tác ghi riêng: `POST /api/research/artifacts` với `kind="crypto_basis"`, `request` là chính payload. Server chạy lại engine từ đầu vào, không nhận kết quả client để lưu. Lineage được scope theo base/quote; review chỉ ghi nhận đã đọc hoặc yêu cầu sửa, không xác minh nguồn.

Tool agent và main MCP `crypto_basis_curve(payload, offset=0)` dùng cùng engine, phân trang tối đa ba hợp đồng mỗi trang. `paging.next_offset` cho trang kế; `summary`, `input_sha256` và `aggregate_scope` luôn nói rõ phạm vi toàn bộ input. Đây là tool chỉ đọc; không thêm quyền giao dịch vào MCP.

```json
{
  "as_of": "2026-11-06T08:00:00Z",
  "base": "CASE",
  "quote": "USDT",
  "spot": {
    "venue": "synthetic-spot",
    "instrument_id": "CASE-USDT-SPOT",
    "kind": "spot",
    "base": "CASE",
    "quote": "USDT",
    "bid": "100",
    "ask": "100",
    "event_time": "2026-11-06T07:59:59Z",
    "available_at": "2026-11-06T08:00:00Z",
    "source_ref": "synthetic:spot-001"
  },
  "futures": [{
    "venue": "synthetic-futures",
    "instrument_id": "CASE-USDT-20261206",
    "kind": "dated_future",
    "base": "CASE",
    "quote": "USDT",
    "settle": "USDT",
    "linear": true,
    "expiry": "2026-12-06T08:00:00Z",
    "bid": "102",
    "ask": "102",
    "event_time": "2026-11-06T07:59:59Z",
    "available_at": "2026-11-06T08:00:00Z",
    "source_ref": "synthetic:future-001"
  }],
  "policy": {"max_quote_age_seconds": 5, "max_pair_skew_seconds": 2}
}
```

Đầu vào tối đa 64.000 byte UTF-8, từ 1 đến 12 futures. Giá phải là chuỗi Decimal dương trong `1e-12..1e24`, `ask >= bid`; bool, float, NaN/Infinity và field thừa bị từ chối. Base/quote/settle là identity riêng, không coi USD/USDT/USDC tương đương. Venue và instrument ID có giới hạn độ dài; một cặp venue/instrument không được lặp lại. `source_ref` tối đa 240 ký tự, chỉ URL HTTP(S) không có credentials hoặc evidence ID có giới hạn; không đọc URL hay đường dẫn từ đó.

Timestamps yêu cầu ISO có giây và timezone, tối đa sáu số thập phân, năm UTC 1900..2200. Engine chuẩn hóa UTC trước hash. `event_time` là thời điểm quote được khai báo; `available_at` là thời điểm caller khai báo nó có thể được biết. Hai trường này chưa có bằng chứng độc lập. Ngưỡng tuổi quote là số nguyên 0..604.800 giây; ngưỡng lệch hai quote là 0..86.400 giây. Không có ngưỡng mặc định ngầm.

## Phép tính và đơn vị

Gọi `S=(spot_bid+spot_ask)/2`, `F=(future_bid+future_ask)/2`, `tau=(expiry-as_of)/(365*86400)` theo giây UTC chính xác. Engine dùng lại `quantlib.fixedincome.year_fraction(..., "ACT/365F")` cho phần ngày UTC, kiểm tra invariant rồi cộng phần trong ngày bằng Decimal; không truyền datetime trực tiếp để tránh mất số giờ qua `.days`.

```text
basis_quote_per_base = F - S
basis_fraction      = F / S - 1
annualized_basis    = basis_fraction / tau
lower_basis_fraction = future_bid / spot_ask - 1
upper_basis_fraction = future_ask / spot_bid - 1
annualized_lower_basis = lower_basis_fraction / tau
annualized_upper_basis = upper_basis_fraction / tau
```

Giá spot 100 và futures 102 còn đúng 30 ngày có basis `0.02` và annualized `0.243333333...`, tức khoảng **24,333333%/năm** theo quy ước đơn. Tỷ lệ API là thập phân, không phải phần trăm. `USDT/CASE` là đơn vị giá; không chuyển USDT thành USD. Dùng precision 48 chữ số cho phép chia; input/output giá và tỷ lệ là chuỗi, kết quả lặp vô hạn được làm tròn tại precision đó. Negative basis giữ dấu, basis bằng zero giữ `"0"`.

Biên bid/ask trên là biên số học của quote hai chân. Chưa có quantity, depth, fills, phí, financing, borrow, vốn, margin, settlement/index reconciliation hoặc custody risk. Không suy diễn rằng giá bid/ask đó thực thi được cho một notional cụ thể. Hợp đồng gần đáo hạn có thể cho annualized rất lớn: đọc cùng `seconds_to_expiry` và basis chưa annualize.

## Điều kiện loại dòng và lỗi cấu trúc

Payload đúng cấu trúc luôn trả báo cáo `ok=true`, kể cả khi mọi dòng bị loại. `summary.accepted=0` lúc đó là kết quả audit hợp lệ; không tạo đường basis hay lợi suất cho các dòng đó. Mọi field tính toán của dòng rejected, gồm `annualized_basis`, các biên, basis và term, giữ `null`.

| Tình huống | Reason điển hình |
|---|---|
| Perpetual, kể cả khi caller đưa expiry giả | `perpetual_has_no_dated_basis` |
| Dated future thiếu expiry hoặc expiry không sau cutoff | `expiry_missing`, `expiry_not_after_cutoff` |
| Inverse/nonlinear hoặc sai base/quote/settle | `nonlinear_contract_unsupported`, `future_identity_mismatch` |
| Quote hoặc availability sau cutoff | `*_event_after_cutoff`, `*_unavailable_at_cutoff` |
| Caller khai báo biết quote trước chính event | `*_availability_before_event` |
| Tuổi quote vượt policy | `*_stale` |
| Hai event time lệch vượt policy | `quote_pair_skew_exceeded` |
| Spot sai identity chung hoặc giả hai loại bằng cùng identity | `spot_identity_mismatch`, `spot_future_identity_conflict` |

Ngưỡng age/skew dùng `>`: bằng ngưỡng vẫn hợp lệ. Spot không đạt điều kiện sẽ loại mọi dòng liên quan; lỗi một future không xóa các future khác hợp lệ. Sai cấu trúc, crossed bid/ask, identity trùng, số lượng quá giới hạn hoặc field thừa làm cả request bị từ chối, không tự bỏ input sai. Dòng được xếp theo expiry UTC thực, vẫn giữ `input_index`; hash input gồm quote, nguồn, policy, cutoff và cả những dòng bị loại.

## Cơ sở nghiên cứu và giới hạn nghiệm thu

Đã đọc nguồn chính thức sau để chọn quy ước, không lấy quote thị trường từ chúng:

- [CF Bitcoin Compounding Basis Index, v1.0, May 2026, trang 6](https://docs.cfbenchmarks.com/CF_Bitcoin_Compounding_Basis_Index.pdf) công bố hệ số 365/ACT và quy ước đơn ACT/365. Adapter này chỉ dùng quy ước day-count để so sánh quote, không sao chép portfolio/index rolling của benchmark đó.
- [CME Cryptocurrency BasisWatch](https://www.cmegroup.com/markets/cryptocurrencies/cryptocurrency-basis-watch-and-implied-rate-tool) phân biệt quan hệ spot/futures với đường rate annualized, đồng thời nêu cách chọn spot marker/contract của riêng CME. Adapter không nhận rằng quote do caller cung cấp tuân thủ các cách chọn đó.
- [Bybit public ticker schema](https://bybit-exchange.github.io/docs/v5/websocket/public/ticker) tách `basisRateYear` cho futures và funding fields cho perpetual. Adapter không dùng funding để gán kỳ hạn cho perp.

Fixture/test offline bao phủ oracle 100/102/30 ngày, backwardation, zero, biên bid/ask, age/skew đúng ngưỡng và hơn một microsecond, future availability, một quote chung stale, UTC offset tương đương, term qua nửa đêm, term một microsecond, identity mismatch, quoted-source validation, hash/paging và read-only tool. Web tests kiểm tra không tự fetch, null/zero/negative, bỏ phản hồi cũ, hủy request và freeze khi lưu. Việc kiểm tra UI trực quan trong trình duyệt, source/provider thật, lịch sử instrument PIT, fee/borrow/capital ledger, cross-venue settlement và execution vẫn chưa được nghiệm thu.

Rollback code theo thay đổi đợt 7; không xóa DB artifact hay historical revisions. Tạm bỏ workflow/API/tool nếu cần dừng khả năng mới; không đổi quyền đọc thành quyền broker-write và không diễn giải rollback app là đóng vị thế trên sàn.
