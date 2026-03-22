# Portfolio Valuation & Return Calculations

This spec defines every portfolio valuation and return calculation used in the Bloomvalley terminal. It is the computational backbone for the Portfolio Dashboard, Risk Dashboard, Performance Attribution, and Tax Module features. Every formula is expressed in both mathematical notation and Python pseudocode using integer cents or `Decimal` — never floating-point for money (per spec conventions).

**Status: DRAFT**

## Dependencies

- `../00-meta/spec-conventions.md` — monetary values in cents, date handling, `Decimal` policy
- `../01-system/data-model.md` — `holdings_snapshot`, `tax_lots`, `transactions`, `prices`, `fx_rates`, `dividends`, `accounts`, `securities` tables
- `../03-calculations/tax-finnish.md` — deemed cost of acquisition, realized P&L rules, account-type tax treatment
- `../03-calculations/tax-lot-tracking.md` — lot creation, FIFO/specific-ID matching, partial close mechanics

---

## 1. Portfolio Valuation

### 1.1 Single Holding Value

The market value of a single holding (one security in one account) on a given date.

**Math:**

$$
V_{holding} = Q \times P_{close} \times \frac{1}{R_{fx}}
$$

Where:
- $Q$ = quantity held (`holdings_snapshot.quantity` or sum of `tax_lots.remaining_quantity` for open lots)
- $P_{close}$ = closing price in the security's native currency (`prices.close_cents`)
- $R_{fx}$ = EUR/foreign exchange rate from `fx_rates.rate` (1 EUR = $R_{fx}$ foreign units); division converts foreign to EUR
- If the security is EUR-denominated, $R_{fx} = 1$

**Python pseudocode:**

```python
from decimal import Decimal, ROUND_HALF_UP

def holding_value_eur_cents(
    quantity: Decimal,
    close_price_cents: int,
    fx_rate: Decimal,  # 1 EUR = fx_rate foreign units; None if EUR security
) -> int:
    """Returns market value in EUR cents."""
    if fx_rate is None or fx_rate == 1:
        value = quantity * close_price_cents
    else:
        value = quantity * Decimal(close_price_cents) / fx_rate
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
```

**Data sources:**
- `prices.close_cents` — latest available closing price for the security
- `fx_rates.rate` — daily close rate where `base_currency = 'EUR'` and `quote_currency = security.currency`

### 1.2 Cash Balance

Each account may hold a cash balance. Cash is tracked via deposit/withdrawal transactions and trade settlements.

**Python pseudocode:**

```python
def account_cash_balance_cents(account_id: int) -> int:
    """Sum of all cash-affecting transactions for the account, in account currency cents."""
    # deposits (+), withdrawals (-), buy settlements (-), sell settlements (+),
    # dividends received (+), fees (-), interest (+)
    return sum(
        t.total_cents for t in transactions
        if t.account_id == account_id and t.type in CASH_AFFECTING_TYPES
    )
```

### 1.3 Account Value

$$
V_{account} = \sum_{h \in H_{account}} V_{holding,h} + C_{account}
$$

Where $C_{account}$ is the cash balance in the account (converted to EUR if needed).

**Python pseudocode:**

```python
def account_value_eur_cents(account_id: int, date: date) -> int:
    """Total account value in EUR cents: sum of holdings + cash balance."""
    holdings_total = sum(
        holding_value_eur_cents(h.quantity, h.market_price_cents, h.fx_rate)
        for h in get_holdings_snapshot(account_id, date)
    )
    cash = account_cash_balance_eur_cents(account_id, date)
    return holdings_total + cash
```

### 1.4 Total Portfolio Value

$$
V_{portfolio} = \sum_{a \in A} V_{account,a}
$$

Where $A$ is the set of all active accounts.

**Python pseudocode:**

```python
def portfolio_value_eur_cents(date: date) -> int:
    """Total portfolio value in EUR cents across all active accounts."""
    return sum(
        account_value_eur_cents(a.id, date)
        for a in accounts
        if a.is_active
    )
```

### 1.5 Missing Price Handling

When a closing price is not available for a security on the requested date:

1. **Use the most recent available price** — look backward up to 5 trading days.
2. **Flag as stale** — attach a `staleness_days` field to the holding value indicating how old the price is.
3. **Never zero out** — a missing price must not cause the holding value to become zero. The last known price is always preferred over no price.
4. **Threshold**: if the most recent price is older than 5 trading days, the holding is flagged as `price_missing` in the response and excluded from weight calculations, but its last-known value is still included in the portfolio total.

**Python pseudocode:**

```python
def get_price_with_staleness(
    security_id: int, date: date
) -> tuple[int, int]:  # (close_cents, staleness_days)
    """Returns (close_cents, staleness_days). Raises if no price found within 30 days."""
    for lookback in range(31):
        check_date = date - timedelta(days=lookback)
        price = get_price(security_id, check_date)
        if price is not None:
            return price.close_cents, lookback
    raise PriceMissingError(f"No price for security {security_id} within 30 days of {date}")
```

---

## 2. Cost Basis Calculations

### 2.1 Per Lot Cost Basis

Stored directly on the `tax_lots` table as `cost_basis_cents`. Includes the purchase price plus allocated transaction fees, converted to EUR at the trade-date FX rate.

$$
CB_{lot} = (Q_{lot} \times P_{purchase} + F_{allocated}) \times \frac{1}{R_{fx,trade}}
$$

Where:
- $Q_{lot}$ = `tax_lots.original_quantity`
- $P_{purchase}$ = per-unit purchase price in native currency
- $F_{allocated}$ = portion of transaction fees allocated to this lot
- $R_{fx,trade}$ = FX rate at trade date (`tax_lots.fx_rate_at_open`)

**Note:** The cost basis is computed once at lot creation time and stored. It does not change with subsequent FX rate movements — this is correct per Finnish tax rules (trade-date FX rate applies).

### 2.2 Per Holding Cost Basis

The aggregate cost basis for a security within an account — the sum of all open lots.

$$
CB_{holding} = \sum_{l \in L_{open}} CB_{lot,l} \times \frac{Q_{remaining,l}}{Q_{original,l}}
$$

For partially closed lots, the cost basis is prorated by the remaining fraction.

**Python pseudocode:**

```python
def holding_cost_basis_eur_cents(account_id: int, security_id: int) -> int:
    """Aggregate cost basis of all open/partially-closed lots for this holding."""
    total = Decimal(0)
    for lot in get_open_lots(account_id, security_id):
        fraction = lot.remaining_quantity / lot.original_quantity
        total += Decimal(lot.cost_basis_cents) * fraction
    return int(total.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
```

### 2.3 Per Account Cost Basis

$$
CB_{account} = \sum_{h \in H_{account}} CB_{holding,h}
$$

### 2.4 Total Portfolio Cost Basis

$$
CB_{portfolio} = \sum_{a \in A} CB_{account,a}
$$

---

## 3. Unrealized P&L

### 3.1 Per Lot Unrealized P&L

$$
UPL_{lot} = MV_{lot} - CB_{lot,remaining}
$$

Where:
- $MV_{lot} = Q_{remaining} \times P_{close} \times \frac{1}{R_{fx,today}}$ (current market value in EUR)
- $CB_{lot,remaining} = CB_{lot} \times \frac{Q_{remaining}}{Q_{original}}$ (prorated cost basis)

**Python pseudocode:**

```python
def lot_unrealized_pnl_eur_cents(
    lot: TaxLot, close_price_cents: int, fx_rate: Decimal
) -> int:
    """Unrealized P&L for a single open/partially-closed lot, in EUR cents."""
    market_value = holding_value_eur_cents(lot.remaining_quantity, close_price_cents, fx_rate)
    remaining_cost = int(
        (Decimal(lot.cost_basis_cents) * lot.remaining_quantity / lot.original_quantity)
        .quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )
    return market_value - remaining_cost
```

### 3.2 Per Holding Unrealized P&L

$$
UPL_{holding} = \sum_{l \in L_{open}} UPL_{lot,l}
$$

Equivalently: $UPL_{holding} = MV_{holding} - CB_{holding}$.

### 3.3 Unrealized P&L Percentage

$$
UPL\%_{holding} = \frac{UPL_{holding}}{CB_{holding}} \times 100
$$

**Edge case — zero cost basis:** When $CB_{holding} = 0$ (gifted shares with zero donor cost, inherited shares with zero stepped-up value, or shares acquired through a corporate action at zero cost):

```python
def unrealized_pnl_pct(unrealized_pnl_cents: int, cost_basis_cents: int) -> Decimal | None:
    """Returns percentage or None if cost basis is zero."""
    if cost_basis_cents == 0:
        return None  # display as "N/A" or "inf" in the UI
    return (Decimal(unrealized_pnl_cents) / Decimal(cost_basis_cents) * 100).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
```

---

## 4. Realized P&L

### 4.1 Per Lot Realized P&L

Computed when a lot is closed (fully or partially) and stored on the `tax_lots` row.

$$
RPL_{lot} = Proceeds_{lot} - CB_{closed\_portion}
$$

Where:
- $Proceeds_{lot}$ = `tax_lots.proceeds_cents` (sale price times closed quantity, minus allocated selling fees, in EUR)
- $CB_{closed\_portion}$ = cost basis prorated by the closed fraction

**Finnish tax integration:** For each closed lot, the system also computes the deemed cost of acquisition (see [tax-finnish.md](../03-calculations/tax-finnish.md) Section 2). The stored `realized_pnl_cents` uses the actual cost basis; the deemed cost comparison is performed at tax calculation time.

### 4.2 Aggregated Realized P&L

**Per security:**

$$
RPL_{security} = \sum_{l \in L_{closed,security}} RPL_{lot,l}
$$

**Per account:**

$$
RPL_{account} = \sum_{s \in S_{account}} RPL_{security,s}
$$

**Per time period:** Filter by `tax_lots.closed_date` within the period.

**Python pseudocode:**

```python
def realized_pnl_for_period(
    account_id: int | None,  # None = all accounts
    security_id: int | None,  # None = all securities
    from_date: date,
    to_date: date,
) -> int:
    """Sum of realized P&L in EUR cents for closed lots within the date range."""
    lots = get_closed_lots(
        account_id=account_id,
        security_id=security_id,
        closed_date_from=from_date,
        closed_date_to=to_date,
    )
    return sum(lot.realized_pnl_cents for lot in lots)
```

### 4.3 Year-to-Date Realized P&L

For tax reporting, compute from January 1 of the current year through today:

```python
def ytd_realized_pnl(year: int) -> int:
    return realized_pnl_for_period(
        account_id=None,
        security_id=None,
        from_date=date(year, 1, 1),
        to_date=date(year, 12, 31),
    )
```

---

## 5. Time-Weighted Return (TWR)

The standard method for comparing portfolio performance against benchmarks. TWR eliminates the distortion caused by the timing and size of external cash flows (deposits and withdrawals), measuring pure investment performance.

### 5.1 Sub-Period Holding Period Return

Break the evaluation period into sub-periods at each external cash flow event. An external cash flow is a deposit into or withdrawal from the portfolio (transfers between accounts are internal and do not create sub-periods).

For sub-period $i$:

$$
HPR_i = \frac{V_{end,i} - V_{start,i} - CF_i}{V_{start,i}}
$$

Where:
- $V_{start,i}$ = portfolio value at the start of sub-period $i$ (immediately after the previous cash flow)
- $V_{end,i}$ = portfolio value at the end of sub-period $i$ (immediately before the next cash flow)
- $CF_i$ = net external cash flow at the start of sub-period $i$ (positive = deposit, negative = withdrawal)

**Convention:** Cash flows are assumed to occur at the start of the sub-period. The sub-period return measures what happened after the cash flow arrived.

### 5.2 Geometric Linking

Link all sub-period returns to get the total TWR:

$$
TWR = \prod_{i=1}^{n}(1 + HPR_i) - 1
$$

### 5.3 Annualized TWR

$$
TWR_{annualized} = (1 + TWR)^{365/D} - 1
$$

Where $D$ = total calendar days in the evaluation period.

### 5.4 Implementation

**Python pseudocode:**

```python
def time_weighted_return(
    valuations: list[tuple[date, int]],  # [(date, portfolio_value_eur_cents), ...]
    cash_flows: list[tuple[date, int]],  # [(date, net_flow_eur_cents), ...]
) -> Decimal:
    """
    Compute TWR over the period defined by valuations.

    valuations: daily portfolio values (at least start and end dates).
    cash_flows: external flows (deposits > 0, withdrawals < 0), sorted by date.
    """
    # Build sub-periods: break at each cash flow date
    cf_by_date: dict[date, int] = defaultdict(int)
    for cf_date, cf_amount in cash_flows:
        cf_by_date[cf_date] += cf_amount  # multiple flows on same day: sum them

    breakpoints = sorted(set([valuations[0][0], valuations[-1][0]] + list(cf_by_date.keys())))

    product = Decimal(1)
    for i in range(len(breakpoints) - 1):
        v_start = get_valuation(valuations, breakpoints[i])
        v_end = get_valuation(valuations, breakpoints[i + 1])
        cf = cf_by_date.get(breakpoints[i], 0)

        denominator = v_start + cf  # value after cash flow
        if denominator == 0:
            continue  # skip zero-value sub-period (inception)

        hpr = Decimal(v_end - v_start - cf) / Decimal(denominator)
        # Corrected: v_start here already includes the CF
        # Actually: HPR = (V_end) / (V_start + CF) - 1
        hpr = Decimal(v_end) / Decimal(v_start + cf) - 1
        product *= (1 + hpr)

    return product - 1


def annualized_return(total_return: Decimal, days: int) -> Decimal:
    """Annualize a cumulative return."""
    if days <= 0:
        return Decimal(0)
    return (1 + total_return) ** (Decimal(365) / Decimal(days)) - 1
```

### 5.5 Special Cases

- **Multiple cash flows on the same day:** Sum all flows for that day into a single net flow. Only one sub-period break is created.
- **Inception date with zero value:** When the portfolio starts with zero value and the first cash flow is a deposit, skip the first sub-period (since $V_{start} + CF = CF$ would be the denominator, but there is no prior return to measure). The first sub-period starts from the first deposit.
- **No cash flows:** If there are no external cash flows, TWR simplifies to a simple return: $(V_{end} / V_{start}) - 1$.

---

## 6. Money-Weighted Return (MWWR / XIRR)

Measures the actual return experienced by the investor, accounting for the timing and magnitude of cash flows. Unlike TWR, MWWR is influenced by when the investor adds or withdraws money.

### 6.1 XIRR Definition

Find the annualized rate $r$ such that the net present value of all cash flows equals zero:

$$
\sum_{i=0}^{n} CF_i \times (1 + r)^{-t_i} = 0
$$

Where:
- $CF_i$ = cash flow at time $i$ (deposits are negative from the investor's perspective — money going out; the final portfolio value is positive — money coming back)
- $t_i$ = fraction of a year from the first cash flow: $t_i = (d_i - d_0) / 365.25$
- $d_i$ = date of cash flow $i$

**Cash flow sign convention (investor perspective):**
- Deposit into portfolio: $CF < 0$ (investor pays money in)
- Withdrawal from portfolio: $CF > 0$ (investor receives money)
- Final portfolio value: $CF > 0$ (treated as if the investor could withdraw everything)

### 6.2 Newton's Method Implementation

**Python pseudocode:**

```python
def xirr(
    cash_flows: list[tuple[date, int]],  # [(date, amount_eur_cents), ...]
    initial_guess: Decimal = Decimal("0.10"),
    max_iterations: int = 100,
    tolerance: Decimal = Decimal("1e-7"),
) -> Decimal | None:
    """
    Compute XIRR using Newton's method.

    Returns annualized rate as Decimal, or None if no convergence.
    Cash flows use investor sign convention: deposits < 0, withdrawals/final value > 0.
    """
    if len(cash_flows) < 2:
        return None

    d0 = cash_flows[0][0]

    def npv(rate: Decimal) -> Decimal:
        return sum(
            Decimal(cf) * (1 + rate) ** (-(d - d0).days / Decimal("365.25"))
            for d, cf in cash_flows
        )

    def npv_derivative(rate: Decimal) -> Decimal:
        return sum(
            Decimal(cf) * (-(d - d0).days / Decimal("365.25"))
            * (1 + rate) ** (-(d - d0).days / Decimal("365.25") - 1)
            for d, cf in cash_flows
        )

    rate = initial_guess
    for _ in range(max_iterations):
        f = npv(rate)
        f_prime = npv_derivative(rate)
        if f_prime == 0:
            return None  # derivative is zero, cannot continue
        new_rate = rate - f / f_prime
        if abs(new_rate - rate) < tolerance:
            return new_rate.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
        rate = new_rate

    return None  # did not converge
```

### 6.3 Special Cases

- **No convergence:** Return `None` with a warning. The UI should display "Unable to compute" with an explanation that the cash flow pattern does not converge.
- **Single cash flow:** Cannot compute XIRR — at minimum, the initial investment and the current portfolio value are needed.
- **Negative total value:** If the portfolio value is negative (e.g., due to margin — though not applicable per investment constraints), XIRR may not converge or may produce a complex result. Return `None`.
- **Very short period:** For periods under 30 days, XIRR can produce extreme annualized rates. The UI should show both the raw return and the annualized XIRR, with a caveat for short periods.

---

## 7. Daily Return Series

Daily returns are the foundation for risk metrics (volatility, Sharpe ratio, max drawdown, etc.).

### 7.1 Daily Return with Cash Flow Adjustment

$$
r_t = \frac{V_t - V_{t-1} - CF_t}{V_{t-1}}
$$

Where:
- $V_t$ = portfolio value at end of day $t$ (from `holdings_snapshot`)
- $V_{t-1}$ = portfolio value at end of previous day
- $CF_t$ = net external cash flow on day $t$

**Python pseudocode:**

```python
def daily_returns(
    start_date: date,
    end_date: date,
) -> list[tuple[date, Decimal]]:
    """
    Compute daily return series from holdings_snapshot, adjusted for cash flows.
    Computed on-the-fly (not stored).
    """
    snapshots = get_portfolio_values(start_date, end_date)  # from holdings_snapshot
    cash_flows = get_external_cash_flows(start_date, end_date)
    cf_by_date = {d: amt for d, amt in cash_flows}

    returns = []
    for i in range(1, len(snapshots)):
        d, v_today = snapshots[i]
        _, v_yesterday = snapshots[i - 1]
        cf = cf_by_date.get(d, 0)

        if v_yesterday == 0:
            returns.append((d, Decimal(0)))
            continue

        r = Decimal(v_today - v_yesterday - cf) / Decimal(v_yesterday)
        returns.append((d, r))

    return returns
```

### 7.2 Storage Strategy

Daily returns are **computed on-the-fly** from the `holdings_snapshot` table, not stored separately. Rationale:
- `holdings_snapshot` already stores daily portfolio state.
- Computing returns from snapshots avoids data duplication and consistency issues.
- For a 15-year history, that is roughly 3,900 trading days — trivial to compute in-memory.

---

## 8. Multi-Currency Handling

### 8.1 Price Storage

All prices are stored in their native currency in the `prices` table. No conversion at ingestion time.

### 8.2 FX Rate Convention

The `fx_rates` table stores rates as **1 EUR = X foreign currency units**.

To convert a foreign-currency value to EUR:

$$
Value_{EUR} = \frac{Value_{foreign}}{R_{fx}}
$$

### 8.3 FX Rate Selection

| Context | FX Rate Source |
|---------|---------------|
| Portfolio valuation (today) | Latest daily close from `fx_rates` |
| Portfolio valuation (historical) | `fx_rates.rate` for that date |
| Cost basis (lot creation) | Trade-date FX rate, stored as `tax_lots.fx_rate_at_open` |
| Realized P&L (lot close) | Trade-date FX rate, stored as `tax_lots.fx_rate_at_close` |
| `holdings_snapshot` rebuild | Daily close FX rate at snapshot date |
| Dividend conversion | FX rate on pay date, stored on `dividends.fx_rate` |

### 8.4 Stale FX Rate Handling

If today's FX rate is not yet available:
1. Use the most recent available rate from `fx_rates` (look back up to 5 days).
2. Flag the rate as stale in the API response with `fx_staleness_days`.
3. For weekends/holidays this is expected behavior (ECB does not publish rates on non-business days).

**Python pseudocode:**

```python
def get_fx_rate(quote_currency: str, target_date: date) -> tuple[Decimal, int]:
    """
    Returns (rate, staleness_days) for EUR/quote_currency.
    If quote_currency is EUR, returns (1, 0).
    """
    if quote_currency == "EUR":
        return Decimal(1), 0

    for lookback in range(8):  # covers weekends + a few holidays
        check_date = target_date - timedelta(days=lookback)
        rate = query_fx_rate("EUR", quote_currency, check_date)
        if rate is not None:
            return rate, lookback

    raise FxRateMissingError(
        f"No EUR/{quote_currency} rate within 7 days of {target_date}"
    )
```

### 8.5 FX Impact Decomposition

For attribution purposes, separate the asset return from the currency return.

For a foreign-currency holding over a period:

$$
R_{total} = R_{local} + R_{fx} + R_{local} \times R_{fx}
$$

Where:
- $R_{local} = \frac{P_{end}}{P_{start}} - 1$ (return in the security's native currency)
- $R_{fx} = \frac{R_{fx,start}}{R_{fx,end}} - 1$ (EUR appreciation/depreciation vs the foreign currency; note the inversion because higher $R_{fx}$ means EUR buys more foreign, i.e., foreign currency depreciated)

**Python pseudocode:**

```python
def decompose_fx_impact(
    price_start_cents: int,
    price_end_cents: int,
    fx_rate_start: Decimal,  # 1 EUR = X foreign
    fx_rate_end: Decimal,
) -> tuple[Decimal, Decimal, Decimal]:
    """Returns (local_return, fx_return, total_return_eur)."""
    r_local = Decimal(price_end_cents) / Decimal(price_start_cents) - 1
    r_fx = fx_rate_start / fx_rate_end - 1  # positive when foreign currency appreciates vs EUR
    r_total = (1 + r_local) * (1 + r_fx) - 1
    return r_local, r_fx, r_total
```

---

## 9. Performance Attribution

### 9.1 By Asset Class

Attribute total portfolio return to contributions from each asset class (stock, bond, etf, crypto).

$$
Contribution_{class} = w_{class} \times R_{class}
$$

Where:
- $w_{class}$ = weight of the asset class at the start of the period (beginning-of-period market value / total portfolio value)
- $R_{class}$ = return of that asset class over the period

**Verification:** $\sum_{class} Contribution_{class} \approx R_{portfolio}$ (approximate due to compounding within the period).

**Python pseudocode:**

```python
def attribution_by_asset_class(
    start_date: date, end_date: date
) -> dict[str, Decimal]:
    """
    Returns {asset_class: contribution_to_return} for each class.
    """
    start_snapshot = get_portfolio_snapshot(start_date)
    end_snapshot = get_portfolio_snapshot(end_date)
    total_start = sum(h.market_value_eur_cents for h in start_snapshot)

    if total_start == 0:
        return {}

    contributions = {}
    for asset_class in ("stock", "bond", "etf", "crypto"):
        class_start = sum(
            h.market_value_eur_cents for h in start_snapshot
            if h.security.asset_class == asset_class
        )
        class_end = sum(
            h.market_value_eur_cents for h in end_snapshot
            if h.security.asset_class == asset_class
        )
        # Include dividends received during the period
        class_dividends = sum_dividends_for_class(asset_class, start_date, end_date)

        weight = Decimal(class_start) / Decimal(total_start)
        if class_start == 0:
            class_return = Decimal(0)
        else:
            class_return = Decimal(class_end + class_dividends - class_start) / Decimal(class_start)

        contributions[asset_class] = weight * class_return

    return contributions
```

### 9.2 By Account

Same methodology as asset class attribution, but group holdings by `account_id`.

$$
Contribution_{account} = w_{account} \times R_{account}
$$

### 9.3 By Currency

Decompose each holding's return into local return and FX return (Section 8.5), then aggregate by currency.

$$
FX\_Contribution_{ccy} = w_{ccy} \times R_{fx,ccy}
$$

$$
Local\_Contribution_{ccy} = w_{ccy} \times R_{local,ccy}
$$

### 9.4 Brinson-Style Attribution (Simplified)

A single-period Brinson-Fachler decomposition comparing the portfolio against a benchmark:

**Allocation Effect** — the impact of over/under-weighting asset classes relative to the benchmark:

$$
AE_{class} = (w_{p,class} - w_{b,class}) \times (R_{b,class} - R_{b,total})
$$

**Selection Effect** — the impact of picking different securities within each asset class:

$$
SE_{class} = w_{b,class} \times (R_{p,class} - R_{b,class})
$$

**Interaction Effect:**

$$
IE_{class} = (w_{p,class} - w_{b,class}) \times (R_{p,class} - R_{b,class})
$$

**Total Attribution:**

$$
R_p - R_b = \sum_{class}(AE_{class} + SE_{class} + IE_{class})
$$

Where:
- $w_{p,class}$ = portfolio weight for asset class
- $w_{b,class}$ = benchmark weight for asset class
- $R_{p,class}$ = portfolio return for asset class
- $R_{b,class}$ = benchmark return for asset class
- $R_{b,total}$ = total benchmark return

**Python pseudocode:**

```python
def brinson_attribution(
    portfolio_weights: dict[str, Decimal],   # {asset_class: weight}
    benchmark_weights: dict[str, Decimal],
    portfolio_returns: dict[str, Decimal],   # {asset_class: return}
    benchmark_returns: dict[str, Decimal],
    benchmark_total_return: Decimal,
) -> dict[str, dict[str, Decimal]]:
    """
    Returns {asset_class: {allocation, selection, interaction}} for each class.
    """
    result = {}
    for cls in portfolio_weights:
        wp = portfolio_weights.get(cls, Decimal(0))
        wb = benchmark_weights.get(cls, Decimal(0))
        rp = portfolio_returns.get(cls, Decimal(0))
        rb = benchmark_returns.get(cls, Decimal(0))

        result[cls] = {
            "allocation": (wp - wb) * (rb - benchmark_total_return),
            "selection": wb * (rp - rb),
            "interaction": (wp - wb) * (rp - rb),
        }
    return result
```

---

## 10. Dividend Return

### 10.1 Dividend Yield

Trailing 12-month dividend yield for a single holding:

$$
DY_{holding} = \frac{\sum_{div \in D_{12m}} Div_{gross,EUR}}{MV_{holding}}
$$

Where $D_{12m}$ is the set of dividends received in the trailing 12 months.

### 10.2 Dividend Return Contribution

The contribution of dividends to the portfolio's total return over a period:

$$
DR = \frac{\sum_{div \in D_{period}} Div_{net,EUR}}{V_{start}}
$$

Where $V_{start}$ is the portfolio value at the beginning of the period.

**Python pseudocode:**

```python
def dividend_return_contribution(
    start_date: date, end_date: date
) -> Decimal:
    """Dividend return as a fraction of beginning portfolio value."""
    v_start = portfolio_value_eur_cents(start_date)
    if v_start == 0:
        return Decimal(0)

    total_dividends = sum(
        d.net_amount_eur_cents
        for d in get_dividends(start_date, end_date)
    )
    return Decimal(total_dividends) / Decimal(v_start)
```

### 10.3 Total Return Decomposition

$$
R_{total} = R_{price} + R_{dividend}
$$

Where:
- $R_{price} = \frac{V_{end} - V_{start}}{V_{start}}$ (capital appreciation)
- $R_{dividend} = \frac{Dividends_{received}}{V_{start}}$ (income return)

Both components are tracked separately in the API response so the UI can display them independently.

---

## 11. Worked Examples

All examples use EUR unless stated otherwise. Monetary values are shown in euros for readability; the system stores cents internally.

### Example 1: Portfolio Valuation — 3 Holdings in EUR and USD

**Scenario:** Portfolio holds three securities across two accounts. EUR/USD rate = 1.0850 (1 EUR = 1.0850 USD). Cash balance of 1,500.00 EUR.

| Security | Account | Qty | Price (native) | Currency |
|----------|---------|-----|----------------|----------|
| Nokia (NOKIA.HE) | Regular | 500 | 4.20 EUR | EUR |
| iShares Core MSCI World (EUNL) | OST | 100 | 82.50 EUR | EUR |
| Apple (AAPL) | Regular | 30 | 178.50 USD | USD |

```
Nokia:
  V = 500 * 4.20 = 2,100.00 EUR

EUNL:
  V = 100 * 82.50 = 8,250.00 EUR

Apple:
  V_usd = 30 * 178.50 = 5,355.00 USD
  V_eur = 5,355.00 / 1.0850 = 4,935.48 EUR

Cash: 1,500.00 EUR

Total portfolio: 2,100.00 + 8,250.00 + 4,935.48 + 1,500.00 = 16,785.48 EUR

In cents: 1,678,548
```

### Example 2: TWR Calculation — Portfolio with a Mid-Period Deposit

**Scenario:**
- Jan 1: Portfolio value = 100,000 EUR
- Mar 31: Portfolio value = 108,000 EUR (before deposit)
- Apr 1: Deposit of 20,000 EUR. Portfolio value after deposit = 128,000 EUR
- Jun 30: Portfolio value = 134,400 EUR

```
Sub-period 1 (Jan 1 - Mar 31):
  HPR_1 = (108,000 - 100,000) / 100,000 = 0.08 (8.0%)

Sub-period 2 (Apr 1 - Jun 30):
  HPR_2 = (134,400 - 128,000) / 128,000 = 0.05 (5.0%)

TWR = (1 + 0.08) * (1 + 0.05) - 1 = 1.08 * 1.05 - 1 = 0.134 (13.4%)

Period = 181 days
Annualized TWR = (1 + 0.134)^(365/181) - 1 = 1.134^2.0166 - 1 = 0.2855 (28.55%)
```

Note: The 20,000 deposit does not inflate the return. TWR correctly measures the investment performance independent of cash flow timing.

### Example 3: XIRR Calculation — Irregular Cash Flows Over 2 Years

**Scenario:** Investor sign convention (deposits negative, withdrawals/final value positive).

| Date | Cash Flow | Description |
|------|-----------|-------------|
| 2024-01-15 | -50,000 EUR | Initial investment |
| 2024-07-01 | -15,000 EUR | Additional deposit |
| 2025-03-01 | +5,000 EUR | Withdrawal |
| 2025-11-01 | -10,000 EUR | Additional deposit |
| 2026-01-15 | +82,000 EUR | Final portfolio value |

```
Find r such that:
  -50,000 * (1+r)^(0/365.25)          = -50,000 * (1+r)^0
  -15,000 * (1+r)^(-168/365.25)        = -15,000 * (1+r)^(-0.4599)
  +5,000  * (1+r)^(-776/365.25)        = +5,000  * (1+r)^(-2.1239)
                                          (wait, let's recalculate days)

Days from first cash flow (2024-01-15):
  2024-01-15:  0 days     -> t = 0
  2024-07-01:  168 days   -> t = 0.4599
  2025-03-01:  411 days   -> t = 1.1252
  2025-11-01:  656 days   -> t = 1.7957
  2026-01-15:  731 days   -> t = 2.0007

NPV(r) = -50,000(1+r)^0 - 15,000(1+r)^(-0.4599) + 5,000(1+r)^(-1.1252)
          - 10,000(1+r)^(-1.7957) + 82,000(1+r)^(-2.0007) = 0

Net invested: 50,000 + 15,000 - 5,000 + 10,000 = 70,000 EUR
Final value: 82,000 EUR
Total gain: 12,000 EUR

Newton's method converges to: r ≈ 0.0876 (8.76% annualized)
```

### Example 4: Unrealized P&L with Multiple Lots at Different Cost Bases

**Scenario:** Investor holds Nokia (NOKIA.HE) in a regular account. Three lots acquired at different times. Current price: 4.80 EUR/share.

| Lot | Acquired | Qty | Purchase Price | Fees | Cost Basis |
|-----|----------|-----|----------------|------|------------|
| A | 2023-03-15 | 200 | 3.50 EUR | 10 EUR | 710.00 EUR |
| B | 2024-01-10 | 150 | 4.20 EUR | 8 EUR | 638.00 EUR |
| C | 2025-06-01 | 100 | 5.10 EUR | 8 EUR | 518.00 EUR |

```
Current market values:
  Lot A: 200 * 4.80 = 960.00 EUR
  Lot B: 150 * 4.80 = 720.00 EUR
  Lot C: 100 * 4.80 = 480.00 EUR

Unrealized P&L per lot:
  Lot A: 960.00 - 710.00 = +250.00 EUR  (+35.2%)
  Lot B: 720.00 - 638.00 = +82.00 EUR   (+12.9%)
  Lot C: 480.00 - 518.00 = -38.00 EUR   (-7.3%)

Holding totals:
  Total market value: 960 + 720 + 480 = 2,160.00 EUR
  Total cost basis:   710 + 638 + 518 = 1,866.00 EUR
  Total unrealized P&L: +294.00 EUR
  Holding P&L %: 294.00 / 1,866.00 * 100 = 15.8%
```

### Example 5: Performance Attribution — Stock vs Bond Contribution

**Scenario:** Portfolio at start of quarter:

| Asset Class | Start Value | End Value | Weight | Return |
|-------------|-------------|-----------|--------|--------|
| Stocks | 80,000 EUR | 86,400 EUR | 64.0% | +8.0% |
| Bonds | 30,000 EUR | 30,600 EUR | 24.0% | +2.0% |
| Crypto | 10,000 EUR | 11,500 EUR | 8.0% | +15.0% |
| Cash | 5,000 EUR | 5,000 EUR | 4.0% | +0.0% |
| **Total** | **125,000 EUR** | **133,500 EUR** | **100%** | **+6.8%** |

```
Attribution (contribution = weight * return):
  Stocks: 0.64 * 0.08 = 0.0512 (5.12%)
  Bonds:  0.24 * 0.02 = 0.0048 (0.48%)
  Crypto: 0.08 * 0.15 = 0.0120 (1.20%)
  Cash:   0.04 * 0.00 = 0.0000 (0.00%)

  Total: 5.12% + 0.48% + 1.20% + 0.00% = 6.80% ✓

Interpretation:
  Stocks contributed 75.3% of total return (5.12 / 6.80)
  Bonds contributed 7.1% of total return
  Crypto contributed 17.6% of total return

Despite being only 8% of the portfolio, crypto's 15% return made it
the second-largest contributor to performance.
```

### Example 6: TWR vs XIRR Divergence

**Scenario:** Demonstrates why TWR and MWWR can differ significantly. Investor deposits heavily right before a market drop.

- Jan 1: Portfolio = 50,000 EUR
- Jun 30: Portfolio = 60,000 EUR (20% gain in H1)
- Jul 1: Investor deposits 200,000 EUR. Portfolio = 260,000 EUR
- Dec 31: Portfolio = 247,000 EUR (5% loss in H2)

```
TWR:
  HPR_1 = (60,000 - 50,000) / 50,000 = +20.0%
  HPR_2 = (247,000 - 260,000) / 260,000 = -5.0%
  TWR = (1.20)(0.95) - 1 = +14.0%

XIRR:
  Cash flows (investor sign convention):
    Jan 1:  -50,000
    Jul 1:  -200,000
    Dec 31: +247,000

  Net invested: 250,000. Final value: 247,000.
  The investor lost 3,000 EUR despite the market returning +14% (TWR).

  XIRR ≈ -1.2% (negative because most capital was deployed before the downturn)

TWR says the portfolio returned +14% (correct investment performance).
XIRR says the investor's actual experience was -1.2% (correct investor return).
This divergence is why both metrics are needed.
```

### Example 7: Multi-Currency P&L with FX Impact

**Scenario:** Investor buys 50 shares of Apple at $150.00 when EUR/USD = 1.1000. Six months later, price is $165.00 and EUR/USD = 1.0500.

```
Purchase:
  Cost in USD: 50 * 150.00 = 7,500.00 USD
  FX rate at purchase: 1 EUR = 1.1000 USD
  Cost in EUR: 7,500.00 / 1.1000 = 6,818.18 EUR

Current value:
  Value in USD: 50 * 165.00 = 8,250.00 USD
  FX rate today: 1 EUR = 1.0500 USD
  Value in EUR: 8,250.00 / 1.0500 = 7,857.14 EUR

Total P&L (EUR): 7,857.14 - 6,818.18 = +1,038.96 EUR (+15.24%)

Decomposition:
  Local return (USD): (165.00 / 150.00) - 1 = +10.00%
  FX return: (1.1000 / 1.0500) - 1 = +4.76%  (USD appreciated vs EUR)
  Cross-term: 0.10 * 0.0476 = +0.48%
  Total: 10.00% + 4.76% + 0.48% = +15.24% ✓

The investor gained 10% from the stock price and an additional ~5%
from USD strengthening against EUR.
```

---

## 12. Edge Cases

1. **Zero portfolio value at inception:** When computing TWR, the first sub-period is skipped until the first deposit creates a non-zero starting value. XIRR starts from the first cash flow naturally.

2. **Simultaneous deposits and market movement on the same day:** The system assumes cash flows occur at the start of the day (before market movement). This is a simplification; in reality, the deposit might arrive mid-day. For daily-level granularity this is acceptable.

3. **Cost basis of zero (gifted shares):** Unrealized P&L percentage returns `None` (displayed as "N/A"). Unrealized P&L in absolute terms is simply the full market value. For realized P&L, the full proceeds are taxable gain (or the deemed cost of acquisition may apply per Finnish rules).

4. **Negative cash balance:** An account may temporarily show a negative cash balance between trade execution and settlement (T+2). The system includes this negative cash in account/portfolio valuation. It should not trigger errors.

5. **Security with no price history:** Newly added securities or delisted securities with no price data. The holding is flagged as `price_missing`, its last known value is used if available, and it is excluded from weight and return calculations until a price is available.

6. **FX rate unavailable for a currency pair:** If the ECB does not publish a rate for an exotic currency, the system raises an `FxRateMissingError`. For MVP, only major currencies (USD, GBP, SEK, NOK, DKK, CHF, JPY, CAD, AUD) are supported.

7. **Corporate action mid-period:** A stock split changes quantity and price but not market value. The daily return on the split date should be zero (or near-zero) since $V_{pre-split} \approx V_{post-split}$. The system uses adjusted prices from the `prices.adjusted_close_cents` column to compute returns across split boundaries.

8. **Multiple accounts holding the same security:** Portfolio-level P&L for a security aggregates across all accounts. Per-account P&L is computed independently. Tax calculations are always per-account (since account type determines tax treatment).

9. **Crypto 24/7 markets:** Crypto prices are available every day including weekends. The daily return series for crypto does not skip weekends. For mixed portfolios, weekend returns only reflect crypto and FX movements (stock/bond prices are unchanged from Friday close).

10. **Dividend reinvested (DRIP) on the same day:** A dividend payment and its reinvestment create a cash inflow and outflow that net to zero for TWR purposes. The dividend is still counted in dividend return contribution. The new purchase creates a new tax lot.

11. **Transfer between own accounts:** An in-kind transfer (e.g., moving shares from regular account to OST) is not an external cash flow and does not affect TWR or XIRR at the portfolio level. At the account level, it appears as a transfer_out and transfer_in that cancel out. Cost basis and acquisition date transfer with the shares.

12. **Rounding accumulation:** When computing portfolio-level values by summing many cent-denominated holdings, rounding errors can accumulate. The system rounds each holding value to the nearest cent, then sums. This is acceptable since the maximum error is bounded by the number of holdings (e.g., 50 holdings means at most 25 cents of rounding error).

---

## Open Questions

1. **Benchmark selection:** Which benchmarks should be used for Brinson attribution? Candidates: MSCI World (for equities), Bloomberg Euro Aggregate (for bonds), a custom blended benchmark matching the glidepath target allocation.

2. **Intraday cash flow timing:** The current spec assumes cash flows occur at start of day. Should we support intraday timing for more accurate TWR on days with large deposits?

3. **Performance fee impact:** If the investor uses managed funds with performance fees, should these be separated in attribution?

---

## Changelog

| Date | Change |
|------|--------|
| 2026-03-19 | Initial draft — DRAFT status |
