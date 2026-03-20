# Screening Factors

Factor definitions, scoring methodology, and composite ranking for the security screener. The screener serves two distinct purposes: identifying high-conviction individual stocks for the Munger satellite portfolio, and selecting optimal index ETFs for the Boglehead core portfolio. Each screen has its own set of factors, thresholds, and data sources.

**Status: DRAFT**

## Dependencies

- [Spec Conventions](../00-meta/spec-conventions.md) — terminology, naming rules
- [Data Model](../01-system/data-model.md) — `securities`, `fundamentals`, `screening_results` tables; `securities_asset_class_enum`
- [Glidepath](../03-calculations/glidepath.md) — defines how much capital is allocated to core vs. satellite

---

## Munger/Buffett Quality Screen

For the satellite portfolio (~30-40% of equities allocation). Seeks wonderful companies at fair prices with durable competitive advantages.

### Factor Definitions

| # | Factor | Formula | Direction | Threshold | Data Source | Rationale |
|---|--------|---------|-----------|-----------|-------------|-----------|
| M1 | ROIC | (Net Operating Profit After Tax) / (Total Equity + Total Debt - Cash) | Higher = better | > 15% | Yahoo Finance fundamentals | Durable competitive advantage indicator |
| M2 | ROE | Net Income / Shareholders' Equity | Higher = better | > 15% | Yahoo Finance fundamentals | Capital efficiency |
| M3 | Debt/Equity | Total Liabilities / Shareholders' Equity | Lower = better | < 0.5 | Yahoo Finance fundamentals | Conservative balance sheet |
| M4 | 10Y Earnings Growth | CAGR of diluted EPS over 10 years | Higher = better | > 0% and consistent | Alpha Vantage / Morningstar | Consistent compounder |
| M5 | Earnings Consistency | 1 - (StdDev of annual EPS growth / Mean of annual EPS growth) | Higher = better | > 0.5 (low variance) | Computed from M4 inputs | Penalizes erratic earnings |
| M6 | Free Cash Flow Yield | Free Cash Flow / Market Cap | Higher = better | > 5% | Yahoo Finance fundamentals | Cash generation ability |
| M7 | Gross Margin | Gross Profit / Revenue | Higher = better | > 40% | Yahoo Finance fundamentals | Pricing power indicator |
| M8 | Owner Earnings Growth | CAGR of owner earnings over 5 years | Higher = better | > 0% | Computed (see formula below) | Buffett's preferred metric |
| M9 | P/E Ratio | Price / Diluted EPS (trailing 12 months) | Lower = better | < 25 | Yahoo Finance | Reasonable price gate |
| M10 | P/FCF Ratio | Market Cap / Free Cash Flow | Lower = better | < 20 | Yahoo Finance | Alternative valuation check |

### Owner Earnings Formula

Buffett's concept of owner earnings, from the 1986 Berkshire Hathaway letter:

```
owner_earnings = net_income
               + depreciation_amortization
               + other_non_cash_charges
               - average_annual_maintenance_capex

where:
    maintenance_capex is estimated as:
        min(capex, depreciation_amortization)
    (conservative assumption: maintenance capex <= D&A; growth capex is the remainder)
```

Data source: Income statement (net_income, D&A) and cash flow statement (capex) from Yahoo Finance.

### Intrinsic Value Estimate

A simple owner-earnings-based valuation, not a full DCF:

```
intrinsic_value = owner_earnings_ttm * earnings_multiple

where:
    earnings_multiple = min(max(10, expected_growth_rate * 2), 25)
    -- Floor of 10x, cap of 25x, scaled by growth rate
    -- Example: 12% growth -> 24x; 8% growth -> 16x; 15% growth -> 25x (capped)

margin_of_safety = (intrinsic_value - current_market_cap) / intrinsic_value
```

Securities with `margin_of_safety > 0.25` (25% discount to intrinsic value) are flagged as potential buys.

### Understandable Business Flag

A boolean field `is_understandable` stored in the `research_notes` table. This is always set manually by the user. The screener can filter to only show securities where `is_understandable = TRUE`. Securities without a research note are treated as "not yet evaluated" and excluded from the final ranking by default.

---

## Boglehead ETF Screen

For the core portfolio (~60-70% of equities allocation). Seeks low-cost, tax-efficient, broadly diversified index funds available to Finnish investors.

### Factor Definitions

| # | Factor | Formula / Source | Direction | Threshold | Data Source | Rationale |
|---|--------|-----------------|-----------|-----------|-------------|-----------|
| B1 | TER | Total Expense Ratio (annual) | Lower = better | < 0.30% | justETF / Morningstar | Cost is the most reliable predictor of future returns |
| B2 | AUM | Assets Under Management in EUR | Higher = better | > 100M EUR | justETF / Morningstar | Liquidity, lower closure risk |
| B3 | Distribution Policy | Accumulating vs. Distributing | Binary: ACC = pass | ACC only | justETF | Tax efficiency for Finnish investors (no dividend tax events) |
| B4 | Replication Method | Physical vs. Synthetic | Binary: Physical = pass | Physical only | justETF | Reduced counterparty risk |
| B5 | Domicile | Fund domicile country | Binary: IE or LU = pass | Ireland or Luxembourg | justETF | Favorable tax treaties with Finland for withholding tax on dividends |
| B6 | Tracking Difference | Actual return minus index return (annualized, 3-year) | Lower = better | < 0.50% | justETF / Morningstar | The true cost of the fund |

### ETF Eligibility Pipeline

The ETF screen applies factors in two phases: hard filters first, then scoring.

```
Phase 1 — Hard Filters (binary pass/fail):
    B3: distribution_policy == 'accumulating'    -> PASS or REJECT
    B4: replication_method == 'physical'         -> PASS or REJECT
    B5: domicile IN ('IE', 'LU')                -> PASS or REJECT
    B1: ter <= 0.0030                            -> PASS or REJECT
    B2: aum_eur >= 100_000_000                   -> PASS or REJECT

Phase 2 — Scoring (on surviving candidates):
    Score on: TER (weight 0.35), Tracking Difference (weight 0.35), AUM (weight 0.30)
    Lower TER = higher score, lower TD = higher score, higher AUM = higher score
```

---

## Factor Calculation Details

### Normalization: Z-Score Method

All continuous factors are normalized to z-scores within the screened universe to enable cross-factor comparison.

```
For factor F across N securities:
    mean_F = (1/N) * sum(F_i for i in 1..N)
    std_F  = sqrt((1/N) * sum((F_i - mean_F)^2 for i in 1..N))

    z_i = (F_i - mean_F) / std_F

    If direction == 'lower_is_better':
        z_i = -z_i      -- flip sign so higher z always means better
```

### Winsorization

Before computing z-scores, winsorize at the 2.5th and 97.5th percentiles to limit the influence of outliers:

```
For factor F:
    p2_5  = percentile(F, 0.025)
    p97_5 = percentile(F, 0.975)
    F_i = max(p2_5, min(F_i, p97_5))
```

### Minimum Data Requirements

Each factor requires a minimum amount of historical data to be considered valid:

| Factor | Minimum Requirement |
|--------|-------------------|
| M1 (ROIC) | 1 year of financials |
| M2 (ROE) | 1 year of financials |
| M3 (Debt/Equity) | 1 quarter of financials |
| M4 (10Y Earnings Growth) | 5 years of EPS data (partial score if 5-9 years) |
| M5 (Earnings Consistency) | 5 years of EPS data |
| M6 (FCF Yield) | 1 year of cash flow data |
| M7 (Gross Margin) | 1 year of financials |
| M8 (Owner Earnings Growth) | 3 years of financials |
| M9 (P/E) | 1 year trailing EPS > 0 |
| M10 (P/FCF) | 1 year FCF > 0 |
| B6 (Tracking Difference) | 3 years of return data |

If a security lacks sufficient data for a factor, that factor is excluded from its composite score, and the remaining factors are re-weighted proportionally.

---

## Composite Scoring

### Munger Composite

```
Input: z-scores for factors M1..M10 (excluding any with insufficient data)
Weights: equal weight by default (1/N for N available factors)

composite_score = sum(weight_i * z_i for i in available_factors)

Rank all securities by composite_score descending.
```

User-configurable weights are stored in `user_settings` as a JSON object:

```json
{
  "munger_weights": {
    "roic": 1.0,
    "roe": 1.0,
    "debt_equity": 1.0,
    "earnings_growth_10y": 1.0,
    "earnings_consistency": 1.0,
    "fcf_yield": 1.0,
    "gross_margin": 1.0,
    "owner_earnings_growth": 1.0,
    "pe_ratio": 1.0,
    "p_fcf": 1.0
  }
}
```

Weights are normalized to sum to 1.0 before applying. A weight of 0.0 disables that factor.

### Boglehead Composite

```
Input: z-scores for factors B1, B2, B6 (only continuous factors; B3-B5 are hard filters)
Weights: TER = 0.35, Tracking Difference = 0.35, AUM = 0.30

composite_score = 0.35 * z_ter + 0.35 * z_td + 0.30 * z_aum
```

### Worked Example: Munger Screen

Three hypothetical stocks after z-score normalization:

| Factor | Stock A (z) | Stock B (z) | Stock C (z) |
|--------|------------|------------|------------|
| M1 ROIC | +1.2 | +0.8 | -0.3 |
| M2 ROE | +1.0 | +0.5 | +0.2 |
| M3 D/E | +0.8 | +1.5 | -1.0 |
| M4 10Y Growth | +0.5 | +0.3 | +1.8 |
| M5 Consistency | +0.9 | +0.2 | +1.5 |
| M6 FCF Yield | +0.3 | +1.2 | -0.1 |
| M7 Gross Margin | +1.1 | +0.4 | +0.7 |
| M8 Owner Earn. | +0.6 | +0.3 | +1.0 |
| M9 P/E | -0.2 | +0.8 | +0.5 |
| M10 P/FCF | -0.1 | +0.9 | +0.4 |

Equal weight = 1/10 = 0.10 per factor.

```
Stock A composite = 0.10 * (1.2 + 1.0 + 0.8 + 0.5 + 0.9 + 0.3 + 1.1 + 0.6 - 0.2 - 0.1) = 0.10 * 6.1 = 0.61
Stock B composite = 0.10 * (0.8 + 0.5 + 1.5 + 0.3 + 0.2 + 1.2 + 0.4 + 0.3 + 0.8 + 0.9) = 0.10 * 6.9 = 0.69
Stock C composite = 0.10 * (-0.3 + 0.2 - 1.0 + 1.8 + 1.5 - 0.1 + 0.7 + 1.0 + 0.5 + 0.4) = 0.10 * 4.7 = 0.47

Ranking: Stock B (0.69) > Stock A (0.61) > Stock C (0.47)
```

Stock B ranks highest due to its strong balance sheet (D/E) and attractive valuation (P/E, P/FCF), even though Stock A has higher quality metrics (ROIC, ROE, gross margin).

---

## API Endpoints

### `GET /api/v1/screener/munger`

Query params: `minRoic`, `minRoe`, `maxDebtEquity`, `minFcfYield`, `minGrossMargin`, `maxPe`, `maxPfcf`, `sortBy`, `limit`, `offset`

Returns ranked list of securities passing all thresholds, with factor values and composite score.

### `GET /api/v1/screener/etf`

Query params: `maxTer`, `minAum`, `domicile`, `replication`, `distribution`, `sortBy`, `limit`, `offset`

Returns ranked list of ETFs passing hard filters, with factor values and composite score.

### `POST /api/v1/screener/munger/weights`

Body: custom weight configuration. Saves to `user_settings` and re-ranks.

---

## Edge Cases

1. **Negative earnings**: If EPS is negative, P/E is undefined. Exclude the security from factor M9 and re-weight remaining factors. Do not compute a negative P/E.
2. **Negative FCF**: If FCF is negative, P/FCF is undefined and FCF yield is negative. Exclude from M6 and M10, re-weight remaining factors.
3. **Zero shareholders' equity**: D/E is undefined. Exclude from M3.
4. **Missing 10-year history**: For newer companies, use available years (minimum 5). Assign a penalty multiplier of `available_years / 10` to factors M4 and M5 to reflect lower confidence.
5. **Single-security universe**: Z-scores are undefined with N=1 (std = 0). If the screened universe has fewer than 5 securities, skip z-score normalization and display raw factor values only.
6. **ETF with no tracking difference data**: New ETFs may lack 3-year TD. Use 1-year TD if available with a confidence flag; otherwise exclude from B6 scoring.
7. **Stale fundamental data**: If the last financial statement is older than 18 months, flag the security as "stale fundamentals" and show a warning in the UI. Do not exclude from screening but mark the staleness.
8. **Currency mismatch**: FCF yield and other valuation metrics must use the same currency for numerator and denominator. Convert market cap to the company's reporting currency before computing ratios.
9. **Financial sector companies**: Banks and insurers have meaningfully different balance sheets. Gross margin (M7) and D/E (M3) are not applicable. Exclude these factors for securities with `sector = 'Financial Services'` and re-weight.
10. **Dual-listed securities**: The same company may appear under different tickers. Deduplicate by ISIN before scoring.

## Open Questions

- Should the Munger screen include a qualitative "moat rating" (none/narrow/wide) as a factor, or keep it purely quantitative?
- Should we implement a "magic formula" (Greenblatt) composite as a third screening preset?
- How frequently should fundamental data be re-screened (weekly vs. quarterly)?

## Changelog

| Date | Change |
|------|--------|
| 2026-03-19 | Initial draft |
