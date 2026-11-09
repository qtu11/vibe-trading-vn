# BAO CAO KIEN TRUC VA KIEM TOAN CHUYEN SAU: WORKSTREAM 2
## HE THONG DATA INGESTION, CHUAN HOA DU LIEU VA AGENT DATA PIPELINES TRONG VIBE-TRADING

Nguoi thuc hien: explorer_ws2_data  
Thoi diem: 2026-11-08T14:25:00Z  
Pham vi: He thong ket noi Broker (Connectors), Bo nap du lieu lich su (Backtest Loaders), Streaming Pipelines, Tinh toan OHLCV/VWAP, va Kha nang dong thoi / Phuc hoi mang.  
Quy tac trinh bay: Khong su dung emoji hoac icon. Toan bo dan chung trich xuat truc tiep tu ma nguon repo kem duong dan file va so dong chi tiet.

---

## 1. TONG QUAN VA BANG DANH GIA HIEN TRANG

| Thanh phan | File ma nguon tieu bieu | Hien trang kien truc | Muc do rui ro / Han che |
|---|---|---|---|
| Broker Connectors | `agent/src/trading/connectors/` (MT5, Binance, IBKR, v.v.) va `agent/src/trading/forex/adapters/` (MT5, Exness, OANDA) | Kien truc module hoa tot qua `TradingService` va `_SDK_CONNECTOR_MODULES`, tuy nhien moi adapter Forex su dung giao thuc rieng le (subprocess IPC, HTTP polling, ephemeral WebSocket). | Trung binh: Khong co co che stream tap trung giua cac broker. |
| Historical Loaders | `agent/backtest/loaders/` (MT5, CCXT, Yahoo, YFinance, Akshare, Local, Base, Registry) | Ho tro fallback chain manh me giua cac nguon (`FALLBACK_CHAINS`). Co cache cuc bo va budget retry. | Cao: Xung dot timestamp timezone giua `yfinance_loader.py` va `yahoo_loader.py`. MT5 loader hieu sai gio broker la UTC. |
| Streaming & Real-Time APIs | `agent/src/api/sessions_routes.py`, `agent/src/channels/websocket.py`, `frontend/src/hooks/useForexChart.ts` | Khong co WebSocket/SSE stream du lieu thi truong toi frontend. Forex dung co che short-polling 3 giay sinh tien trinh Python moi lan. Equities khong co pipeline real-time. | Rat nghiem trong: Thieu kien truc Real-Time Market Data Streamer. |
| Tick Aggregation & Math Integrity | `agent/src/factors/base.py`, `agent/backtest/loaders/base.py`, `agent/backtest/engines/base.py` | Tick aggregation phu thuoc hoan toan vao broker backend. Cong thuc VWAP bi sai lech (+1.0 o Mau so CN, va thay bang OHLC/4 cho cac thi truong khac). Thieu module reset VWAP theo phien. | Cao: Tinh toan toan hoc bi meo mo sai tieu chuan dinh luong institutional. |
| Concurrency, Thread Safety & Backpressure | `agent/src/channels/bus/queue.py`, `agent/src/session/events.py`, `agent/src/trading/connectors/ibkr/local.py` | IBKR pool thread-safe bang thread-local. EventBus SSE co hang doi gio han 200 phan tu nhung am tham lam roi su kien (drop). MessageBus su dung hang doi khong gioi han (unbounded queue). | Cao: Suy giam bo nho va mat dong bo UI khi luu luong su kien cao. |

---

## 2. CHI TIET TARGET 1: END-TO-END DATA FLOWS TU BROKER CONNECTORS VA LOADERS

### 2.1 Kien truc ket noi Broker Connectors
He thong Vibe-Trading phan tach cac ket noi broker thanh 3 co che van chuyen (transports) chinh thong qua `src.trading.service.py`:

1. **Broker SDK Direct Transport (`broker_sdk`)**:
   - Vi tri ma nguon: `agent/src/trading/service.py:18-35` khai bao `_SDK_CONNECTOR_MODULES`:
     * `mt5`: `src.trading.connectors.mt5.sdk`
     * `binance`: `src.trading.connectors.binance.sdk`
     * `okx`: `src.trading.connectors.okx.sdk`
     * `alpaca`: `src.trading.connectors.alpaca.sdk`
     * `tiger`, `futu`, `longbridge`, `mstock`, `dhan`, `shoonya`, `zerodha`, `kis`, `upbit`, `toss`, `trading212`, `etoro`.
   - Co che goi: Ham `get_quote` (`service.py:348-350`) va `get_history` (`service.py:449-459`) goi module SDK tuong ung voi cau hinh xac thuc lay tu OS credential vault thong qua `_sdk_config` (`service.py:81-147`).
   - Vi du MT5 SDK Read (`agent/src/trading/connectors/mt5/reads.py:213-240, 281-304`):
     * Ham `get_quote` su dung context manager `_client._session(cfg)` de attach vao session MT5 va goi `mt5.symbol_info_tick(name)`. Neu truong `last` bang 0 (pho bien o Forex), he thong bo qua de roi ve cap bid/ask.
     * Ham `get_historical_bars` goi `mt5.copy_rates_from_pos(name, timeframe, 0, int(limit))`.

2. **Local TWS Transport (`local_tws`)**:
   - Vi tri ma nguon: `agent/src/trading/connectors/ibkr/local.py`.
   - Co che: Chi ket noi vao ung dung TWS hoac IB Gateway dang chay cuc bo tren may nguoi dung (cong 7496/7497 hoac 4001/4002).
   - Co che Pool va Thread Safety: `_TwsPool` (`local.py:525-600`) quan ly danh sach ket noi `ib_async.IB` theo tung thread thong qua `threading.local()`, tu dong cap phat `client_id` tang dan qua `itertools.count(1)` de tranh xung dot client ID khi cac tool chay song song.
   - Lay bao gia Snapshot: Ham `_wait_for_tick` (`local.py:393-418`) goi `ib.reqMktData(contract, "", True, False)` voi snapshot=True va lap `ib.sleep(0.1)` cho den khi ticker duoc dien du lieu hoac qua timeout 5 giay.
   - Lay nen lich su: Ham `get_historical_bars` (`local.py:477-520`) goi `ib.reqHistoricalData(...)`.

3. **Dedicated Forex Adapters (`agent/src/trading/forex/adapters/`)**:
   Phan he Forex duoc thiet ke doc lap voi 3 adapter chuyen dung:
   - **MT5 Adapter (`agent/src/trading/forex/adapters/mt5.py` va `mt5_worker.py`)**:
     * Co che Co lap Tien trinh (Process Isolation): De bao ve tien trinh chinh khoi cac su co crash cua thu vien C/C++ goc `MetaTrader5`, moi thao tac duoc thuc hien bang cach spawn mot tien trinh con Python qua `subprocess.run([sys.executable, "-m", "src.trading.forex.adapters.mt5_worker"], input=json.dumps(payload), timeout=40)` (`mt5.py:26-35`).
     * Khoa truy cap doc: `terminal_read_lock` (`mt5_worker.py:34-52`) su dung non-blocking lock ket hop vong lap thu lai trong 10 giay voi sleep 50ms de dam bao khong xung dot lenh voi broker.
     * Nen lich su: `_rates` (`mt5_worker.py:208-227`) goi `mt5.copy_rates_from_pos(symbol, timeframe, start_pos, limit)` voi `start_pos=1` cho candles da dong va `start_pos=0` cho chart co zero-bar.
   - **Exness Adapter (`agent/src/trading/forex/adapters/exness.py`)**:
     * Xac thuc va Ky khoa: Su dung Ed25519 private key va API key de ky request theo chuan HTTP signature (`exness_auth.py:15-16`).
     * Co che Lay Quote qua WebSocket ngan han: Ham `quote` (`exness.py:170-221`) thiet lap ket noi WebSocket toi `wss://{ap}/v1/server-events/accounts/{id}/ws/ticks`, gui goi tin dang ky `{"subscribe": {"event": "ticks", "instruments": [symbol]}}`, cho nhan 1 tick hop le roi dong ket noi ngay lap tuc. Day la co che ephemeral socket, gay overhead rat lon neu poll lien tuc.
     * Nen lich su: Goi REST API `GET /v1/market-data/candles` (`exness.py:223-253`). Nen chi co gia Bid, hoan toan khong co truong Volume.
   - **OANDA Adapter (`agent/src/trading/forex/adapters/oanda.py`)**:
     * Giao thuc REST v20 thuan tuy qua HTTP Bearer token.
     * Quote lay tu `GET /v3/accounts/{id}/pricing?instruments={symbol}` (`oanda.py:79-116`).
     * Candles lay tu `GET /v3/accounts/{id}/instruments/{symbol}/candles` (`oanda.py:127-150`). Volume la `price_updates` (so lan nhay gia).

### 2.2 He thong Historical & Backtest Loaders (`agent/backtest/loaders/`)
Kien truc bo nap du lieu lich su duoc dieu phoi thong qua Registry (`registry.py`) va co che Fallback Chain duoc xac dinh trong `agent/src/market_data.py:21-66` va `backtest.loaders.registry.FALLBACK_CHAINS`:

1. **MT5 Loader (`agent/backtest/loaders/mt5_loader.py`)**:
   - Ket noi toi terminal MT5 cuc bo da dang nhap, khong can API key.
   - Ho tro phat hien ma tien to/hau to cua broker qua `_resolve_broker_symbol` (`mt5_loader.py:136-160`), vi du tu `EURUSD` tu dong tim ra `EURUSDm` tren Exness.
   - Lay du lieu qua `mt5.copy_rates_range(name, timeframe, date_from, date_to)` (`mt5_loader.py:258`).
   - Chuyen doi sang DataFrame qua `_rates_to_frame` (`mt5_loader.py:162-180`). Gan `volume = tick_volume`.

2. **CCXT Loader (`agent/backtest/loaders/ccxt_loader.py`)**:
   - Ket noi hon 100 san Crypto, mac dinh Binance (`ccxt_loader.py:4`).
   - Phan biet giua Spot va USD-M Perpetual Swap (`_parse_ccxt_symbol`, `ccxt_loader.py:60-71`).
   - Xu ly dong bo gia Mark va Funding Rate (`_fetch_perpetual`, `ccxt_loader.py:314-390`): Tai ca nen gia Trade va nen gia Mark (`price="mark"`), kiem tra trung khop index 100%. Tai lich su funding settlement qua `_fetch_funding_history` va canh chinh gio theo cac moc 00:00, 08:00, 16:00 UTC.
   - Kiem soat ngan sach thoi gian: `_CCXT_TIMEOUT_MS = 15000` va `_CCXT_FETCH_BUDGET_S = 60.0` (`ccxt_loader.py:55-56`), ngan chan tuyet doi viec treo backtest do mang cham.

3. **Akshare Loader (`agent/backtest/loaders/akshare_loader.py`)**:
   - Cung cap du lieu mien phi cho Co phieu Trung Quoc (A-share), Hong Kong, Forex va Futures.
   - Xu ly chuyen doi co tuc: Ham `_fetch_a_share` phat hien gia qfq additive va goi `convert_additive_to_multiplicative` (`akshare_loader.py:148-176`) de dam bao tinh toan loi nhuan khong bi meo mo.
   - Xu ly Forex: `_fetch_forex` (`akshare_loader.py:300-327`) lay tu `ak.forex_hist_em`. Do API nay khong tra ve volume, loader buoc phai tao cot volume gia dinh bang 0: `df["volume"] = 0.0`.

4. **YFinance Loader (`agent/backtest/loaders/yfinance_loader.py`) va Yahoo Loader (`agent/backtest/loaders/yahoo_loader.py`)**:
   - Cung cap du lieu chung khoan My, Hong Kong, An Do, Han Quoc, Canada, Anh, va Viet Nam (HOSE ma `.VN` tren Yahoo, vi du `VIC.VN`).
   - Xu ly chia tach co phieu qua tham so `auto_adjust=True` (`yfinance_loader.py:141`).
   - Chuyen doi interval: Tu dong gom cum `4h` tu `1h` thong qua `resample("4h")` (`yfinance_loader.py:235-247`).

5. **Local Data Loader (`agent/backtest/loaders/local_loader.py`)**:
   - Doc tu file CSV, Parquet hoac DuckDB cau hinh tai `~/.vibe-trading/data-bridge/config.yaml` (`local_loader.py:50-51`).
   - Nhan dien thay doi file qua SHA-256 hash cua file stat (size, mtime, inode) de tu dong vo hieu hoa cache (`_source_file_revision`, `local_loader.py:159-182`).
   - Downsampling qua `_resample_to_interval` (`local_loader.py:88-136`) bang cach su dung `df.resample(rule).agg(_OHLCV_AGG)`.

---

## 3. CHI TIET TARGET 2: STREAMING PIPELINES VA APIS

### 3.1 Kiem toan cac Streaming Endpoints tren Backend (`agent/src/api/`)
Toan bo cac route HTTP cua server duoc khai bao va kiem tra:

1. **SSE Endpoint: `/api/sessions/{session_id}/events`** (`agent/src/api/sessions_routes.py:870-918`):
   - Muc dich: Day cac su kien tu duy cua Agent (Agent Loop), tien trinh thuc thi cong cu (Tool Calls), de xuat Mandate (`mandate_proposal`), va lenh live (`live_action`).
   - Ban chat: Khong phan phoi du lieu thi truong (Market Ticks / Bars / Quotes).
   - Format: Chuan `text/event-stream` voi header `Cache-Control: no-cache`, `Connection: keep-alive`, `X-Accel-Buffering: no`.

2. **SSE Endpoint: `/api/swarm/events/{run_id}`** (`agent/src/api/swarm_routes.py:228`):
   - Muc dich: Day su kien thuc thi DAG cua Swarm runtime. Khong lien quan den market data.

3. **SSE Endpoint: `/api/alpha/bench/jobs/{job_id}/events`** (`agent/src/api/alpha_routes.py:808`):
   - Muc dich: Day tien do backtest Alpha Zoo. Khong lien quan den market data.

4. **WebSocket Channel: `src/channels/websocket.py`**:
   - Cau hinh: `WebSocketConfig` (`websocket.py:54-95`) lang nghe tai port 8765.
   - Ban chat: Day la kenh giao tiep Chatbot (giong nhu kenh Feishu, Telegram, Discord, WeCom) cho phep nguoi dung chat tu nhien voi Vibe-Trading qua WebSocket, gui va nhan text/media. Day KHONG PHAI la WebSocket broker gateway hay market tick streamer.

### 3.2 Luong Du lieu Ticks va Bars vao Frontend: Su That Kien Truc
Qua kiem tra toan bo frontend tai `frontend/src/`:
1. **Khong co WebSocket hay SSE ket noi du lieu thi truong**:
   Frontend khong mo bat ky ket noi persistent streaming nao de nhan tick hoac bar lien tuc.
2. **Kenh hien thi Live Chart Forex duy nhat (`ForexLiveChart.tsx` va `useForexChart.ts`)**:
   - Vi tri: `frontend/src/hooks/useForexChart.ts:16-35`.
   - Co che: Su dung vong lap Short-Polling qua HTTP moi 3 giay:
     ```typescript
     const poll = async () => {
       if (!active || inFlight) return;
       if (document.visibilityState === "hidden") { timer = setTimeout(poll, 3000); return; }
       inFlight = true; setLoading(true);
       try {
         const result = await fetchForexChart(connection, symbol, frame, controller.signal);
         ...
       } finally {
         inFlight = false;
         if (active) { setLoading(false); timer = setTimeout(poll, 3000); }
       }
     };
     ```
   - Ham `fetchForexChart` goi `GET /api/forex/chart` (`agent/src/api/forex_routes.py:164-171`), goi tiep vao `chart_snapshot` (`agent/src/trading/forex/chart.py:12-50`).
   - Tai day, `chart_snapshot` chi ho tro duy nhat MT5 (`config.connector != "mt5": raise ForexError("CHART_MT5_REQUIRED")`).
   - Backend thuc thi `subprocess.run([sys.executable, "-m", "src.trading.forex.adapters.mt5_worker"])` moi 3 giay de truy van MT5 terminal, parse stdout JSON roi tra ve cho frontend.
   - He qua: Day la mo hinh Polling kem hieu nang nhat tren he dieu hanh Windows (tao tien trinh moi lien tuc, chiem dung CPU va I/O), do tre khong the xuong duoi 1 giay, va hoan toan khong co co che tick push.
3. **Chung khoan (Equities - US, VN, HK, CN)**:
   - Thanh phan `CandlestickChart.tsx` (`frontend/src/components/charts/CandlestickChart.tsx`) chi duoc su dung de ve du lieu Tinh (Static) lay tu ket qua backtest trong `RunDetail.tsx:954` hoac bao cao `CouncilReport.tsx:660`.
   - Khong ton tai bat ky co che nao de cap nhat nến thoi gian thuc cho Co phieu.

---

## 4. CHI TIET TARGET 3: TICK AGGREGATION, TIMESTAMP ALIGNMENT VA TINH TOAN TOAN HOC

### 4.1 Thuat toan Gom Tick thanh Nen OHLCV (Tick Aggregation)
1. **Su thieu vang cua Aggregator Engine trong Repo**:
   Trong toan bo ma nguon `agent/src` va `agent/backtest`, khong co bat ky module nao thuc hien viec tich luy raw ticks (bid, ask, last, volume) theo thoi gian thuc de ghep thanh cac thanh nen M1, M5, H1, D1.
2. **Phu thuoc hoan toan vao Server cua Broker**:
   - MT5: Nen duoc gom san boi may chu MT5 va luu trong terminal local cache. Ham `copy_rates_from_pos` chi viec lay nen da dong goi san tu terminal (`mt5_worker.py:211`).
   - Exness: Nen do may chu Exness tinh toan san va tra ve qua REST API endpoint `/candles` (`exness.py:230-239`).
   - OANDA: Nen do may chu OANDA tra ve qua endpoint `/candles` voi granularity quy dinh (`oanda.py:128-133`).
   - IBKR: TWS tu tong hop lich su thong qua `reqHistoricalData` (`local.py:498-506`).
3. **Nen Zero-Bar (Nen dang hinh thanh - Forming Bar)**:
   - Duoc xu ly duy nhat trong `agent/src/trading/forex/chart.py:20-33` va `mt5_worker.py:203-207`:
     * Khi goi `chart()`, MT5 lay cac nen tu `start_pos=0` (bao gom ca nen dang hinh thanh tai vi tri index 0).
     * `chart.py:29` danh dau: `complete = stamp.timestamp() + SECONDS[timeframe] <= now.timestamp()`. Neu thoi diem hien tai chua vuot qua thoi gian ket thuc nen, nen duoc coi la `complete = False`.
     * Nen dang hinh thanh duoc gui ve frontend de ve mau mo hon, va duoc loai bo khoi thuat toan nhan dien mo hinh gia (`price_action.candle_evidence`, `price_action.py:25-45`) nham tranh repaint chi bao.

### 4.2 Canh chinh Timestamp va Ranh gioi Phien Giao dich (Session Boundaries)

#### 4.2.1 Loi Canh chinh Gio Timezone Nghiem trong giua cac Loaders
Kiem toan phat hien su bat nhat nguy hiem giua cac bo nap du lieu:
1. **Loi trong `yfinance_loader.py:220-224`**:
   ```python
   index = pd.DatetimeIndex(pd.to_datetime(normalized.index))
   if getattr(index, "tz", None) is not None:
       index = index.tz_localize(None)
   normalized.index = index
   ```
   Khi `yfinance` tra ve du lieu intraday cua co phieu My, index mang timezone `America/New_York` (vi du: `2026-10-15 09:30:00-04:00`).
   Lenh `index.tz_localize(None)` khong phai la chuyen doi gio ma la **cat bo thong tin mui gio**, bien index thanh `2026-10-15 09:30:00` naive.
   Gia tri nay chenh lech dung 4 tieng so voi moc gio chuan UTC (13:30:00 UTC).
2. **Xung dot truc tiep voi `yahoo_loader.py:167`**:
   ```python
   index = pd.to_datetime(frame["trade_date"], unit="s", utc=True).dt.tz_convert(None)
   ```
   Loader nay lay epoch timestamp UTC tu Yahoo API v8, chuyen sang UTC datetime roi moi convert ve naive UTC. Ket qua la moc `13:30:00`.
   Khi he thong chay co che Fallback tu `yahoo` sang `yfinance`, hai tap du lieu cung mot ma se bi **lech pha nhau tu 4 den 5 tieng dong ho** tren truc thoi gian intraday.
3. **Loi hieu sai gio Server MT5 la UTC trong `mt5_loader.py:169` va `mt5_worker.py:216`**:
   ```python
   frame["trade_date"] = pd.to_datetime(frame["time"], unit="s")
   ```
   Va trong `mt5_worker.py`:
   ```python
   "time": datetime.fromtimestamp(int(r["time"]), timezone.utc).isoformat()
   ```
   Thuc te, gia tri `time` tra ve boi MT5 la epoch timestamp dua tren **dong ho may chu cua broker**, khong phai gio he thong Windows va cung khong phai gio UTC.
   Cac broker Forex/Gold hang dau nhu Exness, IC Markets, Pepperstone su dung gio GMT+2 (mua dong) hoac GMT+3 (mua he) theo chuan gio Dong Au (EET/EEST) de dam bao 5 cay nen ngay D1 dong nhat trong tuan.
   Viec ep truc tiep `timezone.utc` khien toan bo nen MT5 bi lech truoc tu 2 den 3 tieng so voi gio UTC thuc te.

#### 4.2.2 Thieu hut Ranh gioi Phien Giao dich trong `triggers.py`
Kiem toan file `agent/src/live/runtime/triggers.py:112-127`:
Bien `MARKET_SPECS` chi chua duy nhat 2 dinh nghia:
```python
MARKET_SPECS: Mapping[str, _MarketSpec] = {
    "us_equity": _MarketSpec(
        tz="America/New_York",
        open_time=time(9, 30),
        close_time=time(16, 0),
        weekdays=_WEEKDAYS_MON_FRI,
        holidays=_US_EQUITY_HOLIDAYS,
        early_closes=_US_EQUITY_EARLY_CLOSES,
    ),
    "crypto": _MarketSpec(
        tz="UTC",
        open_time=time(0, 0),
        close_time=time(0, 0),
        always_open=True,
    ),
}
```
He thong hoan toan **khong co cau hinh phien** cho:
- **VN Index (Chung khoan Viet Nam - HOSE/HNX)**: Gio giao dich 09:00 - 15:00 (GMT+7), co gio nghi trua tu 11:30 den 13:00.
- **HKEX (Hong Kong)**: 09:30 - 16:00 (HKT), nghi trua 12:00 - 13:00.
- **A-Share (Thuong Hai/Tham Quyen)**: 09:30 - 15:00 (CST), nghi trua 11:30 - 13:00.
- **Forex / XAU/USD (Vang)**: Thi truong 24/5 tu 17:00 Chu Nhat EST toi 17:00 Thu Sau EST, voi khoang nghi chuyen phien (rollover maintenance break) tu 17:00 den 18:00 EST moi ngay.

### 4.3 Xu ly Nen bi Thieu (Missing Bar Interpolation)
He thong xu ly khoang trong du lieu (gaps) theo 3 cach khac nhau tuy theo tang:
1. **Tang Backtest Engine (`agent/backtest/engines/base.py:299-315`)**:
   - Su dung co che Forward-Fill co gioi han (`ffill with limit`):
     ```python
     ffill_limit = 10 if len({_detect_market_for_align(c) for c in codes}) > 1 else 5
     _tmp = pd.DataFrame(close_arr)
     close_arr = _tmp.ffill(limit=ffill_limit).values
     close_val_arr = _tmp.ffill().values
     ```
   - Neu co phieu bi ngung giao dich (halt) duoi 5 ngay (hoac 10 ngay voi cross-market nhu dip Tet Nguyen Dan), gia duoc forward-fill tu gia dong cua cu. Neu gap vuot qua gioi han, gia se bi tra ve `NaN` de khong sinh lenh giao dich voi gia loi thoi.
   - Tuy nhien, gia danh gia danh muc (`close_val_arr`) lai dung unbounded `ffill()` de giu nguyen gia tri danh muc qua cac dot suspension dai ngay.
2. **Tang Yeu to Dinh luong (Alpha Factors - `agent/src/factors/base.py:398-424` va `test_missing_bar_fabrication.py:1-47`)**:
   - Quy tac nghiem ngat: Cam tuyet doi viec che tao gia tri tu cua so co chua missing bar.
   - Ham `observed_over` kiem tra xem moi thanh phan dau vao co xuat hien day du trong `n` bars gan nhat hay khong. Neu co bar thieu, ket qua tra ve phai la `NaN`, khong duoc phep thay the bang 0 hoac forward-fill vi se lam sai lech alpha signal.
3. **Tang Loader Resampling (`agent/backtest/loaders/base.py:314-347`)**:
   - Khi gom tu Daily sang Weekly (`1W`) hoac Monthly (`1M`), cac khoang thoi gian khong co giao dich se bi loai bo chu khong tu dong tao nến rong (zero-volume flat bar).

### 4.4 Kiem toan Toan hoc Tinh toan VWAP (Volume-Weighted Average Price)
Kiem toan file `agent/src/factors/base.py:440-475`:
```python
def vwap(panel: dict[str, pd.DataFrame], market: Market | str) -> pd.DataFrame:
    if "vwap" in panel:
        return panel["vwap"]

    if market is Market.EQUITY_CN:
        if "amount" not in panel or "volume" not in panel:
            raise KeyError("vwap(equity_cn) requires panel['amount'] and panel['volume']")
        return safe_div(panel["amount"] * 1000.0, panel["volume"] * 100.0 + 1.0)

    required = ("open", "high", "low", "close")
    missing = [k for k in required if k not in panel]
    if missing:
        raise KeyError(f"vwap({market.value}) requires panel keys {required}; missing {missing}")
    return (panel["open"] + panel["high"] + panel["low"] + panel["close"]) / 4.0
```

Hai sai pham nghiem trong ve mat toan hoc tai day:
1. **Loi bien dang Mau so cua Co phieu Trung Quoc**:
   Cong thuc: `panel["volume"] * 100.0 + 1.0`.
   Muc dich them `+ 1.0` la de tranh chia cho 0 khi ma bi ngung giao dich (`volume = 0`).
   Tuy nhien, viec cong them 1 co phieu vao mau so gay sai so lech gia (bias) co he thong doi voi cac co phieu co thanh khoan thap (vi du 100 co phieu bi cong them 1% thanh 101 co phieu).
   Giai phap chuan: Su dung mat na `where(volume > 0)` va tra ve `NaN` khi `volume == 0`.
2. **Thay the VWAP bang Typical Price khong co Khoi luong cho toan bo cac Thi truong con lai**:
   Doi voi `EQUITY_US`, `EQUITY_HK`, `EQUITY_IN`, `EQUITY_KR`, `FUTURES`, va `CRYPTO`:
   Neu `panel["vwap"]` chua duoc nap san tu truoc, he thong tinh:
   $$\text{VWAP} = \frac{\text{Open} + \text{High} + \text{Low} + \text{Close}}{4}$$
   Day la **Typical Price** (hoac OHLC/4), hoan toan **KHONG CO TRONG SO KHOI LUONG**!
   Theo dinh nghia chuan cua CFA Institute va giao dich dinh luong institutional:
   $$\text{VWAP} = \frac{\sum_{i=1}^N P_i \times V_i}{\sum_{i=1}^N V_i}$$
   Viec bo qua khoi luong se triet tieu dac tinh quan trong nhat cua VWAP: phan anh muc gia ma phan lon dong tien thuc su duoc khop lenh (volume clustering tai dau va cuoi phien).
3. **Thieu co che Reset VWAP theo Phien Intraday**:
   He thong khong co bo tich luy Rolling Accumulator de reset tong `Volume` va tong `Price * Volume` ve 0 tai thoi diem mo cua phien (vi du 09:30 EST cho US, hoac 17:00 New York cho Forex).

---

## 5. CHI TIET TARGET 4: DONG THOI, THREAD SAFETY, PHUC HOI MANG VA BACKPRESSURE

### 5.1 Co che Backoff va Retry tren Mang
Repo trien khai nhieu lop retry:
1. **Lop Loader Base (`agent/backtest/loaders/base.py:407-461`)**:
   Ham `retry_with_budget` ap dung co che sleep giam dan:
   ```python
   time.sleep(min(backoff[attempt], max(0.0, remaining)))
   ```
   Voi `DEFAULT_BACKOFF = (0.5, 1.5, 4.0)` ket hop voi deadline `monotonic()`. Neu qua deadline, loader nem ra `TimeoutError` thay vi bi treo vo han.
2. **Cac Loader Cu the**:
   - `tushare.py:35`: `_RATE_LIMIT_BACKOFF_SECONDS = (5.0, 20.0, 40.0)` nham dap ung cua so rate-limit 1 phut cua Tushare Pro API.
   - `etoro/client.py:43, 328`: `READ_BACKOFF = (0.5, 1.5, 4.0)` va uu tien doc header `Retry-After` tu phia may chu broker.
   - `tencent_loader.py:272`: Exponential backoff `_PAGE_BACKOFF * (2 ** attempt)` voi base = 0.6 giay.
3. **Triet ly Tai Live Runner (`LiveRunner` trong `runner.py:24-27`)**:
   Khong bao gio retry doi voi cac lenh lam thay doi trang thai broker (No-retry on mutating calls). Khi phat hien su co khong nhat quan trong qua trinh doi chieu (reconciliation), he thong lap tuc huy tick va fail-closed de tranh sinh lenh lap (double-order).

### 5.2 Kiem toan Backpressure va Hang doi Su kien
1. **Loi Hang doi Khong gioi han trong MessageBus (`agent/src/channels/bus/queue.py:16-17`)**:
   ```python
   self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue()
   self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue()
   ```
   `asyncio.Queue()` duoc khoi tao voi gia tri mac dinh `maxsize=0`.
   Dieu nay dong nghia hang doi khong co gioi han dung luong (unbounded). Neu client hoac broker day su kien voi toc do cao hon toc do xu ly cua Agent Loop, bo nho RAM se bi phinh to khong kiem soat ma khong he co tin hieu backpressure de yeu cau producer giam toc.
2. **Loi Lam roi Su kien (Silent Event Dropping) trong EventBus (`agent/src/session/events.py:257, 167-169`)**:
   ```python
   queue: asyncio.Queue[SSEEvent] = asyncio.Queue(maxsize=200)
   ...
   try:
       queue.put_nowait(event)
   except asyncio.QueueFull:
       logger.warning("EventBus queue full, dropping %s event for session %s", event.event_type, event.session_id)
   ```
   Moi client dang ky nhan SSE stream duoc cap mot hang doi co gioi han 200 su kien.
   Khi mang bi nghen hoac trinh duyet bi cham, hang doi bi day. `EventBus` xu ly bang cach **am tham vut bo su kien** (`drop`).
   Doi voi market data hoac trang thai lenh, viec vut bo su kien ma khong co co che gap recovery hay bao loi ve client se khien giao dien nguoi dung hien thi sai trang thai tai san hoac bo lo cac tin hieu quan trong.

### 5.3 Kiem toan Thread Safety
1. **IBKR Local TWS Pool (`agent/src/trading/connectors/ibkr/local.py:540-580`)**:
   Thiet ke tot: Su dung `threading.local()` va `threading.Lock()` de dam bao moi luong Worker chi so huu doc quyen mot ket noi socket rieng voi TWS, khong chia se socket giua cac luong, giup tranh hoan toan tinh trang race condition tren socket TCP.
2. **MT5 Goc tren Windows**:
   `MetaTrader5` SDK cua MetaQuotes la thu vien C su dung cac bien toan cuc cap tien trinh (process-global state), khong ho tro da luong an toan (thread-unsafe). Vibe-Trading da co lap bang cach spawn tien trinh rieng (`subprocess.run`) va khoa file `daily_order_lock`. Day la giai phap cach ly an toan.
3. **EventBus Cross-Thread Dispatch (`agent/src/session/events.py:123-125`)**:
   Su dung `self._loop.call_soon_threadsafe(self._safe_put, queue, event)` de chuyen su kien tu cac luong worker nen vao event loop chinh cua asyncio, tranh gay deadlock hoac loi bat dong bo cua Python runtime.

---

## 6. KHUYEN NGHI KIEN TRUC VA LO TRINH KHAC PHUC (RECOMMENDATIONS)

De nang cap he thong Data Pipeline cua Vibe-Trading dat chuan institutional va dap ung day du yeu cau ve Real-Time Candlestick cho Equities va XAU/USD:

1. **Xay dung Engine WebSocket / SSE Market Data Streamer Tap trung**:
   - Thay the co che HTTP short-polling 3 giay o `ForexLiveChart.tsx` bang mot FastAPI WebSocket endpoint: `/api/market-data/stream?symbols=XAU/USD,AAPL.US`.
   - Xay dung mot background service doc lap chay nen (daemon worker) duy tri ket noi persistent toi broker (MT5 tick stream hoac Exness/Binance WebSocket). Khi co tick moi, service tong hop va broadcast qua Redis Pub/Sub hoac in-memory broadcast channel toi cac client dang lang nghe.
2. **Xay dung Engine In-Memory Tick-to-Bar Aggregator Chuan xac**:
   - Thiet lap bo dem Ring Buffer tich luy cac tick gia (Timestamp, Bid, Ask, Last, Volume).
   - Tinh toan nen M1, M5 theo thoi gian thuc va tinh toan VWAP tich luy:
     $$\text{Cumulative VWAP}_t = \frac{\sum_{i=1}^t P_i \cdot V_i}{\sum_{i=1}^t V_i}$$
   - Reset bo tich luy nay chinh xac tai thoi diem mo cua phien cua tung loai tai san.
3. **Sua chua Triet de Loi Canh chinh Timezone**:
   - Tai `yfinance_loader.py:220-224`, sua `index.tz_localize(None)` thanh:
     `index = index.tz_convert("UTC").tz_localize(None)` (hoac giu nguyen aware UTC cho toan bo pipeline).
   - Tai `mt5_loader.py:169` va `mt5_worker.py:216`, can xac dinh mui gio server cua broker (thuong la `Europe/Nicosia` hoac EET/EEST cho Exness/IC Markets) va thuc hien chuyen doi mui gio tu broker server time sang UTC truoc khi tao timestamp.
4. **Mo rong Dinh nghia Ranh gioi Phien Giao dich trong `triggers.py`**:
   - Bo sung day du thong so cho `vn_equity` (`Asia/Ho_Chi_Minh`, 09:00 - 15:00, nghi trua 11:30 - 13:00).
   - Bo sung `hk_equity` (`Asia/Hong_Kong`, 09:30 - 16:00, nghi trua 12:00 - 13:00).
   - Bo sung `cn_equity` (`Asia/Shanghai`, 09:30 - 15:00, nghi trua 11:30 - 13:00).
   - Bo sung `forex_metals` (`America/New_York`, Sunday 17:00 to Friday 17:00, voi rollover break 17:00-18:00 hang ngay).
5. **Chuan hoa Toan hoc Tinh toan VWAP**:
   - Loai bo `+ 1.0` o mau so trong `agent/src/factors/base.py:468`. Thay bang co che mask `where(volume > 0)`.
   - Khi khong co cot `vwap` san, neu co `amount` va `volume` thi phai tinh $\text{amount} / \text{volume}$. Khong duoc phep thay the bang Typical Price $(H+L+C+O)/4$ ma van goi la VWAP ma khong canh bao.
6. **Kiem soat Hang doi va Backpressure**:
   - Ap dung `maxsize` hop ly cho `MessageBus.inbound` va `outbound` (vi du 1000).
   - Khi hang doi cua `EventBus` day, thay vi am tham bo roi su kien, phai phat sinh su kien `stream_overflow` thong bao cho client biet rang da mat du lieu va yeu cau client refresh snapshot.
