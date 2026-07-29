# Buffett / Munger — Quality Compounders at a Fair Price

**Status: DRAFT**

Canonical criteria for the mature Buffett + Munger style: durable competitive advantage (moat), high returns on capital, low leverage, honest management, and a long reinvestment runway — bought at a fair (not distressed) price. This spec is the reference used by the `buffett-munger-analyst` agent and the `Buffett/Munger` screener preset.

## Dependencies

- Specs: [screening-factors](../03-calculations/screening-factors.md), [F03-watchlist-screener](../04-features/F03-watchlist-screener.md), [spec-conventions](../00-meta/spec-conventions.md)
- Sibling: [graham-browne](graham-browne.md)
- Data: Yahoo Finance fundamentals pipeline, earnings-reports pipeline, dividends pipeline, insider pipelines

## Philosophy Summary

- **"A great business at a fair price, beats a fair business at a great price."** — Munger's line that shifted Buffett away from Graham cigar-butts. Quality first, price second.
- **Economic moat is the single most important variable.** High returns on capital that persist require a barrier — brand, scale, network effects, switching costs, cost advantage, regulatory. No durable moat → no long-term compounding → not a candidate regardless of ratios.
- **Reinvestment runway matters more than dividend yield.** The compounding case depends on management being able to redeploy earnings at high rates. A 25 % ROIC business with room to grow beats a 40 % ROIC business that must pay everything out.
- **Concentrate.** Buffett/Munger portfolios hold ~10–20 names; the top 5 dominate. Once a wonderful business is identified, size matters.
- **Hold forever, ideally.** Turnover is a tax on returns. Sell only if the moat erodes or price becomes egregious.
- **Circle of competence.** If you can't explain the business to a 12-year-old in two minutes, skip it — no matter how good the numbers look.

## Hard Criteria (all must pass)

Every candidate must clear each of these thresholds. Missing data on any single criterion does NOT auto-fail — the criterion is skipped and marked "insufficient data" — but a candidate that clears < 5 of the 7 available criteria is rejected.

| # | Criterion | Threshold | Source | Rationale |
|---|-----------|-----------|--------|-----------|
| B1 | **ROIC** (5-yr average) | ≥ 15 % | `fundamentals.roic` + earnings-reports | Munger's floor — anything below is a fair-to-mediocre business |
| B2 | **ROE** (5-yr average) | ≥ 15 % | `fundamentals.roe` + earnings-reports | Confirms high return on shareholder capital, not just invested capital |
| B3 | **Gross margin** | ≥ 40 % | `fundamentals.grossMargin` | Pricing-power proxy — commodity businesses fail here |
| B4 | **Net Debt / EBITDA** | ≤ 2× | `fundamentals.netDebtEbitda` | Buffett aversion to leverage; keeps the compounder robust to downturns |
| B5 | **FCF Yield** | ≥ 4 % | `fundamentals.fcfYield` | The "fair price" test — not a bargain (that's Graham), just not overpaying |
| B6 | **Earnings consistency** | 8+ of last 10 years positive & no > 40 % drop | earnings-reports pipeline | Durable earnings power, not cyclical |
| B7 | **Owner earnings ≈ reported earnings** | Cash Conversion Ratio ≥ 80 % (OCF / Net Income, 3-yr avg) | fundamentals + earnings-reports | Earnings must convert to cash — otherwise "earnings" are accounting fiction |

## Soft Criteria (bonus — used for ranking, not filtering)

Points contribute to a `buffett_munger_score` (0–100) used to rank passing candidates. Base score is 60 for a hard-criteria pass.

| # | Signal | Weight | Source |
|---|--------|--------|--------|
| S1 | Moat rating = `wide` in research notes | +12 | research_notes |
| S2 | Moat rating = `narrow` in research notes | +6 | research_notes |
| S3 | Buyback programme active AND SBC < 3 % of revenue (real buyback, not dilution offset) | +8 | fundamentals + news pipeline |
| S4 | Insider net-buying in last 6 months | +5 | insider pipelines |
| S5 | Dividend increased for 10+ consecutive years (Aristocrat-track) | +5 | dividends pipeline |
| S6 | Return on tangible capital > 20 % (excludes goodwill / intangible bloat) | +5 | derived |
| S7 | P/E ≤ 20 (fair-price test) — beyond the FCF-yield floor | +3 | fundamentals |

Max theoretical score: 104 (capped at 100).

## Hard Exclusions

Fail regardless of score:

- **No moat**: research notes rating = `none`. No moat → no persistent excess returns → not a Buffett/Munger candidate. If moat is `unknown`, the security passes screening but is flagged for the research-analyst to rate before promotion to any recommendation list.
- **Sector-specific**:
  - Pure-play **commodity miners / oil & gas E&P**: no pricing power, no moat (with rare exceptions like low-cost producers — must be flagged manually).
  - **Airlines**: Buffett's own "aeronautically cursed" list. Excluded unless manually opted in.
  - **Turnaround stories / restructurings**: Buffett rule "turnarounds seldom turn". Excluded.
- **Business-quality red flags**:
  - Stock-based comp > 10 % of revenue (real cost hidden in "adjusted" metrics)
  - Accrual ratio > 10 % (earnings quality deterioration)
  - Auditor change in last 2 years
  - Earnings restatement in last 5 years
- **Leverage**: Net Debt / EBITDA > 3× (hard fail, overrides B4 which was 2×) — for the exclusion list we allow one grace notch, but > 3× is disqualifying.
- **Delisting / going-concern**: `is_active = FALSE` or `going_concern_warning = TRUE`.

## Universe Scope

- **US (XNYS, XNAS)** — deepest quality-compounder universe.
- **European ex-Nordic** — LVMH, ASML, Novo Nordisk-class businesses.
- **Nordic (XHEL, XSTO, XCSE, XOSL)** — smaller but present (Kone, Assa Abloy, Sampo, Novo, Investor AB).
- **Excluded**: ETFs (buy the market ≠ concentrated conviction), crypto, bonds, direct commodities.

## Portfolio Construction

- **Concentrate**: top 5 positions target 50–70 % of the satellite sleeve; total names in style bucket ≤ 15.
- **Position sizing**: proportional to conviction × margin of safety. A wide-moat, high-ROIC compounder trading at a fair FCF-yield gets 5–10 % of the satellite sleeve. A narrow moat gets 2–5 %.
- **Hold horizon**: indefinite. Sell only if:
  1. Moat erodes (new entrant with structural advantage, technology shift, regulatory change)
  2. Management integrity is compromised (accounting issue, capital-allocation malpractice)
  3. Price reaches > 2× intrinsic value (rare but Buffett has done it — see PetroChina, BYD trims)
  4. A meaningfully better opportunity exists (opportunity cost)

## Output Contract (agent + screener)

The screener returns candidates ranked by `buffett_munger_score` descending. Each candidate row includes:

- `ticker`, `name`, `sector`, `country`
- Hard-criteria pass/fail per B1–B7 (with actual value beside each)
- `buffett_munger_score` (0–100)
- Moat rating (if researched) or `moat_unrated` flag
- Soft-criteria hits (list of triggered S-signals)
- Intrinsic value estimate + margin of safety (from research notes, if present)
- Last data update per source (staleness marker if any hard-criterion input > 90 days old)
- Explicit "why passed" one-liner ("wide moat, 22 % ROIC, 5 % FCF yield, buybacks with low SBC")

## Edge Cases

1. **Missing ROIC** (small/foreign companies with sparse fundamentals): B1 is marked "insufficient data" and skipped. Requires B2 (ROE) to compensate.
2. **Financials (banks, insurance)**: gross margin (B3) is not meaningful — skipped. Replaced with `Net Interest Margin ≥ 3 %` (banks) or `Combined Ratio ≤ 95 %` (insurers) where the earnings-reports pipeline exposes them.
3. **Software / SaaS**: gross margins are typically > 70 % (easily clears B3). Beware SBC — the hard exclusion on SBC > 10 % of revenue removes most hyper-growth SaaS from consideration. This is intentional — Munger has publicly derided the SBC-as-marketing-expense fiction.
4. **Holding companies (Berkshire, Investor AB)**: apply criteria to the *look-through* portfolio if data exists; otherwise the analyst applies criteria to the holding-company aggregate and flags the conglomerate structure.
5. **Deeply cyclical wide-moats** (e.g., Freeport, Ferrari-class luxury during recession): B6 (earnings consistency) may fail at a cycle trough. If moat rating is `wide` and long-run ROIC (10-yr) > 15 %, the security passes with a `cyclical_wide_moat` flag.
6. **Value-trap of quality**: a wonderful business at 40× P/E, 1 % FCF yield fails B5 automatically. That is the correct answer — the "fair price" test is what separates Munger from a growth-at-any-price approach.

## Silent-If-Zero Rule

If the screen returns zero candidates, the `buffett-munger-analyst` agent **does not produce a report**. It writes a one-line log entry (`No Buffett/Munger candidates today. Universe: N, passed hard criteria: 0.`) and exits. Compounders don't come along every week; the style depends on patience.

## Interaction With Portfolio Manager

- Buffett/Munger candidates feed the **satellite sleeve** (30–40 % of portfolio per the investor profile).
- The portfolio-manager treats a `buffett_munger_score` ≥ 80 with `wide` moat as promotion-eligible for the recommendation list.
- A `buffett_munger_score` 70–80 with `narrow` moat requires research-analyst deep-dive before promotion.
- Below 70: watchlist only, not recommendation-eligible.

## Changelog

| Date | Change |
|------|--------|
| 2026-07-29 | Initial draft |
