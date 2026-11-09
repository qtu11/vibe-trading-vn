# Handoff Report: CFA Institute Standards & Quantitative Accuracy Audit

**Subagent**: `explorer_ws4_cfa`  
**Working Directory**: `D:\Vibe-Trading\.agents\teamwork\explorer_ws4_cfa\`  
**Date**: 2026-11-08  
**Handoff Type**: Hard Handoff (Investigation Complete)  

---

## 1. Observation

Direct, verbatim evidence collected from the codebase:

1. **Annualized Returns & CAGR Violation of GIPS 2.A.28**:
   - Location: `agent/backtest/metrics.py:604-615`
   - Code:
     ```python
     growth = 1 + total_ret
     if growth <= 0:
         ann_ret = -1.0
     else:
         try:
             ann_ret = float(growth ** (bpy / max(n, 1)) - 1)
         except OverflowError:
             ann_ret = float("inf")
     ```
   - Contrast with `agent/src/quantlib/performance.py:438-444`:
     ```python
     if days < DAYS_PER_YEAR:
         return None
     growth = 1.0 + total_return
     if growth <= 0.0:
         return -1.0
     try:
         return float(growth ** (DAYS_PER_YEAR / days) - 1.0)
     ```
   - Fact: `metrics.py` unconditionally annualizes sub-annual periods (e.g. 5 days, 14 days), producing astronomical rates ($> 1000\%$). `quantlib/performance.py` enforces GIPS Standard 2.A.28 by returning `None`.

2. **Sharpe Ratio Zero Risk-Free Rate & Inconsistent Return Basis**:
   - Location: `agent/backtest/metrics.py:619-626`
   - Code:
     ```python
     vol = float(port_ret.std()) if len(port_ret) > 1 and returns_finite else 0.0
     sharpe = (
         float(port_ret.mean() / (vol + 1e-10) * np.sqrt(bpy))
         if returns_finite
         else 0.0
     )
     ```
   - Fact: $R_f = 0$ is hardcoded; numerator uses arithmetic mean $\bar{R} \times bpy$ while reported return is geometric CAGR $(1+R)^{bpy/n}-1$. No autocorrelation correction (Lo 2002) is applied. In `agent/backtest/validation.py:225`, `std = returns.std()` uses `ddof=0` (numpy), whereas `metrics.py` uses `ddof=1` (pandas).

3. **Sortino Ratio Downside Semi-Deviation**:
   - Location: `agent/backtest/metrics.py:641-654`
   - Code:
     ```python
     if returns_finite:
         downside = port_ret[port_ret < 0]
         downside_deviation = (
             float(np.sqrt((downside**2).sum() / len(port_ret)))
             if len(downside) > 0
             else 1e-10
         )
         sortino = float(port_ret.mean() / (downside_deviation + 1e-10) * np.sqrt(bpy))
     ```
   - Fact: Divisor correctly uses total periods $N = \text{len}(port\_ret)$ and does not penalize upside. However, Minimum Acceptable Return is hardcoded to $\text{MAR} = 0$, and zero downside defaults to `1e-10`, creating synthetic $10^9$ ratios.

4. **Information Ratio & Benchmark Imputation Hazard**:
   - Location: `agent/backtest/metrics.py:678-687`
   - Code:
     ```python
     aligned_bench = bench_ret.reindex(port_ret.index).fillna(0.0)
     active_ret = port_ret - aligned_bench
     active_std = float(active_ret.std()) if len(active_ret) > 1 and returns_finite else 0.0
     ir = (
         float(active_ret.mean() / (active_std + 1e-10) * np.sqrt(bpy))
         if returns_finite
         else 0.0
     )
     ```
   - Fact: Missing benchmark observations are filled with `0.0` (0% daily return), generating false manager alpha on exchange holidays. Excess return is reported arithmetically (`total_ret - bench_return`) rather than geometrically ($\frac{1+R_p}{1+R_b}-1$).

5. **Brinson Attribution Static Snapshot Disconnect**:
   - Location: `agent/src/quantlib/attribution.py:209-450` contains exact Brinson-Fachler and Cariño multi-period linking.
   - Location: `agent/src/api/attribution_core.py:558-570, 611-651`
   - Code:
     ```python
     weights = _row_weights(rows[-1])
     # ...
     held = _row_weights(rows[-2])
     # ...
     for symbol in symbols:
         symbol_return = _attribution_symbol_cumulative_return(run_dir, symbol)
     # ...
     result = brinson_fachler(portfolio_weights, benchmark_weights, portfolio_returns_map, dict(returns))
     ```
   - Fact: `attribution_core.py` extracts a single static weight row from the end of `positions.csv`, pairs it with cumulative returns across the entire backtest, and bypasses Cariño linking entirely. If leveraged weights sum to $\ne 1.0$, `brinson_fachler` raises `ValueError` and attribution is silently suppressed.

6. **Monte Carlo Trade Scaling & i.i.d. Bootstrap Flaws**:
   - Location: `agent/backtest/validation.py:76-85, 126-138`
   - Code:
     ```python
     shuffled = rng.permutation(pnls)
     equity = np.concatenate(([initial_capital], initial_capital + np.cumsum(pnls)))
     returns = np.where(prev != 0, diff / np.where(prev != 0, prev, 1.0), 0.0)
     sharpe = float(returns.mean() / (std + 1e-10) * np.sqrt(bars_per_year))
     ```
   - Location: `agent/backtest/validation.py:198-208`
   - Code:
     ```python
     sample = rng.choice(returns, size=len(returns), replace=True)
     boot_sharpes.append(_sharpe(sample, bars_per_year))
     lower = float(np.percentile(arr, alpha * 100))
     upper = float(np.percentile(arr, (1 - alpha) * 100))
     ```
   - Fact: Trade-level PnLs with variable holding periods are scaled by $\sqrt{252}$ as if each trade were a 1-day bar. Time-series returns are resampled via naive i.i.d. choice and unadjusted percentiles, destroying autocorrelation and ignoring finite-sample Sharpe estimation bias.

---

## 2. Logic Chain

1. **Premise 1 (GIPS Compliance)**: GIPS 2020 Standard 2.A.28 strictly prohibits annualizing performance for periods under one year.
   - *Observation*: `metrics.py:604` raises growth to $(bpy/n)$ unconditionally. For $n=5$, $(252/5) = 50.4$.
   - *Inference*: Any short backtest outputs non-compliant, misleading annual returns.
2. **Premise 2 (Economic Risk-Adjusted Returns)**: An investment strategy must be evaluated against the risk-free opportunity cost $R_f$.
   - *Observation*: `metrics.py:620` and `validation.py:224` omit $R_f$.
   - *Inference*: In a positive rate environment (SOFR $\approx 5\%$), strategies with single-digit gross returns show deceptively high Sharpe ratios when their true economic excess Sharpe is near zero.
3. **Premise 3 (Multi-Period Attribution Theory)**: Portfolio allocations change dynamically across time.
   - *Observation*: `attribution_core.py:558` samples only the terminal positions row and multiplies by full-period cumulative asset returns.
   - *Inference*: The surfaced attribution report does not represent the strategy's dynamic allocation skills, creating hindsight and survivorship distortions.
4. **Premise 4 (Time-Series Econometrics)**: Daily asset returns exhibit serial correlation and volatility clustering.
   - *Observation*: `validation.py:201` uses `rng.choice` with replacement and `np.percentile`.
   - *Inference*: Confidence intervals for the Sharpe ratio are artificially narrow and uncorrected for finite-sample skewness bias.

---

## 3. Caveats

1. **High-Frequency & Intraday Backtesting**: The current codebase scales annualization factors via `_BARS_PER_DAY` mapping (`metrics.py:59-157`). For tick-level or unevenly spaced intraday bars, effective bars per year depends on observed timestamps rather than fixed table lookup.
2. **Short-Selling & Leverage in Brinson**: The classical Brinson-Fachler model assumes long-only fully invested portfolios ($\sum w_i = 1$). Extending Brinson to long/short market-neutral equity portfolios requires the Menchero & Lee (2015) long/short attribution framework, which is currently unmodeled.
3. **Data Availability**: The audit inspected static code and test cases. Realized broker executions may introduce slippage and borrow cost dynamics that further impact active return and tracking error.

---

## 4. Conclusion

The repository possesses a dual identity:
- Its theoretical core (`agent/src/quantlib/`) demonstrates high mathematical sophistication (true TWR, Modified Dietz, XIRR bisection, Cariño linking, Euler factor risk decomposition, and purged cross-validation).
- Its backtest runtime engine (`agent/backtest/metrics.py`, `agent/backtest/validation.py`, `agent/src/api/attribution_core.py`) suffers from key departures from CFA/GIPS standards: unconditional sub-annual annualization, omission of risk-free rate, naive benchmark gap filling with zero, static single-snapshot attribution bypassing Cariño linking, trade-duration scaling distortion in Monte Carlo, and i.i.d. bootstrap confidence intervals.

Full remediations and reference implementations conforming to CFA Levels I–III and GIPS have been documented in `analysis.md`.

---

## 5. Verification Method

To independently verify the audit findings:

1. **Inspect Code Locations**:
   - `agent/backtest/metrics.py` lines 604–654, 675–702.
   - `agent/src/api/attribution_core.py` lines 558–570, 611–651.
   - `agent/backtest/validation.py` lines 76–85, 126–138, 198–208.
   - `agent/src/quantlib/attribution.py` lines 209–450.
   - `agent/src/quantlib/performance.py` lines 425–447.

2. **Run Existing Test Suites**:
   Execute backend metric and attribution tests via PowerShell:
   ```powershell
   pytest agent/tests/test_metrics.py
   pytest agent/tests/test_metrics_sortino.py
   pytest agent/tests/test_metrics_tracking_error.py
   pytest agent/tests/quantlib/test_attribution.py
   pytest agent/tests/quantlib/test_performance.py
   pytest agent/tests/test_validation.py
   ```

3. **Reproduction of GIPS Annualization Blowout**:
   ```python
   import pandas as pd
   from backtest.metrics import calc_metrics
   eq = pd.Series([100.0, 101.0, 102.0, 103.0, 105.0])
   res = calc_metrics(eq, [], initial_cash=100.0, bars_per_year=252)
   # res['annual_return'] evaluates to ~10.46 (+1046%), violating GIPS 2.A.28
   ```

4. **Reproduction of Attribution Single-Row Snapshot**:
   Inspect `agent/src/api/attribution_core.py:558-570` to verify that `held = _row_weights(rows[-2])` takes only a single row before liquidation instead of iterating across rebalance dates.
