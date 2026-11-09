# BAO CAO KIEM TOAN TOAN DIEN: TAI CHINH, LOGIC GIAO DICH, DONG THOI VA AN NINH HE THONG

Nguoi thuc hien: explorer_finance_sec_1
Ngay kiem toan: 2026-11-08
Thu muc lam viec: D:\Vibe-Trading\.agents\teamwork\explorer_finance_sec_1\
Pham vi kiem toan: Toan bo ma nguon he thong Vibe-Trading (agent/, frontend/, backtest/, contracts/)

---

## 1. OBSERVATION (QUAN SAT TRUC TIEP THEO MUC DO NGHIEM TRONG)

Qua kiem tra ma nguon truc tiep tren he thong, phat hien tong cong 18 van de thuoc 3 nhom nghiep vu: Logic tai chinh & tinh toan so hoc, Xu ly dong thoi & tranh chap tai nguyen, va An ninh he thong & lo hong bao mat.

### Bang tong hop phat hien:

| Ma van de | Phan loai | Muc do | Tep tin va Dong ma nguon | Mo ta ngan gon |
|---|---|---|---|---|
| FIN-01 | Financial Logic | CRITICAL | `agent/src/live/enforcement.py:629-635` | Kiem tra Funding ceiling chan hoan toan tai khoan margin co leverage > 1.0 va chan lenh buy de dong vi the short |
| FIN-02 | Financial Logic | CRITICAL | `agent/src/trading/service.py:748`, `agent/src/live/sdk_order_gate.py:911-924` | Menh gia tien te khong duoc quy doi ty gia ve USD truoc khi kiem tra han muc (VND/KRW bi coi la USD) |
| FIN-03 | Financial / Precision | HIGH | `agent/src/portfolio/fx.py:30-36, 42-52`, `agent/src/portfolio/service.py:1096-1099, 1110-1120`, `agent/src/api/portfolio_routes.py:174-175` | Khong ho tro ty gia VND, chu dong xoa cache VND, nem PortfolioContractError danh sap Dashboard tai Viet Nam |
| FIN-04 | Financial Logic | HIGH | `agent/src/tools/vietnam_research_tool.py:141` | Tinh Free Cash Flow sai quy uoc dau ke toan Capex (nonnegative=(1,)) khien toan bo tinh toan FCF bao loi |
| FIN-05 | Financial Logic | MEDIUM | `agent/backtest/factor_costs.py:80-85, 270-274` | Thieu dinh nghia lai suat vay muon cho thi truong VN, KR, IN khi backtest vi the short, gay loi ValueError |
| FIN-06 | Precision / Math | MEDIUM | `agent/src/tools/trading_connector_tool.py:98-100`, `agent/src/trading/service.py:749`, `agent/src/trading/connectors/upbit/sdk.py:479` | Ep kieu float gay troi so le IEEE-754 voi crypto satoshis/EVM tokens; thieu chuan hoa lot size cho co phieu HK/CN |
| CONC-01 | Concurrency | HIGH | `agent/src/api/live_routes.py:1408-1433, 1456-1464` | Bat doi xung khoa: start co lock nhung stop khong co lock, gay race condition bo sot runner chay ngam mat kiem soat |
| CONC-02 | Concurrency | HIGH | `agent/src/api/swarm_routes.py:91-105`, `agent/src/swarm/runtime.py:388-402`, `agent/src/swarm/store.py:365-383` | Bien huy Swarm run tren RAM bi xoa sach khi restart server, khien cac run dang running bi be tac vinh vien |
| CONC-03 | Concurrency / Resource | HIGH | `agent/src/api/live_routes.py:804` | Live runner sinh ra mot phien tick session moi o moi phut (10.000 session/tuan) gay tran o dia va nghen EventBus |
| CONC-04 | Concurrency | MEDIUM | `agent/src/live/daily_count.py:13, 74-100` | daily_order_lock thieu khoa threading.Lock bao ve tien trinh tren Windows, gay loi PermissionError va tu choi lenh 409 |
| CONC-05 | Concurrency | MEDIUM | `agent/src/tools/__init__.py:42-45` | ToolRegistry._discover_subclasses thao tac tren bien toan cuc khong co thread lock, de loi xung dot khoi tao |
| SEC-01 | Security / SSRF | HIGH | `agent/src/api/qveris_routes.py:102-106`, `agent/src/tools/qveris_tool.py:220-221, 247` | Lo hong SSRF qua QVeris base_url cho phep quet mang noi bo RFC 1918, localhost va Cloud Metadata qua follow_redirects |
| SEC-02 | Security / SSRF | HIGH | `agent/src/api/settings_routes.py:288-300, 394-397, 930` | Lo hong SSRF qua Discovery model LLM khong kiem tra dai IP noi bo |
| SEC-03 | Concurrency / DoS | HIGH | `agent/src/agent/tool_lifecycle.py:519-528` | Goi f.result() tren ThreadPoolExecutor khong co timeout, gay dong bang luong worker vinh vien khi tool bi treo |
| SEC-04 | Security / Validation | MEDIUM | `agent/src/api/swarm_routes.py:91-92`, `agent/src/api/research_routes.py:111, 138`, `agent/src/api/paper_trade_routes.py:67-69` | Nhan raw dict bo qua validation Pydantic, de bi injection tham so bat hop le |
| SEC-05 | Resource Leak | MEDIUM | `agent/src/session/events.py:79, 101-106, 289-293`, `agent/src/channels/websocket.py:300, 312-323, 1094-1110` | Ro ri bo nho RAM trong EventBus buffer khong TTL va WebSocket stream text buffer khong duoc giai phong khi mat mang |
| SEC-06 | Security / Execution | MEDIUM | `agent/src/tools/bash_tool.py:60-120` | Khi bat shell tools, lenh thuc thi truc tiep tren cmd.exe cua may chu khong co co che sandbox he thong tep |
| SEC-07 | Security / Injection | LOW | `frontend/src/lib/api.ts:612-650` | Ghep chuoi truc tiep cac ID vao URL ma khong qua encodeURIComponent |

---

## 2. LOGIC CHAIN (CHUOI LAP LUAN TU QUAN SAT DEN KET LUAN)

### Chuoi 1: Xung dot kiem tra don bay tai khoan va dong vi the (FIN-01)
1. Quan sat: Tai `agent/src/live/enforcement.py`, dong 587-606 (Kiem tra muc 6 `Leverage cap`) cho phep ti le don bay:
   `if current_leverage > caps.max_leverage: return EnforceResult(allowed=False, reason="leverage_exceeded")`.
2. Quan sat tiep: Tai dong 629-635 (Kiem tra muc 8 `Funding ceiling`):
   ```python
   post_exposure = (state.gross_exposure_usd or 0.0) + (intent.notional_usd or 0.0)
   if intent.side == "buy" and post_exposure > caps.account_funding_usd:
       return EnforceResult(allowed=False, reason="funding_ceiling_exceeded", ...)
   ```
3. Lap luan:
   - Khi mot nha dau tu su dung tai khoan Margin voi `max_leverage = 2.0` va von tu co `account_funding_usd = 10,000 USD`. Kiem tra 6 cho phep vi the toi da 20,000 USD. Nhung kiem tra 8 ngay sau do lai bat buoc tong vi the sau lenh khong duoc vuot qua 10,000 USD. Dieu nay lam vo hieu hoa hoan toan tinh nang don bay da duoc phe duyet o kiem tra 6.
   - Khi tai khoan dang co vi the Short (gross exposure > 0) va gui lenh `buy` de dong vi the (Buy to Cover), day la hanh dong lam giam tong rui ro thi truong. Nhung vi `intent.side == "buy"` va cong thuc cong don `post_exposure = gross_exposure + notional`, he thong tinh toan tong vi the tang len thay vi giam xuong, dan den viec chan luon lenh dong vi the thoat lo cua nha dau tu.
4. Ket luan: Logic kiem tra Funding ceiling bi loi thiet ke, phu quyet co che don bay va chan dung lenh thoat vi the Short.

### Chuoi 2: Mat dong nhat don vi tien te gay lech han muc nghiem trong (FIN-02)
1. Quan sat: Tai `agent/src/trading/service.py:748`:
   `intent = OrderIntent(symbol=symbol, side=side, quantity=float(qty), notional_usd=float(notional) if notional else None, ...)`
2. Quan sat tiep: Tai `agent/src/live/sdk_order_gate.py:911-924`, ham `_validate_intent` dua truc tiep `intent.notional_usd` vao bo kiem soat rui ro `evaluate_order(intent=intent, ...)`.
3. Lap luan:
   - Nguoi dung dat lenh mua co phieu tren san chung khoan Viet Nam (VND) voi gia tri 50,000,000 VND (~1,920 USD).
   - Gia tri `notional` 50,000,000 duoc truyen truc tiep vao truong `notional_usd`.
   - He thong quan ly rui ro danh gia lenh nay co gia tri 50 trieu USD, vuot xa moi han muc toi da (vi du trann lenh 50,000 USD), khien lenh bi he thong tu choi lap tuc.
   - Nguoc lai, doi voi cac dong tien co menh gia cao hon USD nhu GBP (1 GBP ~ 1.3 USD), mot lenh tri gia 10,000 GBP chi duoc tinh la 10,000 USD, lam thoat khoi trann kiem soat 30% gia tri rui ro thuc te.
4. Ket luan: Thieu co che quy doi ty gia tien te cua tai khoan ve USD truoc khi nap vao `OrderIntent`, gay te liet toan bo giao dich phi USD hoac gay thung luoi quan ly rui ro.

### Chuoi 3: Do vo he thong Portfolio tai thi truong Viet Nam (FIN-03)
1. Quan sat: Tai `agent/src/portfolio/fx.py:30-36`:
   `SUPPORTED_CURRENCIES = ("USD", "CNY", "HKD", "EUR")`.
2. Quan sat tiep: Tai dong 42-52, ham `convert()` kiem tra:
   `if base not in SUPPORTED_CURRENCIES or quote not in SUPPORTED_CURRENCIES: raise PortfolioContractError(...)`.
3. Quan sat tiep: Tai `agent/src/portfolio/service.py:1096-1099`:
   ```python
   # Line 1098: Xoa cache VND neu co
   self._fx_rates.pop("VND", None)
   ```
4. Quan sat tiep: Tai `agent/src/api/portfolio_routes.py:174-175`, endpoint `/api/portfolio/refresh` bat buoc quy doi toan bo tai san ve USD.
5. Lap luan:
   - Khi tai khoan nguoi dung nam giu bat ky tai san hoac tien mat nao co ky hieu VND, he thong goi `to_usd(amount, "VND")`.
   - Ham nem ngay lap tuc ngoai le `PortfolioContractError: Unsupported currency: VND`.
   - Endpoint `/api/portfolio/refresh` khong bat ngoai le nay ma de bung ra HTTP 500/503.
6. Ket luan: Toan bo chuc nang danh muc va dashboard tai san tai Viet Nam bi dinh chi hoan toan.

### Chuoi 4: Race condition chet nguoi trong quan ly tien trinh Live Runner (CONC-01)
1. Quan sat: Tai `agent/src/api/live_routes.py:1408-1433`:
   Endpoint `start_runner_endpoint` su dung `async with _runner_start_lock:` de dong bo hoa viec khoi chay.
2. Quan sat tiep: Tai `agent/src/api/live_routes.py:1456-1464`:
   Endpoint `stop_runner_endpoint` chi goi `await runner.stop()` va `_active_runners.pop(broker, None)` ma HOAN TOAN KHONG SU DUNG `_runner_start_lock`.
3. Lap luan:
   - Khi client gui lenh Stop ngay khi lenh Start dang o giua qua trinh khoi tao (dang ket noi broker, khoi tao gate), lenh Stop truy cap vao `_active_runners` khi runner chua duoc add vao dict.
   - Lenh Stop tra ve thanh cong vi khong tim thay runner trong dict.
   - Ngay sau do, lenh Start hoan tat va add runner vua tao vao `_active_runners`.
   - Runner nay se tro thanh runner mo coi, chay ngam vo thoi han tren tai khoan tien that ma nguoi dung khong the dung lai bang giao dien web tru khi khoi dong lai toan bo may chu.
4. Ket luan: Thieu dong bo khoa hai chieu gay ra race condition nghiem trong trong viec quan ly tien trinh giao dich live.

### Chuoi 5: Lo hong SSRF nghiem trong trong QVeris va Settings (SEC-01, SEC-02)
1. Quan sat: Tai `agent/src/api/qveris_routes.py:102-106`:
   Ham `_validate_base_url` chi kiem tra chuoi bat dau bang `http://` hoac `https://`:
   `if not (url.startswith("http://") or url.startswith("https://")): raise HTTPException(...)`
2. Quan sat tiep: Tai `agent/src/tools/qveris_tool.py:247`:
   Client httpx duoc cau hinh: `httpx.AsyncClient(base_url=base_url, follow_redirects=True, timeout=10.0)`.
3. Lap luan:
   - Kiem tra tren hoan toan bo qua viec phan giai ten mien DNS va kiem tra dia chi IP dich.
   - Ke tan cong co the truyen vao cac dai dia chi noi bo nhu:
     - `http://127.0.0.1:8000/` (Dich vu noi bo)
     - `http://169.254.169.254/latest/meta-data/` (AWS/GCP Cloud Metadata de danh cap IAM credentials)
     - `http://192.168.1.1/` (Router mang noi bo)
   - Do co `follow_redirects=True`, ngay ca khi chan duoc IP ban dau, may chu nan nhan van bi dan duong toi cac dich vu nhay cam ben trong mang LAN.
4. Ket luan: Lo hong SSRF co do nguy hiem cao, cho phep xam nhap he thong mang noi bo va danh cap thong tin xac thuc cloud.

---

## 3. DEEP DIVE ON FINANCIAL LOGIC, POSITION SIZING & CONCURRENCY

### 3.1. Kiem tra Logic Rui ro & Gioi han Vi the (Funding Ceiling vs Leverage)
- File: `agent/src/live/enforcement.py`
- Phan tich ma nguon:
```python
# Dong 629-635
post_exposure = (state.gross_exposure_usd or 0.0) + (intent.notional_usd or 0.0)
if intent.side == "buy" and post_exposure > caps.account_funding_usd:
    return EnforceResult(
        allowed=False,
        reason="funding_ceiling_exceeded",
        details={"post_exposure": post_exposure, "funding_usd": caps.account_funding_usd},
    )
```
- Khac phuc de xuat:
  1. Su dung `caps.account_funding_usd * caps.max_leverage` lam trann vi the thuc te thay vi chi dung `account_funding_usd`.
  2. Xac dinh ro vi the hien tai: neu vi the hien tai la Short (`current_position < 0`) va lenh la `buy`, thi lenh nay lam GIAM vi the chu khong phai lam tang `post_exposure`.
  ```python
  # De xuat sua doi
  effective_ceiling = caps.account_funding_usd * (caps.max_leverage or 1.0)
  if intent.side == "buy":
      if state.net_position_units and state.net_position_units < 0:
          # Day la lenh dong vi the Short (Cover), giam rui ro -> Luon cho phep hoac tinh lai net exposure
          new_gross = max(0.0, (state.gross_exposure_usd or 0.0) - (intent.notional_usd or 0.0))
      else:
          new_gross = (state.gross_exposure_usd or 0.0) + (intent.notional_usd or 0.0)
      if new_gross > effective_ceiling:
          return EnforceResult(allowed=False, reason="funding_ceiling_exceeded", ...)
  ```

### 3.2. Sai lech Tien te Giao dich trong Order Intent
- File: `agent/src/trading/service.py` va `agent/src/live/sdk_order_gate.py`
- Phan tich ma nguon:
  Khi nha dau tu dat lenh qua `TradeExecutionService.execute_order()`:
```python
# agent/src/trading/service.py:748
intent = OrderIntent(
    symbol=symbol,
    side=side,
    quantity=float(qty),
    notional_usd=float(notional) if notional else None,
    order_type=order_type,
    limit_price=float(limit_price) if limit_price else None,
)
```
  Gia tri `notional` nay lay tu input cua broker account (vi du VND tren DNSE, KRW tren Upbit, HKD tren Longbridge).
  Vao den `sdk_order_gate.py:911-924`, he thong coi day la USD thuc su.
- Khac phuc de xuat:
  Can tich hop module `FXRateService` de quy doi gia tri `notional` sang USD dua theo don vi tien te co so cua ma co phieu/broker truoc khi tao `OrderIntent`.

### 3.3. Tinh toan Free Cash Flow trong Cong cu Phan tich Viet Nam
- File: `agent/src/tools/vietnam_research_tool.py:141`
- Ma nguon hien tai:
```python
metric("free_cash_flow", ["operating_cash_flow", "capital_expenditure"], lambda c, k: c - k, "VND", nonnegative=(1,))
```
- Phan tich loi:
  Theo Chuan muc Ke toan Viet Nam (VAS) va IFRS, trong bao cao luu chuyen tien te, chi tieu "Tien chi de mua sam, xay dung TSCĐ va cac tai san dai han khac" (Capex) da mang san DAU AM (the hien dong tien di ra).
  Khi nha phan tich truyen vao gia tri am cua Capex, ham kiem tra `nonnegative=(1,)` lap tuc nem loi vi tham so thu 2 (Capex) mang gia tri am. Neu truyen gia tri duong, phep tinh `c - k` se dung; nhung do nguon du lieu tu cac cong ty chung khoan (SSI, TCBS, Vietcap) cung cap Capex duoi dang so am hoac duong tuy nha cung cap, viec kiem tra bat buoc khong am da gay vo toan bo chi so FCF.
- Khac phuc de xuat:
  Bo rang buoc `nonnegative=(1,)` va chuan hoa cong thuc: `lambda c, k: c - abs(k)`.

### 3.4. Xu ly So thap phan (Precision & Lot Sizing)
- Cac he thong giao dich crypto nhu Upbit, Binance su dung don vi le rat nho (satoshis, gwei), con co phieu Hong Kong/Trung Quoc bat buoc phai theo lo (Board Lot: 100, 500 co phieu).
- Ma nguon hien tai o `agent/src/tools/trading_connector_tool.py` va `agent/src/trading/connectors/upbit/sdk.py:479` su dung phep chia va nhan `float` tieu chuan cua Python.
- Can chuyen sang `decimal.Decimal` cho tat ca phep tinh so du va khoi luong, kem theo buoc `round_to_lot_size(qty, lot_size)`.

### 3.5. Race Condition va Khoa Tien trinh
1. **Runner Start/Stop Inconsistency (`agent/src/api/live_routes.py`)**:
   Can bao boc ca ham `stop_runner_endpoint` bang `async with _runner_start_lock:` de dam bao khong co runner nao duoc tao ra trong khi tien trinh dung dang quet danh sach.
2. **Be tac Swarm Run khi Restart Server (`agent/src/api/swarm_routes.py`, `agent/src/swarm/runtime.py`)**:
   Bien `_cancel_events: dict[str, asyncio.Event]` chi luu tren RAM cua server. Khi server bi restart hoac crash, dict nay trong rong trong khi cac tap tin `run.json` van o trang thai `"running"`.
   Khac phuc: Khi API server khoi dong lai, quet toan bo cac run trong `SwarmStore` co trang thai `"running"`, tu dong chuyen thanh `"interrupted"` hoac `"failed"` kem ly do "Server restarted".
3. **Bung no session rac trong Live Runner (`agent/src/api/live_routes.py:804`)**:
   Moi phut runner goi `svc.create_session(title=f"live-decision:{broker}")`. Cac session nay chua hang ngan log phan tich va duoc ghi truc tiep vao SQLite/EventBus. Sau 1 ngay tao ra 1,440 session, 1 tuan hon 10,000 session.
   Khac phuc: Tai su dung mot `live_run_session_id` duy nhat cho moi phien giao dich cua broker va dinh ky don dep ban ghi cu hon 7 ngay.

---

## 4. DEEP DIVE ON SECURITY POSTURE & VULNERABILITIES

### 4.1. Lo hong SSRF qua QVeris va LLM Model Discovery (SEC-01, SEC-02)
- Diem yeu cot loi:
  He thong nhan URL tu nguoi dung/client va gui yeu cau HTTP den do ma khong kiem tra xem dia chi IP tuong ung co nam trong dai IP rieng tu (Private IP) hoac IP dac biet hay khong.
- Dia chi co the bi loi dung:
  - `127.0.0.1`, `localhost` (Dich vu noi bo)
  - `169.254.169.254` (Cloud Metadata AWS, GCP, Azure)
  - `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16` (Mang cuc bo)
  - `::1` (IPv6 localhost)
- Giai phap triet de:
  Xay dung mot ham kiem tra IP an toan (`is_safe_public_url`) su dung `ipaddress.ip_address` sau khi phan giai DNS qua `socket.getaddrinfo`, dong thoi vo hieu hoa chuyen huong tu dong (`follow_redirects=False`) hoac kiem tra lai IP o moi lan chuyen huong.

### 4.2. Treo Luong Worker trong Tool Lifecycle (SEC-03)
- File: `agent/src/agent/tool_lifecycle.py:519-528`
- Ma nguon hien tai:
```python
future = executor.submit(tool.run, **kwargs)
result = future.result()  # KHONG CO TIMEOUT
```
- Rui ro:
  Neu mot cong cu goi ra ben ngoai bi nghen mang (socket hang) hoac xay ra deadlock ben trong, luong worker nay se bi chiem dung vo thoi han. Khi tat ca cac luong trong ThreadPoolExecutor bi chiem dung, Agent Loop se ngung hoat dong hoan toan.
- Giai phap:
  Bat buoc phai truyen timeout: `result = future.result(timeout=timeout_seconds)`.

### 4.3. Bo qua Xac thuc Du lieu Dau vao bang Raw Dict (SEC-04)
- File: `agent/src/api/swarm_routes.py:91-92`, `agent/src/api/research_routes.py:111`, `agent/src/api/paper_trade_routes.py:67-69`
- Vi du o `swarm_routes.py`:
```python
@router.post("/runs")
async def create_swarm_run(payload: dict = Body(...)):
```
- Rui ro:
  Viec tiep nhan `payload: dict` bo qua co che kiem tra kieu, do dai va gia tri bien hop le cua Pydantic. Ke tan cong co the gui cac payload co kich thuoc khong lo gay can kiet bo nho (Memory Exhaustion) hoac truyen cac kieu du lieu gay loi runtime unhandled exception.
- Giai phap:
  Dinh nghia cac lop `Pydantic BaseModel` nghiem ngat cho 100% cac endpoint API.

### 4.4. Ro ri Bo nho trong EventBus va WebSocket Buffers (SEC-05)
- File: `agent/src/session/events.py:79, 101-106`
  `_buffers: dict[str, list[Event]]` luu tru 500 su kien gan nhat cho moi session. Khi he thong chay lien tuc voi hang nghin session live tick sinh ra moi ngay, `_buffers` tich luy hang tram nghin object khong bao gio duoc giai phong boi garbage collection vi van con tham chieu trong dict toan cuc.
- File: `agent/src/channels/websocket.py:300, 312-323`
  `_stream_text_buffers: dict[str, str]` ghep noi van ban streaming. Neu client ngat ket noi dot ngot truoc khi nhan duoc goi tin ket thuc phien stream, key cua phien do se nam lai vinh vien trong bo nho.
- Giai phap:
  1. Su dung `collections.OrderedDict` hoac `cachetools.TTLCache` voi thoi gian song (TTL) ro rang cho cac buffer su kien.
  2. Bo sung khoi `finally` trong WebSocket handler de xoa sach moi buffer lien quan den connection khi socket dong.

---

## 5. EXACT CODE SNIPPETS, FILE PATHS & OFFENDING LINE NUMBERS

### 5.1. File: `agent/src/live/enforcement.py` (Lines 629-635)
```python
# HIEN TAI:
post_exposure = (state.gross_exposure_usd or 0.0) + (intent.notional_usd or 0.0)
if intent.side == "buy" and post_exposure > caps.account_funding_usd:
    return EnforceResult(
        allowed=False,
        reason="funding_ceiling_exceeded",
        details={"post_exposure": post_exposure, "funding_usd": caps.account_funding_usd},
    )

# SUA LAI CHUAN XAC:
leverage = caps.max_leverage if caps.max_leverage and caps.max_leverage > 0 else 1.0
effective_funding_limit = caps.account_funding_usd * leverage

# Neu la lenh BUY nhung dang co vi the SHORT -> Day la lenh dong/giam vi the
is_closing_short = (state.net_position_units is not None and state.net_position_units < 0 and intent.side == "buy")
if is_closing_short:
    post_exposure = max(0.0, (state.gross_exposure_usd or 0.0) - (intent.notional_usd or 0.0))
else:
    post_exposure = (state.gross_exposure_usd or 0.0) + (intent.notional_usd or 0.0)

if intent.side == "buy" and not is_closing_short and post_exposure > effective_funding_limit:
    return EnforceResult(
        allowed=False,
        reason="funding_ceiling_exceeded",
        details={"post_exposure": post_exposure, "funding_limit": effective_funding_limit},
    )
```

### 5.2. File: `agent/src/portfolio/fx.py` (Lines 30-36, 42-52)
```python
# HIEN TAI:
SUPPORTED_CURRENCIES = ("USD", "CNY", "HKD", "EUR")

# SUA LAI CHUAN XAC:
SUPPORTED_CURRENCIES = ("USD", "CNY", "HKD", "EUR", "VND", "KRW", "JPY", "GBP")

# Bo sung ty gia co dinh/du phong cho VND trong truong hop Frankfurter API khong co du lieu:
DEFAULT_FALLBACK_RATES = {
    "USD": 1.0,
    "VND": 25450.0,
    "KRW": 1380.0,
    "JPY": 155.0,
    "CNY": 7.24,
    "HKD": 7.82,
    "EUR": 0.92,
    "GBP": 0.79,
}
```

### 5.3. File: `agent/src/portfolio/service.py` (Lines 1096-1099)
```python
# HIEN TAI:
# Co doan ma chu dong xoa VND khoi cache ty gia:
self._fx_rates.pop("VND", None)

# SUA LAI CHUAN XAC:
# Tuyet doi khong xoa VND, ma cap nhat ty gia hop le tu nguon fallback hoac API noi dia:
if "VND" not in self._fx_rates:
    self._fx_rates["VND"] = DEFAULT_FALLBACK_RATES["VND"]
```

### 5.4. File: `agent/src/tools/vietnam_research_tool.py` (Line 141)
```python
# HIEN TAI:
metric("free_cash_flow", ["operating_cash_flow", "capital_expenditure"], lambda c, k: c - k, "VND", nonnegative=(1,))

# SUA LAI CHUAN XAC:
# Capex trong bao cao luu chuyen tien te co the la so am hoac duong, dung abs de dam bao tinh dung FCF:
metric("free_cash_flow", ["operating_cash_flow", "capital_expenditure"], lambda c, k: c - abs(k), "VND")
```

### 5.5. File: `agent/src/api/live_routes.py` (Lines 1456-1464)
```python
# HIEN TAI:
@router.post("/runners/{broker}/stop")
async def stop_runner_endpoint(broker: str):
    runner = _active_runners.get(broker)
    if not runner:
        raise HTTPException(status_code=404, detail=f"No active runner for {broker}")
    await runner.stop()
    _active_runners.pop(broker, None)
    return {"status": "stopped", "broker": broker}

# SUA LAI CHUAN XAC:
@router.post("/runners/{broker}/stop")
async def stop_runner_endpoint(broker: str):
    async with _runner_start_lock:
        runner = _active_runners.get(broker)
        if not runner:
            raise HTTPException(status_code=404, detail=f"No active runner for {broker}")
        await runner.stop()
        _active_runners.pop(broker, None)
        return {"status": "stopped", "broker": broker}
```

### 5.6. File: `agent/src/api/qveris_routes.py` (Lines 102-106)
```python
# HIEN TAI:
def _validate_base_url(url: str) -> None:
    if not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(status_code=400, detail="Base URL must start with http:// or https://")

# SUA LAI CHUAN XAC (CHONG SSRF TRIET DE):
import ipaddress
import socket
from urllib.parse import urlparse

def _validate_base_url(url: str) -> None:
    if not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(status_code=400, detail="Base URL must start with http:// or https://")
    parsed = urlparse(url)
    hostname = parsed.hostname
    if not hostname:
        raise HTTPException(status_code=400, detail="Invalid host in URL")
    
    # Chan localhost va metadata truc tiep
    if hostname.lower() in ("localhost", "127.0.0.1", "::1", "169.254.169.254"):
        raise HTTPException(status_code=400, detail="Access to internal hosts is forbidden")
        
    try:
        addr_info = socket.getaddrinfo(hostname, None)
        for family, _, _, _, sockaddr in addr_info:
            ip = ipaddress.ip_address(sockaddr[0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                raise HTTPException(status_code=400, detail="Access to private or local IP ranges is forbidden")
    except socket.gaierror:
        raise HTTPException(status_code=400, detail="Failed to resolve hostname")
```

---

## 6. CAVEATS (CAC VUNG CHUA KHUA KHAO VA GIA DINH)

1. **Phan tich tinh ma nguon (Read-only static analysis)**:
   Cuoc kiem toan nay duoc thuc hien duoi quy trinh nghiem ngat chi doc ma nguon de dam bao tinh toan ven tuyet doi cua he thong. Cac loi race condition duoc chung minh dua tren phan tich luong thuc thi (execution flow) va khoa dong bo (synchronization primitives), chua duoc chay thuc te tren san giao dich that de tranh rui ro phat sinh lenh that ngoai y muon.
2. **Du lieu ty gia FX thoi gian thuc**:
   Gia dinh rang moi truong san pham co ket noi Internet on dinh de lay ty gia ngoai te. Trong truong hop mat mang hoac bi chan dia ly, he thong bat buoc phai co bang ty gia du phong (fallback rates) de khong lam sap ung dung.
3. **Phu thuoc vao SDK ben thu ba**:
   Cac broker SDK nhu Upbit, Longbridge, Alpaca, Dhan co co che xu ly so thap phan rieng biet. Du an can bo sung lop abstraction layer de chuan hoa so thap phan truoc khi truyen vao cac SDK nay.

---

## 7. CONCLUSION (KET LUAN VA HUONG XU LY)

He thong Vibe-Trading co kien truc phong phu va ho tro nhieu thi truong, tuy nhien ton tai cac diem yeu cot tu ve ca logic nghiep vu tai chinh va an toan he thong can duoc uu tien khac phuc ngay trong cac Milestone tiep theo:

1. **Uu tien 1 (Sua ngay cac loi chan nghiep vu - Critical/High)**:
   - Sua loi Funding ceiling tai `agent/src/live/enforcement.py` de cho phep tai khoan don bay hoat dong va cho phep dong vi the short.
   - Bo sung co che quy doi ty gia tien te cua tai khoan ve USD trong `OrderIntent`.
   - Them VND vao danh sach tien te duoc ho tro trong `agent/src/portfolio/fx.py` va go bo dong ma xoa cache VND tai `portfolio/service.py`.
   - Sua phep tinh FCF trong `agent/src/tools/vietnam_research_tool.py`.
2. **Uu tien 2 (Gia co an ninh va xu ly dong thoi - High/Medium)**:
   - Bo sung khoa `_runner_start_lock` vao endpoint stop runner tai `live_routes.py`.
   - Chan SSRF toan dien tren tat ca cac endpoint nhan URL ben ngoai (QVeris, LLM Base URL).
   - Dat timeout bat buoc cho `future.result()` trong `tool_lifecycle.py`.
   - Chuyen doi cac endpoint nhan raw dict sang schema Pydantic BaseModel.
   - Bo sung co che thu don session live runner va dat TTL cho EventBus buffer.

---

## 8. VERIFICATION METHOD (PHUONG PHAP KIEM THU DOC LAP)

Cac ky su kiem thu hoac auditor doc lap co the kiem chung cac phat hien tren bang cac buoc sau:

1. **Kiem chung FIN-01 (Funding ceiling block margin & cover)**:
   Chay script Python kiem tra `evaluate_order`:
   ```bash
   python -c "from agent.src.live.enforcement import evaluate_order; from agent.src.live.sdk_order_gate import OrderIntent, AccountCaps, PortfolioLiveState; print(evaluate_order(OrderIntent(symbol='AAPL', side='buy', quantity=10, notional_usd=2000), AccountCaps(account_funding_usd=1000, max_leverage=3.0), PortfolioLiveState(gross_exposure_usd=0.0)))"
   ```
   *Ket qua ky vong*: Tra ve `allowed=False, reason='funding_ceiling_exceeded'` mac du `max_leverage=3.0` cho phep vi the toi 3,000 USD.

2. **Kiem chung FIN-03 (VND gay sap Portfolio)**:
   Chay script chuyen doi ty gia:
   ```bash
   python -c "from agent.src.portfolio.fx import FXRateService; fx = FXRateService(); fx.to_usd(1000000.0, 'VND')"
   ```
   *Ket qua ky vong*: Nem ngay `PortfolioContractError: Unsupported currency: VND`.

3. **Kiem chung FIN-04 (Loi tinh Capex FCF)**:
   Chay tinh toan metric FCF:
   ```bash
   python -c "from agent.src.tools.vietnam_research_tool import metric; fn = metric('free_cash_flow', ['operating_cash_flow', 'capital_expenditure'], lambda c, k: c - k, 'VND', nonnegative=(1,)); fn(100.0, -20.0)"
   ```
   *Ket qua ky vong*: Nem ngoai le vi Capex la so am (-20.0 khong thoa man `nonnegative=(1,)`).

4. **Kiem chung SEC-01 (SSRF bypass)**:
   Chay kiem tra ham `_validate_base_url`:
   ```bash
   python -c "from agent.src.api.qveris_routes import _validate_base_url; _validate_base_url('http://169.254.169.254/latest/meta-data/')"
   ```
   *Ket qua ky vong*: Ham vuot qua ma khong nem loi, xac nhan he thong co the bi SSRF tan cong Cloud Metadata.
