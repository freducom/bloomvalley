# Monte Carlo Simulation

Monte Carlo simulation for retirement income projections. This spec defines how to model the probabilistic evolution of the portfolio from the current state to retirement (age 60) and through the withdrawal phase (age 60-95), incorporating the glidepath, tax drag, inflation, and asset class correlations. The simulation answers the fundamental question: "Am I on track for retirement?"

**Status: DRAFT**

## Dependencies

- [Spec Conventions](../00-meta/spec-conventions.md) — monetary format, terminology
- [Data Model](../01-system/data-model.md) — `positions`, `accounts` tables for current portfolio value
- [Glidepath](../03-calculations/glidepath.md) — target allocation at each age, rebalancing logic
- [Finnish Tax](../03-calculations/tax-finnish.md) — capital gains tax rates for rebalancing drag

---

## Simulation Parameters

### Portfolio Inputs

| Parameter | Source | Default |
|-----------|--------|---------|
| `current_portfolio_value_cents` | Computed from `positions` table (sum of all market values in EUR) | Required |
| `annual_contribution_cents` | User input | 0 |
| `contribution_growth_rate` | Annual % increase in contributions (salary growth) | 0% |
| `birth_date` | User settings | Required |
| `retirement_age` | User settings | 60 |
| `death_age_assumption` | For withdrawal phase modeling | 95 |

### Asset Class Return Assumptions

Historical calibration, nominal (before inflation):

| Asset Class | Expected Annual Return (mu) | Annual Volatility (sigma) | Source |
|-------------|---------------------------|--------------------------|--------|
| Equities | 7.0% | 16.0% | Global equity long-run average (MSCI World) |
| Fixed Income | 3.0% | 6.0% | Eurozone government bond average |
| Crypto | 10.0% | 60.0% | User-configurable; highly uncertain |
| Cash | 1.0% | 0.5% | Approximates ECB deposit facility rate |

All return and volatility parameters are user-configurable. The defaults above are stored in `user_settings` and editable through the UI.

### Correlation Matrix

Default asset class correlation matrix (calibrated from 2015-2025 data):

|              | Equities | Fixed Income | Crypto | Cash |
|--------------|----------|-------------|--------|------|
| Equities     | 1.00     | -0.20       | 0.30   | 0.00 |
| Fixed Income | -0.20    | 1.00        | -0.10  | 0.10 |
| Crypto       | 0.30     | -0.10       | 1.00   | 0.00 |
| Cash         | 0.00     | 0.10        | 0.00   | 1.00 |

The correlation matrix must be positive semi-definite. If user-edited values violate this, the system rejects the input and shows an error.

### Other Parameters

| Parameter | Default | Notes |
|-----------|---------|-------|
| Inflation rate | 2.0% | ECB target; used to compute real returns |
| Tax drag (rebalancing) | 0.3% per year | Estimated annual cost of capital gains tax triggered by rebalancing; see derivation below |
| Number of simulation paths | 10,000 | Balance between accuracy and computation time |
| Random seed | None (random) | User can set a seed for reproducibility |

---

## Mathematical Model

### Geometric Brownian Motion (GBM)

Each asset class evolves independently (before correlation), then correlations are applied via Cholesky decomposition.

For asset class *i* over a single year:

```
ln(S_i(t+1) / S_i(t)) = (mu_i - 0.5 * sigma_i^2) * dt + sigma_i * sqrt(dt) * Z_i

where:
    S_i(t)  = value of asset class i at time t
    mu_i    = expected annual return for asset class i
    sigma_i = annual volatility for asset class i
    dt      = 1 (annual time step)
    Z_i     = standard normal random variable (correlated across asset classes)
```

Equivalently:

```
S_i(t+1) = S_i(t) * exp((mu_i - 0.5 * sigma_i^2) + sigma_i * Z_i)
```

### Applying Correlations via Cholesky Decomposition

```
Let C = correlation matrix (4x4)
Let L = cholesky(C)                 -- lower triangular matrix such that L @ L^T = C
Let Z_independent = [z1, z2, z3, z4]   -- 4 independent standard normal draws
Let Z_correlated = L @ Z_independent    -- correlated normal draws

Use Z_correlated[i] as Z_i in the GBM formula above.
```

### Tax Drag Estimation

Annual rebalancing triggers capital gains tax. The drag is modeled as a reduction in effective return:

```
tax_drag_annual = average_turnover * average_gain_fraction * tax_rate

where:
    average_turnover    = 0.05   -- ~5% of portfolio rebalanced annually (from glidepath drift)
    average_gain_fraction = 0.50 -- ~50% of rebalanced amount is gain (conservative estimate)
    tax_rate            = 0.30   -- Finnish capital gains rate (lower bracket)

    tax_drag_annual = 0.05 * 0.50 * 0.30 = 0.0075 = 0.75%

Simplified to ~0.3% after accounting for:
    - Osakesaastotili trades (no tax)
    - Loss harvesting offsets
    - Trades with low gains
```

Applied to equities and crypto returns only (bonds and cash generate minimal rebalancing gains):

```
mu_equities_after_tax = mu_equities - tax_drag
mu_crypto_after_tax   = mu_crypto - tax_drag
```

---

## Simulation Process

### Pseudocode

```python
def run_monte_carlo(params: SimulationParams) -> SimulationResult:
    N = params.num_paths          # 10,000
    T_accum = params.retirement_age - params.current_age   # accumulation years
    T_withdraw = params.death_age - params.retirement_age  # withdrawal years
    T = T_accum + T_withdraw

    # Precompute Cholesky decomposition
    L = np.linalg.cholesky(params.correlation_matrix)

    # Adjust returns for tax drag
    mu = params.expected_returns.copy()
    mu['equities'] -= params.tax_drag
    mu['crypto'] -= params.tax_drag

    # Initialize results array: N paths x T+1 years
    portfolio_values = np.zeros((N, T + 1))
    portfolio_values[:, 0] = params.current_portfolio_value_cents

    for path in range(N):
        # Per-path state: value allocated to each asset class
        values = allocate_to_classes(
            params.current_portfolio_value_cents,
            get_target_allocation(params.current_age)
        )

        for year in range(T):
            age = params.current_age + year

            # 1. Generate correlated returns
            Z_indep = np.random.standard_normal(4)
            Z_corr = L @ Z_indep

            for i, asset_class in enumerate(ASSET_CLASSES):
                annual_return = np.exp(
                    (mu[asset_class] - 0.5 * sigma[asset_class]**2)
                    + sigma[asset_class] * Z_corr[i]
                )
                values[asset_class] *= annual_return

            # 2. Add annual contribution (accumulation phase only)
            if age < params.retirement_age:
                contribution = params.annual_contribution_cents * (
                    (1 + params.contribution_growth_rate) ** year
                )
                # Allocate contribution to underweight classes
                values = add_contribution(values, contribution, get_target_allocation(age))

            # 3. Subtract annual withdrawal (withdrawal phase only)
            if age >= params.retirement_age:
                withdrawal = compute_withdrawal(
                    sum(values.values()),
                    params.withdrawal_rate
                )
                values = subtract_withdrawal(values, withdrawal)

            # 4. Annual rebalance to glidepath target
            target = get_target_allocation(age + 1)
            values = rebalance(values, target)

            # 5. Record total portfolio value
            portfolio_values[path, year + 1] = sum(values.values())

    return portfolio_values
```

### Annual Rebalancing Within Simulation

```
def rebalance(values: dict, target: dict) -> dict:
    total = sum(values.values())
    for asset_class in ASSET_CLASSES:
        values[asset_class] = total * target[asset_class]
    return values
```

This is a simplified instantaneous rebalance. The tax drag parameter accounts for the cost of this rebalancing in the real world.

### Withdrawal Phase

```
def compute_withdrawal(portfolio_value_cents: int, withdrawal_rate: float) -> int:
    return int(portfolio_value_cents * withdrawal_rate)
```

Default withdrawal rate: 4% (the "4% rule"). User-configurable. Withdrawals are inflation-adjusted:

```
withdrawal_year_n = initial_withdrawal * (1 + inflation_rate) ** n
```

For the first year of retirement, `initial_withdrawal = portfolio_value_at_retirement * withdrawal_rate`.

---

## Outputs

### Primary Metrics

| Metric | Formula |
|--------|---------|
| Median portfolio at retirement | `np.median(portfolio_values[:, T_accum])` |
| Mean portfolio at retirement | `np.mean(portfolio_values[:, T_accum])` |
| P5 (pessimistic) | `np.percentile(portfolio_values[:, T_accum], 5)` |
| P25 (below average) | `np.percentile(portfolio_values[:, T_accum], 25)` |
| P75 (above average) | `np.percentile(portfolio_values[:, T_accum], 75)` |
| P95 (optimistic) | `np.percentile(portfolio_values[:, T_accum], 95)` |
| Probability of reaching target | `np.mean(portfolio_values[:, T_accum] >= target_value)` |

### Withdrawal Phase Metrics

| Metric | Formula |
|--------|---------|
| Probability of lasting to age 85 | `np.mean(portfolio_values[:, age_85_index] > 0)` |
| Probability of lasting to age 90 | `np.mean(portfolio_values[:, age_90_index] > 0)` |
| Probability of lasting to age 95 | `np.mean(portfolio_values[:, age_95_index] > 0)` |
| Safe withdrawal rate | Maximum rate where P(lasting to 95) >= 95% |
| Median portfolio at age 85 | `np.median(portfolio_values[:, age_85_index])` |

### Safe Withdrawal Rate Estimation

```
def estimate_safe_withdrawal_rate(params) -> float:
    for rate in np.arange(0.02, 0.08, 0.001):  # 2% to 8% in 0.1% steps
        params.withdrawal_rate = rate
        results = run_monte_carlo(params)
        survival_95 = np.mean(results[:, -1] > 0)
        if survival_95 < 0.95:
            return rate - 0.001  # last rate where survival >= 95%
    return 0.08  # portfolio can sustain even 8%
```

---

## Worked Example

### Inputs

```
Current portfolio: 200,000 EUR (20,000,000 cents)
Annual contribution: 24,000 EUR (2,400,000 cents)
Contribution growth: 2% per year
Current age: 45
Retirement age: 60
Withdrawal rate: 4%
All other parameters: defaults
```

### Expected Accumulation (Deterministic Midpoint)

For intuition, the deterministic case (no volatility):

```
Weighted expected return (at age 45 allocation):
    0.75 * 0.07 + 0.15 * 0.03 + 0.07 * 0.10 + 0.03 * 0.01
    = 0.0525 + 0.0045 + 0.007 + 0.0003
    = 0.0643 = 6.43% nominal

After tax drag (~0.25% blended):
    ~6.18% nominal

After inflation (2%):
    ~4.18% real

Year 0:  200,000
Year 1:  200,000 * 1.0618 + 24,000 = 236,360
Year 5:  ~377,000 (approximate)
Year 10: ~603,000
Year 15: ~920,000 (approximate, deterministic)
```

### Simulated Distribution (Illustrative)

After 10,000 paths with volatility:

| Percentile | Portfolio at Age 60 (EUR) |
|------------|--------------------------|
| 5th        | ~480,000                  |
| 25th       | ~680,000                  |
| 50th (median) | ~870,000              |
| 75th       | ~1,120,000                |
| 95th       | ~1,650,000                |

Probability of reaching 800,000 EUR target: ~58%

### Withdrawal Phase (from median)

Starting at 870,000 EUR, 4% withdrawal = 34,800 EUR/year (inflation-adjusted):

| Age | Median Portfolio (EUR) | P(portfolio > 0) |
|-----|----------------------|-------------------|
| 65  | ~780,000             | 99.5%             |
| 75  | ~550,000             | 96%               |
| 85  | ~280,000             | 88%               |
| 90  | ~120,000             | 79%               |
| 95  | ~0                   | 65%               |

Safe withdrawal rate (95% survival to age 95): ~3.1%

---

## Fan Chart Visualization Data

The API returns data for rendering a fan chart (percentile bands over time).

### API Endpoint: `GET /api/v1/projections/monte-carlo`

Query params: `annualContribution`, `contributionGrowth`, `withdrawalRate`, `retirementAge`, `numPaths`, `seed`

### Response Shape

```json
{
  "params": {
    "currentPortfolioValue": 20000000,
    "annualContribution": 2400000,
    "contributionGrowth": 0.02,
    "retirementAge": 60,
    "withdrawalRate": 0.04,
    "numPaths": 10000,
    "expectedReturns": {
      "equities": 0.07,
      "fixedIncome": 0.03,
      "crypto": 0.10,
      "cash": 0.01
    }
  },
  "fanChart": [
    {
      "age": 45,
      "year": 0,
      "p5": 20000000,
      "p25": 20000000,
      "p50": 20000000,
      "p75": 20000000,
      "p95": 20000000
    },
    {
      "age": 46,
      "year": 1,
      "p5": 22100000,
      "p25": 23200000,
      "p50": 23640000,
      "p75": 24100000,
      "p95": 25300000
    }
  ],
  "summary": {
    "medianAtRetirement": 87000000,
    "probabilityOfTarget": 0.58,
    "targetValue": 80000000,
    "safeWithdrawalRate": 0.031,
    "probabilityLastingTo85": 0.88,
    "probabilityLastingTo90": 0.79,
    "probabilityLastingTo95": 0.65
  }
}
```

The `fanChart` array contains one entry per year from current age to `death_age_assumption`. The frontend renders this as a filled area chart with the median line highlighted.

---

## Sensitivity Analysis

The system computes how key outputs change when individual inputs are varied, holding all else constant.

### Variables to Vary

| Variable | Range | Step | Output Measured |
|----------|-------|------|----------------|
| Equity return assumption | 3% to 11% | 1% | Median at retirement, P(reaching target) |
| Annual contribution | 0 to 48,000 EUR | 6,000 EUR | Median at retirement, P(reaching target) |
| Retirement age | 55 to 65 | 1 year | Median at retirement, Safe withdrawal rate |
| Withdrawal rate | 2% to 6% | 0.5% | P(lasting to 85), P(lasting to 95) |
| Crypto allocation | 0% to 15% | 2.5% | Median at retirement, P5 at retirement (downside) |

### API Endpoint: `GET /api/v1/projections/sensitivity`

Query params: `variable` (one of the above), `outputMetric`

### Response Shape

```json
{
  "variable": "annualContribution",
  "outputMetric": "medianAtRetirement",
  "baseline": {
    "inputValue": 2400000,
    "outputValue": 87000000
  },
  "dataPoints": [
    { "inputValue": 0, "outputValue": 52000000 },
    { "inputValue": 600000, "outputValue": 58000000 },
    { "inputValue": 1200000, "outputValue": 65000000 },
    { "inputValue": 1800000, "outputValue": 75000000 },
    { "inputValue": 2400000, "outputValue": 87000000 },
    { "inputValue": 3000000, "outputValue": 100000000 },
    { "inputValue": 3600000, "outputValue": 114000000 },
    { "inputValue": 4200000, "outputValue": 129000000 },
    { "inputValue": 4800000, "outputValue": 145000000 }
  ]
}
```

---

## Performance Considerations

- **10,000 paths x 50 years x 4 asset classes**: ~2,000,000 random draws per simulation run
- Target execution time: < 3 seconds on a single core (Python with NumPy vectorization)
- Vectorize across all paths simultaneously (no per-path Python loop):

```python
# Vectorized: all 10,000 paths in one operation
Z = np.random.standard_normal((N, T, 4))        # shape: (10000, 50, 4)
Z_corr = np.einsum('ij,...j->...i', L, Z)       # apply Cholesky
log_returns = (mu - 0.5 * sigma**2) + sigma * Z_corr
cumulative = np.exp(np.cumsum(log_returns, axis=1))
```

- Cache simulation results for 1 hour (key: hash of all input parameters)
- For sensitivity analysis: run 5-9 simulations sequentially, each with reduced paths (2,000) for faster feedback

---

## Edge Cases

1. **Zero portfolio value**: If the portfolio is empty, the simulation starts from contributions only. All paths begin at 0 and grow purely from annual contributions.
2. **Zero contributions**: Valid scenario. Simulation runs on existing portfolio value only with no new capital.
3. **Negative returns in all paths for a year**: Possible, especially for crypto. Portfolio values can approach zero but never go negative (floored at 0).
4. **Portfolio depletion during withdrawal**: If a path's portfolio hits 0, it stays at 0 for all remaining years (no borrowing). This path counts as "failed" for survival probability.
5. **Extremely high crypto volatility**: With sigma = 60%, a single year can see returns from -70% to +300%. The log-normal model handles this correctly but the tails are extreme. Consider capping simulated single-year crypto returns at -90% / +500% to avoid unrealistic paths.
6. **Correlation matrix not positive semi-definite**: If user edits create an invalid matrix, Cholesky decomposition fails. Validate on input; if invalid, show error and suggest the nearest valid matrix (via Higham's algorithm or simply reject).
7. **Inflation higher than returns**: If inflation > weighted return, real portfolio value declines. This is a valid pessimistic scenario and should not be suppressed.
8. **Retirement age in the past**: If the user's current age > retirement_age, skip accumulation phase entirely and begin with withdrawal phase simulation.
9. **Contribution exceeds portfolio value**: Valid for early years with small portfolios. No special handling needed.
10. **Tax drag during withdrawal phase**: Withdrawals also trigger tax. Model withdrawal-phase tax drag as an additional 0.5% reduction in effective returns during the withdrawal period.
11. **Leap years and exact age**: Use 365.25 days/year for age calculation consistency with the glidepath spec.

## Open Questions

- Should the simulation support non-annual time steps (monthly) for more granularity? Monthly steps would require 12x more computation but produce smoother fan charts.
- Should fat-tailed distributions (Student's t with ~5 degrees of freedom) replace the normal distribution for more realistic tail modeling?
- Should historical sequence-of-returns risk be modeled separately (block bootstrap from actual historical returns) as an alternative to GBM?
- How should the correlation matrix be updated — fixed defaults, rolling historical window, or regime-switching model?

## Changelog

| Date | Change |
|------|--------|
| 2026-03-19 | Initial draft |
