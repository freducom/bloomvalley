# Morningstar Adapter

Fund ratings and analysis adapter for the Warren Cashett terminal. Provides Morningstar star ratings (1-5), style box classification (value/blend/growth by large/mid/small cap), Morningstar category, analyst ratings (Gold/Silver/Bronze/Neutral/Negative), and expense ratio data. Very limited free access — no official free API. Strategy: try morningstar.com basic pages first, fall back to Yahoo Finance for overlapping data.

**Status: DRAFT**

## Dependencies

- [Pipeline Framework](./pipeline-framework.md) — base adapter interface, scheduling, error handling
- [Data Model](../01-system/data-model.md) — target table schemas (`securities`)
- [Yahoo Finance Adapter](./yahoo-finance.md) — provides some Morningstar-sourced data as proxy
- [justETF Adapter](./justetf.md) — provides overlapping ETF metadata
- [Architecture](../01-system/architecture.md) — system topology, Redis caching
- [Spec Conventions](../00-meta/spec-conventions.md) — naming, date format

---

## Source Description

Morningstar (https://www.morningstar.com) is the gold standard for fund analysis, ratings, and classification. Their star rating system (1-5 stars) and style box are widely used by investors to evaluate funds and ETFs. However, Morningstar does not offer a free API, and their website employs aggressive anti-scraping measures (CloudFlare, JavaScript rendering, fingerprinting).

### Strategy: Tiered Hybrid Approach

Given the difficulty of scraping Morningstar directly, this adapter uses a tiered strategy:

1. **Primary: Morningstar.com basic pages** — Attempt direct scraping of Morningstar fund pages first. Some basic JSON endpoints exist that may return structured data without full page rendering.
2. **Secondary: Yahoo Finance proxy** — Yahoo Finance displays Morningstar star ratings and category information for many funds/ETFs in its `Ticker.info` dict. Extract this data from the Yahoo Finance fundamentals cache.
3. **Tertiary: justETF overlap** — For European ETFs, justETF provides performance data and some classification that overlaps with Morningstar. Use as fallback.
4. **Skip if unavailable** — Morningstar data is nice-to-have, not critical. If all sources fail, the system operates without star ratings.

### What This Adapter Provides

| Data Category | Source Strategy | Refresh Frequency | Target |
|---------------|----------------|-------------------|--------|
| Star rating (1-5) | Morningstar scrape, Yahoo Finance proxy | Monthly | Redis cache |
| Style box (3x3 grid) | Morningstar scrape | Monthly | Redis cache |
| Morningstar category | Morningstar scrape, Yahoo Finance proxy | Monthly | Redis cache |
| Analyst rating (Gold/Silver/Bronze/Neutral/Negative) | Morningstar scrape only | Monthly | Redis cache |
| Expense ratio | Morningstar scrape | Monthly | Redis cache |
| Category rank percentile | Morningstar scrape | Monthly | Redis cache |

---

## Authentication

No authentication required for web scraping. Yahoo Finance data is fetched via the Yahoo adapter (no separate auth needed here).

**Environment variables:** None specific to this adapter.

---

## Library and Installation

```
pip install requests>=2.31.0 beautifulsoup4>=4.12.3 lxml>=5.1.0
```

The adapter uses `requests` for HTTP fetching and `BeautifulSoup` with the `lxml` parser for HTML parsing.

---

## Rate Limits and Scheduling

### Morningstar Direct Scraping

Morningstar aggressively blocks scrapers. Use very conservative rate limits.

| Constraint | Value |
|------------|-------|
| Minimum delay between requests | 10 seconds |
| Requests per minute | 6 (1 every 10 seconds) |
| Max concurrent requests | 1 (sequential only) |
| Max requests per session | 20 (then stop) |
| User-Agent | Standard browser User-Agent (Morningstar blocks non-browser agents) |
| Backoff on 403 / CAPTCHA / block | Stop for 48 hours. Alert operator. |
| Cool-down after repeated failures | 15 minutes pause, then resume |

### Schedule

| Pipeline Job | Cron Expression | Description |
|--------------|----------------|-------------|
| `morningstar_ratings` | `0 5 1 * *` | 1st of month 05:00 UTC — monthly ratings refresh |

Monthly refresh is appropriate because Morningstar star ratings update monthly based on trailing returns, and analyst ratings change only on analyst review.

---

## Data Source 1: Morningstar.com Scraping (Primary)

### URL Patterns

```
# US-listed ETFs/funds
https://www.morningstar.com/etfs/{exchange}/{ticker}/overview

# Morningstar basic JSON endpoint (may return structured data)
https://api-global.morningstar.com/sal-service/v1/etf/process/asset/v2/{morningstar_id}

# Search by ISIN (to discover Morningstar internal ID)
https://www.morningstar.com/search?query={isin}

# European funds (regional sites)
https://www.morningstar.co.uk/uk/etf/snapshot/snapshot.aspx?id={morningstar_id}
```

The challenge is identifying the Morningstar internal ID for European funds. The mapping must be maintained manually or discovered through search.

### HTTP Headers

```python
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
    "Accept-Language": "en-US,en;q=0.9",
}
```

**Note:** Morningstar blocks non-browser User-Agent strings. Use a realistic browser User-Agent.

### Sample HTML Structure to Parse

```html
<!-- Star rating — typically in a data attribute or aria-label -->
<div data-testid="overall-rating">
  <span class="mds-star-rating" aria-label="4 out of 5 stars">
    <!-- SVG stars rendered here -->
  </span>
</div>

<!-- Analyst rating -->
<div data-testid="analyst-rating">
  <span class="mds-medalist-rating">Gold</span>
</div>

<!-- Category -->
<div data-testid="category">
  <span>Global Large-Stock Blend</span>
</div>

<!-- Style box — 3x3 grid with highlighted cell -->
<div data-testid="style-box">
  <div class="mds-style-box" data-style="6">
    <!-- data-style encodes position: 1=LV, 2=LB, 3=LG, 4=MV, ... 9=SG -->
  </div>
</div>

<!-- Expense ratio -->
<div data-testid="expense-ratio">
  <span>0.20%</span>
</div>
```

### Scraping Code

```python
import requests
from bs4 import BeautifulSoup
import re

def scrape_morningstar_fund(ticker: str, exchange: str) -> dict | None:
    """
    Attempt to scrape Morningstar fund page.
    Returns None if scraping fails (expected outcome in many cases).
    """
    url = f"https://www.morningstar.com/etfs/{exchange}/{ticker.lower()}/overview"

    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
        if response.status_code != 200:
            return None

        soup = BeautifulSoup(response.text, "lxml")
        result = {}

        # Star rating
        star_el = soup.select_one("[data-testid='overall-rating'] .mds-star-rating")
        if star_el:
            aria = star_el.get("aria-label", "")
            match = re.search(r"(\d) out of 5", aria)
            if match:
                result["star_rating"] = int(match.group(1))

        # Analyst rating
        analyst_el = soup.select_one("[data-testid='analyst-rating']")
        if analyst_el:
            result["analyst_rating"] = analyst_el.get_text(strip=True)

        # Category
        category_el = soup.select_one("[data-testid='category']")
        if category_el:
            result["category"] = category_el.get_text(strip=True)

        # Style box
        style_el = soup.select_one("[data-testid='style-box'] .mds-style-box")
        if style_el:
            style_code = style_el.get("data-style")
            if style_code:
                result["style_box"] = decode_style_box(int(style_code))

        # Expense ratio
        expense_el = soup.select_one("[data-testid='expense-ratio']")
        if expense_el:
            text = expense_el.get_text(strip=True)
            match = re.search(r"([\d.]+)%", text)
            if match:
                result["expense_ratio_bps"] = round(float(match.group(1)) * 100)

        return result if result else None

    except Exception:
        return None
```

### Morningstar JSON Endpoints

Some Morningstar data may be available via basic JSON endpoints that do not require full page rendering:

```python
def try_morningstar_json(morningstar_id: str) -> dict | None:
    """
    Attempt to fetch data from Morningstar's basic JSON API.
    These endpoints are undocumented and may be blocked or removed.
    """
    url = f"https://api-global.morningstar.com/sal-service/v1/etf/process/asset/v2/{morningstar_id}"
    headers = {
        "User-Agent": HEADERS["User-Agent"],
        "Accept": "application/json",
        "ApiKey": "",  # some endpoints work without a key
    }

    try:
        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code != 200:
            return None
        data = response.json()
        return {
            "star_rating": data.get("starRating"),
            "category": data.get("categoryName"),
            "analyst_rating": data.get("analystRatingValue"),
        }
    except Exception:
        return None
```

---

## Data Source 2: Yahoo Finance Proxy (Secondary)

Yahoo Finance exposes some Morningstar data in the `Ticker.info` dict. This is the preferred fallback because it piggybacks on existing Yahoo API calls.

### Relevant Yahoo Finance Fields

```python
import yfinance as yf

ticker = yf.Ticker("VWCE.DE")  # Vanguard FTSE All-World
info = ticker.info

# Morningstar-related fields in Yahoo info:
# {
#   "morningStarOverallRating": 4,        # 1-5 star rating
#   "morningStarRiskRating": 3,           # 1-5 risk rating
#   "category": "Global Large-Stock Blend", # Morningstar category
#   ...
# }
```

### Yahoo Fields to Extract

| Yahoo Field | Data Point | Availability |
|-------------|-----------|--------------|
| `morningStarOverallRating` | Star rating (1-5) | Common for US-listed funds |
| `morningStarRiskRating` | Risk rating (1-5) | Common for US-listed funds |
| `category` | Morningstar category string | Common for funds/ETFs |

**Availability limitation:** These fields are present for ETFs and mutual funds listed on US exchanges. European-listed ETFs (e.g., `.DE`, `.HE` suffixes) may not have Morningstar data in Yahoo.

---

## Style Box Encoding

Morningstar's style box is a 3x3 grid:

```
           Value    Blend    Growth
Large    [ LV ]   [ LB ]   [ LG ]
Mid      [ MV ]   [ MB ]   [ MG ]
Small    [ SV ]   [ SB ]   [ SG ]
```

### Style Box Code Mapping

| data-style Code | Size | Style | Two-Char Encoding |
|----------------|------|-------|-------------------|
| 1 | Large | Value | `LV` |
| 2 | Large | Blend | `LB` |
| 3 | Large | Growth | `LG` |
| 4 | Mid | Value | `MV` |
| 5 | Mid | Blend | `MB` |
| 6 | Mid | Growth | `MG` |
| 7 | Small | Value | `SV` |
| 8 | Small | Blend | `SB` |
| 9 | Small | Growth | `SG` |

```python
STYLE_BOX_MAP = {
    1: "LV", 2: "LB", 3: "LG",
    4: "MV", 5: "MB", 6: "MG",
    7: "SV", 8: "SB", 9: "SG",
}

def decode_style_box(code: int) -> str | None:
    return STYLE_BOX_MAP.get(code)
```

Example: `"LB"` = Large Blend (typical for broad market index ETFs like VWCE).

---

## Data Mapping

### All Sources to Redis Cache

Morningstar data is stored exclusively in Redis, not in database tables, because it is supplementary display data that can be refetched.

| Data Point | Redis Key | Value | TTL |
|-----------|-----------|-------|-----|
| Star rating | `morningstar:{security_id}:star_rating` | integer 1-5 | 35 days |
| Risk rating | `morningstar:{security_id}:risk_rating` | integer 1-5 | 35 days |
| Category | `morningstar:{security_id}:category` | string (e.g., `"Global Large-Stock Blend"`) | 35 days |
| Analyst rating | `morningstar:{security_id}:analyst_rating` | string: `"gold"`, `"silver"`, `"bronze"`, `"neutral"`, `"negative"` | 35 days |
| Style box | `morningstar:{security_id}:style_box` | two-char string: `"LB"`, `"MV"`, etc. | 35 days |
| Expense ratio | `morningstar:{security_id}:expense_ratio_bps` | integer (basis points) | 35 days |
| Category rank | `morningstar:{security_id}:category_rank_pct` | integer 1-100 (percentile) | 35 days |
| Data source | `morningstar:{security_id}:source` | `"morningstar_scrape"`, `"morningstar_json"`, `"yahoo"`, or `"justetf"` | 35 days |
| Last updated | `morningstar:{security_id}:updated_at` | ISO 8601 timestamp | 35 days |

**TTL of 35 days** ensures data persists between monthly refreshes with a 5-day buffer.

---

## Analyst Rating Normalization

| Morningstar Text | Normalized Value |
|-----------------|-----------------|
| `"Gold"` / `"Medalist Rating: Gold"` | `gold` |
| `"Silver"` / `"Medalist Rating: Silver"` | `silver` |
| `"Bronze"` / `"Medalist Rating: Bronze"` | `bronze` |
| `"Neutral"` / `"Medalist Rating: Neutral"` | `neutral` |
| `"Negative"` / `"Medalist Rating: Negative"` | `negative` |
| Not available / not rated | `null` |

---

## Sample Adapter Logic

### Full Pipeline with Tiered Fallback

```python
from typing import Any

class MorningstarAdapter(PipelineAdapter):
    source_name = "morningstar"
    pipeline_name = "morningstar_ratings"

    async def fetch(self, from_date=None, to_date=None) -> list[dict]:
        # Get all active ETFs and funds
        securities = await self.db.fetch_all(
            "SELECT id, ticker, isin, exchange, asset_class FROM securities "
            "WHERE asset_class IN ('etf', 'stock') AND is_active = TRUE"
        )

        results = []
        scrape_count = 0

        for sec in securities:
            result = {"security_id": sec["id"], "ticker": sec["ticker"]}

            # Tier 1: Try Morningstar direct scrape
            if scrape_count < 20:  # session limit
                scraped = scrape_morningstar_fund(sec["ticker"], sec["exchange"])
                if scraped:
                    result.update(scraped)
                    result["source"] = "morningstar_scrape"
                scrape_count += 1
                await asyncio.sleep(10)  # 10-second delay between requests

            # Tier 2: Try Yahoo Finance proxy for missing fields
            if "star_rating" not in result:
                yahoo_data = await self.get_yahoo_cache(sec["id"])
                if yahoo_data:
                    if star := yahoo_data.get("morningStarOverallRating"):
                        result["star_rating"] = int(star)
                        result.setdefault("source", "yahoo")
                    if risk := yahoo_data.get("morningStarRiskRating"):
                        result["risk_rating"] = int(risk)
                    if cat := yahoo_data.get("category"):
                        result.setdefault("category", cat)

            if result.keys() > {"security_id", "ticker"}:  # has data beyond identifiers
                results.append(result)

        return results

    async def get_yahoo_cache(self, security_id: int) -> dict | None:
        """Read Yahoo Finance fundamentals from Redis cache."""
        import json
        cached = await self.redis.get(f"fundamentals:{security_id}:raw")
        return json.loads(cached) if cached else None
```

---

## Securities Coverage

Morningstar coverage varies significantly by security type and region:

| Security Type | Star Rating | Style Box | Analyst Rating | Coverage |
|--------------|-------------|-----------|----------------|----------|
| US-listed ETFs | High | High | Medium | Excellent |
| European UCITS ETFs | Medium | Medium | Low | Moderate |
| Individual stocks | N/A | Yes (size/style) | N/A | Limited usefulness |
| Crypto | N/A | N/A | N/A | None |
| Bonds / bond ETFs | Medium | N/A (bond-specific) | Low | Moderate |

The adapter focuses on ETFs and funds, where Morningstar data is most valuable. Individual stocks are fetched opportunistically but are low priority.

---

## Validation Rules

1. **Star rating range**: Must be integer 1-5. Reject any other value.
2. **Risk rating range**: Must be integer 1-5. Reject any other value.
3. **Analyst rating values**: Must be one of the 5 normalized values (`gold`, `silver`, `bronze`, `neutral`, `negative`). Reject anything else.
4. **Style box format**: Must be exactly 2 characters matching `^[LMS][VBG]$`. Reject invalid combinations.
5. **Category rank**: Must be integer 1-100. Reject values outside this range.
6. **Category string**: Must be non-empty and less than 100 characters. Trim whitespace.
7. **Expense ratio range**: Must be 0-1000 basis points (0%-10%). Values outside this range indicate a parsing error.
8. **Source tracking**: Always record which source provided each data point (`morningstar_scrape`, `morningstar_json`, `yahoo`, `justetf`) for debugging and data provenance.
9. **Freshness**: If data from all sources is older than 90 days, display a staleness warning in the UI.

---

## Error Scenarios and Handling

| Scenario | Detection | Response |
|----------|-----------|----------|
| Morningstar blocks scraping (403) | HTTP 403, CloudFlare challenge page | Stop all scraping immediately. Fall through to Yahoo proxy. Mark `'partial'`. |
| Morningstar CAPTCHA | Response HTML contains challenge JavaScript | Stop scraping. Use Yahoo/justETF data only. Alert operator. |
| Morningstar rate limit (429) | HTTP 429 | Stop all scraping for current run. Use available data from other sources. |
| Morningstar page structure changed | All CSS selectors return `None` | Log warning. Mark `'failed'` for scrape source. Continue with Yahoo proxy. |
| Yahoo proxy returns no Morningstar fields | `info.get("morningStarOverallRating")` is `None` | Normal for European ETFs. Continue with next source. |
| Security not found on Morningstar (404) | HTTP 404 on fund page | Log at DEBUG level. Skip. Not all securities have Morningstar coverage. |
| Network timeout | `requests.Timeout` after 30s | Skip security. Continue with next. No retry for individual securities. |
| JSON endpoint returns unexpected schema | `KeyError` or missing expected fields | Log warning. Skip endpoint. Fall through to HTML scrape. |
| All sources fail for a security | No data points collected | Normal for many securities. Store nothing. Not an error. |

### Graceful Degradation Matrix

| Morningstar Scrape | Yahoo Proxy | justETF | Outcome |
|--------------------|-------------|---------|---------|
| Available | Available | Available | Use best data from each source (Morningstar scrape preferred) |
| Available | Failed | Any | Use scraped data |
| Failed | Available | Any | Use Yahoo data; no analyst rating or style box |
| Failed | Failed | Available | Use justETF for overlapping fields (performance only) |
| Failed | Failed | Failed | No Morningstar data — system continues without it |

---

## Edge Cases

1. **Data only available for funds/ETFs, not individual stocks**: Morningstar star ratings and analyst ratings apply only to funds and ETFs. Individual stocks get style box (size/style) classification but no star rating. The adapter must not log errors for missing star ratings on stocks.

2. **Region-specific pages**: Morningstar has regional sites — `morningstar.com` (US), `morningstar.co.uk` (UK), `morningstar.de` (Germany) — with different coverage. European ETFs may only appear on European Morningstar sites. The adapter tries the US site first, then UK site for European-listed securities.

3. **Rating lag**: Morningstar star ratings are based on trailing returns (3, 5, 10 years). New funds have no rating until they have a 3-year track record. Return `NULL` for unrated funds.

4. **Multiple share classes**: A fund with both ACC and DIST share classes may have different ISINs but the same star rating. The adapter fetches per-security regardless.

5. **Analyst rating system changes**: Morningstar upgraded from Bronze/Silver/Gold to a "Medalist" system. Both naming conventions are normalized to the same values via the normalization table.

6. **Style box for bond funds**: Bond funds use a different style box (duration vs credit quality) instead of the equity size/style grid. The adapter stores the raw style box and lets the frontend handle display differences.

7. **Morningstar anti-bot measures**: Morningstar uses CloudFlare, JavaScript rendering, and fingerprinting. The simple `requests` approach may fail consistently. If direct scraping fails for 3 consecutive monthly runs, the adapter should be auto-disabled for direct scraping (rely on Yahoo proxy only).

8. **Copyright considerations**: Morningstar star ratings are proprietary. This is a personal-use tool, not a commercial product. Displaying scraped data in a personal dashboard is low-risk, but the adapter should not redistribute the data.

9. **Yahoo Finance deprecating Morningstar fields**: Yahoo may remove Morningstar-related fields from their API at any time. If `morningStarOverallRating` disappears from Yahoo responses, the adapter degrades to scrape-only mode.

10. **Session limit exhausted mid-run**: With 20 requests per session and 10-second delays, a session covers at most 20 securities in ~3.5 minutes. If the universe exceeds 20 ETFs/funds, prioritize securities with existing portfolio holdings first, then watchlist items, then others.

---

## Open Questions

- Should we invest effort in Morningstar scraping at all, given the fragility and anti-bot measures? Yahoo proxy + justETF may be sufficient for a personal finance tool.
- Should we use Morningstar's official API (starts at $100+/month) if the free approach proves too unreliable?
- Should we compute our own star-rating equivalent based on trailing returns from our `prices` table, rather than depending on Morningstar?
- Should we store Morningstar data in a database table instead of Redis, to preserve historical snapshots of ratings over time?

---

## Changelog

| Date | Change |
|------|--------|
| 2026-03-19 | Initial draft |
