# Portfolio Operations Guide

How to add, remove, and edit securities, transactions, and account balances via the API. All examples use placeholder data — never commit real portfolio values.

**Status: CURRENT**

## Dependencies

- [Data Model](data-model.md) — table definitions, constraints, enums
- [API Overview](api-overview.md) — authentication, base URL, response envelope
- [Nordnet Import](../04-features/F17-nordnet-import.md) — bulk import from broker exports

---

## Authentication

All requests require the `X-API-Key` header:

```bash
API="http://localhost:8000/api/v1"
KEY="X-API-Key: $API_KEY"    # from .env file
```

---

## 1. Managing Securities

Securities are the master catalog of tradeable instruments. A security must exist before it can be referenced in transactions.

### 1.1 Look Up a Security by Ticker

Check if a security already exists before creating it:

```bash
# Search by name or ticker (paginated, 50 per page)
curl -s -H "$KEY" "$API/securities?q=example"

# If total > 50, paginate:
curl -s -H "$KEY" "$API/securities?limit=50&offset=50"
```

The search uses trigram matching on name and case-insensitive ticker matching. If there are many securities, you may need to paginate through all pages (check `pagination.total` in the response).

### 1.2 Look Up External Data (Yahoo Finance)

Before creating, you can fetch metadata from Yahoo Finance without saving:

```bash
curl -s -H "$KEY" "$API/securities/lookup/KEMIRA.HE"
```

Returns: name, currency, exchange, sector, industry, country, asset class. Useful for getting the right field values.

### 1.3 Create a New Security

```bash
curl -s -X POST "$API/securities" \
  -H "$KEY" -H "Content-Type: application/json" \
  -d '{
    "ticker": "EXAMPLE.HE",
    "isin": "FI0000000000",
    "name": "Example Corporation Oyj",
    "asset_class": "stock",
    "currency": "EUR",
    "exchange": "XHEL",
    "sector": "Materials",
    "country": "FI"
  }'
```

**Required fields:** `ticker`, `name`, `asset_class`, `currency`

**Optional fields:**
| Field | When to use |
|-------|-------------|
| `isin` | Always if available — unique constraint prevents duplicates |
| `exchange` | MIC code (XHEL, XSTO, XNAS, XNYS, XAMS, etc.) |
| `sector` | GICS sector name |
| `industry` | GICS industry name |
| `country` | ISO 3166-1 alpha-2 (FI, SE, US, DE, etc.) |
| `is_accumulating` | `true`/`false` for ETFs (ACC vs DIST) |
| `coingecko_id` | For crypto — maps to CoinGecko API |
| `company_group` | Groups multi-class shares (e.g. `"Kesko"` for both A and B shares) |

**Asset class values:** `stock`, `bond`, `etf`, `crypto`, `fund`

**Common errors:**
- `500` with "duplicate key" on ISIN — security already exists, search for it by ISIN
- `500` with "duplicate key" on ticker+exchange — same ticker already registered on that exchange

### 1.4 Find Existing Security by ISIN

If you get a duplicate ISIN error, the security exists but may not appear in first page of results:

```bash
# Paginate through all securities to find by ISIN
for offset in 0 50 100 150; do
  curl -s -H "$KEY" "$API/securities?limit=50&offset=$offset" | \
    python3 -c "
import json,sys
for s in json.load(sys.stdin)['data']:
    if s.get('isin') == 'FI0000000000':
        print(f'id={s[\"id\"]}, ticker={s[\"ticker\"]}, name={s[\"name\"]}')
"
done
```

---

## 2. Managing Accounts

### 2.1 List Accounts

```bash
curl -s -H "$KEY" "$API/accounts"
```

Returns all active accounts with their IDs, types, institutions, and cash balances.

### 2.2 Create a New Account

```bash
curl -s -X POST "$API/accounts" \
  -H "$KEY" -H "Content-Type: application/json" \
  -d '{
    "name": "Broker - Regular",
    "type": "regular",
    "institution": "Nordnet",
    "currency": "EUR"
  }'
```

**Account types:**
| Type | Description |
|------|-------------|
| `regular` | Standard brokerage (AOT/AF/ISK) |
| `osakesaastotili` | Finnish equity savings account (50k EUR deposit cap) |
| `pension` | Pension account (requires `pension_subtype`) |
| `crypto_wallet` | Crypto exchange or wallet |

**Pension subtypes:** `ps_sopimus`, `kapitalisaatiosopimus`

### 2.3 Update Cash Balance

After a trade, update the remaining cash in the account:

```bash
# Finnish format with comma decimal
curl -s -X POST "$API/accounts/cash" \
  -H "$KEY" -H "Content-Type: application/json" \
  -d '{
    "account_id": 1,
    "text": "13 800,00 EUR"
  }'

# English format works too
curl -s -X POST "$API/accounts/cash" \
  -H "$KEY" -H "Content-Type: application/json" \
  -d '{
    "account_id": 1,
    "text": "13800.00 EUR"
  }'
```

The parser handles: spaces as thousands separators, commas or dots as decimal separators, and extracts the currency code. If `account_id` is omitted, it updates the first active Nordnet account.

---

## 3. Recording Transactions

### 3.1 Buy Shares

The core operation. Requires: `account_id` (from accounts list) and `security_id` (from securities list).

```bash
curl -s -X POST "$API/transactions" \
  -H "$KEY" -H "Content-Type: application/json" \
  -d '{
    "account_id": 1,
    "security_id": 28,
    "type": "buy",
    "trade_date": "2026-05-04",
    "quantity": "500",
    "price_cents": 1765,
    "price_currency": "EUR",
    "total_cents": 882500,
    "fee_cents": 0,
    "fee_currency": "EUR",
    "currency": "EUR"
  }'
```

**Monetary values are always in cents:**
- Price of 17.65 EUR = `1765` cents
- Total of 8,825.00 EUR = `882500` cents
- Fee of 9.00 EUR = `900` cents

**Calculation:** `total_cents = quantity * price_cents` (exclude fees — they are tracked separately)

### 3.2 Sell Shares (via Portfolio Endpoint)

The portfolio sell endpoint validates quantity, creates the transaction, and updates cash balance automatically:

```bash
curl -s -X POST "$API/portfolio/sell" \
  -H "$KEY" -H "Content-Type: application/json" \
  -d '{
    "account_id": 1,
    "security_id": 28,
    "quantity": "200",
    "price_cents": 1850,
    "total_cents": 370000,
    "fee_cents": 900,
    "currency": "EUR",
    "trade_date": "2026-06-01"
  }'
```

This will:
1. Verify you hold enough shares
2. Create a sell transaction
3. Add net proceeds (total - fees) to the account's cash balance

### 3.3 Sell Shares (via Transaction Endpoint)

Alternatively, create a sell transaction directly (does NOT auto-update cash):

```bash
curl -s -X POST "$API/transactions" \
  -H "$KEY" -H "Content-Type: application/json" \
  -d '{
    "account_id": 1,
    "security_id": 28,
    "type": "sell",
    "trade_date": "2026-06-01",
    "quantity": "200",
    "price_cents": 1850,
    "total_cents": 370000,
    "fee_cents": 900,
    "currency": "EUR"
  }'
```

When using this method, also update the cash balance manually (see section 2.3).

### 3.4 Record a Dividend

```bash
curl -s -X POST "$API/transactions" \
  -H "$KEY" -H "Content-Type: application/json" \
  -d '{
    "account_id": 1,
    "security_id": 28,
    "type": "dividend",
    "trade_date": "2026-04-15",
    "quantity": "0",
    "total_cents": 25000,
    "withholding_tax_cents": 7500,
    "currency": "EUR",
    "notes": "Q1 dividend"
  }'
```

### 3.5 Record a Deposit or Withdrawal

Cash events have no `security_id`:

```bash
# Deposit
curl -s -X POST "$API/transactions" \
  -H "$KEY" -H "Content-Type: application/json" \
  -d '{
    "account_id": 1,
    "type": "deposit",
    "trade_date": "2026-05-01",
    "total_cents": 500000,
    "currency": "EUR"
  }'
```

### 3.6 Transfer Between Accounts

Use `transfer_out` from source and `transfer_in` to destination:

```bash
# Transfer out of account 1
curl -s -X POST "$API/transactions" \
  -H "$KEY" -H "Content-Type: application/json" \
  -d '{
    "account_id": 1,
    "security_id": 28,
    "type": "transfer_out",
    "trade_date": "2026-05-04",
    "quantity": "100",
    "total_cents": 176500,
    "currency": "EUR"
  }'

# Transfer into account 2
curl -s -X POST "$API/transactions" \
  -H "$KEY" -H "Content-Type: application/json" \
  -d '{
    "account_id": 2,
    "security_id": 28,
    "type": "transfer_in",
    "trade_date": "2026-05-04",
    "quantity": "100",
    "total_cents": 176500,
    "currency": "EUR"
  }'
```

---

## 4. Editing and Deleting Transactions

### 4.1 List Transactions

```bash
# All transactions for an account
curl -s -H "$KEY" "$API/transactions?accountId=1&limit=20"

# Filter by security and type
curl -s -H "$KEY" "$API/transactions?securityId=28&type=buy"

# Filter by date range
curl -s -H "$KEY" "$API/transactions?fromDate=2026-01-01&toDate=2026-06-30"
```

### 4.2 Edit a Transaction

All fields are optional — only include what you want to change:

```bash
curl -s -X PUT "$API/transactions/628" \
  -H "$KEY" -H "Content-Type: application/json" \
  -d '{
    "fee_cents": 900,
    "notes": "Updated broker fee"
  }'
```

### 4.3 Delete a Transaction

```bash
curl -s -X DELETE "$API/transactions/628" -H "$KEY"
```

**Warning:** Deleting a transaction changes the calculated holdings and cost basis. If the holding was later sold, the P&L calculation will change.

---

## 5. Bulk Import from Nordnet

For importing many positions at once (initial portfolio setup or reconciliation), use the import flow instead of individual transactions.

### 5.1 Parse a Nordnet Export

Paste the TSV/CSV content from Nordnet's "Salkkuni" export:

```bash
curl -s -X POST "$API/imports/parse" \
  -H "$KEY" -H "Content-Type: application/json" \
  -d '{
    "text": "Instrumentti\tISIN\t...",
    "account_type": "regular",
    "account_name": "Nordnet - Regular"
  }'
```

Returns an import ID with matched/unmatched securities. The parser auto-detects tab vs semicolon delimiters and Finnish vs English decimal format.

### 5.2 Review and Map Unrecognized Securities

```bash
# Get import details with all rows
curl -s -H "$KEY" "$API/imports/{import_id}"

# Manually map an unrecognized row to a security
curl -s -X POST "$API/imports/{import_id}/rows/{row_id}/map" \
  -H "$KEY" -H "Content-Type: application/json" \
  -d '{"security_id": 28}'
```

### 5.3 Confirm Import

Creates all transactions (buy/sell/transfer_in) from the matched rows:

```bash
curl -s -X POST "$API/imports/{import_id}/confirm" -H "$KEY"
```

### 5.4 Cancel Import

```bash
curl -s -X POST "$API/imports/{import_id}/cancel" -H "$KEY"
```

---

## 6. Common Workflows

### Buy New Position (Security Doesn't Exist Yet)

1. **Check if security exists** — search by name or ISIN
2. **Look up metadata** — `GET /securities/lookup/{ticker}` for Yahoo Finance data
3. **Create security** — `POST /securities` with ticker, ISIN, name, asset_class, currency, exchange, sector, country
4. **Create buy transaction** — `POST /transactions` with account_id, security_id, type="buy", trade_date, quantity, price_cents, total_cents
5. **Update cash balance** — `POST /accounts/cash` with remaining cash amount

### Buy More of Existing Position

1. **Find the security ID** — search securities by name/ticker
2. **Find the account ID** — list accounts
3. **Create buy transaction** — `POST /transactions`
4. **Update cash balance** — `POST /accounts/cash`

### Sell a Position

1. **Use portfolio sell** — `POST /portfolio/sell` (validates quantity, auto-updates cash)
2. Or: create sell transaction + update cash manually

### Record a Stock Split

1. **Create corporate action** — insert into `corporate_actions` table with type="split", ratio_from, ratio_to
2. The application processes it to adjust tax lots and historical prices

### Multi-Currency Transaction

For securities traded in a foreign currency (e.g., USD stock in a EUR account):

```bash
curl -s -X POST "$API/transactions" \
  -H "$KEY" -H "Content-Type: application/json" \
  -d '{
    "account_id": 1,
    "security_id": 42,
    "type": "buy",
    "trade_date": "2026-05-04",
    "quantity": "50",
    "price_cents": 15000,
    "price_currency": "USD",
    "total_cents": 694444,
    "fee_cents": 500,
    "fee_currency": "EUR",
    "fx_rate": "1.080000",
    "currency": "EUR"
  }'
```

Here `total_cents` is in EUR (account currency), and `fx_rate` records the conversion rate used. The `price_cents` is in USD (security currency).

---

## 7. Verifying Changes

### Check Current Holdings

```bash
curl -s -H "$KEY" "$API/portfolio/holdings" | python3 -m json.tool
```

Returns all positions with quantities, cost basis, current prices, and P&L.

### Check Portfolio Summary

```bash
curl -s -H "$KEY" "$API/portfolio/summary"
```

Returns total value, allocation breakdown, and per-account cash balances.

### Check Transaction History

```bash
curl -s -H "$KEY" "$API/transactions?securityId=28&limit=10"
```

---

## 8. Data Integrity Notes

- **All monetary values are integers (cents)** — 17.65 EUR = 1765 cents. No floats anywhere.
- **Quantities are strings** in the API (backed by `NUMERIC(28,18)`) to support fractional crypto amounts without floating-point errors.
- **Currency codes must be uppercase** — enforced by check constraints.
- **Holdings are calculated, not stored** — the `/portfolio/holdings` endpoint aggregates from transactions in real-time. There is no "holdings" table to manually edit.
- **The `holdings_snapshot` table** is a nightly materialized view for historical tracking, not the source of truth.
- **ISIN is unique** — the database enforces this. If you try to create a security with a duplicate ISIN, it will fail with a 500 error. Search for the existing security instead.
- **Ticker + exchange is unique** — same ticker can exist on different exchanges (e.g., `ASML` on XAMS and `ASML` on XNAS).
- **Deleting a security is not supported** via API — deactivate by setting `is_active = false` (not yet exposed as an endpoint; use direct DB update if needed).

---

## Changelog

| Date | Change |
|------|--------|
| 2026-05-04 | Initial version |
