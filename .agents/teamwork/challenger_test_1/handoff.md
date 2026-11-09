# BAO CAO KIEM THU THUC NGHIEM TOAN DIEN HE THONG (EMPIRICAL CHALLENGER REPORT)

- Co quan thuc hien: Empirical Challenger Agent (challenger_test_1)
- Vai tro: critic, specialist
- Pham vi kiem thu: Toan bo cac bo test suites hien co, cac engine tinh toan tai chinh, precision so hoc, quan ly concurrency live runner va ket noi SQLite trong he thong Vibe-Trading.
- Thoi diem hoan tat: 2026-11-08T13:37:00Z
- Tap tin harness tao moi: `agent/tests/test_empirical_stress_harness.py`

---

## 1. OBSERVATION (QUAN SAT THUC TE THEO SO LIEU THUC NGHIEM)

Moi so lieu duoi day deu duoc thu thap truc tiep tu qua trinh thuc thi lenh thuc te tren terminal Windows, khong su dung so lieu gia dinh hay hardcode:

### 1.1. Ket qua chay Test Suites Frontend
- Lenh thuc thi: `cd frontend; npm run test:run` (vitest run)
  * Exit code: 0
  * Tong so test files: 125/125 passed (100%)
  * Tong so test cases: 1.136/1.136 passed (100%)
  * Thoi gian thuc thi: 153.12s
- Lenh thuc thi build & typecheck: `cd frontend; npm run build` (`tsc -b && vite build`)
  * Exit code: 0
  * TypeScript typecheck: 0 loi bien dich.
  * Vite bundling: 3.260 modules transformed, xuat dist thanh cong trong 5.96s.

### 1.2. Ket qua kiem tra & chay Test Suites Backend (Python / Pytest)
- Su co thu vien thieu hut ban dau tren moi truong host:
  * Khi chay thu thap test lan dau (`python -m pytest --collect-only agent/tests`), he thong phat hien 68 loi import module do thieu cac goi phu thuoc khai bao trong `pyproject.toml`: `matplotlib`, `python-docx`, `openpyxl`, `langchain-core`, `nh3`, `reportlab`, `pypdfium2`, `ccxt`.
  * Sau khi bo sung cac dependency chuan tren moi truong, lenh thu thap test `python -m pytest --collect-only -q agent/tests` dat ket qua hoan hao:
    `21876 tests collected in 18.13s` (0 loi collection tren toan bo 21.876 test cases).
- Ket qua chay nhom test core portfolio va vietnam (`python -m pytest -k "portfolio or vietnam" agent/tests/ --maxfail=10 -q`):
  * Exit code: 0
  * So test cases vuot qua: 710 passed, 8 skipped, 21.166 deselected trong 33.69s.

### 1.3. Ket qua chay Bo Test Harness Stress-Test Thuc Nghiem
Tien hanh thiet ke va thuc thi file harness doc lap tai `agent/tests/test_empirical_stress_harness.py`:
- Lenh thuc thi: `python -m pytest agent/tests/test_empirical_stress_harness.py -v -s`
- Exit code: 0 (14/14 tests passed trong 16.68s)
- Cac so lieu stress-test do luong truc tiep:
  * **Float Drift trong phi giao dich**:
    Qua 50.000 giao dich voi khoi luong 100 cp gia 54.321 VND, phep tinh `float` IEEE 754 tich luy tong phi la `543209999.999750 VND`, trong khi chuan `Decimal` la `543210000.000000 VND`. Do lech troi so hoc do luong duoc la `0.0002495 VND`.
  * **Xung dot Concurrency tren SQLite (Database is locked)**:
    Khi 16 luong dong thoi ghi va doc 800 snapshot vao SQLite qua `PortfolioStore`, ghi nhan 794 thao tac thanh cong va 6 thao tac bi that bai voi loi verbatim:
    `sqlite3.OperationalError: database is locked`.
  * **Deduplication cua Live Runner Start Lock**:
    Khi gui dong thoi 20 requests bat dong bo khoi chay cung mot broker (`binance`), he thong lock `_get_runner_start_lock` dam bao chinh xac: 1 task duoc khoi tao thanh cong (`Started=1`), 19 task bi tu choi an toan voi co `already_running=True` (`Rejected=19`).
  * **Co che Fail-Closed khi thieu ty gia VND**:
    Ham `build_rates(Decimal("7.24"), Decimal("7.82"))` chi bao gom USD, CNY, HKD. Khi goi `to_usd(Decimal("25000000"), "VND", rates)`, he thong nem ngoai le chinh xac:
    `src.portfolio.compatibility.PortfolioContractError: portfolio FX conversion is not available for: VND`.
  * **Loi quy uoc dau am Capex trong Vietnam Research Tool**:
    Tai `agent/src/tools/vietnam_research_tool.py`, metric Free Cash Flow su dung rang buoc `nonnegative=(1,)` cho capex. Khi du lieu bao cao ghi nhan capex theo quy uoc dong tien am (`-10000000`), metric bi danh dau tu choi voi ly do `reason = "expected_nonnegative_magnitude"`.
  * **Phan loai Retryability va Exponential Backoff**:
    `ProviderStreamError.retryable` xac dinh chinh xac loi mang/429/5xx la retryable (`True`), loi 400/401/403/404/422 la non-retryable (`False`). `SchedulerKernel` tinh toan backoff luy thua chuan: 1s, 2s, 4s, 8s, 16s, 30s (clamp tai max delay 30s) va chan tran so mu tai exponent 62.

---

## 2. LOGIC CHAIN

Tu cac quan sat thuc nghiem, chuoi suy luan ky thuat duoc thiet lap nhu sau:

1. **Ve nguy co khoa chet du lieu trong SQLite (RES-01 / SQLite Concurrency)**:
   - *Quan sat*: Khi 16 worker dong thoi thuc hien 800 transaction doc/ghi, 6 transaction bi loi `database is locked`.
   - *Suy luan*: SQLite mac dinh su dung rollback journal (DELETE journal mode) va co che busy timeout rat ngan (hoac bang 0 ms tren ket noi moi tao). Khi co nhieu tien trinh/luong cung ghi, tien trinh ghi thu hai khong the dat duoc SHARED/EXCLUSIVE lock tren file database va lap tuc nem `OperationalError`.
   - *He qua*: Neu nguoi dung mo nhieu tab trinh duyet hoac background workers chay dong thoi cap nhat danh muc, he thong se nem loi 500 ra giao dien.

2. **Ve do sai lech so hoc khi tich luy giao dich (Float vs Decimal Precision)**:
   - *Quan sat*: Qua 50.000 lenh, do lech giua float va Decimal la 0.0002495 don vi tien te.
   - *Suy luan*: Cac engine backtest (`vietnam_equity.py:495`, `crypto.py:157`) tinh phi truc tiep bang kieu `float`. Voi tan suat giao dich cao (high-frequency hoac backtest dai han hang trieu bars), su tich luy sai so dau phay dong (IEEE 754) se dan den lech so du tai khoan thuc te voi so du tinh toan.

3. **Ve su co Portfolio Refresh tai thi truong Viet Nam (NUM-01 / FX Feed Gap)**:
   - *Quan sat*: Frankfurter v1 chi tra ve ty gia cac dong tien chinh (CNY, HKD, EUR), khong co VND. `build_rates` khong co tham so mac dinh cho VND.
   - *Suy luan*: Ham `compatibility.py:239-243` duoc thiet ke fail-closed: moi loai tien te khong co ty gia trong rates map se nem `PortfolioContractError`. Do do, bat ky tai khoan nao co tien te `VND` khi goi refresh se lam sap API `/api/portfolio/refresh` voi loi HTTP 503.

4. **Ve su khong dong nhat trong ghi nhan dong tien Capex (NUM-03 / Financial Metrics)**:
   - *Quan sat*: `vietnam_research_tool.py:141` khai bao `metric("free_cash_flow", ..., nonnegative=(1,))`.
   - *Suy luan*: Trong nhieu he thong ke toan quoc te va mot so bao cao tai chinh Viet Nam, dong tien chi mua sam tai san co dinh (Capex) duoc ghi duoi dang so am the hien dong tien ra (cash outflow). Rang buoc `nonnegative=(1,)` chan tat ca cac gia tri am, khien chi so Free Cash Flow bi tra ve `null` va `reason = "expected_nonnegative_magnitude"`, lam hong phan tich co phieu.

5. **Ve do an toan concurrency cua Live Runner Start**:
   - *Quan sat*: 20 request dong thoi toi live runner start lock duoc chan chi con duy nhat 1 request thanh cong, 19 request tu choi.
   - *Suy luan*: `_runner_start_lock` giai quyet triet de nguy co duplicate worker khi chay tren cung 1 event loop. Tuy nhien, can luu y bien `_runner_start_lock` toan cuc phai duoc quan ly theo vong doi event loop de tranh loi `got Future attached to a different loop` khi restart server hoac doi thread loop.

---

## 3. CAVEATS

1. Test stress SQLite duoc thuc hien tren o dia cuc bo NTFS Windows. Tren moi truong Linux hoac NFS/network mounts, hien tuong lock file co the tram trong hon.
2. Ty gia VND duoc kiem thu bang ty gia co dinh (injected fixed rate). He thong production can mot service lay ty gia dong (tu ngan hang hoac feed chuyen biet cho VN) de tranh sai lech voi thi truong thuc.
3. Kiem thu mang moi chi gia lap do tre bang `asyncio.sleep` va timeout bang `asyncio.wait_for`. Cac truong hop rui ro thuc te nhu TCP connection reset giua chung tren WebSocket live order can duoc kiem chung them khi ket noi testnet broker that.

---

## 4. CONCLUSION & CONCRETE RECOMMENDATIONS

### 4.1. Tong ket danh gia rui ro thuc nghiem
- **Rui ro Khoa SQLite (Database Lock)**: MUC DO CAO (HIGH). Da tai hien thanh cong 6 loi/800 ops.
- **Rui ro Portfolio VND bi fail-closed**: MUC DO CAO (HIGH). Da xac minh PortfolioContractError khi thieu VND.
- **Rui ro Sai lech dau Capex trong Financial Statements**: MUC DO TRUNG BINH (MEDIUM). Da xac minh loi expected_nonnegative_magnitude khi Capex am.
- **Rui ro Troi so hoc Float**: MUC DO THAP - TRUNG BINH (LOW-MEDIUM). Do lech xac dinh la 0.00025 VND/50.000 trades, an toan voi backtest thong thuong nhung can luu y voi paper trading tien that.

### 4.2. Khuyen nghi kien truc va patch can ap dung
1. **Khac phuc SQLite Concurrency**:
   - Bat che do WAL mode ngay khi khoi tao database: `PRAGMA journal_mode = WAL;`.
   - Thiet lap thoi gian cho busy timeout tren tat ca cac ket noi: `sqlite3.connect(self.path, timeout=15.0)`.
   - WAL mode cho phep Readers va Writers hoat dong song song ma khong block lan nhau.
2. **Khac phuc VND Portfolio Availability**:
   - Cung cap ty gia fallback mac dinh cho USD/VND (vi du: 25.400) trong `service.py` khi Frankfurter feed khong ho tro VND, hoac tich hop fallback provider cho cac thi truong Dong Nam A.
3. **Khac phuc Capex Sign Convention trong Vietnam Research Tool**:
   - Truoc khi tinh Free Cash Flow, chuan hoa capex bang tri tuyet doi: `abs(capex)` hoac cho phep capex am bang cach thay doi cong thuc thanh `cfo - abs(capex)`.
4. **Tich hop Harness vao CI/CD**:
   - File harness `agent/tests/test_empirical_stress_harness.py` da duoc thiet ke theo chuan pytest, can duoc them vao pipeline CI (`pytest agent/tests/test_empirical_stress_harness.py`) trong GitHub Actions de kiem soat tu dong cac loi hoi quy.

---

## 5. VERIFICATION METHOD (HUONG DAN TU XAC MINH DOC LAP)

Nguoi kiem toan doc lap (teamwork_auditor hoac bat ky ky su nao) co the xac minh lai toan bo ket luan trong bao cao bang cac lenh sau:

1. **Xac minh Frontend Tests**:
   ```powershell
   cd d:\Vibe-Trading\frontend
   npm run test:run
   npm run build
   ```
   *Tieu chi dat*: 125 test files passed, 1.136 tests passed, build xong khong co loi typecheck.

2. **Xac minh Toan bo Backend Test Collection**:
   ```powershell
   cd d:\Vibe-Trading
   python -m pytest --collect-only -q agent/tests
   ```
   *Tieu chi dat*: Thu thap du 21.876 tests, 0 loi collection.

3. **Chay Bo Test Harness Thuc Nghiem**:
   ```powershell
   cd d:\Vibe-Trading
   python -m pytest agent/tests/test_empirical_stress_harness.py -v -s
   ```
   *Tieu chi dat*:
   - 14 test cases PASSED.
   - Stdout in ra:
     * `[DRIFT REPORT] Over 50000 trades: ... Drift=0.0002495`
     * `[SQLITE STRESS] Total Ops: 800, Successful: ..., Lock Errors: ... [OBSERVED SQLITE LOCK ERRORS]: Sample: database is locked`
     * `[LIVE RUNNER CONCURRENCY] 20 parallel requests: Started=1, Rejected=19`
