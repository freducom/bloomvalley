# Compliance Officer Report

**Date:** 2026-03-23
**Portfolio Total Value:** EUR 292,096.06
**Report Type:** Full Portfolio Compliance Review

---

## 1. Portfolio Allocation vs. Glidepath Target

| Asset Class       | Current Value (EUR) | Current % | Target % (Age 45) | Deviation |
|-------------------|--------------------:|----------:|-----------:|----------:|
| Equities (stocks + equity ETFs) | 110,266.63 | 37.75% | 75% | **-37.25 pp** |
| Fixed Income (ALYK) | 157,491.30 | 53.92% | 15% | **+38.92 pp** |
| Crypto            | 5,467.13            | 1.87%     | 7%         | -5.13 pp  |
| Cash              | 18,871.00           | 6.46%     | 3%         | +3.46 pp  |

### Glidepath Assessment: SIGNIFICANT DEVIATION

The portfolio is dramatically overweight fixed income and underweight equities relative to the age-45 glidepath target. The fixed-income allocation (53.92%) is nearly 4x the 15% target, while equities (37.75%) are roughly half the 75% target. This allocation profile more closely resembles a post-retirement defensive posture (age 60+) than the growth-oriented profile appropriate for a 45-year-old with a 15-year horizon.

**Severity: HIGH** -- This is not a policy violation per se (there are no hard limits), but this is a material misalignment with stated investment policy that warrants immediate attention from the Portfolio Manager.

---

## 2. Position Limits and Concentration Analysis

No hard position limits are defined in policy. The following notable concentrations are flagged for awareness:

### By Security
| Security | Value (EUR) | % of Portfolio | Flag |
|----------|------------:|---------------:|------|
| ALYK (Alandsbanken Lyhyt Yrityskorko) | 157,491.30 | 53.92% | Dominant position |
| KESKOB.HE (Kesko Oyj B) - combined | 49,709.42 | 17.02% | Notable concentration |
| KEMIRA.HE (Kemira Oyj) | 10,776.00 | 3.69% | Acceptable |
| MSFT (Microsoft) | 9,913.89 | 3.39% | Acceptable |
| BNP.PA (BNP Paribas) | 7,934.00 | 2.72% | Acceptable |
| SAN.PA (Sanofi) | 6,108.80 | 2.09% | Acceptable |
| EVO.ST (Evolution) | 5,321.58 | 1.82% | Acceptable |

### By Sector (Equities Only)
| Sector | Value (EUR) | % of Equities | Observation |
|--------|------------:|--------------:|-------------|
| Consumer Staples (Kesko, Solar Foods) | 49,820.96 | 45.18% | Heavy overweight |
| Financials (BNP, Nordea, Aktia) | 12,452.40 | 11.29% | Moderate |
| Materials (Kemira) | 10,776.00 | 9.77% | Single-name exposure |
| Information Technology (MSFT, XDWT.DE) | 10,654.05 | 9.66% | Moderate |
| Consumer Discretionary (EVO, AMZN) | 9,409.42 | 8.53% | Moderate |
| Health Care (Sanofi) | 6,108.80 | 5.54% | Single-name exposure |
| Communication Services (Reddit) | 4,236.04 | 3.84% | Single-name exposure |

**Observation:** Consumer Staples (primarily Kesko) dominates equity holdings at 45%. This is a significant single-name/sector concentration. Not a policy violation but a diversification concern.

---

## 3. Account Structure Compliance

### OST (Osakesaastotili) Account
- **Holdings:** KESKOB.HE (Kesko Oyj B) -- Finnish equity. **COMPLIANT.**
- **Deposit cap:** EUR 50,000 lifetime. Tracked deposits: EUR 0 (0% used). **COMPLIANT.**
- **Current value:** EUR 27,233.42
- **Note:** The zero deposit tracking suggests deposits have not been recorded in the system. This is a **DATA QUALITY FLAG** -- OST deposit history should be populated to ensure the EUR 50,000 cap is monitored accurately.

### OST Eligibility Check
- No crypto in OST: **PASS**
- No bonds in OST: **PASS**
- Holdings are Finnish/EU equities: **PASS** (KESKOB.HE is Finnish)

### Regular Account (Nordnet)
- Contains stocks, ETFs, and fixed income fund: **COMPLIANT.** All permitted asset types.

### Crypto Wallet
- Contains only crypto assets (BTC, ETH, XRP, CRO, SHIB, ADA, MOON): **COMPLIANT.**

**Account Structure: PASS**

---

## 4. Investment Style Compliance

| Rule | Status | Detail |
|------|--------|--------|
| No leverage | **PASS** | No leveraged positions detected |
| No options | **PASS** | No options positions detected |
| No margin trading | **PASS** | No margin detected |
| No day trading | **PASS** | All lots acquired 2026-03-20/21, no closed lots |
| Prefer ACC ETFs | **PASS** | XDWT.DE, XGID.DE, XMAF.DE are accumulating; INRG.L is accumulating |
| Minimize turnover | **PASS** | No trades closed; portfolio is newly established |

**Investment Style: PASS**

---

## 5. Tax Compliance Review

### Unrealized P&L Summary
| Status | Count | Total (EUR) |
|--------|------:|------------:|
| Unrealized losses | ~15 positions | Approx. -9,170 EUR |
| Unrealized gains | ~3 positions | Approx. +2,173 EUR |
| Crypto (zero cost basis) | 7 positions | Cost basis EUR 0 -- see flag below |

### Tax Observations

1. **Loss Harvesting:** All positions are very new (acquired 2026-03-20/21, holding period < 1 week). Loss harvesting at this stage would likely violate the substance-over-form doctrine and is NOT recommended. **No action required.**

2. **Crypto Cost Basis Missing:** All 7 crypto positions show a cost basis of EUR 0. This creates a tax reporting risk -- when these are eventually sold, the full proceeds would be treated as taxable gain. **ACTION REQUIRED:** Populate actual acquisition costs for crypto holdings.

3. **Finnish Tax Rates:** 30% on capital gains up to EUR 30,000; 34% above EUR 30,000. No realized gains this year. No compliance concern at this time.

4. **OST Tax Treatment:** Gains within OST are tax-deferred. KESKOB.HE position currently shows unrealized loss of EUR -3,559.72 within OST. No tax event.

**Tax Compliance: PASS (with data quality flag on crypto cost basis)**

---

## 6. Data Quality Flags

| Issue | Severity | Detail |
|-------|----------|--------|
| MOON (crypto) has no price data | MEDIUM | Price is null, market value is null. Cannot assess position value. |
| Crypto cost basis all EUR 0 | HIGH | 7 crypto positions with zero cost basis. Tax reporting will be inaccurate. |
| OST deposit history empty | MEDIUM | Deposit cap tracking requires accurate deposit records. |
| XMAF.DE, XGID.DE, ALYK prices marked "manual" | LOW | Manual prices may become stale. Ensure regular updates. |
| Several USD-priced stocks have priceDate 2026-03-20 (Friday) | LOW | Weekend stale -- acceptable, will update Monday. |

---

## 7. Overall Compliance Summary

| Category | Status | Severity |
|----------|--------|----------|
| Position Limits | **PASS** | No hard limits violated |
| Account Structure | **PASS** | All holdings in correct accounts |
| Investment Style | **PASS** | No prohibited instruments or strategies |
| Tax Compliance | **CONDITIONAL PASS** | Crypto cost basis must be populated |
| Glidepath Alignment | **FLAG** | Severe underweight equities, overweight fixed income |
| Cash Minimum (3%) | **PASS** | Cash at 6.46%, above 3% minimum |
| Data Quality | **FLAG** | MOON missing price, crypto cost basis zero, OST deposits untracked |

---

## 8. Recommended Actions

### Immediate (Priority 1)
1. **Populate crypto cost basis** -- Enter actual acquisition costs for BTC, ETH, XRP, CRO, SHIB, ADA, and MOON. Current zero-cost-basis entries will cause incorrect tax calculations on any future sale.
2. **Record OST deposit history** -- Enter historical deposits into OST to enable accurate tracking against the EUR 50,000 lifetime cap.
3. **Obtain MOON pricing** -- The MOON token has no price source. Either set up a price feed or mark as worthless if appropriate.

### Strategic (Priority 2)
4. **Address glidepath misalignment** -- The Portfolio Manager should evaluate whether the current 54% fixed income / 38% equity split is intentional or requires rebalancing toward the 75% equity / 15% fixed income target. This is the most significant compliance observation in this review.
5. **Diversify equity concentration** -- Kesko represents 17% of total portfolio and 45% of equities. Consider whether this single-name concentration aligns with the Munger/Boglehead hybrid philosophy (60-70% index core).

---

## 9. No Proposed Trades to Review

No pending trade proposals were submitted for compliance review. This report covers the static portfolio state as of 2026-03-23.

When trade proposals are submitted, each will be evaluated against:
1. Position limit impact
2. Glidepath directional effect
3. Tax implications
4. Account placement eligibility
5. Investment style adherence

---

*Report generated: 2026-03-23 | Compliance Officer Agent | Bloomvalley Terminal*
