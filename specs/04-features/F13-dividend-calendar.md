# F13 — Dividend Calendar & Income Tracker

Provides a comprehensive dividend calendar and income tracking system for the portfolio. Answers the questions: "When are my next dividends? How much income will I receive this year?" Tracks ex-dates, payment dates, dividend history, projected income, yield metrics, and withholding tax for both Finnish and foreign securities. Integrates with the tax module for Finnish-specific dividend taxation rules across regular accounts and osakesaastotili.

**Status: DRAFT**

## Dependencies

- [Data Model](../01-system/data-model.md) — `securities`, `transactions` (type = `dividend`), `accounts`, `tax_lots` tables
- [API Overview](../01-system/api-overview.md) — endpoint conventions, response envelope, monetary format
- [Spec Conventions](../00-meta/spec-conventions.md) — date format, monetary values in cents, naming rules
- `../02-data-pipelines/yahoo-finance.md` — dividend data ingestion from Yahoo Finance
- `../03-calculations/tax-lot-tracking.md` — cost basis for yield-on-cost calculation

## Data Requirements

### New Tables

#### `dividend_events`

Stores known upcoming and historical dividend events for tracked securities.

```sql
CREATE TABLE dividend_events (
    id              BIGSERIAL       PRIMARY KEY,
    security_id     BIGINT          NOT NULL REFERENCES securities(id),
    ex_date         DATE            NOT NULL,
    payment_date    DATE,
    record_date     DATE,
    amount_cents    BIGINT          NOT NULL,       -- dividend per share in cents
    currency        CHAR(3)         NOT NULL,       -- dividend currency (may differ from security currency)
    frequency       VARCHAR(20),                     -- 'annual', 'semi_annual', 'quarterly', 'monthly', 'irregular'
    source          VARCHAR(50)     NOT NULL DEFAULT 'yahoo_finance',
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),

    CONSTRAINT uq_dividend_events_security_ex_date
        UNIQUE (security_id, ex_date),
    CONSTRAINT chk_dividend_events_amount_positive
        CHECK (amount_cents > 0),
    CONSTRAINT chk_dividend_events_currency_upper
        CHECK (currency = upper(currency))
);
```

**Indexes:**

```sql
CREATE INDEX idx_dividend_events_security_id ON dividend_events (security_id);
CREATE INDEX idx_dividend_events_ex_date ON dividend_events (ex_date);
CREATE INDEX idx_dividend_events_payment_date ON dividend_events (payment_date);
```

#### `dividend_receipts`

Tracks actual dividends received by the user, including withholding tax.

```sql
CREATE TABLE dividend_receipts (
    id                      BIGSERIAL       PRIMARY KEY,
    transaction_id          BIGINT          REFERENCES transactions(id),   -- link to dividend transaction
    account_id              BIGINT          NOT NULL REFERENCES accounts(id),
    security_id             BIGINT          NOT NULL REFERENCES securities(id),
    dividend_event_id       BIGINT          REFERENCES dividend_events(id),
    ex_date                 DATE            NOT NULL,
    payment_date            DATE,
    shares_held             NUMERIC(18, 8)  NOT NULL,
    gross_amount_cents      BIGINT          NOT NULL,       -- total gross dividend
    withholding_tax_cents   BIGINT          NOT NULL DEFAULT 0,
    net_amount_cents        BIGINT          NOT NULL,       -- gross - withholding
    withholding_tax_rate    NUMERIC(5, 4),                  -- e.g. 0.1500 for 15%
    reclaimable_cents       BIGINT          NOT NULL DEFAULT 0,  -- amount reclaimable via tax treaty
    currency                CHAR(3)         NOT NULL,
    fx_rate_to_eur          NUMERIC(12, 6),                 -- FX rate at payment date
    gross_amount_eur_cents  BIGINT,                         -- converted to EUR for tax reporting
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT now(),

    CONSTRAINT chk_dividend_receipts_net
        CHECK (net_amount_cents = gross_amount_cents - withholding_tax_cents),
    CONSTRAINT chk_dividend_receipts_currency_upper
        CHECK (currency = upper(currency))
);
```

**Indexes:**

```sql
CREATE INDEX idx_dividend_receipts_account_id ON dividend_receipts (account_id);
CREATE INDEX idx_dividend_receipts_security_id ON dividend_receipts (security_id);
CREATE INDEX idx_dividend_receipts_ex_date ON dividend_receipts (ex_date);
```

### Data Ingestion

- **Source**: Yahoo Finance dividend data via `yfinance` library
- **Refresh**: daily during market hours; fetches dividend calendar for all held + watchlisted securities
- **Historical**: on first load, backfill up to 10 years of dividend history per security
- **Fields ingested**: ex-date, payment date, amount per share, currency

## API Endpoints

| Tag | Prefix | Feature |
|-----|--------|---------|
| Dividends | `/dividends` | F13 — Dividend calendar, income tracking |

| Method | Path | Description |
|--------|------|-------------|
| GET | `/dividends/calendar` | Dividend events for a date range, filterable by `securityId`, `accountId`. Query params: `fromDate`, `toDate` (default: current month) |
| GET | `/dividends/upcoming` | Upcoming dividends for held securities. Query param: `days` (30, 60, or 90; default 30) |
| GET | `/dividends/history` | Past dividend receipts, paginated. Filterable by `securityId`, `accountId`, `fromDate`, `toDate` |
| GET | `/dividends/income-projection` | Projected annual dividend income based on current holdings and historical patterns. Query param: `year` (default: current year) |
| GET | `/dividends/yield-metrics` | Portfolio-level yield metrics: dividend yield, yield on cost, dividend growth rates |
| GET | `/dividends/tax-summary` | Withholding tax summary: gross, withheld, net, reclaimable. Filterable by `year`, `country` |

### Example Responses

**GET `/dividends/upcoming?days=30`**

```json
{
  "data": [
    {
      "securityId": 42,
      "ticker": "NESTE",
      "name": "Neste Oyj",
      "exDate": "2026-04-01",
      "paymentDate": "2026-04-15",
      "amountPerShare": { "amount": 80, "currency": "EUR" },
      "sharesHeld": 150,
      "totalAmount": { "amount": 12000, "currency": "EUR" },
      "currentYield": 3.45,
      "accountId": 1,
      "accountName": "Nordnet AF"
    }
  ],
  "meta": { "timestamp": "2026-03-19T10:00:00Z", "cacheAge": 120, "stale": false }
}
```

**GET `/dividends/yield-metrics`**

```json
{
  "data": {
    "portfolioDividendYield": 2.85,
    "yieldOnCost": 3.42,
    "dividendGrowthRate3Y": 6.8,
    "dividendGrowthRate5Y": 5.2,
    "annualDividendIncome": { "amount": 485000, "currency": "EUR" },
    "monthlyBreakdown": [
      { "month": "2026-01", "projected": { "amount": 25000, "currency": "EUR" } },
      { "month": "2026-02", "projected": { "amount": 0, "currency": "EUR" } }
    ]
  },
  "meta": { "timestamp": "2026-03-19T10:00:00Z", "cacheAge": 3600, "stale": false }
}
```

## UI Views

### Calendar View

Monthly grid displaying dividend events for all held securities:

- **Ex-dates**: marked with a red dot / triangle indicator
- **Payment dates**: marked with a green dot / circle indicator
- Clicking a date reveals a tooltip or side panel listing all dividend events on that date
- Navigation: month-by-month with forward/back arrows, jump-to-month selector
- Color intensity indicates total dividend amount for that day (darker = larger payout)

### Upcoming Dividends Table

Tabular view of dividends expected in the next 30/60/90 days:

| Column | Description |
|--------|-------------|
| Security | Ticker + name |
| Ex-Date | Date you must hold shares before |
| Payment Date | Expected payment date |
| Amount/Share | Dividend per share in native currency |
| Shares Held | Current quantity held |
| Total Amount | Amount/share x shares held |
| Yield | Annualized yield based on current price |
| Account | Which account holds the position |

- Sortable by any column; default sort by ex-date ascending
- Toggle: 30 / 60 / 90 day horizon selector

### Dividend History

Past dividends received, with filtering:

- Filter by: security (dropdown), year (dropdown), account (dropdown)
- Columns: date, security, gross amount, withholding tax, net amount, yield at time
- Summary row at bottom: total gross, total tax withheld, total net
- Export to CSV button

### Income Projection

Projected annual dividend income based on current holdings and historical dividend patterns:

- **Monthly bar chart**: 12 bars showing projected dividend income per month
- Bars split by: received (solid fill) vs. projected (hatched/lighter fill) for months not yet paid
- Total annual projection displayed prominently above the chart
- Comparison line: previous year's actual income overlaid
- Assumes current holdings remain unchanged; note this assumption in the UI

### Yield Metrics Panel

Key dividend yield statistics displayed as `MetricCard` components:

| Metric | Calculation |
|--------|-------------|
| Portfolio Dividend Yield | Total annual dividends / total market value |
| Yield on Cost | Total annual dividends / total cost basis |
| 3Y Dividend Growth Rate | CAGR of total dividends received over 3 years |
| 5Y Dividend Growth Rate | CAGR of total dividends received over 5 years |

### Withholding Tax Tracking

Table showing tax impact of dividends:

| Column | Description |
|--------|-------------|
| Security | Ticker + name |
| Country | Country of domicile |
| Gross Dividend | Total gross amount |
| Withholding Tax Rate | Applied rate |
| Withholding Tax | Amount withheld |
| Net Received | Gross minus withholding |
| Reclaimable | Amount recoverable via tax treaty |
| Finnish Tax Treatment | 85% taxable / 100% taxable |

- Summary: total gross, total withheld, total net, total reclaimable
- Filterable by year

## Business Rules

1. **Automatic population**: Dividend events are fetched from Yahoo Finance dividend data via the `yahoo_dividends` pipeline. The `dividend_reconciliation` pipeline then matches events against actual holdings on each ex-date and auto-creates both `dividends` records and `transactions` (type=`dividend`). The reconciliation is idempotent and skips events that already have a matching dividend or transaction record (e.g., Nordnet-imported ones). Run order: `yahoo_dividends` first, then `dividend_reconciliation`.

2. **Ex-date sell warning**: When a user initiates a sell order for a security that has an ex-date within the next 5 business days, display a warning: "Selling before {ex-date} will forfeit the upcoming dividend of {amount}/share (payment date: {payment_date})."

3. **Finnish dividend taxation**:
   - **Finnish listed companies**: 85% of the dividend is taxable capital income (15% tax-free portion applies to natural persons)
   - **Foreign companies**: 100% of the dividend is taxable capital income
   - These rates are applied at the tax reporting level, not at receipt time

4. **Osakesaastotili dividends**: Dividends received in an osakesaastotili account are NOT taxed individually. They are automatically reinvested within the account. The `dividend_receipts` record is still created for tracking, but marked with `account.type = 'osakesaastotili'` so the tax module excludes them from annual tax calculations.

5. **Withholding tax defaults by country**:
   - Finland: 0% (no withholding for domestic investors on Finnish shares)
   - US: 15% (with W-8BEN tax treaty rate; 30% without)
   - Sweden: 15% (Nordic tax treaty)
   - Germany: 26.375% (Kapitalertragsteuer + Soli)
   - Other: store actual rate from broker statement

6. **Income projection**: Based on trailing 12-month dividends per security, multiplied by current shares held. If a company has announced a dividend change, use the announced amount for future projections.

7. **Dividend growth rate**: Calculated as compound annual growth rate (CAGR) of total dividends received. Requires at least 3 full calendar years of data for 3Y rate, 5 for 5Y rate. Display "Insufficient data" if not met.

8. **FX conversion**: All dividend amounts are converted to EUR using the FX rate on the payment date for portfolio-level aggregations. The original currency amount is always preserved.

## Edge Cases

1. **Special dividends**: Marked with `frequency = 'irregular'` in `dividend_events`. Excluded from income projection and growth rate calculations unless the user explicitly includes them.
2. **Dividend cuts or suspensions**: If a company paid dividends historically but has no upcoming dividend event, the income projection shows the last known amount with a "No dividend announced" warning flag.
3. **Stock dividends (scrip)**: Treated as a corporate action (share increase), not a cash dividend. Not tracked in `dividend_events`.
4. **Currency mismatch**: A Finnish-listed company may pay dividends in EUR while the security trades in another currency. Always use the dividend's own currency, not the security's trading currency.
5. **Withholding tax reclaimation**: Reclaimable amounts are informational only. The system does not automate tax reclaim filings.
6. **Ex-date on non-trading day**: Rare, but if it occurs, the ex-date is stored as-is from the data source. The sell warning uses the next trading day.
7. **Fractional shares**: Dividend calculated on fractional share quantities (e.g., 10.5 shares x 0.80 EUR = 8.40 EUR).
8. **Merged/acquired companies**: If a held security is acquired, its dividend history is preserved but no future projections are made. The security is marked inactive.

## Acceptance Criteria

1. Calendar view displays ex-dates and payment dates for all held securities for any selected month.
2. Upcoming dividends table shows correct dividend amounts based on shares held and declared dividend per share.
3. Dividend history is filterable by security, year, and account, with correct gross/net/tax amounts.
4. Income projection chart shows monthly breakdown with received vs. projected distinction.
5. Yield metrics (dividend yield, yield on cost, growth rates) are calculated correctly against current holdings.
6. Withholding tax tracking shows correct rates and reclaimable amounts by country.
7. Sell warning appears when selling a security with an ex-date in the next 5 business days.
8. Osakesaastotili dividends are tracked but excluded from taxable income calculations.
9. All monetary values follow the cents convention and include currency codes.
10. Data refreshes daily; staleness indicator shown if data is older than 48 hours.

## Changelog

| Date | Change |
|------|--------|
| 2026-03-19 | Initial draft |
| 2026-04-08 | Added `dividend_reconciliation` pipeline for auto-matching events to holdings |
