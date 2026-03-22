# justETF Adapter

European ETF data source for the Bloomvalley terminal. Provides ETF profiles including total expense ratio (TER), assets under management (AUM), replication method, distribution policy, domicile, ISIN, top holdings, performance history, and fund size. No official API is available — data is obtained by web scraping with `requests` + `BeautifulSoup`, targeting `justetf.com/en/etf-profile.html?isin={ISIN}`. This is the primary source for Boglehead-style ETF screening criteria (low TER, accumulating, physical replication, Ireland/Luxembourg domicile).

**Status: DRAFT**

## Dependencies

- [Pipeline Framework](./pipeline-framework.md) — base adapter interface, scheduling, error handling
- [Data Model](../01-system/data-model.md) — target table schemas (`securities`, new `etf_profiles` table)
- [Yahoo Finance Adapter](./yahoo-finance.md) — provides ETF prices; justETF provides profile/metadata
- [Architecture](../01-system/architecture.md) — system topology, Redis caching, environment variables
- [Spec Conventions](../00-meta/spec-conventions.md) — naming, monetary format, date format

---

## Source Description

justETF (https://www.justetf.com) is the leading European ETF comparison and screening platform. It covers ETFs listed on European exchanges (XETRA, London, Euronext, SIX, etc.) with detailed profile pages including cost data, replication methods, distribution policies, domicile information, and holdings breakdowns. This data is essential for evaluating ETFs in the Boglehead core portfolio and for the Compliance Officer to verify accumulating vs. distributing status for Finnish tax optimization.

Because there is no official API, data must be scraped from HTML pages. The site structure is stable but can change without notice — the adapter must handle structural changes gracefully.

### What This Adapter Provides

| Data Category | Refresh Frequency | Target Tables |
|---------------|-------------------|---------------|
| ETF profiles (TER, AUM, replication, distribution, domicile) | Monthly | `etf_profiles`, `securities` (metadata columns) |
| Top holdings (top 10 positions with weights) | Monthly | `etf_profiles` (JSON column) |
| Performance history (1m, 3m, 6m, 1y, 3y, 5y returns) | Monthly | `etf_profiles` (performance columns) |
| Fund size (AUM in EUR) | Monthly | `etf_profiles.aum_eur_cents` |

---

## Authentication

No authentication required. justETF profile pages are publicly accessible. However, scraping must respect the site's terms of service and robots.txt.

**Environment variables:** None specific to this adapter.

---

## Library and Installation

```
pip install requests>=2.31.0 beautifulsoup4>=4.12.3 lxml>=5.1.0
```

The adapter uses `requests` for HTTP fetching and `BeautifulSoup` with the `lxml` parser for HTML parsing. No headless browser or JavaScript rendering is required — the target data is present in the initial HTML response.

---

## Rate Limits and Scheduling

justETF has no published rate limits, but aggressive scraping triggers IP-based blocking (HTTP 403 or CAPTCHA challenges).

| Constraint | Value |
|------------|-------|
| Minimum delay between requests | 5 seconds |
| Requests per minute | 12 (1 every 5 seconds) |
| Max concurrent requests | 1 (sequential only) |
| Max requests per session | 50 (then pause 10 minutes) |
| User-Agent | Custom: `WarrenCashett/1.0 (personal finance tool)` |
| Session management | Use `requests.Session` with cookies for consistent behavior |
| Backoff on 403 / CAPTCHA / connection error | Exponential: 30s, 60s, 120s, 240s (max 3 retries) |
| Cool-down after repeated failures | 10 minutes pause, then resume |
| Respect robots.txt | Yes — check `robots.txt` before first request each run |

### Schedule

| Pipeline Job | Cron Expression | Description |
|--------------|----------------|-------------|
| `justetf_profiles` | `0 4 1 * *` | 1st of month 04:00 UTC — monthly ETF profile refresh |

Monthly refresh is sufficient because TER, replication method, and distribution policy change very rarely (typically once a year at most).

---

## Scraping Approach

### Target URL

```
https://www.justetf.com/en/etf-profile.html?isin={ISIN}
```

Each ETF is identified by its ISIN (e.g., `IE00B4L5Y983` for iShares Core MSCI World). The adapter fetches the profile page for each ISIN in the `securities` table where `asset_class = 'etf'` and `is_active = TRUE` and `isin IS NOT NULL`.

Examples:
- Vanguard FTSE All-World (ACC): `https://www.justetf.com/en/etf-profile.html?isin=IE00BK5BQT80`
- iShares Core MSCI World: `https://www.justetf.com/en/etf-profile.html?isin=IE00B4L5Y983`
- iShares Core S&P 500 (ACC): `https://www.justetf.com/en/etf-profile.html?isin=IE00B5BMR087`

### robots.txt Compliance

Before starting a scrape run, the adapter fetches `https://www.justetf.com/robots.txt` and verifies that `/en/etf-profile.html` is not disallowed. If the path is disallowed, the entire pipeline run is skipped with status `failed` and error message `"robots.txt disallows scraping of ETF profile pages"`.

### HTTP Headers

```python
HEADERS = {
    "User-Agent": "WarrenCashett/1.0 (personal finance tool)",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}
```

---

## Sample HTML Structure to Parse

The following shows the key HTML elements targeted by the parser. Class names and structure are based on the site as of March 2026 and may change.

```html
<!-- ETF name in the header -->
<h1 class="h2">
  iShares Core MSCI World UCITS ETF USD (Acc)
</h1>

<!-- Key facts / quickfacts table -->
<table class="table-quickfacts">
  <tbody>
    <tr>
      <td>Fund size</td>
      <td>EUR 73,451 m</td>
    </tr>
    <tr>
      <td>Total expense ratio (TER)</td>
      <td>0.20% p.a.</td>
    </tr>
    <tr>
      <td>Replication</td>
      <td>Physical (Optimized sampling)</td>
    </tr>
    <tr>
      <td>Legal structure</td>
      <td>ETF</td>
    </tr>
    <tr>
      <td>Fund domicile</td>
      <td>Ireland</td>
    </tr>
    <tr>
      <td>Fund currency</td>
      <td>USD</td>
    </tr>
    <tr>
      <td>Distribution policy</td>
      <td>Accumulating</td>
    </tr>
    <tr>
      <td>Fund launch date</td>
      <td>25 September 2009</td>
    </tr>
  </tbody>
</table>

<!-- Performance table -->
<div id="returns">
  <table class="table">
    <thead>
      <tr>
        <th>1 month</th><th>3 months</th><th>6 months</th>
        <th>1 year</th><th>3 years</th><th>5 years</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td>+1.23%</td><td>+4.56%</td><td>+8.90%</td>
        <td>+15.67%</td><td>+34.21%</td><td>+78.45%</td>
      </tr>
    </tbody>
  </table>
</div>

<!-- Top holdings -->
<div id="holdings">
  <table class="table">
    <tbody>
      <tr>
        <td>Apple Inc.</td>
        <td class="text-right">4.82%</td>
      </tr>
      <tr>
        <td>Microsoft Corp.</td>
        <td class="text-right">4.21%</td>
      </tr>
      <!-- ... more holdings ... -->
    </tbody>
  </table>
</div>
```

---

## Sample Code

### Data Extraction (HTML Parsing)

```python
from bs4 import BeautifulSoup
import requests
import re
import time

def scrape_etf_profile(isin: str) -> dict:
    url = f"https://www.justetf.com/en/etf-profile.html?isin={isin}"
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "lxml")

    result = {"isin": isin}

    # Fund name
    name_el = soup.select_one("h1.h2")
    result["name"] = name_el.get_text(strip=True) if name_el else None

    # Key facts table
    key_facts = {}
    for row in soup.select("table.table-quickfacts tr"):
        label = row.select_one("td:first-child")
        value = row.select_one("td:last-child")
        if label and value:
            label_text = label.get_text(strip=True).lower()
            value_text = value.get_text(strip=True)

            if "total expense ratio" in label_text:
                result["ter_pct"] = parse_percentage(value_text)
            elif "replication" in label_text:
                result["replication_method"] = value_text
            elif "distribution policy" in label_text:
                result["distribution_policy"] = value_text
            elif "fund size" in label_text:
                result["aum_eur_cents"] = parse_fund_size(value_text)
            elif "fund domicile" in label_text:
                result["domicile"] = value_text
            elif "fund currency" in label_text:
                result["fund_currency"] = value_text
            elif "fund launch date" in label_text:
                result["launch_date"] = value_text

    # Performance table
    returns_div = soup.select_one("#returns table")
    if returns_div:
        headers = [th.get_text(strip=True) for th in returns_div.select("th")]
        values = [td.get_text(strip=True) for td in returns_div.select("tbody td")]
        result["performance"] = dict(zip(headers, values))

    # Top holdings
    holdings = []
    holdings_div = soup.select_one("#holdings table")
    if holdings_div:
        for row in holdings_div.select("tbody tr"):
            cells = row.select("td")
            if len(cells) >= 2:
                name = cells[0].get_text(strip=True)
                weight = cells[-1].get_text(strip=True)
                holdings.append({"name": name, "weight_pct": weight})
    result["top_holdings"] = holdings[:10]

    return result
```

### Parsing TER

```python
def parse_percentage(text: str) -> float | None:
    """Parse '0.20% p.a.' into 0.20"""
    match = re.search(r"([+-]?[\d.]+)\s*%", text)
    return float(match.group(1)) if match else None
```

### Parsing Fund Size

```python
def parse_fund_size(text: str) -> int | None:
    """Parse 'EUR 73,451 m' into cents."""
    match = re.search(r"([\d,.]+)\s*(m|bn)", text, re.IGNORECASE)
    if not match:
        return None
    num = float(match.group(1).replace(",", ""))
    multiplier = 1_000_000 if match.group(2).lower() == "m" else 1_000_000_000
    return round(num * multiplier * 100)  # to cents
```

### Full Pipeline Fetch

```python
class JustETFAdapter(PipelineAdapter):
    source_name = "justetf"
    pipeline_name = "justetf_profiles"

    async def fetch(self, from_date=None, to_date=None) -> list[dict]:
        # Check robots.txt first
        if not await self.check_robots_txt():
            raise NonRetryableError("robots.txt disallows scraping of ETF profile pages")

        # Get all active ETFs from securities table
        etfs = await self.db.fetch_all(
            "SELECT id, isin FROM securities "
            "WHERE asset_class = 'etf' AND is_active = TRUE AND isin IS NOT NULL"
        )

        results = []
        for etf in etfs:
            try:
                profile = scrape_etf_profile(etf["isin"])
                profile["security_id"] = etf["id"]
                results.append(profile)
            except requests.HTTPError as e:
                if e.response.status_code == 404:
                    results.append({"isin": etf["isin"], "security_id": etf["id"], "not_found": True})
                elif e.response.status_code in (403, 429):
                    raise RetryableError(f"HTTP {e.response.status_code} — blocked or rate limited")
                else:
                    raise RetryableError(f"HTTP {e.response.status_code} for {etf['isin']}")
            time.sleep(5)  # respect rate limit

        return results
```

---

## Data Mapping

### New `etf_profiles` Table

This adapter introduces a new `etf_profiles` table to store ETF-specific data that does not fit into the existing `securities` table. This table must be added to the [Data Model](../01-system/data-model.md).

```sql
CREATE TABLE etf_profiles (
    id                  BIGSERIAL       PRIMARY KEY,
    security_id         BIGINT          NOT NULL REFERENCES securities(id),
    isin                CHAR(12)        NOT NULL,
    ter_bps             INTEGER,                    -- TER in basis points (20 = 0.20%)
    aum_eur_cents       BIGINT,                     -- fund size in EUR cents
    replication_method  VARCHAR(50),                -- 'physical', 'physical_sampling', 'synthetic'
    distribution_policy VARCHAR(20),                -- 'accumulating', 'distributing'
    domicile            CHAR(2),                     -- ISO 3166-1 alpha-2 (IE, LU, DE, etc.)
    fund_currency       CHAR(3),                     -- fund base currency
    launch_date         DATE,
    index_tracked       VARCHAR(255),
    top_holdings        JSONB,                       -- array of {name, weight_pct}
    return_1m_bps       INTEGER,                    -- 1-month return in basis points
    return_3m_bps       INTEGER,
    return_6m_bps       INTEGER,
    return_1y_bps       INTEGER,
    return_3y_bps       INTEGER,
    return_5y_bps       INTEGER,
    as_of_date          DATE            NOT NULL,
    source              VARCHAR(50)     NOT NULL DEFAULT 'justetf',
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT now(),

    CONSTRAINT fk_etf_profiles_securities
        FOREIGN KEY (security_id) REFERENCES securities(id)
);

CREATE UNIQUE INDEX idx_etf_profiles_security_date
    ON etf_profiles (security_id, as_of_date);
CREATE INDEX idx_etf_profiles_security_id ON etf_profiles (security_id);
CREATE INDEX idx_etf_profiles_isin ON etf_profiles (isin);
CREATE INDEX idx_etf_profiles_ter ON etf_profiles (ter_bps);
```

### Scraped Fields to `etf_profiles` Table

| Scraped Field | Database Column | Type | Transformation |
|---------------|-----------------|------|----------------|
| `ter_pct` | `etf_profiles.ter_bps` | `INTEGER` | `round(value * 100)` — e.g., `0.20` to `20` basis points |
| `aum_eur_cents` | `etf_profiles.aum_eur_cents` | `BIGINT` | Already parsed to cents by `parse_fund_size()` |
| `replication_method` | `etf_profiles.replication_method` | `VARCHAR(50)` | Normalize via lookup table (see below) |
| `distribution_policy` | `etf_profiles.distribution_policy` | `VARCHAR(20)` | Lowercase: `"Accumulating"` to `"accumulating"` |
| `domicile` | `etf_profiles.domicile` | `CHAR(2)` | Map country name to ISO 3166-1 alpha-2 |
| `fund_currency` | `etf_profiles.fund_currency` | `CHAR(3)` | Direct string, uppercase |
| `launch_date` | `etf_profiles.launch_date` | `DATE` | Parse `"25 September 2009"` to `2009-09-25` |
| `top_holdings` | `etf_profiles.top_holdings` | `JSONB` | `[{"name": "Apple Inc.", "weight_pct": 4.82}, ...]` — parse percentage strings to floats |
| `performance["1 month"]` | `etf_profiles.return_1m_bps` | `INTEGER` | Parse `"+1.23%"` to `123` basis points |
| `performance["3 months"]` | `etf_profiles.return_3m_bps` | `INTEGER` | Parse percentage to basis points |
| `performance["6 months"]` | `etf_profiles.return_6m_bps` | `INTEGER` | Parse percentage to basis points |
| `performance["1 year"]` | `etf_profiles.return_1y_bps` | `INTEGER` | Parse percentage to basis points |
| `performance["3 years"]` | `etf_profiles.return_3y_bps` | `INTEGER` | Parse percentage to basis points |
| `performance["5 years"]` | `etf_profiles.return_5y_bps` | `INTEGER` | Parse percentage to basis points |
| (today) | `etf_profiles.as_of_date` | `DATE` | Current date |
| (constant) | `etf_profiles.source` | `VARCHAR(50)` | Always `'justetf'` |

### Scraped Fields to `securities` Table (updates)

| Scraped Field | Database Column | Transformation |
|---------------|-----------------|----------------|
| `distribution_policy` | `securities.is_accumulating` | `"Accumulating"` to `TRUE`, `"Distributing"` to `FALSE`, unknown to `NULL` |
| `domicile` | `securities.country` | Map country name to ISO 3166-1 alpha-2 |

---

## Replication Method Normalization

| justETF Raw Value | Normalized Value |
|-------------------|-----------------|
| `Physical (Full replication)` | `physical` |
| `Physical (Optimised sampling)` | `physical_sampling` |
| `Physical (Optimized sampling)` | `physical_sampling` |
| `Synthetic (Swap based)` | `synthetic` |
| `Synthetic (Unfunded swap)` | `synthetic` |
| `Synthetic (Funded swap)` | `synthetic` |
| `Synthetic (Securities lending)` | `synthetic` |
| Other / unknown | `unknown` |

---

## Domicile Country Mapping

| justETF Name | ISO 3166-1 | Notes |
|-------------|------------|-------|
| `Ireland` | `IE` | Most common for UCITS ETFs |
| `Luxembourg` | `LU` | Second most common |
| `Germany` | `DE` | |
| `France` | `FR` | |
| `Switzerland` | `CH` | Non-EU |
| `Netherlands` | `NL` | |
| `United Kingdom` | `GB` | Post-Brexit, non-EU |
| `Sweden` | `SE` | |

---

## Boglehead Screening Criteria

The primary purpose of this adapter is to enable Boglehead-style ETF screening. The following criteria are extracted and queryable:

| Criterion | Field | Filter |
|-----------|-------|--------|
| Low cost | `etf_profiles.ter_bps` | `ter_bps < 30` (< 0.30%) |
| Accumulating | `etf_profiles.distribution_policy` | `= 'accumulating'` |
| Physical replication | `etf_profiles.replication_method` | `IN ('physical', 'physical_sampling')` |
| Ireland/Luxembourg domicile | `etf_profiles.domicile` | `IN ('IE', 'LU')` |
| Sufficient fund size | `etf_profiles.aum_eur_cents` | `> 10000000000` (> EUR 100M) |

### Example Screening Query

```sql
SELECT s.ticker, s.name, ep.ter_bps, ep.distribution_policy,
       ep.replication_method, ep.domicile, ep.aum_eur_cents
FROM etf_profiles ep
JOIN securities s ON s.id = ep.security_id
WHERE ep.ter_bps < 30
  AND ep.distribution_policy = 'accumulating'
  AND ep.replication_method IN ('physical', 'physical_sampling')
  AND ep.domicile IN ('IE', 'LU')
  AND ep.aum_eur_cents > 10000000000
  AND ep.as_of_date = (
      SELECT MAX(as_of_date) FROM etf_profiles WHERE security_id = ep.security_id
  )
ORDER BY ep.ter_bps ASC;
```

---

## ETFs to Track

The adapter scrapes profiles only for ETFs present in the `securities` table with `asset_class = 'etf'` and a non-null `isin`. Expected initial set:

| ISIN | Name | Role in Portfolio |
|------|------|-------------------|
| IE00BK5BQT80 | Vanguard FTSE All-World UCITS ETF (ACC) | Core global equity (Boglehead) |
| IE00B4L5Y983 | iShares Core MSCI World UCITS ETF | Core developed equity |
| IE00B5BMR087 | iShares Core S&P 500 UCITS ETF (ACC) | US equity core |
| IE00BKM4GZ66 | iShares Core EM IMI UCITS ETF (ACC) | Emerging markets |
| IE00B3RBWM25 | Vanguard FTSE All-World UCITS ETF (DIST) | Distributing alternative |
| IE00B3F81R35 | iShares Core Euro Corp Bond UCITS ETF | Euro corporate bonds |
| IE00B4WXJJ64 | iShares Core Govt Bond UCITS ETF | Euro government bonds |
| LU0290358497 | Xtrackers II Eurozone Govt Bond UCITS ETF | Eurozone govts |

---

## Validation Rules

1. **ISIN format**: Must match pattern `^[A-Z]{2}[A-Z0-9]{9}[0-9]$` (12 characters). Reject invalid ISINs before attempting to scrape.
2. **TER range**: `ter_bps` must be 0-1000 (0% to 10%). Most ETFs are 3-100 bps. Values outside this range indicate a parsing error. Reject the record.
3. **AUM positive**: `aum_eur_cents > 0` when present. Zero or negative indicates a parsing error. Reject the field.
4. **Replication method known**: Must be one of `'physical'`, `'physical_sampling'`, `'synthetic'`, `'unknown'`. Unknown raw values are logged and stored as `'unknown'`.
5. **Distribution policy known**: Must be one of `'accumulating'`, `'distributing'`. Unknown values are logged and stored as `NULL`.
6. **Domicile valid**: Must be a valid ISO 3166-1 alpha-2 code. Unknown country names are logged and stored as `NULL`.
7. **Performance returns range**: Return basis points must be between -10000 and 100000 (-100% to +1000%). Values outside this range indicate a parsing error. Reject the field (not the whole record).
8. **Top holdings weights**: Each weight must be between 0 and 100. Total of top 10 weights should not exceed 100. Log warning if exceeded.
9. **Page structure validation**: Before parsing, check that key elements exist (e.g., `h1.h2`, the quickfacts table). If the page structure has changed, log an error and skip — do not extract garbage data.
10. **HTTP status**: Only parse on HTTP 200. On 301/302, follow redirects. On 404, ISIN may be invalid or ETF delisted.
11. **HTML encoding**: Parse as UTF-8. justETF uses UTF-8 encoding for European characters in fund names.
12. **Duplicate dates**: Upsert (`ON CONFLICT ... DO UPDATE`) on `(security_id, as_of_date)` — always overwrite with latest fetch.

---

## Error Scenarios and Handling

| Scenario | Detection | Response |
|----------|-----------|----------|
| IP blocked (HTTP 403) | `requests.HTTPError` with status 403 | Stop all scraping immediately. Alert operator. Retry after 24 hours. May need to adjust User-Agent or scraping pattern. |
| Rate limited (HTTP 429) | `requests.HTTPError` with status 429 | Stop scraping for 24 hours. Reduce rate in config. |
| CAPTCHA challenge | Response HTML contains CAPTCHA form / CloudFlare challenge page | Stop scraping. Alert operator. Log error. Consider headless browser as last resort. |
| ISIN not found (HTTP 404) | `requests.HTTPError` with status 404 | Log warning. Skip ETF. May indicate delisted fund or wrong ISIN. Do not mark security as inactive (may be active on exchanges not covered by justETF). |
| Page structure changed | Expected CSS selectors return `None` for all fields | Log error with ISIN and raw HTML snippet. Mark pipeline `'failed'`. Needs manual selector update. |
| ETF delisted / liquidated | Profile page shows "liquidated", "delisted", or "closed" keywords | Set `securities.is_active = FALSE`. Log info. Continue with remaining ETFs. |
| Network timeout | `requests.Timeout` after 30s | Retry once after 10s. If still failing, skip ETF and continue with next. |
| Partial data on page | Some fields parsed, others return `None` | Store available fields, set missing fields to `NULL`. Mark pipeline `'partial'` if >10% of fields missing across all ETFs. |
| robots.txt disallows scraping | `robots.txt` check at start of run | Abort entire pipeline. Status = `'failed'`. Alert operator. |
| Cookie consent blocking content | Response missing expected data elements | Accept cookies via session. Retry request with cookie jar. |

---

## Edge Cases

1. **ETF delisted / liquidated**: The profile page may still exist but show a delisted banner. Check for keywords like "liquidated", "delisted", "closed" in the page content. Set `securities.is_active = FALSE` and do not store a new `etf_profiles` row.

2. **Page structure changes**: justETF redesigns may change CSS classes, table structures, or page layout. The adapter should fail gracefully per-field rather than crashing. If the quickfacts table is not found at all, log an error and skip the ETF. If individual fields within the table are missing, store `NULL` for those fields.

3. **ISIN not found on justETF**: Not all ETFs are covered by justETF (e.g., US-domiciled ETFs). If the ISIN returns a 404, log a warning and skip. Do not mark the security as inactive — it may be active on other exchanges.

4. **Multiple share classes**: Some ETFs have multiple share classes (e.g., accumulating and distributing) with different ISINs. Each share class has its own `securities` row and its own `etf_profiles` row. The adapter treats them independently.

5. **Currency of fund size**: justETF may report fund size in EUR or the fund's base currency. The adapter normalizes to EUR using the latest `fx_rates` if the reported currency is not EUR.

6. **Stale page data**: justETF updates data at varying intervals. The `as_of_date` in `etf_profiles` is set to the date the scrape occurred, not the date justETF last updated the data.

7. **Regional justETF variants**: justETF has localized versions (justetf.com/de, justetf.com/it, etc.). Always use the English version (`www.justetf.com/en/`) for consistent field labels. If redirected to a localized version, force the `/en/` prefix.

8. **Rate limit leading to incomplete run**: If the adapter is paused due to rate limiting and the pipeline timeout is reached, the run is marked as `'partial'` with metadata indicating how many ETFs were processed out of the total.

9. **Very large ETF universe**: If the securities table contains hundreds of ETFs, a single monthly run at 1 request per 5 seconds could take over an hour. The pipeline timeout should be set accordingly (3600s recommended for large universes).

10. **Percentage parsing edge cases**: Negative returns are prefixed with `-` (e.g., `-2.34%`). The parser must handle both `+` and `-` prefixes, as well as bare percentages without a sign prefix.

11. **TER changes**: ETF providers occasionally change TER (usually downward for competitive reasons). The monthly refresh captures this. Historical TER is preserved via the `as_of_date` keying in `etf_profiles`.

12. **Newly launched ETFs**: Funds less than 3 months old may have incomplete data on justETF (no performance history, provisional TER). Handle gracefully with NULLs.

13. **JavaScript-rendered content**: Some pages may load additional data via JavaScript (e.g., holdings tables). The `requests` + BeautifulSoup approach only captures server-rendered HTML. If critical data is JS-rendered, consider `playwright` as a fallback (last resort).

14. **Cookie consent**: justETF may show a cookie consent banner. The adapter should accept cookies via the session to ensure full page content loads.

---

## Open Questions

- Should `etf_profiles` store one row per `(security_id, as_of_date)` for historical tracking, or only keep the latest profile per security?
- Should the `etf_profiles` table definition be added to the data model spec now, or kept here until implementation?
- Should we use a headless browser (Playwright) instead of requests+BeautifulSoup for more robust scraping, at the cost of complexity and resource usage?
- Is there a justETF API or data partnership we could use instead of scraping?

---

## Changelog

| Date | Change |
|------|--------|
| 2026-03-19 | Initial draft |
