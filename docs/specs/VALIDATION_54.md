# 54 kịch bản kiểm thử chuyên sâu — fixture và oracle

**Ngày:** 04/11/2026. Giữ nguyên ID/tên 54 `Scenario` tại mục 13.1 của [Master Plan V1](../../VIBE_TRADING_MULTI_MARKET_MASTER_PLAN_V1.md). Những mục dưới là acceptance specification, không phải 54 test vừa được chạy thành công.

Các số trong fixture là **dữ liệu tổng hợp dùng kiểm thử**, không phải giá thật, rule hiện hành của broker hoặc bằng chứng lợi nhuận. Tham số market rules lấy từ ruleset có version trước khi chạy; các giá trị nguồn không đủ độ chính xác phải dẫn tới unknown/reject phù hợp.

## 1. Quy tắc thực thi chung

- Golden input/output do người viết oracle tính độc lập với engine; không gọi lại cùng hàm implementation để tạo expected value.
- Clock được inject và đóng băng; không dùng thời điểm máy để quyết định fixture có stale hay không.
- Scope, source, instrument, currency/spec versions và dataset membership được pin trong manifest.
- Broker/model/network được stub cho unit/contract tests. Demo/live validation là nhóm riêng chỉ chạy trong phạm vi operator cấp.
- Mọi case lưu input hash, expected, observed, reason code, attempt, test version và kết quả. Test bị skip/timeout là chưa có evidence đạt.
- Cột coverage ghi **PARTIAL** khi đã thấy test/source liên quan, **GAP** khi thiếu một fixture/end-to-end path đủ cho scenario. Không suy PARTIAL nghĩa là acceptance đã pass.

## 2. Vietnam — 10 tình huống

| ID | Tên giữ nguyên từ master | Fixture và lỗi cần inject | Oracle/tiêu chí đạt cụ thể | Coverage/seam |
| --- | --- | --- | --- | --- |
| `A01` | VN backtest T+2 with weekends | Rule fixture quy định hai business sessions tới thời điểm sellable, buy trước weekend + một holiday | Không tính ngày nghỉ là trading session; sell trước availability bị block; release tại đúng instant của rule | PARTIAL: [Vietnam engine tests](../../agent/tests/test_vietnam_equity_engine.py); cần holiday/sellable-time oracle |
| `A02` | HOSE HNX UPCoM tick ladder | Cùng giá ở sát hai ngưỡng tick, ba venue và hai loại chứng khoán | Đúng tick theo venue/product/version; venue chưa có rule phải unsupported, không mượn HOSE | PARTIAL: HOSE tests hiện có; HNX/UPCoM fixture cần bổ sung |
| `A03` | VN adjusted vs raw price | 100 shares, cash1000, raw price100; tách cổ tức10/share và raw ex-price90, không phí | Trước NAV11000, sau cash2000+inventory9000=11000; adjusted input không cộng cổ tức hai lần | PARTIAL: [corporate action tests](../../agent/tests/test_paper_trade_corporate_actions.py); không coi là VN production coverage |
| `A04` | VN restated EPS | EPS revision1=1000 public t1, revision2=800 public t3; query t2 và t4 | t2 chỉ thấy1000; t4 có800 và lineage; backtest snapshot cũ không bị rewrite | GAP: VN filing/PIT revision adapter cần có |
| `A05` | VN fiscal quarter | Cùng năm/currency/consolidation, Q1 YTD120, Q2 YTD270; thêm fiscal-year mismatch | Q2 standalone150; mismatch không trừ; giữ evidence IDs của hai input và phương pháp | PARTIAL: [financial statements tool](../../agent/src/tools/financial_statements_tool.py); cần fixture VN |
| `A06` | VN bank capital | Dataset ngân hàng có NIM/CASA/NPL nhưng không có EBITDA comparable; một ratio có denominator thiếu | Không coi trường không áp dụng là0; không dùng model công nghiệp mặc định để tính bank fair value | GAP: mapper tài chính VN theo ngành |
| `A07` | VN liquidity cap | Rule participation5%, observed eligible volume100000 shares, proposed6000; missing volume ở biến thể | Cap5000 trước lot rounding; thiếu volume không báo order eligible theo giả định0 hoặc unlimited | PARTIAL: [constraints](../../agent/backtest/constraints.py); cần venue+volume-unit fixture |
| `A08` | VN filing after close | Filing công bố sau phiên t1, decision t1-close; một bản khác date-only | Không dùng filing sau cutoff; date-only áp policy bảo thủ có khai báo, không tự gán09:00 | GAP: native VN publication-time policy |
| `A09` | VN delisted ticker | Universe thời t0 gồm A/B; B delist t2 và biến mất khỏi current endpoint | Backtest t0 vẫn có B; exit/valuation treatment rõ; không loại B để tăng kết quả | GAP: historical universe/security master |
| `A10` | VN rights subscription | 100 shares, quyền1:1 giá50, cash3000; deadline t3, shares unlock t5 | Không tự mua đủ100 quyền khi thiếu tiền; exercised quantity/cash/rights expiry và unlock phân biệt | GAP: rights engine theo VN rules và độc lập oracle |

## 3. Forex/XAUUSD — 16 tình huống

| ID | Tên giữ nguyên từ master | Fixture và lỗi cần inject | Oracle/tiêu chí đạt cụ thể | Coverage/seam |
| --- | --- | --- | --- | --- |
| `B01` | XAU buy on ask | Quote bid2000/ask2000.2, buy rồi exit cùng quote, multiplier100, quantity0.1 | Gross immediate roundtrip=-2 tiền quote trước fee; không buy ở bid hoặc close ở ask | PARTIAL: [MT5 tests](../../agent/tests/test_forex_mt5.py), [Forex engine](../../agent/backtest/engines/forex.py) |
| `B02` | XAU SL and TP same candle | Long có SL99/TP102; bar O100 H103 L98 C101; tick order chưa biết | Trả intrabar-ambiguous hoặc policy bảo thủ công bố; không chọn TP trước để tối đa lãi | GAP: tick replay hoặc explicit OHLC ambiguity oracle |
| `B03` | XAU stale 8 seconds | Clock t; quote source t-8s; configured max_age5s; receive vừa xong | Reject stale dù receipt mới; biến thể max_age10s dùng đúng policy, không hardcode8s mọi broker | PARTIAL: [execution tests](../../agent/tests/test_forex_execution.py), risk freshness |
| `B04` | XAU spread from 100 to 400 | Quote chuẩn hóa point0.01, spread100points rồi400; cap150points | Order được preview không giữ pass khi submit spread400; không lẫn points/pips/price | PARTIAL: [risk.py](../../agent/src/trading/forex/risk.py), [MT5 tests](../../agent/tests/test_forex_mt5.py) |
| `B05` | XAU hedge netting account | Hai connection Hedge/Netting; journal owns ticketA, foreign ticketB | Close nhắm đúng ticket/volume hỗ trợ; không gửi opposite rồi coi đã đóng Hedge; unsupported environment reject | PARTIAL: native Demo owned-close tests; legacy flatten cần fixture riêng |
| `B06` | XAU 0.01 min volume risk | Budget10USD; broker estimated loss/lot2000USD; volume_min0.01, step0.01 | Quantity budget0.005 dưới min nên NO TRADE; không làm tròn lên0.01 để vi phạm budget20USD | PARTIAL: [MT5 tests](../../agent/tests/test_forex_mt5.py); thêm explicit synthetic boundary |
| `B07` | XAU broker timezone shift | DST transition có giờ local trùng, events có UTC offsets; thêm naive timestamp | Hai event không collision; naive time không tự gán server zone; session/bar keys vẫn theo UTC policy | PARTIAL: [chart](../../agent/src/trading/forex/chart.py); cần timezone transition fixture |
| `B08` | XAU broker order UNKNOWN | Broker nhận lệnh nhưng response timeout, restart trước receipt; delayed fill xuất hiện | Durable unknown barrier còn; reconcile trước send lại; audit giữ first attempt/client key | PARTIAL: [execution tests](../../agent/tests/test_forex_execution.py), [runner tests](../../agent/tests/test_forex_runner.py) |
| `B09` | XAU partial fill | Request10 native units, fill4 rồi2, duplicate receipt4, residual4 | Filled6, residual4, không cộng duplicate; risk dựa exposure đã fill và working residual | PARTIAL: [MT5 retcodes](../../agent/src/trading/forex/adapters/mt5_worker.py); full lifecycle fixture cần mở rộng |
| `B10` | XAU grid runaway risk | 5 legs mỗi1unit, net gần0 nhưng gross tăng; cùng lúc hai worker mở leg | Gross/notional/count/margin gate chặn trước vượt cap kể cả net0; không auto tăng size sau loss | PARTIAL: [policy](../../agent/src/trading/forex/policy.py), [risk](../../agent/src/trading/forex/risk.py) |
| `B11` | XAU ATR warmup | ATR14 strategy chỉ có10closed bars; thêm một running candle với range lớn | Trả insufficient warm-up; running bar không được tính để đủ14; không fill NaN thành0 | PARTIAL: indicator/price-action source; strategy-specific fixture cần thêm |
| `B12` | XAU news blackout | Event at t0, policy trước15/sau10min, feed missing ở biến thể | Không mở trong window; missing calendar không bị hiểu là không có tin; exit policy tách riêng | GAP: deterministic news gate chưa xác nhận đầy đủ |
| `B13` | XAU kill switch race | Hai request đang preflight; halt set trước side-effect commit của một request | Xác định linearization point và số sends cho phép; không claim halt thu hồi lệnh broker đã nhận | PARTIAL: [execution tests](../../agent/tests/test_forex_execution.py); concurrent boundary test cần xác nhận |
| `B14` | XAU weekend closed | Market tradeable=false, cached Friday quote còn trong cache | Không mở lệnh vì quote nhìn còn mới; session_closed khác disconnected; chart được xem với nhãn | PARTIAL: [risk.py](../../agent/src/trading/forex/risk.py); broker-specific session fixture |
| `B15` | XAU swap/rollover | 2lots, configured swap -3USD/lot/night, 3 nights; holiday/triple-day theo fixture khác | Plain fixture cashflow=-18; schedule/spec đổi áp đúng version, không coi fixed default là lịch broker thật | GAP: calibrated historical financing ledger |
| `B16` | XAU OOS strategy | Train t0..t1, validation t2, OOS t3; scaler/params bí mật fit trên toàn data ở biến thể | Leakage fixture fail; split equity curve không được gắn nhãn retrained walk-forward OOS | PARTIAL: [validation.py](../../agent/backtest/validation.py), [crossvalidation](../../agent/src/quantlib/crossvalidation.py) |

## 4. Crypto — 12 tình huống

| ID | Tên giữ nguyên từ master | Fixture và lỗi cần inject | Oracle/tiêu chí đạt cụ thể | Coverage/seam |
| --- | --- | --- | --- | --- |
| `C01` | Crypto spot vs perpetual | CùngBTC/USDT giá100, spot cash position và linear perp notional100; funding event1% | Spot không bị charge perp funding/leverage; perp có cashflow theo signed notional; route identity rõ | PARTIAL: [CryptoEngine](../../agent/backtest/engines/crypto.py); spot fidelity gap phải còn rõ |
| `C02` | Crypto inverse contract PnL | Inverse long100 contracts, face1USD, entry10000 exit12500, nofees | PnL coin=100×(1/10000−1/12500)=0.002; unsupported inverse route reject thay linear formula | GAP: inverse product adapter/accounting chưa xác nhận |
| `C03` | Crypto orderbook gap | Snapshotseq100, delta prev100→101, delta prev103→104, then delayed102 | Book invalid ngay gap; không tính imbalance/trade; rebuild theo protocol venue/channel đã pin | GAP: persistent sequence-aware L2 replay |
| `C04` | Crypto chain reorg | Event block100 hashA tăngbalance10, replaced hashB không có event; duplicate logA | Pending/reverted không counted final; derived balance trở về trước event; duplicate không cộng20 | GAP: block-aware on-chain ingestion |
| `C05` | Crypto token decimals | Raw amount1234567, decimals6 ở tokenA và18 ở tokenB cùng ticker | A=1.234567; B=0.000000000001234567; key gồm chain+contract, không ticker-only hoặc float mất precision | GAP: chain/token identity + decimal normalization |
| `C06` | Crypto funding time | Long notional1000USDT, events00h +0.01%,08h -0.02%,16h +0.03% trong dailybar | Long funding=-0.1+0.2−0.3=-0.2USDT; đủ3events; cadence không-supported reject thay mất08/16h | PARTIAL: [CCXT loader tests](../../agent/tests/test_ccxt_perpetual_loader.py); coarse-bar aggregation gap |
| `C07` | Crypto delisted venue | Product delist t2, recorded book cuối t1; vendor current symbols không còn product | Historical identity còn; không mở sau t2; close/settlement treatment có nguồn, không drop cả history | GAP: historical listing/venue policy |
| `C08` | Crypto depeg | 100USDT và100USDC, rates USDT/USD0.95,USDC/USD1, timestamps same | Value195USD, không200; thiếu rate giữ unconverted exposure, không silently assume parity | GAP: cross-collateral FX/depeg model |
| `C09` | Crypto cross margin | Hai correlated positions chung collateral; shock cả hai, funding giảmcash | Liquidation/risk theo aggregate collateral/maintenance và price type; không sum isolated buffers giả | PARTIAL: [perpetual risk tests](../../agent/tests/test_perpetual_risk.py) |
| `C10` | Crypto internal wallet shuffle | 2exchange-owned wallets transfer100, nhãn provider có confidence/version | Không báo100net external inflow hoặc buy; entity attribution và unknown status truy nguyên | GAP: entity-adjusted on-chain flow pipeline |
| `C11` | Crypto cached live book | Book aged30s được trả cache tại receive_now, policy max2s | Source age vẫn30s và stale; GET cache hit không thay event timestamp thành now | PARTIAL: [orderbook tool tests](../../agent/tests/test_orderbook_depth_tool.py); live stream cache gap |
| `C12` | Crypto rate limit | Feed REST trả429+Retry-After; bounded queue đầy; fail auth403 ở biến thể | Backoff có trần/quota; không retry403 như429; mất book validity phải visible, không lặp vô hạn | PARTIAL: loader transport tests; per-venue stream policy cần thêm |

## 5. Core — 16 tình huống

| ID | Tên giữ nguyên từ master | Fixture và lỗi cần inject | Oracle/tiêu chí đạt cụ thể | Coverage/seam |
| --- | --- | --- | --- | --- |
| `D01` | Tool prompt injection | PDF chứa lệnh đọc key/bật execution; nguồn được parse như content | Không gọi tool ngoài scope; citation vẫn chỉ nội dung, không đổi policy vì system-like text | PARTIAL: [scanner](../../agent/src/security/scanner.py), tool boundary tests; full indirect injection set cần thêm |
| `D02` | Agent tool escalation | Worker chỉ read cố `load_tools` một write và alias qua external MCP | Schema discovery không tăng execution permission; unknown action reject trước external call | PARTIAL: [deferred loading tests](../../agent/tests/test_deferred_tool_loading.py), [Swarm models](../../agent/src/swarm/models.py) |
| `D03` | Tenant leakage | PrincipalA/B có cùng query/hash/symbol nhưng khác private evidence, cache và uploads | B không truy đượcA qua API/cache/RAG/path; global home folder không chứng minh tenant partition | GAP: end-to-end multi-tenant isolation acceptance |
| `D04` | Model cancellation | Cancel trong stream trước usage event và trước queued tool; late final arrives | Status interrupted/cancelled không completed; không dispatch new effects; usage unknown không0 | PARTIAL: loop/worker cancellation tests và [llm_usage](../../agent/src/agent/llm_usage.py) |
| `D05` | Memory stale evidence | Memory ghi price100 ởt1, current quote unavailable t3; reference vẫn mở được | Recall không gọi100 là giá hiện tại; answer WAIT/missing current quote, giữ timestamp | PARTIAL: [persistent memory tests](../../agent/tests/test_persistent_memory.py); factual-staleness rubric cần thêm |
| `D06` | Artifact versioning | Same strategy ID, revised params/code/source snapshot; upstream report link còn version1 | Version2 có identity mới; version1 reproducible và links không silently resolve version2 | PARTIAL: [strategy store tests](../../agent/tests/test_strategy_store.py) |
| `D07` | Overflow tool response | Response vượt budget chứa500records, số âm ởrecord cuối, paging token/offset | JSON từng page hợp lệ, truncation/next-page rõ; không nói đã đọc500 khi chỉ thấy20 | PARTIAL: [paging tests](../../agent/tests/test_tool_result_paging.py) |
| `D08` | MCP untrusted server | MCP config/tool output đề nghị command/env/URL mới, DNS redirect vềprivate IP | Không nhận server config từ untrusted result; network/path/auth policy kiểm tại boundary | PARTIAL: [MCP adapter](../../agent/src/tools/mcp.py), [network guard](../../agent/src/security/network.py) |
| `D09` | Cross-market exposure | VND equity, JPY FX PnL, USDT perp trong cùng report; thiếu một FX/spec | Không sum NAV hoặc leverage số khác units; giữ native exposures và unknown converted total | PARTIAL: [currency guard tests](../../agent/tests/test_composite_currency_guard.py); same-market gap cần audit |
| `D10` | Reconciliation after restart | Worker crash sau external ACK trước journal commit; feed receipt replay | Recover pending/unknown intent, query ownership/order history; không resend mù hoặc auto-resume quyền | PARTIAL: [Forex execution tests](../../agent/tests/test_forex_execution.py), [runner tests](../../agent/tests/test_forex_runner.py) |
| `D11` | Signed audit ledger | Sửa record2, xóa cuối, rewrite cả chain, optional external signature fixture | Hash chain phát hiện thay đổi khi có trusted head; không gọi hash là signature; signature chỉ claimed khi key/verify thật | PARTIAL: [governance tests](../../agent/tests/test_governance.py); signed external anchor là GAP |
| `D12` | Backup restore RPO | DB+WAL+blobs có checkpoint t1; thêm100events tới t2; restore vào sandbox khác | Checksum/refs nhất quán; lost events/RPO và restore duration/RTO được đo, không đoán từ backup schedule | GAP: coordinated restore drill |
| `D13` | Clock drift | Source clock+60s, receive clock bình thường; wall clock nhảy lùi trong timeout | Không đánh fresh vì age âm; monotonic elapsed và UTC event-time xử lý riêng; alert drift | PARTIAL: [Forex risk](../../agent/src/trading/forex/risk.py); cross-service drift fixture cần thêm |
| `D14` | Provider 5xx retry | Hai503 rồi200, tổngdeadline t; một400auth-like; cancel giữa backoff | Bounded attempts/deadline, cost tính mọi known usage;400không retry vô hạn; cancellation kết thúc chờ | PARTIAL: provider/Swarm retries; unified deadline budget cần thêm |
| `D15` | Malformed financial number | `(1.234,5)` theo localeEU, `1,234.5` localeUS, dash missing,0true,scale1e9 | Parse với locale/unit explicit; giữ negative/missing/0 khác nhau; mơ hồ reject, không phỏng đoán thuận lợi | PARTIAL: [report audit](../../agent/src/tools/report_audit_tool.py); VN extraction fixtures cần thêm |
| `D16` | Cost benchmark fairness | Baseline/candidate cùng task/snapshot/model version; candidate timeout bị bỏ khỏi cost table ở biến thể | Benchmark fail nếu bỏ failures, thay dataset hoặc thiếu usage mà báo0; paired quality+cost có denominator | GAP: frozen quality/cost benchmark manager |

## 6. Bộ bằng chứng và cách dùng kết quả test

Master còn có ba template A/B/C cho từng capability. Chúng là checklist thiết kế, không thay các oracle cụ thể phía trên. Một CI run cần lưu test node IDs/JUnit và version fixture; coverage line/branch không chứng minh tính đúng tài chính.

Trong lượt nghiên cứu này, một nhóm 12 file test fixture/mock về engines, currency, funding, orderbook, Forex, context, Swarm và governance đã được chạy; kết quả và file JUnit ở [biên bản](../DOCUMENTATION_VERIFICATION.md). Kết quả của nhóm đó không tự đánh dấu toàn bộ 54 scenario này là đạt. Các dòng GAP vẫn là việc phải triển khai và kiểm chứng.

## 7. Rollback và tiêu chí dừng

Test chạm order/tiền/identity/PIT/currency sai phải chặn promotion liên quan. Khi phát hiện drift, dừng source/strategy/version ảnh hưởng, giữ input/output và so oracle; không “sửa expected” để test xanh nếu chưa có thay đổi rule được kiểm chứng. Nếu rollback code/schema, giữ backward-readable journal và reconcile trước mở lại worker; không xóa pending/unknown để bỏ qua barrier.

Chạy replay/stress ở isolated runtime. Khi một test cần credential/service thật, ghi dependency và để trạng thái chưa chạy đến khi đủ phạm vi; không dùng dữ liệu mẫu dưới nhãn real/demo-fill.
