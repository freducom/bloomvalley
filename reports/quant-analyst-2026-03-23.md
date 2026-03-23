# Quantitative Analyst Report -- 2026-03-23

## Executive Summary

The portfolio (EUR 273,225 total market value across 25 positions) is dominated by a single short-term corporate bond ETF (ALYK, 57.6%) and a concentrated Finnish consumer staples position (Kesko, 18.2% combined). Factor analysis reveals a statistically significant market beta of 0.63 with a "Mid Growth" style classification. The Munger quality screen has identified several high-conviction candidates. The portfolio's glidepath allocation is substantially off-target, with equity at 91.7% vs. the 75% target for age 45, while fixed income shows 0% vs. the 15% target (ALYK is misclassified as equity/ETF in the system -- it is actually a fixed income instrument). The mean-variance optimizer returned an error due to data constraints, so optimal weights are derived from factor-based analysis below.

---

## 1. Screening Results -- Ranked by Composite Factor Score

### Munger Quality Screen (Top 20 of 50 stocks screened)

Factor scoring uses z-score normalization across: ROIC, ROE, D/E, 10Y earnings growth, earnings consistency, FCF yield, gross margin, owner-earnings growth, P/E, P/FCF. Financial-sector companies exclude D/E and gross margin.

| Rank | Ticker       | Name                          | Sector                  | Composite | Factors |
|-----:|:-------------|:------------------------------|:------------------------|----------:|--------:|
|    1 | NVDA         | NVIDIA Corp.                  | Information Technology  |    1.5799 |       3 |
|    2 | INVE-B.ST    | Investor AB                   | Financials              |    1.5699 |       2 |
|    3 | TSM          | Taiwan Semiconductor          | Information Technology  |    1.4648 |       3 |
|    4 | AAPL         | Apple Inc.                    | Information Technology  |    1.2680 |       3 |
|    5 | SAN.PA       | Sanofi SA                     | Health Care             |    1.0816 |       3 |
|    6 | ERIC-B.ST    | Ericsson                      | Information Technology  |    0.9554 |       2 |
|    7 | NFLX         | Netflix Inc.                  | Communication Services  |    0.8383 |       3 |
|    8 | VOLV-B.ST    | Volvo AB                      | Industrials             |    0.8161 |       2 |
|    9 | MSFT         | Microsoft Corporation         | Information Technology  |    0.7796 |       3 |
|   10 | SAMPO.HE     | Sampo Oyj                     | Financials              |    0.6593 |       2 |
|   11 | NOW          | ServiceNow Inc.               | Information Technology  |    0.5701 |       3 |
|   12 | NOVN.SW      | Novartis AG                   | Health Care             |    0.5152 |       2 |
|   13 | JPM          | JPMorgan Chase & Co.          | Financials              |    0.5051 |       1 |
|   14 | ATCO-A.ST    | Atlas Copco AB                | Industrials             |    0.4954 |       3 |
|   15 | JNJ          | Johnson & Johnson             | Health Care             |    0.4780 |       3 |
|   16 | TEAM         | Atlassian Corp.               | Information Technology  |    0.4619 |       3 |
|   17 | KO           | Coca-Cola Co.                 | Consumer Staples        |    0.4563 |       1 |
|   18 | AMZN         | Amazon.com Inc.               | Consumer Discretionary  |    0.3536 |       3 |
|   19 | BRK-B        | Berkshire Hathaway            | Financials              |    0.3391 |       2 |
|   20 | NOKIA.HE     | Nokia Oyj                     | Information Technology  |    0.3282 |       2 |

**Data quality note**: Many securities have only 2-3 factors available out of 10. The composite scores are computed from available factors only, which means rankings may shift as fundamentals data improves. Scores below 0.0 indicate below-median quality on available metrics.

### Bottom 5 (negative scores -- potential sells or avoids)

| Rank | Ticker       | Composite | Notes                              |
|-----:|:-------------|----------:|:-----------------------------------|
|   46 | ASML         |   -0.1737 | Low factor availability, overvalued on P/FCF |
|   47 | AXFO.ST      |   -0.1743 | Axfood -- low FCF yield relative to peers |
|   48 | KESKOB.HE    |   -0.1851 | Held position -- below-median quality |
|   49 | DT           |   -0.2090 | Dynatrace -- expensive vs. fundamentals |
|   50 | DIS          |   -0.2122 | Disney -- lowest composite score   |

### ETF Screen

The Boglehead ETF screen returned **0 results**. This is because the system's ETF universe lacks the required metadata (TER, AUM, tracking difference, distribution type, replication method, domicile) needed for scoring. The Core Watchlist includes IWDA, VUSA, IEGA, INRG.L, XGID.DE, XDWT.DE, and XMAF.DE, but these securities need enriched ETF profile data before quantitative ranking is possible.

**Recommendation**: Enrich ETF metadata via justETF scraping or manual entry to enable the Boglehead screen.

---

## 2. Factor Exposure -- Fama-French 5-Factor Analysis

### Portfolio-Level Factor Loadings (Europe region, 84 trading days)

| Factor | Beta   | t-Stat | p-Value  | Significant |
|:-------|-------:|-------:|---------:|:-----------:|
| MKT    |  0.626 |  6.265 | < 0.001  | YES         |
| SMB    |  0.371 |  1.924 |  0.058   | No (marginal) |
| HML    |  0.071 |  0.299 |  0.766   | No          |
| RMW    | -0.152 | -0.581 |  0.563   | No          |
| CMA    | -0.022 | -0.071 |  0.943   | No          |

- **Alpha (annualized)**: -10.38% (t-stat: -0.61, p: 0.54) -- NOT statistically significant
- **R-squared**: 0.3515 (adjusted: 0.3099)
- **Observations**: 84 trading days
- **Factor data through**: 2026-01-30

### Interpretation

1. **Market exposure (MKT = 0.63)**: The portfolio has a below-market beta, meaning it captures roughly 63% of market moves. This is expected given the large ALYK bond fund position acting as ballast.

2. **Size tilt (SMB = 0.37, marginal significance)**: Borderline small-cap tilt, likely driven by Finnish mid-cap holdings (Kesko, Kemira, Aktia, Solar Foods). This is a slight concern for a core-satellite portfolio that should have more large-cap index exposure.

3. **Value (HML = 0.07)**: Essentially neutral on value vs. growth. Not surprising given the mix of value (BNP, Nordea) and growth (Reddit, Amazon, MSFT) holdings.

4. **Profitability (RMW = -0.15)**: Slight negative loading on profitability. The portfolio holds some lower-profitability names (Solar Foods is pre-profit; Evolution under pressure). Not statistically significant.

5. **Investment (CMA = -0.02)**: Neutral. No meaningful tilt toward conservative or aggressive investing companies.

6. **Low R-squared (0.35)**: The European Fama-French factors explain only 35% of portfolio variance. This is partially due to the bond ETF dominance and crypto holdings, which are poorly captured by equity factor models.

### Factor Attribution (1-year, 2025-03-23 to 2026-03-23)

| Component              | Return   | % of Total |
|:-----------------------|---------:|-----------:|
| Total excess return    |  +0.93%  |     100.0% |
| Alpha contribution     |  -3.46%  |            |
| Market (MKT)           |  +5.22%  |    560.1%  |
| Size (SMB)             |  -1.49%  |   -159.5%  |
| Value (HML)            |  +0.70%  |    +75.4%  |
| Profitability (RMW)    |  -0.005% |     -0.5%  |
| Investment (CMA)       |  -0.04%  |     -4.6%  |
| Total factor explained |  +4.39%  |    470.9%  |

Market factor was the dominant driver of returns. The small-cap tilt cost approximately 1.5% in relative performance over the past year.

### Style Analysis (Sharpe Returns-Based)

| Style Dimension | Weight  | Interpretation         |
|:----------------|--------:|:-----------------------|
| Market (MKT)    |  59.9%  | Core equity exposure   |
| Size (SMB)      |  16.0%  | Mid-cap tilt           |
| Value (HML)     |   5.2%  | Slight value           |
| Quality (RMW)   |  12.9%  | Moderate quality       |
| Investment (CMA)|   6.0%  | Moderate conservative  |

**Style classification**: Mid Growth (R-squared: 0.32)
**Value tilt**: 0.18 (0.0 = pure growth, 1.0 = pure value)
**Size tilt**: 0.16 (positive = small-cap bias)

---

## 3. Watchlist Review -- Additions and Removals

### Current Watchlist Inventory

| Watchlist       | Items | Coverage                        |
|:----------------|------:|:--------------------------------|
| Core Watchlist  |    38 | Full investment universe         |
| Personal        |    13 | Holdings + near-term candidates  |
| US Aristocrats  |    10 | 25+ year dividend growers (US)   |
| EU Aristocrats  |    10 | European quality dividend payers |
| FI Aristocrats  |    10 | Finnish dividend champions       |
| SE Aristocrats  |    10 | Swedish dividend champions       |
| Tech & AI       |    10 | Technology/semiconductor leaders |

### Recommended Watchlist Additions

Based on the Munger screen results and cross-referencing with the existing watchlists, the following securities score well quantitatively but are NOT currently on any watchlist:

| Ticker    | Name           | Composite | Sector               | Rationale                                    |
|:----------|:---------------|----------:|:---------------------|:---------------------------------------------|
| NFLX      | Netflix        |    0.8383 | Communication Svc    | Strong FCF yield + gross margin, add to Core |
| NOW       | ServiceNow     |    0.5701 | Information Tech     | High quality SaaS, add to Tech & AI          |
| TEAM      | Atlassian      |    0.4619 | Information Tech     | Improving margins, add to Tech & AI          |

### Recommended Watchlist Removals

| Ticker    | Current List  | Composite | Rationale                                          |
|:----------|:--------------|----------:|:---------------------------------------------------|
| DIS       | (if present)  |   -0.2122 | Lowest composite score, weak fundamentals trend     |
| SFOODS.HE | Personal     |    0.0000 | Pre-revenue, no fundamental data, speculative hold  |
| XMAF.DE   | Core         |       N/A | Africa ETF with -8.5% PnL, no ETF scoring data     |

### Watchlist Health Check

- **US Aristocrats**: Good coverage of classic dividend growers (KO, JNJ, PEP, XOM, ADP). Consider adding MDT from screen results.
- **EU Aristocrats**: Strong selection (Novo Nordisk, LVMH, Sanofi, Nestle, Unilever). Well balanced.
- **FI Aristocrats**: Solid Finnish quality names (Sampo, Elisa, Kone, Nordea). Kemira and Wartsila add industrial diversification.
- **SE Aristocrats**: Excellent Swedish industrial base (Atlas Copco, Investor AB, Assa Abloy, Volvo, Sandvik).
- **Tech & AI**: Semiconductor-heavy (NVDA, TSM, MRVL, CDNS). Good but could use software diversification -- NOW and TEAM are candidates.

---

## 4. Backtest Summary

The backtesting system is available at `/api/v1/backtest/run` with predefined strategies. Based on the current portfolio allocation and the default Munger-Boglehead strategy configuration:

### Default Strategy Parameters
- **Start**: 2011-03-21 -- **End**: 2026-03-21
- **Initial capital**: EUR 20,000
- **Monthly contribution**: EUR 500
- **Rebalance frequency**: Quarterly
- **Allocation**: 75% equity / 15% fixed income / 7% crypto / 3% cash
- **Glidepath**: Active (age-based equity reduction)

### Current Portfolio Performance Metrics (from Risk endpoint)

| Metric                  | Value           | Assessment       |
|:------------------------|:----------------|:-----------------|
| Annualized return       | -5.67%          | Poor (negative)  |
| Annualized volatility   | 11.69%          | Moderate          |
| Sharpe ratio            | -0.74           | Poor (negative)  |
| Sortino ratio           | -0.88           | Poor              |
| Max drawdown            | -11.40%         | Moderate          |
| Daily VaR (95%)         | -1.38%          | Acceptable       |
| Daily VaR (EUR)         | -EUR 4,041.93   |                  |
| Beta                    | 1.00            | Market-neutral    |
| Trading days tracked    | 122             |                  |

**Assessment**: The portfolio has underperformed over the tracked 122-day period with negative risk-adjusted returns. The negative Sharpe (-0.74) indicates returns have not compensated for the risk taken. The max drawdown of -11.4% is within tolerance for a moderate-aggressive profile, but the negative absolute return warrants attention.

### Stress Test Results

| Scenario                | Portfolio Impact | After-Stress Value |
|:------------------------|:----------------:|:-------------------|
| 2008 Financial Crisis   |     -47.3%       | EUR 153,843        |
| Rate Shock (+200bp)     |     -14.1%       | EUR 250,839        |
| Crypto Winter           |      -6.2%       | EUR 274,061        |
| Stagflation             |     -28.4%       | EUR 209,035        |
| Nordic Housing Crisis   |   (truncated)    | (see risk endpoint)|

The 2008-style crash scenario shows a severe -47.3% impact, which is higher than expected for a portfolio with a large bond ETF. This is because ALYK is classified as "etf" (equity) in the system rather than "fixed_income", so the stress model applies equity shocks to it. **This classification error must be corrected.**

---

## 5. Optimal Weights -- Mean-Variance Analysis

The mean-variance optimizer at `/api/v1/optimization/optimal` returned an internal server error, likely due to insufficient overlapping price history across all holdings (only 84-122 trading days available). Below is a factor-based allocation recommendation derived from the screening and factor analysis.

### Recommended Target Allocation (Age 45, Glidepath-Compliant)

#### Asset Class Level

| Asset Class   | Current | Target  | Action      |
|:--------------|--------:|--------:|:------------|
| Equity (core) |  ~40%   |  45-50% | Increase via VWCE/IWDA |
| Equity (satellite) | ~18% | 25-30% | Selective adds from screen |
| Fixed Income  |  ~58%*  |   15%   | Reduce ALYK gradually |
| Crypto        |   2.0%  |    7%   | Top up BTC/ETH |
| Cash          |   6.5%  |    3%   | Deploy excess |

*ALYK (57.6%) is a short-term corporate bond fund. The system classifies it as ETF/equity, but it is functionally fixed income.

#### Top Security-Level Recommendations (from Munger Screen + Watchlist Overlap)

For the Munger satellite (30-40% of equity sleeve):

| Priority | Ticker      | Action   | Target Weight | Rationale                                       |
|---------:|:------------|:---------|:--------------|:------------------------------------------------|
|        1 | MSFT        | HOLD     |  3-5%         | Already held, quality score 0.78, IT leader     |
|        2 | SAN.PA      | HOLD     |  2-3%         | Already held, top-5 screen score 1.08, defensive healthcare |
|        3 | BRK-B       | HOLD     |  2-3%         | Already held, Munger approved, diversified conglomerate |
|        4 | SAMPO.HE    | BUY      |  2-3%         | FI aristocrat, score 0.66, quality financials   |
|        5 | ATCO-A.ST   | BUY      |  2-3%         | SE aristocrat, score 0.50, Swedish industrial   |
|        6 | NOVN.SW     | BUY      |  1-2%         | EU aristocrat, score 0.52, defensive healthcare |

For the Boglehead core (60-70% of equity sleeve):

| Priority | Ticker | Action | Rationale                                              |
|---------:|:-------|:-------|:-------------------------------------------------------|
|        1 | VWCE   | BUY    | All-world accumulating ETF -- primary core vehicle     |
|        2 | IWDA   | HOLD   | If already held; VWCE preferred for new money          |

#### Positions to Review for Reduction/Exit

| Ticker     | Current Weight | Issue                                              |
|:-----------|---------------:|:---------------------------------------------------|
| KESKOB.HE  | 18.2% combined | Concentration risk, negative composite score (-0.19), split across 2 accounts |
| ALYK       | 57.6%          | Excessive fixed income vs. 15% target, deploy into equities |
| SFOODS.HE  | 0.04%          | Speculative micro-cap, no fundamentals, -16.5% PnL |
| XMAF.DE    | 0.3%           | Illiquid niche ETF, -8.5% PnL, no screening data  |
| INRG.L     | (held)         | Clean energy ETF -- check performance and mandate fit |

---

## 6. Correlation Highlights

The correlation analysis across 15 priced holdings reveals:

**High correlations (diversification concern)**:
- ETH / BTC: +0.917 (expected -- both are major crypto assets)
- BTC / CRO: +0.569 (crypto cluster)
- RDDT / AMZN: +0.458 (US growth tech cluster)

**Low/negative correlations (diversification benefit)**:
- BRK-B / BTC: +0.006 (essentially uncorrelated)
- AMZN / INRG.L: -0.006 (uncorrelated)
- BNP.PA / INRG.L: +0.002 (uncorrelated)

**Assessment**: The crypto holdings (ETH, BTC, CRO) are highly correlated and behave as a single risk block. Finnish holdings (Kesko, Kemira, Nordea) show moderate intercorrelation (0.25-0.30). US tech names (MSFT, AMZN, RDDT) cluster moderately (0.30-0.46). The cross-region correlations are low, which provides genuine diversification benefit.

---

## 7. Key Findings and Action Items

### Critical Issues

1. **ALYK classification error**: The Alandsbanken short-term corporate bond fund (57.6% of portfolio) is classified as "etf" with no sector tag of "Fixed Income" in the glidepath system, causing the allocation tracker to show 0% fixed income and 91.7% equity. The stress test model incorrectly applies equity shocks to it. **Fix: Update security asset_class or add glidepath override logic.**

2. **Kesko concentration**: Combined Kesko position is 18.2% across two accounts with a negative quality score (-0.19). This exceeds the 5% single-stock guideline (breach flagged in risk system). The position in the regular account (8.2%) should be reviewed for reduction.

3. **Fundamental data gaps**: The Munger screen has only 2-3 factors available for most securities (out of 10). ROIC, ROE, P/E, D/E, and earnings growth are missing for nearly all stocks. **Priority: Enrich Yahoo Finance fundamental data pipeline to include income statement and balance sheet metrics.**

4. **ETF screen non-functional**: Returns 0 results due to missing ETF metadata (TER, AUM, domicile, distribution type). Cannot perform Boglehead core screening.

### Recommendations Summary

| Priority | Action                                           | Impact        |
|---------:|:-------------------------------------------------|:--------------|
|        1 | Fix ALYK asset class to "bond" or "fixed_income" | Corrects glidepath, stress tests |
|        2 | Reduce Kesko to max 5% total portfolio weight    | Reduces concentration risk |
|        3 | Begin ALYK-to-VWCE rebalancing per PM strategy   | Aligns with glidepath |
|        4 | Add SAMPO.HE, ATCO-A.ST, NOVN.SW to satellite   | Diversifies quality exposure |
|        5 | Enrich fundamental data for all tracked securities| Improves screen accuracy |
|        6 | Add ETF metadata for Boglehead screen            | Enables core portfolio optimization |
|        7 | Top up BTC/ETH toward 7% crypto allocation       | Aligns with glidepath |

---

*Report generated by Quantitative Analyst agent on 2026-03-23. Data pipelines refreshed prior to analysis. Factor data through 2026-01-30. Price data through 2026-03-23 (stocks) / 2026-03-20 (US markets).*
