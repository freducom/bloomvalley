# Finnish Tax Rules

This spec defines every Finnish tax rule that the system must implement to calculate gains, losses, dividends, and taxes correctly across all account types. It is the single source of truth for the Tax Strategist agent and the backend tax calculation engine. Errors here cascade into wrong P&L, wrong rebalancing suggestions, and wrong tax reports — making this the highest-risk spec in the project.

**Status: DRAFT**

## Dependencies

- `../00-meta/spec-conventions.md` — monetary values in cents, date handling, naming
- `../01-system/data-model.md` — `tax_lots`, `transactions`, `accounts`, `dividends` tables
- `../03-calculations/tax-lot-tracking.md` — lot creation, matching methods (FIFO, specific ID)

## 1. Capital Income Tax Rates

Finland taxes capital income (*paaomatulo*) at two progressive rates:

| Capital Income Band | Rate |
|---------------------|------|
| 0 - 30,000 EUR/year | 30% |
| Above 30,000 EUR/year | 34% |

**Tax year**: Calendar year, January 1 through December 31.

**Capital income includes** (non-exhaustive):

- Gains from sale of securities (stocks, ETFs, bonds)
- Gains from sale of cryptocurrency
- Dividends (taxable portion — see Section 7)
- Rental income
- Interest income
- Gains from withdrawal from osakesaastotili, kapitalisaatiosopimus
- Royalties

**Implementation note**: The system must aggregate all realized capital income across the entire tax year to determine which rate applies. Income up to and including 30,000 EUR is taxed at 30%; only the portion exceeding 30,000 EUR is taxed at 34%. This is a marginal rate, not an effective rate on the full amount.

### 1.1 Tax Calculation Formula

```
if total_capital_income <= 30_000_00:  # cents
    tax = total_capital_income * 30 / 100
else:
    tax = 30_000_00 * 30 / 100 + (total_capital_income - 30_000_00) * 34 / 100
```

All calculations use integer cents or `Decimal` — never floating-point (per spec conventions).

## 2. Deemed Cost of Acquisition (Hankintameno-olettama)

Finnish tax law allows the taxpayer to choose, **per disposal event**, whichever produces a lower taxable gain:

1. **Actual cost basis** — purchase price + purchase fees, minus selling fees from proceeds
2. **Deemed cost of acquisition** — a percentage of the sale price based on holding period

| Holding Period | Deemed Cost % of Sale Price |
|----------------|----------------------------|
| Less than 10 years | 20% |
| 10 years or more | 40% |

### 2.1 Rules

- The choice is made **per disposal event**, not per tax year or per security.
- When deemed cost is used, **no deduction is allowed** for purchase fees, selling fees, or any other costs. The deemed percentage is the entire deduction.
- Holding period is measured from the **acquisition date** of the specific tax lot to the **disposal date**.
- The system must calculate both methods for every disposal and automatically select the more favorable one (lower tax).
- Deemed cost can never produce a loss — if the deemed cost exceeds proceeds, the gain is zero (not negative). In practice this cannot happen mathematically since deemed cost is a percentage of sale price.

### 2.2 When Deemed Cost is Favorable

Deemed cost (20%) is more favorable when:
```
actual_cost_basis < 80% of sale_price
→ i.e., the stock has gained more than 25% from purchase
```

Deemed cost (40%) is more favorable when:
```
actual_cost_basis < 60% of sale_price
→ i.e., the stock has gained more than ~67% from purchase (held ≥ 10 years)
```

**Key insight**: The more profitable the sale, the more likely deemed cost is favorable. For multi-bagger positions held over 10 years, the 40% deemed cost can save significant tax.

### 2.3 Implementation

For each disposal event, the system must:

1. Calculate `actual_gain = proceeds - selling_fees - cost_basis - purchase_fees`
2. Calculate `deemed_gain_20 = proceeds * 80 / 100` (if held < 10 years)
3. Calculate `deemed_gain_40 = proceeds * 60 / 100` (if held >= 10 years)
4. Select `taxable_gain = min(actual_gain, deemed_gain)` — but only if actual_gain > 0
5. If `actual_gain <= 0` (a loss), deemed cost is irrelevant — use actual cost to realize the loss
6. Store the chosen method on the `tax_lots` record for audit trail

**Note on losses**: Deemed cost cannot be used to create or increase a loss. If the actual sale results in a loss, the taxpayer must use the actual cost basis.

## 3. Osakesaastotili (Equity Savings Account)

The osakesaastotili (OST) is a tax-advantaged account for investing in listed securities.

### 3.1 Core Rules

| Rule | Detail |
|------|--------|
| Lifetime deposit limit | 50,000 EUR |
| Accounts per person | Exactly one (1) |
| Tax on internal trades | None — buy, sell, dividend reinvestment inside the account are all tax-free |
| Tax trigger | Withdrawal of cash from the account |
| Allowed instruments | Listed stocks (regulated markets), UCITS funds, certain ETFs. **No crypto, no unlisted shares, limited bond funds** |
| Transfers between brokers | Allowed as in-kind transfer; does not reset deposit tracking |

### 3.2 Withdrawal Taxation

On withdrawal, only the **gains portion** is taxed as capital income. The gains portion is calculated as:

```
gains_ratio = (account_value - total_deposits) / account_value
taxable_amount = withdrawal_amount * gains_ratio
```

Where:
- `account_value` = total market value of all holdings + cash in the OST at the time of withdrawal
- `total_deposits` = cumulative deposits made into the account minus cumulative withdrawals already made (the remaining "deposit base")
- `withdrawal_amount` = the EUR amount being withdrawn

**If `account_value <= total_deposits`** (the account is at a loss):
- `gains_ratio = 0` — no taxable amount on withdrawal
- The withdrawal is treated as return of deposits only
- **No loss deduction is available** until the account is fully closed

### 3.3 Account Closure

When the OST is closed (all assets liquidated, full withdrawal):

- If `final_value > total_remaining_deposits`: the difference is taxed as capital income
- If `final_value < total_remaining_deposits`: the loss **is deductible** against capital income, following the normal loss deduction rules (Section 6)

This is the **only way** to realize a loss from an OST.

### 3.4 Tracking Requirements

The system must track for each OST account:

- `total_deposits_cents` — cumulative deposits (only increases on deposit, never on internal gains)
- `total_withdrawals_cents` — cumulative withdrawals
- `remaining_deposit_base_cents = total_deposits_cents - total_withdrawals_cents`
- On each withdrawal, reduce `remaining_deposit_base_cents` by `withdrawal_amount * (1 - gains_ratio)`
- Internal transactions (buys, sells, dividends) must **not** generate tax events

### 3.5 Deposit Limit Enforcement

- The system must track lifetime deposits and reject or warn when a deposit would exceed 50,000 EUR
- Withdrawals do **not** restore the deposit limit — it is a **lifetime** cap
- Example: deposit 50,000 EUR, withdraw 20,000 EUR — you cannot deposit another 20,000 EUR

## 4. PS-sopimus (Voluntary Pension Insurance)

### 4.1 Core Rules

| Rule | Detail |
|------|--------|
| Annual deductible contribution | Up to 5,000 EUR deductible from capital income |
| Tax on contributions | Deducted from capital income tax (reduces tax by up to 1,500-1,700 EUR/year) |
| Tax on withdrawals | Taxed as capital income after pension age |
| Pension age | Varies by birth year; for the investor (born ~1981): likely 68-69 years |
| Early withdrawal | Subject to penalty tax — withdrawal amount taxed as capital income + 20% surcharge |
| Internal trades | Tax-deferred — no tax on buy/sell/dividends within the contract |
| Investment options | Limited by provider; typically mutual funds, some allow ETFs |

### 4.2 Deduction Rules

- Maximum 5,000 EUR/year deductible if the taxpayer does **not** have an employer-sponsored pension insurance that covers PS-sopimus deduction
- The deduction is from **capital income**, not earned income
- If capital income is insufficient, the deduction creates a capital income deficit, which gives a credit against earned income tax (30% of deficit, max 1,400 EUR per person, increased by 400 EUR for first qualifying home mortgage)

### 4.3 Withdrawal Rules

- Withdrawals allowed only after reaching the pension age set in the contract
- Withdrawals taxed as capital income at 30%/34% rates
- Can be taken as lump sum or periodic payments
- **Early withdrawal penalty**: the withdrawn amount is taxed as capital income and an additional 20 percentage point surcharge is applied (effectively 50%/54% tax rate)

### 4.4 Implementation

The system must track:
- Annual contributions and their tax deduction impact
- Contract value (for projection purposes)
- Expected pension age and earliest withdrawal date
- Model early withdrawal penalty in tax projections

## 5. Kapitalisaatiosopimus (Capitalization Agreement)

### 5.1 Core Rules

| Rule | Detail |
|------|--------|
| Deposit limit | None — unlimited deposits |
| Tax on internal trades | None — fully tax-deferred |
| Tax trigger | Withdrawal (partial or full) |
| Allowed instruments | Broad — stocks, bonds, funds, structured products (varies by provider) |
| Number of accounts | No limit |

### 5.2 Withdrawal Taxation

Identical formula to osakesaastotili:

```
gains_ratio = (contract_value - total_deposits) / contract_value
taxable_amount = withdrawal_amount * gains_ratio
```

- Only the gains portion of each withdrawal is taxed as capital income
- If `contract_value <= total_deposits`, no taxable gain on withdrawal
- On contract termination, losses are deductible against capital income

### 5.3 Key Differences from Osakesaastotili

| Feature | Osakesaastotili | Kapitalisaatiosopimus |
|---------|----------------|----------------------|
| Deposit limit | 50,000 EUR lifetime | None |
| Accounts per person | 1 | Unlimited |
| Instruments | Listed stocks, UCITS funds | Broader (depends on provider) |
| Provider | Banks, brokers | Insurance companies |
| Withdrawal limit restore | No | No |
| Loss on closure | Deductible | Deductible |

### 5.4 Implementation

Same tracking as OST: `total_deposits_cents`, `total_withdrawals_cents`, `remaining_deposit_base_cents`, and the gains ratio calculation per withdrawal.

## 6. Loss Deduction Rules

### 6.1 General Rules

| Rule | Detail |
|------|--------|
| Same-year offset | Capital losses are deducted against capital gains in the same tax year |
| Carry-forward | Excess losses carried forward for **5 years** |
| Carry-forward priority | Oldest losses used first (FIFO) |
| Carry-forward automatic | Losses are applied automatically by Vero — no election needed |
| No carry-back | Losses cannot be applied to prior tax years |

### 6.2 Loss Categories (since 2016 Reform)

Since the 2016 tax reform, loss deduction has been simplified:

- **Losses from listed securities** (stocks, ETFs, bonds traded on regulated markets): deductible against **all capital income** (gains, dividends, rental income, etc.)
- **Losses from other assets** (unlisted shares, real estate, collectibles): deductible only against **gains from similar assets**
- **Crypto losses**: deductible against **capital gains** (all types of capital gains, per Vero guidance)

### 6.3 Interaction with Tax-Advantaged Accounts

- Losses inside an osakesaastotili or kapitalisaatiosopimus are **not deductible** while the account is open
- Losses are only realized for tax purposes when the account is **closed** and the final value is below the deposit base
- This is a critical consideration for the Tax Strategist: a losing position in a regular account can generate a tax-deductible loss, but the same losing position in an OST cannot (until closure)

### 6.4 Loss Carry-Forward Tracking

The system must track per tax year:
- `realized_gains_cents` — total realized gains
- `realized_losses_cents` — total realized losses
- `net_capital_gain_or_loss_cents` — net position
- `loss_carryforward_by_year` — array of (year, remaining_loss) for each of the prior 5 years
- On each new tax year, apply carry-forward losses (oldest first) against gains before calculating tax

### 6.5 Implementation Formula

```
# For tax year T:
available_losses = losses_year_T + sum(carryforward from years T-5 to T-1, oldest first)
net_taxable = max(0, gains_year_T + other_capital_income - available_losses)
unused_losses = available_losses - (gains_year_T + other_capital_income - net_taxable)
# unused_losses carries forward (up to 5 years from original year)
# losses older than 5 years expire
```

## 7. Dividend Taxation

### 7.1 Listed Finnish Companies

Dividends from companies listed on a **regulated market** (e.g., Nasdaq Helsinki):

| Component | Rate |
|-----------|------|
| Taxable portion | 85% of dividend |
| Tax-free portion | 15% of dividend |
| Tax on taxable portion | 30% / 34% (capital income rates) |
| Effective tax rate | 25.5% (at 30% band) or 28.9% (at 34% band) |

Example: 1,000 EUR dividend from Nordea (listed)
- Taxable: 850 EUR
- Tax-free: 150 EUR
- Tax (at 30% band): 850 * 30% = 255 EUR
- Effective rate: 25.5%

### 7.2 Unlisted Finnish Companies (Summary)

Dividends from unlisted companies follow more complex rules based on the company's net asset value and the dividend amount relative to the mathematical value of shares. The system should support the following simplified model:

- Dividends up to 8% of the mathematical value of shares:
  - 25% taxable as capital income, 75% tax-free (up to 150,000 EUR)
  - Above 150,000 EUR: 85% taxable as capital income, 15% tax-free
- Dividends exceeding 8% of mathematical value:
  - 75% taxable as earned income, 25% tax-free

**Implementation**: For the MVP, unlisted dividend rules can be a simplified model with a note that manual verification is needed. The investor profile focuses on listed securities.

### 7.3 Foreign Dividends

| Rule | Detail |
|------|--------|
| Default treatment | 100% taxable as capital income in Finland |
| No 85/15 split | The 85% taxable / 15% tax-free rule applies **only** to Finnish listed companies |
| Withholding tax at source | Many countries withhold tax before payment |
| Tax treaty relief | Finland has treaties with ~80 countries reducing withholding rates |
| Credit method | Foreign withholding tax is credited against Finnish tax (avoids double taxation) |

### 7.4 Common Tax Treaty Withholding Rates

| Country | Treaty Rate | Notes |
|---------|-------------|-------|
| United States | 15% | W-8BEN form required; without it, 30% withheld |
| United Kingdom | 0% | No withholding on UK dividends |
| Germany | 0-15% | 15% on most dividends; some exemptions |
| Sweden | 0-15% | 15% standard; 0% for substantial holdings |
| France | 0-15% | Often 15%; historically complex reclaim process |
| Ireland | 0-15% | Many ETFs domiciled here; 15% typical |
| Netherlands | 15% | Standard treaty rate |
| Switzerland | 0-15% | Complex; often 15% effective |
| Canada | 15% | Standard treaty rate |
| Japan | 15% | Standard treaty rate |
| Norway | 15% | Standard treaty rate |
| Denmark | 15% | Standard treaty rate; reclaim process for excess |

### 7.5 Foreign Tax Credit Mechanism

```
finnish_tax_on_dividend = taxable_dividend * finnish_rate  # 30% or 34%
credit = min(foreign_withholding_paid, finnish_tax_on_dividend)
net_finnish_tax = finnish_tax_on_dividend - credit
```

Rules:
- Credit is limited to the **Finnish tax** that would be payable on the same income — you cannot get a refund via credit
- Credit is limited to the **treaty rate** — if the source country withholds more than the treaty rate, the excess must be reclaimed from the source country directly
- Example: US stock, $1,000 dividend, 30% withheld (no W-8BEN filed)
  - Treaty rate: 15%, so credit = 15% of dividend = $150
  - The other $150 over-withheld must be reclaimed from the IRS
  - Finnish tax: $1,000 * 30% = $300, minus $150 credit = $150

### 7.6 Dividend Tracking Requirements

For each dividend payment, the system must store:
- `gross_amount_cents` — dividend before any withholding
- `withholding_tax_cents` — tax withheld at source
- `withholding_tax_rate` — percentage withheld
- `treaty_rate` — applicable treaty rate for the source country
- `creditable_amount_cents = min(withholding_tax_cents, gross_amount_cents * treaty_rate)`
- `reclaimable_amount_cents = withholding_tax_cents - creditable_amount_cents`
- `taxable_portion` — 0.85 for Finnish listed, 1.0 for foreign, or as computed for unlisted
- `account_type` — if in OST, no tax event is generated

## 8. Crypto Taxation

### 8.1 Taxable Events

In Finland, cryptocurrency is treated as "other property" and every disposal is a taxable event:

| Event | Taxable? | Notes |
|-------|----------|-------|
| Buy crypto with fiat (EUR) | No | Establishes cost basis |
| Sell crypto for fiat (EUR) | **Yes** | Capital gain/loss realized |
| Swap crypto for crypto (BTC → ETH) | **Yes** | Treated as sale of BTC + purchase of ETH |
| Pay for goods/services with crypto | **Yes** | Treated as sale at market value |
| Receive mining rewards | **Yes** | Earned income when received; new cost basis at market value |
| Receive staking rewards | **Yes** | Capital income when received; new cost basis at market value |
| Receive airdrop | **Yes** | Capital income when received (if value > 0); new cost basis at market value |
| Transfer between own wallets | No | No change in ownership |
| DeFi lending (deposit) | Possibly | Vero guidance unclear; treat as disposal if tokens are exchanged |
| DeFi yield farming rewards | **Yes** | Capital income when received |
| NFT sale | **Yes** | Capital gain/loss on disposal |

### 8.2 Cost Basis and Matching

- **FIFO** (First-In, First-Out) is the default matching method per Finnish Tax Administration guidance
- FIFO is applied **per cryptocurrency** (e.g., all BTC purchases form one FIFO queue, all ETH another)
- Cost basis includes:
  - Purchase price in EUR
  - Transaction fees (exchange fees, gas fees) — added to cost basis
  - For crypto-to-crypto swaps: the EUR market value of the disposed crypto at the time of swap becomes the cost basis of the acquired crypto

### 8.3 Deemed Cost for Crypto

The deemed cost of acquisition (Section 2) applies to crypto as well:
- Held < 10 years: 20% of sale price
- Held >= 10 years: 40% of sale price
- Same rules: cannot generate a loss, no fee deductions when used

### 8.4 Mining Income

Mining income has a **two-step tax treatment**:

1. **When mined**: taxed as **earned income** (progressive income tax, not capital income) at the EUR market value on the date received
2. **When later sold/swapped**: taxed as **capital income** — gain/loss calculated from the cost basis established in step 1

The system must:
- Record the EUR market value at the time of mining as both earned income and cost basis
- Track the mining date as the acquisition date for holding period calculations

### 8.5 Staking Rewards

- Taxed as **capital income** when received (not earned income — different from mining)
- EUR market value at receipt date = taxable amount and new cost basis
- On later disposal, gain/loss calculated from this cost basis

### 8.6 DeFi Considerations

DeFi transactions are complex and Vero guidance is evolving. The system should:
- Flag DeFi transactions for manual review
- When tokens are exchanged for LP tokens: treat as disposal
- When LP tokens are redeemed: treat as disposal of LP tokens
- Yield farming rewards: treat as capital income when received
- Lending interest: treat as capital income when received

## 9. No Wash Sale Rule (Substance-over-Form)

### 9.1 The Rule (or Lack Thereof)

Finland has **no explicit wash sale rule**. Unlike the US (30-day rule) or UK (30-day bed-and-breakfasting rule), there is no statutory provision that disallows a loss when you repurchase the same security shortly after selling it.

### 9.2 Substance-over-Form Doctrine

However, the Finnish Tax Administration (*Verohallinto*) can challenge transactions that lack **economic substance** under the general anti-avoidance rule (*veron kiertaminen*, Tax Procedure Act Section 28):

- Selling and immediately repurchasing the **identical security** solely to realize a tax loss may be recharacterized
- The Tax Administration looks at: timing, intent, economic substance, whether the position materially changed
- This is applied on a case-by-case basis — there is no bright-line rule

### 9.3 Practical Guidance for the System

The system should:
- **Allow** loss harvesting transactions (no automatic blocking)
- **Flag** transactions where the same security is sold and repurchased within a short period (e.g., < 7 days) with a warning
- **Suggest** alternatives: buy a similar but not identical security (e.g., sell one S&P 500 ETF, buy a different S&P 500 ETF from another provider)
- **Log** the warning for tax audit documentation

### 9.4 Tax Loss Harvesting Strategy

Given the lack of a formal wash sale rule, tax loss harvesting is a powerful strategy in Finland:

1. Sell losing positions to realize capital losses
2. Losses offset gains in the same year (or carry forward 5 years)
3. Repurchase a similar (but not identical) security to maintain market exposure
4. Wait a reasonable period before repurchasing the identical security (conservative: 30 days)

The Tax Strategist agent should identify loss harvesting candidates annually, especially in December before year-end.

## 10. Taxable Events Summary

| Event | Taxable? | Tax Type | Regular Account | Osakesaastotili | Kapitalisaatiosopimus | PS-sopimus |
|-------|----------|----------|-----------------|-----------------|----------------------|------------|
| Buy security | No | — | — | — | — | — |
| Sell security at gain | Yes | Capital income | Taxed immediately | Not taxed | Not taxed | Not taxed |
| Sell security at loss | Yes (loss) | Capital loss | Deductible | Not deductible* | Not deductible* | Not deductible* |
| Receive dividend | Yes | Capital income | Taxed (85/15 or 100%) | Not taxed | Not taxed | Not taxed |
| Crypto swap | Yes | Capital income | Taxed immediately | N/A (not allowed) | Depends on provider | N/A |
| Withdrawal from account | N/A | — | N/A | Gains portion taxed | Gains portion taxed | Taxed as capital income |
| Account closure at loss | N/A | — | N/A | Loss deductible | Loss deductible | Complex (see 4.3) |
| Deposit into account | No | — | — | — | — | Deductible (up to 5k) |

\* Losses inside tax-advantaged accounts are not deductible until the account is closed.

## 11. Worked Examples

All examples use EUR. Monetary values shown in euros for readability; the system stores cents internally.

### Example 1: Simple Stock Sale — Actual Cost Basis

**Scenario**: Buy 100 shares of Nokia at 4.50 EUR. Sell all at 5.00 EUR after 2 years. No other capital income this year.

```
Purchase cost:    100 * 4.50 = 450.00 EUR
Purchase fees:                   10.00 EUR
Total cost basis:               460.00 EUR

Sale proceeds:    100 * 5.00 = 500.00 EUR
Selling fees:                    10.00 EUR
Net proceeds:                   490.00 EUR

Actual gain:      490.00 - 460.00 = 30.00 EUR

Deemed cost (20%): 500.00 * 20% = 100.00 EUR
Deemed gain:       500.00 - 100.00 = 400.00 EUR

Actual gain (30.00) < Deemed gain (400.00) → use actual cost basis

Taxable gain: 30.00 EUR
Tax (30% band): 30.00 * 30% = 9.00 EUR
```

### Example 2: Stock Sale — Deemed Cost (20%) More Favorable

**Scenario**: Buy 100 shares of Kone at 20.00 EUR. Sell all at 70.00 EUR after 5 years.

```
Purchase cost:    100 * 20.00 = 2,000.00 EUR
Purchase fees:                     15.00 EUR
Total cost basis:               2,015.00 EUR

Sale proceeds:    100 * 70.00 = 7,000.00 EUR
Selling fees:                      15.00 EUR
Net proceeds:                   6,985.00 EUR

Actual gain:      6,985.00 - 2,015.00 = 4,970.00 EUR

Deemed cost (20%): 7,000.00 * 20% = 1,400.00 EUR
Deemed gain:       7,000.00 - 1,400.00 = 5,600.00 EUR

Actual gain (4,970.00) < Deemed gain (5,600.00) → use actual cost basis

NOTE: In this case actual cost is still better. Deemed cost 20% is favorable
only when actual cost < 20% of sale price, i.e., stock has 5x'd or more.
```

### Example 3: Stock Held >10 Years — Deemed Cost (40%) More Favorable

**Scenario**: Buy 200 shares of Sampo at 8.00 EUR in 2014. Sell all at 45.00 EUR in 2026 (12 years held).

```
Purchase cost:    200 * 8.00  = 1,600.00 EUR
Purchase fees:                     12.00 EUR
Total cost basis:               1,612.00 EUR

Sale proceeds:    200 * 45.00 = 9,000.00 EUR
Selling fees:                      15.00 EUR
Net proceeds:                   8,985.00 EUR

Actual gain:      8,985.00 - 1,612.00 = 7,373.00 EUR

Deemed cost (40%): 9,000.00 * 40% = 3,600.00 EUR
Deemed gain:       9,000.00 - 3,600.00 = 5,400.00 EUR

Actual gain (7,373.00) > Deemed gain (5,400.00) → use deemed cost (40%)

Taxable gain: 5,400.00 EUR
Tax (30% band): 5,400.00 * 30% = 1,620.00 EUR

Tax saved by using deemed cost: (7,373.00 - 5,400.00) * 30% = 591.90 EUR
```

### Example 4: Loss Harvesting Within the Year

**Scenario**: In 2026, the investor has:
- Realized gain from selling ETF: +8,000 EUR
- Unrealized loss on Tech Stock X: -3,000 EUR

Strategy: sell Tech Stock X before Dec 31 to realize the loss.

```
Without loss harvesting:
  Taxable gain: 8,000.00 EUR
  Tax: 8,000.00 * 30% = 2,400.00 EUR

With loss harvesting (sell Tech Stock X):
  Gain: +8,000.00 EUR
  Loss: -3,000.00 EUR
  Net taxable: 5,000.00 EUR
  Tax: 5,000.00 * 30% = 1,500.00 EUR

Tax saved: 900.00 EUR
```

The investor can then buy a similar (but not identical) tech stock to maintain exposure.

### Example 5: Losses Carried Forward

**Scenario**:
- 2025: Net capital loss of -5,000 EUR (no gains to offset)
- 2026: Net capital gain of +3,000 EUR
- 2027: Net capital gain of +4,000 EUR

```
2025: Loss of 5,000 EUR → carried forward (expires end of 2030)
2026: Gain of 3,000 EUR - 3,000 carryforward = 0 taxable. Tax = 0.
      Remaining carryforward: 2,000 EUR
2027: Gain of 4,000 EUR - 2,000 carryforward = 2,000 taxable.
      Tax: 2,000 * 30% = 600 EUR
      Remaining carryforward: 0 EUR
```

### Example 6: Osakesaastotili Partial Withdrawal

**Scenario**: OST account status:
- Total deposits: 50,000 EUR (lifetime limit reached)
- Current account value: 72,000 EUR
- Withdrawal: 10,000 EUR

```
Gains ratio: (72,000 - 50,000) / 72,000 = 22,000 / 72,000 = 0.30556

Taxable amount: 10,000 * 0.30556 = 3,055.60 EUR
Tax-free amount (return of deposit): 10,000 - 3,055.60 = 6,944.40 EUR

Tax (30% band): 3,055.60 * 30% = 916.68 EUR

After withdrawal:
  Account value: 62,000 EUR
  Remaining deposit base: 50,000 - 6,944.40 = 43,055.60 EUR
```

### Example 7: Osakesaastotili Full Closure with Gains

**Scenario**: Closing OST:
- Total deposits over lifetime: 50,000 EUR
- Previous withdrawals: 10,000 EUR (of which 6,944.40 was deposit return — from Example 6)
- Remaining deposit base: 43,055.60 EUR
- Final account value at closure: 65,000 EUR

```
Taxable gain: 65,000.00 - 43,055.60 = 21,944.40 EUR
Tax (30% band): 21,944.40 * 30% = 6,583.32 EUR
```

### Example 8: Osakesaastotili Closure with Losses

**Scenario**: Closing OST after market crash:
- Remaining deposit base: 43,055.60 EUR
- Final account value at closure: 30,000 EUR

```
Loss: 30,000.00 - 43,055.60 = -13,055.60 EUR

This loss IS deductible against capital income (only upon account closure).

If investor has 20,000 EUR in other capital gains this year:
  Net taxable: 20,000.00 - 13,055.60 = 6,944.40 EUR
  Tax: 6,944.40 * 30% = 2,083.32 EUR
  Tax saved by loss: 13,055.60 * 30% = 3,916.68 EUR

If no other gains: loss carries forward for 5 years.
```

### Example 9: Foreign Dividend with Withholding Tax Credit (US Stock)

**Scenario**: Investor holds Apple (AAPL) in a regular account. Receives $1,000 gross dividend. W-8BEN filed (15% treaty rate). EUR/USD = 0.92.

```
Gross dividend:           $1,000 = 920.00 EUR
US withholding (15%):     $150   = 138.00 EUR
Net received:             $850   = 782.00 EUR

Finnish tax treatment:
  Foreign dividend → 100% taxable as capital income
  Taxable amount: 920.00 EUR
  Finnish tax (30% band): 920.00 * 30% = 276.00 EUR
  Foreign tax credit: 138.00 EUR (= treaty rate withheld)
  Net Finnish tax due: 276.00 - 138.00 = 138.00 EUR

Total tax paid: 138.00 (US) + 138.00 (FI) = 276.00 EUR
Effective rate: 276.00 / 920.00 = 30.0%
```

If W-8BEN had NOT been filed (30% US withholding):
```
US withholding (30%):     $300 = 276.00 EUR
Credit allowed (treaty max 15%): 138.00 EUR
Reclaimable from IRS:     276.00 - 138.00 = 138.00 EUR
Net Finnish tax due:      276.00 - 138.00 = 138.00 EUR
Total tax until reclaim:  276.00 (US) + 138.00 (FI) = 414.00 EUR
After reclaim:            138.00 (US) + 138.00 (FI) = 276.00 EUR
```

### Example 10: Crypto Swap (BTC to ETH)

**Scenario**: Investor bought 0.5 BTC at 25,000 EUR/BTC. Later swaps 0.5 BTC for 8 ETH when BTC = 50,000 EUR/BTC and ETH = 3,125 EUR/ETH.

```
Disposal of BTC:
  Cost basis: 0.5 * 25,000 = 12,500.00 EUR
  Sale value (market): 0.5 * 50,000 = 25,000.00 EUR
  Gain: 25,000.00 - 12,500.00 = 12,500.00 EUR

  Deemed cost check (20%, held < 10 years):
    Deemed gain: 25,000 * 80% = 20,000.00 EUR
    Actual gain (12,500) < Deemed gain (20,000) → use actual cost basis

  Taxable gain: 12,500.00 EUR
  Tax (30% band): 12,500.00 * 30% = 3,750.00 EUR

Acquisition of ETH:
  Cost basis: 8 * 3,125 = 25,000.00 EUR
  Acquisition date: date of swap (for future holding period calculation)

Note: The swap is ONE taxable event (disposal of BTC) creating a new cost
basis for ETH. No tax on the ETH side until it is disposed of.
```

### Example 11: Mixed Year — Gains + Losses + Dividends

**Scenario**: Full tax year summary for the investor:

```
Regular account activity:
  Stock sale gain (Kone):              +12,000.00 EUR
  Stock sale loss (Tech Corp):          -4,000.00 EUR
  Crypto gain (BTC sold):              +8,000.00 EUR
  ETF sale gain:                        +3,500.00 EUR

Dividends (regular account):
  Finnish listed dividends (gross):     2,000.00 EUR
    Taxable (85%):                      1,700.00 EUR
  US dividends (gross):                 1,500.00 EUR
    Taxable (100%):                     1,500.00 EUR
    US withholding (15%):                 225.00 EUR

OST withdrawal (gains portion):        2,500.00 EUR

Loss carryforward from 2025:          -1,500.00 EUR

CALCULATION:
  Capital gains:    12,000 + 8,000 + 3,500          = 23,500.00 EUR
  Capital losses:   -4,000                            = -4,000.00 EUR
  Net gains:                                          = 19,500.00 EUR
  Dividend income:  1,700 + 1,500                     =  3,200.00 EUR
  OST withdrawal gain:                                =  2,500.00 EUR
  Loss carryforward:                                  = -1,500.00 EUR

  Total capital income: 19,500 + 3,200 + 2,500 - 1,500 = 23,700.00 EUR

  Tax (all within 30,000 band):
    23,700 * 30%                                      =  7,110.00 EUR
  Foreign tax credit (US dividends):                  =   -225.00 EUR
  Net tax payable:                                    =  6,885.00 EUR

  Effective rate: 6,885 / (23,700 + 225) = 28.8%
```

### Example 12: Deemed Cost vs Actual Cost Comparison

**Scenario**: Investor sells shares bought at different times. Same stock (Neste), 100 shares sold at 50.00 EUR/share.

```
LOT A: 50 shares bought at 45.00 EUR, held 3 years
  Actual cost: 50 * 45 = 2,250 + 8 fee = 2,258 EUR
  Actual gain: (50 * 50 - 8 fee) - 2,258 = 2,492 - 2,258 = 234 EUR
  Deemed (20%): 2,500 * 80% = 2,000 EUR (deemed gain)
  → Actual cost better (234 < 2,000). Use actual.

LOT B: 50 shares bought at 10.00 EUR, held 12 years
  Actual cost: 50 * 10 = 500 + 8 fee = 508 EUR
  Actual gain: (50 * 50 - 8 fee) - 508 = 2,492 - 508 = 1,984 EUR
  Deemed (40%): 2,500 * 60% = 1,500 EUR (deemed gain)
  → Deemed cost better (1,500 < 1,984). Use deemed.

TOTAL for the sale:
  Lot A taxable gain:    234.00 EUR (actual cost)
  Lot B taxable gain:  1,500.00 EUR (deemed cost)
  Total taxable:       1,734.00 EUR
  Tax (30% band):        520.20 EUR

If actual cost used for both:
  Total taxable: 234 + 1,984 = 2,218.00 EUR
  Tax: 665.40 EUR

Tax saved by using deemed cost on Lot B: 145.20 EUR
```

## Edge Cases

1. **Partial share sales**: Deemed cost calculation applies to the proceeds of the actual quantity sold, even if fractional shares are involved.
2. **Corporate actions (splits, mergers)**: Cost basis and acquisition date must be adjusted. A 2:1 split halves the per-share cost basis but preserves the original acquisition date (holding period continues).
3. **Spin-offs**: Cost basis of the original holding is allocated between the parent and spin-off based on market values on the first trading day. Acquisition date is preserved for both.
4. **Currency conversion**: For foreign securities, both the purchase FX rate and sale FX rate affect the gain. A stock that is flat in USD can generate a gain or loss in EUR due to FX movement. This FX component is part of the capital gain.
5. **Dividends reinvested via DRIP**: Each reinvested dividend creates a new tax lot with its own cost basis and acquisition date (for deemed cost holding period). In a regular account, the dividend is still a taxable event even if reinvested.
6. **Osakesaastotili broker transfer**: In-kind transfers between brokers do not reset the deposit base or trigger tax. The system must handle the accounting continuity.
7. **Osakesaastotili with only losses**: If the OST account value drops below total deposits, withdrawals are tax-free (return of capital only), but no loss is recognized until full closure.
8. **Deemed cost on crypto**: Applies identically; holding period starts from the acquisition of each FIFO lot. For crypto-to-crypto swaps, the holding period of the new token starts from the swap date, not from the original BTC purchase.
9. **Year boundary**: A trade executed on Dec 31 (trade date) but settled on Jan 2 (T+2) — Finnish tax uses the **trade date**, not the settlement date.
10. **Death / inheritance**: Inherited securities receive a stepped-up cost basis (market value at date of death). This resets the holding period for deemed cost calculation. The system should support manual override of cost basis for inherited lots.
11. **Gifts**: Gifted securities retain the donor's cost basis and acquisition date. If a gift tax was paid, it is added to the cost basis.
12. **Negative capital income**: If total capital losses exceed all capital income, the deficit creates a *paaomatulolajin alijaamahyvitys* (capital income deficit credit) applied against earned income tax at 30%, capped at 1,400 EUR per person (or 1,800 EUR for first home mortgage owners).
13. **PS-sopimus early withdrawal**: If withdrawn before pension age, the 20% surcharge applies on top of normal capital income tax rate. The system must check withdrawal eligibility before calculating tax.
14. **Multiple osakesaastotili violation**: If the system detects data for more than one OST account, it must raise an error — only one is legally allowed.

## Open Questions

1. **DeFi tax treatment evolution**: Vero.fi guidance on DeFi is still developing. How should the system handle retroactive rule changes?
2. **Crypto cost basis across exchanges**: Should the system maintain separate FIFO queues per exchange/wallet, or one global FIFO queue per cryptocurrency? Current Vero guidance suggests one global queue per crypto asset.
3. **PS-sopimus pension age**: The exact pension age for the investor needs to be confirmed based on birth year and contract terms.
4. **Unlisted company dividends**: How much detail does the system need? The investor profile focuses on listed securities.

## References

- [Vero.fi — Capital gains on the sale of shares](https://www.vero.fi/en/individuals/property/investments/selling-shares/)
- [Vero.fi — Deemed cost of acquisition (hankintameno-olettama)](https://www.vero.fi/en/individuals/property/investments/selling-shares/deemed-acquisition-cost/)
- [Vero.fi — Equity savings account (osakesaastotili)](https://www.vero.fi/en/individuals/property/investments/equity-savings-account/)
- [Vero.fi — Taxation of dividends](https://www.vero.fi/en/individuals/property/investments/dividend-income/)
- [Vero.fi — Taxation of virtual currencies](https://www.vero.fi/en/individuals/property/investments/virtual-currencies/)
- [Vero.fi — Capital income and capital income tax](https://www.vero.fi/en/individuals/tax-cards-and-tax-returns/income/capital-income/)
- [Vero.fi — Tax on capital income deficit](https://www.vero.fi/en/individuals/tax-cards-and-tax-returns/income/capital-income/deficit-of-capital-income/)
- [Vero.fi — Voluntary pension insurance (PS-sopimus)](https://www.vero.fi/en/individuals/tax-cards-and-tax-returns/income/deductions/voluntary-pension-insurance/)
- [Vero.fi — Tax treaties](https://www.vero.fi/en/About-us/tax-treaties/)
- [Vero.fi — General anti-avoidance rule](https://www.vero.fi/en/About-us/tax-administration/tax-audits/)

## Changelog

| Date | Change |
|------|--------|
| 2026-03-19 | Initial draft — DRAFT status |
