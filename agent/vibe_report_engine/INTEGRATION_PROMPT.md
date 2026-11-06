# Prompt cho Claude Code / Codex / AI Coding Agent

Bạn là Senior Python/FastAPI Engineer + Financial Research Systems Architect + Document Rendering Engineer. Hãy tích hợp mô-đun Vibe Report Engine (bộ mã được cung cấp trong thư mục này) vào **repository thực tế** `qtu11/vibe-trading-vn` theo các yêu cầu sau. ĐỌC MÃ NGUỒN TRƯỚC KHI SỬA, không dựa vào README như hợp đồng runtime duy nhất.

## Outcome
Người dùng nhập chat: “Phân tích sâu mã FPT HOSE, chỉ dùng dữ liệu có nguồn tại ngày T, xuất báo cáo DOCX + PDF định dạng Vibe-Trading”. Hệ thống phải tạo artefact sau một lần chạy research, hiển thị trong run/session và cho người dùng có quyền tải về. Quy trình phải tái sử dụng AgentLoop, Swarm, run artifacts, authenticated FastAPI và MCP tool registry hiện có; không tạo orchestration hoặc authentication stack trùng lặp.

## Bước bắt buộc
1. Khảo sát chi tiết `agent/api_server.py`, `agent/src/api`, `agent/src/agent/tools.py`, registry auto-discovery, current run store/artifact service, MCP registration, swarm orchestration, frontend RunDetail/chat và test hiện tại. Ghi rõ API contract liên quan, path, chính sách xác thực và nơi lưu trữ trước khi chỉnh sửa.
2. Xây `reporting` module gồm contracts Pydantic, financial provenance adapter, business rule validators, brand tokens, template renderer, PDF worker và artifact registrator; giữ tương thích Python 3.11+ và các conventions của repo. Có thể reuse `schema.py`, `brand.py`, `renderer.py` từ starter này nhưng refactor import sao cho phù hợp thực tế.
3. Thêm agent tool `export_research_report` với input là `ResearchReport` JSON có version; phải gọi deterministic renderer, không gọi LLM để dựng layout, không cho tool truy cập path do user/model cung cấp. Tích hợp với MCP **chỉ theo interface thực tế đã đọc**; thêm tool schema/authorization và tests hợp lệ.
4. Khi user yêu cầu xuất báo cáo, phân tích dữ liệu qua tool hiện có. Research JSON phải nêu asset class/venue/symbol/currency, price basis, cutoff UTC/Asia-Ho_Chi_Minh, model assumptions, nguồn as-of/PIT, original link, retrieved_at, evidence_id, snapshot revision, units, missing data, risk warnings và disclaimer. AI chỉ viết narrative; tính ratios, DCF/P/E upside, EPS, YoY bằng Python deterministic. Chênh lệch giá được tính bằng đơn vị nhất quán; phát hiện dùng VND so với nghìn VND.
5. Đối chiếu schema với immutable evidence store: model tự gắn `verified` không đủ. Chỉ phát hành rating/target price nếu nguồn đủ, valuation output có bảng giả định, source reference và reviewer gate. Không tự biến model recommendation thành hành động đặt lệnh.
6. Dựng template Vibe-Trading chính thức: dùng logo/mascot nằm trong assets của repo (không screenshot), bảng màu dark navy #071827, teal #13C6B0, green #17B978, font sans dễ đọc. DOCX cần editable thật: heading styles, metrics, chart image, table, citation/source register, page numbers, footers, risk disclosure. PDF được tạo từ cùng DOCX bằng LibreOffice with isolated profile. Lên template riêng VN_EQUITY, FOREX/XAUUSD, CRYPTO; phần Forex có broker, symbol digits, spread, slippage, timezone, cost assumptions; Crypto có venue, spot/perp, funding, liquidity, exchange risk.
7. Export là job có trạng thái queued/running/succeeded/failed, idempotency key theo run+schema+format+template version, timeout và retries phù hợp. Lưu private artifact trong existing artifact store / object storage, kiểm soát user/tenant, signed URL TTL, không static mount công khai, dọn tài liệu sau TTL; log hash của snapshot và schema version. Kiểm soát tải trọng, số trang, hình/chart, độ dài mô tả và chi phí tính toán.
8. Frontend React: thao tác "Xuất báo cáo" → chọn DOCX/PDF, trạng thái tiến độ, nút tải, preview PDF, phiên bản báo cáo; bắt lỗi dữ liệu thiếu và hiển thị điều kiện phát hành. Không dựng image screenshot thay cho DOCX có thể sửa.
9. Tests: schema missing source; stale price; source revision; dividend/split price basis; VND/nghìn VND; unsupported instrument; negative/signed metrics; future quotes; NaN/inf; malicious paths; concurrent DOCX-to-PDF; auth/tenant isolation; PDF/DOCX typography; Unicode Vietnamese. Generate QA PDF pages and inspect clipping, table spill, page orphans, sources, footer, units.
10. Output: code changes, migration plan (nếu cần), architecture flow, các chức năng đã chạy thực, test commands và outputs, known limitations. Không tuyên bố hoàn thành nếu chỉ có stub/pseudocode.

## Acceptance test
- Một research run có snapshot thật hoặc được gắn nhãn demo; export đầy đủ hoặc trả lỗi rõ ràng.
- Không tự xuất khuyến nghị mua/bán nếu thiếu valuation và provenance đã xác thực.
- Cùng input snapshot + template version tạo DOCX và PDF nhất quán; tên file gồm symbol/as_of/run metadata.
- Ảnh/logo đúng bản quyền thương hiệu, dữ liệu và nguồn rõ ràng; có footer/disclaimer.
- Không phát sinh order/trade trong workflow report.
- Bắt buộc chạy test và render visual QA cho một mẫu thực tế được người dùng cho phép và một mẫu demo.

Hãy triển khai, không chỉ viết kế hoạch. Bất kỳ điểm nào chưa phù hợp source thực phải giải thích và thích ứng theo mã đang có.
