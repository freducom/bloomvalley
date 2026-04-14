# Data Model

The complete database schema for the Bloomvalley terminal. This is the foundational spec: every feature, pipeline, calculation, and API endpoint depends on these table definitions. The schema runs on PostgreSQL 16 with TimescaleDB 2.x, managed through SQLAlchemy 2.0 and Alembic migrations.

**Status: DRAFT**

## Dependencies

- [Spec Conventions](../00-meta/spec-conventions.md) — naming rules, monetary format, date format
- [Architecture](../01-system/architecture.md) — tech stack, deployment topology

---

## Enum Type Definitions

All enums are created as PostgreSQL `CREATE TYPE` before the tables that reference them.

```sql
CREATE TYPE accounts_type_enum AS ENUM (
    'regular',
    'osakesaastotili',
    'crypto_wallet',
    'pension'
);

CREATE TYPE accounts_pension_subtype_enum AS ENUM (
    'ps_sopimus',
    'kapitalisaatiosopimus'
);

CREATE TYPE securities_asset_class_enum AS ENUM (
    'stock',
    'bond',
    'etf',
    'crypto'
);

CREATE TYPE transactions_type_enum AS ENUM (
    'buy',
    'sell',
    'dividend',
    'transfer_in',
    'transfer_out',
    'fee',
    'interest',
    'corporate_action',
    'deposit',
    'withdrawal'
);

CREATE TYPE tax_lots_state_enum AS ENUM (
    'open',
    'partially_closed',
    'closed'
);

CREATE TYPE corporate_actions_type_enum AS ENUM (
    'split',
    'reverse_split',
    'merger',
    'spinoff',
    'name_change',
    'ticker_change',
    'delisting'
);

CREATE TYPE alerts_type_enum AS ENUM (
    'price_above',
    'price_below',
    'drift_threshold',
    'staleness',
    'dividend_announced',
    'custom'
);

CREATE TYPE alerts_status_enum AS ENUM (
    'active',
    'triggered',
    'dismissed',
    'expired'
);

CREATE TYPE pipeline_runs_status_enum AS ENUM (
    'running',
    'success',
    'failed',
    'partial'
);

CREATE TYPE pipeline_runs_source_enum AS ENUM (
    'yahoo_finance',
    'alpha_vantage',
    'fred',
    'ecb',
    'coingecko',
    'justetf',
    'morningstar',
    'manual'
);
```

---

## Tables — Core Portfolio

### `accounts`

Represents a brokerage account, savings account, or crypto wallet. Finnish tax-advantaged account types are modeled as distinct `type` values with tax logic handled at the application layer.

```sql
CREATE TABLE accounts (
    id              BIGSERIAL       PRIMARY KEY,
    name            VARCHAR(100)    NOT NULL,
    type            accounts_type_enum NOT NULL,
    pension_subtype accounts_pension_subtype_enum,  -- only when type = 'pension'
    institution     VARCHAR(100),                    -- e.g. 'Nordnet', 'Coinbase'
    currency        CHAR(3)         NOT NULL DEFAULT 'EUR',
    osa_deposit_total_cents BIGINT  NOT NULL DEFAULT 0,
        -- running total of deposits into osakesaastotili (max 50 000 EUR)
    notes           TEXT,
    is_active       BOOLEAN         NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),

    CONSTRAINT chk_accounts_pension_subtype
        CHECK (
            (type = 'pension' AND pension_subtype IS NOT NULL) OR
            (type <> 'pension' AND pension_subtype IS NULL)
        ),
    CONSTRAINT chk_accounts_osa_deposit
        CHECK (
            (type = 'osakesaastotili' AND osa_deposit_total_cents >= 0
             AND osa_deposit_total_cents <= 5000000) OR
            (type <> 'osakesaastotili' AND osa_deposit_total_cents = 0)
        ),
    CONSTRAINT chk_accounts_currency_upper
        CHECK (currency = upper(currency))
);
```

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | `BIGSERIAL` | NO | auto | Primary key |
| `name` | `VARCHAR(100)` | NO | | Human-readable account name |
| `type` | `accounts_type_enum` | NO | | Account type determining tax treatment |
| `pension_subtype` | `accounts_pension_subtype_enum` | YES | `NULL` | Required when `type = 'pension'` |
| `institution` | `VARCHAR(100)` | YES | `NULL` | Broker or exchange name |
| `currency` | `CHAR(3)` | NO | `'EUR'` | Base currency of the account (ISO 4217) |
| `osa_deposit_total_cents` | `BIGINT` | NO | `0` | Cumulative deposits for osakesaastotili; enforced max 50 000 EUR |
| `notes` | `TEXT` | YES | `NULL` | Free-text notes |
| `is_active` | `BOOLEAN` | NO | `TRUE` | Soft-delete flag |
| `created_at` | `TIMESTAMPTZ` | NO | `now()` | Row creation timestamp |
| `updated_at` | `TIMESTAMPTZ` | NO | `now()` | Last modification timestamp |

**Indexes:**

```sql
CREATE INDEX idx_accounts_type ON accounts (type);
CREATE INDEX idx_accounts_is_active ON accounts (is_active) WHERE is_active = TRUE;
```

---

### `securities`

Master catalog of all tradeable instruments. Each security has exactly one row regardless of how many accounts hold it.

```sql
CREATE TABLE securities (
    id              BIGSERIAL       PRIMARY KEY,
    ticker          VARCHAR(20)     NOT NULL,
    isin            CHAR(12),                       -- NULL for crypto
    name            VARCHAR(255)    NOT NULL,
    asset_class     securities_asset_class_enum NOT NULL,
    currency        CHAR(3)         NOT NULL,       -- native trading currency
    exchange        VARCHAR(20),                     -- e.g. 'XHEL', 'XNAS', 'XNYS'; NULL for crypto
    sector          VARCHAR(100),
    industry        VARCHAR(100),
    country         CHAR(2),                         -- ISO 3166-1 alpha-2
    is_accumulating BOOLEAN,                         -- for ETFs: ACC vs DIST
    coingecko_id    VARCHAR(100),                    -- for crypto mapping
    openfigi        VARCHAR(12),                     -- FIGI identifier
    morningstar_id  VARCHAR(20),                     -- Morningstar SecId
    company_group   VARCHAR(100),                    -- groups share classes (e.g. 'Kesko' for A+B)
    is_active       BOOLEAN         NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),

    CONSTRAINT chk_securities_currency_upper
        CHECK (currency = upper(currency))
);
```

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | `BIGSERIAL` | NO | auto | Primary key |
| `ticker` | `VARCHAR(20)` | NO | | Ticker symbol (e.g. `AAPL`, `BTC`) |
| `isin` | `CHAR(12)` | YES | `NULL` | ISIN code; NULL for crypto |
| `name` | `VARCHAR(255)` | NO | | Full instrument name |
| `asset_class` | `securities_asset_class_enum` | NO | | stock, bond, etf, or crypto |
| `currency` | `CHAR(3)` | NO | | Native trading currency (ISO 4217) |
| `exchange` | `VARCHAR(20)` | YES | `NULL` | MIC code of the exchange |
| `sector` | `VARCHAR(100)` | YES | `NULL` | GICS sector |
| `industry` | `VARCHAR(100)` | YES | `NULL` | GICS industry |
| `country` | `CHAR(2)` | YES | `NULL` | Country of domicile (ISO 3166-1) |
| `is_accumulating` | `BOOLEAN` | YES | `NULL` | ETF distribution policy; NULL for non-ETFs |
| `coingecko_id` | `VARCHAR(100)` | YES | `NULL` | CoinGecko API identifier |
| `openfigi` | `VARCHAR(12)` | YES | `NULL` | OpenFIGI identifier |
| `morningstar_id` | `VARCHAR(20)` | YES | `NULL` | Morningstar SecId for data lookups |
| `company_group` | `VARCHAR(100)` | YES | `NULL` | Groups share classes as one company (e.g. Kesko A+B both have `"Kesko"`). Portfolio analysis aggregates by this field for weights/exposure. |
| `is_active` | `BOOLEAN` | NO | `TRUE` | FALSE if delisted |
| `created_at` | `TIMESTAMPTZ` | NO | `now()` | Row creation timestamp |
| `updated_at` | `TIMESTAMPTZ` | NO | `now()` | Last modification timestamp |

**Indexes:**

```sql
CREATE UNIQUE INDEX idx_securities_ticker_exchange ON securities (ticker, exchange)
    WHERE exchange IS NOT NULL;
CREATE UNIQUE INDEX idx_securities_ticker_crypto ON securities (ticker)
    WHERE asset_class = 'crypto';
CREATE UNIQUE INDEX idx_securities_isin ON securities (isin)
    WHERE isin IS NOT NULL;
CREATE INDEX idx_securities_asset_class ON securities (asset_class);
CREATE INDEX idx_securities_name_trgm ON securities USING gin (name gin_trgm_ops);
```

---

### `transactions`

Every portfolio event that changes a position, balance, or cost basis. Each row is a single atomic event.

```sql
CREATE TABLE transactions (
    id              BIGSERIAL       PRIMARY KEY,
    account_id      BIGINT          NOT NULL REFERENCES accounts(id),
    security_id     BIGINT          REFERENCES securities(id),
        -- NULL for deposits, withdrawals, and account-level fees
    type            transactions_type_enum NOT NULL,
    trade_date      DATE            NOT NULL,
    settlement_date DATE,
    quantity        NUMERIC(28, 18) NOT NULL DEFAULT 0,
        -- positive for buys/transfers_in, negative for sells/transfers_out
    price_cents     BIGINT,         -- per-unit price in security's currency
    price_currency  CHAR(3),
    total_cents     BIGINT          NOT NULL,
        -- total amount in account currency (price * qty * fx, excluding fees)
    fee_cents       BIGINT          NOT NULL DEFAULT 0,
    fee_currency    CHAR(3)         NOT NULL DEFAULT 'EUR',
    fx_rate         NUMERIC(12, 6), -- rate from price_currency to account currency at trade time
    currency        CHAR(3)         NOT NULL DEFAULT 'EUR',
        -- account currency (denominator for total_cents)
    withholding_tax_cents BIGINT    NOT NULL DEFAULT 0,
        -- for dividends: tax withheld at source
    notes           TEXT,
    external_ref    VARCHAR(255),   -- broker reference / transaction ID
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),

    CONSTRAINT fk_transactions_accounts
        FOREIGN KEY (account_id) REFERENCES accounts(id),
    CONSTRAINT fk_transactions_securities
        FOREIGN KEY (security_id) REFERENCES securities(id),
    CONSTRAINT chk_transactions_currency_upper
        CHECK (currency = upper(currency)),
    CONSTRAINT chk_transactions_fee_non_negative
        CHECK (fee_cents >= 0),
    CONSTRAINT chk_transactions_withholding_non_negative
        CHECK (withholding_tax_cents >= 0)
);
```

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | `BIGSERIAL` | NO | auto | Primary key |
| `account_id` | `BIGINT` | NO | | FK to `accounts` |
| `security_id` | `BIGINT` | YES | `NULL` | FK to `securities`; NULL for cash events |
| `type` | `transactions_type_enum` | NO | | Event type |
| `trade_date` | `DATE` | NO | | Date the trade was executed |
| `settlement_date` | `DATE` | YES | `NULL` | Settlement date (T+2 for stocks) |
| `quantity` | `NUMERIC(28,18)` | NO | `0` | Signed quantity; positive = inflow, negative = outflow |
| `price_cents` | `BIGINT` | YES | `NULL` | Per-unit price in `price_currency` cents |
| `price_currency` | `CHAR(3)` | YES | `NULL` | Currency of the per-unit price |
| `total_cents` | `BIGINT` | NO | | Total value in account currency cents |
| `fee_cents` | `BIGINT` | NO | `0` | Transaction fees in `fee_currency` cents |
| `fee_currency` | `CHAR(3)` | NO | `'EUR'` | Currency of the fee |
| `fx_rate` | `NUMERIC(12,6)` | YES | `NULL` | FX rate applied (price currency to account currency) |
| `currency` | `CHAR(3)` | NO | `'EUR'` | Account's base currency |
| `withholding_tax_cents` | `BIGINT` | NO | `0` | Withholding tax on dividends |
| `notes` | `TEXT` | YES | `NULL` | Free-text notes |
| `external_ref` | `VARCHAR(255)` | YES | `NULL` | Broker/exchange reference ID |
| `created_at` | `TIMESTAMPTZ` | NO | `now()` | Row creation timestamp |
| `updated_at` | `TIMESTAMPTZ` | NO | `now()` | Last modification timestamp |

**Indexes:**

```sql
CREATE INDEX idx_transactions_account_id ON transactions (account_id);
CREATE INDEX idx_transactions_security_id ON transactions (security_id);
CREATE INDEX idx_transactions_trade_date ON transactions (trade_date);
CREATE INDEX idx_transactions_type ON transactions (type);
CREATE INDEX idx_transactions_account_security_date
    ON transactions (account_id, security_id, trade_date);
```

---

### `tax_lots`

Specific identification tax lot tracking. Each buy creates a lot; each sell partially or fully closes one or more lots. Cost basis includes fees allocated to the lot.

```sql
CREATE TABLE tax_lots (
    id                  BIGSERIAL       PRIMARY KEY,
    account_id          BIGINT          NOT NULL REFERENCES accounts(id),
    security_id         BIGINT          NOT NULL REFERENCES securities(id),
    open_transaction_id BIGINT          NOT NULL REFERENCES transactions(id),
    close_transaction_id BIGINT         REFERENCES transactions(id),
        -- NULL while open; set when fully or partially closed
    state               tax_lots_state_enum NOT NULL DEFAULT 'open',
    acquired_date       DATE            NOT NULL,
    closed_date         DATE,
    original_quantity   NUMERIC(28, 18) NOT NULL,
        -- quantity at lot creation
    remaining_quantity  NUMERIC(28, 18) NOT NULL,
        -- current open quantity (= original_quantity when fully open)
    cost_basis_cents    BIGINT          NOT NULL,
        -- total cost including allocated fees, in account currency
    cost_basis_currency CHAR(3)         NOT NULL DEFAULT 'EUR',
    proceeds_cents      BIGINT,
        -- total proceeds when closed (net of fees), in account currency
    realized_pnl_cents  BIGINT,
        -- proceeds - (cost_basis * closed_fraction), computed on close
    fx_rate_at_open     NUMERIC(12, 6),
        -- FX rate at acquisition (for multi-currency lots)
    fx_rate_at_close    NUMERIC(12, 6),
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT now(),

    CONSTRAINT fk_tax_lots_accounts
        FOREIGN KEY (account_id) REFERENCES accounts(id),
    CONSTRAINT fk_tax_lots_securities
        FOREIGN KEY (security_id) REFERENCES securities(id),
    CONSTRAINT fk_tax_lots_open_transaction
        FOREIGN KEY (open_transaction_id) REFERENCES transactions(id),
    CONSTRAINT fk_tax_lots_close_transaction
        FOREIGN KEY (close_transaction_id) REFERENCES transactions(id),
    CONSTRAINT chk_tax_lots_quantity_positive
        CHECK (original_quantity > 0 AND remaining_quantity >= 0),
    CONSTRAINT chk_tax_lots_remaining_lte_original
        CHECK (remaining_quantity <= original_quantity),
    CONSTRAINT chk_tax_lots_closed_has_date
        CHECK (
            (state = 'closed' AND closed_date IS NOT NULL) OR
            (state <> 'closed')
        )
);
```

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | `BIGSERIAL` | NO | auto | Primary key |
| `account_id` | `BIGINT` | NO | | FK to `accounts` |
| `security_id` | `BIGINT` | NO | | FK to `securities` |
| `open_transaction_id` | `BIGINT` | NO | | FK to the buy `transactions` row |
| `close_transaction_id` | `BIGINT` | YES | `NULL` | FK to the sell `transactions` row; NULL while open |
| `state` | `tax_lots_state_enum` | NO | `'open'` | open, partially_closed, or closed |
| `acquired_date` | `DATE` | NO | | Date the lot was acquired |
| `closed_date` | `DATE` | YES | `NULL` | Date the lot was fully closed |
| `original_quantity` | `NUMERIC(28,18)` | NO | | Quantity at lot creation |
| `remaining_quantity` | `NUMERIC(28,18)` | NO | | Currently open quantity |
| `cost_basis_cents` | `BIGINT` | NO | | Total cost basis in account currency cents (including fees) |
| `cost_basis_currency` | `CHAR(3)` | NO | `'EUR'` | Currency of cost basis |
| `proceeds_cents` | `BIGINT` | YES | `NULL` | Proceeds from closing the lot |
| `realized_pnl_cents` | `BIGINT` | YES | `NULL` | Realized profit/loss in account currency cents |
| `fx_rate_at_open` | `NUMERIC(12,6)` | YES | `NULL` | FX rate at acquisition |
| `fx_rate_at_close` | `NUMERIC(12,6)` | YES | `NULL` | FX rate at disposal |
| `created_at` | `TIMESTAMPTZ` | NO | `now()` | Row creation timestamp |
| `updated_at` | `TIMESTAMPTZ` | NO | `now()` | Last modification timestamp |

**Design note on partial closes:** When a sell closes only part of a lot, the application creates a new `tax_lots` row for the closed portion (with `state = 'closed'`) and updates the original lot's `remaining_quantity`. The `close_transaction_id` on the closed portion points to the sell transaction. This allows a single sell to close multiple lots (specific identification).

**Indexes:**

```sql
CREATE INDEX idx_tax_lots_account_id ON tax_lots (account_id);
CREATE INDEX idx_tax_lots_security_id ON tax_lots (security_id);
CREATE INDEX idx_tax_lots_state ON tax_lots (state);
CREATE INDEX idx_tax_lots_open_transaction_id ON tax_lots (open_transaction_id);
CREATE INDEX idx_tax_lots_account_security_state
    ON tax_lots (account_id, security_id, state);
CREATE INDEX idx_tax_lots_acquired_date ON tax_lots (acquired_date);
```

---

### `holdings_snapshot`

Materialized daily snapshot of all positions. Rebuilt nightly after market close. Provides fast point-in-time portfolio queries without scanning the full transaction history.

```sql
CREATE TABLE holdings_snapshot (
    id              BIGSERIAL       PRIMARY KEY,
    snapshot_date   DATE            NOT NULL,
    account_id      BIGINT          NOT NULL REFERENCES accounts(id),
    security_id     BIGINT          NOT NULL REFERENCES securities(id),
    quantity        NUMERIC(28, 18) NOT NULL,
    cost_basis_cents BIGINT         NOT NULL,
        -- aggregate cost basis of all open lots
    cost_basis_currency CHAR(3)     NOT NULL DEFAULT 'EUR',
    market_price_cents BIGINT       NOT NULL,
        -- closing price in security's native currency
    market_price_currency CHAR(3)   NOT NULL,
    market_value_eur_cents BIGINT   NOT NULL,
        -- quantity * market_price * fx_rate, converted to EUR
    unrealized_pnl_eur_cents BIGINT NOT NULL,
        -- market_value_eur - cost_basis (both in EUR)
    fx_rate         NUMERIC(12, 6),
        -- FX rate used for EUR conversion
    weight_pct      NUMERIC(7, 4),
        -- position weight as % of total portfolio value
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),

    CONSTRAINT fk_holdings_snapshot_accounts
        FOREIGN KEY (account_id) REFERENCES accounts(id),
    CONSTRAINT fk_holdings_snapshot_securities
        FOREIGN KEY (security_id) REFERENCES securities(id)
);
```

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | `BIGSERIAL` | NO | auto | Primary key |
| `snapshot_date` | `DATE` | NO | | Date of the snapshot |
| `account_id` | `BIGINT` | NO | | FK to `accounts` |
| `security_id` | `BIGINT` | NO | | FK to `securities` |
| `quantity` | `NUMERIC(28,18)` | NO | | Total open quantity |
| `cost_basis_cents` | `BIGINT` | NO | | Aggregate cost basis (EUR cents) |
| `cost_basis_currency` | `CHAR(3)` | NO | `'EUR'` | Always EUR for snapshot |
| `market_price_cents` | `BIGINT` | NO | | Closing price in native currency cents |
| `market_price_currency` | `CHAR(3)` | NO | | Native currency of the price |
| `market_value_eur_cents` | `BIGINT` | NO | | EUR market value in cents |
| `unrealized_pnl_eur_cents` | `BIGINT` | NO | | Unrealized P&L in EUR cents |
| `fx_rate` | `NUMERIC(12,6)` | YES | `NULL` | FX rate used; NULL when security is EUR |
| `weight_pct` | `NUMERIC(7,4)` | YES | `NULL` | % of total portfolio |
| `created_at` | `TIMESTAMPTZ` | NO | `now()` | When snapshot was generated |

**Indexes:**

```sql
CREATE UNIQUE INDEX idx_holdings_snapshot_date_account_security
    ON holdings_snapshot (snapshot_date, account_id, security_id);
CREATE INDEX idx_holdings_snapshot_date ON holdings_snapshot (snapshot_date);
CREATE INDEX idx_holdings_snapshot_security_id ON holdings_snapshot (security_id);
```

---

### `dividends`

Dividend payment records with withholding tax tracking. Each row represents a single dividend event for a security held in an account.

```sql
CREATE TABLE dividends (
    id                  BIGSERIAL       PRIMARY KEY,
    account_id          BIGINT          NOT NULL REFERENCES accounts(id),
    security_id         BIGINT          NOT NULL REFERENCES securities(id),
    transaction_id      BIGINT          REFERENCES transactions(id),
        -- link to the corresponding transaction record
    ex_date             DATE            NOT NULL,
    pay_date            DATE,
    record_date         DATE,
    amount_per_share_cents BIGINT       NOT NULL,
        -- gross dividend per share in security's currency
    amount_currency     CHAR(3)         NOT NULL,
    shares_held         NUMERIC(18, 8)  NOT NULL,
        -- quantity held on record date
    gross_amount_cents  BIGINT          NOT NULL,
        -- total gross dividend in security's currency
    withholding_tax_cents BIGINT        NOT NULL DEFAULT 0,
        -- tax withheld at source (e.g. 15% US, 30% default)
    withholding_tax_pct NUMERIC(5, 2),
        -- withholding rate applied
    net_amount_cents    BIGINT          NOT NULL,
        -- gross - withholding, in security's currency
    net_amount_eur_cents BIGINT         NOT NULL,
        -- net amount converted to EUR
    fx_rate             NUMERIC(12, 6),
    is_qualified        BOOLEAN,
        -- whether tax treaty rate was applied
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT now(),

    CONSTRAINT fk_dividends_accounts
        FOREIGN KEY (account_id) REFERENCES accounts(id),
    CONSTRAINT fk_dividends_securities
        FOREIGN KEY (security_id) REFERENCES securities(id),
    CONSTRAINT fk_dividends_transactions
        FOREIGN KEY (transaction_id) REFERENCES transactions(id),
    CONSTRAINT chk_dividends_net_amount
        CHECK (net_amount_cents = gross_amount_cents - withholding_tax_cents)
);
```

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | `BIGSERIAL` | NO | auto | Primary key |
| `account_id` | `BIGINT` | NO | | FK to `accounts` |
| `security_id` | `BIGINT` | NO | | FK to `securities` |
| `transaction_id` | `BIGINT` | YES | `NULL` | FK to corresponding `transactions` row |
| `ex_date` | `DATE` | NO | | Ex-dividend date |
| `pay_date` | `DATE` | YES | `NULL` | Payment date |
| `record_date` | `DATE` | YES | `NULL` | Record date |
| `amount_per_share_cents` | `BIGINT` | NO | | Gross dividend per share (native currency cents) |
| `amount_currency` | `CHAR(3)` | NO | | Dividend currency |
| `shares_held` | `NUMERIC(18,8)` | NO | | Shares held on record date |
| `gross_amount_cents` | `BIGINT` | NO | | Total gross dividend (native currency cents) |
| `withholding_tax_cents` | `BIGINT` | NO | `0` | Tax withheld at source |
| `withholding_tax_pct` | `NUMERIC(5,2)` | YES | `NULL` | Withholding rate (e.g. 15.00 for 15%) |
| `net_amount_cents` | `BIGINT` | NO | | Net after withholding (native currency cents) |
| `net_amount_eur_cents` | `BIGINT` | NO | | Net amount converted to EUR cents |
| `fx_rate` | `NUMERIC(12,6)` | YES | `NULL` | FX rate used for EUR conversion |
| `is_qualified` | `BOOLEAN` | YES | `NULL` | Whether treaty rate was applied |
| `created_at` | `TIMESTAMPTZ` | NO | `now()` | Row creation timestamp |
| `updated_at` | `TIMESTAMPTZ` | NO | `now()` | Last modification timestamp |

**Indexes:**

```sql
CREATE INDEX idx_dividends_account_id ON dividends (account_id);
CREATE INDEX idx_dividends_security_id ON dividends (security_id);
CREATE INDEX idx_dividends_ex_date ON dividends (ex_date);
CREATE INDEX idx_dividends_account_security_ex_date
    ON dividends (account_id, security_id, ex_date);
```

---

### `corporate_actions`

Records of stock splits, mergers, spinoffs, and other corporate events that affect holdings and tax lots. Processing a corporate action adjusts the `tax_lots` and `holdings_snapshot` tables via application logic.

```sql
CREATE TABLE corporate_actions (
    id              BIGSERIAL       PRIMARY KEY,
    security_id     BIGINT          NOT NULL REFERENCES securities(id),
    type            corporate_actions_type_enum NOT NULL,
    effective_date  DATE            NOT NULL,
    ratio_from      NUMERIC(12, 6), -- e.g. 1 (for a 4:1 split)
    ratio_to        NUMERIC(12, 6), -- e.g. 4 (for a 4:1 split)
    new_security_id BIGINT          REFERENCES securities(id),
        -- for mergers/spinoffs: the resulting security
    cash_in_lieu_cents BIGINT,
        -- cash paid for fractional shares
    cash_currency   CHAR(3),
    description     TEXT            NOT NULL,
    is_processed    BOOLEAN         NOT NULL DEFAULT FALSE,
        -- TRUE once tax lots have been adjusted
    processed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),

    CONSTRAINT fk_corporate_actions_securities
        FOREIGN KEY (security_id) REFERENCES securities(id),
    CONSTRAINT fk_corporate_actions_new_security
        FOREIGN KEY (new_security_id) REFERENCES securities(id),
    CONSTRAINT chk_corporate_actions_ratio
        CHECK (
            (type IN ('split', 'reverse_split') AND ratio_from IS NOT NULL AND ratio_to IS NOT NULL) OR
            (type NOT IN ('split', 'reverse_split'))
        )
);
```

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | `BIGSERIAL` | NO | auto | Primary key |
| `security_id` | `BIGINT` | NO | | FK to the affected security |
| `type` | `corporate_actions_type_enum` | NO | | Type of corporate action |
| `effective_date` | `DATE` | NO | | Date the action takes effect |
| `ratio_from` | `NUMERIC(12,6)` | YES | `NULL` | Split/reverse-split "from" (e.g. 1 in 4:1) |
| `ratio_to` | `NUMERIC(12,6)` | YES | `NULL` | Split/reverse-split "to" (e.g. 4 in 4:1) |
| `new_security_id` | `BIGINT` | YES | `NULL` | Resulting security for mergers/spinoffs |
| `cash_in_lieu_cents` | `BIGINT` | YES | `NULL` | Cash for fractional shares |
| `cash_currency` | `CHAR(3)` | YES | `NULL` | Currency of cash-in-lieu |
| `description` | `TEXT` | NO | | Human-readable description |
| `is_processed` | `BOOLEAN` | NO | `FALSE` | Whether tax lots have been adjusted |
| `processed_at` | `TIMESTAMPTZ` | YES | `NULL` | When processing occurred |
| `created_at` | `TIMESTAMPTZ` | NO | `now()` | Row creation timestamp |
| `updated_at` | `TIMESTAMPTZ` | NO | `now()` | Last modification timestamp |

**Indexes:**

```sql
CREATE INDEX idx_corporate_actions_security_id ON corporate_actions (security_id);
CREATE INDEX idx_corporate_actions_effective_date ON corporate_actions (effective_date);
CREATE INDEX idx_corporate_actions_is_processed
    ON corporate_actions (is_processed) WHERE is_processed = FALSE;
```

---

## Tables — Market Data (TimescaleDB Hypertables)

### `prices`

Daily OHLCV price data for all securities. Designated as a TimescaleDB hypertable with 1-month chunk interval. All price values stored as integers (cents).

```sql
CREATE TABLE prices (
    security_id     BIGINT          NOT NULL REFERENCES securities(id),
    date            DATE            NOT NULL,
    open_cents      BIGINT,
    high_cents      BIGINT,
    low_cents       BIGINT,
    close_cents     BIGINT          NOT NULL,
    adjusted_close_cents BIGINT,    -- adjusted for splits/dividends
    volume          BIGINT,
    currency        CHAR(3)         NOT NULL,
    source          pipeline_runs_source_enum NOT NULL DEFAULT 'yahoo_finance',
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),

    CONSTRAINT fk_prices_securities
        FOREIGN KEY (security_id) REFERENCES securities(id),
    CONSTRAINT chk_prices_ohlc
        CHECK (
            high_cents >= low_cents
            AND high_cents >= open_cents
            AND high_cents >= close_cents
            AND low_cents <= open_cents
            AND low_cents <= close_cents
        )
);

-- Primary key as unique index (TimescaleDB requirement)
SELECT create_hypertable('prices', 'date', chunk_time_interval => INTERVAL '1 month');
CREATE UNIQUE INDEX idx_prices_security_id_date ON prices (security_id, date);
```

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `security_id` | `BIGINT` | NO | | FK to `securities` |
| `date` | `DATE` | NO | | Trading date |
| `open_cents` | `BIGINT` | YES | `NULL` | Opening price in cents |
| `high_cents` | `BIGINT` | YES | `NULL` | High price in cents |
| `low_cents` | `BIGINT` | YES | `NULL` | Low price in cents |
| `close_cents` | `BIGINT` | NO | | Closing price in cents |
| `adjusted_close_cents` | `BIGINT` | YES | `NULL` | Split/dividend-adjusted close |
| `volume` | `BIGINT` | YES | `NULL` | Trading volume |
| `currency` | `CHAR(3)` | NO | | Price currency |
| `source` | `pipeline_runs_source_enum` | NO | `'yahoo_finance'` | Data source |
| `created_at` | `TIMESTAMPTZ` | NO | `now()` | Row creation timestamp |

**Hypertable:** chunk interval = 1 month (optimized for "last N days" queries).

**Indexes:**

```sql
CREATE INDEX idx_prices_date ON prices (date DESC);
CREATE INDEX idx_prices_security_id ON prices (security_id);
```

---

### `fx_rates`

Daily exchange rates with EUR as the base currency. All rates express "1 EUR = X foreign currency." To convert from foreign to EUR, divide by the rate.

```sql
CREATE TABLE fx_rates (
    base_currency   CHAR(3)         NOT NULL DEFAULT 'EUR',
    quote_currency  CHAR(3)         NOT NULL,
    date            DATE            NOT NULL,
    rate            NUMERIC(12, 6)  NOT NULL,
        -- 1 base = rate quote (e.g. EUR/USD = 1.0850)
    source          pipeline_runs_source_enum NOT NULL DEFAULT 'ecb',
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),

    CONSTRAINT chk_fx_rates_rate_positive
        CHECK (rate > 0),
    CONSTRAINT chk_fx_rates_base_eur
        CHECK (base_currency = 'EUR')
);

SELECT create_hypertable('fx_rates', 'date', chunk_time_interval => INTERVAL '1 month');
CREATE UNIQUE INDEX idx_fx_rates_pair_date
    ON fx_rates (base_currency, quote_currency, date);
```

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `base_currency` | `CHAR(3)` | NO | `'EUR'` | Always EUR |
| `quote_currency` | `CHAR(3)` | NO | | Foreign currency code |
| `date` | `DATE` | NO | | Rate date |
| `rate` | `NUMERIC(12,6)` | NO | | Exchange rate (1 EUR = X quote) |
| `source` | `pipeline_runs_source_enum` | NO | `'ecb'` | Data source |
| `created_at` | `TIMESTAMPTZ` | NO | `now()` | Row creation timestamp |

**Hypertable:** chunk interval = 1 month.

**Indexes:**

```sql
CREATE INDEX idx_fx_rates_quote_currency ON fx_rates (quote_currency);
CREATE INDEX idx_fx_rates_date ON fx_rates (date DESC);
```

---

### `macro_indicators`

Economic indicator time-series from FRED, ECB, OECD, and Statistics Finland.

```sql
CREATE TABLE macro_indicators (
    indicator_code  VARCHAR(50)     NOT NULL,
        -- e.g. 'FEDFUNDS', 'ECBMRO', 'FI_CPI'
    date            DATE            NOT NULL,
    value           NUMERIC(18, 6)  NOT NULL,
    unit            VARCHAR(20),    -- e.g. 'percent', 'index', 'billions_eur'
    source          pipeline_runs_source_enum NOT NULL,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT now()
);

SELECT create_hypertable('macro_indicators', 'date', chunk_time_interval => INTERVAL '3 months');
CREATE UNIQUE INDEX idx_macro_indicators_code_date
    ON macro_indicators (indicator_code, date);
```

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `indicator_code` | `VARCHAR(50)` | NO | | Indicator identifier (e.g. FRED series ID) |
| `date` | `DATE` | NO | | Observation date |
| `value` | `NUMERIC(18,6)` | NO | | Indicator value |
| `unit` | `VARCHAR(20)` | YES | `NULL` | Unit of measurement |
| `source` | `pipeline_runs_source_enum` | NO | | Data source |
| `created_at` | `TIMESTAMPTZ` | NO | `now()` | Row creation timestamp |

**Hypertable:** chunk interval = 3 months (macro data is sparser than daily prices).

**Indexes:**

```sql
CREATE INDEX idx_macro_indicators_code ON macro_indicators (indicator_code);
CREATE INDEX idx_macro_indicators_date ON macro_indicators (date DESC);
```

---

## Tables — Features

### `watchlists`

User-defined watchlists for tracking securities of interest.

```sql
CREATE TABLE watchlists (
    id              BIGSERIAL       PRIMARY KEY,
    name            VARCHAR(100)    NOT NULL,
    description     TEXT,
    is_default      BOOLEAN         NOT NULL DEFAULT FALSE,
    sort_order      INTEGER         NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),

    CONSTRAINT uq_watchlists_name UNIQUE (name)
);
```

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | `BIGSERIAL` | NO | auto | Primary key |
| `name` | `VARCHAR(100)` | NO | | Watchlist name (unique) |
| `description` | `TEXT` | YES | `NULL` | Watchlist description |
| `is_default` | `BOOLEAN` | NO | `FALSE` | Whether this is the default watchlist |
| `sort_order` | `INTEGER` | NO | `0` | Display ordering |
| `created_at` | `TIMESTAMPTZ` | NO | `now()` | Row creation timestamp |
| `updated_at` | `TIMESTAMPTZ` | NO | `now()` | Last modification timestamp |

---

### `watchlist_items`

Join table linking securities to watchlists, with per-item notes and ordering.

```sql
CREATE TABLE watchlist_items (
    id              BIGSERIAL       PRIMARY KEY,
    watchlist_id    BIGINT          NOT NULL REFERENCES watchlists(id) ON DELETE CASCADE,
    security_id     BIGINT          NOT NULL REFERENCES securities(id),
    notes           TEXT,
    sort_order      INTEGER         NOT NULL DEFAULT 0,
    added_at        TIMESTAMPTZ     NOT NULL DEFAULT now(),

    CONSTRAINT fk_watchlist_items_watchlists
        FOREIGN KEY (watchlist_id) REFERENCES watchlists(id) ON DELETE CASCADE,
    CONSTRAINT fk_watchlist_items_securities
        FOREIGN KEY (security_id) REFERENCES securities(id),
    CONSTRAINT uq_watchlist_items_watchlist_security
        UNIQUE (watchlist_id, security_id)
);
```

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | `BIGSERIAL` | NO | auto | Primary key |
| `watchlist_id` | `BIGINT` | NO | | FK to `watchlists`; cascade on delete |
| `security_id` | `BIGINT` | NO | | FK to `securities` |
| `notes` | `TEXT` | YES | `NULL` | Per-item notes |
| `sort_order` | `INTEGER` | NO | `0` | Display ordering within watchlist |
| `added_at` | `TIMESTAMPTZ` | NO | `now()` | When item was added |

**Indexes:**

```sql
CREATE INDEX idx_watchlist_items_watchlist_id ON watchlist_items (watchlist_id);
CREATE INDEX idx_watchlist_items_security_id ON watchlist_items (security_id);
```

---

### `research_notes`

Investment theses and research notes attached to a security. Supports the Research Analyst workflow with bull/bear/base case fields.

```sql
CREATE TABLE research_notes (
    id              BIGSERIAL       PRIMARY KEY,
    security_id     BIGINT          NOT NULL REFERENCES securities(id),
    title           VARCHAR(255)    NOT NULL,
    thesis          TEXT,           -- overall investment thesis
    bull_case       TEXT,
    bear_case       TEXT,
    base_case       TEXT,
    intrinsic_value_cents BIGINT,   -- estimated intrinsic value per share
    intrinsic_value_currency CHAR(3),
    margin_of_safety_pct NUMERIC(5, 2),
        -- (intrinsic_value - current_price) / intrinsic_value * 100
    moat_rating     VARCHAR(20),    -- 'none', 'narrow', 'wide'
    tags            TEXT[],         -- PostgreSQL text array for labels
    is_active       BOOLEAN         NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),

    CONSTRAINT fk_research_notes_securities
        FOREIGN KEY (security_id) REFERENCES securities(id)
);
```

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | `BIGSERIAL` | NO | auto | Primary key |
| `security_id` | `BIGINT` | NO | | FK to `securities` |
| `title` | `VARCHAR(255)` | NO | | Note title |
| `thesis` | `TEXT` | YES | `NULL` | Overall investment thesis |
| `bull_case` | `TEXT` | YES | `NULL` | Optimistic scenario |
| `bear_case` | `TEXT` | YES | `NULL` | Pessimistic scenario |
| `base_case` | `TEXT` | YES | `NULL` | Expected scenario |
| `intrinsic_value_cents` | `BIGINT` | YES | `NULL` | Estimated intrinsic value (cents) |
| `intrinsic_value_currency` | `CHAR(3)` | YES | `NULL` | Currency of the intrinsic value |
| `margin_of_safety_pct` | `NUMERIC(5,2)` | YES | `NULL` | Margin of safety percentage |
| `moat_rating` | `VARCHAR(20)` | YES | `NULL` | Competitive advantage rating |
| `tags` | `TEXT[]` | YES | `NULL` | Array of tags/labels |
| `is_active` | `BOOLEAN` | NO | `TRUE` | Soft-delete flag |
| `created_at` | `TIMESTAMPTZ` | NO | `now()` | Row creation timestamp |
| `updated_at` | `TIMESTAMPTZ` | NO | `now()` | Last modification timestamp |

**Indexes:**

```sql
CREATE INDEX idx_research_notes_security_id ON research_notes (security_id);
CREATE INDEX idx_research_notes_tags ON research_notes USING gin (tags);
CREATE INDEX idx_research_notes_is_active
    ON research_notes (is_active) WHERE is_active = TRUE;
```

---

### `alerts`

Price alerts, drift alerts, staleness warnings, and custom notifications.

```sql
CREATE TABLE alerts (
    id              BIGSERIAL       PRIMARY KEY,
    type            alerts_type_enum NOT NULL,
    status          alerts_status_enum NOT NULL DEFAULT 'active',
    security_id     BIGINT          REFERENCES securities(id),
        -- NULL for portfolio-level alerts (drift, staleness)
    account_id      BIGINT          REFERENCES accounts(id),
        -- NULL for security-level or global alerts
    threshold_value NUMERIC(18, 6), -- meaning depends on type
    threshold_currency CHAR(3),
    message         TEXT            NOT NULL,
    triggered_at    TIMESTAMPTZ,
    dismissed_at    TIMESTAMPTZ,
    expires_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),

    CONSTRAINT fk_alerts_securities
        FOREIGN KEY (security_id) REFERENCES securities(id),
    CONSTRAINT fk_alerts_accounts
        FOREIGN KEY (account_id) REFERENCES accounts(id)
);
```

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | `BIGSERIAL` | NO | auto | Primary key |
| `type` | `alerts_type_enum` | NO | | Alert type |
| `status` | `alerts_status_enum` | NO | `'active'` | Current alert status |
| `security_id` | `BIGINT` | YES | `NULL` | FK to `securities`; NULL for portfolio-level |
| `account_id` | `BIGINT` | YES | `NULL` | FK to `accounts`; NULL for security/global |
| `threshold_value` | `NUMERIC(18,6)` | YES | `NULL` | Threshold (price in cents, drift in %, etc.) |
| `threshold_currency` | `CHAR(3)` | YES | `NULL` | Currency for price thresholds |
| `message` | `TEXT` | NO | | Human-readable alert description |
| `triggered_at` | `TIMESTAMPTZ` | YES | `NULL` | When the alert was triggered |
| `dismissed_at` | `TIMESTAMPTZ` | YES | `NULL` | When the alert was dismissed |
| `expires_at` | `TIMESTAMPTZ` | YES | `NULL` | Auto-expiration timestamp |
| `created_at` | `TIMESTAMPTZ` | NO | `now()` | Row creation timestamp |
| `updated_at` | `TIMESTAMPTZ` | NO | `now()` | Last modification timestamp |

**Indexes:**

```sql
CREATE INDEX idx_alerts_status ON alerts (status);
CREATE INDEX idx_alerts_security_id ON alerts (security_id);
CREATE INDEX idx_alerts_type_status ON alerts (type, status);
CREATE INDEX idx_alerts_active
    ON alerts (status) WHERE status = 'active';
```

---

### `esg_scores`

Per-security ESG (Environmental, Social, Governance) data. Refreshed monthly from available free sources.

```sql
CREATE TABLE esg_scores (
    id              BIGSERIAL       PRIMARY KEY,
    security_id     BIGINT          NOT NULL REFERENCES securities(id),
    as_of_date      DATE            NOT NULL,
    environment_score NUMERIC(5, 2),  -- 0-100 scale
    social_score    NUMERIC(5, 2),
    governance_score NUMERIC(5, 2),
    total_score     NUMERIC(5, 2),
    controversy_level VARCHAR(20),
        -- 'none', 'low', 'moderate', 'significant', 'severe'
    controversy_details TEXT,
    eu_taxonomy_aligned BOOLEAN,
    sfdr_classification VARCHAR(20),
        -- 'article_6', 'article_8', 'article_9' (for funds)
    source          VARCHAR(50)     NOT NULL,
        -- e.g. 'yahoo_finance', 'sustainalytics'
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),

    CONSTRAINT fk_esg_scores_securities
        FOREIGN KEY (security_id) REFERENCES securities(id)
);
```

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | `BIGSERIAL` | NO | auto | Primary key |
| `security_id` | `BIGINT` | NO | | FK to `securities` |
| `as_of_date` | `DATE` | NO | | Date the scores are valid for |
| `environment_score` | `NUMERIC(5,2)` | YES | `NULL` | Environmental pillar (0-100) |
| `social_score` | `NUMERIC(5,2)` | YES | `NULL` | Social pillar (0-100) |
| `governance_score` | `NUMERIC(5,2)` | YES | `NULL` | Governance pillar (0-100) |
| `total_score` | `NUMERIC(5,2)` | YES | `NULL` | Combined ESG score (0-100) |
| `controversy_level` | `VARCHAR(20)` | YES | `NULL` | Controversy severity |
| `controversy_details` | `TEXT` | YES | `NULL` | Description of controversies |
| `eu_taxonomy_aligned` | `BOOLEAN` | YES | `NULL` | EU Taxonomy alignment |
| `sfdr_classification` | `VARCHAR(20)` | YES | `NULL` | SFDR article classification |
| `source` | `VARCHAR(50)` | NO | | Data source |
| `created_at` | `TIMESTAMPTZ` | NO | `now()` | Row creation timestamp |
| `updated_at` | `TIMESTAMPTZ` | NO | `now()` | Last modification timestamp |

**Indexes:**

```sql
CREATE UNIQUE INDEX idx_esg_scores_security_date
    ON esg_scores (security_id, as_of_date);
CREATE INDEX idx_esg_scores_security_id ON esg_scores (security_id);
CREATE INDEX idx_esg_scores_as_of_date ON esg_scores (as_of_date);
```

---

## Tables — System

### `pipeline_runs`

Execution log for data ingestion pipelines. Every adapter run (scheduled or manual) creates a row. Used for staleness detection, debugging, and the pipeline status dashboard.

```sql
CREATE TABLE pipeline_runs (
    id              BIGSERIAL       PRIMARY KEY,
    source          pipeline_runs_source_enum NOT NULL,
    pipeline_name   VARCHAR(100)    NOT NULL,
        -- human-readable name, e.g. 'yahoo_daily_prices', 'ecb_fx_rates'
    status          pipeline_runs_status_enum NOT NULL,
    started_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ,
    duration_ms     INTEGER,
    rows_affected   INTEGER         NOT NULL DEFAULT 0,
    error_message   TEXT,
    metadata        JSONB,
        -- flexible field for source-specific details (e.g. tickers processed)
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),

    CONSTRAINT chk_pipeline_runs_duration
        CHECK (
            (finished_at IS NOT NULL AND duration_ms IS NOT NULL AND duration_ms >= 0) OR
            (finished_at IS NULL AND duration_ms IS NULL)
        )
);
```

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | `BIGSERIAL` | NO | auto | Primary key |
| `source` | `pipeline_runs_source_enum` | NO | | Data source adapter |
| `pipeline_name` | `VARCHAR(100)` | NO | | Descriptive pipeline name |
| `status` | `pipeline_runs_status_enum` | NO | | Execution outcome |
| `started_at` | `TIMESTAMPTZ` | NO | `now()` | Pipeline start time |
| `finished_at` | `TIMESTAMPTZ` | YES | `NULL` | Pipeline end time; NULL while running |
| `duration_ms` | `INTEGER` | YES | `NULL` | Execution duration in milliseconds |
| `rows_affected` | `INTEGER` | NO | `0` | Number of rows upserted/inserted |
| `error_message` | `TEXT` | YES | `NULL` | Error details on failure |
| `metadata` | `JSONB` | YES | `NULL` | Flexible metadata (tickers processed, API calls made, etc.) |
| `created_at` | `TIMESTAMPTZ` | NO | `now()` | Row creation timestamp |

**Indexes:**

```sql
CREATE INDEX idx_pipeline_runs_source ON pipeline_runs (source);
CREATE INDEX idx_pipeline_runs_status ON pipeline_runs (status);
CREATE INDEX idx_pipeline_runs_started_at ON pipeline_runs (started_at DESC);
CREATE INDEX idx_pipeline_runs_source_started
    ON pipeline_runs (source, started_at DESC);
```

---

## Entity-Relationship Summary

```
                         ┌─────────────────┐
                         │   watchlists     │
                         └────────┬────────┘
                                  │ 1:N
                         ┌────────┴────────┐
                         │ watchlist_items  │
                         └────────┬────────┘
                                  │ N:1
┌──────────┐  1:N  ┌─────────────┴───────────────┐  1:N  ┌──────────────┐
│ accounts │───────│       securities             │───────│ research_    │
│          │       │                              │       │   notes      │
└────┬─────┘       └──┬───────┬──────┬──────┬────┘       └──────────────┘
     │                 │       │      │      │
     │ 1:N             │ 1:N   │ 1:N  │ 1:N  │ 1:N
     │                 │       │      │      │
     │    ┌────────────┘       │      │      └────────┐
     │    │                    │      │               │
┌────┴────┴──┐          ┌─────┴──┐  ┌┴────────────┐  ┌┴────────────┐
│transactions│          │ prices │  │corporate_   │  │ esg_scores  │
│            │          │(hyper) │  │  actions     │  │             │
└────┬───────┘          └────────┘  └─────────────┘  └─────────────┘
     │ 1:N
┌────┴───────┐
│  tax_lots  │
└────────────┘

┌──────────────┐    ┌──────────────┐    ┌──────────────────┐
│  dividends   │    │  fx_rates    │    │ macro_indicators  │
│ (account +   │    │  (hyper)     │    │ (hyper)           │
│  security)   │    └──────────────┘    └──────────────────┘
└──────────────┘

┌──────────────────┐    ┌──────────┐
│ holdings_snapshot│    │  alerts  │
│ (account +       │    │          │
│  security + date)│    └──────────┘
└──────────────────┘

┌──────────────────┐
│ pipeline_runs    │
│ (system)         │
└──────────────────┘
```

### Relationship Detail

| Parent | Child | Cardinality | FK Column | On Delete |
|--------|-------|-------------|-----------|-----------|
| `accounts` | `transactions` | 1:N | `transactions.account_id` | RESTRICT |
| `accounts` | `tax_lots` | 1:N | `tax_lots.account_id` | RESTRICT |
| `accounts` | `holdings_snapshot` | 1:N | `holdings_snapshot.account_id` | RESTRICT |
| `accounts` | `dividends` | 1:N | `dividends.account_id` | RESTRICT |
| `accounts` | `alerts` | 1:N | `alerts.account_id` | SET NULL |
| `securities` | `transactions` | 1:N | `transactions.security_id` | RESTRICT |
| `securities` | `tax_lots` | 1:N | `tax_lots.security_id` | RESTRICT |
| `securities` | `holdings_snapshot` | 1:N | `holdings_snapshot.security_id` | RESTRICT |
| `securities` | `prices` | 1:N | `prices.security_id` | RESTRICT |
| `securities` | `dividends` | 1:N | `dividends.security_id` | RESTRICT |
| `securities` | `corporate_actions` | 1:N | `corporate_actions.security_id` | RESTRICT |
| `securities` | `research_notes` | 1:N | `research_notes.security_id` | RESTRICT |
| `securities` | `watchlist_items` | 1:N | `watchlist_items.security_id` | RESTRICT |
| `securities` | `esg_scores` | 1:N | `esg_scores.security_id` | RESTRICT |
| `securities` | `alerts` | 1:N | `alerts.security_id` | SET NULL |
| `securities` | `corporate_actions` (new) | 1:N | `corporate_actions.new_security_id` | SET NULL |
| `watchlists` | `watchlist_items` | 1:N | `watchlist_items.watchlist_id` | CASCADE |
| `transactions` | `tax_lots` (open) | 1:N | `tax_lots.open_transaction_id` | RESTRICT |
| `transactions` | `tax_lots` (close) | 1:N | `tax_lots.close_transaction_id` | SET NULL |
| `transactions` | `dividends` | 1:1 | `dividends.transaction_id` | SET NULL |

---

## Required Extensions

```sql
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS pg_trgm;  -- trigram index for security name search
```

---

## Corporate Action Processing Rules

Corporate actions are entered into the `corporate_actions` table and processed by the application layer. The processing rules are:

### Split / Reverse Split
1. For each open/partially-closed `tax_lots` row for the affected security:
   - Multiply `original_quantity` and `remaining_quantity` by `ratio_to / ratio_from`
   - Divide `cost_basis_cents` proportionally (total cost basis is unchanged)
2. Update `prices` history: divide all price columns by `ratio_to / ratio_from` for dates before `effective_date`
3. Mark `is_processed = TRUE`

### Merger
1. For each open tax lot of the old security:
   - Create a new tax lot for `new_security_id` with the same `cost_basis_cents`, `acquired_date`, and adjusted quantity
   - Close the old lot with `state = 'closed'` and `realized_pnl_cents = 0` (tax-deferred exchange)
2. If `cash_in_lieu_cents > 0`, create a separate closed lot with realized gain/loss
3. Mark `is_processed = TRUE`

### Spinoff
1. Allocate the original cost basis between the parent and spinoff securities based on the market-value ratio on `effective_date`
2. Create new open tax lots in `new_security_id` for the spinoff shares
3. Reduce `cost_basis_cents` on existing parent lots proportionally
4. Mark `is_processed = TRUE`

---

## Finnish Tax-Specific Design Notes

### Osakesaastotili (Equity Savings Account)
- Modeled as `accounts.type = 'osakesaastotili'`
- Deposit cap enforced via `osa_deposit_total_cents` (max 5 000 000 = 50 000 EUR)
- Internal trades within the account do NOT create taxable events; tax lots are still tracked for reporting but `realized_pnl_cents` has no tax consequence until withdrawal
- On withdrawal, the taxable portion is calculated as: `withdrawal_amount * (total_gains / total_account_value)`
- Tax rate: 30% on gains up to 30 000 EUR/year, 34% above

### Deemed Cost of Acquisition (Hankintameno-olettama)
- Finnish tax rule: when selling, the taxpayer may use 20% of sale price (or 40% if held > 10 years) as the acquisition cost instead of the actual cost, if more favorable
- The application layer computes both actual cost and deemed cost, uses whichever results in lower tax
- The `tax_lots.acquired_date` is critical for determining the 10-year threshold
- This rule does NOT apply inside osakesaastotili

### Crypto Taxation
- Each crypto-to-crypto swap is a taxable event in Finland
- Modeled as two `transactions`: a sell of the source crypto and a buy of the target
- Crypto quantities use `NUMERIC(28, 18)` to handle token-level precision (e.g., wei)

### Capital Gains Tax Brackets
- 30% on capital income up to 30 000 EUR/year
- 34% on capital income above 30 000 EUR/year
- Both realized gains and dividend income count toward the 30 000 EUR threshold

---

## Holdings Snapshot Rebuild Process

The `holdings_snapshot` table is rebuilt nightly via a scheduled pipeline:

1. For each active account and each security with open tax lots:
   - Aggregate `remaining_quantity` across all open lots
   - Aggregate `cost_basis_cents` across all open lots
   - Fetch the latest `close_cents` from `prices` for the security
   - Fetch the latest `rate` from `fx_rates` for the security's currency (if not EUR)
   - Compute `market_value_eur_cents = quantity * close_cents * (1 / fx_rate)` (when security currency is not EUR)
   - Compute `unrealized_pnl_eur_cents = market_value_eur_cents - cost_basis_cents`
2. After all positions are computed, calculate `weight_pct` for each row as `market_value_eur_cents / total_portfolio_value * 100`
3. Insert all rows for the current date
4. Old snapshots are retained indefinitely for historical portfolio analysis

---

## Edge Cases

1. **Security traded on multiple exchanges:** The same company can appear as multiple `securities` rows with different `exchange` values. The unique index `(ticker, exchange)` allows this. Portfolio logic must avoid double-counting by linking transactions to the specific exchange listing.

2. **Missing price data:** If a `prices` row is missing for a date (market holiday, data gap), the holdings snapshot uses the most recent available `close_cents`. The snapshot includes the actual price date in the pipeline metadata to flag staleness.

3. **FX rate for EUR-denominated securities:** When `security.currency = 'EUR'`, no `fx_rates` lookup is needed. The `fx_rate` column in `holdings_snapshot` is NULL, and `market_value_eur_cents = quantity * close_cents`.

4. **Fractional shares from splits:** A 3:2 split on an odd number of shares produces a fractional share. If the broker pays cash in lieu, this is recorded via `corporate_actions.cash_in_lieu_cents` and a corresponding sell `transactions` row for the fractional amount.

5. **Negative cost basis after return of capital:** Some distributions are classified as return of capital, reducing cost basis. If cost basis reaches zero, further distributions are treated as capital gains. The `cost_basis_cents` on a tax lot can reach zero but never go negative.

6. **Osakesaastotili deposit limit mid-year:** The `osa_deposit_total_cents` check constraint enforces the lifetime deposit cap of 50 000 EUR. The application must reject deposit transactions that would exceed this limit.

7. **Corporate action on partially closed lot:** When processing a split on a `partially_closed` lot, only the `remaining_quantity` is adjusted. The already-closed portion (separate lot rows) retains its pre-split values since it was closed before the action.

8. **Crypto traded 24/7:** Unlike stock prices which are date-based, crypto has no market close. The daily price stored in `prices` is the UTC midnight close from CoinGecko. The `holdings_snapshot` uses this value.

9. **Multi-currency dividend reinvestment:** A USD dividend received in an osakesaastotili (EUR account) must be converted at the day's FX rate. The `dividends.fx_rate` records the rate used, and the reinvestment buy transaction uses the same rate for consistency.

10. **Concurrent sell closing multiple lots:** A single sell transaction can close portions of multiple tax lots (specific identification). The sell creates one `transactions` row but multiple `tax_lots` rows (one per lot consumed), each linked to the same `close_transaction_id`.

11. **Pipeline partial failure:** If a price pipeline successfully fetches 450 of 500 tickers, the run is recorded with `status = 'partial'`, `rows_affected = 450`, and `metadata` listing the failed tickers. Existing prices for failed tickers remain unchanged.

12. **Deemed cost versus actual cost:** The application computes both when generating tax reports. The `tax_lots` table always stores actual cost basis; deemed cost is calculated on-the-fly since it depends on the sale price which is only known at disposal time.

---

## Open Questions

1. **Should `holdings_snapshot` also store asset class and sector for faster aggregation queries, or always join to `securities`?** Denormalizing would speed up allocation breakdowns but adds maintenance burden on security metadata changes.

2. **Should we add a `cash_balances` table to track uninvested cash per account, or derive it from transactions?** A dedicated table simplifies portfolio valuation but requires reconciliation logic.

3. **Should `tax_lots` support a `method` column (FIFO, LIFO, specific ID) per lot, or is specific identification the only method?** Finnish tax law allows specific identification, which subsumes the others.

---

## Changelog

| Date | Change |
|------|--------|
| 2026-03-19 | Initial draft |
