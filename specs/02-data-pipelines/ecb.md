# ECB Adapter

European Central Bank data adapter for the Bloomvalley terminal. Provides ECB key interest rates, eurozone inflation (HICP), EUR exchange rates, and money supply data via the ECB's SDMX RESTful API. Critical for a EUR-denominated portfolio — ECB rates directly impact eurozone fixed income, and ECB-published FX rates are the authoritative source for EUR conversion.

**Status: DRAFT**

## Dependencies

- [Pipeline Framework](./pipeline-framework.md) — base adapter interface, scheduling, error handling
- [Data Model](../01-system/data-model.md) — target table schemas (`macro_indicators`, `fx_rates`)
- [Alpha Vantage Adapter](./alpha-vantage.md) — supplementary FX source; ECB is the primary FX source
- [Architecture](../01-system/architecture.md) — system topology, Redis caching
- [Spec Conventions](../00-meta/spec-conventions.md) — naming, date format

---

## Source Description

The ECB Statistical Data Warehouse (SDW) provides macroeconomic data for the eurozone via a RESTful SDMX 2.1 API. The API is free, requires no authentication, and has no published rate limits. ECB-published EUR exchange rates are considered reference rates and are widely used for financial reporting in Europe.

### What This Adapter Provides

| Data Category | Refresh Frequency | Target Table |
|---------------|-------------------|--------------|
| EUR exchange rates (vs USD, GBP, SEK, NOK, DKK, CHF, JPY) | Daily | `fx_rates` |
| ECB key interest rates (MRO, deposit facility, marginal lending) | Daily (changes infrequently) | `macro_indicators` |
| Eurozone HICP inflation | Monthly | `macro_indicators` |
| Eurozone money supply (M3) | Monthly | `macro_indicators` |

---

## Authentication

No authentication required. The ECB SDMX API is fully public.

**Environment variables:** None specific to this adapter.

---

## Rate Limits and Scheduling

| Constraint | Value |
|------------|-------|
| Published rate limit | None (no official limit) |
| Recommended courtesy limit | Max 30 requests/minute |
| Minimum delay between calls | 2 seconds |
| Backoff on error | Exponential: 2s, 4s, 8s (max 3 retries) |

### Schedule

| Pipeline Job | Cron Expression | Description |
|--------------|----------------|-------------|
| `ecb_fx_rates` | `0 17 * * 1-5` (EET) | Daily at 17:00 — ECB publishes reference rates around 16:00 CET (17:00 EET) |
| `ecb_interest_rates` | `0 18 * * 1-5` (EET) | Daily at 18:00 — check for rate changes |
| `ecb_inflation` | `0 3 18 * *` | 18th of month 03:00 — Eurostat publishes flash HICP estimate mid-month |
| `ecb_money_supply` | `0 3 28 * *` | 28th of month 03:00 — M3 data published end of month |

---

## API Endpoints

Base URL: `https://data-api.ecb.europa.eu/service`

The ECB uses SDMX RESTful API conventions. Data is organized into dataflows (datasets), each identified by a flow reference.

### Exchange Rates (EXR)

```
GET https://data-api.ecb.europa.eu/service/data/EXR/D.USD+GBP+SEK+NOK+DKK+CHF+JPY.EUR.SP00.A
  ?startPeriod=2026-03-01
  &format=jsondata
```

URL structure: `EXR/{frequency}.{currency}.{base_currency}.{rate_type}.{series_variation}`

| Parameter | Value | Meaning |
|-----------|-------|---------|
| Frequency | `D` | Daily |
| Currency | `USD+GBP+SEK+NOK+DKK+CHF+JPY` | Target currencies (multi-value with `+`) |
| Base currency | `EUR` | Always EUR |
| Rate type | `SP00` | Spot rate |
| Series variation | `A` | Average |

### Key Interest Rates (MIR / FM)

```
# ECB Main Refinancing Operations (MRO) rate
GET https://data-api.ecb.europa.eu/service/data/FM/D.U2.EUR.4F.KR.MRR_FR.LEV
  ?startPeriod=2026-01-01
  &format=jsondata

# ECB Deposit Facility rate
GET https://data-api.ecb.europa.eu/service/data/FM/D.U2.EUR.4F.KR.DFR.LEV
  ?startPeriod=2026-01-01
  &format=jsondata

# ECB Marginal Lending Facility rate
GET https://data-api.ecb.europa.eu/service/data/FM/D.U2.EUR.4F.KR.MLFR.LEV
  ?startPeriod=2026-01-01
  &format=jsondata
```

### Eurozone HICP Inflation (ICP)

```
# HICP - Overall index (eurozone, monthly, index and annual rate of change)
GET https://data-api.ecb.europa.eu/service/data/ICP/M.U2.N.000000.4.ANR
  ?startPeriod=2025-01-01
  &format=jsondata
```

URL structure: `ICP/{frequency}.{ref_area}.{adjustment}.{item}.{indicator}.{unit}`

| Parameter | Value | Meaning |
|-----------|-------|---------|
| Frequency | `M` | Monthly |
| Reference area | `U2` | Euro area (changing composition) |
| Adjustment | `N` | Neither seasonally nor working day adjusted |
| Item | `000000` | All items (headline HICP) |
| Indicator | `4` | Harmonised index (index level) |
| Unit | `ANR` | Annual rate of change (%) |

### Money Supply (BSI)

```
# M3 aggregate, eurozone
GET https://data-api.ecb.europa.eu/service/data/BSI/M.U2.N.V.M30.X.1.U2.2300.Z01.E
  ?startPeriod=2025-01-01
  &format=jsondata
```

---

## Sample API Response

### EXR (Exchange Rates) — JSON format

```json
{
  "header": {
    "id": "ecb-sdmx-response",
    "prepared": "2026-03-19T15:00:00+01:00"
  },
  "dataSets": [
    {
      "action": "Information",
      "series": {
        "0:0:0:0:0": {
          "observations": {
            "0": [1.08950],
            "1": [1.08520],
            "2": [1.09100]
          }
        },
        "0:1:0:0:0": {
          "observations": {
            "0": [0.83640],
            "1": [0.83500],
            "2": [0.83750]
          }
        }
      }
    }
  ],
  "structure": {
    "dimensions": {
      "series": [
        {
          "id": "FREQ",
          "values": [{"id": "D", "name": "Daily"}]
        },
        {
          "id": "CURRENCY",
          "values": [
            {"id": "USD", "name": "US dollar"},
            {"id": "GBP", "name": "UK pound sterling"}
          ]
        },
        {
          "id": "CURRENCY_DENOM",
          "values": [{"id": "EUR", "name": "Euro"}]
        },
        {
          "id": "EXR_TYPE",
          "values": [{"id": "SP00", "name": "Spot"}]
        },
        {
          "id": "EXR_SUFFIX",
          "values": [{"id": "A", "name": "Average"}]
        }
      ],
      "observation": [
        {
          "id": "TIME_PERIOD",
          "values": [
            {"id": "2026-03-18", "name": "2026-03-18"},
            {"id": "2026-03-17", "name": "2026-03-17"},
            {"id": "2026-03-16", "name": "2026-03-16"}
          ]
        }
      ]
    }
  }
}
```

---

## Data Mapping

### Exchange Rates: EXR to `fx_rates` table

| Source Field | Database Column | Type | Transformation |
|-------------|-----------------|------|----------------|
| (constant) | `fx_rates.base_currency` | `CHAR(3)` | `'EUR'` (always) |
| `CURRENCY` dimension value | `fx_rates.quote_currency` | `CHAR(3)` | Direct: `'USD'`, `'GBP'`, etc. |
| `TIME_PERIOD` observation dimension | `fx_rates.date` | `DATE` | Parse `YYYY-MM-DD` |
| Observation value | `fx_rates.rate` | `NUMERIC(12,6)` | Direct numeric — ECB rate means "1 EUR = X quote_currency" |
| (constant) | `fx_rates.source` | `ENUM` | `'ecb'` |

### FX Pairs to Fetch

| Pair | Quote Currency | Purpose |
|------|---------------|---------|
| EUR/USD | `USD` | US stocks, ETFs, most international securities |
| EUR/GBP | `GBP` | UK-listed securities |
| EUR/SEK | `SEK` | Swedish securities (Nordic) |
| EUR/NOK | `NOK` | Norwegian securities (Nordic) |
| EUR/DKK | `DKK` | Danish securities (Nordic) |
| EUR/CHF | `CHF` | Swiss securities |
| EUR/JPY | `JPY` | Japanese securities |

**Priority over Alpha Vantage:** ECB rates are the primary FX source. Alpha Vantage serves as backup if ECB data is unavailable or delayed.

### Interest Rates: FM to `macro_indicators` table

| ECB Series | `indicator_code` | `unit` | Description |
|-----------|-------------------|--------|-------------|
| FM MRR_FR | `ECBMRO` | `'percent'` | Main Refinancing Operations rate |
| FM DFR | `ECBDFR` | `'percent'` | Deposit Facility rate |
| FM MLFR | `ECBMLFR` | `'percent'` | Marginal Lending Facility rate |

| Source Field | Database Column | Transformation |
|-------------|-----------------|----------------|
| `TIME_PERIOD` | `macro_indicators.date` | Parse date |
| Observation value | `macro_indicators.value` | `Decimal(value)` |
| (mapped) | `macro_indicators.indicator_code` | Map from series key (see table above) |
| (constant) | `macro_indicators.unit` | `'percent'` |
| (constant) | `macro_indicators.source` | `'ecb'` |

### HICP Inflation: ICP to `macro_indicators` table

| ECB Series | `indicator_code` | `unit` | Description |
|-----------|-------------------|--------|-------------|
| ICP ANR (all items) | `EZ_HICP_YOY` | `'percent'` | Eurozone headline HICP year-over-year |

### Money Supply: BSI to `macro_indicators` table

| ECB Series | `indicator_code` | `unit` | Description |
|-----------|-------------------|--------|-------------|
| BSI M30 | `EZ_M3_YOY` | `'percent'` | Eurozone M3 annual growth rate |

---

## SDMX Response Parsing

The ECB SDMX JSON format is structured but non-trivial to parse. The observations are keyed by positional indices that map to dimension values.

```python
import httpx
from decimal import Decimal

async def parse_ecb_fx_response(response_json: dict) -> list[dict]:
    """Parse ECB SDMX JSON into flat rows for fx_rates."""
    rows = []
    structure = response_json["structure"]

    # Extract currency dimension values
    currency_dim = next(
        d for d in structure["dimensions"]["series"] if d["id"] == "CURRENCY"
    )
    currencies = [v["id"] for v in currency_dim["values"]]

    # Extract time period values
    time_dim = next(
        d for d in structure["dimensions"]["observation"] if d["id"] == "TIME_PERIOD"
    )
    dates = [v["id"] for v in time_dim["values"]]

    # Parse series data
    dataset = response_json["dataSets"][0]
    for series_key, series_data in dataset["series"].items():
        # series_key format: "0:currency_idx:0:0:0"
        parts = series_key.split(":")
        currency_idx = int(parts[1])
        currency = currencies[currency_idx]

        for obs_key, obs_values in series_data["observations"].items():
            date_idx = int(obs_key)
            rate = obs_values[0]

            if rate is None:
                continue

            rows.append({
                "base_currency": "EUR",
                "quote_currency": currency,
                "date": dates[date_idx],
                "rate": Decimal(str(rate)),
                "source": "ecb",
            })

    return rows
```

---

## Validation Rules

1. **FX rate range**: Each pair has a plausible range. Reject values outside these bounds:
   - EUR/USD: 0.70 - 1.60
   - EUR/GBP: 0.60 - 1.20
   - EUR/SEK: 8.00 - 14.00
   - EUR/NOK: 8.00 - 14.00
   - EUR/DKK: 7.40 - 7.50 (DKK is pegged to EUR)
   - EUR/CHF: 0.80 - 1.30
   - EUR/JPY: 100.00 - 200.00
2. **Rate positive**: All FX rates must be > 0.
3. **Interest rate range**: ECB rates should be between -1.0 and 15.0 percent. Negative rates were in effect 2014-2022.
4. **HICP range**: Year-over-year inflation should be between -5.0 and 25.0 percent.
5. **No weekend dates**: ECB does not publish rates on weekends. If weekend dates appear, skip them.
6. **Duplicate handling**: Upsert on `(base_currency, quote_currency, date)` for FX and `(indicator_code, date)` for macro indicators.
7. **Null observations**: Some observations in SDMX responses may be `null` (e.g., TARGET holidays). Skip these.

---

## Error Scenarios and Handling

| Scenario | Detection | Response |
|----------|-----------|----------|
| ECB API unavailable | HTTP 5xx or connection error | Retry with backoff (2s, 4s, 8s). After 3 failures, mark `'failed'`. FX rates fall back to Alpha Vantage. |
| Invalid SDMX response | Missing `dataSets` or `structure` keys | Log full response. Mark `'failed'`. |
| No new observations | Response has 0 observations for today | Normal on holidays. Log at INFO level. Use previous day's rate. |
| Response format change | Unexpected dimension structure | Log error. Mark `'failed'`. Needs manual investigation. |
| HTTP 404 on series | Dataflow or series key changed | Log error. Check ECB documentation for updated keys. |
| Partial data (some currencies missing) | Fewer series than expected in response | Process available data. Log warning for missing currencies. Mark `'partial'`. |

---

## Edge Cases

1. **TARGET2 holidays**: The ECB does not publish FX rates on TARGET2 holidays (about 6 days/year beyond weekends, e.g., Good Friday, Christmas). The portfolio valuation uses the most recent available rate. The adapter skips these dates naturally.
2. **DKK peg**: The Danish krone is pegged to EUR at ~7.46 (narrow band). Rates outside 7.40-7.50 indicate a crisis or data error.
3. **Rate publication timing**: ECB reference rates are published at approximately 16:00 CET (17:00 EET). The adapter runs at 17:00 EET to catch the publication. If rates are delayed, the adapter retries at 17:30 and 18:00.
4. **Historical backfill**: For the initial deployment, fetch rates from 2020-01-01 onward. Use `startPeriod=2020-01-01` with no `endPeriod` to get all data.
5. **ECB rate changes**: Key interest rate changes happen only at ECB Governing Council meetings (every 6 weeks). Between meetings, the rate series simply repeats the same value. The adapter stores each day's rate anyway for completeness.
6. **EUR as both base and target**: The system never needs an EUR/EUR rate (always 1.0). The adapter does not fetch this.
7. **SDMX format versions**: The ECB may update its SDMX API version. Currently using SDMX 2.1 JSON format. Monitor ECB API announcements for breaking changes.
8. **Monthly series date convention**: Monthly HICP and M3 observations are dated to the first of the month (e.g., `2026-02-01` for February data). The adapter stores this date as-is.

---

## Open Questions

- Should we add more eurozone macro indicators (e.g., eurozone GDP, eurozone unemployment) from the ECB, or source these from OECD/Eurostat?
- Should we store ECB FX rates for all 30+ currencies the ECB publishes, or only the 7 we need for portfolio securities?

---

## Changelog

| Date | Change |
|------|--------|
| 2026-03-19 | Initial draft |
