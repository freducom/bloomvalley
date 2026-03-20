# F18 — Global Events & Sector Impact Dashboard

Unified dashboard answering "What is happening in the world and how does it affect my portfolio and watchlist?" Aggregates global macro events from GDELT, ACLED, and OWID; maps them to sector impacts; tracks commodity prices and alternative economic data (housing, travel, employment, consumer sentiment); and overlays all of this onto the user's actual holdings and watchlist securities.

**Status: DRAFT**

## Dependencies

- [Data Model](../01-system/data-model.md) — `global_events`, `sector_impact_analysis`, `macro_indicators` tables, `securities`, `positions`
- [API Overview](../01-system/api-overview.md) — endpoint conventions, response envelope, pagination
- [Global Events Pipeline](../02-data-pipelines/global-events.md) — data sources, schema additions, sector impact mapping rules
- [FRED Adapter](../02-data-pipelines/fred.md) — commodity and macro indicator data
- [Pipeline Framework](../02-data-pipelines/pipeline-framework.md) — staleness tracking, scheduling
- [Spec Conventions](../00-meta/spec-conventions.md) — date/time, naming rules
- [F01 — Portfolio Dashboard](./F01-portfolio-dashboard.md) — portfolio holdings and allocation data
- [F07 — Macro Dashboard](./F07-macro-dashboard.md) — existing macro indicators, regime assessment
- [F10 — Alerts & Rebalancing](./F10-alerts-rebalancing.md) — alert integration for high-severity events

## Data Requirements

### Global Events Data

Events are sourced from the [Global Events Pipeline](../02-data-pipelines/global-events.md) and stored in the `global_events` table:

| Field | Type | Description |
|-------|------|-------------|
| `source` | enum | `gdelt`, `acled`, `owid`, `open_meteo` |
| `event_type` | enum | `conflict`, `trade`, `weather`, `health`, `economic`, `energy`, `protest`, `strategic` |
| `headline` | VARCHAR(500) | Event headline / summary |
| `location_country` | VARCHAR(100) | Country of event |
| `sentiment_score` | NUMERIC(6,3) | GDELT tone (-100 to +100); NULL for non-GDELT sources |
| `impact_severity` | enum | `high`, `medium`, `low` |
| `affected_sectors` | JSONB | Array of sector names affected |
| `event_date` | TIMESTAMPTZ | When the event occurred |

### Sector Impact Data

Stored in `sector_impact_analysis`, linked to `global_events`:

| Field | Type | Description |
|-------|------|-------------|
| `event_id` | FK → `global_events` | Linked event |
| `sector` | VARCHAR(50) | Affected sector name |
| `impact_direction` | enum | `positive`, `negative`, `neutral` |
| `impact_magnitude` | SMALLINT (1-5) | Strength of impact |
| `reasoning` | TEXT | Explanation of why this sector is affected |

### Commodity & Alternative Data

Extended FRED series and alternative data sources stored in `macro_indicators`:

| Category | Indicator Codes | Source |
|----------|----------------|--------|
| Oil | `DCOILWTICO`, `DCOILBRENTEU` | FRED |
| Natural Gas | `DHHNGSP` | FRED |
| Gold | `GOLDAMGBD228NLBM` | FRED |
| Copper | `PCOPPUSDM` | FRED |
| Baltic Dry Index | `DBDI` | FRED |
| VIX | `VIXCLS` | FRED |
| US Housing Starts | `HOUST` | FRED |
| Case-Shiller Index | `CSUSHPINSA` | FRED |
| Consumer Sentiment | `UMCSENT` | FRED |
| Initial Jobless Claims | `ICSA` | FRED |
| Job Openings | `JTSJOL` | FRED |
| Vehicle Sales | `TOTALSA` | FRED |
| Finnish Housing Price | `FI_HOUSING_PRICE` | Tilastokeskus |
| Finnish Consumer Confidence | `FI_CONSUMER_CONFIDENCE` | Tilastokeskus |
| EU Housing Price Index | `EU_HOUSING_PRICE_INDEX` | Eurostat |
| EU Tourism Arrivals | `EU_TOURISM_ARRIVALS` | Eurostat |
| EU Unemployment | `EU_UNEMPLOYMENT` | Eurostat |
| Daily Flight Volume | `OPENSKY_FLIGHTS_DAILY` | OpenSky |

### Data Freshness

| Data Type | Refresh Interval | Staleness Threshold |
|-----------|-----------------|-------------------|
| GDELT events | Every 15 min | 30 min |
| ACLED events | Weekly | 14 days |
| Commodity prices (FRED) | Daily (weekdays) | 48 hours |
| VIX | Daily (weekdays) | 48 hours |
| Finnish indicators | Monthly | 60 days |
| Eurostat indicators | Monthly | 60 days |
| Weather events | Every 6 hours | 12 hours |
| Flight volume | Daily | 48 hours |

---

## API Endpoints

### Global Events

| Method | Path | Description |
|--------|------|-------------|
| GET | `/global-events` | Paginated event feed with filters |
| GET | `/global-events/{id}` | Event detail with full impact analysis |
| GET | `/global-events/sector-impact` | Current sector impact summary across all recent events |
| GET | `/global-events/sector-impact/{sector}` | Detailed impact analysis for one sector |
| GET | `/global-events/portfolio-impact` | How recent events affect the user's holdings |

### Commodities

| Method | Path | Description |
|--------|------|-------------|
| GET | `/commodities` | Current commodity prices and trend data |

### Alternative Data

| Method | Path | Description |
|--------|------|-------------|
| GET | `/alternative-data/housing` | Housing indicators (Finland, EU, US) |
| GET | `/alternative-data/travel` | Travel and aviation volume data |
| GET | `/alternative-data/employment` | Detailed employment data beyond headline unemployment |
| GET | `/alternative-data/sentiment` | Consumer sentiment indicators |

### Request: `GET /global-events`

Query parameters:

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `eventType` | string (multi-value) | all | Filter by event type: `conflict`, `trade`, `weather`, `health`, `economic`, `energy`, `protest`, `strategic` |
| `severity` | string (multi-value) | all | Filter by severity: `high`, `medium`, `low` |
| `region` | string | all | Filter by country or region name |
| `sector` | string | all | Filter by affected sector |
| `fromDate` | date (ISO 8601) | 30 days ago | Start of date range |
| `toDate` | date (ISO 8601) | today | End of date range |
| `q` | string | — | Free-text search in headlines |
| `limit` | integer | 50 | Page size (max 500) |
| `offset` | integer | 0 | Pagination offset |
| `sortBy` | string | `eventDate` | Sort field: `eventDate`, `severity`, `sentiment` |
| `sortOrder` | string | `desc` | `asc` or `desc` |

### Response: `GET /global-events`

```json
{
  "data": [
    {
      "id": 12345,
      "source": "gdelt",
      "eventType": "conflict",
      "eventSubtype": null,
      "headline": "Military tensions escalate in Middle East region",
      "description": "Source: reuters.com",
      "locationCountry": "Iran",
      "locationLat": 32.4279,
      "locationLon": 53.6880,
      "sentimentScore": -7.82,
      "impactSeverity": "high",
      "affectedSectors": ["Energy", "Airlines", "Defense"],
      "sourceUrl": "https://reuters.com/article/...",
      "eventDate": "2026-03-19T10:30:00Z"
    }
  ],
  "meta": {
    "timestamp": "2026-03-19T14:30:00Z",
    "cacheAge": 120,
    "stale": false
  },
  "pagination": {
    "total": 847,
    "limit": 50,
    "offset": 0,
    "hasMore": true
  }
}
```

### Response: `GET /global-events/{id}`

```json
{
  "data": {
    "id": 12345,
    "source": "gdelt",
    "eventType": "conflict",
    "headline": "Military tensions escalate in Middle East region",
    "description": "Source: reuters.com",
    "locationCountry": "Iran",
    "sentimentScore": -7.82,
    "impactSeverity": "high",
    "affectedSectors": ["Energy", "Airlines", "Defense"],
    "sourceUrl": "https://reuters.com/article/...",
    "eventDate": "2026-03-19T10:30:00Z",
    "sectorImpacts": [
      {
        "sector": "Energy",
        "impactDirection": "positive",
        "impactMagnitude": 4,
        "reasoning": "Middle East conflict historically drives oil prices higher, benefiting energy producers"
      },
      {
        "sector": "Airlines",
        "impactDirection": "negative",
        "impactMagnitude": 3,
        "reasoning": "Conflict zones disrupt flight routes, increase fuel costs, and reduce travel demand"
      },
      {
        "sector": "Defense",
        "impactDirection": "positive",
        "impactMagnitude": 4,
        "reasoning": "Military conflicts drive increased defense spending and procurement"
      }
    ],
    "affectedHoldings": [
      {
        "securityId": 42,
        "ticker": "XOM",
        "name": "Exxon Mobil Corp",
        "sector": "Energy",
        "impactDirection": "positive",
        "impactMagnitude": 4
      },
      {
        "securityId": 88,
        "ticker": "LHA.DE",
        "name": "Deutsche Lufthansa AG",
        "sector": "Airlines",
        "impactDirection": "negative",
        "impactMagnitude": 3
      }
    ],
    "affectedWatchlistItems": [
      {
        "securityId": 201,
        "ticker": "LMT",
        "name": "Lockheed Martin Corp",
        "sector": "Defense",
        "impactDirection": "positive",
        "impactMagnitude": 4
      }
    ]
  }
}
```

### Response: `GET /global-events/sector-impact`

```json
{
  "data": {
    "period": "last_30_days",
    "sectors": [
      {
        "sector": "Energy",
        "netImpact": 2.4,
        "eventCount": 18,
        "positiveEvents": 12,
        "negativeEvents": 4,
        "neutralEvents": 2,
        "topEvent": "OPEC announces production cut extension",
        "portfolioExposure": 8.5
      },
      {
        "sector": "Airlines",
        "netImpact": -1.8,
        "eventCount": 7,
        "positiveEvents": 1,
        "negativeEvents": 5,
        "neutralEvents": 1,
        "topEvent": "Military tensions escalate in Middle East region",
        "portfolioExposure": 2.1
      }
    ]
  }
}
```

### Response: `GET /global-events/portfolio-impact`

```json
{
  "data": {
    "period": "last_7_days",
    "overallImpact": "mixed",
    "highSeverityEvents": 3,
    "affectedHoldingsCount": 8,
    "holdings": [
      {
        "securityId": 42,
        "ticker": "XOM",
        "name": "Exxon Mobil Corp",
        "sector": "Energy",
        "currentWeight": 3.2,
        "events": [
          {
            "eventId": 12345,
            "headline": "Military tensions escalate in Middle East region",
            "impactDirection": "positive",
            "impactMagnitude": 4,
            "eventDate": "2026-03-19T10:30:00Z"
          }
        ],
        "netImpact": "positive",
        "netMagnitude": 3.5
      }
    ]
  }
}
```

### Response: `GET /commodities`

```json
{
  "data": {
    "commodities": [
      {
        "code": "DCOILWTICO",
        "name": "WTI Crude Oil",
        "latestValue": 78.45,
        "unit": "usd_per_barrel",
        "change1d": 1.23,
        "changePct1d": 1.59,
        "change30d": -3.45,
        "changePct30d": -4.21,
        "sparkline": [75.2, 76.1, 77.8, 76.5, 78.45],
        "lastUpdated": "2026-03-19T00:00:00Z"
      },
      {
        "code": "VIXCLS",
        "name": "VIX (Fear Index)",
        "latestValue": 18.72,
        "unit": "index",
        "change1d": 2.15,
        "changePct1d": 12.97,
        "change30d": 4.30,
        "changePct30d": 29.80,
        "sparkline": [14.4, 15.1, 16.2, 17.8, 18.72],
        "lastUpdated": "2026-03-19T00:00:00Z"
      }
    ]
  },
  "meta": {
    "timestamp": "2026-03-19T14:30:00Z",
    "cacheAge": 3600,
    "stale": false
  }
}
```

### Response: `GET /alternative-data/housing`

```json
{
  "data": {
    "indicators": [
      {
        "code": "FI_HOUSING_PRICE",
        "name": "Finnish Housing Price Index",
        "source": "tilastokeskus",
        "latestValue": 102.3,
        "unit": "index",
        "latestDate": "2026-02-01",
        "change": -1.2,
        "changePct": -1.16,
        "sparkline": [105.1, 104.2, 103.5, 102.8, 102.3],
        "lastUpdated": "2026-03-15T08:00:00Z"
      },
      {
        "code": "EU_HOUSING_PRICE_INDEX",
        "name": "EU House Price Index",
        "source": "eurostat",
        "latestValue": 148.7,
        "unit": "index",
        "latestDate": "2025-Q4",
        "change": 2.1,
        "changePct": 1.43,
        "sparkline": [144.2, 145.6, 146.8, 147.9, 148.7],
        "lastUpdated": "2026-03-15T09:00:00Z"
      },
      {
        "code": "CSUSHPINSA",
        "name": "Case-Shiller Home Price Index (US)",
        "source": "fred",
        "latestValue": 322.15,
        "unit": "index",
        "latestDate": "2026-01-01",
        "change": 1.85,
        "changePct": 0.58,
        "sparkline": [318.2, 319.4, 320.1, 321.3, 322.15],
        "lastUpdated": "2026-03-18T22:00:00Z"
      }
    ]
  }
}
```

---

## UI Views

The Global Events & Sector Impact Dashboard is organized into four sub-tabs.

### Sub-tab: Event Feed

- **Event feed** (reverse chronological, card-based layout):
  - Each event card shows:
    - Headline (bold, primary text)
    - Source badge (`GDELT`, `ACLED`, `OWID`, `Weather`) with source-specific color
    - Event date (relative format, e.g., "2h ago", "3d ago")
    - Location (country flag + name)
    - Severity badge: `HIGH` (red), `MEDIUM` (amber), `LOW` (gray)
    - Affected sector tags (colored pills)
    - Sentiment indicator: negative tone shown as red bar, positive as green bar, proportional to score magnitude
  - Click to expand event card:
    - Full description and source link (opens in new tab)
    - Sector impact breakdown table: sector, direction arrow (up/down/neutral), magnitude (1-5 dots), reasoning text
    - "Your affected holdings" section: list of portfolio holdings in affected sectors with ticker, name, sector, and impact direction
    - "Affected watchlist items" section: same format for watchlist securities
- **Filter bar** (top of feed):
  - Event type filter: multi-select dropdown (`Conflict`, `Trade`, `Weather`, `Health`, `Economic`, `Energy`, `Protest`, `Strategic`)
  - Severity filter: multi-select (`High`, `Medium`, `Low`)
  - Region filter: dropdown of countries/regions
  - Sector filter: dropdown of sectors
  - Date range picker: from/to date
  - Free-text search: searches headlines
- **Pagination**: offset-based with "Load more" button at bottom

### Sub-tab: Sector Impact

- **Sector heatmap** (primary visualization):
  - Grid of sector tiles (4-5 per row)
  - Each tile shows: sector name, net impact score, event count, trend arrow
  - Color gradient: bright green (strong positive impact) through gray (neutral) to bright red (strong negative impact)
  - Color intensity based on `netImpact` value from `/global-events/sector-impact`
- **Portfolio exposure overlay**:
  - Each sector tile also shows a small bar indicating the user's portfolio weight in that sector (from F01 allocation data)
  - Sectors where the user has significant exposure AND negative impact are highlighted with a warning icon
- **Per-sector detail panel** (click a sector tile to expand):
  - List of events affecting this sector (last 30 days), sorted by magnitude
  - List of user's holdings in this sector with current value and weight
  - Net impact assessment with reasoning
  - See component: `SectorDetailPanel`
- **Impact timeline chart** (below heatmap):
  - Recharts area chart showing how sector impacts have evolved
  - X-axis: date (configurable: 30d, 90d, 365d)
  - Y-axis: net impact score per sector
  - Multiple sector lines, color-coded to match heatmap
  - Hover tooltip shows exact values per sector at that date

### Sub-tab: Commodities

- **Commodity price cards** (grid layout, 2-3 per row):
  - Each card uses the `MetricCard` component pattern
  - Shows: commodity name, current price, unit, 1-day change (absolute + percentage), 30-day change, sparkline (last 30 data points)
  - Color coding: green if price rose (for holdings that benefit from rises), red if fell
  - Cards for: WTI Crude Oil, Brent Crude Oil, Natural Gas, Gold, Copper
  - See component: `MetricCard`
- **Special indicator cards**:
  - Baltic Dry Index card: shows index value with trend, tooltip explains "proxy for global shipping and trade activity"
  - VIX card: shows current value with trend; above 20 = amber badge "Elevated Fear", above 30 = red badge "High Fear", above 40 = red flashing badge "Extreme Fear"
- **Commodity detail charts** (click any card):
  - Full time-series chart (Recharts line chart) with configurable date range (1M, 3M, 6M, 1Y, 5Y)
  - Key levels overlay: 52-week high/low as horizontal dashed lines
- **Portfolio commodity sensitivity** (bottom section):
  - Table listing holdings that are commodity-sensitive
  - Columns: ticker, name, primary commodity exposure, current commodity price trend, estimated impact direction
  - Example: "XOM — Oil exposure — WTI up 1.6% today — Positive"

### Sub-tab: Alternative Data

- **Housing section** (card group):
  - `MetricCard` for each housing indicator: Finnish Housing Price Index, EU Housing Price Index, US Case-Shiller
  - Each card shows: latest value, change from previous period, sparkline trend
  - Click for full time-series chart
- **Travel & Aviation section** (card group):
  - `MetricCard` for: Daily Flight Volume (OpenSky), EU Tourism Arrivals (Eurostat)
  - Flight volume card includes a tooltip: "Leading indicator for airline and travel sector activity"
  - Sparkline shows last 30/90 data points
- **Employment section** (card group):
  - `MetricCard` for: US Initial Jobless Claims, US Job Openings (JOLTS), Finnish Employment Rate, EU Unemployment
  - Each card shows change direction with trend arrow
- **Consumer Sentiment section** (card group):
  - `MetricCard` for: Michigan Consumer Sentiment, Finnish Consumer Confidence
  - Cards color-coded: green if sentiment improving, red if deteriorating
- Each section is collapsible to manage vertical space
- All cards show a staleness badge if data is older than 2x the expected refresh interval

---

## Business Rules

1. **Event severity auto-classification**: events are classified by severity based on GDELT tone score and event type per the rules in the [Global Events Pipeline](../02-data-pipelines/global-events.md#severity-classification). Severity is stored at ingestion time and not recomputed on the fly.

2. **Sector impact rule engine**: sector impacts are derived from pre-defined rules mapping event types to sectors (see [sector impact mapping](../02-data-pipelines/global-events.md#sector-impact-mapping-rules)). Rules are applied at event ingestion time and stored in `sector_impact_analysis`.

3. **Portfolio holdings linkage**: the `/global-events/portfolio-impact` endpoint joins `sector_impact_analysis` with the user's current `positions` and `securities` tables. A holding is "affected" if its `sector` field matches any sector in the event's impact analysis.

4. **Watchlist linkage**: same logic as holdings linkage but using securities in the user's watchlists (from `watchlist_items`).

5. **High-severity alert integration**: when a high-severity event is ingested that affects a sector containing at least one of the user's holdings, an alert is generated per the [F10 — Alerts](./F10-alerts-rebalancing.md) system. Alert type: `global_event_impact`. Alert message includes: event headline, affected holdings list, and impact direction.

6. **Net sector impact calculation**: the `netImpact` score for a sector is computed as the weighted average of `impact_magnitude * direction_sign` for all events in the selected period, where `direction_sign` is +1 for positive, -1 for negative, 0 for neutral.

7. **Commodity data freshness**: commodity prices follow the same refresh schedule as the extended FRED pipeline (daily on weekdays, 22:00 UTC). Weekend commodity data shows Friday's close.

8. **GDELT refresh cycle**: the event feed is refreshed every 15 minutes. The UI should auto-poll the `/global-events` endpoint every 60 seconds when the Event Feed tab is active, using the last-fetched event date as a cursor.

9. **Staleness badge display**: per standard staleness handling across all data types. A staleness badge (amber "Data may be outdated" label with last-updated timestamp) appears on any card or section whose source pipeline has exceeded its staleness threshold.

10. **Event deduplication in UI**: if multiple near-identical events exist (e.g., same GDELT story from different sources), the UI shows only the first occurrence. The API handles deduplication at ingestion per the [pipeline spec](../02-data-pipelines/global-events.md#idempotency).

---

## Edge Cases

1. **No events matching filters**: the Event Feed shows an empty state message: "No events match your filters. Try broadening your search criteria." with a button to reset all filters.

2. **No portfolio holdings**: if the user has no holdings, the Sector Impact tab still shows the heatmap (sector impacts exist regardless of holdings), but the "Portfolio Exposure" overlay is hidden and "Your affected holdings" sections in event detail show "No holdings in this sector."

3. **Sector mismatch**: some holdings may not have a `sector` field populated in the `securities` table (e.g., newly added securities). These holdings are excluded from sector impact matching. A warning badge on the Portfolio Impact view notes: "{N} holdings have no sector assigned and are excluded from impact analysis."

4. **All pipelines stale**: if all global events pipelines are stale, the Event Feed shows a banner: "Event data may be outdated. Last updated: {timestamp}." The feed still displays cached events.

5. **Commodity data gaps on weekends/holidays**: commodity cards show the most recent available value with the date label. No interpolation or forward-fill is applied.

6. **VIX spike**: when VIX rises above 30 (High Fear threshold) within a single trading day, this is treated as an implicit high-severity economic event. The system generates a synthetic `global_events` record of type `economic` to ensure it appears in the Event Feed and triggers portfolio impact analysis.

7. **Extreme weather false positives**: weather events are generated from forecasts, not observations. If a forecast-based extreme weather event does not materialize in subsequent fetches, the event remains in the feed but is not retroactively deleted. No severity upgrade occurs from forecasts alone.

8. **Very old alternative data**: some alternative data sources (Tilastokeskus, Eurostat) update monthly or quarterly. Cards for these sources display the observation period prominently (e.g., "As of 2026-Q4") so users understand the data lag is expected, not a pipeline failure.

9. **Large number of affected sectors**: some events (e.g., global pandemic) affect many sectors simultaneously. The event card in the feed shows up to 5 sector tags with a "+{N} more" overflow indicator. The expanded detail shows all sectors.

10. **Sector naming consistency**: sector names in `sector_impact_analysis` must match sector names in the `securities` table. A mapping table or normalization layer ensures consistency (e.g., "Tech" in impact rules maps to "Information Technology" in securities if that is the canonical name).

---

## Acceptance Criteria

1. The Event Feed tab displays a chronological feed of global events from GDELT and ACLED with correct severity badges, affected sector tags, and sentiment indicators.

2. Event feed filtering works for all filter types: event type, severity, region, sector, date range, and free-text search. Filters can be combined.

3. Clicking an event card expands to show full impact analysis including sector impacts with direction, magnitude, and reasoning.

4. Expanded event detail shows which of the user's actual holdings and watchlist securities are affected, with correct sector matching.

5. The Sector Impact heatmap displays all sectors with correct color coding based on net impact scores derived from recent events.

6. Portfolio exposure is overlaid on the sector heatmap, and sectors with high exposure and negative impact are visually highlighted.

7. Clicking a sector tile shows the detail panel with events affecting that sector and the user's holdings in that sector.

8. The Commodities tab shows current prices for WTI, Brent, Natural Gas, Gold, and Copper with 1-day and 30-day changes and sparklines.

9. The VIX card displays the correct fear level badge (Elevated/High/Extreme) based on current value thresholds.

10. The Alternative Data tab shows housing indicators from all three sources (Finland, EU, US), travel data, employment data, and consumer sentiment with sparklines.

11. High-severity events affecting held securities trigger an alert via the F10 alerts system.

12. Staleness badges appear on any data card or section whose source pipeline exceeds the staleness threshold.

13. All timestamps display in `Europe/Helsinki` timezone per spec conventions.

14. All API endpoints follow the standard response envelope with `data`, `meta` (including `cacheAge` and `stale`), and `pagination` where applicable.

15. The sector impact timeline chart renders correctly for 30-day, 90-day, and 365-day periods with multiple sector lines.

---

## Changelog

| Date | Change |
|------|--------|
| 2026-03-19 | Initial draft |
