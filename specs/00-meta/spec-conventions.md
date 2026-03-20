# Spec Conventions

Standards and vocabulary for all Warren Cashett specification documents.

## Terminology Glossary

| Term | Definition |
|------|-----------|
| **Security** | Any tradeable instrument: stock, bond, ETF, or cryptocurrency |
| **Position** | The current quantity of a security held in an account (aggregate of all open lots) |
| **Holding** | Synonym for position when viewed in portfolio context |
| **Tax Lot** | A specific purchase of a security with its own cost basis, quantity, and acquisition date |
| **Account** | A container for positions — typed as `regular`, `osakesaastotili`, `crypto_wallet`, or `pension` |
| **Portfolio** | The collection of all accounts belonging to the user |
| **Cost Basis** | The original purchase price of a tax lot including fees, in cents |
| **Market Value** | Current quantity × current price × FX rate, in EUR cents |
| **Unrealized P&L** | Market value minus cost basis for open lots |
| **Realized P&L** | Proceeds minus cost basis for closed lots |
| **Glidepath** | The target asset allocation trajectory from now (age 45) to retirement (age 60) |
| **Drift** | The absolute percentage difference between current and target allocation |
| **Rebalancing** | Trades executed to bring allocation back to target |
| **Adapter** | A data pipeline module that fetches from one external data source |
| **Staleness** | Time elapsed since a data point was last successfully refreshed |

## Monetary Values

- **All monetary values are stored as integers representing cents** (1 EUR = 100 cents)
- Always paired with an ISO 4217 currency code (e.g., `EUR`, `USD`, `GBP`)
- In the database: `amount_cents INTEGER NOT NULL`, `currency CHAR(3) NOT NULL DEFAULT 'EUR'`
- In API responses: `{ "amount": 123456, "currency": "EUR" }` (represents 1,234.56 EUR)
- Display formatting: `€1,234.56` (euro sign prefix, comma thousands separator, dot decimal, 2 decimals)
- **Never use floating-point for money.** Calculations use integer arithmetic or Python `Decimal` where intermediate precision is needed.

## Quantity Values

- Stock/ETF/bond quantities: integer (whole shares) or `NUMERIC(18, 8)` for fractional shares
- Crypto quantities: `NUMERIC(28, 18)` to handle high-precision tokens (e.g., wei for ETH)
- FX rates: `NUMERIC(12, 6)` — 6 decimal places

## Date and Time

- **Storage**: All timestamps in UTC as `TIMESTAMP WITH TIME ZONE`
- **Display**: Converted to `Europe/Helsinki` (EET/EEST) for the UI
- **Date-only fields** (ex-dividend date, trade date): `DATE` type, no timezone
- **API format**: ISO 8601 (`2026-03-19T14:30:00Z` for timestamps, `2026-03-19` for dates)
- **Market dates**: Weekdays only for stock/bond/ETF markets; crypto markets are 24/7/365

## Spec Document Template

Every spec file follows this structure:

```markdown
# {Spec Title}

{One paragraph describing what this spec covers and why it matters.}

## Dependencies

- List of other spec files this spec depends on
- Use relative paths: `../01-system/data-model.md`

## {Domain-Specific Sections}

{The actual specification content — varies by spec type.}

## Edge Cases

- Numbered list of edge cases and how they are handled

## Open Questions

- Any unresolved decisions (removed once resolved)

## Changelog

| Date | Change |
|------|--------|
| YYYY-MM-DD | Initial draft |
```

## Cross-References

- Reference other specs with relative Markdown links: `[data model](../01-system/data-model.md)`
- Reference specific sections with anchors: `[tax lots](../03-calculations/tax-lot-tracking.md#lot-creation)`
- Reference API endpoints by OpenAPI operation ID: `see API: getPortfolioHoldings`
- Reference database tables in backticks: `` `transactions` table ``
- Reference UI components by catalog name: `see component: MetricCard`

## Status Markers

Each spec has a status in its changelog:

| Status | Meaning |
|--------|---------|
| `DRAFT` | Being written, may have gaps or open questions |
| `REVIEW` | Complete, awaiting review and cross-validation |
| `FINAL` | Approved, ready for implementation |

## Naming Conventions

### Files
- Spec files: lowercase, kebab-case (e.g., `tax-finnish.md`)
- Feature specs: prefixed with `F{NN}-` (e.g., `F01-portfolio-dashboard.md`)

### Database
- Tables: lowercase, snake_case, plural (e.g., `tax_lots`, `transactions`)
- Columns: lowercase, snake_case (e.g., `cost_basis_cents`, `created_at`)
- Indexes: `idx_{table}_{columns}` (e.g., `idx_prices_security_id_date`)
- Foreign keys: `fk_{table}_{referenced_table}` (e.g., `fk_transactions_accounts`)
- Enums: `{table}_{column}_enum` (e.g., `accounts_type_enum`)

### API
- Endpoints: lowercase, kebab-case, plural nouns (e.g., `/api/v1/holdings`, `/api/v1/tax-lots`)
- Query params: camelCase (e.g., `fromDate`, `accountId`)
- Response fields: camelCase (e.g., `marketValue`, `costBasis`)

### Code
- Python (backend): snake_case for variables/functions, PascalCase for classes
- TypeScript (frontend): camelCase for variables/functions, PascalCase for components/types

## Changelog

| Date | Change |
|------|--------|
| 2026-03-19 | Initial draft |
