# Graham / Browne — Statistical Deep Value

**Status: DRAFT**

Canonical criteria for the Graham (defensive investor) + Browne (Tweedy Browne, *The Little Book of Value Investing*) style: statistical cheapness across multiple lenses, plus enough financial soundness that the discount reflects mispricing rather than terminal decline. This spec is the reference used by the `graham-browne-analyst` agent and the `Graham/Browne` screener preset.

## Dependencies

- Specs: [screening-factors](../03-calculations/screening-factors.md), [F03-watchlist-screener](../04-features/F03-watchlist-screener.md), [spec-conventions](../00-meta/spec-conventions.md)
- Sibling: [buffett-munger](buffett-munger.md)
- Data: Yahoo Finance fundamentals pipeline, OpenInsider / Nasdaq Nordic / FI+SE insider pipelines, dividends pipeline

## Philosophy Summary

- **Price first, quality second.** A cheap enough price is its own margin of safety; the business need not be wonderful. Graham was willing to buy statistically cheap junk in a basket; Browne modernised the same lens with more metrics (P/CF, EV/EBITDA, insider buying, buybacks) and a global universe.
- **Multiple cheapness confirmations.** No single ratio is enough — Browne's rule is that a name should look cheap on several independent measures at once.
- **Diversify away idiosyncratic risk.** Deep value has high dispersion; hold ≥ 20 names (Browne) up to Graham's 30+.
- **Hold to fair value.** Exit when the discount closes, typically 2–5 years. Not a forever holding.
- **Contrarian by construction.** The screen surfaces names the market currently hates. That is the point.

## Hard Criteria (all must pass)

Every candidate must clear each of these thresholds. Missing data on any single criterion does NOT auto-fail — the criterion is skipped and marked "insufficient data" — but a candidate that clears < 4 of the 6 available criteria is rejected.

| # | Criterion | Threshold | Source | Rationale |
|---|-----------|-----------|--------|-----------|
| G1 | **P/B** | ≤ 1.5 | `fundamentals.priceToBook` | Graham's book-value ceiling; Browne's core lens |
| G2 | **P/E (trailing)** | ≤ 15 | `fundamentals.peRatio` | Graham defensive-investor cap on earnings multiple |
| G3 | **Graham number** | P/E × P/B ≤ 22.5 | derived | Combined valuation guardrail — allows one to breach if the other is very low |
| G4 | **FCF Yield** | ≥ 6 % | `fundamentals.fcfYield` | Confirms the cheapness is backed by cash, not just accounting book |
| G5 | **Dividend Yield** | ≥ 3 % OR paid uninterrupted 10+ yrs | `fundamentals.dividendYield`, dividends pipeline | Browne: income component + management discipline signal |
| G6 | **Solvency** | Net Debt / EBITDA ≤ 3× | `fundamentals.netDebtEbitda` | Graham: "strong financial condition" — filters value-trap balance sheets |

## Soft Criteria (bonus — used for ranking, not filtering)

Points contribute to a `graham_browne_score` (0–100) used to rank passing candidates. Each bonus adds the listed weight to the score; base score is 60 for a hard-criteria pass.

| # | Signal | Weight | Source |
|---|--------|--------|--------|
| S1 | Insider net-buying in last 6 months (aggregate ≥ 0.05 % of market cap) | +10 | insider pipelines (OpenInsider, FI-SE-nordic, Nasdaq Nordic) |
| S2 | Active buyback programme announced or in-progress | +8 | fundamentals + news pipeline |
| S3 | P/B ≤ 1.0 (below book) | +6 | derived |
| S4 | Dividend uninterrupted for 20+ years (Graham defensive rule) | +6 | dividends pipeline |
| S5 | Net cash on balance sheet (Net Debt/EBITDA < 0) | +5 | fundamentals |
| S6 | Small/mid cap (< €5 B market cap) — where value dispersion is highest | +5 | fundamentals |

Max theoretical score: 100.

## Hard Exclusions

Fail regardless of score:

- **Sector filter**: exclude sectors where P/B and P/E are structurally uninformative — `Energy` (commodity-price driven), `Biotechnology` (pre-revenue), and pure-play `Miners` unless the analyst opts in per-name. Financials are allowed but flagged (banks live at low P/B by design).
- **Earnings quality red flags**: any security marked `earnings_quality = "red_flag"` in research notes is excluded.
- **Delisting / going-concern**: `is_active = FALSE` or `going_concern_warning = TRUE`.
- **Micro-cap illiquid**: market cap < €50 M or average daily traded value < €100 k (Graham's "adequate size" rule, scaled down for the Nordic universe).
- **Stock-based comp > 15 % of revenue** (Graham era had no SBC; Browne-modern rule: SBC dilution can hide poor economics).

## Universe Scope

- Nordic (XHEL, XSTO, XCSE, XOSL) — Browne emphasised international diversification and inefficiency in smaller markets.
- European ex-Nordic (XETR, XPAR, XAMS, XMIL, XMAD, LSE, SIX).
- US (XNYS, XNAS) — included but expect fewer passers; US is more efficient.
- **Excluded**: ETFs, crypto, bonds (deep value is a stock-selection style).

## Portfolio Construction

- **Diversify**: hold ≥ 15 names when using this style (Browne's practical floor; Graham said 30+).
- **Size equal-weight**: no oversized bets — deep-value dispersion is high, so the individual-name error is compensated by the basket.
- **Hold horizon**: 2–5 years, exit when discount closes to fair value or the thesis breaks (accounting restatement, dividend cut, covenant breach).

## Output Contract (agent + screener)

The screener returns candidates ranked by `graham_browne_score` descending. Each candidate row includes:

- `ticker`, `name`, `sector`, `country`
- Hard-criteria pass/fail per G1–G6 (with the actual value beside each)
- `graham_browne_score` (0–100)
- Soft-criteria hits (list of triggered S-signals)
- Last data update per source (staleness marker if any hard-criterion input > 90 days old)
- Explicit "why passed" one-liner ("cheap on P/B, P/E, FCF-yield; insider buying")

## Edge Cases

1. **Missing book value** (some securities lack balance-sheet data): G1 and G3 are marked "insufficient data" and skipped. Candidate must still clear ≥ 4 of the remaining criteria to pass.
2. **Financials (banks, insurance)**: P/B is meaningful but at different levels — a bank at P/B 0.6 is not automatically deep value (may be fairly priced for its ROE). Financials pass through the screen but are labelled `sector = financial` and the analyst is expected to apply an excess-return-model overlay before flagging.
3. **REITs**: FCF Yield criterion is replaced with `FFO Yield ≥ 6 %` where FFO data is available; otherwise REIT is skipped.
4. **Cyclicals at cycle top**: a homebuilder or steelmaker showing P/E 6 at peak earnings is a value trap. The analyst must flag when trailing earnings sit > 1.5× the 10-year average — the P/E test is applied against 3-year-average earnings in that case (Graham's original rule).
5. **Buyback + dividend cut combo**: if a name shows S2 (buyback) but recent dividend was cut, the combined signal is treated as neutral (management chose buyback over yield), and G5 must be satisfied via dividend-history rather than current yield.
6. **Nordic small caps with sparse coverage**: acceptable to run the screen on only G1, G2, G3, G6 if G4/G5 data unavailable — but the candidate carries a `low_data_confidence` flag.

## Silent-If-Zero Rule

If the screen returns zero candidates, the `graham-browne-analyst` agent **does not produce a report**. It writes a one-line log entry (`No Graham/Browne candidates today. Universe: N, passed hard criteria: 0.`) and exits. No filler, no "here's what we're watching" — the whole point of the style is patience; empty output IS the output.

## Changelog

| Date | Change |
|------|--------|
| 2026-07-29 | Initial draft |
