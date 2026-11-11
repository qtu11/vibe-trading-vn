# Luồng đọc nguồn, phân tích và xuất nghiên cứu — 2026-11-11

Phần này mô tả code đang triển khai, thay cho các giới hạn về cắt nguồn và review tùy chọn trong audit ngày 10/11. Đây là thay đổi hệ thống AI; không phải một báo cáo tài chính được viết thủ công để thay kết quả của ứng dụng.

## Từ yêu cầu đến kết quả

1. `SessionService` giữ quyền chạy phiên và checkpoint. `ContextBuilder` dựng ngữ cảnh, còn `AgentLoop` ghi nhận định dạng xuất được yêu cầu bằng tên DOCX/PDF/PPTX. URL đầu vào chứa `.pdf` không tự trở thành yêu cầu xuất PDF.
2. `research_workflow.requires_research_review` nhận diện yêu cầu nghiên cứu chuyên sâu hoặc phân tích/báo cáo doanh nghiệp, cổ phiếu. Những yêu cầu này tự gọi preset `deep_research_review` trước model tổng hợp. Tra giá, giải thích thuật ngữ, tóm tắt một tài liệu hay chuyển định dạng đơn giản không tự chạy cả nhóm. Quy tắc nhận diện có phạm vi giới hạn, chưa hiểu được mọi cách diễn đạt hoặc chỉ dẫn phủ định.
3. Bốn vai chạy theo DAG nối tiếp: `source_analyst → domain_analyst → critical_reviewer → research_editor`. Mỗi vai phải thực sự gọi model và đọc dữ liệu. Chỉ viết file, tạo bản nháp, tìm link, đọc RSS/snippet hay tự tính một con số không chứng minh đã đọc bằng chứng. Đọc lại bản sao snippet cũng không đổi điều kiện này. Lượt đọc phải qua công cụ được hệ thống xác định là chỉ đọc hoặc bản sao bằng chứng được kiểm bytes; chỉ `readOnlyHint` tự khai báo của MCP không đủ. Các vai có thể dùng cùng model/provider đã cấu hình.
4. `SwarmObservations` lấy kết quả công cụ thực tế đưa vào ledger cha dưới ID lời gọi riêng. Các worker dùng chung `[S#]`; worker tiếp theo nhận đường dẫn tới bản sao bất biến trong sandbox của mình. Model tổng hợp nhận lại bảng `[S#] → URL`, coverage và đường dẫn bằng chứng trong sandbox cha. Báo cáo do model viết và URL model tự nêu không được nâng thành nguồn thu thập.
5. Runtime ghi receipt trạng thái từng task, số lượt model và lượt đọc dữ liệu. Lượt đọc mới phải có lượt model xử lý tiếp theo; hết vòng ngay sau khi đọc không được ghi hoàn tất bằng văn bản cũ. `AgentLoop` chỉ gọi model tổng hợp sau khi đủ bốn vai thành công. Hết một cửa sổ chờ thì chờ tiếp đúng `run_id`, tối đa ba cửa sổ theo `SWARM_TIMEOUT`; nếu vẫn chưa xong, dừng run thuộc yêu cầu đó và trả `research_workflow_incomplete`. Không khởi tạo thêm một đội từ đoạn “tiếp tục”. Cancel và token budget được chuyển tới đội đang chạy.
6. Chat và `ExportResearchReportTool` dùng chung kiểm tra review và nguồn được trích. Nghiên cứu chuyên sâu phải có trích dẫn nguồn đã quan sát. Nguồn mới chỉ xuất hiện trong kết quả tìm kiếm, nguồn chưa đọc hết hoặc snapshot bị sửa không đủ điều kiện. AI phải đọc tiếp, lấy nguồn thay thế hoặc bỏ luận điểm phụ thuộc; không được tự đặt cờ `verified`/`complete`.
7. Export tiếp tục qua schema, nguồn, ngày, đơn vị, phạm vi dữ liệu và phép tính. Sau render, receipt phải khớp file đã đăng ký và định dạng được yêu cầu. Thiếu file trả `report_delivery_incomplete` cùng những liên kết đã tạo thành công. Trạng thái nghiên cứu và nguồn được giữ trên metadata reply để còn xem sau khi tải lại phiên.

## Đọc nguồn và coverage

`read_url` dùng transport kiểm tra địa chỉ/DNS và redirect. MIME cùng chữ ký bytes nhận diện PDF, kể cả URL download không có đuôi `.pdf`. PDF được đọc native bằng bộ đọc tài liệu; trang scan thử OCR khi có. Thiếu OCR, PDF hỏng, trang bị bỏ hoặc lấy một phần trang được thể hiện trong coverage và giữ bytes đã nhận để kiểm tra lại.

HTML được trích nội dung và bảng. Trang Next.js/JavaScript có vỏ giao diện nhưng thiếu nội dung sẽ thử reader render Jina; lỗi render không được ghi thành đọc đầy đủ. Dịch vụ render nhận URL công khai của nguồn. Trang yêu cầu đăng nhập, thao tác, dữ liệu ẩn sau API riêng hoặc chống bot có thể vẫn chưa đọc được.

`concurrent_scraper` lưu bytes gốc và toàn văn **trước** BM25/rút gọn. Tóm tắt và excerpt chỉ phục vụ định hướng. Kết quả hỗn hợp giữ lỗi từng URL và trạng thái batch thiếu một phần. Redirect giữ cả URL yêu cầu và URL cuối. Tài liệu local dùng `doc://` kèm đường dẫn đầy đủ để hai file cùng tên không nhập thành một nguồn.

`source_documents` lưu snapshot theo SHA trong `run/artifacts/sources`. Văn bản trích xuất chuẩn hóa xuống dòng và trung hòa token điều khiển chat; bytes gốc giữ nguyên. Các trường chính:

| Trường | Ý nghĩa |
| --- | --- |
| `extraction_complete` | Đã trích đủ phạm vi tài liệu nhận được, không có phần đã biết bị bỏ/lỗi |
| `text_delivery_complete` | Các khoảng ký tự công cụ trả về đã phủ toàn văn trích xuất |
| `complete` | Cả hai điều kiện trên đều đúng |
| `next_offset` | Vị trí đọc tiếp, không cần tải lại URL |
| `coverage_id`, SHA | Receipt do process tạo, gắn snapshot với trạng thái đọc thực tế |
| `skipped_pages`, `unread_pages` | Phần PDF chưa được đọc/trích xuất đầy đủ |

Reader tính dung lượng cả JSON và cảnh báo trước khi ghi nhận đoạn đã trả. Đọc lại đoạn đầu không được tính thành đọc hết. Worker đọc bản sao văn bản được kiểm bytes trước khi cộng coverage và đưa số liệu mới vào ledger; đoạn cuối ngắn hơn đoạn trước vẫn phải được gộp bằng chứng.

Receipt coverage giữ trong process. Sau restart, mất tracker hoặc snapshot thay đổi thì kiểm tra đóng theo hướng chưa hoàn tất; file/manifest còn trên đĩa không tự khôi phục niềm tin. `run_id` resume chỉ được công cụ chấp nhận khi thuộc đúng instance và ledger cha; chưa hỗ trợ khôi phục đội đang chạy qua lần restart hoặc sang một yêu cầu khác.

## Kiểm chứng và giới hạn

Các kiểm thử dùng công cụ/runtime thực, thay provider/network bằng fixture ở ranh giới: đọc từng đoạn; nguồn dài; PDF scan/hỏng; Next.js shell; redirect; file cùng tên; SHA/coverage giả; phần cuối số liệu; bàn giao nguồn giữa bốn vai; resume đúng một run; chặn trả kết quả/export sớm; phép tính và giao file. Đã smoke đọc trực tiếp PDF TCB người dùng đưa: 2 trang, 0 trang bỏ, 7.413 ký tự chuẩn hóa qua 2 đoạn, coverage đầy đủ.

Lượt hồi quy cuối trên 90 file kiểm thử liên quan: **985 passed, 7 skipped, 0 failed**; 7 ca symlink bỏ qua do thiếu quyền hỗ trợ trên Windows. Ruff và `git diff --check` sạch. Receipt JUnit: `output/test-results/research-pipeline-20261111.xml`. Đây là tập kiểm thử theo phạm vi thay đổi, không phải kết quả toàn bộ repository.

Coverage chứng minh văn bản được chuyển qua công cụ vào ngữ cảnh, không chứng minh AI hiểu đúng, mọi bảng được diễn giải đúng, hay đã đọc tất cả tab/liên kết của một website. Giới hạn kích thước, thời gian, OCR và context vẫn tồn tại. Số liệu có mặt trong nguồn chưa chứng minh đúng kỳ hoặc đúng ý nghĩa kế toán. Chưa nghiệm thu LLM/provider thật, Next.js tương tác thật hoặc bản desktop cài đặt; không phải chứng nhận CFA hay bảo đảm hệ thống hoàn hảo.

## Các điểm code chính

- `agent/src/agent/research_workflow.py`, `agent/src/agent/loop.py`: nhận diện yêu cầu, review bắt buộc và kiểm trước trả kết quả.
- `agent/src/swarm/presets/deep_research_review.yaml`: vai, thứ tự, công cụ và yêu cầu phương pháp.
- `agent/src/swarm/observations.py`, `runtime.py`, `worker.py`: bằng chứng thực tế, truyền context qua thread và receipt.
- `agent/src/tools/source_documents.py`, `web_reader_tool.py`, `doc_reader_tool.py`: snapshots và đọc theo offset.
- `agent/src/tools/parallel_web_tools.py`, `scraper/reader_fallback.py`: đọc song song, PDF và render có giới hạn.
- `agent/src/reporting/tool.py`, `agent/src/agent/write_targets.py`: kiểm trước render và giao định dạng/file thực tế.
