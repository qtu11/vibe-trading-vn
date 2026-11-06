# DCF và độ nhạy Việt Nam

Cập nhật **06/11/2026**. Trong `/research`, chọn thị trường Việt Nam → **Phòng lab định giá Việt Nam** → **DCF và độ nhạy**. Giao diện cũng nối phương pháp [so sánh P/E–P/B](VN_COMPARABLES.md). Nhập file JSON hoặc dán yêu cầu tối đa64000 byte; nạp ví dụ không tự tính hay lưu. [Ví dụ DCF](examples/vn-dcf.example.json) chỉ là kịch bản tổng hợp CASE.VN, không phải dữ liệu hay dự báo của doanh nghiệp thật.

## Hợp đồng đầu vào

[VietnamDCFRequest](../agent/src/tools/vietnam_dcf.py) chỉ hỗ trợ doanh nghiệp phi tài chính, BCTC hợp nhất, tiền VND. `amount_scale` phải là1,1000,1000000 hoặc1000000000; chỉ các khoản tiền được nhân scale. `diluted_shares` là số cổ phiếu thực, không nhân scale. Tiền được nhập bằng chuỗi decimal có giới hạn, tỷ lệ bằng số hữu hạn; field lạ bị từ chối.

Phải khai báo đầy đủ thành phần WACC: risk-free rate, beta, equity-risk premium, pretax cost of debt, tax, size và country premiums, cùng cơ cấu vốn mục tiêu hoặc giá trị thị trường hiện tại. Giá trị0 cũng cần basis; phần mềm không điền premium, thuế, tăng trưởng hay dự báo mặc định. Các scalar/forecast/bridge giữ `basis` và `source_ids`; `[]` nói rõ giả định chưa có bằng chứng hỗ trợ.

`forecast` có1–10 năm tương đối liên tục từ1, mỗi năm là một khoảng đủ năm kể từ thời điểm định giá, gồm EBIT, D&A, capex và delta NWC có dấu. Chưa hỗ trợ calendar stub, dòng tiền giữa kỳ hay actual-day discounting. Người dùng chọn year-end hoặc mid-year theo contract engine hiện hữu.

Equity bridge tách total debt, unrestricted cash, restricted cash, minority interest, preferred equity, associates và actual diluted shares. Restricted cash được báo riêng, không cộng vào giá trị vốn chủ. Associates chỉ được cộng khi caller khai rõ earnings của chúng không nằm trong EBIT dự báo. Đối chiếu debt-like claims, dilution, currency và nguồn là trách nhiệm của đầu vào, chưa được engine xác minh độc lập.

Tối đa12 evidence có ID duy nhất, URL HTTP(S) không credential, locator, document SHA và các mốc published/available/retrieved. Source availability phải phù hợp cutoff khai báo. Retrieval sau `as_of` được đánh dấu `historical_reconstruction`; đây không chứng minh nguồn đã thực sự được biết ở thời điểm lịch sử. Không fetch URL hoặc coi hash do caller cung cấp là chứng nhận tài liệu.

## Engine và đầu ra

Adapter gọi lại `run_dcf`, `sensitivity_grid` và equity bridge của [quantlib DCF](../agent/src/quantlib/valuation/dcf.py). Base case giữ FCFF bridge, WACC build, discounted cash flows, terminal value và bridge enterprise→equity→per-share. Money output là VND; per-share là VND/cổ phiếu. Kết quả dùng floating point sau khi chuẩn hóa decimal, không phải sổ kế toán exact-decimal.

Sensitivity là hai trục WACC/g tăng dần, duy nhất, mỗi trục tối đa9 giá trị, có basis rõ. Mỗi cell tính từ cùng FCFF và cùng equity bridge; không chỉ chia enterprise value cho shares. `g >= WACC` cho `value_per_share_vnd: null`, reason `growth_must_be_below_wacc`, không trả JSON NaN hay0.

**Grid luôn dùng perpetuity growth**, kể cả khi base case chọn exit multiple. Giao diện ghi rõ khác biệt này; không gọi grid là phân phối xác suất, không gán xác suất cho cell. Input tax, currency và bridge cố định trong một grid; thay chúng cần yêu cầu/phiên bản riêng. Base growth không hợp lệ bị từ chối trước chạy, ngay cả khi chọn exit multiple.

Kết quả giữ `input_sha256`, `model_version` từ source adapter/DCF/contracts, normalized inputs với đơn vị và evidence. Model hash không xác minh môi trường triển khai, tài liệu bên ngoài hay tính phù hợp kinh tế của giả định. Tất cả vẫn là kịch bản có điều kiện từ nguồn chưa xác minh.

## API, lưu và review

`POST /api/research/vietnam/dcf` nhận trực tiếp JSON theo fixture, cần quyền đọc qua cơ chế auth chung. Gọi này không ghi kho nghiên cứu. Ví dụ từ repo root:

```python
import json
from pathlib import Path
import requests

payload = json.loads(Path("docs/examples/vn-dcf.example.json").read_text(encoding="utf-8"))
# Lấy bearer từ cấu hình môi trường chạy nếu server yêu cầu; không đặt secret trong file này.
response = requests.post("http://127.0.0.1:8000/api/research/vietnam/dcf",
                         json=payload, timeout=30)
response.raise_for_status()
result = response.json()
```

Port/base URL phải theo server đang chạy của bạn;8000 là default của server CLI, không phải bằng chứng server hiện đang mở. Với server yêu cầu bearer, thêm `Authorization` từ secret store của môi trường.

**Chạy và lưu phiên bản** gọi kho [research revisions](RESEARCH_REVISIONS.md) với `kind: vietnam_dcf`, `request` là payload gốc và parent tùy chọn. Server thực thi lại, không nhận kết quả tự chứng nhận từ browser. Không tự retry write; timeout cần đọc lịch sử trước khi gửi lại. Review chỉ ghi nhãn người thao tác tự khai và ghi chú, không đổi `user_supplied_unverified`.

Đợt này không thêm main MCP tool hoặc quantlib export. Luồng `quantlib_call` hiện hữu vẫn nhận envelope Assumption riêng trong [hướng dẫn](MULTI_MARKET_RESEARCH_USAGE.md#2-dcf-qua-json-và-main-mcp); không gửi schema VN mới vào tool đó như thể cùng contract.

## Kiểm chứng và giới hạn

[Domain tests](../agent/tests/test_vietnam_dcf.py) kiểm chuẩn hóa scale/share count, bridge restricted cash/debt/minority/associates, engine parity, WACC/terminal methods, trục sensitivity, invalid cells, evidence cutoff, strict shape và finite JSON. [HTTP tests](../agent/tests/test_research_routes.py) kiểm cùng kết quả engine qua JSON/auth và lỗi an toàn. [UI tests](../frontend/src/components/research/__tests__/VietnamValuationLab.test.tsx) kiểm phương pháp, zero/null, stale responses và lưu riêng. Hai fixture docs/frontend được đối chiếu byte; chưa browser visual acceptance.

Mapping partial: `VN-112`, `VN-117`, `VN-128`. Đợt7 bổ sung [reverse DCF tìm tăng trưởng hàm ý từ giá](VN_REVERSE_DCF.md) qua cùng input bridge/engine, không thay grid này. Chưa forecast tự động, bank/insurance model, corporate-action verification, nguồn thật được xác minh, report AI/PDF hoặc claim graph. [Tracker](IMPLEMENTATION_TRACKER.md) giữ toàn bộ acceptance mở. Rollback adapter/API/UI bằng snapshot tương ứng, giữ các phiên bản nghiên cứu đã lưu; không xóa database để downgrade.
