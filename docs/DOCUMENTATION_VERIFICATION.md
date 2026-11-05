# Biên bản viết lại và kiểm tra tài liệu

**Ngày:** 04/11/2026, Asia/Saigon. **Workspace:** `D:\Vibe-Trading-0.1.18`. **Version trong cấu hình:** `0.1.18`. Không có `.git` trong thư mục làm việc; không có commit/diff Git để xác nhận.

## 1. Kết quả bàn giao

| Nhóm | Thay đổi |
| --- | --- |
| README chính | Viết lại phần giới thiệu/hướng dẫn bằng tiếng Việt, rút lịch sử tin tức khỏi luồng đọc, thêm ma trận current/proposed, quick start, các domain và link tài liệu sâu |
| Inventory README | Giữ các danh mục source, numeric badges, CLI table, MCP tool list và generated broker matrix đang có test bảo vệ; sửa claim quá rộng về availability, Tushare, MCP và halt |
| README ngôn ngữ khác | Chỉ đồng bộ một dòng số lượng agent tools từ 113 thành 114 trong mỗi bản; không dịch lại toàn bộ nội dung |
| Tài liệu mới | Index, source baseline, kiến trúc, data/evidence contracts, Vietnam, Forex/XAUUSD, Crypto, roadmap và biên bản này |
| Tài liệu Forex cũ | Thêm cập nhật source ngày 04/11 và liên kết thiết kế mới; giữ bằng chứng runtime cũ với nhãn thời điểm lịch sử |

Không sửa source Python/TypeScript, schema runtime, credentials, dependency, chính sách CONTRIBUTING/SECURITY hoặc cấu hình broker. Không commit, publish package hay deploy website/wiki.

## 2. Backup trước khi ghi đè

Backup nằm tại `.codex-backups/2026-11-04-multi-market-docs/`, giữ tên/đường dẫn của file gốc:

- `README.md` và sáu bản `README_{zh,ja,ko,ar,es,id}.md`.
- `docs/FOREX_MCP_IMPLEMENTATION.md`.
- `docs/FOREX_LIVE_CANDLES.md`.
- `docs/FOREX_AGENTIC_RESEARCH.md`.
- `docs/EXNESS_FOREX_MCP_INTEGRATION_RESEARCH.md`.

README chính và bốn tài liệu Forex đã được so SHA256 trước sửa. Sáu bản dịch được copy nguyên bản trước khi đổi count; đối chiếu sau sửa kiểm tra nội dung chỉ khác số đếm trên dòng tools. Manifest hash và kết quả kiểm tra cấu trúc được lưu cạnh backup; `README_OVERLAY.md` là bản nội dung mới dùng để sắp README, không phải một bản gốc bổ sung.

Khôi phục một tài liệu bằng cách copy đúng backup về file tương ứng sau khi kiểm tra target. Không xóa cả thư mục runtime hoặc chạy cleanup để rollback tài liệu. Những file mới không có bản gốc; giữ riêng nếu muốn tiếp tục nghiên cứu.

## 3. Kiểm tra bằng test hiện có

Lệnh:

```powershell
.\.venv\Scripts\python.exe -m pytest agent/tests/test_readme_counts.py agent/tests/test_capability_matrix.py -q --tb=short --disable-warnings
```

| Thời điểm | Kết quả | Diễn giải |
| --- | --- | --- |
| Trước sửa README | 114 passed, 7 failed, 9 warnings | Cả bảy README ghi 113 agent tools; registry sạch trả 114 |
| Sau rewrite và đồng bộ count | 121 passed, 9 warnings | Kiểm tra inventory, lệnh, nguồn, badge và generated capability matrix đạt |

Trong sandbox, launcher venv ban đầu báo `uv trampoline failed to spawn Python child process` / `permission denied`. Cùng lệnh chạy được với quyền thực thi ngoài sandbox đã được cấp. Không sửa Python/venv hoặc tải dependency để vượt lỗi. Bộ test có sandbox runtime trong `agent/tests/conftest.py`; đây không phải kiểm tra broker hay live account.

Warnings ghi nhận từ pytest-asyncio và NumPy Timedelta trong dependency/loader hiện có. Đợt tài liệu không sửa các warning này. Kết quả pass không có nghĩa pipeline thị trường hoặc tài khoản thật đã đạt nghiệm thu.

## 4. Kiểm tra nội dung và cấu trúc

Đã đối chiếu source theo các bề mặt AgentLoop/Swarm, loader/engine, Strategy Store/quantlib, Forex native context/risk và connector gates. Rà soát chéo đã bổ sung rõ tick theo vùng giá HOSE, funding cadence/coarse bars, same-market currency gap và ý nghĩa halt/resume.

Kiểm tra cấu trúc đã đạt: 14 tài liệu chính/chuyên đề có UTF-8 hợp lệ, code fences cân bằng và 254 liên kết file/anchor nội bộ tồn tại; README giữ đúng một cặp marker generated; sáu bản dịch chỉ đổi count. Không có lỗi trong lần kiểm tra cuối.

Lệnh kiểm tra cấu trúc:

```powershell
node .codex-backups/2026-11-04-multi-market-docs/check-docs.cjs
```

Kết quả máy đọc nằm trong `.codex-backups/2026-11-04-multi-market-docs/documentation-checks.json`; SHA256 trước/sau của 20 tài liệu nằm trong `document-manifest.json` cùng thư mục. Script có self-check cho việc bỏ qua code fences và xử lý anchor trùng. Con số 135 lượt liên kết ngoài được thống kê, không phải 135 URL đã kiểm tra truy cập tự động.

Nguồn nghiên cứu web dùng tài liệu chính thức: HOSE, VSDC, HNX, Cục Thống kê, MetaQuotes, OANDA, Binance, Ethereum, W3C, SQLite, PostgreSQL và OWASP. Link trực tiếp được đặt ở các tài liệu domain/contract/architecture. Nguồn không truy cập được hoặc quy định chưa xác minh đầy đủ được ghi giới hạn; không dùng ảnh tham khảo, favicon hoặc snippet làm bằng chứng đã triển khai.

## 5. Chưa kiểm tra trong đợt này

- Không chạy toàn bộ backend suite hoặc build/frontend tests vì không thay runtime/UI.
- Không chạy research gọi model, feed streaming hoặc đánh giá lợi nhuận chiến lược.
- Không attach terminal, đăng nhập broker/API, đọc tài khoản hay gửi/hủy/đóng lệnh.
- Không kiểm chứng toàn bộ market rules/thuế/pháp lý hiện hành, vendor entitlement, license hoặc độ phủ dữ liệu.
- Không audit lại `CONTEXT_MEMORY_TOKEN_AUDIT.md`, sáu bản dịch ngoài count, hoặc toàn bộ nội dung wiki.

Các milestone và contract mới vẫn là thiết kế. Đọc [roadmap](IMPLEMENTATION_ROADMAP.md) để triển khai từng slice, rồi tạo bằng chứng runtime riêng trước khi đổi nhãn capability.

## 6. Nghiên cứu chuyên sâu lần hai: hoàn tất 05/11/2026

Các mục 1–5 ghi lịch sử đợt tài liệu 04/11; source sau đó đã thay đổi theo yêu cầu code. Đợt nghiên cứu tiếp theo dùng [master plan người dùng cung cấp](../VIBE_TRADING_MULTI_MARKET_MASTER_PLAN_V1.md), giữ đúng 265 ID/tên gốc và bổ sung catalog có source seam, trạng thái và acceptance riêng: 64 VN, 62 Forex, 72 Crypto, 67 Core; 54 Scenario; 10 phase; 16 quyết định PENDING. [Điểm vào catalog](specs/README.md).

Trước sửa đã snapshot master và các tài liệu liên quan tại `.codex-backups/2026-11-04-deep-research-pass-2/`. `reconcile-plan.cjs` kiểm tra số lượng, thứ tự, ID và tên với master gốc, thêm source/gate annotation rồi ghi `specification-index.json`. Script không tự duyệt quyết định, không thực thi những lệnh minh họa trong master.

Đã tra thêm tài liệu chính thức SSI MCP/FastConnect, MetaQuotes/OANDA/Exness, OKX/Binance/CCXT/Ethereum, scikit-learn, SQLite và OpenTelemetry. Các cập nhật đặc biệt gồm SSI account/OAuth và ngữ nghĩa giá trị0 không áp dụng; OKX checksum theo channel/version; raw/reference VN; funding/bar alignment; memory BM25/FTS khác vector retrieval; walk-forward slicing khác retraining.

Baseline source tests dùng fixture/mock:

| Nhóm | Kết quả | Artifact |
| --- | --- | --- |
| Engines/currency/funding/orderbook/Forex/context/Swarm/governance | 245 passed | `source-contract-tests.xml` trong backup pass2 |
| Validation/deferred schemas/paging/memory/usage | 229 passed, 1 skipped | `core-quant-tests.xml` trong backup pass2 |

Skip của nhóm thứ hai là test POSIX flock trên Windows. Không cộng những nhóm baseline này vào số test của implementation; không đánh dấu 54 Scenario là đã đạt.

## 7. Đợt code local 05/11/2026

Theo yêu cầu tiếp theo, đã sửa ba slice P0; xem [phạm vi và cách dùng](IMPLEMENTATION_STATUS_2026-11-05.md). Source gốc được snapshot tại `.codex-backups/2026-11-05-implementation/`. Không có credential hoặc tài khoản nào được cấp quyền trong quá trình này.

Regression mở rộng gồm 28 file test engines, local/cache, run cards, Crypto, Forex và README/capability: **728 passed, 3 skipped**, artifact `final-regression.xml` tại thư mục implementation. Sau điều chỉnh tương thích default caliber, chạy lại nhóm local/cache/run-card liên quan đạt **138 passed, 3 skipped** (`local-final-tests.xml`); đây là nhóm trùng phạm vi, không cộng thêm vào 728. Ba skip do thiếu optional pandas Parquet engine cho đường đọc local Parquet; cached bars và CSV paths vẫn được kiểm bằng fixture. Các warning/deprecation được ghi nhận; không sửa toàn bộ dependency/toolchain ngoài phạm vi.

Các regression mới đã tái hiện lỗi trước sửa: funding mất settlement ngoài grid, local `pre_close` bị bỏ, warning runtime không tới run card và Forex quote assessment sai cấu trúc trả bare exception. Tests sau sửa kiểm cả đường data/caller/output, không chỉ mirror helper. Có lệnh thử ban đầu trỏ tới `test_local_loader_resample.py` không tồn tại; lệnh đó không chạy test và đã được sửa về đúng file, không tính là thất bại nghiệp vụ.

Không có Ruff trong venv hiện tại nên chưa chạy lint bằng Ruff; không cài dependency chỉ để che giới hạn này. Python modules thay đổi đã được import/chạy qua pytest. Không sửa frontend nên không chạy build/UI suite. Broker, network feed thật, source entitlements, live execution, package release và production deployment chưa được kiểm tra.

Kiểm tra tài liệu cuối gồm 23 file Markdown, 1.034 liên kết file/anchor nội bộ và 8 file source/test thay đổi; đối chiếu canonical 265/54/10/16 và whitespace dòng mới. Kết quả và SHA256 trước/sau lưu trong `deep-research-checks.json` / `deep-research-manifest.json` tại backup pass2. 193 lượt liên kết ngoài chỉ là thống kê, không phải kiểm tra truy cập tự động toàn bộ.
