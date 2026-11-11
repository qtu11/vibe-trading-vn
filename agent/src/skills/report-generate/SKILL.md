---
name: report-generate
description: Professional financial research report generation — standard structure (summary / views / main body / risks / recommendation), Markdown formatting standards, rating system, and terminology guide.
category: tool
---

# Professional Research Report Generation

## Overview

Generate structured, evidence-bound financial research. Use readable Markdown in chat and the shared report renderer for exported equity documents.

## Saving and Delivering a PDF

For equity research documents, call `export_research_report` with structured
`ResearchReport` content and the requested DOCX/PDF/PPTX formats. This shared
renderer owns the VIBE masthead, KPI band, tables, charts and chapter layout.
`write_file(...pdf)` is for unrelated general documents; it cannot substitute
for an equity report or bypass a failed evidence check. If export fails, repair
the returned `accepted_report` and fix every `field_errors` entry in one pass.
`collected_sources` lists the URLs this run actually read: use `expected_url`
when an issue supplies it, and never invent a replacement URL. Repair the
number/source binding inside an `analysis_sections` chapter instead of deleting
the chapter. Headings are plain text without "1."/"Chương 1" numbering because
the renderer numbers chapters. A `read_url` failure (`source_blocked`,
`source_not_found`, `source_rate_limited`, `source_unreadable`,
`source_unreachable`, `wrapper_unresolved`) is terminal for that URL; use its
`remedy` or mark the data unavailable. Never relabel evidence as verified or erase a missing-data
marker to force publication. Deliver only returned artifacts and download URLs;
if a format is unavailable, say so.

## Evidence and Analytical Discipline

Apply the research practices in CFA Institute [Standard V(A)](https://www.cfainstitute.org/standards/professionals/code-ethics-standards/standards-of-practice-v-a)
and [Standard V(B)](https://www.cfainstitute.org/standards/professionals/code-ethics-standards/standards-of-practice-v-b):
assess the research basis, explain the methods and material risks/limitations,
and separate observed facts from calculations, assumptions and opinions. These
practices do not imply CFA endorsement, certification or a prescribed page count.

- Bind each figure to its source, period, currency/unit and consolidation basis;
  compare like periods and distinguish intraday trades from closing prices.
- Separate group profit, minority interests and profit attributable to parent
  shareholders. Reconcile profit to operating cash flow, capex and free cash
  flow; show debt, maturities, guarantees and funding needs. Recompute ratios.
- Select valuation by business model. Holding-company SOTP/NAV must address
  ownership percentages, minorities, parent net debt and double counting;
  banking ratios are not a substitute for that analysis.
- Populate `financial_table`, `peer_comparison`, `valuation_scenarios`,
  `risk_factors`, `catalysts` and `analysis_sections` only with supported inputs.
  Show bear/base/bull assumptions, sensitivity and the strongest counterargument.
  If necessary inputs are missing, omit a target, stay `CHƯA XẾP HẠNG`, and name
  what evidence would change the conclusion. Never pad pages or manufacture data.

## Report Types and Structure

### Type Classification

| Type | Length | Core Content | Trigger Scenario |
|------|------|---------|---------|
| Deep-dive stock report | 3000-5000 words | Company analysis + valuation + supported rating or unrated conclusion | "Analyze stock XX" |
| Industry research | 2000-4000 words | Industry structure + trend + recommended names | "How is sector XX?" |
| Strategy report | 1500-3000 words | Macro + strategy + allocation recommendation | "What is the market outlook?" |
| Backtest report | 1000-2000 words | Strategy performance + risk + improvement suggestions | After a backtest is completed |
| Flash comment / note | 500-1000 words | Event commentary + impact + action suggestion | "How should we view event XX?" |

### Standard Structure Template

```markdown
# [Report Title]

> **Rating**: [MUA / THEO DÕI / BÁN / CHƯA XẾP HẠNG]
> **Target price**: [only if supported; currency/unit and horizon] | **Reference price**: [observed value, currency/unit, date/time and price basis, or unavailable]
> **Prepared by**: Vibe-Trading AI | **Data as of**: [actual cutoff date]

## Summary

3-5 key points, each 1-2 sentences, covering the core conclusion.
State the evidence-backed view and its limits. If evidence is insufficient, state what is missing and remain unrated.

## Core Views

### View 1: [One-line heading]
2-3 paragraphs of discussion, supported by data.

### View 2: [One-line heading]
2-3 paragraphs of discussion, supported by data.

### View 3: [One-line heading]
2-3 paragraphs of discussion, supported by data.

## Main Analysis

### [Section 1: for example Industry analysis / Company fundamentals / Strategy logic]
Detailed analysis...

### [Section 2: for example Financial analysis / Competitive landscape / Backtest results]
Detailed analysis...

### [Section 3: for example Valuation analysis / Catalysts / Risk-reward]
Detailed analysis...

## Data Appendix

Key data tables...

## Risk Warnings

1. [Risk 1]: specific description + trigger condition + impact level
2. [Risk 2]: ...
3. [Risk 3]: ...

## Investment Recommendation

State a supported view, horizon, conditional scenarios and invalidation evidence.
If price or valuation inputs are missing, remain unrated and identify the next evidence required.
Include position sizing only when the user supplied portfolio and risk constraints.

---
*Disclaimer: This report is generated by an AI quantitative system for research reference only and does not constitute investment advice.*
```

## Rating System

### Equity Ratings

Use exactly the structured report's supported labels: `MUA`, `THEO DÕI`, `BÁN`,
or `CHƯA XẾP HẠNG`. Explain the benchmark, horizon, methodology and risks behind
any rating; a return threshold alone does not establish investment suitability.
Missing verified price, source or reproducible valuation inputs means
`CHƯA XẾP HẠNG`. A `BÁN` view does not authorize a short sale or an order.

### Strategy Ratings

| Rating | Definition | Applicable Standard |
|------|------|------|
| High allocation priority | Excellent risk-reward profile | Sharpe > 1.5, max drawdown < 20% |
| Allocatable | Good risk-reward profile | Sharpe > 1.0, max drawdown < 30% |
| Watch | Needs more validation | Sharpe 0.5-1.0 |
| Not recommended | Poor risk-reward profile | Sharpe < 0.5 or drawdown > 40% |

## Markdown Formatting Standards

### Heading Hierarchy

```
# H1: Report title (only one)
## H2: Main sections (summary / views / body / risks / recommendation)
### H3: Subsections
#### H4: Maximum depth; use bold text instead of deeper nesting
```

### Table Standards

```markdown
| Metric | 2024A | 2025E | 2026E | Notes |
|------|-------|-------|-------|------|
| Revenue (100m RMB) | 500.2 | 580.0 | 660.0 | +15% YoY |
| Net profit (100m RMB) | 45.3 | 55.0 | 65.0 | +22% YoY |
| PE(TTM) | 25.0x | 20.5x | 17.3x | Valuation compressing |
```

**Table rules**:
- Right-align numbers where possible (when Markdown cannot do so, at least keep visual alignment clean)
- Put the actual source currency and unit in the header; never copy example units into another market
- Forecast values use `E` (`2025E`), actual values use `A` (`2024A`)
- Keep 1 decimal place for percentages and 1-2 decimal places for monetary values

### Number Formatting Standards

| Type | Format | Example |
|------|------|------|
| Percentage | `X.X%` | Return `12.5%` |
| Large amount | `X,XXX.X亿` | Market cap `1,234.5亿` |
| Small amount | `X.XX元` | Stock price `25.80元` |
| Multiple | `X.Xx` | PE `20.5x` |
| Date | `YYYY-MM-DD` | `2026-03-28` |
| Time range | `YYYY.MM-YYYY.MM` | `2024.01-2025.03` |

### Chart Substitute (Text Description + Data Table)

For exported equity reports, supply validated `price_history`, `quarterly_results`
or `analysis_sections.charts`; the shared renderer builds charts from those inputs.
In chat, accompany chart discussion with a source-bound data table when useful.
The example below illustrates structure only; do not reuse its numbers:

```markdown
### Equity Curve

The strategy equity started at 1.00 in 2020-01, peaked at 1.85 in 2021-02,
then suffered its largest drawdown from 2022.04 to 2022.10 (-25.3%), and
recovered by 2023.06 to a new high of 2.10.

| Time Point | Equity | Cumulative Return | Phase Event |
|---------|------|---------|---------|
| 2020-01 | 1.00 | 0% | Start |
| 2021-02 | 1.85 | +85% | Bull-market peak |
| 2022-10 | 1.38 | +38% | Drawdown low |
| 2023-06 | 2.10 | +110% | Recovery to new high |
| 2024-12 | 2.45 | +145% | Latest |
```

## Professional Terminology Guide

### Terms You Should Use (to improve professionalism)

| Scenario | Professional Expression | Avoid |
|------|---------|---------|
| Price down | pullback / correction / drawdown | dropped / fell |
| Price up | strengthened / rebounded / recovered / climbed | rose / went up |
| Uncertainty | uncertainty remains / needs monitoring | hard to say / cannot tell |
| Recommend buying | recommend overweight / add | buy now |
| Recommend selling | recommend underweight / avoid | sell now |
| Undervalued | valuation offers a margin of safety | cheap |
| Expensive | valuation premium is elevated | expensive |
| Trend favorable | conditions are improving / trend is constructive | market looks okay |

### Common Abbreviations

| Abbreviation | Full Name | Chinese Meaning |
|------|------|------|
| YoY | Year over Year | 同比 |
| QoQ | Quarter over Quarter | 环比 |
| MoM | Month over Month | 月环比 |
| TTM | Trailing Twelve Months | 滚动12个月 |
| CAGR | Compound Annual Growth Rate | 复合增长率 |
| ROE | Return on Equity | 净资产收益率 |
| EPS | Earnings Per Share | 每股收益 |
| FCF | Free Cash Flow | 自由现金流 |

## Backtest Report Template

After a backtest is completed, read the engine-written `metrics.csv` and
`equity.csv` from that run. Declare reported measurements with the run directory
or exact engine field as their grounding reference. A metrics file you write
yourself is not evidence, and a previous run's archive cannot substantiate the
current call. For list results, use the exact element reference (for example,
`call_id::data.positions[0].contribution_pct`); correction hints only identify
candidates to check and cite explicitly.

Use the verified output to generate:

```markdown
# Backtest Report: [Strategy Name]

## Strategy Overview
- **Strategy type**: momentum / mean reversion / multi-factor / ...
- **Instruments**: 000001.SZ, 600519.SH, ...
- **Backtest period**: 2016-01-01 to 2026-01-01
- **Initial capital**: ¥1,000,000

## Performance Summary

| Metric | Strategy | Benchmark (CSI 300) | Excess |
|------|------|-------------|------|
| Cumulative return | +145.2% | +35.6% | +109.6% |
| Annualized return | 9.8% | 3.2% | +6.6% |
| Sharpe | 1.25 | 0.45 | - |
| Max drawdown | -18.5% | -32.4% | - |
| Calmar | 0.53 | 0.10 | - |
| Win rate | 58.3% | - | - |
| Trade count | 245 | - | - |

## Annual Performance

| Year | Return | Benchmark | Excess | Max Drawdown |
|------|------|------|------|---------|
| 2016 | +12.3% | -8.5% | +20.8% | -8.2% |
| ... | ... | ... | ... | ... |

## Risk Analysis
[Insert output from the `risk-analysis` skill]

## Improvement Suggestions
1. Specific suggestion 1...
2. Specific suggestion 2...

## Rating: Allocatable
Sharpe > 1.0 and max drawdown < 20%, indicating a good risk-reward profile.
```

## Analysis Framework

### Preparation Before Writing

1. **Clarify the report type**: stock / industry / strategy / backtest / flash note
2. **Collect data**: backtest results, fundamentals, industry data
3. **Determine the core view**: evaluate the evidence and counterarguments before writing the conclusion
4. **Choose the rating**: only when source, quote and reproducible valuation inputs support it; otherwise stay unrated

### Writing Principles

1. **Put the conclusion first**: the summary should contain the most important views, without too much buildup
2. **Let data speak**: every view should have at least one supporting data point
3. **Keep logic clear**: because A (data) → therefore B (judgment) → recommendation C (action)
4. **Argue both sides**: even in bullish reports, discuss risks; even in bearish reports, mention possible catalysts
5. **Be specific**: explain conditional scenarios, horizon and invalidation evidence; do not invent portfolio sizing or order authority

## Output Format

Use the template above for readable chat prose; export requested equity documents through the structured report engine. Ensure that:
- it has a supported rating or an explicit unrated state
- it is supported by quantitative data
- it includes at least 3 risk warnings
- it explains conditional scenarios and what would change the view
- it ends with a disclaimer

## Notes

1. **Do not make overly precise forecasts**: use ranges rather than single points (`target price 25-30 RMB` instead of `target price 27.5 RMB`)
2. **Data consistency**: all quoted numbers must be consistent throughout the report and never contradict each other
3. **Mark timeliness**: state both the data cut-off date and the report generation date
4. **Disclaimer is mandatory**: AI-generated reports must explicitly state that they are not investment advice
5. **Avoid absolutes**: "likely" is better than "certain", and "may" is better than "will"
6. **China A-share specific risks**: policy risk / delisting risk / goodwill impairment / major-shareholder selling / lock-up expiry
7. **Crypto-specific risks**: regulation / smart-contract exploits / liquidity risk / rug pulls
