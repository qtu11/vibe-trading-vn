# VN reverse DCF — tăng trưởng cuối kỳ hàm ý trong một bracket khai báo

Cập nhật **2026-11-06**, đợt 7. Chức năng trả lời: với forecast FCFF, WACC, equity bridge và số cổ phiếu được giữ cố định, mức tăng trưởng cuối kỳ nào khớp một giá VND/cổ phiếu trong sai số cho phép? Kết quả là lời giải có điều kiện, không phải dự báo tăng trưởng, fair value đã xác minh hoặc khuyến nghị đầu tư. Đây là phần mở rộng của [VN DCF và sensitivity](VN_DCF_SENSITIVITY.md); acceptance toàn chương trình vẫn mở trong [tracker](IMPLEMENTATION_TRACKER.md).

## Luồng sử dụng thực tế

Trong `/research`, chọn Vietnam rồi workflow reverse DCF. Input ban đầu trống. Nhập/import JSON hoặc chủ động nạp [ví dụ tổng hợp](examples/vn-reverse-dcf.example.json), sau đó bấm tính. Ví dụ dùng `CASE.VN`, target được tạo từ một kịch bản biết trước `g=0.03`; không phải giá quan sát ngoài thị trường. Nạp ví dụ không tự gọi engine hoặc lưu revision.

Web gọi `POST /api/research/vietnam/reverse-dcf` qua quyền đọc API hiện có. Body là payload trực tiếp trong fixture, không bọc thêm `payload`. API chạy [adapter reverse DCF](../agent/src/tools/vietnam_reverse_dcf.py) và các hàm [quantlib DCF](../agent/src/quantlib/valuation/dcf.py) đã có. Luồng này không fetch giá, đọc tài liệu từ URL, gọi model, broker hay tự ghi database.

Ví dụ gửi fixture từ repo root, khi server local của bạn đã chạy:

```python
import json
from pathlib import Path
import requests

payload = json.loads(
    Path("docs/examples/vn-reverse-dcf.example.json").read_text(encoding="utf-8")
)
response = requests.post(
    "http://127.0.0.1:8000/api/research/vietnam/reverse-dcf",
    json=payload,
    timeout=30,
    # Thêm Authorization từ secret store nếu cấu hình server yêu cầu.
)
response.raise_for_status()
result = response.json()
```

Base URL/port phải theo môi trường đang chạy; ví dụ không khẳng định port 8000 hiện đang mở. Không thêm main MCP tool hay CLI command riêng cho reverse DCF trong đợt này. Schema VN reverse DCF cũng không phải envelope `quantlib_call`.

## Request và phạm vi tài chính

| Field | Contract hiện có |
|---|---|
| `schema_version` | Số nguyên `1`; bool không được xem là version |
| `dcf` | Toàn bộ [contract VN DCF](VN_DCF_SENSITIVITY.md), gồm identity, cutoff, scale, forecast, WACC, terminal assumptions, equity bridge, sensitivity và evidence |
| `target_price_vnd` | Chuỗi Decimal dương, VND đầy đủ trên một cổ phiếu pha loãng thực |
| `price_observed_at` | Timestamp có timezone, không sau `dcf.as_of` |
| `price_evidence` | ID, URL HTTP(S) không credentials, document SHA-256, locator, published/available/retrieved do caller khai báo |
| `share_basis_note` | Ghi chú không rỗng, tối đa 400 ký tự, giải thích sự tương thích giữa giá và actual diluted shares |
| `growth_bracket` | `lower`, `upper` hữu hạn trong `[-0.99, 1]`, tăng nghiêm ngặt; `basis` không rỗng, tối đa 400 ký tự |
| `tolerance_vnd_per_share` | Chuỗi Decimal dương, sai số tuyệt đối VND/cổ phiếu cho phép |

Toàn request tối đa 64.000 byte UTF-8; field thừa, input không hữu hạn và schema sai bị từ chối. Target và tolerance theo quy tắc Decimal của adapter: tối đa 48 ký tự, giá trị dương `1e-12..1e24`; không nhận JSON float/bool thay chuỗi. Tỷ lệ trong DCF/bracket dùng dạng thập phân, không tự đổi `3` thành `3%`.

Chỉ dùng DCF consolidated, non-financial FCFF, với `terminal_value_method="perpetuity_growth"`. Exit-multiple không có một biến tăng trưởng Gordon tương đương để giải ở đây và bị từ chối. Base DCF phải hợp lệ trước khi tìm nghiệm; contract vẫn yêu cầu exit-multiple assumption để engine thực hiện cross-check hiện hữu, dù phương pháp được chọn là perpetuity growth.

`dcf.forecast` có 1–10 năm tương đối liên tục, mỗi khoảng đủ một năm; year-end hoặc mid-year theo lựa chọn của caller. WACC được xây từ các thành phần và cơ cấu vốn đã khai báo, sau đó giữ cố định trong toàn solver. Thay target không tự thay market-value equity input để tính lại WACC. Thuế, forecast, bridge và phương pháp discounting cũng không được tối ưu để tạo ra nghiệm đẹp.

`amount_scale` chỉ nhân tiền trong forecast/bridge/cơ cấu vốn, đưa về VND. **Target và tolerance không nhân scale; diluted shares cũng không nhân scale.** Ví dụ `amount_scale=1000000` vẫn nhận `target_price_vnd="126.52373764383182"`, không hiểu giá đó là triệu VND/cổ phiếu.

## Chronology, bằng chứng và share basis

Các mốc phải thỏa:

```text
price_observed_at <= price_evidence.published_at
                  <= price_evidence.available_at <= dcf.as_of
price_evidence.available_at <= price_evidence.retrieved_at
```

Bằng chứng tài chính và snapshot equity bridge tiếp tục qua kiểm tra của DCF hiện hữu: nguồn được khai báo available không sau cutoff; bridge snapshot không sau cutoff; evidence được viện dẫn cho bridge không có ngày công bố trước snapshot. Retrieval sau cutoff được phép như nghiên cứu tái dựng và làm `historical_reconstruction=true`, gồm cả evidence giá mới.

Chronology hợp lệ chỉ xác nhận các timestamp caller khai báo nhất quán. URL/hash không chứng minh tài liệu thật, giá đúng instrument hay split/rights/dilution đã đối chiếu. Hai ghi chú share basis ở outer request và equity bridge phải nói rõ giả định dùng giá trên cùng cơ sở cổ phiếu. Không có corporate-action adjustment, issuer identity hay available-at được xác minh độc lập. Kết quả và mọi review giữ `user_supplied_unverified`.

## Phép tính được giữ cố định

Solver dùng lại FCFF bridge từ `run_dcf`, rồi gọi `sensitivity_grid` cho từng giá trị `g`. Mỗi lần định giá giữ cùng WACC, tax/forecast và toàn bộ enterprise→equity→per-share bridge:

```text
TV(g) = FCFF_last * (1 + g) / (WACC - g)
EV(g) = PV_explicit_FCFF + TV(g) * terminal_discount_factor
Equity(g) = EV(g) - debt + unrestricted_cash
            - minority_interest - preferred_equity + associate_investments
Price(g) = Equity(g) / actual_diluted_shares
```

Restricted cash được tách riêng và không cộng vào unrestricted cash. Associates chỉ cộng theo xác nhận của caller rằng earnings của chúng đã loại khỏi EBIT dự báo. Solver không bỏ minority/preferred claims hoặc chỉ chia EV cho shares.

Toàn bracket phải thấp hơn WACC; `upper` cách WACC **hơn `1e-12`**. Lower không được lớn hơn hoặc bằng upper. Solver không cắt bracket, không vượt WACC để tìm nghiệm, không extrapolate target ngoài bracket và không gán xác suất cho các giá trị `g`. GDP growth reference vẫn là diagnostic của base DCF; nó không tự trở thành giới hạn cứng cho nghiệm reverse. Khi diễn giải, cần so sánh implied growth với các giả định kinh tế của chính mình.

Bisection kiểm tra endpoints trước, sau đó tối đa **128 vòng**. Chiều đơn điệu được lấy từ hai endpoint nên final FCFF âm vẫn được xử lý theo chiều giá giảm, không áp quy tắc FCFF dương một cách ngầm định.

## Đọc trạng thái và sai số số học

`ok=true` nghĩa là request hợp lệ và báo cáo được tính, không đồng nghĩa đã tìm được nghiệm. Chỉ `solver.status="solved"` mới có `implied_terminal_growth` khác null.

| `solver.status` | Ý nghĩa và giá trị cần giữ |
|---|---|
| `solved` | Endpoint hoặc điểm bisection đạt tolerance; giữ growth, giá định lại, residual và số vòng |
| `outside_bracket` | Target không thuộc khoảng giá tìm được và không đạt tolerance tại endpoint; không extrapolate, implied growth và giá định lại giữ null |
| `non_identifiable` | FCFF cuối kỳ bằng zero hoặc hai giá endpoint không phân biệt được ở độ phân giải số học; không chọn một growth tùy ý |
| `iteration_limit` | Chưa đạt tolerance; có thể do đủ 128 vòng hoặc `reason="numeric_resolution_limit"` khi midpoint float không còn thay đổi; giữ giá/điểm cuối và residual để kiểm tra nhưng implied growth vẫn null |

`endpoints`, `final_bracket`, `last_evaluated_growth`, `maximum_iterations`, `minimum_wacc_separation` và `reason` giúp kiểm tra kết quả mà không biến null thành zero. Growth `0.03` nghĩa là 3%/năm theo kịch bản, không phải xác suất 3% hoặc forecast đã được AI xác nhận.

Engine định giá và bisection vẫn dùng floating point. Phần hội tụ được đối chiếu với **giá trị Decimal của chuỗi giá thực sự hiển thị trong JSON**:

```text
residual = Decimal(str(engine_price)) - Decimal(declared_target)
converged = exact_absolute_residual <= Decimal(declared_tolerance)
```

Phép trừ residual dùng context 80 chữ số; giá trị tuyệt đối phải giữ nguyên chữ số thay vì làm tròn về context Decimal mặc định. `residual_vnd_per_share` được trả bằng chuỗi Decimal có dấu, hoặc null nếu chưa có điểm định lại; không ép target sang float trước rồi báo residual bằng zero. Một target lớn vẫn có thể tròn về cùng float với giá engine, nhưng chênh lệch Decimal thực tế còn vượt tolerance: khi đó không được báo `solved`.

Đây là kiểm tra tolerance đối với giá JSON của engine, không nâng toàn bộ DCF thành exact-decimal và không chứng nhận sai số kinh tế bằng tolerance caller chọn. Target/tolerance quá chặt có thể dẫn tới không có nghiệm biểu diễn được bằng float; cần giữ trạng thái thất bại thay vì tự nới tolerance.

## Lưu phiên bản, diff và review

Thao tác lưu riêng trong Web dùng [research revisions](RESEARCH_REVISIONS.md):

```text
POST /api/research/artifacts
kind = "vietnam_reverse_dcf"
request = <toàn bộ payload reverse DCF>
parent_revision_id = <tùy chọn>
```

Đây là write-auth, khác endpoint tính chỉ đọc. Server chạy lại engine và lưu `one_bounded_reverse_dcf_scenario`; client không gửi kết quả để tự xác nhận. Một báo cáo hợp lệ `outside_bracket`/`non_identifiable` cũng giữ null và reason khi được lưu. Parent phải cùng scope symbol/consolidation, nếu sai trả conflict; không thay thế revision gốc. Hash input chứa cả target, bracket, tolerance và bằng chứng; model hash nhận diện adapter/DCF/contracts được dùng.

Diff có thể cho thấy request, producer, source hoặc result thay đổi; không suy ra bằng chứng mới đã được xác minh. Review ghi nhãn người thao tác tự khai, ghi chú và quyết định đã đọc/yêu cầu sửa. Không tự retry một write timeout; đọc lịch sử để đối chiếu trước khi gửi lại. Input và selector workflow bị khóa trong lúc ghi; edit/cancel/unmount hủy read và bỏ phản hồi cũ.

## Kiểm chứng và phần còn lại

[Domain tests](../agent/tests/test_vietnam_reverse_dcf.py) so lời giải với phép đảo Gordon độc lập, cả discounting year-end/mid-year, full equity bridge, scale/shares, growth âm/zero/dương, negative/zero terminal FCFF, ngoài bracket, chronology và finite JSON. Precision regression kiểm tra target lớn không thể giả hội tụ sau float rounding và biên residual vượt tolerance. [HTTP/artifact/MCP tests đợt 7](../agent/tests/test_research_iteration7_routes.py) kiểm endpoint, auth, server recomputation, lineage, null, review và injection; MCP coverage trong file đó dành cho Crypto basis, không phải một reverse-DCF tool mới. [Web tests](../frontend/src/components/research/__tests__/VietnamReverseDCFLab.test.tsx) kiểm kết quả/status, null/zero, không tự chạy mẫu, bỏ response cũ và lưu riêng.

Chưa xác minh issuer/prices/financial documents thật, corporate actions và dilution; chưa ngân hàng/bảo hiểm, actual-day/stub/interim flows, multi-variable reverse model, probability/calibration, broker execution, report AI/PDF hoặc browser visual acceptance. Nghiệm trong bracket không xác nhận một cổ phiếu rẻ/đắt hoặc mô hình kinh tế phù hợp. Đóng góp cho `VN-112`/`VN-117`/`VN-128` tiếp tục ở mức partial.

Rollback adapter/API/Web của đợt 7 theo snapshot và thay đổi code; giữ database/revisions/review history. Không xóa dữ liệu nghiên cứu để downgrade và không dùng rollback ứng dụng để suy diễn đã đóng vị thế broker.
