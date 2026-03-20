# Tax Lot Tracking

This spec defines the complete lifecycle of tax lots: creation on purchase, matching on disposal, partial and full closes, realized gain calculation (including Finnish deemed cost comparison), corporate action adjustments, and account-type-specific rules for osakesaastotili and crypto. Every disposal in the system flows through this spec's logic to determine which lots are consumed, what cost basis is used, and what gain or loss is realized. Errors here directly produce wrong tax reports and wrong rebalancing suggestions.

**Status: DRAFT**

## Dependencies

- [Spec Conventions](../00-meta/spec-conventions.md) — monetary values in cents, date handling, naming rules
- [Data Model](../01-system/data-model.md) — `tax_lots`, `transactions`, `accounts`, `corporate_actions` table definitions
- [Finnish Tax Rules](../03-calculations/tax-finnish.md) — deemed cost of acquisition, capital income rates, loss deduction, crypto taxation

---

## 1. Lot Creation

Every `buy` transaction creates exactly one new row in the `tax_lots` table.

### 1.1 Fields Set on Creation

| Field | Value |
|-------|-------|
| `account_id` | From the transaction |
| `security_id` | From the transaction |
| `open_transaction_id` | The buy transaction's `id` |
| `state` | `'open'` |
| `acquired_date` | `transaction.trade_date` |
| `original_quantity` | `transaction.quantity` (always positive for buys) |
| `remaining_quantity` | Same as `original_quantity` |
| `cost_basis_cents` | See calculation below |
| `cost_basis_currency` | `transaction.currency` (the account's base currency) |
| `fx_rate_at_open` | `transaction.fx_rate` (NULL if same currency) |

### 1.2 Cost Basis Calculation

```
cost_basis_cents = transaction.total_cents + transaction.fee_cents
```

Where `transaction.total_cents = price_cents * quantity * fx_rate` (already computed by the transaction layer in account currency cents) and `fee_cents` is the brokerage/exchange fee converted to account currency.

**Multi-currency handling**: The transaction layer converts everything to the account's base currency at the trade-date FX rate before storing `total_cents`. The tax lot inherits this converted value. The original `fx_rate_at_open` is preserved for audit and for EUR reporting if the account currency is not EUR.

### 1.3 EUR Reporting Basis

For tax reporting to Vero, all gains must be expressed in EUR. If the account currency is not EUR (e.g., a USD brokerage account), the system must also compute and store (or be able to derive) the EUR-equivalent cost basis using the ECB reference rate on the trade date:

```
cost_basis_eur_cents = cost_basis_cents * eur_fx_rate_on_trade_date
```

This is handled at the reporting layer, not stored redundantly on the lot itself — the `fx_rates` table provides the historical rate.

---

## 2. Lot Matching Methods

When a `sell` transaction is processed, the system must determine which open lots to consume. The matching method determines the order.

### 2.1 Available Methods

| Method | Code | Description | Default For |
|--------|------|-------------|-------------|
| **FIFO** | `fifo` | First In, First Out — oldest lots consumed first | Crypto (mandatory per Vero.fi) |
| **LIFO** | `lifo` | Last In, First Out — newest lots consumed first | — |
| **Specific Identification** | `specific_id` | User explicitly selects which lot(s) to close | Stocks, ETFs, bonds |
| **Highest Cost First** | `highest_cost` | Lots with highest per-unit cost basis consumed first | — (tax optimization) |

### 2.2 Method Resolution

The matching method is resolved in this priority order:

1. **Per-disposal override**: If the sell transaction specifies `lot_ids` (specific identification), use those exact lots regardless of account default.
2. **Account-level default**: Each account has a configured default method. For `crypto_wallet` accounts, this is always `fifo` and cannot be changed.
3. **System default**: `specific_id` for stocks/ETFs/bonds; `fifo` for crypto.

### 2.3 FIFO Implementation

```python
def match_fifo(account_id, security_id, sell_quantity):
    lots = (
        TaxLot.query
        .filter_by(account_id=account_id, security_id=security_id)
        .filter(TaxLot.state.in_(['open', 'partially_closed']))
        .filter(TaxLot.remaining_quantity > 0)
        .order_by(TaxLot.acquired_date.asc(), TaxLot.id.asc())
        .all()
    )
    return consume_lots(lots, sell_quantity)
```

Ties in `acquired_date` are broken by `id` (insertion order).

### 2.4 LIFO Implementation

Same as FIFO but ordered by `acquired_date DESC, id DESC`.

### 2.5 Highest Cost First Implementation

Ordered by per-unit cost basis descending:

```python
.order_by((TaxLot.cost_basis_cents / TaxLot.original_quantity).desc(), TaxLot.id.asc())
```

### 2.6 Specific Identification

The sell request includes an ordered list of `(lot_id, quantity)` pairs. The system validates:

- Each `lot_id` belongs to the correct `account_id` and `security_id`
- Each `lot_id` is in state `open` or `partially_closed`
- The requested quantity does not exceed `remaining_quantity` for that lot
- The sum of all quantities equals `sell_quantity`

If validation fails, the transaction is rejected.

---

## 3. Partial Close

When a sell consumes less than a lot's full `remaining_quantity`, the lot is partially closed.

### 3.1 Mechanics

Given a lot with `remaining_quantity = R` and `cost_basis_cents = C`, selling quantity `S` where `S < R`:

1. **Create a new closed lot row** representing the sold portion:
   - `original_quantity = S`
   - `remaining_quantity = 0`
   - `cost_basis_cents = C * (S / R)` (proportional allocation, using `Decimal` arithmetic)
   - `state = 'closed'`
   - `close_transaction_id = sell_transaction.id`
   - `closed_date = sell_transaction.trade_date`
   - `acquired_date` = same as original lot (holding period preserved)
   - `open_transaction_id` = same as original lot
   - `proceeds_cents` and `realized_pnl_cents` computed per Section 5

2. **Update the original lot**:
   - `remaining_quantity = R - S`
   - `cost_basis_cents = C - closed_portion_cost_basis` (remainder)
   - `state = 'partially_closed'`

### 3.2 Cost Basis Allocation Precision

Cost basis allocation uses `Decimal` division to avoid rounding drift:

```python
from decimal import Decimal, ROUND_HALF_UP

closed_cost = (Decimal(lot.cost_basis_cents) * Decimal(sell_qty) / Decimal(lot.remaining_quantity)).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
remaining_cost = lot.cost_basis_cents - int(closed_cost)
```

This ensures the closed and remaining portions always sum to the original cost basis exactly.

---

## 4. Full Close

When a sell consumes a lot's entire `remaining_quantity`:

1. Update the existing lot row (no new row needed):
   - `remaining_quantity = 0`
   - `state = 'closed'`
   - `close_transaction_id = sell_transaction.id`
   - `closed_date = sell_transaction.trade_date`
   - `proceeds_cents` and `realized_pnl_cents` computed per Section 5
   - `fx_rate_at_close = sell_transaction.fx_rate`

---

## 5. Realized Gain Calculation

### 5.1 Actual Gain

For each lot (or lot portion) being closed:

```
proceeds_cents = (sell_price_cents * quantity_sold * fx_rate_at_sell) - allocated_selling_fees
realized_gain_actual = proceeds_cents - cost_basis_cents
```

Where:
- `sell_price_cents * quantity_sold * fx_rate_at_sell` is the gross proceeds in account currency
- `allocated_selling_fees` = total sell fee allocated proportionally if the sell closes multiple lots: `total_fee * (quantity_from_this_lot / total_sell_quantity)`
- `cost_basis_cents` = the lot's cost basis (already includes purchase fees)

### 5.2 Deemed Cost Comparison (Hankintameno-olettama)

For every disposal in a **regular account** (not osakesaastotili, not kapitalisaatiosopimus, not pension), the system must compute and compare:

```python
gross_proceeds = sell_price_cents * quantity_sold * fx_rate_at_sell  # before selling fees

holding_years = (sell_date - lot.acquired_date).days / 365.25

if holding_years < 10:
    deemed_cost = gross_proceeds * 20 // 100
else:
    deemed_cost = gross_proceeds * 40 // 100

deemed_gain = gross_proceeds - deemed_cost  # no fee deductions when using deemed cost

actual_gain = proceeds_cents - cost_basis_cents  # proceeds already net of selling fees

if actual_gain <= 0:
    # Loss — must use actual cost (deemed cost cannot create a loss)
    taxable_gain = actual_gain
    method_used = 'actual'
elif deemed_gain < actual_gain:
    taxable_gain = deemed_gain
    method_used = 'deemed'
else:
    taxable_gain = actual_gain
    method_used = 'actual'
```

### 5.3 Storage

On the closed lot row, store:

| Field | Value |
|-------|-------|
| `proceeds_cents` | Net proceeds (gross - allocated selling fees) |
| `realized_pnl_cents` | The `taxable_gain` value (whichever method is more favorable) |

Additionally, the system must store or be able to reconstruct for audit:
- `actual_gain_cents` — gain using actual cost basis
- `deemed_gain_cents` — gain using deemed cost
- `deemed_cost_method` — `'actual'`, `'deemed_20'`, or `'deemed_40'`

These fields may be stored on the lot, in a separate `tax_lot_disposals` detail table, or computed on-the-fly from the lot's dates and amounts. The implementation must ensure they are available for the tax report.

---

## 6. Corporate Action Adjustments

All corporate action processing follows the rules defined in the [data model corporate action section](../01-system/data-model.md#corporate-action-processing-rules). This section specifies the tax lot impact.

### 6.1 Stock Split

For a split with `ratio_from:ratio_to` (e.g., 1:2 for a 2-for-1 split):

```
For each open or partially_closed lot of the affected security:
    new_original_quantity = original_quantity * (ratio_to / ratio_from)
    new_remaining_quantity = remaining_quantity * (ratio_to / ratio_from)
    # cost_basis_cents is UNCHANGED — total cost stays the same
    # Per-unit cost is implicitly halved (cost / new_quantity)
```

The `acquired_date` is preserved — the holding period is not reset by a split.

### 6.2 Reverse Split

Inverse of a split: `ratio_from:ratio_to` where `ratio_from > ratio_to` (e.g., 10:1 for a 10-to-1 reverse split):

```
new_original_quantity = original_quantity * (ratio_to / ratio_from)
new_remaining_quantity = remaining_quantity * (ratio_to / ratio_from)
# cost_basis_cents is UNCHANGED
```

If the reverse split produces fractional shares and the broker pays cash-in-lieu, a partial close is triggered for the fractional amount at the cash-in-lieu price.

### 6.3 Merger

When company A merges into company B (acquiring company):

1. For each open lot of security A:
   - Create a new open lot for security B with:
     - `cost_basis_cents` = same as the old lot (tax-deferred exchange)
     - `acquired_date` = same as the old lot (holding period preserved)
     - `quantity` = old quantity * merger conversion ratio
   - Close the old lot with `realized_pnl_cents = 0`

2. If cash consideration is part of the merger:
   - The cash portion is treated as a partial disposal — allocate cost basis proportionally
   - Realized gain on the cash portion = cash received - allocated cost basis

### 6.4 Spinoff

When company A spins off subsidiary as company C:

1. Determine the allocation ratio based on fair market values on the first trading day after the effective date:
   ```
   parent_fmv = market_price_A * quantity
   spinoff_fmv = market_price_C * spinoff_quantity
   total_fmv = parent_fmv + spinoff_fmv
   parent_ratio = parent_fmv / total_fmv
   spinoff_ratio = spinoff_fmv / total_fmv
   ```

2. For each open lot of security A:
   - Reduce `cost_basis_cents` to `cost_basis_cents * parent_ratio`
   - Create a new open lot for security C with:
     - `cost_basis_cents` = original cost basis * spinoff_ratio
     - `acquired_date` = same as the parent lot (holding period preserved)
     - `quantity` = determined by the spinoff distribution ratio

3. The `acquired_date` is preserved for both parent and spinoff lots — this is critical for the deemed cost 10-year threshold.

### 6.5 Audit Trail

Every corporate action adjustment creates an entry in the audit log (see Section 9):
- `action_type`: `'split_adjustment'`, `'reverse_split_adjustment'`, `'merger_close'`, `'merger_open'`, `'spinoff_allocation'`
- `old_values`: the lot's state before the adjustment
- `new_values`: the lot's state after the adjustment
- `reason`: reference to the `corporate_actions.id`

---

## 7. Osakesaastotili Special Rules

Lots inside an `osakesaastotili` account are tracked identically to regular accounts for internal accounting purposes, but differ in tax treatment.

### 7.1 Key Differences

| Behavior | Regular Account | Osakesaastotili |
|----------|----------------|-----------------|
| Lot creation on buy | Yes | Yes |
| Lot close on sell | Yes | Yes (for internal tracking) |
| `realized_pnl_cents` computed | Yes | Yes (for internal tracking) |
| Gain is taxable | Yes (immediately) | **No** — tax-free internally |
| Loss is deductible | Yes (immediately) | **No** — not until account closure |
| Deemed cost comparison | Yes | **No** — irrelevant (no per-disposal tax) |
| Lot matching method | Configurable | Configurable (for internal use only) |

### 7.2 Internal Trade Handling

When a sell occurs inside an osakesaastotili:
1. Lots are closed normally (state changes, `realized_pnl_cents` computed)
2. The gain/loss is stored but **not** included in the tax year's capital income
3. No deemed cost comparison is performed
4. The transaction is flagged as `tax_exempt = true` in tax reporting logic

### 7.3 Withdrawal Tax Calculation

Tax is triggered only on withdrawal from the osakesaastotili. The calculation uses aggregate account values, not individual lots:

```python
account_value = sum_of_all_holdings_market_value + cash_balance
total_deposits = account.osa_deposit_total_cents
total_prior_withdrawals = sum_of_prior_withdrawal_deposit_returns

remaining_deposit_base = total_deposits - total_prior_withdrawals

if account_value <= remaining_deposit_base:
    gains_ratio = 0
    taxable_amount = 0
else:
    gains_ratio = (account_value - remaining_deposit_base) / account_value
    taxable_amount = withdrawal_amount * gains_ratio

deposit_return = withdrawal_amount - taxable_amount
# Update remaining_deposit_base -= deposit_return
```

### 7.4 Tracking Fields

On the `accounts` row for osakesaastotili:
- `osa_deposit_total_cents` — cumulative lifetime deposits (never decreases; capped at 5,000,000 = 50,000 EUR)

Derived at query time:
- `osa_current_value` — sum of open lot market values + cash in account
- `osa_remaining_deposit_base` — `osa_deposit_total_cents` minus the deposit-return portion of all prior withdrawals

---

## 8. Crypto Special Rules

### 8.1 Mandatory FIFO

For all `crypto_wallet` accounts, the lot matching method is **always FIFO**. This cannot be overridden per disposal. Specific identification is not permitted for crypto per Vero.fi guidance.

### 8.2 Global FIFO Queue Per Coin

FIFO is applied **per cryptocurrency across all wallets**, not per-wallet. If the investor holds BTC in Wallet A and Wallet B:

```python
def match_crypto_fifo(security_id, sell_quantity):
    lots = (
        TaxLot.query
        .filter_by(security_id=security_id)
        .join(Account)
        .filter(Account.type == 'crypto_wallet')
        .filter(TaxLot.state.in_(['open', 'partially_closed']))
        .filter(TaxLot.remaining_quantity > 0)
        .order_by(TaxLot.acquired_date.asc(), TaxLot.id.asc())
        .all()
    )
    return consume_lots(lots, sell_quantity)
```

This means a sale from Wallet B may consume a lot that was opened in Wallet A.

### 8.3 Crypto-to-Crypto Swaps

A swap of coin X for coin Y is modeled as two transactions:

1. **Sell transaction** for coin X at fair market value in EUR
   - Closes lots of coin X using FIFO
   - Realized gain/loss computed normally (including deemed cost comparison)

2. **Buy transaction** for coin Y at fair market value in EUR
   - Creates a new lot for coin Y
   - `cost_basis_cents` = EUR market value of coin Y at the time of the swap

The two transactions share a common `external_ref` or `notes` linking them as a swap pair.

### 8.4 Gas Fees and Transaction Fees

- **On purchase**: gas/network fees are added to the lot's `cost_basis_cents`
- **On sale**: gas/network fees are deducted from proceeds
- **On swap**: gas fees are added to the cost basis of the **received** coin (coin Y), not deducted from the disposed coin's proceeds

```
# Swap: 1 BTC -> 15 ETH, gas fee = 0.005 ETH
# BTC disposal proceeds = 1 BTC * market_price_btc_eur (no gas deduction)
# ETH lot cost_basis = (15 ETH * market_price_eth_eur) + (0.005 ETH * market_price_eth_eur)
```

### 8.5 Transfers Between Own Wallets

Transfers between the investor's own wallets are **not taxable events**. No lots are closed. The lot remains associated with the original `account_id` in the database; the transfer is recorded as a `transfer_out` / `transfer_in` pair for reconciliation but does not affect tax lot state.

---

## 9. Audit Trail

### 9.1 Lot Audit Log

Every modification to a tax lot after its initial creation is logged. The audit log is append-only.

| Field | Type | Description |
|-------|------|-------------|
| `id` | `BIGSERIAL` | Primary key |
| `tax_lot_id` | `BIGINT` | FK to `tax_lots.id` |
| `action_type` | `VARCHAR(50)` | One of: `partial_close`, `full_close`, `split_adjustment`, `reverse_split_adjustment`, `merger_close`, `merger_open`, `spinoff_allocation`, `cost_basis_correction`, `manual_override` |
| `old_values` | `JSONB` | Snapshot of changed fields before the action |
| `new_values` | `JSONB` | Snapshot of changed fields after the action |
| `reason` | `TEXT` | Human-readable reason or reference (e.g., `corporate_action:42`) |
| `created_at` | `TIMESTAMPTZ` | When the action occurred |

### 9.2 Immutability Rule

Tax lot rows are **never deleted**. Closed lots remain in the database permanently. If a lot was created in error, it is closed with `realized_pnl_cents = 0` and an audit log entry with `action_type = 'manual_override'` and the reason documented.

---

## 10. Reconciliation

### 10.1 Position Reconciliation

After every transaction and after every corporate action is processed, the system runs a reconciliation check:

```python
for each (account_id, security_id) with open lots:
    lot_quantity = sum(remaining_quantity for lots in [open, partially_closed])
    expected_quantity = sum(transaction.quantity for all transactions)
    # (buys positive, sells negative, transfers signed)

    if lot_quantity != expected_quantity:
        create_reconciliation_alert(
            account_id=account_id,
            security_id=security_id,
            lot_quantity=lot_quantity,
            expected_quantity=expected_quantity,
            severity='error'
        )
```

### 10.2 Rules

- **Never auto-correct**: mismatches are flagged for manual review, never silently adjusted
- **Reconciliation runs**: after every transaction insert, after every corporate action processing, and as a nightly batch job
- **Alert resolution**: a human must review, identify the root cause (missing transaction, duplicate lot, corporate action error), and correct with an audited manual adjustment

---

## 11. Worked Examples

All monetary values shown in EUR for readability. The system stores everything as integer cents internally.

### Example 1: Buy 100 Shares — Lot Creation

**Scenario**: Buy 100 shares of Nokia (NOK1V) at 4.50 EUR on 2025-06-15. Fee: 10.00 EUR.

```
Transaction:
  type: buy
  quantity: 100
  price_cents: 450
  total_cents: 45,000  (100 * 450)
  fee_cents: 1,000

Tax Lot Created:
  lot_id: 1
  security_id: (Nokia)
  state: open
  acquired_date: 2025-06-15
  original_quantity: 100
  remaining_quantity: 100
  cost_basis_cents: 46,000  (45,000 + 1,000)
```

### Example 2: Buy 50 More Shares — Second Lot

**Scenario**: Buy 50 more Nokia at 5.00 EUR on 2025-09-20. Fee: 8.00 EUR.

```
Tax Lot Created:
  lot_id: 2
  security_id: (Nokia)
  state: open
  acquired_date: 2025-09-20
  original_quantity: 50
  remaining_quantity: 50
  cost_basis_cents: 25,800  (25,000 + 800)

Open lots after both buys:
  Lot 1: 100 shares, cost 46,000 cents (acquired 2025-06-15)
  Lot 2:  50 shares, cost 25,800 cents (acquired 2025-09-20)
  Total: 150 shares
```

### Example 3: Sell 75 Shares with FIFO

**Scenario**: Sell 75 Nokia at 5.50 EUR on 2026-01-10. Fee: 12.00 EUR. Account uses FIFO.

```
FIFO matching: consume oldest lots first.

Step 1 — Lot 1 (100 shares, oldest):
  Need 75, lot has 100 → partial close of 75.
  Remaining after: 25 shares.

Lot 1 partial close:
  Closed portion (new lot row):
    lot_id: 3  (new row for the closed portion)
    open_transaction_id: (same as lot 1)
    close_transaction_id: (this sell)
    state: closed
    acquired_date: 2025-06-15
    original_quantity: 75
    remaining_quantity: 0
    cost_basis_cents: 46,000 * (75 / 100) = 34,500
    closed_date: 2026-01-10

  Remaining lot 1 (updated):
    lot_id: 1
    state: partially_closed
    remaining_quantity: 25
    cost_basis_cents: 46,000 - 34,500 = 11,500

Proceeds calculation for the 75 shares:
  Gross proceeds: 75 * 550 = 41,250 cents
  Allocated selling fee: 12.00 EUR (entire fee, since only one lot consumed)
  Net proceeds: 41,250 - 1,200 = 40,050 cents

Realized gain (actual):
  40,050 - 34,500 = 5,550 cents (55.50 EUR)

Deemed cost check (held ~7 months, < 10 years):
  Deemed cost (20%): 41,250 * 20 / 100 = 8,250 cents
  Deemed gain: 41,250 - 8,250 = 33,000 cents (330.00 EUR)

  Actual gain (55.50) < Deemed gain (330.00) → use actual cost basis.
  method_used: 'actual'

Lot 3 final values:
  proceeds_cents: 40,050
  realized_pnl_cents: 5,550

State after sale:
  Lot 1: 25 shares, cost 11,500 cents, state: partially_closed
  Lot 2: 50 shares, cost 25,800 cents, state: open
  Lot 3: 75 shares, cost 34,500 cents, state: closed (realized +55.50 EUR)
```

### Example 4: Sell Remaining Using Specific Identification

**Scenario**: Sell the remaining 75 shares on 2026-03-01 at 4.80 EUR. Fee: 12.00 EUR. The investor chooses specific identification and wants to sell Lot 2 first (50 shares), then Lot 1's remainder (25 shares).

```
Specific identification request: [(lot_2, 50), (lot_1, 25)]

--- Lot 2: full close (50 shares) ---
  Gross proceeds for lot 2: 50 * 480 = 24,000 cents
  Allocated selling fee: 1,200 * (50 / 75) = 800 cents
  Net proceeds: 24,000 - 800 = 23,200 cents
  Cost basis: 25,800 cents

  Actual gain: 23,200 - 25,800 = -2,600 cents (-26.00 EUR loss)

  Loss → deemed cost is irrelevant (cannot create or increase a loss).
  method_used: 'actual'

  Lot 2 updated:
    state: closed
    remaining_quantity: 0
    proceeds_cents: 23,200
    realized_pnl_cents: -2,600
    closed_date: 2026-03-01

--- Lot 1 remainder: full close (25 shares) ---
  Gross proceeds for lot 1: 25 * 480 = 12,000 cents
  Allocated selling fee: 1,200 * (25 / 75) = 400 cents
  Net proceeds: 12,000 - 400 = 11,600 cents
  Cost basis: 11,500 cents

  Actual gain: 11,600 - 11,500 = 100 cents (1.00 EUR)

  Deemed cost check (held ~8.5 months, < 10 years):
    Deemed cost (20%): 12,000 * 20 / 100 = 2,400 cents
    Deemed gain: 12,000 - 2,400 = 9,600 cents (96.00 EUR)
    Actual gain (1.00) < Deemed gain (96.00) → use actual cost basis.
    method_used: 'actual'

  Lot 1 updated:
    state: closed
    remaining_quantity: 0
    proceeds_cents: 11,600
    realized_pnl_cents: 100
    closed_date: 2026-03-01

Final state: all lots closed. Net realized P&L = 5,550 - 2,600 + 100 = 3,050 cents (30.50 EUR).
```

### Example 5: Stock Split 2:1

**Scenario**: Nokia announces a 2:1 stock split effective 2025-08-01. At that time, the investor has Lot 1 (100 shares, cost 46,000 cents) still fully open.

```
Corporate action:
  type: split
  ratio_from: 1
  ratio_to: 2
  security_id: (Nokia)
  effective_date: 2025-08-01

Processing Lot 1:
  Before split:
    original_quantity: 100
    remaining_quantity: 100
    cost_basis_cents: 46,000

  After split:
    original_quantity: 200   (100 * 2/1)
    remaining_quantity: 200   (100 * 2/1)
    cost_basis_cents: 46,000  (UNCHANGED)
    Per-share cost: 46,000 / 200 = 230 cents (was 460 cents)
    acquired_date: 2025-06-15  (UNCHANGED — holding period preserved)

Audit log entry:
  tax_lot_id: 1
  action_type: split_adjustment
  old_values: {"original_quantity": 100, "remaining_quantity": 100}
  new_values: {"original_quantity": 200, "remaining_quantity": 200}
  reason: "corporate_action:7 — Nokia 2:1 split"
```

### Example 6: Deemed Cost Comparison on Disposal

**Scenario**: Investor bought 200 shares of Sampo at 8.00 EUR on 2014-05-10 (cost basis: 1,612 EUR including fees). Sells all at 45.00 EUR on 2026-06-15. Fee: 15.00 EUR. Held 12 years.

```
Gross proceeds: 200 * 4,500 = 900,000 cents (9,000.00 EUR)
Selling fee: 1,500 cents
Net proceeds: 898,500 cents (8,985.00 EUR)
Cost basis: 161,200 cents (1,612.00 EUR)

Actual gain: 898,500 - 161,200 = 737,300 cents (7,373.00 EUR)

Holding period: 2014-05-10 to 2026-06-15 = 12.1 years (>= 10 years)
Deemed cost (40%): 900,000 * 40 / 100 = 360,000 cents (3,600.00 EUR)
Deemed gain: 900,000 - 360,000 = 540,000 cents (5,400.00 EUR)

Actual gain (7,373.00) > Deemed gain (5,400.00) → USE DEEMED COST (40%)

Lot closed with:
  realized_pnl_cents: 540,000  (5,400.00 EUR — the deemed gain)
  method_used: 'deemed_40'

Tax saved: (737,300 - 540,000) * 30% = 59,190 cents (591.90 EUR)
```

### Example 7: Crypto Swap (BTC to ETH)

**Scenario**: Investor bought 0.5 BTC at 25,000 EUR/BTC on 2024-03-01 (cost basis: 12,510 EUR including 10 EUR exchange fee). On 2026-02-15, swaps 0.5 BTC for 8 ETH. Market prices at swap time: BTC = 50,000 EUR, ETH = 3,125 EUR. Gas fee: 0.002 ETH.

```
--- Step 1: Dispose of BTC (sell side of swap) ---

BTC lot (lot_id: 10):
  acquired_date: 2024-03-01
  remaining_quantity: 0.5
  cost_basis_cents: 1,251,000  (12,510.00 EUR)

Sell transaction:
  quantity: -0.5
  price = 50,000 EUR/BTC
  total_cents: 2,500,000  (0.5 * 50,000 * 100)
  fee_cents: 0  (gas fee attributed to received coin)

Gross proceeds: 2,500,000 cents (25,000.00 EUR)
Net proceeds: 2,500,000 cents (no fee deduction on sell side)
Actual gain: 2,500,000 - 1,251,000 = 1,249,000 cents (12,490.00 EUR)

Deemed cost check (held ~23 months, < 10 years):
  Deemed cost (20%): 2,500,000 * 20 / 100 = 500,000 cents
  Deemed gain: 2,500,000 - 500,000 = 2,000,000 cents (20,000.00 EUR)
  Actual gain (12,490.00) < Deemed gain (20,000.00) → use actual cost.
  method_used: 'actual'

Lot 10 closed:
  realized_pnl_cents: 1,249,000 (12,490.00 EUR)

--- Step 2: Acquire ETH (buy side of swap) ---

Buy transaction:
  quantity: 8.0 ETH
  price = 3,125 EUR/ETH
  total_cents: 2,500,000  (8 * 3,125 * 100)
  fee_cents: 625  (0.002 ETH * 3,125 EUR/ETH * 100 = 625 cents)

New ETH lot (lot_id: 11):
  acquired_date: 2026-02-15  (swap date — NOT original BTC purchase date)
  original_quantity: 8.0
  remaining_quantity: 8.0
  cost_basis_cents: 2,500,625  (2,500,000 + 625 gas fee)

Note: The ETH holding period starts fresh from the swap date.
Future deemed cost calculation for this ETH lot will use 2026-02-15 as the start.
```

---

## Edge Cases

1. **Sell exceeds open lots**: If the sell quantity exceeds the total `remaining_quantity` across all eligible lots, the transaction is rejected. The system must not create lots with negative remaining quantity.

2. **Same-day buys and sells**: When a buy and sell occur on the same date, the buy creates its lot first (by insertion order), then the sell is matched. FIFO ordering ties on date are broken by `tax_lots.id`.

3. **Zero-cost lots**: Lots from mining rewards, airdrops, or zero-cost corporate actions may have `cost_basis_cents = 0`. This is valid. The full proceeds become the realized gain.

4. **Fractional shares from splits**: If a split produces a fractional share and the broker pays cash-in-lieu, the lot is partially closed for the fractional amount at the cash-in-lieu price. The remaining whole-share portion stays open.

5. **Multi-currency lot close**: When closing a lot in a USD account for Finnish tax reporting, the system must convert both cost basis and proceeds to EUR. The gain in EUR may differ from the gain in USD due to FX rate changes between acquisition and disposal.

6. **Corporate action on partially closed lot**: Only the `remaining_quantity` is adjusted. The already-closed portion (a separate lot row) retains its pre-action values — it was settled before the corporate event.

7. **Lot matching across accounts (crypto)**: Crypto FIFO spans all `crypto_wallet` accounts. A sell in Wallet A may consume a lot from Wallet B. The `close_transaction_id` references the sell in Wallet A, but the lot's `account_id` is Wallet B. This cross-account reference is expected.

8. **Osakesaastotili closure**: When the OST account is closed, all remaining open lots are force-closed at market value. The aggregate gain/loss is computed at the account level per the withdrawal formula, not as a sum of individual lot P&Ls.

9. **Dividend reinvestment (DRIP)**: Each reinvested dividend creates a new tax lot with the reinvestment price as cost basis. In a regular account, the dividend itself is a separate taxable event (see [Finnish tax rules Section 7](../03-calculations/tax-finnish.md#7-dividend-taxation)).

10. **Lot cost basis correction**: If a lot's cost basis must be corrected (e.g., retroactive fee adjustment from the broker), the correction updates `cost_basis_cents` and creates an audit log entry with `action_type = 'cost_basis_correction'`. Already-closed lots derived from this lot are NOT retroactively adjusted — the correction only affects the open remainder.

11. **Transfer between own accounts (non-crypto)**: When transferring a stock position between two regular accounts, the tax lot is closed in the source account and a new lot is created in the target account with the same `cost_basis_cents` and `acquired_date`. This is not a taxable event.

12. **Holding period across corporate actions**: Stock splits, reverse splits, mergers, and spinoffs preserve the original `acquired_date`. This is critical for the deemed cost 10-year threshold. Only crypto swaps reset the holding period for the acquired coin.

13. **Rounding on multi-lot sells**: When selling fees are allocated across multiple lots, rounding may cause the allocated fees to not sum exactly to the total fee. The last lot in the allocation receives the remainder to ensure exact totals.

---

## Open Questions

1. **Tax lot audit log table**: Should the audit log be a formal table in the data model spec, or kept as an application-layer concern? Currently described here but not defined in `data-model.md`.

2. **Cross-wallet crypto lot display**: When crypto FIFO spans wallets, how should the UI display which lot was consumed? Show the source wallet, or abstract it away?

3. **Deemed cost storage**: Should `deemed_gain_cents` and `method_used` be columns on `tax_lots`, a separate `tax_lot_disposals` table, or computed on-the-fly for tax reports?

---

## Changelog

| Date | Change |
|------|--------|
| 2026-03-19 | Initial draft — DRAFT status |
