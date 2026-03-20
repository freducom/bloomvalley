# Global Events Pipeline

Multi-source data pipeline aggregating global macro events, alternative economic data, and sector-impacting signals from GDELT, ACLED, FRED (additional commodity/labor/housing series), Our World in Data, Open-Meteo, Tilastokeskus, Eurostat, and OpenSky Network. This pipeline feeds the Global Events & Sector Impact Dashboard (F18) and provides the Macro Strategist with real-time awareness of world events that may affect portfolio holdings and watchlist securities.

**Status: DRAFT**

## Dependencies

- [Pipeline Framework](./pipeline-framework.md) — base adapter interface, scheduling, error handling, retry logic
- [FRED Adapter](./fred.md) — existing FRED pipeline (this pipeline extends with additional series)
- [Data Model](../01-system/data-model.md) — target table schemas
- [Architecture](../01-system/architecture.md) — environment variables, Redis caching, APScheduler
- [Spec Conventions](../00-meta/spec-conventions.md) — naming, date format, monetary values

---

## Source Summary

| Source | Data Types | Schedule | Rate Limit | Auth |
|--------|-----------|----------|------------|------|
| **GDELT Project** | Global news events, sentiment, geolocation | Every 15 min | ~10 req/min (recommended) | None |
| **FRED (extended)** | Commodity prices, labor, housing, sentiment, VIX | Daily / Monthly | 120 req/min | API key (required) |
| **ACLED** | Armed conflict events, protests, riots | Weekly | Reasonable free tier | API key (registration required) |
| **Our World in Data** | Pandemic, mortality, energy, pollution indicators | Weekly | None (GitHub raw files) | None |
| **Open-Meteo** | Extreme weather events, forecasts | Every 6 hours | None (free, no key) | None |
| **Tilastokeskus** | Finnish housing prices, construction, employment | Monthly | No published limit | None |
| **Eurostat** | EU housing index, tourism, industrial production | Monthly | No published limit | None |
| **OpenSky Network** | Flight volume trends (experimental) | Daily | Free tier | None |

---

## Source 1: GDELT Project (Primary)

### Description

The GDELT Global Knowledge Graph monitors world news from 100+ countries in 65+ languages, classifying events using CAMEO event codes and providing sentiment analysis, geolocation, and actor identification. This is the primary event source for the pipeline.

### API Details

| Property | Value |
|----------|-------|
| Base URL | `https://api.gdeltproject.org/api/v2/doc/doc` |
| Format | JSON |
| Auth | None |
| Rate limit | ~10 req/min (recommended; no hard published limit) |
| Refresh | Every 15 minutes (GDELT updates this frequently) |

### Query Categories

The adapter runs the following queries on each fetch cycle, covering the event types most relevant to portfolio impact:

| Query Category | GDELT Query Terms | Mapped Event Type |
|---------------|-------------------|-------------------|
| Conflicts & military | `conflict OR military OR war OR airstrike` | `conflict` |
| Trade disputes & sanctions | `tariff OR sanction OR trade war OR trade dispute` | `trade` |
| Natural disasters | `earthquake OR hurricane OR flood OR wildfire OR drought` | `weather` |
| Economic policy | `interest rate OR central bank OR fiscal policy OR stimulus` | `economic` |
| Pandemic & health | `pandemic OR outbreak OR epidemic OR WHO emergency` | `health` |
| Energy markets | `oil price OR OPEC OR energy crisis OR pipeline` | `energy` |

### Sample API Request

```
GET https://api.gdeltproject.org/api/v2/doc/doc
  ?query=conflict OR military OR war
  &mode=artlist
  &maxrecords=50
  &format=json
  &timespan=15min
```

### Sample Response

```json
{
  "articles": [
    {
      "url": "https://example.com/article",
      "url_mobile": "",
      "title": "Military tensions escalate in region",
      "seendate": "20260319T143000Z",
      "socialimage": "",
      "domain": "example.com",
      "language": "English",
      "sourcecountry": "United States",
      "tone": -3.45
    }
  ]
}
```

### Data Mapping: GDELT to `global_events`

| Source Field | Database Column | Transformation |
|-------------|-----------------|----------------|
| `title` | `headline` | Direct string, truncate to 500 chars |
| (from query category) | `event_type` | Map query category to enum value |
| `seendate` | `event_date` | Parse `YYYYMMDDTHHMMSSZ` to timestamp |
| `sourcecountry` | `location_country` | Direct string |
| `tone` | `sentiment_score` | `NUMERIC(6,3)` — GDELT tone ranges from -100 to +100 |
| `url` | `source_url` | Direct string |
| `domain` | `description` | Used as source attribution |
| (constant) | `source` | `'gdelt'` |
| (derived from tone + event_type) | `impact_severity` | See severity classification below |
| (derived from event_type) | `affected_sectors` | JSONB array, see sector impact mapping |
| `NOW()` | `fetched_at` | Timestamp of ingestion |

### Severity Classification

| Condition | Severity |
|-----------|----------|
| abs(tone) >= 10.0 AND event_type in (`conflict`, `weather`, `health`) | `high` |
| abs(tone) >= 5.0 OR event_type in (`trade`, `energy`) | `medium` |
| All other events | `low` |

---

## Source 2: FRED Extended Series

### Description

Additional FRED series beyond those in the [existing FRED adapter](./fred.md), covering commodities, labor market detail, housing, consumer sentiment, and the VIX fear index.

### Authentication

Same as existing FRED adapter — uses `FRED_API_KEY` environment variable.

### Extended Series Catalog

#### Commodities

| Series ID | Name | Frequency | Unit | Description |
|-----------|------|-----------|------|-------------|
| `DCOILWTICO` | WTI Crude Oil Price | Daily | usd_per_barrel | West Texas Intermediate spot price |
| `DCOILBRENTEU` | Brent Crude Oil Price | Daily | usd_per_barrel | Europe Brent spot price |
| `DHHNGSP` | Henry Hub Natural Gas Spot Price | Daily | usd_per_mmbtu | US natural gas benchmark |
| `GOLDAMGBD228NLBM` | Gold Price (London PM Fix) | Daily | usd_per_troy_oz | Gold fixing price |
| `PCOPPUSDM` | Copper Price | Monthly | usd_per_pound | Global copper price |

#### Shipping & Trade

| Series ID | Name | Frequency | Unit | Description |
|-----------|------|-----------|------|-------------|
| `DBDI` | Baltic Dry Index | Daily | index | Shipping cost proxy, global trade activity indicator |

#### Labor Market (Extended)

| Series ID | Name | Frequency | Unit | Description |
|-----------|------|-----------|------|-------------|
| `ICSA` | Initial Jobless Claims | Weekly | thousands | Leading labor market indicator |
| `JTSJOL` | Job Openings (JOLTS) | Monthly | thousands | Labor demand indicator |

#### Housing

| Series ID | Name | Frequency | Unit | Description |
|-----------|------|-----------|------|-------------|
| `HOUST` | Housing Starts | Monthly | thousands | Residential construction activity |
| `CSUSHPINSA` | Case-Shiller Home Price Index | Monthly | index | US home price trend (20-city composite) |

#### Sentiment & Volatility

| Series ID | Name | Frequency | Unit | Description |
|-----------|------|-----------|------|-------------|
| `UMCSENT` | Michigan Consumer Sentiment | Monthly | index | Consumer confidence proxy (already in base FRED but included here for commodity context) |
| `VIXCLS` | VIX (CBOE Volatility Index) | Daily | index | Market fear gauge |

#### Auto & Semiconductor

| Series ID | Name | Frequency | Unit | Description |
|-----------|------|-----------|------|-------------|
| `TOTALSA` | Total Vehicle Sales | Monthly | millions | US auto sales |

### Data Mapping

All extended FRED series map to the `macro_indicators` table using the same pattern as the [existing FRED adapter](./fred.md#data-mapping):

| Source Field | Database Column | Transformation |
|-------------|-----------------|----------------|
| Series ID | `indicator_code` | Direct string |
| `date` | `date` | `DATE` |
| `value` | `value` | `Decimal(str(value))` |
| (from catalog) | `unit` | Mapped per series |
| (constant) | `source` | `'fred'` |

### Validation Rules

Same base rules as [existing FRED adapter](./fred.md#validation-rules) plus:

1. **Commodity prices**: must be > 0 (oil, gas, gold, copper cannot be negative in spot markets)
2. **VIX**: must be between 0 and 150 (historical max was ~82 in 2020; 150 provides headroom)
3. **Baltic Dry Index**: must be > 0
4. **Housing Starts**: must be >= 0
5. **Vehicle Sales**: must be >= 0
6. **Missing value marker**: FRED `"."` values skipped, same as existing adapter

---

## Source 3: ACLED

### Description

The Armed Conflict Location & Event Data Project provides detailed information on conflict events, protests, riots, and strategic developments worldwide. Free for research and personal use with registration.

### API Details

| Property | Value |
|----------|-------|
| Base URL | `https://api.acleddata.com/acled/read` |
| Format | JSON |
| Auth | API key + email (registration required) |
| Rate limit | Reasonable free tier |
| Refresh | Weekly |

| Environment Variable | Required | Description |
|---------------------|----------|-------------|
| `ACLED_API_KEY` | Yes | ACLED API key (free registration) |
| `ACLED_EMAIL` | Yes | Email used for ACLED registration |

### Sample API Request

```
GET https://api.acleddata.com/acled/read
  ?key={ACLED_API_KEY}
  &email={ACLED_EMAIL}
  &event_date={from_date}|{to_date}
  &event_date_where=BETWEEN
  &limit=500
```

### Sample Response

```json
{
  "status": 200,
  "success": true,
  "data": [
    {
      "data_id": 12345678,
      "event_date": "2026-03-15",
      "event_type": "Battles",
      "sub_event_type": "Armed clash",
      "country": "Syria",
      "location": "Aleppo",
      "latitude": "36.2021",
      "longitude": "37.1343",
      "fatalities": 5,
      "notes": "Armed clash between government forces and opposition fighters..."
    }
  ]
}
```

### Data Mapping: ACLED to `global_events`

| Source Field | Database Column | Transformation |
|-------------|-----------------|----------------|
| `notes` (first 500 chars) | `headline` | Truncate to 500 chars |
| `notes` | `description` | Full text |
| `event_type` | `event_type` | Map to `conflict` (Battles, Explosions), `protest` (Protests, Riots), `strategic` (Strategic developments) |
| `sub_event_type` | `event_subtype` | Direct string |
| `event_date` | `event_date` | Parse `YYYY-MM-DD` |
| `country` | `location_country` | Direct string |
| `latitude` | `location_lat` | `NUMERIC(9,6)` |
| `longitude` | `location_lon` | `NUMERIC(9,6)` |
| (derived from fatalities + event_type) | `impact_severity` | fatalities >= 50 → `high`; fatalities >= 10 → `medium`; else `low` |
| (derived from event_type + country) | `affected_sectors` | JSONB array, see sector impact mapping |
| (none) | `sentiment_score` | `NULL` (ACLED does not provide sentiment) |
| (constant) | `source` | `'acled'` |
| (construct from ACLED URL) | `source_url` | `https://acleddata.com/` |
| `NOW()` | `fetched_at` | Timestamp of ingestion |

---

## Source 4: Our World in Data (OWID)

### Description

Open-source datasets covering pandemic indicators, vaccination rates, excess mortality, air pollution, and energy production. Data is accessed via raw CSV files hosted on GitHub.

### Data Access

| Property | Value |
|----------|-------|
| Source | GitHub raw CSV files |
| Auth | None |
| Rate limit | None (standard GitHub raw file access) |
| Refresh | Weekly |

### Datasets

| Dataset | GitHub URL | Key Fields | Mapped Event Type |
|---------|-----------|------------|-------------------|
| COVID-19 | `https://raw.githubusercontent.com/owid/covid-19-data/master/public/data/latest/owid-covid-latest.csv` | new_cases, new_deaths, icu_patients | `health` |
| Excess Mortality | `https://raw.githubusercontent.com/owid/covid-19-data/master/public/data/excess_mortality/excess_mortality.csv` | excess_mortality_cumulative | `health` |
| Energy | `https://raw.githubusercontent.com/owid/energy-data/master/owid-energy-data.csv` | energy_per_capita, renewables_share | `energy` |

### Data Mapping: OWID to `global_events`

OWID data is aggregated into summary events when significant thresholds are crossed (e.g., new pandemic wave detected, excess mortality spike). Routine data points are stored in `macro_indicators` rather than `global_events`.

| Condition | Action |
|-----------|--------|
| Weekly new cases increase > 50% in any G20 country | Create `global_events` record, severity `high`, type `health` |
| Excess mortality > 10% above baseline in any EU country | Create `global_events` record, severity `medium`, type `health` |
| All other data points | Store in `macro_indicators` with source `'owid'` |

---

## Source 5: Open-Meteo

### Description

Free weather API providing current conditions, forecasts, and historical data. Used to detect extreme weather events in regions relevant to portfolio holdings (e.g., hurricanes in Gulf Coast affecting oil refineries, drought in agricultural regions).

### API Details

| Property | Value |
|----------|-------|
| Base URL | `https://api.open-meteo.com/v1/forecast` |
| Format | JSON |
| Auth | None (free, no API key required) |
| Rate limit | No published limit; recommend < 30 req/min |
| Refresh | Every 6 hours |

### Monitored Regions

| Region | Coordinates | Relevance |
|--------|------------|-----------|
| US Gulf Coast (Houston) | 29.76, -95.37 | Oil refining, energy infrastructure |
| US Midwest (Chicago) | 41.88, -87.63 | Agriculture, commodities |
| Northern Europe (Helsinki) | 60.17, 24.94 | Finnish market, local holdings |
| Central Europe (Frankfurt) | 50.11, 8.68 | EU market, ECB region |
| East Asia (Shanghai) | 31.23, 121.47 | Supply chain, manufacturing |

### Sample API Request

```
GET https://api.open-meteo.com/v1/forecast
  ?latitude=29.76
  &longitude=-95.37
  &daily=temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max
  &timezone=auto
```

### Extreme Weather Event Detection

| Condition | Event Created | Severity | Affected Sectors |
|-----------|--------------|----------|-----------------|
| Wind speed > 120 km/h (hurricane force) | Yes | `high` | Energy, Insurance, Airlines |
| Temperature > 45C or < -30C | Yes | `medium` | Agriculture, Energy, Transportation |
| Precipitation > 100mm/day | Yes | `medium` | Agriculture, Insurance, Construction |
| Drought (< 1mm rain for 30+ days in agricultural region) | Yes | `medium` | Agriculture, Commodities |

---

## Source 6: Tilastokeskus (Statistics Finland)

### Description

Official Finnish statistical agency providing housing prices, construction permits, rental indices, employment by sector, and consumer confidence. Data accessed via PxWeb API.

### API Details

| Property | Value |
|----------|-------|
| Base URL | `https://pxdata.stat.fi/PxWeb/api/v1/en/StatFin/` |
| Format | JSON-stat |
| Auth | None |
| Rate limit | No published limit; recommend < 10 req/min |
| Refresh | Monthly |

### Series Tracked

| Dataset Path | Indicator Code | Name | Frequency | Unit |
|-------------|---------------|------|-----------|------|
| `ashi/statfin_ashi_pxt_112p.px` | `FI_HOUSING_PRICE` | Finnish Housing Price Index | Monthly | index |
| `ras/statfin_ras_pxt_116s.px` | `FI_CONSTRUCTION_PERMITS` | Building Permits Granted | Monthly | count |
| `asvh/statfin_asvh_pxt_11x4.px` | `FI_RENTAL_INDEX` | Rental Price Index | Quarterly | index |
| `tyti/statfin_tyti_pxt_135y.px` | `FI_EMPLOYMENT_RATE` | Employment Rate | Monthly | percent |
| `kbar/statfin_kbar_pxt_001.px` | `FI_CONSUMER_CONFIDENCE` | Consumer Confidence Indicator | Monthly | balance_figure |

### Data Mapping: Tilastokeskus to `macro_indicators`

| Source Field | Database Column | Transformation |
|-------------|-----------------|----------------|
| (from dataset path) | `indicator_code` | Use indicator codes above |
| Period field | `date` | Parse Finnish period format (e.g., `2026M02` → `2026-02-01`) |
| Value | `value` | `Decimal(str(value))` |
| (from catalog) | `unit` | Mapped per series |
| (constant) | `source` | `'tilastokeskus'` |

---

## Source 7: Eurostat

### Description

EU statistical agency providing EU-wide housing prices, tourism arrivals, industrial production, employment, and trade balance data.

### API Details

| Property | Value |
|----------|-------|
| Base URL | `https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/` |
| Format | JSON-stat |
| Auth | None |
| Rate limit | No published limit; recommend < 10 req/min |
| Refresh | Monthly |

### Series Tracked

| Dataset Code | Indicator Code | Name | Frequency | Unit |
|-------------|---------------|------|-----------|------|
| `prc_hpi_q` | `EU_HOUSING_PRICE_INDEX` | EU House Price Index | Quarterly | index |
| `tour_occ_nim` | `EU_TOURISM_ARRIVALS` | EU Tourism Nights Spent | Monthly | millions |
| `sts_inpr_m` | `EU_INDUSTRIAL_PRODUCTION` | EU Industrial Production Index | Monthly | index |
| `une_rt_m` | `EU_UNEMPLOYMENT` | EU Unemployment Rate | Monthly | percent |
| `ext_lt_maineu` | `EU_TRADE_BALANCE` | EU Trade Balance | Monthly | millions_eur |

### Data Mapping: Eurostat to `macro_indicators`

| Source Field | Database Column | Transformation |
|-------------|-----------------|----------------|
| (from dataset code) | `indicator_code` | Use indicator codes above |
| Time period | `date` | Parse Eurostat period format (e.g., `2026-Q1` → `2026-01-01`, `2026M02` → `2026-02-01`) |
| Value | `value` | `Decimal(str(value))` |
| (from catalog) | `unit` | Mapped per series |
| (constant) | `source` | `'eurostat'` |

---

## Source 8: OpenSky Network (Experimental)

### Description

Free flight tracking API used as a leading indicator for travel/airline sector recovery or downturn. Tracks total daily flight volume as a trend metric.

### API Details

| Property | Value |
|----------|-------|
| Base URL | `https://opensky-network.org/api` |
| Format | JSON |
| Auth | None (anonymous access) |
| Rate limit | 100 req/day (anonymous); 1000 req/day (registered) |
| Refresh | Daily aggregate |

### Data Mapping

Daily total flight count is stored in `macro_indicators`:

| Source Field | Database Column | Transformation |
|-------------|-----------------|----------------|
| (constant) | `indicator_code` | `'OPENSKY_FLIGHTS_DAILY'` |
| Query date | `date` | `DATE` |
| Count of active flights | `value` | `Decimal` |
| (constant) | `unit` | `'count'` |
| (constant) | `source` | `'opensky'` |

### Note

This source is experimental. If the free tier proves unreliable or insufficient, it can be disabled without affecting core functionality.

---

## Database Schema Additions

### New Enum Types

```sql
CREATE TYPE global_events_source_enum AS ENUM (
    'gdelt',
    'acled',
    'owid',
    'open_meteo'
);

CREATE TYPE global_events_type_enum AS ENUM (
    'conflict',
    'trade',
    'weather',
    'health',
    'economic',
    'energy',
    'protest',
    'strategic'
);

CREATE TYPE impact_severity_enum AS ENUM (
    'high',
    'medium',
    'low'
);

CREATE TYPE impact_direction_enum AS ENUM (
    'positive',
    'negative',
    'neutral'
);
```

### Table: `global_events`

```sql
CREATE TABLE global_events (
    id                  BIGSERIAL PRIMARY KEY,
    source              global_events_source_enum NOT NULL,
    event_type          global_events_type_enum NOT NULL,
    event_subtype       VARCHAR(100),
    headline            VARCHAR(500) NOT NULL,
    description         TEXT,
    location_country    VARCHAR(100),
    location_lat        NUMERIC(9, 6),
    location_lon        NUMERIC(9, 6),
    sentiment_score     NUMERIC(6, 3),          -- GDELT tone: -100 to +100; NULL for non-GDELT sources
    impact_severity     impact_severity_enum NOT NULL DEFAULT 'low',
    affected_sectors    JSONB DEFAULT '[]',     -- e.g. ["Energy", "Airlines", "Defense"]
    source_url          TEXT,
    event_date          TIMESTAMP WITH TIME ZONE NOT NULL,
    fetched_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_global_events_event_date ON global_events (event_date DESC);
CREATE INDEX idx_global_events_event_type ON global_events (event_type);
CREATE INDEX idx_global_events_severity ON global_events (impact_severity);
CREATE INDEX idx_global_events_source ON global_events (source);
CREATE INDEX idx_global_events_affected_sectors ON global_events USING GIN (affected_sectors);
```

### Table: `sector_impact_analysis`

```sql
CREATE TABLE sector_impact_analysis (
    id                  BIGSERIAL PRIMARY KEY,
    event_id            BIGINT NOT NULL REFERENCES global_events(id) ON DELETE CASCADE,
    sector              VARCHAR(50) NOT NULL,
    impact_direction    impact_direction_enum NOT NULL,
    impact_magnitude    SMALLINT NOT NULL CHECK (impact_magnitude BETWEEN 1 AND 5),
    reasoning           TEXT,
    created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_sector_impact_event_id ON sector_impact_analysis (event_id);
CREATE INDEX idx_sector_impact_sector ON sector_impact_analysis (sector);
CREATE UNIQUE INDEX idx_sector_impact_event_sector ON sector_impact_analysis (event_id, sector);
```

### Extended `pipeline_runs_source_enum`

Add new values to the existing enum:

```sql
ALTER TYPE pipeline_runs_source_enum ADD VALUE 'gdelt';
ALTER TYPE pipeline_runs_source_enum ADD VALUE 'acled';
ALTER TYPE pipeline_runs_source_enum ADD VALUE 'owid';
ALTER TYPE pipeline_runs_source_enum ADD VALUE 'open_meteo';
ALTER TYPE pipeline_runs_source_enum ADD VALUE 'tilastokeskus';
ALTER TYPE pipeline_runs_source_enum ADD VALUE 'eurostat';
ALTER TYPE pipeline_runs_source_enum ADD VALUE 'opensky';
```

---

## Sector Impact Mapping Rules

A rules engine maps event types to affected sectors. These rules are applied automatically when events are ingested and stored in `sector_impact_analysis`.

| Event Type | Affected Sectors | Direction | Magnitude |
|-----------|-----------------|-----------|-----------|
| Middle East conflict | Energy (+), Airlines (-), Defense (+) | Mixed | 3-4 |
| Oil price spike (WTI > +5% daily) | Energy (+), Transportation (-), Consumer Discretionary (-) | Mixed | 3-4 |
| Pandemic outbreak | Healthcare (+), Travel & Leisure (-), Tech (+remote work) | Mixed | 4-5 |
| Interest rate hike | Banks (+), REITs (-), Growth Tech (-), Bonds (-) | Mixed | 3-4 |
| Extreme weather / hurricane | Insurance (-), Construction (+rebuild), Agriculture (-) | Mixed | 3-4 |
| Trade war / tariffs | Import-dependent manufacturers (-), Domestic producers (+) | Mixed | 3-4 |
| Currency devaluation | Exporters (+), Importers (-) | Mixed | 2-3 |
| Supply chain disruption | Semiconductors (-), EV manufacturers (-), Diversified manufacturers (-) | Negative | 3-5 |
| Consumer sentiment drop | Retail (-), Luxury (-), Consumer Staples (neutral) | Negative | 2-3 |
| Housing market decline | Banks (-), Construction (-), REITs (-) | Negative | 3-4 |

### Rule Implementation

```python
SECTOR_IMPACT_RULES: dict[str, list[dict]] = {
    "conflict": [
        {"sector": "Energy", "direction": "positive", "magnitude": 3, "condition": "Middle East OR Russia"},
        {"sector": "Airlines", "direction": "negative", "magnitude": 3},
        {"sector": "Defense", "direction": "positive", "magnitude": 4},
        {"sector": "Insurance", "direction": "negative", "magnitude": 2},
    ],
    "trade": [
        {"sector": "Import-Dependent Manufacturing", "direction": "negative", "magnitude": 3},
        {"sector": "Domestic Producers", "direction": "positive", "magnitude": 2},
        {"sector": "Semiconductors", "direction": "negative", "magnitude": 3},
    ],
    "weather": [
        {"sector": "Insurance", "direction": "negative", "magnitude": 4},
        {"sector": "Construction", "direction": "positive", "magnitude": 2},
        {"sector": "Agriculture", "direction": "negative", "magnitude": 3},
        {"sector": "Energy", "direction": "positive", "magnitude": 2, "condition": "Gulf Coast region"},
    ],
    "health": [
        {"sector": "Healthcare", "direction": "positive", "magnitude": 4},
        {"sector": "Travel & Leisure", "direction": "negative", "magnitude": 5},
        {"sector": "Tech", "direction": "positive", "magnitude": 2},
        {"sector": "Airlines", "direction": "negative", "magnitude": 4},
    ],
    "economic": [
        {"sector": "Banks", "direction": "positive", "magnitude": 3, "condition": "rate hike"},
        {"sector": "REITs", "direction": "negative", "magnitude": 3, "condition": "rate hike"},
        {"sector": "Growth Tech", "direction": "negative", "magnitude": 3, "condition": "rate hike"},
    ],
    "energy": [
        {"sector": "Energy", "direction": "positive", "magnitude": 3},
        {"sector": "Transportation", "direction": "negative", "magnitude": 2},
        {"sector": "Consumer Discretionary", "direction": "negative", "magnitude": 2},
    ],
}
```

---

## Adapter Interface Implementation

### Adapter Classes

Each source has its own adapter class inheriting from `PipelineAdapter` per the [Pipeline Framework](./pipeline-framework.md#adapter-interface):

| Adapter Class | File | `source_name` | `pipeline_name` |
|--------------|------|---------------|-----------------|
| `GdeltAdapter` | `backend/app/pipelines/gdelt.py` | `'gdelt'` | `'gdelt_global_events'` |
| `FredExtendedAdapter` | `backend/app/pipelines/fred_extended.py` | `'fred'` | `'fred_extended_series'` |
| `AcledAdapter` | `backend/app/pipelines/acled.py` | `'acled'` | `'acled_conflict_events'` |
| `OwidAdapter` | `backend/app/pipelines/owid.py` | `'owid'` | `'owid_indicators'` |
| `OpenMeteoAdapter` | `backend/app/pipelines/open_meteo.py` | `'open_meteo'` | `'open_meteo_weather'` |
| `TilastokeskusAdapter` | `backend/app/pipelines/tilastokeskus.py` | `'tilastokeskus'` | `'tilastokeskus_indicators'` |
| `EurostatAdapter` | `backend/app/pipelines/eurostat.py` | `'eurostat'` | `'eurostat_indicators'` |
| `OpenSkyAdapter` | `backend/app/pipelines/opensky.py` | `'opensky'` | `'opensky_flights'` |

### GDELT Adapter Sample Logic

```python
@register_pipeline
class GdeltAdapter(PipelineAdapter):
    source_name = "gdelt"
    pipeline_name = "gdelt_global_events"

    QUERY_CATEGORIES = {
        "conflict": "conflict OR military OR war OR airstrike",
        "trade": "tariff OR sanction OR trade war OR trade dispute",
        "weather": "earthquake OR hurricane OR flood OR wildfire OR drought",
        "economic": "interest rate OR central bank OR fiscal policy",
        "health": "pandemic OR outbreak OR epidemic OR WHO emergency",
        "energy": "oil price OR OPEC OR energy crisis OR pipeline",
    }

    async def fetch(self, from_date=None, to_date=None):
        all_articles = []
        for category, query in self.QUERY_CATEGORIES.items():
            url = (
                f"https://api.gdeltproject.org/api/v2/doc/doc"
                f"?query={query}&mode=artlist&maxrecords=50&format=json&timespan=15min"
            )
            resp = await self.http_client.get(url)
            articles = resp.json().get("articles", [])
            for article in articles:
                article["_category"] = category
            all_articles.extend(articles)
            await self.rate_limiter.acquire()  # respect ~10 req/min
        return all_articles

    async def validate(self, raw_records):
        valid, errors = [], []
        for record in raw_records:
            if not record.get("title"):
                errors.append(f"Missing title for URL: {record.get('url', 'unknown')}")
                continue
            if not record.get("seendate"):
                errors.append(f"Missing date for: {record.get('title', 'unknown')[:50]}")
                continue
            valid.append(record)
        return valid, errors

    async def transform(self, valid_records):
        transformed = []
        for record in valid_records:
            tone = float(record.get("tone", 0))
            category = record["_category"]
            severity = self._classify_severity(tone, category)
            sectors = SECTOR_IMPACT_RULES.get(category, [])

            transformed.append({
                "source": "gdelt",
                "event_type": category,
                "headline": record["title"][:500],
                "description": f"Source: {record.get('domain', 'unknown')}",
                "location_country": record.get("sourcecountry"),
                "sentiment_score": Decimal(str(tone)),
                "impact_severity": severity,
                "affected_sectors": [s["sector"] for s in sectors],
                "source_url": record.get("url"),
                "event_date": parse_gdelt_date(record["seendate"]),
            })
        return transformed

    async def load(self, transformed_records):
        # INSERT ... ON CONFLICT (source, headline, event_date) DO UPDATE
        # to handle duplicate articles across fetch cycles
        ...
```

---

## Scheduling

### Pipeline YAML Configuration (additions to `backend/pipelines.yaml`)

```yaml
pipelines:
  # ... existing pipelines ...

  gdelt_global_events:
    source: gdelt
    schedule: "*/15 * * * *"        # every 15 minutes
    enabled: true
    timeout: 120
    max_retries: 3
    rate_limit:
      requests_per_minute: 10

  fred_extended_series:
    source: fred
    schedule: "0 22 * * 1-5"        # weekdays at 22:00 UTC (after US market close)
    enabled: true
    timeout: 120
    max_retries: 3
    rate_limit:
      requests_per_minute: 120

  acled_conflict_events:
    source: acled
    schedule: "0 6 * * 0"           # weekly, Sunday 06:00 UTC
    enabled: true
    timeout: 300
    max_retries: 3
    rate_limit:
      requests_per_minute: 10

  owid_indicators:
    source: owid
    schedule: "0 7 * * 0"           # weekly, Sunday 07:00 UTC
    enabled: true
    timeout: 300
    max_retries: 3
    rate_limit:
      requests_per_minute: 30

  open_meteo_weather:
    source: open_meteo
    schedule: "0 */6 * * *"         # every 6 hours
    enabled: true
    timeout: 60
    max_retries: 3
    rate_limit:
      requests_per_minute: 30

  tilastokeskus_indicators:
    source: tilastokeskus
    schedule: "0 8 15 * *"          # 15th of month at 08:00 UTC
    enabled: true
    timeout: 120
    max_retries: 3
    rate_limit:
      requests_per_minute: 10

  eurostat_indicators:
    source: eurostat
    schedule: "0 9 15 * *"          # 15th of month at 09:00 UTC
    enabled: true
    timeout: 120
    max_retries: 3
    rate_limit:
      requests_per_minute: 10

  opensky_flights:
    source: opensky
    schedule: "0 2 * * *"           # daily at 02:00 UTC
    enabled: true
    timeout: 60
    max_retries: 3
    rate_limit:
      requests_per_day: 50
```

### Refresh Schedule Summary

| Pipeline | Frequency | Notes |
|----------|-----------|-------|
| GDELT events | Every 15 minutes | Primary event source, 24/7 |
| FRED extended | Daily (weekdays, 22:00 UTC) | After US market data published |
| ACLED conflicts | Weekly (Sunday) | ACLED updates weekly |
| OWID indicators | Weekly (Sunday) | GitHub CSV files |
| Open-Meteo weather | Every 6 hours | Extreme weather detection |
| Tilastokeskus | Monthly (15th) | Finnish data published mid-month |
| Eurostat | Monthly (15th) | EU data published mid-month |
| OpenSky flights | Daily (02:00 UTC) | Experimental; previous day aggregate |

### Staleness Thresholds

| Pipeline | Scheduled Interval | Staleness Threshold |
|----------|-------------------|-------------------|
| gdelt_global_events | 15 min | 30 min |
| fred_extended_series | 24 hours | 48 hours |
| acled_conflict_events | 7 days | 14 days |
| owid_indicators | 7 days | 14 days |
| open_meteo_weather | 6 hours | 12 hours |
| tilastokeskus_indicators | 30 days | 60 days |
| eurostat_indicators | 30 days | 60 days |
| opensky_flights | 24 hours | 48 hours |

---

## Rate Limiting

| Source | Limit | Implementation |
|--------|-------|----------------|
| GDELT | ~10 req/min (recommended) | Token bucket, 1 token/6sec |
| FRED | 120 req/min (shared with existing FRED adapter) | Token bucket, 2 tokens/sec |
| ACLED | ~10 req/min (estimated) | Token bucket, 1 token/6sec |
| OWID | None (GitHub raw files) | No limiter needed |
| Open-Meteo | ~30 req/min (recommended) | Token bucket, 1 token/2sec |
| Tilastokeskus | ~10 req/min (recommended) | Token bucket, 1 token/6sec |
| Eurostat | ~10 req/min (recommended) | Token bucket, 1 token/6sec |
| OpenSky | 100 req/day (anonymous) | Daily counter, resets 00:00 UTC |

---

## Idempotency

### Conflict Keys by Table

| Table | Conflict Key | Update Columns |
|-------|-------------|----------------|
| `global_events` | `(source, headline, event_date::date)` | `sentiment_score`, `impact_severity`, `affected_sectors`, `fetched_at` |
| `sector_impact_analysis` | `(event_id, sector)` | `impact_direction`, `impact_magnitude`, `reasoning` |
| `macro_indicators` (extended) | `(indicator_code, date)` | `value`, `unit`, `source` |

### Guarantees

- Re-running any pipeline for the same period produces the same result
- Duplicate GDELT articles (same headline + source + date) are merged, not duplicated
- ACLED events keyed by `data_id` from source to prevent duplicates
- OWID/Tilastokeskus/Eurostat indicator values upserted by `(indicator_code, date)`

---

## Data Validation

### Global Events

1. `headline` is required and non-empty
2. `event_date` is required and not more than 1 day in the future (clock skew tolerance)
3. `event_type` must be a valid enum value
4. `sentiment_score` (when present) must be between -100.0 and +100.0
5. `location_lat` (when present) must be between -90.0 and +90.0
6. `location_lon` (when present) must be between -180.0 and +180.0
7. `source_url` (when present) must start with `http://` or `https://`
8. Duplicate detection: skip if identical `(source, headline, event_date::date)` already exists in current batch

### Extended FRED Series

Same rules as [FRED adapter validation](./fred.md#validation-rules) plus commodity-specific ranges listed above.

### Tilastokeskus / Eurostat

1. Value must be a finite number (not NaN or Inf)
2. Period must parse to a valid date
3. Indicator code must be in the tracked series catalog

---

## Error Scenarios and Handling

| Scenario | Detection | Response |
|----------|-----------|----------|
| GDELT API returns empty articles | `articles` array is empty | Log warning. Successful run with 0 rows. |
| GDELT API returns HTML instead of JSON | JSON decode error | `NonRetryableError`. Log error. |
| ACLED API key invalid | HTTP 403 | `NonRetryableError`. Log critical. |
| ACLED API down | HTTP 5xx | `RetryableError`. Backoff and retry. |
| OWID GitHub CSV URL changed | HTTP 404 | `NonRetryableError`. Log error, flag for review. |
| Open-Meteo returns null for region | Missing fields in response | Skip region. Log warning. Continue with other regions. |
| Tilastokeskus PxWeb API schema change | Unexpected JSON structure | `NonRetryableError`. Log error. |
| Eurostat API maintenance | HTTP 503 | `RetryableError`. Backoff and retry. |
| OpenSky rate limit exceeded | HTTP 429 | `RetryableError`. Retry next day (daily budget). |
| Network timeout (any source) | `asyncio.TimeoutError` | `RetryableError`. Backoff and retry. Max 3 retries. |

---

## Edge Cases

1. **GDELT duplicate articles**: The same news story is often reported by hundreds of sources. The adapter deduplicates by headline similarity — if a headline matches an existing record (same source + date), the record is updated rather than duplicated.

2. **GDELT language filtering**: GDELT returns articles in 65+ languages. The adapter filters to English-language articles only (`sourcelang=eng` parameter) to ensure headline quality and avoid encoding issues.

3. **ACLED retroactive updates**: ACLED may update historical events (e.g., revised fatality counts). Weekly full-refresh with upsert handles this transparently.

4. **OWID CSV schema changes**: Our World in Data occasionally restructures CSV columns. The adapter should validate expected column headers at fetch time and raise `NonRetryableError` if critical columns are missing.

5. **Open-Meteo forecast vs. observation**: The adapter uses forecast data for extreme weather detection. Forecasts may not materialize. Events generated from weather data carry a note indicating they are forecast-based until confirmed by subsequent fetches.

6. **Tilastokeskus seasonal data gaps**: Some Finnish statistical series have seasonal patterns (e.g., construction permits drop in winter). The adapter does not flag seasonal drops as anomalies.

7. **Eurostat delayed publications**: Eurostat sometimes delays data publication by several weeks. The adapter handles empty responses gracefully and retries next scheduled run.

8. **OpenSky anonymous rate limits**: The free anonymous tier is limited. If rate limits are hit frequently, consider registering for a free account (1000 req/day).

9. **Sector impact rule ambiguity**: Some events affect multiple sectors in conflicting ways. The rules engine applies all matching rules and stores each sector impact separately in `sector_impact_analysis`.

10. **Backfill on first run**: GDELT supports querying historical data (limited timespan). ACLED supports full historical queries. On initial deployment, run a backfill for the last 90 days to populate the event feed.

11. **Time zone normalization**: GDELT uses UTC. ACLED uses date-only (no time). Open-Meteo uses local timezone. All dates are normalized to UTC before storage per spec conventions.

12. **Very high event volume days**: Major global events (e.g., war outbreak) may generate thousands of GDELT articles. The adapter caps at 50 articles per category per fetch cycle (300 total max) to prevent database bloat.

---

## Open Questions

- Should we implement NLP-based headline deduplication (cosine similarity) or is exact-match sufficient for GDELT?
- Should sector impact rules be stored in the database (editable at runtime) or kept in code (simpler, version-controlled)?
- Should we add sentiment aggregation — a rolling "global sentiment score" computed from recent GDELT tone values?
- Is the OpenSky Network data valuable enough to justify the operational complexity, or should it remain permanently experimental?

---

## Changelog

| Date | Change |
|------|--------|
| 2026-03-19 | Initial draft |
