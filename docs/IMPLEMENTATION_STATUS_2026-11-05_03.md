# Triển khai đợt 3: các luồng nghiên cứu và tracker đầy đủ

Ngày **05/11/2026**, checkout hiện tại **`D:/Vibe-Trading`**, version `0.1.18`. Thư mục đã chuyển từ `D:/Vibe-Trading-0.1.18`; đầu lượt này Git `main` sạch. Những sửa README/repository trước khi bắt đầu được giữ. Không commit, publish hoặc deploy trong đợt này.

## Code và callers đã nối

| Luồng | Đầu ra thực tế | Source/test |
| --- | --- | --- |
| VN financial research | Tool registry + main MCP `vietnam_research`: source snapshot một lần, chọn scope/cutoff, chuẩn hóa VND, quý từ lũy kế, balance/CF/working-capital metrics có evidence; missing/incompatible giữ unknown | [tool](../agent/src/tools/vietnam_research_tool.py), [tests](../agent/tests/test_vietnam_research.py) |
| DCF bridge | `quantlib_call` dựng kiểu Assumption cố định từ JSON rồi chạy engine DCF hiện có; model/preset caller được nối thay claim không có engine | [bridge](../agent/src/tools/quantlib_tool.py), [DCF/MCP tests](../agent/tests/test_dcf_tool_bridge.py), [preset](../agent/src/swarm/presets/fundamental_research_team.yaml) |
| Forex research | Shared typed request → readonly API/Forex MCP → train-only parameter refit/purged fold/OOS/trial outcomes + hashes; bar-open/label availability tách rõ | [evaluator](../agent/src/trading/forex/walk_forward.py), [tests](../agent/tests/test_forex_walk_forward.py) |
| Crypto derivatives | Registry/main MCP public Binance linear-perp OI/funding, units/observed coverage/hash/type/historical-mark cash; sampled display có nhãn | [tool](../agent/src/tools/crypto_derivatives_tool.py), [tests](../agent/tests/test_crypto_derivatives_tool.py) |
| DAG | Một gate dùng chung runtime/inspect; validate trước persistence/reaper/thread, giữ transitive context hợp lệ | [validator](../agent/src/swarm/task_store.py), [tests](../agent/tests/test_swarm_dag_validation.py) |
| Requirement tracking | Đủ265 canonical IDs/titles, source baseline riêng, các local deliveries và acceptance chưa đủ; không dùng số test làm % hoàn thành | [tracker](IMPLEMENTATION_TRACKER.md), [generator](../scripts/build_implementation_tracker.py) |

[Cách chạy và fixture tổng hợp](MULTI_MARKET_RESEARCH_USAGE.md). Inventory sau thay đổi: **116 keyless agent tools /84 main MCP tools**; Forex stdio riêng **8 readonly /11 khi opt-in execution**, không cộng hai MCP surface thành một count. Không thêm dependencies.

## Phần chưa hoàn tất

Tracker hiện có **26 ID được bổ sung một phần**, **239 ID theo baseline chưa nghiệm thu lại**. Đây không phải tuyên bố 239 tính năng hoàn toàn chưa có code, cũng không phải 26 đặc tả đã hoàn tất. Từng gate đầy đủ nằm trong tracker/catalog.

VN vẫn cần collection/parser/source verification/immutable history/taxonomy ngành và report AI có review; các phép tính không tự cấp tính xác thực cho dữ liệu local. Forex chưa có calibrated broker costs, tick/SL/TP/swap parity hoặc persistent experiment registry. Crypto chưa có complete archive/PIT joins, cash-spot/inverse hoặc full funding ledger. Platform chưa hoàn thành long-term RAG, token budgets và toàn bộ reliability/security/tenant scope. Chưa thêm giao diện mới hoặc kiểm nghiệm model/broker thật.

## Kiểm chứng

Các lượt scoped đã có bằng chứng JUnit trong `.codex-backups/2026-11-05-implementation-3/`: Forex84 passed (sau đó26 focused cho timing metadata), Crypto107 passed, DAG162 passed/3 deselected, root tool/preset/inventory319 passed/1 skipped. Các lượt có test trùng, không cộng thành tổng riêng.

Regression tích hợp cuối trên **44 file test: 1137 passed, 3 skipped, 0 failed**, khoảng68 giây,63 deprecation warnings. [Danh sách test](../.codex-backups/2026-11-05-implementation-3/regression-tests.json), [JUnit](../.codex-backups/2026-11-05-implementation-3/final-regression.xml), [lệnh/phạm vi kiểm chứng](../.codex-backups/2026-11-05-implementation-3/verification.json). Ba skip: optional `statsmodels` chưa cài và2 case symlink không khả dụng trên máy Windows này. Các ví dụ VN/DCF/Forex đã đi qua caller thật bằng dữ liệu tổng hợp; không có lời gọi model/broker thật.

Lượt tích hợp đầu có2 lỗi test đọc artifact UTF-8 bằng cp1252 và1 lỗi quyền symlink; [JUnit ban đầu](../.codex-backups/2026-11-05-implementation-3/initial-regression.xml) được giữ. Đã sửa `read_text(encoding="utf-8")` và chỉ skip symlink khi setup không khả dụng, giữ nguyên assertion cách ly artifact. Review còn tái hiện được trường hợp precision128 làm A=1e100, L=1e-100, E=1e100 báo residual0 sai; precision320 và regression hiện giữ đúng residual−1e-100, không sửa số để cân đối.

Lượt DAG scoped đầu riêng có3 lỗi `WinError 1314` khi setup symlink trong `test_swarm_replay.py`; XML lỗi được giữ. Lượt scoped supported bỏ đúng3 case đó. Chưa chạy full repository suite, frontend build, Ruff hoặc provider thật. [Manifest/diff hashes](../.codex-backups/2026-11-05-implementation-3/manifest.json) và [kiểm tra tài liệu/tracker](../.codex-backups/2026-11-05-implementation-3/checks.json) ghi phạm vi hiện tại; không có giả định mọi URL ngoài đã được fetch lại.

## Rollback

Snapshot trước sửa ở `.codex-backups/2026-11-05-implementation-3/` theo nhóm `root`, `forex`, `crypto`, `platform`; Git diff và manifest ghi file mới/sửa. Hoàn tác source, wrapper, test, preset và inventory liên quan cùng nhau. Tool VN/Crypto mới không ghi dữ liệu người dùng; Forex research không gọi broker. DAG gate có thay đổi tương thích với custom preset: graph sai trước đây chỉ warning nay là lỗi; sửa dependency hoặc hoàn tác cả gate/caller nếu cần đánh giá lại. Giữ mọi datasets, run artifacts, audit và credentials.
