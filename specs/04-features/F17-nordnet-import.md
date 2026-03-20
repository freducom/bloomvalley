# F17 — Nordnet Portfolio Import

Enables importing portfolio data from Nordnet (the primary broker) via a paste-in text area. Answers the question: "How do I get my actual portfolio into the system?" Parses Nordnet's export format, maps securities to the system catalog via ISIN, and generates reconciliation transactions to bring the system's records in line with the broker's data. Supports one-time initial import and recurring imports with diff detection.

**Status: DRAFT**

## Dependencies

- [Data Model](../01-system/data-model.md) — `securities`, `accounts`, `transactions`, `tax_lots` tables
- [API Overview](../01-system/api-overview.md) — endpoint conventions, response envelope, error codes
- [Spec Conventions](../00-meta/spec-conventions.md) — monetary values in cents, date format, naming rules
- `../03-calculations/tax-lot-tracking.md` — tax lot creation from reconciliation transactions

## Data Requirements

### New Enum Types

```sql
CREATE TYPE imports_status_enum AS ENUM (
    'pending',          -- parsed but not yet confirmed
    'confirmed',        -- user confirmed, transactions created
    'failed',           -- parsing or processing failed
    'cancelled'         -- user cancelled before confirmation
);

CREATE TYPE import_rows_match_status_enum AS ENUM (
    'auto_matched',     -- matched by ISIN
    'ticker_matched',   -- matched by ticker (less reliable)
    'manual_matched',   -- user manually mapped
    'unrecognized',     -- no match found, awaiting user action
    'skipped'           -- user chose to skip this row
);

CREATE TYPE import_rows_action_enum AS ENUM (
    'new_position',     -- first import: initial holding
    'quantity_increase',-- subsequent: infer buy
    'quantity_decrease',-- subsequent: infer sell
    'no_change',        -- position unchanged
    'position_closed'   -- position existed before but not in this import
);
```

### New Tables

#### `imports`

```sql
CREATE TABLE imports (
    id              BIGSERIAL       PRIMARY KEY,
    account_id      BIGINT          REFERENCES accounts(id),    -- NULL if account auto-detected or multi-account
    raw_text        TEXT            NOT NULL,                    -- original pasted text
    parser_version  VARCHAR(20)     NOT NULL DEFAULT '1.0',
    status          imports_status_enum NOT NULL DEFAULT 'pending',
    total_rows      INTEGER         NOT NULL DEFAULT 0,
    matched_rows    INTEGER         NOT NULL DEFAULT 0,
    unrecognized_rows INTEGER       NOT NULL DEFAULT 0,
    skipped_rows    INTEGER         NOT NULL DEFAULT 0,
    error_message   TEXT,
    imported_at     TIMESTAMPTZ,                                 -- when user confirmed
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT now()
);
```

**Indexes:**

```sql
CREATE INDEX idx_imports_status ON imports (status);
CREATE INDEX idx_imports_created_at ON imports (created_at DESC);
```

#### `import_rows`

Individual parsed rows from the import, with matching and reconciliation status.

```sql
CREATE TABLE import_rows (
    id                      BIGSERIAL       PRIMARY KEY,
    import_id               BIGINT          NOT NULL REFERENCES imports(id) ON DELETE CASCADE,
    row_number              INTEGER         NOT NULL,
    raw_instrument          VARCHAR(500),               -- original instrument name from Nordnet
    raw_isin                CHAR(12),                   -- ISIN from Nordnet
    raw_ticker              VARCHAR(50),                -- ticker from Nordnet
    raw_quantity            NUMERIC(18, 8),
    raw_avg_price           NUMERIC(18, 8),             -- stored as decimal from source
    raw_market_value        NUMERIC(18, 2),
    raw_currency            CHAR(3),
    raw_account_type        VARCHAR(50),                -- 'AF', 'OST', 'IPS', etc.
    security_id             BIGINT          REFERENCES securities(id),
    account_id              BIGINT          REFERENCES accounts(id),
    match_status            import_rows_match_status_enum NOT NULL DEFAULT 'unrecognized',
    action                  import_rows_action_enum,     -- determined during reconciliation
    quantity_before         NUMERIC(18, 8),              -- quantity in system before import
    quantity_delta          NUMERIC(18, 8),              -- change: raw_quantity - quantity_before
    transaction_id          BIGINT          REFERENCES transactions(id),  -- created reconciliation txn
    notes                   TEXT,
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT now(),

    CONSTRAINT chk_import_rows_currency_upper
        CHECK (raw_currency IS NULL OR raw_currency = upper(raw_currency))
);
```

**Indexes:**

```sql
CREATE INDEX idx_import_rows_import_id ON import_rows (import_id);
CREATE INDEX idx_import_rows_security_id ON import_rows (security_id);
CREATE INDEX idx_import_rows_match_status ON import_rows (match_status);
```

## API Endpoints

| Tag | Prefix | Feature |
|-----|--------|---------|
| Imports | `/imports` | F17 — Nordnet portfolio import |

| Method | Path | Description |
|--------|------|-------------|
| POST | `/imports/parse` | Parse pasted text and return preview. Body: `{ rawText, accountId? }`. Returns parsed rows with auto-matching results |
| GET | `/imports/{id}` | Get import detail with all rows |
| PUT | `/imports/{id}/rows/{rowId}/map` | Manually map an unrecognized row to a security. Body: `{ securityId }` or `{ action: "skip" }` or `{ action: "create", ticker, name, isin, assetClass, currency, exchange }` |
| POST | `/imports/{id}/confirm` | Confirm import — creates reconciliation transactions |
| POST | `/imports/{id}/cancel` | Cancel a pending import |
| GET | `/imports` | List past imports, paginated. Sort: `createdAt` desc |
| GET | `/imports/{id}/diff` | Show diff between this import and the previous confirmed import for the same account |

### Example Responses

**POST `/imports/parse`**

Request body:
```json
{
  "rawText": "Instrument\tISIN\tAntal\tGAV\tMarknadsvärde\tValuta\tKontotyp\nNeste Oyj\tFI0009013296\t150\t36,50\t5 775,00\tEUR\tAF\nApple Inc.\tUS0378331005\t25\t178,20\t4 455,00\tUSD\tAF\nNordea ETF Norden\tFI4000197777\t500\t12,45\t6 225,00\tEUR\tOST\n"
}
```

Response:
```json
{
  "data": {
    "importId": 42,
    "status": "pending",
    "totalRows": 3,
    "matchedRows": 2,
    "unrecognizedRows": 1,
    "rows": [
      {
        "rowId": 101,
        "rowNumber": 1,
        "rawInstrument": "Neste Oyj",
        "rawIsin": "FI0009013296",
        "rawQuantity": 150,
        "rawAvgPrice": 36.50,
        "rawMarketValue": 5775.00,
        "rawCurrency": "EUR",
        "rawAccountType": "AF",
        "matchStatus": "auto_matched",
        "securityId": 42,
        "matchedTicker": "NESTE",
        "matchedName": "Neste Oyj",
        "action": "no_change",
        "quantityBefore": 150,
        "quantityDelta": 0
      },
      {
        "rowId": 102,
        "rowNumber": 2,
        "rawInstrument": "Apple Inc.",
        "rawIsin": "US0378331005",
        "rawQuantity": 25,
        "rawAvgPrice": 178.20,
        "rawMarketValue": 4455.00,
        "rawCurrency": "USD",
        "rawAccountType": "AF",
        "matchStatus": "auto_matched",
        "securityId": 15,
        "matchedTicker": "AAPL",
        "matchedName": "Apple Inc.",
        "action": "quantity_increase",
        "quantityBefore": 20,
        "quantityDelta": 5
      },
      {
        "rowId": 103,
        "rowNumber": 3,
        "rawInstrument": "Nordea ETF Norden",
        "rawIsin": "FI4000197777",
        "rawQuantity": 500,
        "rawAvgPrice": 12.45,
        "rawMarketValue": 6225.00,
        "rawCurrency": "EUR",
        "rawAccountType": "OST",
        "matchStatus": "unrecognized",
        "securityId": null,
        "action": null
      }
    ]
  },
  "meta": { "timestamp": "2026-03-19T10:00:00Z", "cacheAge": null, "stale": false }
}
```

**GET `/imports/42/diff`**

```json
{
  "data": {
    "importId": 42,
    "previousImportId": 38,
    "previousImportDate": "2026-02-15T10:00:00Z",
    "changes": {
      "newPositions": [
        { "ticker": "NVDA", "name": "NVIDIA Corp.", "quantity": 10, "accountType": "AF" }
      ],
      "closedPositions": [
        { "ticker": "INTC", "name": "Intel Corp.", "previousQuantity": 50, "accountType": "AF" }
      ],
      "quantityChanges": [
        { "ticker": "AAPL", "name": "Apple Inc.", "previousQuantity": 20, "newQuantity": 25, "delta": 5, "accountType": "AF" }
      ],
      "unchanged": [
        { "ticker": "NESTE", "name": "Neste Oyj", "quantity": 150, "accountType": "AF" }
      ]
    }
  },
  "meta": { "timestamp": "2026-03-19T10:00:00Z", "cacheAge": null, "stale": false }
}
```

## Data Format

### Nordnet Export Format

Nordnet portfolio exports are typically tab-separated or semicolon-separated with the following characteristics:

- **Column separator**: tab (`\t`) or semicolon (`;`) — auto-detect
- **Decimal separator**: comma (`,`) for Finnish locale, period (`.`) for English locale — auto-detect
- **Thousands separator**: space (` `) in Finnish locale — strip before parsing
- **Encoding**: UTF-8 (may include BOM)
- **Header row**: always present as first row

**Expected columns** (Nordnet may use Finnish or Swedish headers):

| Expected Column | Finnish Header | Swedish Header | English Header | Type |
|----------------|----------------|----------------|----------------|------|
| Instrument name | Instrumentti / Arvopaperi | Instrument | Instrument | string |
| ISIN | ISIN | ISIN | ISIN | CHAR(12) |
| Ticker | Tunnus | Kortnamn | Ticker | string |
| Quantity | Määrä / Lukumäärä | Antal | Quantity | numeric |
| Average price | Keskihinta / GAV | GAV | Avg. Price | numeric |
| Market value | Markkina-arvo | Marknadsvärde | Market Value | numeric |
| Currency | Valuutta | Valuta | Currency | CHAR(3) |
| Account type | Tilityyppi | Kontotyp | Account Type | string |

### Account Type Mapping

| Nordnet Value | System Account Type | Notes |
|--------------|-------------------|-------|
| `AF` | `regular` | Arvo-osuustili (regular securities account) |
| `OST` | `osakesaastotili` | Osakesäästötili (equity savings account) |
| `IPS` | `pension` (subtype: `ps_sopimus`) | Individuellt pensionssparande |
| `KF` | `pension` (subtype: `kapitalisaatiosopimus`) | Kapitalförsäkring |
| `ISK` | `regular` | Swedish ISK — treated as regular for Finnish tax purposes |

### Parser Requirements

1. **Auto-detect separator**: try tab first, then semicolon, then comma. Choose the separator that produces the most consistent column count.
2. **Auto-detect decimal format**: check if numeric fields contain comma or period as decimal separator.
3. **Strip thousands separators**: remove spaces and thin spaces from numeric values before parsing.
4. **Header normalization**: map column headers to canonical names regardless of language (Finnish/Swedish/English). Use fuzzy matching if headers don't exactly match known variants.
5. **Encoding handling**: strip UTF-8 BOM if present. Handle Windows-style line endings (`\r\n`).
6. **Blank rows**: skip empty rows or rows where all fields are empty.

## UI Views

### Import Page

Full-page view with the following layout:

1. **Text area**: large paste-in area (minimum 10 rows visible) with placeholder text: "Paste your Nordnet portfolio export here..."
   - Accepts paste from clipboard (Ctrl+V / Cmd+V)
   - Drag-and-drop of text/CSV files accepted
   - "Parse" button below the text area

2. **Account selector**: optional dropdown to pre-select which account to import into. If omitted, account is auto-detected from the `rawAccountType` column.

### Preview Table

Shown after parsing, before confirmation:

| Column | Description |
|--------|-------------|
| # | Row number |
| Status | Match icon: green check (auto), yellow (ticker match), orange (manual), red X (unrecognized) |
| Instrument | Name from Nordnet |
| ISIN | ISIN from Nordnet |
| Matched Security | System security name + ticker (or "Unrecognized") |
| Quantity | Quantity from Nordnet |
| Avg Price | Average price from Nordnet |
| Currency | Currency |
| Account | Mapped account type |
| Action | New / Increase (+N) / Decrease (-N) / No Change / Closed |

- **Unrecognized rows** have action buttons: "Map to existing security" (opens search modal), "Create new security" (opens create form), "Skip" (exclude from import)
- **Summary bar** at top: "3 rows parsed: 2 auto-matched, 1 unrecognized"
- **Confirm Import** button: disabled until all rows are matched or skipped
- **Cancel** button: discards the pending import

### Mapping Review

For unrecognized securities, a modal with:

- **Search**: type-ahead search against the securities catalog (by ticker, ISIN, or name)
- **Create new**: form to add a new security to the catalog with fields pre-populated from the Nordnet data (instrument name, ISIN, ticker, currency)
- **Skip**: exclude this row from the import

### Import History

Table listing past imports:

| Column | Description |
|--------|-------------|
| Date | Import date |
| Account | Account(s) affected |
| Total Rows | Number of rows in the import |
| Matched | Successfully matched rows |
| Skipped | Skipped rows |
| Status | Pending / Confirmed / Failed / Cancelled |
| Actions | View details, view diff |

- Click a row to see full import detail (all parsed rows with their matches and actions)

### Diff View

Side-by-side or tabular comparison between current import and the last confirmed import:

- **New positions**: securities in this import but not in the previous (highlighted green)
- **Closed positions**: securities in the previous import but not in this one (highlighted red)
- **Quantity changes**: securities where quantity differs (highlighted yellow, showing +/- delta)
- **Unchanged**: securities with same quantity (dimmed)

## Business Rules

1. **ISIN is the primary matching key**: When matching Nordnet rows to system securities, ISIN is checked first. ISIN matches are highly reliable (unique per security globally) and result in `match_status = 'auto_matched'`.

2. **Ticker as fallback match**: If ISIN is not available or not found in the catalog, fall back to ticker matching. Ticker matches are less reliable (same ticker on different exchanges) and result in `match_status = 'ticker_matched'` with a warning displayed in the UI.

3. **Unrecognized securities**: If neither ISIN nor ticker produces a match, the row is marked `match_status = 'unrecognized'`. The user must either map it to an existing security, create a new security, or skip it before confirming the import.

4. **First import — initial holdings**: On the first import for an account (no previous confirmed import exists), all matched rows create positions as initial holdings. A `transfer_in` transaction is created for each position with the import date as the transaction date and the Nordnet average price as the cost basis. No transaction history is inferred.

5. **Subsequent imports — reconciliation**:
   - If a security's quantity **increased**: create a `buy` transaction for the delta quantity. Use the Nordnet average price as an estimate (note: this is approximate since the actual trade price may differ).
   - If a security's quantity **decreased**: create a `sell` transaction for the delta quantity. Use the current market price (or Nordnet market value / quantity) as the sell price.
   - If a security's quantity is **unchanged**: no transaction created.
   - If a security is **no longer in the import** but existed before: create a `sell` transaction for the full remaining quantity (position closed).

6. **Never delete user-entered transactions**: Reconciliation transactions are additive. The import process never modifies or deletes transactions that were manually entered by the user. Reconciliation transactions are tagged with `source = 'nordnet_import'` in the transaction metadata for traceability.

7. **Multiple account types**: A single Nordnet paste may contain rows from multiple account types (AF, OST, IPS). The parser groups rows by `rawAccountType` and maps each to the appropriate system account. If the system account does not exist, prompt the user to create it.

8. **Osakesaastotili handling**: Rows with `rawAccountType = 'OST'` are imported into the osakesaastotili account. The import does NOT update `osa_deposit_total_cents` automatically (deposit tracking requires actual deposit transactions, not position snapshots).

9. **Idempotency**: Confirming the same import twice is a no-op (the system checks if the import is already confirmed). Re-parsing the same text creates a new pending import.

10. **Average price precision**: Nordnet reports average price with 2-4 decimal places. Store as `NUMERIC(18, 8)` in `import_rows`. Convert to cents (integer) when creating transactions: `price_cents = round(raw_avg_price * 100)`.

## Edge Cases

1. **Empty paste**: If the user pastes empty text or whitespace only, return a validation error: "No data found. Please paste your Nordnet portfolio export."
2. **Malformed data**: If the parser cannot identify at least 3 expected columns, return an error with details: "Could not parse the pasted data. Expected tab-separated or semicolon-separated columns with headers."
3. **Partial match**: Some rows match, others don't. The import can proceed with matched rows only if unrecognized rows are explicitly skipped.
4. **Duplicate ISIN in paste**: If the same ISIN appears twice (e.g., same security in different rows due to export formatting), merge quantities before matching.
5. **Zero quantity rows**: Nordnet may include rows with quantity 0 (fully sold positions still showing in the overview). Skip these rows with a note in the UI.
6. **Negative quantity**: Should not occur in Nordnet exports. If detected, flag as a parsing error and skip the row.
7. **Currency mismatch**: If the Nordnet currency for a security differs from the system security's native currency, flag a warning but proceed (could be due to different listing exchanges).
8. **Very large imports**: Nordnet portfolios are unlikely to exceed a few hundred rows. No special handling needed for performance, but set a maximum of 1,000 rows per import as a sanity check.
9. **Re-import after partial confirmation**: If the user starts an import, maps some securities, then navigates away, the pending import is preserved. They can return and continue mapping via the import history page.
10. **Multi-currency account**: A single Nordnet account may hold securities in multiple currencies (EUR, USD, SEK). Each row has its own currency; the account currency is the base currency for reporting.

## Acceptance Criteria

1. Pasting Nordnet tab-separated or semicolon-separated data into the text area and clicking "Parse" produces a preview table with correctly parsed rows.
2. Finnish locale (comma decimal, space thousands separator) is handled correctly.
3. ISIN-based matching correctly links rows to existing securities in the catalog.
4. Ticker-based fallback matching works when ISIN is not available, with a lower-confidence indicator.
5. Unrecognized securities can be mapped to existing, created as new, or skipped.
6. "Confirm Import" is disabled until all rows are matched or skipped.
7. First import creates `transfer_in` transactions for all matched rows.
8. Subsequent imports detect quantity changes and create appropriate buy/sell reconciliation transactions.
9. Diff view correctly shows new positions, closed positions, quantity changes, and unchanged positions.
10. Multiple account types (AF, OST, IPS) in a single paste are correctly routed to the appropriate system accounts.
11. Import history shows all past imports with status and row counts.
12. User-entered transactions are never modified or deleted by the import process.
13. All monetary values follow the cents convention with currency codes in created transactions.
14. The raw pasted text is preserved in the `imports` table for auditability.

## Changelog

| Date | Change |
|------|--------|
| 2026-03-19 | Initial draft |
