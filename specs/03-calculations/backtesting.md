# Backtesting Engine

Historical simulation engine for evaluating investment strategies against actual market data. Unlike Monte Carlo (which models probabilistic future outcomes), the backtesting engine replays real historical prices, dividends, FX rates, and transaction costs to answer: "How would this strategy have performed?" It supports strategy comparison, what-if analysis, rolling window analysis, and parameter sensitivity testing. All computations are server-side in Python; the frontend is display-only.

**Status: DRAFT**

## Dependencies

- [Spec Conventions](../00-meta/spec-conventions.md) — monetary values in cents, date handling, `Decimal` policy
- [Data Model](../01-system/data-model.md) — `prices`, `fx_rates`, `dividends`, `securities` hypertables and tables
- [Glidepath](../03-calculations/glidepath.md) — target allocation at each age, anchor points, interpolation, rebalancing logic
- [Portfolio Math](../03-calculations/portfolio-math.md) — TWR, XIRR, daily return series, FX conversion
- [Risk Metrics](../03-calculations/risk-metrics.md) — Sharpe, Sortino, max drawdown, Calmar, volatility
- [Finnish Tax](../03-calculations/tax-finnish.md) — capital gains rates (30%/34%), deemed cost of acquisition, OST rules, dividend taxation, loss carry-forward

---

## 1. Strategy Definition

A backtestable strategy is a JSON configuration object that fully specifies the portfolio rules. All strategies are stored and versioned so results are reproducible.

### 1.1 Strategy Schema

```json
{
  "name": "Munger-Boglehead Hybrid v1",
  "description": "60-70% index core, 30-40% conviction satellite, 15-year glidepath",
  "startDate": "2011-03-21",
  "endDate": "2026-03-21",
  "initialCapitalCents": 20000000,
  "contribution": {
    "monthlyCents": 200000,
    "annualGrowthRate": 0.02,
    "startDate": "2011-04-01"
  },
  "withdrawal": {
    "enabled": false,
    "monthlyCents": 0,
    "startDate": null,
    "inflationAdjusted": true
  },
  "allocation": {
    "mode": "glidepath",
    "glidepathAnchorAge": 45,
    "birthDate": "1981-03-19",
    "fixedWeights": null
  },
  "rebalancing": {
    "frequency": "quarterly",
    "driftThresholdPct": 5.0,
    "driftTriggered": true
  },
  "securities": {
    "core": [
      { "ticker": "IWDA.AS", "targetWeightOfEquity": 0.65, "role": "core_etf" }
    ],
    "satellite": [
      { "ticker": "NOKIA.HE", "targetWeightOfEquity": 0.10, "role": "satellite_stock" },
      { "ticker": "SAMPO.HE", "targetWeightOfEquity": 0.10, "role": "satellite_stock" },
      { "ticker": "AAPL", "targetWeightOfEquity": 0.15, "role": "satellite_stock" }
    ],
    "fixedIncome": [
      { "ticker": "VGEA.DE", "targetWeightOfFI": 1.0, "role": "bond_etf" }
    ],
    "crypto": [
      { "ticker": "BTC", "targetWeightOfCrypto": 1.0, "role": "crypto" }
    ]
  },
  "accountRouting": {
    "osakesaastotili": {
      "enabled": true,
      "depositLimitCents": 5000000,
      "eligibleSecurities": ["IWDA.AS", "NOKIA.HE", "SAMPO.HE"],
      "priority": "satellite_first"
    },
    "regular": {
      "securities": ["AAPL", "VGEA.DE", "BTC"]
    }
  },
  "costs": {
    "transactionFees": {
      "helsinki": 0.001,
      "stockholm": 0.0015,
      "us": { "fixedCents": 1500, "percentageFee": 0.0 },
      "etf_europe": 0.001,
      "crypto": 0.001
    },
    "slippage": {
      "etf": 0.0,
      "largeCapStock": 0.0005,
      "smallCapStock": 0.001,
      "crypto": 0.001
    }
  },
  "dividendReinvestment": {
    "enabled": true,
    "reinvestInSameSecurity": true,
    "taxOnDividends": true
  },
  "taxSimulation": {
    "enabled": true,
    "capitalGainsRateLow": 0.30,
    "capitalGainsRateHigh": 0.34,
    "highRateThresholdCents": 3000000,
    "deemedCostEnabled": true,
    "lossCarryForwardYears": 5,
    "dividendTaxation": {
      "finnishListed": { "taxablePortion": 0.85, "rate": 0.30 },
      "foreign": { "taxablePortion": 1.0, "rate": 0.30, "withholdingCreditEnabled": true }
    }
  }
}
```

### 1.2 Rebalancing Modes

| Mode | Description |
|------|-------------|
| `monthly` | Rebalance on the first trading day of each month |
| `quarterly` | Rebalance on the first trading day of each quarter |
| `annually` | Rebalance on the first trading day of each year |
| `drift_triggered` | Rebalance only when any asset class drifts beyond `driftThresholdPct` from target |
| `combined` | Rebalance at the frequency OR when drift is triggered, whichever comes first |

### 1.3 Account Routing Logic

Trades are routed to accounts following these rules:

1. **Osakesaastotili first** for eligible equity securities (tax-free internal trading)
2. If OST deposit limit is reached, overflow to regular account
3. Fixed income, crypto, and ineligible securities always go to regular account
4. Sells from OST are preferred when reducing equity (avoids triggering capital gains tax)

```python
def route_trade(
    security: Security,
    action: str,  # "buy" or "sell"
    ost_deposits_cents: int,
    ost_deposit_limit_cents: int,
    ost_eligible: list[str],
) -> str:
    """Returns account type: 'osakesaastotili' or 'regular'."""
    if security.ticker not in ost_eligible:
        return "regular"
    if action == "sell":
        return "osakesaastotili"  # prefer tax-free sells
    if ost_deposits_cents >= ost_deposit_limit_cents:
        return "regular"
    return "osakesaastotili"
```

---

## 2. Historical Simulation Engine

### 2.1 Simulation Loop

The engine steps through each trading day in the backtest period, processing events in a deterministic order.

**Daily event processing order:**

1. Update prices and FX rates from the `prices` and `fx_rates` hypertables
2. Process any dividends payable on this date (ex-date lookup)
3. Process any corporate actions (splits)
4. Check if a contribution is due (monthly schedule)
5. Check if rebalancing is triggered (schedule or drift)
6. Execute rebalancing trades with transaction costs and slippage
7. Record end-of-day portfolio snapshot

### 2.2 Core Simulation Pseudocode

```python
from decimal import Decimal, ROUND_HALF_UP
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

@dataclass
class BacktestState:
    date: date
    positions: dict[str, dict]  # {ticker: {quantity: Decimal, lots: list[TaxLot]}}
    cash_cents: dict[str, int]  # {account_type: cash_balance_cents}
    ost_deposits_cents: int = 0
    realized_gains_by_year: dict[int, int] = field(default_factory=dict)
    realized_losses_by_year: dict[int, int] = field(default_factory=dict)
    loss_carryforward: dict[int, int] = field(default_factory=dict)  # {year: remaining_loss_cents}
    total_taxes_paid_cents: int = 0
    total_dividends_received_cents: int = 0
    total_contributions_cents: int = 0
    snapshots: list[dict] = field(default_factory=list)

@dataclass
class TaxLot:
    security_ticker: str
    account_type: str
    quantity: Decimal
    remaining_quantity: Decimal
    cost_basis_cents: int  # total cost including fees, in EUR
    acquisition_date: date
    fx_rate_at_open: Decimal

def run_backtest(strategy: dict) -> BacktestResult:
    """Main backtest loop. Returns complete results."""
    state = initialize_state(strategy)
    trading_days = get_trading_days(strategy["startDate"], strategy["endDate"])

    for day in trading_days:
        state.date = day

        # 1. Fetch prices and FX rates
        prices = get_historical_prices(day, strategy["securities"])
        fx_rates = get_historical_fx_rates(day)

        # 2. Process dividends
        dividends = get_dividends_for_date(day, list(state.positions.keys()))
        for div in dividends:
            process_dividend(state, div, fx_rates, strategy)

        # 3. Process corporate actions (splits)
        splits = get_splits_for_date(day, list(state.positions.keys()))
        for split in splits:
            apply_split(state, split)

        # 4. Monthly contribution
        if is_contribution_date(day, strategy["contribution"]):
            contribution_cents = compute_contribution(
                strategy["contribution"], day, strategy["startDate"]
            )
            state.cash_cents["regular"] += contribution_cents
            state.total_contributions_cents += contribution_cents

        # 5. Check rebalancing trigger
        portfolio_value = compute_portfolio_value(state, prices, fx_rates)
        current_weights = compute_current_weights(state, prices, fx_rates)
        target_weights = compute_target_weights(state.date, strategy["allocation"])

        needs_rebalance = check_rebalance_trigger(
            day, current_weights, target_weights, strategy["rebalancing"]
        )

        # 6. Execute rebalancing trades
        if needs_rebalance:
            trades = generate_rebalance_trades(
                state, current_weights, target_weights,
                portfolio_value, prices, fx_rates, strategy
            )
            for trade in trades:
                execute_trade(state, trade, prices, fx_rates, strategy)

        # 7. Record daily snapshot
        snapshot = record_snapshot(state, prices, fx_rates, portfolio_value)
        state.snapshots.append(snapshot)

    return compile_results(state, strategy)
```

### 2.3 FX Conversion

All portfolio values are computed in EUR. Foreign-denominated securities use the historical FX rate from the `fx_rates` table.

```python
def convert_to_eur_cents(
    amount_foreign_cents: int,
    currency: str,
    fx_rates: dict[str, Decimal],  # {"USD": Decimal("1.0850"), ...} — 1 EUR = X foreign
) -> int:
    """Convert foreign currency amount to EUR cents."""
    if currency == "EUR":
        return amount_foreign_cents
    rate = fx_rates.get(currency)
    if rate is None:
        raise FxRateMissingError(f"No FX rate for EUR/{currency}")
    eur_value = Decimal(amount_foreign_cents) / rate
    return int(eur_value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
```

### 2.4 Transaction Cost Model

| Market | Fee Model | Example on 10,000 EUR trade |
|--------|-----------|---------------------------|
| Helsinki (Nasdaq Helsinki) | 0.10% of trade value | 10.00 EUR |
| Stockholm (Nasdaq Stockholm) | 0.15% of trade value | 15.00 EUR |
| US (NYSE/NASDAQ) | Fixed 15.00 EUR per trade | 15.00 EUR |
| European ETFs (Xetra, Euronext) | 0.10% of trade value | 10.00 EUR |
| Crypto exchanges | 0.10% of trade value | 10.00 EUR |

```python
def compute_transaction_cost_cents(
    trade_value_cents: int,
    market: str,
    fee_config: dict,
) -> int:
    """Compute transaction cost in EUR cents."""
    if market == "us":
        return fee_config["us"]["fixedCents"]
    pct = fee_config.get(market, 0.001)
    return int(Decimal(trade_value_cents) * Decimal(str(pct)))
```

### 2.5 Slippage Model

Slippage models the difference between the theoretical price and the actual execution price. For a backtest, it is modeled as a percentage deducted from sell proceeds and added to buy costs.

```python
def apply_slippage(
    price_cents: int,
    action: str,  # "buy" or "sell"
    security_type: str,
    slippage_config: dict,
) -> int:
    """Adjust price for slippage. Returns adjusted price in cents."""
    slippage_pct = slippage_config.get(security_type, 0.0)
    if slippage_pct == 0:
        return price_cents
    adjustment = Decimal(price_cents) * Decimal(str(slippage_pct))
    if action == "buy":
        return int((Decimal(price_cents) + adjustment).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    else:  # sell
        return int((Decimal(price_cents) - adjustment).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
```

### 2.6 Dividend Processing

```python
def process_dividend(
    state: BacktestState,
    dividend: DividendRecord,
    fx_rates: dict[str, Decimal],
    strategy: dict,
) -> None:
    """Process a dividend payment: tax, credit to cash, optional reinvestment."""
    position = state.positions.get(dividend.ticker)
    if position is None or position["quantity"] == 0:
        return

    gross_eur_cents = convert_to_eur_cents(
        int(position["quantity"] * dividend.per_share_cents),
        dividend.currency,
        fx_rates,
    )

    # Determine account type for this holding
    account_type = get_account_type_for_ticker(state, dividend.ticker)

    # Tax calculation
    tax_cents = 0
    if strategy["taxSimulation"]["enabled"] and account_type != "osakesaastotili":
        tax_config = strategy["taxSimulation"]["dividendTaxation"]
        if dividend.country == "FI" and dividend.is_listed:
            taxable = int(Decimal(gross_eur_cents) * Decimal("0.85"))
        else:
            taxable = gross_eur_cents
            # Apply withholding tax credit for foreign dividends
            if tax_config["foreign"]["withholdingCreditEnabled"]:
                withholding_cents = int(
                    Decimal(gross_eur_cents) * Decimal(str(dividend.withholding_rate))
                )
                finnish_tax = int(Decimal(taxable) * Decimal("0.30"))
                credit = min(withholding_cents, finnish_tax)
                tax_cents = finnish_tax - credit
            else:
                tax_cents = int(Decimal(taxable) * Decimal("0.30"))
        if tax_cents == 0:
            tax_cents = int(Decimal(taxable) * Decimal("0.30"))

    net_cents = gross_eur_cents - tax_cents
    state.cash_cents[account_type] += net_cents
    state.total_dividends_received_cents += gross_eur_cents
    state.total_taxes_paid_cents += tax_cents

    # Dividend reinvestment
    if strategy["dividendReinvestment"]["enabled"]:
        # Reinvest on the next trading day (handled in the main loop)
        state.pending_reinvestments.append({
            "ticker": dividend.ticker,
            "amount_cents": net_cents,
            "account_type": account_type,
        })
```

### 2.7 Corporate Actions (Splits)

```python
def apply_split(state: BacktestState, split: SplitRecord) -> None:
    """Adjust position quantity and lot cost basis for a stock split."""
    position = state.positions.get(split.ticker)
    if position is None:
        return

    # split.ratio: e.g., 4.0 for a 4:1 split
    position["quantity"] *= Decimal(str(split.ratio))
    for lot in position["lots"]:
        lot.quantity *= Decimal(str(split.ratio))
        lot.remaining_quantity *= Decimal(str(split.ratio))
        # Cost basis stays the same (total cost unchanged), per-share cost decreases
```

### 2.8 Tax Simulation on Realized Gains

```python
def compute_realized_tax(
    state: BacktestState,
    gain_cents: int,
    lot: TaxLot,
    proceeds_cents: int,
    strategy: dict,
) -> int:
    """Compute tax on a realized gain, applying Finnish tax rules."""
    if lot.account_type == "osakesaastotili":
        return 0  # No tax on internal OST trades

    if gain_cents <= 0:
        # Loss: no tax, record for carry-forward
        year = state.date.year
        state.realized_losses_by_year[year] = (
            state.realized_losses_by_year.get(year, 0) + abs(gain_cents)
        )
        return 0

    # Check deemed cost of acquisition
    taxable_gain = gain_cents
    if strategy["taxSimulation"]["deemedCostEnabled"]:
        holding_days = (state.date - lot.acquisition_date).days
        if holding_days >= 3652:  # ~10 years
            deemed_gain = int(Decimal(proceeds_cents) * Decimal("0.60"))
        else:
            deemed_gain = int(Decimal(proceeds_cents) * Decimal("0.80"))
        taxable_gain = min(gain_cents, deemed_gain)

    # Apply carry-forward losses
    taxable_gain = apply_loss_carryforward(state, taxable_gain)

    # Determine tax rate based on cumulative gains this year
    year = state.date.year
    ytd_gains = state.realized_gains_by_year.get(year, 0)
    threshold = strategy["taxSimulation"]["highRateThresholdCents"]

    if ytd_gains + taxable_gain <= threshold:
        tax = int(Decimal(taxable_gain) * Decimal("0.30"))
    else:
        low_bracket = max(0, threshold - ytd_gains)
        high_bracket = taxable_gain - low_bracket
        tax = (
            int(Decimal(low_bracket) * Decimal("0.30"))
            + int(Decimal(high_bracket) * Decimal("0.34"))
        )

    state.realized_gains_by_year[year] = ytd_gains + taxable_gain
    return tax

def apply_loss_carryforward(state: BacktestState, gain_cents: int) -> int:
    """Apply carried-forward losses to reduce taxable gain. FIFO by year."""
    remaining_gain = gain_cents
    current_year = state.date.year
    for year in sorted(state.loss_carryforward.keys()):
        if current_year - year > 5:
            del state.loss_carryforward[year]  # expired
            continue
        if remaining_gain <= 0:
            break
        available = state.loss_carryforward[year]
        offset = min(available, remaining_gain)
        remaining_gain -= offset
        state.loss_carryforward[year] -= offset
        if state.loss_carryforward[year] == 0:
            del state.loss_carryforward[year]
    return max(remaining_gain, 0)
```

---

## 3. Performance Metrics

Computed from the backtest result's daily snapshot series. All formulas reference the math defined in [Portfolio Math](../03-calculations/portfolio-math.md) and [Risk Metrics](../03-calculations/risk-metrics.md).

### 3.1 Total Return (Nominal)

$$
R_{total} = \frac{V_{end} - V_{start} - C_{total} + W_{total}}{V_{start} + C_{total,weighted}}
$$

Where:
- $V_{end}$ = final portfolio value
- $V_{start}$ = initial capital
- $C_{total}$ = sum of all contributions
- $W_{total}$ = sum of all withdrawals
- $C_{total,weighted}$ = time-weighted contributions (contributions made earlier have more weight)

For backtests, we use TWR (see Portfolio Math Section 5) to eliminate cash flow timing effects.

### 3.2 Total Return (Real, After Inflation)

$$
R_{real} = \frac{1 + R_{nominal}}{1 + \pi} - 1
$$

Where $\pi$ is cumulative inflation over the backtest period. Inflation data is sourced from FRED CPI or Eurostat HICP for EUR.

**Python pseudocode:**

```python
def real_return(nominal_return: Decimal, inflation_cumulative: Decimal) -> Decimal:
    return (1 + nominal_return) / (1 + inflation_cumulative) - 1
```

### 3.3 CAGR (Compound Annual Growth Rate)

$$
CAGR = \left(\frac{V_{end}}{V_{start}}\right)^{1/n} - 1
$$

Where $n$ = number of years in the backtest period.

```python
def cagr(start_value_cents: int, end_value_cents: int, years: Decimal) -> Decimal:
    if start_value_cents <= 0 or years <= 0:
        return Decimal(0)
    return (Decimal(end_value_cents) / Decimal(start_value_cents)) ** (1 / years) - 1
```

### 3.4 Sharpe Ratio

$$
\text{Sharpe} = \frac{\bar{r}_{daily} - r_{f,daily}}{\sigma_{daily}} \times \sqrt{252}
$$

Uses the daily return series from the backtest snapshots and the historical ECB deposit facility rate as the risk-free rate.

### 3.5 Sortino Ratio

$$
\text{Sortino} = \frac{\bar{r}_{daily} - r_{f,daily}}{\sigma_{downside}} \times \sqrt{252}
$$

Where $\sigma_{downside} = \sqrt{\frac{1}{n} \sum \min(r_i - r_f, 0)^2}$.

### 3.6 Maximum Drawdown

$$
\text{MDD} = \max_t \left(\frac{\text{Peak}_t - V_t}{\text{Peak}_t}\right)
$$

Returns both the drawdown percentage and the peak/trough/recovery dates.

```python
@dataclass
class DrawdownInfo:
    drawdown_pct: Decimal
    peak_date: date
    peak_value_cents: int
    trough_date: date
    trough_value_cents: int
    recovery_date: Optional[date]
    recovery_days: Optional[int]
```

### 3.7 Calmar Ratio

$$
\text{Calmar} = \frac{CAGR}{\text{MDD}}
$$

### 3.8 Win Rate

$$
\text{WinRate} = \frac{\text{Years with positive return}}{\text{Total full calendar years}}
$$

```python
def win_rate(annual_returns: list[Decimal]) -> Decimal:
    if not annual_returns:
        return Decimal(0)
    positive_years = sum(1 for r in annual_returns if r > 0)
    return Decimal(positive_years) / Decimal(len(annual_returns))
```

### 3.9 Best/Worst Year

```python
def best_worst_year(
    annual_returns: dict[int, Decimal],  # {year: return}
) -> tuple[tuple[int, Decimal], tuple[int, Decimal]]:
    best = max(annual_returns.items(), key=lambda x: x[1])
    worst = min(annual_returns.items(), key=lambda x: x[1])
    return best, worst
```

### 3.10 Underwater Chart

Time series showing how far below the previous all-time high the portfolio is at each point.

$$
\text{Underwater}_t = \frac{V_t - \text{Peak}_t}{\text{Peak}_t}
$$

This is always $\leq 0$. The series returns to 0 when a new ATH is reached.

```python
def underwater_series(
    portfolio_values: list[int],  # daily values in cents
    dates: list[date],
) -> list[tuple[date, Decimal]]:
    running_peak = 0
    result = []
    for d, v in zip(dates, portfolio_values):
        running_peak = max(running_peak, v)
        underwater = Decimal(v - running_peak) / Decimal(running_peak) if running_peak > 0 else Decimal(0)
        result.append((d, underwater))
    return result
```

### 3.11 Tax Drag

Total taxes paid (capital gains + dividend withholding) as a percentage of total return.

$$
\text{TaxDrag} = \frac{\text{Total taxes paid}}{V_{end} - V_{start} - C_{total} + W_{total}}
$$

```python
def tax_drag(
    total_taxes_cents: int,
    total_return_cents: int,  # end_value - start_value - contributions + withdrawals
) -> Decimal:
    if total_return_cents <= 0:
        return Decimal(0)
    return Decimal(total_taxes_cents) / Decimal(total_return_cents)
```

---

## 4. Strategy Comparison

Run multiple strategies over the same historical period and compare them side-by-side.

### 4.1 Comparison Metrics Table

| Metric | Strategy A | Strategy B | Strategy C |
|--------|-----------|-----------|-----------|
| Total Return (nominal) | — | — | — |
| Total Return (real) | — | — | — |
| CAGR | — | — | — |
| Sharpe Ratio | — | — | — |
| Sortino Ratio | — | — | — |
| Max Drawdown | — | — | — |
| Calmar Ratio | — | — | — |
| Win Rate | — | — | — |
| Best Year | — | — | — |
| Worst Year | — | — | — |
| Tax Drag | — | — | — |
| Final Value (EUR) | — | — | — |

### 4.2 Overlay Equity Curves

Each strategy produces a daily value series (the snapshots). The API returns all series normalized to a starting value of 10,000 for visual comparison.

```python
def normalize_equity_curve(
    snapshots: list[dict],  # [{date, portfolio_value_cents}, ...]
    base: int = 1000000,    # 10,000.00 EUR in cents
) -> list[dict]:
    start_value = snapshots[0]["portfolio_value_cents"]
    return [
        {
            "date": s["date"],
            "normalizedValue": int(Decimal(s["portfolio_value_cents"]) / Decimal(start_value) * base),
        }
        for s in snapshots
    ]
```

### 4.3 Statistical Significance Test

To determine whether the return difference between two strategies is statistically significant, use a paired t-test on their monthly return series.

$$
t = \frac{\bar{d}}{s_d / \sqrt{n}}
$$

Where:
- $\bar{d}$ = mean of monthly return differences $(r_{A,i} - r_{B,i})$
- $s_d$ = standard deviation of the differences
- $n$ = number of monthly observations

```python
from scipy import stats

def return_difference_significance(
    monthly_returns_a: np.ndarray,
    monthly_returns_b: np.ndarray,
    significance_level: float = 0.05,
) -> dict:
    """Paired t-test on monthly return differences."""
    differences = monthly_returns_a - monthly_returns_b
    t_stat, p_value = stats.ttest_rel(monthly_returns_a, monthly_returns_b)
    return {
        "meanDifference": float(np.mean(differences)),
        "tStatistic": float(t_stat),
        "pValue": float(p_value),
        "significant": p_value < significance_level,
        "confidenceLevel": 1 - significance_level,
    }
```

**Bootstrap alternative** (for non-normal return distributions):

```python
def bootstrap_return_difference(
    monthly_returns_a: np.ndarray,
    monthly_returns_b: np.ndarray,
    n_bootstrap: int = 10000,
) -> dict:
    """Bootstrap confidence interval for return difference."""
    differences = monthly_returns_a - monthly_returns_b
    observed_mean = np.mean(differences)

    bootstrap_means = np.array([
        np.mean(np.random.choice(differences, size=len(differences), replace=True))
        for _ in range(n_bootstrap)
    ])

    ci_lower = float(np.percentile(bootstrap_means, 2.5))
    ci_upper = float(np.percentile(bootstrap_means, 97.5))

    return {
        "observedMeanDifference": float(observed_mean),
        "ci95Lower": ci_lower,
        "ci95Upper": ci_upper,
        "significant": ci_lower > 0 or ci_upper < 0,  # CI does not contain zero
    }
```

---

## 5. What-If Analysis

Modify a single parameter from the baseline strategy and observe the impact on final portfolio value and key metrics.

### 5.1 Predefined What-If Scenarios

| Scenario | Parameter Changed | Range |
|----------|------------------|-------|
| Earlier start | `startDate` shifted backward | 1, 3, 5, 10 years earlier |
| Later start | `startDate` shifted forward | 1, 3, 5 years later |
| Higher bond allocation | Fixed income weight | +5%, +10%, +15%, +20% |
| Lower bond allocation | Fixed income weight | -5%, -10% |
| Different rebalancing frequency | `rebalancing.frequency` | monthly, quarterly, annually, drift-only |
| Higher contributions | `contribution.monthlyCents` | 1.5x, 2x baseline |
| No crypto allocation | Crypto weight set to 0% | Redistributed to equities/FI |
| Tax-optimized | All equities in OST | Compare to baseline routing |

### 5.2 Parameter Sensitivity

Vary one input continuously and plot the impact on the output.

```python
def parameter_sensitivity(
    baseline_strategy: dict,
    parameter_path: str,        # e.g., "allocation.fixedWeights.equities"
    values: list[float],        # e.g., [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80]
    output_metric: str,         # e.g., "finalValueCents", "cagr", "maxDrawdown"
) -> list[dict]:
    """Run backtest for each parameter value, return metric for each."""
    results = []
    for v in values:
        modified = deep_copy_and_set(baseline_strategy, parameter_path, v)
        backtest_result = run_backtest(modified)
        results.append({
            "parameterValue": v,
            "outputValue": getattr(backtest_result.metrics, output_metric),
        })
    return results
```

---

## 6. Rolling Backtest

Sliding window analysis to understand how the strategy performs across different market regimes.

### 6.1 Rolling Window Analysis

For a given window length (e.g., 10 years), slide the window across all available historical data and compute metrics for each window.

$$
\text{For each window } [t, t + W]:
$$
$$
\text{CAGR}_t = \left(\frac{V_{t+W}}{V_t}\right)^{1/(W/252)} - 1
$$

```python
def rolling_backtest(
    strategy: dict,
    window_years: int,          # e.g., 5, 10, or 15
    step_months: int = 1,       # slide by 1 month at a time
) -> list[dict]:
    """Run the strategy over every possible window of the given length."""
    results = []
    earliest = get_earliest_data_date(strategy["securities"])
    latest = date.today()

    window_start = earliest
    while True:
        window_end = window_start + timedelta(days=int(window_years * 365.25))
        if window_end > latest:
            break

        modified = copy_strategy_with_dates(strategy, window_start, window_end)
        result = run_backtest(modified)

        results.append({
            "windowStart": window_start.isoformat(),
            "windowEnd": window_end.isoformat(),
            "cagr": result.metrics.cagr,
            "totalReturn": result.metrics.total_return_nominal,
            "maxDrawdown": result.metrics.max_drawdown.drawdown_pct,
            "sharpe": result.metrics.sharpe_ratio,
            "finalValueCents": result.final_value_cents,
        })

        # Advance by step_months
        window_start = add_months(window_start, step_months)

    return results
```

### 6.2 Distribution of Outcomes

From the rolling backtest results, compute the distribution statistics.

```python
def rolling_distribution(
    rolling_results: list[dict],
    metric: str = "cagr",
) -> dict:
    values = [r[metric] for r in rolling_results]
    return {
        "metric": metric,
        "count": len(values),
        "min": float(np.min(values)),
        "p5": float(np.percentile(values, 5)),
        "p25": float(np.percentile(values, 25)),
        "median": float(np.median(values)),
        "p75": float(np.percentile(values, 75)),
        "p95": float(np.percentile(values, 95)),
        "max": float(np.max(values)),
        "mean": float(np.mean(values)),
        "std": float(np.std(values)),
    }
```

### 6.3 Sequence-of-Returns Risk

Identifies how the order of returns affects outcomes, particularly for the withdrawal phase.

```python
def sequence_risk_analysis(
    rolling_results: list[dict],
    window_years: int,
) -> dict:
    """Analyze how starting date affects outcomes."""
    cagrs = [r["cagr"] for r in rolling_results]
    drawdowns = [r["maxDrawdown"] for r in rolling_results]

    # Find the worst starting periods
    worst_starts = sorted(rolling_results, key=lambda r: r["cagr"])[:5]
    best_starts = sorted(rolling_results, key=lambda r: r["cagr"], reverse=True)[:5]

    return {
        "windowYears": window_years,
        "totalWindows": len(rolling_results),
        "positiveReturnPct": float(np.mean([1 for c in cagrs if c > 0]) / len(cagrs)),
        "worstStartingPeriods": worst_starts,
        "bestStartingPeriods": best_starts,
        "cagr_distribution": rolling_distribution(rolling_results, "cagr"),
        "drawdown_distribution": rolling_distribution(rolling_results, "maxDrawdown"),
    }
```

---

## 7. Worked Examples

All examples use EUR. Monetary values shown in euros for readability; the system stores cents internally.

### Example 1: Basic 15-Year Glidepath Backtest

**Scenario:** Backtest from 2011-03-21 to 2026-03-21. Start with 200,000 EUR, contribute 2,000 EUR/month (2% annual growth). 65% IWDA.AS / 35% satellite stocks. Quarterly rebalancing. Tax simulation enabled.

```
Initial portfolio: 200,000.00 EUR
Total contributions over 15 years:
  Year 1:  2,000 * 12 = 24,000
  Year 2:  2,040 * 12 = 24,480  (2% growth)
  ...
  Year 15: 2,000 * (1.02^14) * 12 = 31,612

Total contributed: ~425,000 EUR (sum of geometric series)
Starting capital: 200,000 EUR
Total invested: ~625,000 EUR

Backtest results (illustrative):
  Final portfolio value:    1,420,000 EUR
  Total return (nominal):   127.2% (on total invested)
  CAGR:                     8.1%
  Sharpe ratio:             0.62
  Sortino ratio:            0.89
  Max drawdown:             -28.4% (Feb 2020 - Mar 2020, COVID crash)
  Max drawdown recovery:    147 days
  Calmar ratio:             0.285
  Win rate:                 80% (12 of 15 full calendar years positive)
  Best year:                +24.3% (2019)
  Worst year:               -14.8% (2022)

  Total dividends received: 48,200 EUR
  Total taxes paid:         32,100 EUR
  Tax drag:                 4.0% of total return

  Final allocation:
    Equities:     52% (target at age 60: 30%)
    Fixed income: 38% (target: 60%)
    Crypto:       4%  (target: 2%)
    Cash:         6%  (target: 8%)
    Note: drift present because glidepath shifted targets during the backtest
```

### Example 2: Strategy Comparison — Quarterly vs Annual Rebalancing

**Scenario:** Same baseline as Example 1, but compare quarterly vs annual rebalancing.

```
Strategy A: Quarterly rebalancing
  CAGR:          8.1%
  Sharpe:        0.62
  Max drawdown:  -28.4%
  Taxes paid:    32,100 EUR
  Final value:   1,420,000 EUR

Strategy B: Annual rebalancing
  CAGR:          8.3%
  Sharpe:        0.60
  Max drawdown:  -31.2%
  Taxes paid:    28,500 EUR
  Final value:   1,445,000 EUR

Difference:
  CAGR: +0.2% for annual (less tax drag from fewer trades)
  Max drawdown: -2.8% worse for annual (drift accumulates between rebalances)
  Tax saved: 3,600 EUR with annual rebalancing

Paired t-test on monthly returns:
  Mean difference: 0.017%/month
  t-statistic: 0.84
  p-value: 0.401
  Significant at 95%: No

Conclusion: The return difference is NOT statistically significant.
Annual rebalancing saves on taxes but tolerates more drift.
```

### Example 3: What-If — Started 5 Years Earlier

**Scenario:** Shift start date from 2011-03-21 to 2006-03-21 (captures the 2008 GFC).

```
Original (2011-2026):
  Total invested: 625,000 EUR
  Final value:    1,420,000 EUR
  CAGR:           8.1%

What-if (2006-2026, 20 years):
  Total invested: 825,000 EUR (5 more years of contributions)
  Final value:    2,180,000 EUR
  CAGR:           7.2% (lower CAGR due to 2008 crash, but higher absolute value)
  Max drawdown:   -48.2% (Oct 2007 - Mar 2009)

  The extra 5 years of contributions during the 2008-2011 recovery period
  bought assets at depressed prices, contributing significantly to the higher
  final value despite the lower CAGR.

  Additional value from starting 5 years earlier: +760,000 EUR
  Of which:
    Additional contributions: ~200,000 EUR
    Compound growth on those contributions: ~560,000 EUR
```

### Example 4: Rolling 10-Year Window Analysis

**Scenario:** Run the glidepath strategy over every possible 10-year window from 2001-2026.

```
Total windows analyzed: 180 (one per month from 2001 to 2016)

CAGR distribution:
  Worst 10-year CAGR:   2.1% (started Oct 2000, includes dot-com bust + GFC)
  5th percentile:       3.8%
  25th percentile:      5.9%
  Median:               7.4%
  75th percentile:      9.2%
  95th percentile:      11.1%
  Best 10-year CAGR:    12.8% (started Mar 2009, bought at the bottom)

Probability of positive 10-year return: 100% (no 10-year window lost money)

Max drawdown distribution:
  Median max drawdown:  -22.5%
  Worst max drawdown:   -48.2% (window starting 2005, capturing full GFC)

Worst 5 starting months for CAGR:
  1. Oct 2000: 2.1%  (dot-com peak)
  2. Nov 2000: 2.3%
  3. Sep 2000: 2.5%
  4. Mar 2001: 2.8%
  5. Aug 2000: 3.0%

All worst starting periods clustered around the dot-com peak.
```

### Example 5: Tax Drag Comparison — OST vs Regular Account

**Scenario:** 50,000 EUR invested in IWDA.AS for 10 years. Compare osakesaastotili routing vs regular account.

```
OST Account:
  All trades inside OST: 0 EUR tax during accumulation
  Final value: 97,200 EUR
  On withdrawal: gains_ratio = (97,200 - 50,000) / 97,200 = 48.56%
  Tax on full withdrawal: 47,200 * 30% = 14,160 EUR
  After-tax value: 83,040 EUR

Regular Account:
  Dividend tax each year (IWDA is accumulating — no dividends distributed)
  Rebalancing tax: ~3,200 EUR over 10 years
  Final value before tax: 95,800 EUR (lower due to tax drag on rebalancing)
  Capital gains tax on exit: (95,800 - 50,000) * 30% = 13,740 EUR
  After-tax value: 78,860 EUR

OST advantage: 83,040 - 78,860 = 4,180 EUR (+5.3% more after tax)
```

---

## 8. API Endpoints

### 8.1 Run Backtest

`POST /api/v1/backtest/run`

**Request body:** Full strategy configuration (Section 1.1 schema).

**Response:**

```json
{
  "data": {
    "id": "bt_20260321_abc123",
    "status": "completed",
    "executionTimeMs": 4820,
    "strategy": { "...strategy config..." },
    "metrics": {
      "totalReturnNominal": 1.272,
      "totalReturnReal": 0.891,
      "cagr": 0.081,
      "sharpeRatio": 0.62,
      "sortinoRatio": 0.89,
      "maxDrawdown": {
        "drawdownPct": 0.284,
        "peakDate": "2020-02-19",
        "peakValueCents": 98500000,
        "troughDate": "2020-03-23",
        "troughValueCents": 70510000,
        "recoveryDate": "2020-08-18",
        "recoveryDays": 147
      },
      "calmarRatio": 0.285,
      "winRate": 0.80,
      "bestYear": { "year": 2019, "return": 0.243 },
      "worstYear": { "year": 2022, "return": -0.148 },
      "taxDrag": 0.040,
      "totalTaxesPaidCents": 3210000,
      "totalDividendsReceivedCents": 4820000,
      "totalContributionsCents": 42500000,
      "finalValueCents": 142000000
    },
    "annualReturns": [
      { "year": 2011, "return": 0.052 },
      { "year": 2012, "return": 0.138 }
    ],
    "equityCurve": [
      { "date": "2011-03-21", "valueCents": 20000000, "normalizedValue": 10000 },
      { "date": "2011-03-22", "valueCents": 20050000, "normalizedValue": 10025 }
    ],
    "underwaterSeries": [
      { "date": "2020-03-23", "drawdownPct": -0.284 }
    ],
    "allocationHistory": [
      {
        "date": "2011-03-21",
        "equities": 0.75,
        "fixedIncome": 0.15,
        "crypto": 0.07,
        "cash": 0.03
      }
    ],
    "trades": [
      {
        "date": "2011-04-01",
        "action": "buy",
        "ticker": "IWDA.AS",
        "quantity": "42.00",
        "priceCents": 4250,
        "totalCents": 178500,
        "feeCents": 179,
        "accountType": "osakesaastotili",
        "reason": "quarterly_rebalance"
      }
    ]
  },
  "meta": {
    "calculatedAt": "2026-03-21T10:30:00Z",
    "dataRange": {
      "pricesFrom": "2011-03-21",
      "pricesTo": "2026-03-21",
      "tradingDays": 3912
    }
  }
}
```

### 8.2 Get Backtest Results

`GET /api/v1/backtest/results/{id}`

Returns the same response shape as the `POST /run` endpoint. Results are cached for 24 hours.

**Query parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `includeEquityCurve` | bool | true | Include daily equity curve data |
| `includeUnderwaterSeries` | bool | true | Include underwater chart data |
| `includeAllocationHistory` | bool | false | Include daily allocation weights |
| `includeTrades` | bool | false | Include full trade log |

### 8.3 Compare Strategies

`POST /api/v1/backtest/compare`

**Request body:**

```json
{
  "strategies": [
    { "...strategy A config..." },
    { "...strategy B config..." },
    { "...strategy C config..." }
  ],
  "startDate": "2011-03-21",
  "endDate": "2026-03-21",
  "significanceTest": "paired_ttest"
}
```

**Response:**

```json
{
  "data": {
    "strategies": [
      {
        "name": "Quarterly Rebalance",
        "metrics": { "...same metrics as run response..." }
      },
      {
        "name": "Annual Rebalance",
        "metrics": { "...same metrics..." }
      }
    ],
    "comparison": {
      "equityCurves": {
        "dates": ["2011-03-21", "2011-03-22"],
        "series": {
          "Quarterly Rebalance": [10000, 10025],
          "Annual Rebalance": [10000, 10030]
        }
      },
      "significanceTests": [
        {
          "strategyA": "Quarterly Rebalance",
          "strategyB": "Annual Rebalance",
          "meanDifference": -0.00017,
          "tStatistic": -0.84,
          "pValue": 0.401,
          "significant": false
        }
      ]
    }
  }
}
```

### 8.4 What-If Analysis

`GET /api/v1/backtest/what-if`

**Query parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `baselineId` | string | Yes | ID of the baseline backtest result |
| `parameter` | string | Yes | Parameter path (e.g., `startDate`, `allocation.fixedWeights.equities`) |
| `values` | string | Yes | Comma-separated list of parameter values |
| `outputMetric` | string | No | Metric to report (default: `finalValueCents`) |

**Response:**

```json
{
  "data": {
    "parameter": "rebalancing.frequency",
    "outputMetric": "finalValueCents",
    "baseline": {
      "parameterValue": "quarterly",
      "outputValue": 142000000
    },
    "scenarios": [
      { "parameterValue": "monthly", "outputValue": 139500000, "metrics": { "...full metrics..." } },
      { "parameterValue": "quarterly", "outputValue": 142000000, "metrics": { "..." } },
      { "parameterValue": "annually", "outputValue": 144500000, "metrics": { "..." } },
      { "parameterValue": "drift_triggered", "outputValue": 143200000, "metrics": { "..." } }
    ]
  }
}
```

### 8.5 Rolling Window Analysis

`GET /api/v1/backtest/rolling`

**Query parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `strategyId` | string | Required | Strategy configuration to use |
| `windowYears` | int | 10 | Window length: 5, 10, or 15 |
| `stepMonths` | int | 1 | Slide interval in months |
| `metric` | string | `cagr` | Primary metric to analyze |

**Response:**

```json
{
  "data": {
    "windowYears": 10,
    "totalWindows": 180,
    "distribution": {
      "metric": "cagr",
      "min": 0.021,
      "p5": 0.038,
      "p25": 0.059,
      "median": 0.074,
      "p75": 0.092,
      "p95": 0.111,
      "max": 0.128,
      "mean": 0.072,
      "std": 0.025
    },
    "positiveReturnPct": 1.0,
    "worstStartingPeriods": [
      {
        "windowStart": "2000-10-01",
        "windowEnd": "2010-10-01",
        "cagr": 0.021,
        "maxDrawdown": 0.482
      }
    ],
    "bestStartingPeriods": [
      {
        "windowStart": "2009-03-01",
        "windowEnd": "2019-03-01",
        "cagr": 0.128,
        "maxDrawdown": 0.198
      }
    ],
    "windows": [
      {
        "windowStart": "2001-01-01",
        "windowEnd": "2011-01-01",
        "cagr": 0.034,
        "totalReturn": 0.397,
        "maxDrawdown": 0.461,
        "sharpe": 0.22,
        "finalValueCents": 87500000
      }
    ]
  }
}
```

---

## 9. Performance Considerations

- **Target execution time**: <10 seconds for a 15-year daily backtest (~3,900 trading days)
- **Bottleneck**: Price lookups. Pre-load all required prices into memory before the simulation loop.
- **Memory**: A single backtest with daily snapshots for 15 years: ~3,900 snapshots x ~200 bytes = ~780 KB. Negligible.
- **Vectorization**: The inner simulation loop is inherently sequential (state depends on previous day). Optimize by batching database reads and minimizing per-day overhead.
- **Comparison runs**: Run strategies in parallel (Python `concurrent.futures` or async). 3 strategy comparison = 3 parallel backtests.
- **Rolling backtests**: Many windows share overlapping periods. Cache intermediate price data. For 180 windows of 10 years each, pre-load the full 25-year price history once.
- **Caching**: Cache completed backtest results by hash of strategy config + data version. TTL: 24 hours (invalidated when new price data is ingested).

```python
import hashlib
import json

def backtest_cache_key(strategy: dict) -> str:
    """Generate a deterministic cache key for a strategy config."""
    serialized = json.dumps(strategy, sort_keys=True, default=str)
    return f"backtest:{hashlib.sha256(serialized.encode()).hexdigest()[:16]}"
```

---

## 10. Edge Cases

1. **Missing price data for a security**: If a security has no price on a given trading day (e.g., trading halt, market holiday mismatch), use the last available price with a lookback of up to 5 trading days. If no price exists within 5 days, exclude the security from that day's rebalancing and log a `data_gap` warning.

2. **Security not listed for the entire backtest period**: If a security was listed in 2015 but the backtest starts in 2011, substitute cash for that security's allocation until its IPO date. Log a `late_listing` warning with the date the security becomes available.

3. **FX rate gaps on weekends/holidays**: Use the most recent available FX rate (lookback up to 7 days to cover long holiday weekends). Crypto positions that trade on weekends use the Friday FX rate for EUR conversion.

4. **Stock split with fractional shares**: After a split, if the resulting quantity includes fractions, round down to the nearest whole share and credit the fractional remainder as cash (matching Nordnet's actual behavior).

5. **Dividend reinvestment produces fractional shares**: Round down to whole shares; remainder stays as cash in the account. Exception: if the security supports fractional shares on Nordnet, use the exact amount.

6. **OST deposit limit exceeded during backtest**: When cumulative deposits to the OST account reach 50,000 EUR, all subsequent equity purchases are routed to the regular account. The simulation must track `ost_deposits_cents` throughout.

7. **Rebalancing trade too small**: If a rebalancing trade would be less than 50 EUR (below Nordnet minimum), skip it. Accumulate the drift until the trade becomes large enough.

8. **Backtest period includes no trading days**: If `startDate` equals `endDate` or the range contains no trading days, return an error with message `"No trading days in the specified date range"`.

9. **Zero or negative portfolio value**: If aggressive withdrawals or extreme losses reduce the portfolio to zero, stop all trading activity. Record zero for all remaining days. Do not allow negative portfolio values.

10. **Tax year boundary during backtest**: At each January 1 crossing, reset the YTD realized gains counter (for the 30k threshold), apply any carry-forward losses from the previous year, and expire losses older than 5 years.

11. **Multiple securities on different exchanges with different trading calendars**: Helsinki, Stockholm, and US markets have different holidays. A security may have a price update on a day when another does not. The simulation advances on the union of all trading calendars, using the last available price for each security individually.

12. **Crypto 24/7 vs stock market hours**: Crypto has prices every day. When the simulation runs on weekends (for crypto), stock/bond/ETF positions use Friday's closing price. This is consistent with the risk-metrics spec approach.

---

## Open Questions

1. **Historical data depth**: How far back do we have reliable daily prices for all securities in the strategy? Yahoo Finance typically provides 20+ years for major indices, but some Nordic stocks and European ETFs may have shorter histories. Should we define a minimum data requirement (e.g., 10 years)?

2. **Survivorship bias**: Backtesting only securities that exist today ignores delisted/bankrupt securities. Should we support adding delisted securities with their historical prices to reduce survivorship bias?

3. **Look-ahead bias in glidepath**: The glidepath is defined today but applied retroactively. A true out-of-sample backtest would use the glidepath as defined at each point in time. Is this level of rigor needed for a personal tool?

4. **Transaction timing**: Should trades execute at open, close, or VWAP? Current assumption is close price on the rebalancing day. Using open price might be more realistic for market orders.

5. **Reinvestment delay**: Dividends and contribution deposits arrive with a delay (T+2 settlement, bank transfer timing). Should the simulation model this delay, or assume instant availability?

6. **Tax lot matching**: The simulation currently uses FIFO for lot matching on sells. Should specific identification (used in real trading) be an option? This would allow the simulation to optimize lot selection for tax efficiency.

7. **Inflation data source**: Should inflation be sourced from Finnish CPI (Tilastokeskus), Eurozone HICP (Eurostat), or user-configurable? Finnish CPI is more relevant for the investor's purchasing power.

---

## Changelog

| Date | Change |
|------|--------|
| 2026-03-21 | Initial draft — DRAFT status |
