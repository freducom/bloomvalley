# Glidepath Calculation, Drift Detection & Rebalancing

The glidepath defines the target asset allocation trajectory from age 45 (now) to age 60 (retirement). This spec covers how to compute the target allocation for any given date, detect drift from that target, and generate a tax-efficient rebalancing plan. The glidepath is the single most important guardrail in the portfolio: it enforces the disciplined shift from growth to capital preservation.

**Status: DRAFT**

## Dependencies

- [Spec Conventions](../00-meta/spec-conventions.md) — monetary format, terminology
- [Data Model](../01-system/data-model.md) — `accounts`, `securities`, `positions`, `tax_lots` tables; `securities_asset_class_enum`
- [Finnish Tax](../03-calculations/tax-finnish.md) — capital gains tax rates, osakesaastotili rules, deemed cost of acquisition

---

## Target Allocation Table

Defined anchor points from the investment policy ([AGENTS.md](../../AGENTS.md)):

| Age | Equities | Fixed Income | Crypto | Cash |
|-----|----------|--------------|--------|------|
| 45  | 75%      | 15%          | 7%     | 3%   |
| 48  | 68%      | 23%          | 6%     | 3%   |
| 50  | 62%      | 30%          | 5%     | 3%   |
| 53  | 55%      | 38%          | 4%     | 3%   |
| 55  | 47%      | 47%          | 3%     | 3%   |
| 58  | 38%      | 55%          | 2%     | 5%   |
| 60  | 30%      | 60%          | 2%     | 8%   |

**Equities sub-split** (applied after computing the equities allocation):
- 60-70% of the equities allocation goes to index ETFs (Boglehead core)
- 30-40% of the equities allocation goes to individual stocks (Munger satellite)
- Default split: 65% core / 35% satellite

These sub-split percentages are user-configurable via the `user_settings` table.

### Asset Class Mapping

The `securities_asset_class_enum` values map to glidepath classes as follows:

| `asset_class` enum | Glidepath class | Notes |
|--------------------|----------------|-------|
| `stock`            | Equities       | Munger satellite bucket |
| `etf` with equity underlying | Equities | Boglehead core bucket |
| `etf` with bond underlying   | Fixed Income | Determined by `sector` or `etf_asset_class` field |
| `bond`             | Fixed Income   | Direct bond holdings |
| `crypto`           | Crypto         | All crypto wallets |
| Cash balances      | Cash           | Uninvested account balances |

**ETF classification**: ETFs are classified by their `sector` field in the `securities` table. Values containing "bond", "fixed income", "treasury", or "aggregate" map to Fixed Income. All others map to Equities. If `sector` is NULL, fall back to the ETF name heuristic or manual override in `research_notes`.

---

## Linear Interpolation

For any date between anchor points, the target allocation is computed by linear interpolation.

### Inputs

- `birth_date: DATE` — the user's date of birth (from `user_settings`)
- `as_of_date: DATE` — the date to compute the target for (typically today)
- `anchor_points: list[tuple[int, dict]]` — the table above

### Algorithm

```
age_exact = (as_of_date - birth_date).days / 365.25

For each asset_class in [equities, fixed_income, crypto, cash]:
    Find the two anchor points age_lo and age_hi such that age_lo <= age_exact < age_hi

    If age_exact <= 45:
        target = anchor_points[45][asset_class]
    Elif age_exact >= 60:
        target = anchor_points[60][asset_class]
    Else:
        frac = (age_exact - age_lo) / (age_hi - age_lo)
        target = anchor_points[age_lo][asset_class] + frac * (anchor_points[age_hi][asset_class] - anchor_points[age_lo][asset_class])

Return { equities: target_eq, fixed_income: target_fi, crypto: target_cr, cash: target_ca }
```

### Worked Example

User born 1981-03-19, as_of_date = 2027-09-19.

```
age_exact = (2027-09-19 - 1981-03-19).days / 365.25 = 46.50 years

Anchors: age_lo = 45, age_hi = 48
frac = (46.50 - 45) / (48 - 45) = 0.50

equities:     75% + 0.50 * (68% - 75%) = 75% - 3.5% = 71.5%
fixed_income: 15% + 0.50 * (23% - 15%) = 15% + 4.0% = 19.0%
crypto:        7% + 0.50 * ( 6% -  7%) =  7% - 0.5% =  6.5%
cash:          3% + 0.50 * ( 3% -  3%) =  3% + 0.0% =  3.0%

Sum check: 71.5 + 19.0 + 6.5 + 3.0 = 100.0%   OK

Equities sub-split (65/35 default):
  Core ETFs:       71.5% * 0.65 = 46.475%
  Satellite stocks: 71.5% * 0.35 = 25.025%
```

---

## Current Allocation Calculation

### Inputs

- All rows from the `positions` view (account_id, security_id, quantity, market_value_eur_cents)
- The `securities` table for asset_class classification
- Uninvested cash balances per account

### Algorithm

```
total_value = sum(position.market_value_eur_cents for all positions) + sum(cash balances)

For each glidepath_class in [equities, fixed_income, crypto, cash]:
    class_value = sum(market_value_eur_cents for positions where security maps to glidepath_class)
    if glidepath_class == 'cash':
        class_value += sum(uninvested cash balances)
    current_weight[glidepath_class] = class_value / total_value

For equities sub-split:
    core_value = sum(market_value for ETF positions classified as equities)
    satellite_value = sum(market_value for stock positions)
    core_pct = core_value / (core_value + satellite_value)
    satellite_pct = satellite_value / (core_value + satellite_value)
```

All intermediate calculations use Python `Decimal` to avoid floating-point drift. Weights are stored as `NUMERIC(8, 6)` (six decimal places, e.g., 0.715000 for 71.5%).

---

## Drift Detection

### Definition

For each asset class:

```
drift[class] = abs(current_weight[class] - target_weight[class])
```

### Thresholds

| Threshold | Action |
|-----------|--------|
| drift < 2% | No action (green) |
| 2% <= drift < 5% | Monitor (yellow) — log to `alerts` table with type `drift_threshold` |
| drift >= 5% | Rebalance recommended (red) — trigger alert, surface on dashboard |

The 5% threshold is the primary trigger defined in the investment policy. The 2% monitoring threshold provides early warning.

### Drift Check Frequency

- Computed daily after market close prices are ingested
- Stored in a `portfolio_snapshots` table (date, asset_class, target_weight, actual_weight, drift)
- UI displays the current drift alongside the glidepath chart

---

## Rebalancing Algorithm

When drift exceeds the 5% threshold for any asset class, the system generates a rebalancing plan.

### Principles

1. **Minimize trades** — fewest possible transactions to bring all classes within 2% of target
2. **Prefer buying underweight over selling overweight** — avoids triggering capital gains tax
3. **Respect osakesaastotili constraints** — this account can only hold stocks and equity ETFs; cannot hold bonds, crypto, or cash beyond settlement
4. **Tax efficiency** — estimate tax impact of every sell trade; prefer selling lots with losses or lots held >10 years (deemed cost of acquisition benefit)
5. **Cash flow first** — if the user has pending contributions, direct them to underweight classes before selling

### Algorithm: Cash-Flow Rebalancing (Preferred)

Used when new cash is available (contributions, dividends, etc.):

```
Input:
    new_cash_eur_cents: int           -- available cash to deploy
    current_weights: dict[str, Decimal]
    target_weights: dict[str, Decimal]
    total_portfolio_eur_cents: int

new_total = total_portfolio_eur_cents + new_cash_eur_cents

For each asset_class, sorted by (target_weight - current_weight) descending:
    target_value = new_total * target_weight[class]
    current_value = total_portfolio_eur_cents * current_weight[class]
    deficit = target_value - current_value

    if deficit > 0:
        buy_amount = min(deficit, remaining_cash)
        allocate buy_amount to this class
        remaining_cash -= buy_amount

If remaining_cash > 0:
    allocate to cash class

Output: list of (asset_class, buy_amount_eur_cents)
```

### Algorithm: Sell/Buy Rebalancing (When Cash-Flow Is Insufficient)

```
Input:
    current_weights, target_weights, total_portfolio_eur_cents
    tax_lots: list[TaxLot]  -- all open lots with cost_basis, acquisition_date, account_type

Step 1: Compute required trades
    For each asset_class:
        delta[class] = (target_weight[class] - current_weight[class]) * total_portfolio_eur_cents
        -- positive delta = need to buy, negative delta = need to sell

Step 2: Select lots to sell (for classes with negative delta)
    For each class where delta < 0:
        candidates = open tax_lots in this class, sorted by sell priority:
            1. Lots with unrealized LOSS (harvest the loss)
            2. Lots held > 10 years (40% deemed cost rule may apply)
            3. Lots in osakesaastotili (no tax on internal trades)
            4. Lots with smallest gain (minimize tax)

        Select lots until sum(lot.market_value) >= abs(delta[class])

Step 3: Estimate tax impact for each selected lot
    For each lot:
        if lot.account_type == 'osakesaastotili':
            tax_impact = 0  -- no tax on trades inside OSA
        else:
            gain = lot.market_value - lot.cost_basis
            if gain <= 0:
                tax_impact = 0  -- loss, no tax (and loss is harvestable)
            else:
                -- Check deemed cost of acquisition
                deemed_20 = lot.market_value * 0.20
                deemed_40 = lot.market_value * 0.40 if held > 10 years else 0
                actual_cost = lot.cost_basis
                taxable_gain = lot.market_value - max(actual_cost, deemed_20, deemed_40)
                taxable_gain = max(taxable_gain, 0)

                -- Finnish capital gains tax rate
                tax_rate = 0.30  -- or 0.34 if cumulative annual gains > 30_000 EUR
                tax_impact = taxable_gain * tax_rate

Step 4: Generate trade list
    Output: ordered list of:
        {
            action: 'sell' | 'buy',
            security_id: int,
            account_id: int,
            amount_eur_cents: int,
            quantity: Decimal,          -- estimated shares
            tax_lot_id: int | null,     -- for sells, the specific lot
            estimated_tax_cents: int,   -- tax impact of this trade
            rationale: str              -- human-readable explanation
        }

    Sells are listed first, buys second (sells generate cash for buys).
```

### Worked Example: Sell/Buy Rebalancing

Portfolio total: 100,000 EUR.

| Class | Current | Target | Delta |
|-------|---------|--------|-------|
| Equities | 80% (80,000) | 71.5% (71,500) | -8,500 |
| Fixed Income | 10% (10,000) | 19.0% (19,000) | +9,000 |
| Crypto | 7% (7,000) | 6.5% (6,500) | -500 |
| Cash | 3% (3,000) | 3.0% (3,000) | 0 |

Trades generated:
1. **SELL** 8,500 EUR of equities — select lots with lowest tax impact
2. **SELL** 500 EUR of crypto — select lot with smallest gain
3. **BUY** 9,000 EUR of fixed income (bond ETF)

If an equity lot (cost basis 5,000, market value 8,500) is in osakesaastotili: tax = 0 EUR.
If that lot is in a regular account: gain = 3,500, tax = 3,500 * 0.30 = 1,050 EUR.
The algorithm prefers the osakesaastotili lot.

### Osakesaastotili Constraints

- Can only hold: stocks and equity ETFs (`asset_class IN ('stock', 'etf')` where the ETF is equity-classified)
- Cannot hold: bonds, bond ETFs, crypto, or significant cash
- Rebalancing within osakesaastotili is tax-free — always prefer selling here when reducing equities
- Cannot buy fixed income instruments inside osakesaastotili — those must go in regular accounts

---

## Glidepath Visualization Data

The API endpoint `GET /api/v1/glidepath` returns data for three lines:

### 1. Target Line (theoretical)

```
For each month from now to age 60:
    compute target_weights via interpolation
    return { date, equities, fixed_income, crypto, cash }
```

### 2. Actual Line (historical)

```
For each date with a portfolio_snapshot:
    return { date, equities, fixed_income, crypto, cash }
```

### 3. Projected Line (forward drift)

```
If current drift is non-zero and no rebalancing occurs:
    For each future month:
        project current weights forward, adjusted for expected returns per class
        return { date, equities, fixed_income, crypto, cash }
```

The projected line shows where the portfolio is heading if the user takes no action. If drift is zero, the projected line equals the target line.

### API Response Shape

```json
{
  "asOfDate": "2026-03-19",
  "ageExact": 45.0,
  "targetAllocation": {
    "equities": 0.750,
    "fixedIncome": 0.150,
    "crypto": 0.070,
    "cash": 0.030
  },
  "currentAllocation": {
    "equities": 0.780,
    "fixedIncome": 0.120,
    "crypto": 0.070,
    "cash": 0.030
  },
  "drift": {
    "equities": 0.030,
    "fixedIncome": 0.030,
    "crypto": 0.000,
    "cash": 0.000
  },
  "maxDrift": 0.030,
  "rebalanceNeeded": false,
  "equitiesSubSplit": {
    "coreTarget": 0.65,
    "coreActual": 0.60,
    "satelliteTarget": 0.35,
    "satelliteActual": 0.40
  },
  "targetLine": [
    { "date": "2026-04-01", "equities": 0.749, "fixedIncome": 0.151, "crypto": 0.069, "cash": 0.030 }
  ],
  "actualLine": [
    { "date": "2026-03-19", "equities": 0.780, "fixedIncome": 0.120, "crypto": 0.070, "cash": 0.030 }
  ],
  "projectedLine": [
    { "date": "2026-04-01", "equities": 0.781, "fixedIncome": 0.119, "crypto": 0.070, "cash": 0.030 }
  ]
}
```

---

## Edge Cases

1. **Age below 45**: Use the age-45 allocation (no extrapolation beyond the table).
2. **Age above 60**: Use the age-60 allocation (hold steady at retirement targets).
3. **Empty portfolio**: Return target weights with zero drift; rebalancing is just "buy in target proportions."
4. **Single asset class**: If user holds only equities, drift will be large for all other classes. Generate buy-only recommendations.
5. **Osakesaastotili at deposit limit**: If the 50,000 EUR deposit cap is reached, new equity purchases must go to a regular account. The algorithm must check `osa_deposit_total_cents` before suggesting buys in that account.
6. **ETF classification ambiguous**: If an ETF's asset class cannot be determined from `sector` or name, flag it for manual review and exclude from drift calculation until classified.
7. **FX impact on weights**: All market values are converted to EUR before weight calculation. Large FX moves can cause drift even without price changes in local currency.
8. **Rounding**: Target weights from interpolation may not sum to exactly 100% due to floating-point. Normalize by dividing each weight by the sum of all weights.
9. **Tax year boundary**: When generating sell trades near December 31, consider whether pushing the sale to January would result in a lower tax rate (e.g., if the user is near the 30,000 EUR threshold for the 34% rate).
10. **Crypto 24/7 vs stock market hours**: Crypto prices update continuously; stock prices update on market days only. Drift calculation should use the most recent available price for each asset class.

## Open Questions

- Should the equities sub-split (core/satellite ratio) also follow a glidepath, or remain constant at 65/35 throughout?
- Should the system auto-generate rebalancing trades, or only suggest them for manual approval?
- How to handle the transition at age 60 — does the glidepath stop, or does a new withdrawal-phase glidepath begin?

## Changelog

| Date | Change |
|------|--------|
| 2026-03-19 | Initial draft |
