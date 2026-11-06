# Research revisions: lưu kết quả server và đối chiếu thay đổi

Cập nhật **06/11/2026**, đợt 8. Đây là kho snapshot nghiên cứu định lượng đã thực thi trên server. Mỗi revision giữ nguyên request chuẩn hóa, kết quả, nguồn khai báo và dấu vết mã tạo kết quả. Kho có lịch sử attempt, khóa chống lặp tùy chọn và [xuất Markdown từ snapshot](RESEARCH_REPORT_EXPORT.md); chưa tạo bài phân tích bằng AI, PDF, khuyến nghị đầu tư hoặc báo cáo đã xác minh độc lập.

## Luồng thực thi và phạm vi

Client gửi **input** vào `POST /api/research/artifacts`. [Service](../agent/src/research_artifacts/service.py) chọn một trong năm engine cố định. Với một ý định mới, server ghi nhận attempt rồi chạy engine ngoài writer lock; chỉ append revision khi kết quả có `ok: true`. Gửi lại cùng `idempotency_key` và cùng body được đối chiếu với attempt cũ, không chạy lại engine. Client không được truyền `result`, tên tool tùy ý hoặc đường dẫn dữ liệu. Không có model call, thực thi lệnh hoặc broker action trong luồng này.

| `kind` | Hình dạng `request` | Engine | Nội dung được lưu |
| --- | --- | --- | --- |
| `vietnam` | `code`, `as_of?`, `period?`, `consolidation?`, `offset?` | [VietnamResearchTool](../agent/src/tools/vietnam_research_tool.py) | Một trang research thực sự được trả về, bao gồm periods, input/metric/evidence và `paging` |
| `vietnam_comparables` | `{ "payload": <comparables>, "offset": 0 }` | [VietnamComparablesTool](../agent/src/tools/vietnam_comparables_tool.py) | Request toàn bộ peer set; kết quả có aggregate toàn set và chi tiết peer của trang được trả về |
| `vietnam_dcf` | Payload DCF trực tiếp, không bọc thêm `payload` | [build_vietnam_dcf](../agent/src/tools/vietnam_dcf.py) | Một kịch bản FCFF có base case, equity bridge, sensitivity và giả định/nguồn khai báo |
| `vietnam_reverse_dcf` | Payload reverse DCF trực tiếp; DCF nằm trong trường `dcf` của payload | [build_vietnam_reverse_dcf](../agent/src/tools/vietnam_reverse_dcf.py) | Một kịch bản giá suy ra terminal growth trong bracket khai báo; giữ trạng thái solver và lý do chưa có nghiệm |
| `crypto_basis` | Payload basis trực tiếp gồm `as_of`, `base`, `quote`, `spot`, `futures`, `policy`; không bọc `payload` hoặc thêm `offset` | [build_crypto_basis](../agent/src/tools/crypto_basis.py) | Toàn bộ curve tối đa 12 futures được cung cấp, gồm cả các row rejected với reason codes và giá trị tính toán null |

`content_scope` là `one_returned_research_page` cho hai kind đầu, `one_bounded_dcf_scenario` cho DCF, `one_bounded_reverse_dcf_scenario` cho reverse DCF và `one_supplied_basis_curve` cho Crypto basis. Lưu thành công một trang không chứng minh đã đọc hoặc lưu toàn bộ lịch sử. Snapshot có trang trống vẫn được giữ đúng nếu engine trả `ok: true`; không biến trang trống thành báo cáo có số liệu.

`ok: true` có nghĩa engine đã trả envelope hợp lệ để lưu, không có nghĩa mọi phép tính con đã cho kết quả khả dụng. Reverse DCF có thể `outside_bracket`, `non_identifiable` hoặc chưa đạt tolerance; `implied_terminal_growth` vẫn null. Crypto basis có thể chứa toàn bộ row rejected vì perpetual, quá tuổi quote, lệch thời gian hoặc identity không khớp; annualized basis của các row đó vẫn null. Revision giữ nguyên các trạng thái/lý do, không loại row lỗi để dựng curve hoàn chỉnh hoặc tự gán nghiệm.

Các nguồn BCTC phải được operator cấu hình trước theo [hướng dẫn BCTC local](LOCAL_VN_FINANCIAL_STATEMENTS.md). Comparables, DCF, reverse DCF và Crypto basis dùng dữ liệu người gọi khai báo; engine không tải hoặc xác minh tài liệu gốc. [Ví dụ comparables](examples/vn-comparables.example.json), [ví dụ DCF](examples/vn-dcf.example.json), [reverse DCF](examples/vn-reverse-dcf.example.json), [Crypto basis](examples/crypto-basis.example.json) và [BCTC](examples/vn-company-research.example.json) đều là dữ liệu synthetic phục vụ kiểm tra phép tính. Lưu Crypto basis không phải thao tác capture feed hoặc xác minh giá đang giao dịch.

## API và quyền truy cập

Các endpoint được đăng ký tại [research_artifact_routes.py](../agent/src/api/research_artifact_routes.py). Không có endpoint sửa hoặc xóa revision, review hoặc attempt.

| Method và URL | Quyền | Hành vi |
| --- | --- | --- |
| `POST /api/research/artifacts` | Write auth | Nhận `kind`, `request`, `parent_revision_id?`, `idempotency_key?`; nhận ý định mới hoặc trả lại kết quả/trạng thái attempt cũ |
| `GET /api/research/artifacts?kind=vietnam&limit=20&offset=0` | Read auth | Trả metadata, tổng số revision và `next_offset`; không tải toàn bộ result của từng dòng |
| `GET /api/research/artifacts/attempts?kind=vietnam&limit=20&offset=0` | Read auth | Trả receipts; lọc thêm `parent_revision_id?` và `idempotency_key?`; có refresh state khi chỉ định parent |
| `GET /api/research/artifacts/{revision_id}` | Read auth | Đọc result đầy đủ của revision cùng review history |
| `GET /api/research/artifacts/{revision_id}/report` | Read auth | Xuất Markdown UTF-8 từ revision đã đọc; không chạy engine hoặc ghi storage |
| `GET /api/research/artifacts/{after_id}/diff?before={before_id}&limit=100` | Read auth | So sánh result của hai revision cùng scope |
| `POST /api/research/artifacts/{revision_id}/reviews` | Write auth | Append một acknowledgment hoặc yêu cầu chỉnh sửa |

Read dùng `require_auth`; write dùng `require_settings_write_auth` của [security.py](../agent/src/api/security.py). Khi server cấu hình `API_AUTH_KEY`, cần `Authorization: Bearer ...`. Khi chưa cấu hình key, chỉ client loopback được tin cậy theo quy tắc hiện hữu. Write từ browser cross-site bị từ chối, kể cả khi có bearer hợp lệ. Nhãn reviewer không thay thế danh tính xác thực: đây là kho theo runtime của ứng dụng, chưa có ACL theo tài khoản hoặc tenant cho từng revision.

ID revision server cấp có dạng `rr_` cộng 32 ký tự hex thường; attempt dùng `ra_` cộng 32 ký tự hex. Đọc revision chưa tồn tại trả `404`; input sai hoặc research thất bại theo domain trả `422`; scope không khớp, hash hỏng, database khác loại, clock lùi, key xung đột hoặc attempt chưa rõ kết quả trả `409`. Lỗi engine bất ngờ trả `503 RESEARCH_EXECUTION_FAILED` với receipt an toàn nếu đã ghi được outcome. Lỗi storage bất ngờ trả `503 RESEARCH_ARTIFACT_UNAVAILABLE`. Không đưa đường dẫn riêng hay nội dung exception tùy ý ra HTTP. Report vượt bound trả `413 REPORT_TOO_LARGE`, shape không được hỗ trợ trả `422 INVALID_REPORT_REVISION`.

Ví dụ lưu một trang research VN sau khi đã cấu hình nguồn cho `CASE.VN`:

```json
{
  "kind": "vietnam",
  "idempotency_key": "research_request_001",
  "request": {
    "code": "CASE.VN",
    "as_of": "2026-11-05T00:00:00Z",
    "period": "quarter",
    "consolidation": "consolidated",
    "offset": 0
  }
}
```

Ví dụ PowerShell đọc file DCF synthetic và gửi snapshot; chạy từ thư mục repository. Header chỉ sử dụng key đã được cấu hình trong môi trường hiện tại, không ghi credential vào file:

```powershell
$revisionHeaders = @{}
if ($env:API_AUTH_KEY) {
    $revisionHeaders.Authorization = "Bearer $env:API_AUTH_KEY"
}
$revisionScenario = Get-Content -LiteralPath 'docs/examples/vn-dcf.example.json' -Raw -Encoding utf8 | ConvertFrom-Json
$revisionBody = @{ kind = 'vietnam_dcf'; request = $revisionScenario } | ConvertTo-Json -Depth 64
Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/research/artifacts' -Method Post -Headers $revisionHeaders -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($revisionBody))
```

Đối với comparables, thay `kind` bằng `vietnam_comparables` và đặt đối tượng đọc từ file vào `request.payload`, kèm `request.offset = 0`. Với reverse DCF, đọc `docs/examples/vn-reverse-dcf.example.json`, đặt `kind = 'vietnam_reverse_dcf'` và giữ đối tượng đọc được làm `request` trực tiếp. Crypto basis tương tự với `docs/examples/crypto-basis.example.json` và `kind = 'crypto_basis'`. Không bọc thêm `payload` cho hai kind mới này.

Các endpoint chỉ tính `/api/research/vietnam/dcf`, `/api/research/vietnam/reverse-dcf` và `/api/research/crypto/basis` không tự lưu revision; thao tác lưu luôn là write rõ ràng. Giao diện dùng [ResearchRevisionPanel](../frontend/src/components/research/ResearchRevisionPanel.tsx) trong luồng research. Main MCP `crypto_basis_curve(payload, offset)` có wrapper paging riêng; artifact `crypto_basis` dùng trực tiếp builder để lưu toàn bộ supplied curve trong bound, không nhận `offset` và không gọi exchange.

## Idempotency, attempt và refresh state

`idempotency_key` tùy chọn, gồm 8..128 chữ ASCII, số, `_` hoặc `-`. Key được ràng buộc với JSON canonical của **body caller gốc**: `kind`, `request`, `parent_revision_id`. Vì vậy retry của request VN không khai `as_of` vẫn tìm đúng ý định cũ dù clock đã đổi; nó không lấy cutoff mới để tạo một lần chạy khác. Key không phải credential và không cấp quyền đọc/ghi.

| Kết quả của key đã có | Lần gửi lại cùng body |
| --- | --- |
| `succeeded` | Trả revision đã lưu, kèm review history hiện tại; không đọc lại nguồn, producer hoặc engine |
| `failed` | Trả lại lỗi an toàn và receipt đã lưu; nguồn được sửa sau đó không làm key cũ tự chạy lại |
| `in_flight_unknown` | `409 RESEARCH_ATTEMPT_IN_FLIGHT`; không chiếm attempt hoặc tự chạy lại |
| Key dùng với body/kind/parent khác | `409 IDEMPOTENCY_CONFLICT`, kèm receipt của ý định đã có |

Không gửi key thì mỗi lần gọi hợp lệ là một attempt riêng; save thành công tạo revision ID mới kể cả input/output giống nhau. Muốn nghiên cứu lại sau một failed attempt, dùng key mới cho ý định mới. Không tự retry write do timeout. Nếu việc ghi terminal outcome không thể được xác nhận, API có thể trả `409 RESEARCH_ATTEMPT_UNCERTAIN`; đọc lịch sử để kiểm tra trước bước tiếp theo. Trạng thái `in_flight_unknown` nghĩa là có admission nhưng chưa có outcome được ghi: có thể đang chạy hoặc đã gián đoạn, không tự suy thành thất bại hoặc thành công. Hiện chưa có lease, timeout takeover hoặc endpoint resume attempt đó.

Receipt gồm attempt/key/kind/parent, hash của caller body và request chuẩn hóa, `created_at`, `status`, `finished_at`, `revision_id` và `error`. Lỗi có `code`, `message`, `stage` (`producer`, `engine`, `manifest`) và loại exception an toàn. Listing không trả nguyên normalized request; request bounded vẫn được lưu trong manifest nội bộ của attempt. Một input bị từ chối trước admission không tạo receipt.

`GET /attempts` nhận `limit=1..100`, `offset=0..100000`; thứ tự là admission sequence mới nhất trước. Khi truyền `parent_revision_id`, `refresh_state` phản ánh attempt mới nhất được nhận cho parent đó, kể cả khi bộ lọc kind/key làm trang `items` hẹp hơn:

| `refresh_state.state` | Ý nghĩa |
| --- | --- |
| `no_refresh_attempt` | Chưa có attempt refresh được nhận; `last_good_revision_id` là parent |
| `refresh_failed` | Attempt được nhận sau cùng thất bại; giữ parent hoặc child thành công gần nhất làm last good |
| `refresh_in_flight_unknown` | Attempt được nhận sau cùng chưa có outcome; không khẳng định dữ liệu đã cập nhật |
| `superseded` | Attempt được nhận sau cùng thành công; có revision thay thế để chủ động mở |

`last_good_revision_id` là revision thành công có admission mới nhất trong các attempt cùng parent, hoặc parent nếu chưa có. Thứ tự này không phải thời gian hoàn tất: một request cũ chạy chậm không được che trạng thái của request được nhận sau nó. Đây là trạng thái luồng refresh, không phải cam kết dữ liệu thị trường còn mới hoặc mọi tài liệu nguồn đã cập nhật. Revision gốc không bị gắn lại timestamp hoặc sửa nội dung khi refresh lỗi.

Web sinh key `rk_...`, khóa bản sao request/parent cho lần lưu và giữ key khi người dùng chủ động gửi lại cùng ý định chưa có xác nhận. Đổi request/parent hoặc chọn “ý định mới” tạo key mới. Key chỉ ở state của panel, chưa lưu qua reload trình duyệt; nên giữ lại key nếu cần đối chiếu sau khi đóng trang. [ResearchAttemptHistory](../frontend/src/components/research/ResearchAttemptHistory.tsx) chỉ đọc khi bấm, cho chọn toàn kind, parent đang mở hoặc key đang có; không tự chạy lại nghiên cứu. Review write hiện chưa có idempotency key.

## Cấu trúc lưu trữ, thời gian và tính bất biến

[ResearchArtifactStore](../agent/src/research_artifacts/store.py) dùng SQLite stdlib theo pattern connection ngắn hiện có. Đường dẫn mặc định là:

```text
<get_runtime_root()>/research/artifacts.sqlite
```

`get_runtime_root()` tôn trọng `VIBE_TRADING_HOME`; đường dẫn này thuộc runtime ứng dụng, không được truyền qua HTTP. Database độc lập với sessions, Forex experiments và Crypto capture archive. Writer hiện dùng **`user_version=2`**, `application_id=0x56524152` (1448231250); revision manifest vẫn `schema_version=1`. Reader chấp nhận database phiên bản 1 hoặc 2 đúng application ID. Database khác loại hoặc version ngoài allowlist bị từ chối.

Đợt 8 thêm `attempts` và `attempt_outcomes` vào schema 2. Đọc database schema 1 không migrate, không thêm file và trả lịch sử attempt rỗng; revision/review cũ vẫn đọc được. Write hợp lệ dùng writer mới nâng 1 → 2 trong transaction; không ghi lại revision, review, nội dung hash hoặc timestamp cũ. Lịch sử trước migration không được bịa thành attempt. Mã chỉ hiểu schema 1 sẽ từ chối schema 2; reader cũ cũng có thể không hiểu hai kind bổ sung ở đợt 7. Không hạ `user_version` để ép mã cũ mở kho.

Khởi tạo service và thao tác đọc không tạo thư mục/database. GET mở SQLite bằng `mode=ro`. Admission đầu tiên có thể tạo storage kể cả khi engine sau đó thất bại. Transaction `BEGIN IMMEDIATE` kiểm parent/scope, ràng buộc key và commit admission trước khi chạy engine; engine không giữ writer lock. Transaction thành công append revision và terminal success atomically; transaction failure append terminal error riêng, không có replacement revision. Mỗi attempt có nhiều nhất một terminal outcome. Parent có thể có nhiều child, chưa có quy tắc single-head hoặc tự merge các nhánh.

SQL triggers chặn `UPDATE` và `DELETE` trên revisions, reviews, attempts và attempt outcomes. Review nằm trong bảng event riêng; không sửa request/result/hash hoặc timestamp gốc của revision. Replay key thành công trả ID cũ, không append revision hoặc attempt mới.

`created_at` là thời gian UTC ghi cục bộ từ clock server, không phải lúc sàn/doanh nghiệp công bố dữ liệu hoặc chứng nhận thời gian bên ngoài. Attempt ghi thời gian admission; revision ghi thời gian append dưới writer lock. Admission mới không được trước các recording time revision/attempt/outcome hiện có; completion không trước admission, hoặc trước revision vừa ghi trong cùng success transaction. `as_of` là cutoff của nghiên cứu: nếu VN statements bỏ `as_of`, service giải quyết thành UTC cụ thể trong request chuẩn hóa. Review không trước review trước đó hoặc thời điểm tạo của revision; chưa có clock ordering chung giữa review trên mọi nhánh và toàn bộ các loại event.

Manifest giữ `request_sha256`, `result_sha256`, `producer_sha256`, `source_sha256` và `facts_sha256`. JSON canonical giữ decimal string, `null` và zero; không làm tròn input để tạo hash. Producer ghi hash các module nguồn được liệt kê, chưa khóa toàn bộ dependency hoặc môi trường Python. Source hash chứa bằng chứng và metadata tương ứng; với BCTC, thay đổi byte file nguồn ngoài phần dữ liệu đang hiển thị vẫn có thể làm source hash đổi.

Với reverse DCF, source projection giữ evidence của DCF và evidence giá; `facts_sha256` tách các đối tượng evidence đó khỏi phần request còn lại. Với Crypto basis, source projection gồm venue, instrument ID, event time, available time và source reference của spot/futures; `facts_sha256` hiện bao toàn bộ request chuẩn hóa, gồm cả các khai báo nguồn/policy. Vì vậy thay riêng source reference của Crypto cũng có thể làm `facts_changed` bằng true; cờ này chưa chứng minh giá hoặc giá trị kinh tế đã đổi. Dùng field diff để xác định cụ thể phần thay đổi.

Store kiểm manifest hash và binding request/result/producer khi đọc; đọc đầy đủ revision kiểm các event review. Listing kiểm manifest và event review mới nhất để trả metadata có giới hạn, không xác minh toàn bộ note lịch sử của mọi revision trên mỗi trang. Hash và SQL trigger phát hiện/chặn các sửa đổi thông thường; người có toàn quyền sửa file SQLite, bỏ trigger và tính lại hash vẫn có thể làm giả database. Đây chưa là chữ ký nguồn, ledger chống operator sửa, hoặc chứng cứ về ngày công bố lịch sử.

## Scope, parent và diff

Parent phải tồn tại, cùng `kind` và cùng scope:

| Kind | Scope bắt buộc giống nhau |
| --- | --- |
| `vietnam` | `code`, `period`, `consolidation`, `offset` |
| `vietnam_comparables` | Target symbol, `period_start`, `period_end`, `consolidation`, `offset` |
| `vietnam_dcf` | `symbol`, `consolidation` |
| `vietnam_reverse_dcf` | `dcf.symbol`, `dcf.consolidation` |
| `crypto_basis` | `base`, `quote` |

`as_of` và các giá trị tài chính có thể thay đổi giữa các revision cùng scope. Parent chỉ ghi lineage, không cấp quyền mới hoặc đổi trạng thái nguồn. Diff cũng yêu cầu cùng scope, nhưng hai revision được so sánh không bắt buộc là parent/child trực tiếp. Với paging theo offset, các kỳ mới xuất hiện có thể đẩy trang cũ sang vị trí khác; diff sẽ hiện các period được thêm/bỏ, không tự ghép một báo cáo đa trang.

Diff trả cờ `request_changed`, `producer_changed`, `source_changed`, `facts_changed`, `result_changed`; các field change dùng JSON Pointer với `before`, `after` và `change: added|removed|changed`. Giá trị thiếu/null không bị đổi thành zero. Có `total_changes`, `truncated` và giới hạn 1..200 field changes mỗi lần gọi. Đổi cutoff VN mà giữ nguyên nguồn/facts không tự biến thành `source_changed`.

`affected_metrics` hiện chỉ theo dependency đã ghi trong kết quả VN ratios: đổi input hoặc bằng chứng của input sẽ chỉ ra metric phụ thuộc; metric như cash conversion cycle được truyền ảnh hưởng qua DSO/DIO/DPO. Trường `changed_inputs` chỉ chứa leaf input liên quan. Đây là cờ hỗ trợ người review, không phải claim graph cho bài viết, tự viết lại nhận định, hoặc chứng nhận các nhận định khác vẫn đúng. Comparables, DCF, reverse DCF và Crypto basis có diff field/hash nhưng chưa có dependency invalidation cho các claim diễn giải; `affected_metrics: []` của chúng không có nghĩa mọi nhận định không bị ảnh hưởng.

Scope Crypto hiện chỉ ràng buộc base/quote, cho phép thay đổi venue và tập hợp contracts để đối chiếu. Các row trong result được sắp theo expiry/venue/instrument; thêm/bỏ row có thể làm JSON Pointer theo array index dịch chuyển. Diff chưa ghép row theo semantic identity; cần kiểm contract ID và source reference khi đọc thay đổi.

## Review và giới hạn dữ liệu

Request review:

```json
{
  "decision": "acknowledged",
  "note": "Đã đọc kết quả; nguồn tài liệu vẫn cần đối chiếu độc lập.",
  "reviewer": "Người kiểm tra cục bộ"
}
```

Revision mới có `review_state: pending_review`. Event chỉ nhận `acknowledged` hoặc `changes_requested`; trạng thái hiển thị lấy event mới nhất theo thứ tự append. `reviewer_identity` luôn là `self_reported_operator_label`; review của một revision không được kế thừa thành review của child. `verification_status` vẫn là `user_supplied_unverified` sau mọi quyết định. Không có quyết định `verified`, `approved_for_trading` hoặc thao tác nâng quyền nguồn.

Các bound hiện tại: request tối đa 64.000 byte UTF-8 canonical, result 64.000 byte, manifest 128.000 byte; listing 1..100 dòng và offset 0..100.000; diff 1..200 field changes; note 1..2.000 ký tự, reviewer 1..120 ký tự, tối đa 1.000 review events cho một revision. Bound của engine gốc vẫn áp dụng, gồm paging và số peer/forecast/evidence cho từng loại. Vượt bound sẽ báo lỗi, không cắt âm thầm thành một kết quả đầy đủ.

## Lỗi lưu, backup và rollback

Một ý định save mới được nhận chạy engine trước khi ghi revision. Nếu engine thất bại, store ghi safe terminal error nếu có thể; bản trước giữ nguyên ID, nội dung và thời gian. Nếu process chết sau admission hoặc không xác nhận được completion, attempt vẫn `in_flight_unknown`. Lỗi schema/hash/scope/clock không được xử lý bằng cách sửa bản trước hoặc tạo số liệu thay thế. Refresh state là phép chiếu từ lịch sử attempt, không sửa last-good revision thành nội dung mới.

Mất kết nối, timeout hoặc đóng trang trong lúc write không chứng minh transaction chưa commit. Đọc attempt theo key để phân biệt success/failed/unknown. Gửi lại có chủ đích cùng key/body không tái thực thi; tạo key mới hoặc không dùng key là một ý định khác và có thể tạo thêm revision. Review chưa có key nên vẫn cần kiểm tra review history trước khi gửi lại. Không dùng abort phía trình duyệt như bằng chứng rollback hoặc tự retry write.

Backup SQLite nhất quán **trước write đầu tiên bằng schema-2 writer** hoặc trước bảo trì: dùng SQLite backup khi database đang mở, hoặc dừng writer rồi sao chép database. Không chụp một file đang được ghi và bỏ qua journal liên quan. Rollback chức năng bằng ngừng save/review, khôi phục source theo snapshot và giữ nguyên database hiện tại; mã schema-1-only có thể phải bỏ qua kho schema 2 đó. Không xóa runtime/revision/review/attempt, không hạ `user_version`, đổi kind hoặc sửa hash/timestamp để vượt kiểm tra. Database tách riêng nên không cần chuyển schema sessions/Forex/Crypto. Chỉ restore backup khi đã xác định đầy đủ các ghi mới hơn sẽ bị bỏ, không ghi đè storage đang có nghiên cứu của người dùng.

## Bằng chứng kiểm thử và phần còn mở

[Domain revisions](../agent/tests/test_research_artifact_revisions.py) kiểm actual fixture execution, hashes, immutable triggers, clock/scope/null và ratio dependencies. [Attempt tests](../agent/tests/test_research_refresh_attempts.py) kiểm replay/concurrency, producer/engine failures, last good, thứ tự admission, interrupted/uncertain completion, clock và migration 1 → 2 không sửa revision cũ. [Artifact HTTP tests](../agent/tests/test_research_artifact_routes.py) kiểm auth/cross-site và safe errors; [iteration-8 HTTP tests](../agent/tests/test_research_iteration8_routes.py) kiểm receipts, conflict/status/auth/no-create, report UTF-8/headers/no-write và 413/422. [Iteration-7 HTTP tests](../agent/tests/test_research_iteration7_routes.py) tiếp tục kiểm actual builders cho năm kind, parent/diff/review, unsolved/rejected outputs và main MCP Crypto basis. Report có [renderer tests](../agent/tests/test_research_report_export.py), Web có [attempt tests](../frontend/src/components/research/__tests__/ResearchAttemptHistory.test.tsx) và [export tests](../frontend/src/components/research/__tests__/ResearchReportExport.test.tsx).

Các kiểm thử dùng fixture và database tạm, không xác minh issuer/tài liệu thật hoặc broker/model. Phần local đã có attempt/stale projection, save idempotency và Markdown định lượng; phần vẫn mở gồm dữ liệu mới từ nguồn thật, phục hồi attempt gián đoạn, review idempotency, AI narrative/PDF, narrative claim graph/selective regeneration, danh tính người review/role separation, entitlement/ACL theo nguồn, chữ ký bằng chứng, publishing/delivery và bộ môi trường tái lập đầy đủ. Nghiệm thu PLATFORM-033, PLATFORM-064, VN-128 và VN-130 tiếp tục mở; export snapshot không hoàn thành phương pháp phân tích cơ bản/kỹ thuật và kế hoạch lệnh Việt Nam.
