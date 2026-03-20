# F14 — News Feed & Impact Analysis

Aggregates per-security and global financial news with impact analysis, providing a unified view of what is happening with held securities and watchlist candidates. Answers the questions: "What's happening with my stocks? How do global events affect my portfolio?" Deduplicates news from multiple sources, tags impact severity, and surfaces sentiment indicators on the holdings table.

**Status: DRAFT**

## Dependencies

- [Data Model](../01-system/data-model.md) — `securities`, `accounts` tables
- [API Overview](../01-system/api-overview.md) — endpoint conventions, response envelope, pagination
- [Spec Conventions](../00-meta/spec-conventions.md) — date format, naming rules
- `../04-features/F03-watchlist-screener.md` — watchlist securities for news monitoring

## Data Requirements

### New Tables

#### `news_items`

Stores fetched news articles with deduplication and impact tagging.

```sql
CREATE TYPE news_items_impact_direction_enum AS ENUM (
    'positive',
    'negative',
    'neutral'
);

CREATE TYPE news_items_impact_severity_enum AS ENUM (
    'high',
    'medium',
    'low'
);

CREATE TABLE news_items (
    id                  BIGSERIAL       PRIMARY KEY,
    title               VARCHAR(500)    NOT NULL,
    url                 TEXT            NOT NULL,
    source              VARCHAR(100)    NOT NULL,       -- 'google_news', 'finnhub', 'manual'
    published_at        TIMESTAMPTZ     NOT NULL,
    fetched_at          TIMESTAMPTZ     NOT NULL DEFAULT now(),
    summary             TEXT,                           -- article summary / snippet
    image_url           TEXT,
    fingerprint         VARCHAR(64)     NOT NULL,       -- SHA-256 of normalized title for dedup
    is_global           BOOLEAN         NOT NULL DEFAULT FALSE,  -- TRUE for macro/global news
    is_bookmarked       BOOLEAN         NOT NULL DEFAULT FALSE,
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT now(),

    CONSTRAINT uq_news_items_fingerprint
        UNIQUE (fingerprint)
);
```

**Indexes:**

```sql
CREATE INDEX idx_news_items_published_at ON news_items (published_at DESC);
CREATE INDEX idx_news_items_source ON news_items (source);
CREATE INDEX idx_news_items_is_bookmarked ON news_items (is_bookmarked) WHERE is_bookmarked = TRUE;
```

#### `news_item_securities`

Many-to-many link between news items and securities, with per-security impact tagging.

```sql
CREATE TABLE news_item_securities (
    id                  BIGSERIAL       PRIMARY KEY,
    news_item_id        BIGINT          NOT NULL REFERENCES news_items(id) ON DELETE CASCADE,
    security_id         BIGINT          NOT NULL REFERENCES securities(id),
    impact_direction    news_items_impact_direction_enum,    -- NULL = not yet tagged
    impact_severity     news_items_impact_severity_enum,     -- NULL = not yet tagged
    impact_reasoning    TEXT,                                 -- brief explanation of why

    CONSTRAINT uq_news_item_securities
        UNIQUE (news_item_id, security_id)
);
```

**Indexes:**

```sql
CREATE INDEX idx_news_item_securities_security_id ON news_item_securities (security_id);
CREATE INDEX idx_news_item_securities_news_item_id ON news_item_securities (news_item_id);
```

### Data Sources

| Source | Method | Coverage | Rate Limit |
|--------|--------|----------|------------|
| Google News RSS | RSS feed per security (company name + ticker as query) | Global, broad coverage | No hard limit; fetch every 30 min |
| Finnhub Company News | REST API (`/company-news`) | US-listed companies primarily | Free tier: 60 calls/min |
| Manual | User-added news items | Anything | N/A |

### Data Ingestion

- **Refresh interval**: every 30 minutes during market hours (weekdays 08:00-22:00 Helsinki time, covering US + EU sessions)
- **Off-hours**: every 2 hours outside market hours
- **Monitored securities**: all held securities + all watchlist securities
- **Global news**: fetched from Google News RSS with query terms like "stock market", "ECB", "inflation", "trade war"
- **Retention**: news items older than 90 days are archived (moved to cold storage or soft-deleted); bookmarked items retained indefinitely

### Deduplication

- **Fingerprint generation**: normalize title (lowercase, strip punctuation, remove common prefixes like "Breaking:", "UPDATE:"), then SHA-256 hash
- **Fuzzy matching**: before insert, compare new title against titles from the last 48 hours using trigram similarity (`pg_trgm`). If similarity > 0.7, treat as duplicate — keep the earlier item, skip the new one
- **Cross-source dedup**: the same story from Google News and Finnhub should result in one `news_items` row (the first fetched wins)

## API Endpoints

| Tag | Prefix | Feature |
|-----|--------|---------|
| News | `/news` | F14 — News feed, impact analysis |

| Method | Path | Description |
|--------|------|-------------|
| GET | `/news` | Unified news feed, paginated. Filters: `securityId`, `watchlistId`, `isGlobal`, `impactDirection`, `impactSeverity`, `fromDate`, `toDate`, `isBookmarked`. Sort: `publishedAt` desc (default) |
| GET | `/news/{id}` | Single news item detail with linked securities and impact tags |
| GET | `/news/security/{securityId}` | News for a specific security, paginated |
| PUT | `/news/{id}/impact` | Tag or update impact for a news item on a specific security. Body: `{ securityId, impactDirection, impactSeverity, impactReasoning }` |
| PUT | `/news/{id}/bookmark` | Toggle bookmark status. Body: `{ isBookmarked: true }` |
| GET | `/news/sentiment-summary` | Aggregated sentiment for held securities: per security, count of positive/negative/neutral news in last 7 days |

### Example Responses

**GET `/news?limit=2`**

```json
{
  "data": [
    {
      "id": 1001,
      "title": "ECB Holds Rates Steady, Signals Possible Cut in June",
      "url": "https://example.com/ecb-rates",
      "source": "google_news",
      "publishedAt": "2026-03-19T12:30:00Z",
      "summary": "The European Central Bank kept its main refinancing rate unchanged at 2.5%, but signaled openness to a cut in June if inflation continues to moderate.",
      "isGlobal": true,
      "isBookmarked": false,
      "securities": [
        {
          "securityId": 10,
          "ticker": "SAMPO",
          "impactDirection": "positive",
          "impactSeverity": "medium",
          "impactReasoning": "Lower rates reduce Sampo's investment income but boost insurance policy demand"
        }
      ]
    }
  ],
  "meta": { "timestamp": "2026-03-19T13:00:00Z", "cacheAge": 60, "stale": false },
  "pagination": { "total": 847, "limit": 2, "offset": 0, "hasMore": true }
}
```

**GET `/news/sentiment-summary`**

```json
{
  "data": [
    {
      "securityId": 42,
      "ticker": "NESTE",
      "name": "Neste Oyj",
      "last7Days": { "positive": 3, "negative": 1, "neutral": 5 },
      "sentimentIndicator": "positive"
    },
    {
      "securityId": 15,
      "ticker": "AAPL",
      "name": "Apple Inc.",
      "last7Days": { "positive": 2, "negative": 4, "neutral": 8 },
      "sentimentIndicator": "negative"
    }
  ],
  "meta": { "timestamp": "2026-03-19T13:00:00Z", "cacheAge": 300, "stale": false }
}
```

## UI Views

### Unified News Feed

Chronological list of all news items, with filtering capabilities:

- **Filter bar**: security selector (multi-select), watchlist selector, global news toggle, impact direction filter, severity filter, date range picker, bookmarked-only toggle
- **Each news card shows**: title (clickable link to source), source badge, published timestamp (relative: "2h ago"), summary snippet (2-3 lines), linked securities as pill badges, impact indicator (colored arrow: green up / red down / gray dash)
- **Infinite scroll** with pagination (50 items per page)
- **Bookmark icon** on each card (star toggle)

### Per-Security News Tab

Displayed on the security detail page as a tab alongside fundamentals, chart, research notes:

- Shows only news linked to that specific security
- Same card format as unified feed
- Sorted by published date descending
- Summary at top: "12 articles in last 30 days | Sentiment: Mostly Positive"

### Impact Analysis Panel

When a major global event occurs (tagged `isGlobal = true` and `impactSeverity = 'high'`):

- Prominently displayed at the top of the news feed or as a banner on the dashboard
- Shows the event headline
- Below it: table of affected holdings with columns:

| Column | Description |
|--------|-------------|
| Security | Ticker + name |
| Impact | Positive / Negative / Neutral (colored) |
| Severity | High / Medium / Low |
| Reasoning | Brief explanation |

- Impact tags are initially manual (user or analyst tags them via the PUT endpoint)
- Future enhancement: LLM-generated impact analysis (v2, out of scope for initial release)

### News Sentiment Indicators on Holdings Table

On the main portfolio holdings table (F01 Dashboard):

- Add a **Sentiment** column showing a colored dot:
  - Green dot: more positive than negative news in last 7 days
  - Red dot: more negative than positive news in last 7 days
  - Gray dot: neutral or no news
  - No dot: no news items linked to this security
- Dot is clickable — opens a popover with the last 3 news headlines for that security

### Saved / Bookmarked News

- Accessible via "Bookmarked" filter toggle on the unified feed
- Also available as a dedicated section in the sidebar navigation
- Bookmarked items are never auto-archived

## Business Rules

1. **Fetch frequency**: News is fetched every 30 minutes during market hours (weekdays 08:00-22:00 Helsinki time). Every 2 hours outside market hours. No fetching between 00:00-06:00 Helsinki time.

2. **Deduplication**: Before inserting a new news item, check the `fingerprint` (SHA-256 of normalized title). Additionally, run trigram similarity check against titles from the last 48 hours. Threshold: 0.7 similarity = duplicate.

3. **Impact tagging**: In v1, all impact tagging is manual — the user or an analyst tags each news item with direction, severity, and reasoning via the API. The system does NOT auto-generate impact analysis. Future versions may add LLM-powered analysis.

4. **Sentiment indicator calculation**: For each security, count tagged news items from the last 7 days. If positive > negative, sentiment = "positive". If negative > positive, sentiment = "negative". Otherwise "neutral". Ties go to "neutral".

5. **Security linking**: When news is fetched, the system auto-links to securities by matching the query (ticker/company name) used to fetch the news. A single news item may link to multiple securities (e.g., "Apple and Samsung settle patent dispute" links to both AAPL and 005930.KS).

6. **Global news**: Fetched with broad market queries. Not auto-linked to specific securities — linking requires manual tagging via the impact analysis workflow.

7. **Data retention**: News items older than 90 days are soft-deleted (`is_active = FALSE` or moved to archive). Bookmarked items are exempt from archival.

## Edge Cases

1. **No news available**: If no news is found for a security, the per-security news tab shows "No recent news found" with the last fetch timestamp.
2. **Source outage**: If Google News RSS or Finnhub is unreachable, the system logs the failure, skips that source for the current cycle, and retries on the next cycle. Staleness indicator shows on the UI.
3. **Non-English news**: Finnish/Swedish companies may have news in local languages. News is stored as-is; no translation in v1. The title language is preserved.
4. **Very high volume securities**: Popular stocks (AAPL, TSLA) may generate 50+ news items per day. Apply a relevance filter: only store items from high-quality sources or with minimum engagement signals (if available from source).
5. **Ticker collision**: Some tickers are shared across exchanges (e.g., "NDA" on Helsinki vs. NASDAQ). Linking uses the security ID, not the ticker, to avoid misattribution.
6. **Duplicate with different angles**: Two articles about the same event but with different analysis (bullish vs. bearish take) should NOT be deduped. The fuzzy match threshold of 0.7 should allow these through, as the titles will differ sufficiently.

## Acceptance Criteria

1. Unified news feed displays news items from all sources in chronological order with working filters.
2. Per-security news tab on security detail pages shows only linked news for that security.
3. Impact tagging works via the PUT endpoint and is reflected in the UI (direction arrow, severity badge, reasoning text).
4. Sentiment indicators (colored dots) appear on the holdings table and correctly reflect the 7-day sentiment balance.
5. Bookmarking persists across sessions and bookmarked items are filterable.
6. Deduplication prevents the same story from appearing twice, even from different sources.
7. News fetches run on schedule (30 min during market hours) without impacting system performance.
8. Staleness indicator appears if the last successful news fetch was more than 2 hours ago during market hours.
9. Pagination works correctly on the unified feed (infinite scroll loads next page).
10. News items link to original source URL and open in a new browser tab.

## Changelog

| Date | Change |
|------|--------|
| 2026-03-19 | Initial draft |
