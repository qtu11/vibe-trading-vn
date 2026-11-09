# BAO CAO BAN GIAO KIEM TOAN KIEN TRUC: WORKSTREAM 2
## HE THONG DATA INGESTION, CHUAN HOA DU LIEU VA AGENT DATA PIPELINES

Nguoi lap: explorer_ws2_data  
Nguoi nhan: Parent Orchestrator (Conversation ID: a6331bc6-4f92-4664-b80f-a4540ff330ff)  
Thoi diem: 2026-11-08T14:30:00Z  
Trang thai: Hard Handoff (Khao sat hoan tat)

---

### 1. OBSERVATION (QUAN SAT TRUC TIEP)

1.1 **Broker Connectors & Adapters**:
- `agent/src/trading/service.py:18-35`: Danh muc `_SDK_CONNECTOR_MODULES` dinh nghia 16 connectors van chuyen qua direct SDK (mstock, tiger, longbridge, alpaca, okx, binance, futu, dhan, shoonya, zerodha, kis, upbit, toss, trading212, mt5, etoro).
- `agent/src/trading/connectors/ibkr/local.py:525-600`: IBKR su dung `_TwsPool` voi `threading.local()` va `threading.Lock()` de quan ly socket `ib_async.IB` doc quyen cho tung luong worker, cap phat `client_id` dong qua `itertools.count(1)`.
- `agent/src/trading/forex/adapters/mt5.py:26-35`: MT5 Adapter thuc thi moi thao tac bang cach spawn tien trinh Python doc lap: `subprocess.run([sys.executable, "-m", "src.trading.forex.adapters.mt5_worker"], input=json.dumps(payload), timeout=40)`.
- `agent/src/trading/forex/adapters/exness.py:178-221`: Ham `quote` cua Exness adapter mo mot ket noi WebSocket dong thoi (`with self.ws_factory(uri, ...) as socket:`), gui goi tin subscribe tick, cho nhan 1 tick hop le roi ngat ket noi (ephemeral socket), khong phai persistent stream.

1.2 **Historical Loaders & Timezone Flaws**:
- `agent/backtest/loaders/yfinance_loader.py:220-223`:
  ```python
  index = pd.DatetimeIndex(pd.to_datetime(normalized.index))
  if getattr(index, "tz", None) is not None:
      index = index.tz_localize(None)
  normalized.index = index
  ```
  `index.tz_localize(None)` cat bo thong tin mui gio goc cua Yahoo (`America/New_York` cho US Equities) ma khong chuyen doi sang UTC, bien `09:30-04:00` thanh `09:30 naive` (lech 4 tieng so voi UTC thuc).
- `agent/backtest/loaders/yahoo_loader.py:167`:
  ```python
  index = pd.to_datetime(frame["trade_date"], unit="s", utc=True).dt.tz_convert(None)
  ```
  Ham nay convert sang UTC roi moi cat tz, tra ve `13:30 naive`. Tao ra xung dot truc tiep giua hai loader cung mot nguon Yahoo.
- `agent/backtest/loaders/mt5_loader.py:169` va `agent/src/trading/forex/adapters/mt5_worker.py:216`:
  `pd.to_datetime(frame["time"], unit="s")` va `datetime.fromtimestamp(int(r["time"]), timezone.utc)` coi gio may chu broker (GMT+2 / GMT+3 cua Exness/IC Markets) nhu gio UTC, lech tu 2 den 3 tieng so voi gio chuan.

1.3 **Streaming Pipelines & Frontend Data Delivery**:
- `agent/src/api/sessions_routes.py:910-918`: Endpoint SSE `/api/sessions/{session_id}/events` chi stream cac su kien agent turn (`attempt.started`, `tool_call`, `mandate_proposal`, `live_action`), hoan toan khong stream du lieu gia thi truong hay nến.
- `agent/src/channels/websocket.py:54-95`: WebSocket channel chi la kenh chat danh cho bot tuong tac ngon ngu tu nhien, khong phai duong truyen market data.
- `frontend/src/hooks/useForexChart.ts:16-35`: Frontend Forex Live Chart lay du lieu bang cach lap Short-Polling HTTP moi 3 giay (`fetchForexChart` goi `GET /api/forex/chart`).
- `agent/src/trading/forex/chart.py:16-17`:
  `if config.connector != "mt5": raise ForexError("CHART_MT5_REQUIRED", "Live native chart currently requires an MT5 connection")`.
  Co che nay chi ho tro duy nhat MT5.
- `frontend/src/components/charts/CandlestickChart.tsx`: Chi la component hien thi tinh trong `RunDetail.tsx:954` va `CouncilReport.tsx:660`, hoan toan khong co luong streaming nến cho Co phieu.

1.4 **Tick Aggregation & Math Flaws**:
- Khong ton tai bat ky module aggregation tick nao trong `agent/src` hoac `agent/backtest`. Toan bo nến duoc tra ve duoi dang tinh san tu broker.
- `agent/src/factors/base.py:440-475`:
  * Voi CN Equity: `safe_div(panel['amount'] * 1000.0, panel['volume'] * 100.0 + 1.0)`. Dung `+ 1.0` o mau so lam bien dang gia tri tren cac nến thanh khoan thap.
  * Voi US, HK, IN, KR, Crypto: Neu khong co san cot `vwap`, he thong tinh:
    `vwap = (panel["open"] + panel["high"] + panel["low"] + panel["close"]) / 4.0`.
    Day la Typical Price khong co trong so khoi luong, khong phai VWAP.
  * Thieu co che reset VWAP theo moc mo cua phien hang ngay.
- `agent/src/live/runtime/triggers.py:112-127`: `MARKET_SPECS` chi chua `us_equity` va `crypto`. Hoan toan thieu phien Viet Nam (HOSE/HNX), Hong Kong (HKEX), Trung Quoc (A-share) va Forex/Metals (24/5 cho XAU/USD).

1.5 **Concurrency, Queues & Backpressure**:
- `agent/src/channels/bus/queue.py:16-17`: `MessageBus` su dung `asyncio.Queue()` voi `maxsize=0` (unbounded), khong co co che backpressure.
- `agent/src/session/events.py:257, 167-169`: `EventBus` gioi han `maxsize=200`, khi hang doi day se am tham vut bo su kien (`logger.warning("EventBus queue full, dropping...")`).

---

### 2. LOGIC CHAIN (CHUOI LAP LUAN)

1. **Tu Quan sat 1.3 va 1.1**:
   Frontend su dung HTTP short-polling 3 giay mot lan goi vao `GET /api/forex/chart`, va backend moi lan nhan request lai thuc thi mot tien trinh Python con moi thong qua `subprocess.run` de attach vao MT5 terminal.
   -> **Suy luan**: He thong hien tai khong co kien truc Real-Time Market Data Streamer. Mo hinh polling + subprocess tao overhead cuc lon ve mat CPU, I/O tren Windows va do tre bi co dinh o muc >= 3 giay, khong the dat duoc toc do stream tick duoi 1 giay cho XAU/USD hoac Equities.

2. **Tu Quan sat 1.2**:
   `yfinance_loader.py` cat bo mui gio goc bang `tz_localize(None)` khien gio My bien thanh gio naive (9:30 sang New York hieu thanh 9:30 naive). Trong khi `yahoo_loader.py` lai convert gio sang UTC roi moi cat bo mui gio (13:30 naive).
   -> **Suy luan**: Co su lech pha nghiem trong tu 4 den 5 tieng dong ho giua cac bo nap du lieu khi cung lay tu mot nha cung cap (Yahoo Finance). Khi thuc hien cross-market backtest giua co phieu My va Crypto/Forex, cac thanh nến bi gep sai lech thoi gian nghiem trong.

3. **Tu Quan sat 1.4**:
   `agent/src/factors/base.py` tinh VWAP bang cach lay trung binh cong 4 muc gia `(O+H+L+C)/4` khi khong co cot `vwap` san.
   -> **Suy luan**: Chi bao VWAP tren he thong thuc chat la Typical Price khong co trong so khoi luong. Dieu nay vi pham truc tiep cac tieu chuan dinh luong cua CFA Institute ve Volume-Weighted Average Price, triet tieu dac tinh nhan dien vung thanh khoan lon dau va cuoi phien.

4. **Tu Quan sat 1.5**:
   `EventBus` cua SSE stream am tham vut bo cac su kien khi hang doi 200 phan tu bi day do mang cham.
   -> **Suy luan**: Client UI co the bi mat dong bo trang thay lenh hoac bo sot cac event quan trong ma khong he nhan duoc tin hieu canh bao hay yeu cau dong bo lai.

---

### 3. CAVEATS (CAC DIEM CHUA KHAO SAT / GIA DINH)

1. Khong chay truc tiep terminal MT5 tren moi truong thuc vi day la tac vu kham pha doc-ma (read-only exploration); toan bo quan sat ve MT5 duoc doi chieu truc tiep tu code adapter va unit tests (`tests/test_mt5_loader.py`, `tests/test_forex_chart.py`).
2. Cac broker quoc te khac nhu Futu, Longbridge, KIS duoc module hoa qua `broker_sdk` nhung khong nam trong tieu diem Forex/XAU/USD nen chi duoc ra soat qua danh muc module.

---

### 4. CONCLUSION (KET LUAN VA KIEN NGHI HANH DONG)

He thong Data Pipeline cua Vibe-Trading da co nen tang tot ve co che fallback chain va quan ly credential an toan qua OS vault. Tuy nhien, he thong **chua san sang cho Real-Time Candlestick Engines va Institutional CFA Analytics** do 4 khiem khuyet cot loi:
1. **Thieu Real-Time Market Data Streaming Engine**: Khong co WebSocket/SSE broadcast nen cho Equities va XAU/USD (dang dung HTTP polling 3s kem subprocess MT5).
2. **Sai lech Timestamp Timezone**: Xung dot giua `yfinance_loader` va `yahoo_loader`, va hieu sai broker time MT5 thanh UTC.
3. **Thieu Dinh nghia Phien Giao dich**: `triggers.py` khong co phien Viet Nam (VN Index), Hong Kong, Trung Quoc, va Forex 24/5.
4. **Meo mo Toan hoc VWAP**: Tinh bang `(O+H+L+C)/4` thieu khoi luong va `+ 1.0` o mau so co phieu Trung Quoc.

**Cac buoc hanh dong de xuat cho doi ngu Implementer**:
1. Xay dung mot FastAPI WebSocket Market Data Endpoint (`/api/market-data/stream`) voi in-memory tick-to-bar aggregator.
2. Sua loi `tz_localize(None)` trong `yfinance_loader.py:222` thanh `tz_convert("UTC").tz_localize(None)`.
3. Them chuyen doi mui gio may chu broker MT5 ve UTC trong `mt5_loader.py` va `mt5_worker.py`.
4. Bo sung cau hinh phien cho `vn_equity`, `hk_equity`, `cn_equity`, va `forex_metals` vao `triggers.py:MARKET_SPECS`.
5. Chuan hoa ham `vwap()` trong `factors/base.py` de tinh dung $\sum(P \cdot V)/\sum V$ va reset theo phien.
6. Thiet lap `maxsize` cho `MessageBus` va bo sung co che canh bao overflow cho `EventBus`.

---

### 5. VERIFICATION METHOD (PHUONG PHAP XAC MINH DOC LAP)

Cac ky su co the xac minh doc lap cac phat hien tren bang cac buoc sau:

1. **Kiem tra loi Timezone**:
   Mo file `agent/backtest/loaders/yfinance_loader.py` dong 220-224 va `agent/backtest/loaders/yahoo_loader.py` dong 167. So sanh cach xu ly index cua hai loader khi tai cung ma `AAPL.US`.
2. **Kiem tra loi Toan hoc VWAP**:
   Mo file `agent/src/factors/base.py` dong 462-475 de thay cong thuc `(open + high + low + close) / 4.0` duoc su dung thay cho VWAP thuc su.
3. **Kiem tra co che Polling cua Frontend**:
   Mo file `frontend/src/hooks/useForexChart.ts` dong 16-35 de thay vong lap `setTimeout(poll, 3000)`.
4. **Chay test suite cua Chart va MT5 Loader**:
   Chay lenh PowerShell tu thu muc `agent`:
   `pytest tests/test_forex_chart.py tests/test_mt5_loader.py -v`
