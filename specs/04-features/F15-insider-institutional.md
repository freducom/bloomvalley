# F15 — Insider & Institutional Tracking

Tracks insider trading activity, US congressional trades, institutional holdings changes, and share buyback programs for held and watchlisted securities. Answers the questions: "Are insiders buying or selling? What are institutions doing? Is management confident?" Aggregates data from Finnish (FIN-FSA), Swedish (Finansinspektionen), and US (SEC EDGAR) regulatory sources, plus congressional trading disclosures and 13F filings.

**Status: DRAFT**

## Dependencies

- [Data Model](../01-system/data-model.md) — `securities` table for security references
- [API Overview](../01-system/api-overview.md) — endpoint conventions, response envelope, pagination
- [Spec Conventions](../00-meta/spec-conventions.md) — date format, monetary values in cents, naming rules
- `../04-features/F03-watchlist-screener.md` — watchlist securities for monitoring scope
- `../04-features/F14-news-impact.md` — buyback announcements sourced from news pipeline

## Data Requirements

### New Enum Types

```sql
CREATE TYPE insider_trades_role_enum AS ENUM (
    'ceo',
    'cfo',
    'cto',
    'coo',
    'director',
    'board_chair',
    'vp',
    'other_executive',
    'related_party'         -- closely associated persons (EU MAR definition)
);

CREATE TYPE insider_trades_type_enum AS ENUM (
    'buy',
    'sell',
    'exercise',             -- stock option exercise
    'gift',
    'other'
);

CREATE TYPE insider_trades_jurisdiction_enum AS ENUM (
    'fi',       -- Finland (Finanssivalvonta / FIN-FSA)
    'se',       -- Sweden (Finansinspektionen)
    'us'        -- United States (SEC EDGAR Form 4)
);

CREATE TYPE congress_trades_party_enum AS ENUM (
    'democrat',
    'republican',
    'independent'
);

CREATE TYPE congress_trades_chamber_enum AS ENUM (
    'senate',
    'house'
);

CREATE TYPE buyback_programs_status_enum AS ENUM (
    'announced',
    'active',
    'completed',
    'cancelled'
);
```

### New Tables

#### `insider_trades`

```sql
CREATE TABLE insider_trades (
    id                  BIGSERIAL       PRIMARY KEY,
    security_id         BIGINT          NOT NULL REFERENCES securities(id),
    insider_name        VARCHAR(255)    NOT NULL,
    role                insider_trades_role_enum NOT NULL,
    trade_type          insider_trades_type_enum NOT NULL,
    jurisdiction        insider_trades_jurisdiction_enum NOT NULL,
    trade_date          DATE            NOT NULL,
    disclosure_date     DATE            NOT NULL,       -- when the filing was published
    shares              NUMERIC(18, 8)  NOT NULL,
    price_cents         BIGINT,                         -- price per share; NULL if not disclosed
    value_cents         BIGINT,                         -- total transaction value
    currency            CHAR(3)         NOT NULL,
    shares_after        NUMERIC(18, 8),                 -- total holding after transaction
    source_url          TEXT,                           -- link to regulatory filing
    source              VARCHAR(50)     NOT NULL,       -- 'fin_fsa', 'finansinspektionen', 'sec_form4', 'openinsider'
    is_significant      BOOLEAN         NOT NULL DEFAULT FALSE,  -- flagged by business rules
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT now(),

    CONSTRAINT chk_insider_trades_currency_upper
        CHECK (currency = upper(currency))
);
```

**Indexes:**

```sql
CREATE INDEX idx_insider_trades_security_id ON insider_trades (security_id);
CREATE INDEX idx_insider_trades_trade_date ON insider_trades (trade_date DESC);
CREATE INDEX idx_insider_trades_jurisdiction ON insider_trades (jurisdiction);
CREATE INDEX idx_insider_trades_is_significant ON insider_trades (is_significant) WHERE is_significant = TRUE;
```

#### `congress_trades`

```sql
CREATE TABLE congress_trades (
    id                  BIGSERIAL       PRIMARY KEY,
    security_id         BIGINT          REFERENCES securities(id),   -- NULL if security not in catalog
    member_name         VARCHAR(255)    NOT NULL,
    party               congress_trades_party_enum NOT NULL,
    chamber             congress_trades_chamber_enum NOT NULL,
    state               CHAR(2),                         -- US state abbreviation
    trade_type          insider_trades_type_enum NOT NULL,  -- reuse: buy, sell, exercise
    trade_date          DATE            NOT NULL,
    disclosure_date     DATE            NOT NULL,
    amount_range_low_cents  BIGINT      NOT NULL,        -- STOCK Act reports in ranges
    amount_range_high_cents BIGINT      NOT NULL,
    currency            CHAR(3)         NOT NULL DEFAULT 'USD',
    ticker_reported     VARCHAR(20)     NOT NULL,        -- ticker as reported in filing
    asset_description   VARCHAR(500),                    -- description from filing
    source_url          TEXT,
    source              VARCHAR(50)     NOT NULL DEFAULT 'quiver_quantitative',
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT now(),

    CONSTRAINT chk_congress_trades_amount_range
        CHECK (amount_range_high_cents >= amount_range_low_cents),
    CONSTRAINT chk_congress_trades_currency_upper
        CHECK (currency = upper(currency))
);
```

**Indexes:**

```sql
CREATE INDEX idx_congress_trades_security_id ON congress_trades (security_id);
CREATE INDEX idx_congress_trades_trade_date ON congress_trades (trade_date DESC);
CREATE INDEX idx_congress_trades_member_name ON congress_trades (member_name);
```

#### `institutional_holdings`

Quarterly 13F filing data showing institutional ownership.

```sql
CREATE TABLE institutional_holdings (
    id                  BIGSERIAL       PRIMARY KEY,
    security_id         BIGINT          NOT NULL REFERENCES securities(id),
    institution_name    VARCHAR(255)    NOT NULL,
    cik                 VARCHAR(20),                     -- SEC Central Index Key
    filing_date         DATE            NOT NULL,        -- 13F filing date
    report_date         DATE            NOT NULL,        -- quarter end date
    shares              BIGINT          NOT NULL,
    value_cents         BIGINT          NOT NULL,        -- reported market value
    currency            CHAR(3)         NOT NULL DEFAULT 'USD',
    shares_change       BIGINT,                          -- change from previous quarter (NULL if first appearance)
    change_type         VARCHAR(20),                     -- 'new', 'added', 'reduced', 'sold_out', 'unchanged'
    ownership_percent   NUMERIC(8, 4),                   -- % of company shares outstanding
    source              VARCHAR(50)     NOT NULL DEFAULT 'sec_13f',
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT now(),

    CONSTRAINT uq_institutional_holdings_filing
        UNIQUE (security_id, institution_name, report_date),
    CONSTRAINT chk_institutional_holdings_currency_upper
        CHECK (currency = upper(currency))
);
```

**Indexes:**

```sql
CREATE INDEX idx_institutional_holdings_security_id ON institutional_holdings (security_id);
CREATE INDEX idx_institutional_holdings_report_date ON institutional_holdings (report_date DESC);
CREATE INDEX idx_institutional_holdings_institution ON institutional_holdings (institution_name);
```

#### `buyback_programs`

```sql
CREATE TABLE buyback_programs (
    id                      BIGSERIAL       PRIMARY KEY,
    security_id             BIGINT          NOT NULL REFERENCES securities(id),
    announced_date          DATE            NOT NULL,
    start_date              DATE,
    end_date                DATE,
    authorized_amount_cents BIGINT,                     -- total authorized buyback value
    authorized_shares       BIGINT,                     -- total authorized shares (alternative)
    currency                CHAR(3)         NOT NULL,
    executed_amount_cents   BIGINT          NOT NULL DEFAULT 0,
    executed_shares         BIGINT          NOT NULL DEFAULT 0,
    status                  buyback_programs_status_enum NOT NULL DEFAULT 'announced',
    shares_outstanding_at_start BIGINT,                 -- for calculating % impact
    source_url              TEXT,
    notes                   TEXT,
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT now(),

    CONSTRAINT chk_buyback_programs_currency_upper
        CHECK (currency = upper(currency))
);
```

**Indexes:**

```sql
CREATE INDEX idx_buyback_programs_security_id ON buyback_programs (security_id);
CREATE INDEX idx_buyback_programs_status ON buyback_programs (status);
```

### Data Sources

| Source | Data | Method | Refresh |
|--------|------|--------|---------|
| Finanssivalvonta (FIN-FSA) | Finnish insider trades | Scrape notifications page | Daily |
| Finansinspektionen | Swedish insider trades | Scrape insider register | Daily |
| SEC EDGAR Form 4 | US insider trades | EDGAR XBRL API / RSS feed | Daily |
| OpenInsider | US insider trades (aggregated) | Scrape / API | Daily (backup for SEC) |
| Quiver Quantitative | US Congress trades | Free API | Daily |
| SEC EDGAR 13F | Institutional holdings | EDGAR XBRL API | Quarterly (45 days after quarter end) |
| News pipeline (F14) | Buyback announcements | Internal cross-reference | As news arrives |

### Data Ingestion

- **Insider trades**: fetched daily at 07:00 Helsinki time. Only fetch for held + watchlisted securities.
- **Congress trades**: fetched daily. Match `ticker_reported` against `securities` catalog; set `security_id` to NULL if no match found (user can manually map later).
- **Institutional holdings**: fetched quarterly after 13F filing deadline (45 days after quarter end). Only for US-listed held + watchlisted securities.
- **Buyback programs**: initially created from news items (F14) tagged with buyback keywords. Progress updates via company press releases or quarterly reports.

## API Endpoints

| Tag | Prefix | Feature |
|-----|--------|---------|
| Insiders | `/insiders` | F15 — Insider, congress, institutional tracking |

| Method | Path | Description |
|--------|------|-------------|
| GET | `/insiders/trades` | Insider trades, paginated. Filters: `securityId`, `jurisdiction`, `tradeType`, `role`, `isSignificant`, `fromDate`, `toDate` |
| GET | `/insiders/trades/security/{securityId}` | Insider trades for a specific security |
| GET | `/insiders/trades/summary/{securityId}` | Net insider buying/selling summary for 3/6/12 months |
| GET | `/insiders/congress` | Congress trades, paginated. Filters: `securityId`, `party`, `chamber`, `memberName`, `tradeType`, `fromDate`, `toDate` |
| GET | `/insiders/institutional/{securityId}` | Top institutional holders for a security with quarterly changes |
| GET | `/insiders/buybacks` | Active buyback programs, filterable by `securityId`, `status` |
| GET | `/insiders/buybacks/{id}` | Buyback program detail with execution progress |
| GET | `/insiders/signals` | Aggregated significant signals: cluster buying events, large transactions, notable congress trades |

### Example Responses

**GET `/insiders/trades/summary/42`**

```json
{
  "data": {
    "securityId": 42,
    "ticker": "NESTE",
    "name": "Neste Oyj",
    "summary": {
      "3months": { "buys": 5, "sells": 1, "netShares": 12500, "netValue": { "amount": 562000, "currency": "EUR" } },
      "6months": { "buys": 8, "sells": 3, "netShares": 18000, "netValue": { "amount": 810000, "currency": "EUR" } },
      "12months": { "buys": 12, "sells": 7, "netShares": 22000, "netValue": { "amount": 990000, "currency": "EUR" } }
    },
    "signals": [
      { "type": "cluster_buying", "message": "4 insiders bought within 21 days (Feb 2026)", "date": "2026-02-28" }
    ]
  },
  "meta": { "timestamp": "2026-03-19T10:00:00Z", "cacheAge": 3600, "stale": false }
}
```

**GET `/insiders/congress?limit=1`**

```json
{
  "data": [
    {
      "id": 501,
      "memberName": "Jane Smith",
      "party": "democrat",
      "chamber": "senate",
      "state": "CA",
      "tradeType": "buy",
      "tradeDate": "2026-01-15",
      "disclosureDate": "2026-02-28",
      "securityId": 15,
      "ticker": "AAPL",
      "amountRange": { "low": { "amount": 1500100, "currency": "USD" }, "high": { "amount": 5000000, "currency": "USD" } },
      "assetDescription": "Apple Inc. Common Stock",
      "sourceUrl": "https://efds.senate.gov/..."
    }
  ],
  "meta": { "timestamp": "2026-03-19T10:00:00Z", "cacheAge": 7200, "stale": false },
  "pagination": { "total": 234, "limit": 1, "offset": 0, "hasMore": true }
}
```

## UI Views

### Insider Trades Table

Full-width table of insider transactions with rich filtering:

| Column | Description |
|--------|-------------|
| Date | Trade date |
| Disclosure | Disclosure/filing date |
| Security | Ticker + name |
| Insider | Name |
| Role | CEO, CFO, Director, etc. |
| Type | Buy / Sell / Exercise (color-coded: green buy, red sell, gray exercise) |
| Shares | Number of shares transacted |
| Price | Price per share |
| Value | Total transaction value |
| Holdings After | Total shares held after transaction |
| Jurisdiction | FI / SE / US flag icon |

- **Filter bar**: security selector, jurisdiction (FI/SE/US checkboxes), transaction type, role, date range, "significant only" toggle
- **Significant transactions** highlighted with a yellow border or badge
- Sortable by any column; default sort by trade date descending
- Click a row to expand details (source URL link, full filing text if available)

### Per-Security Insider Activity Summary

Displayed on the security detail page as a section or tab:

- **Net buying/selling bar chart**: 3 bars for 3M/6M/12M, showing net value (green = net buying, red = net selling)
- **Recent trades list**: last 10 insider trades for this security
- **Signal badges**: "Cluster Buying Detected" (if applicable), "CEO Bought" (if CEO bought recently)
- **Insider ownership %**: total shares held by all insiders as % of outstanding

### US Congress Trades Tab

Separate tab within the Insiders section:

| Column | Description |
|--------|-------------|
| Member | Name + party (D/R/I) colored badge |
| Chamber | Senate / House |
| State | US state |
| Type | Buy / Sell (color-coded) |
| Security | Ticker + description |
| Amount Range | Low - High range (STOCK Act format) |
| Trade Date | When the trade occurred |
| Disclosure Date | When filed (note the lag) |

- **Filter bar**: security selector, party, chamber, member name search, date range
- **Disclosure lag indicator**: show days between trade date and disclosure date (highlight if >45 days)
- Sort by trade date or disclosure date

### Institutional Holdings

Per-security view of top institutional holders:

| Column | Description |
|--------|-------------|
| Institution | Name |
| Shares | Current holding |
| Value | Market value at report date |
| Change | Shares added/reduced since previous quarter |
| Change Type | New / Added / Reduced / Sold Out / Unchanged (color-coded) |
| Ownership % | % of shares outstanding |
| Report Date | Quarter end date |

- Default: show latest quarter, with dropdown to compare quarters
- **Top 20 holders** shown by default, "Show all" to expand
- **Change summary**: "8 institutions added, 3 reduced, 2 sold out, 1 new position"

### Share Buyback Tracker

Table of companies with active or recent buyback programs:

| Column | Description |
|--------|-------------|
| Security | Ticker + name |
| Authorized | Total buyback authorization (amount or shares) |
| Executed | Amount or shares bought back so far |
| Progress | Progress bar (% of authorization used) |
| Status | Announced / Active / Completed / Cancelled |
| Start Date | Program start |
| End Date | Program end (if specified) |
| Impact | % reduction in shares outstanding |

- Click a row to see program details: announcement source, execution history, notes

## Business Rules

1. **Insider cluster buying signal**: When 3 or more distinct insiders buy the same security within a 30-day window, flag as "Cluster Buying" — a significant bullish signal. Display prominently on the security detail page and in the signals feed.

2. **Large transaction threshold**: Transactions with value exceeding 100,000 EUR (or equivalent in other currencies, converted at current FX rate) are flagged as `is_significant = TRUE` and highlighted in the UI.

3. **Congress trade disclosure delay**: STOCK Act requires disclosure within 45 days. The system shows both the trade date and disclosure date, and notes: "Disclosed {N} days after trade." Trades are only available after disclosure — the system cannot show real-time Congress trades.

4. **Monitoring scope**: Only track insider trades and institutional holdings for securities in the user's portfolio (held securities) and watchlist. Congress trades are tracked broadly (all members, all securities) since the data is small and globally interesting.

5. **CEO/CFO buys prioritized**: Insider buys by the CEO or CFO carry more weight than other insiders. These are always flagged as significant regardless of transaction size.

6. **Option exercises excluded from signals**: Stock option exercises (`trade_type = 'exercise'`) are tracked for completeness but excluded from the cluster buying signal and net buying/selling calculations, as they are compensation events, not open-market purchases.

7. **Buyback progress updates**: Updated when new data is available (quarterly reports, press releases). If no update for 6 months on an "active" program, flag for manual review.

8. **13F staleness**: Institutional holdings data is inherently 45+ days old (filing deadline). Always show the report date prominently and note: "Data as of {report_date}. 13F filings have a 45-day lag."

## Edge Cases

1. **No insider data available**: Some securities (especially small-cap or non-US/FI/SE) may have no insider trade data. Show "No insider data available for this jurisdiction" message.
2. **Insider name normalization**: The same insider may appear with slightly different name spellings across filings. Normalize by matching on (security_id, name similarity > 0.9, role). Flag potential duplicates for manual review.
3. **Congress trade — security not in catalog**: A congress member may trade a security not in the user's catalog. Store with `security_id = NULL` and `ticker_reported` for reference. These appear in the congress trades table but cannot be linked to security detail pages.
4. **Buyback program with no execution data**: Some companies announce buybacks but do not regularly disclose execution progress. Show "Execution data unavailable" with the last known update date.
5. **Multiple jurisdictions for one security**: A dual-listed company (e.g., listed on both Helsinki and Stockholm) may have insider filings from both FIN-FSA and Finansinspektionen. Show both, tagged by jurisdiction, without deduplication (different regulatory frameworks).
6. **Related party transactions**: EU Market Abuse Regulation requires disclosure of trades by "closely associated persons" (family members of insiders). These are tracked with `role = 'related_party'` and clearly labeled.
7. **13F threshold**: Institutions are only required to file 13F if they manage >$100M. Smaller institutions will not appear.

## Acceptance Criteria

1. Insider trades table displays trades from all three jurisdictions (FI, SE, US) with correct filtering.
2. Per-security insider summary shows net buying/selling for 3/6/12 months with correct calculations.
3. Cluster buying signals are automatically detected and displayed when 3+ insiders buy within 30 days.
4. Large transactions (>100K EUR equivalent) are flagged and highlighted.
5. Congress trades table shows all fields including disclosure lag.
6. Institutional holdings show quarterly changes with correct change type classification.
7. Buyback tracker shows progress as a percentage of authorization.
8. CEO/CFO buys are always flagged as significant regardless of size.
9. Option exercises are excluded from net buying/selling calculations and cluster signals.
10. Data freshness: insider trades updated daily; institutional holdings updated quarterly; staleness indicators shown when data is older than expected.
11. All monetary values follow the cents convention with currency codes.
12. Source URLs link to original regulatory filings.

## Changelog

| Date | Change |
|------|--------|
| 2026-03-19 | Initial draft |
