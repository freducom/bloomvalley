# F03 — Watchlist & Screener

**Status: DRAFT**

Dynamic watchlist management combined with a multi-factor security screener. The watchlist answers "What am I tracking?" and the screener answers "What should I be tracking?" Together they support the Quantitative Analyst's workflow of identifying candidates across Swedish, Finnish, European, and US markets — including dividend aristocrats and high-quality growth companies. The feature also provides side-by-side security comparison for up to 4 securities.

## Dependencies

- Specs: [data-model](../01-system/data-model.md), [api-overview](../01-system/api-overview.md), [architecture](../01-system/architecture.md), [spec-conventions](../00-meta/spec-conventions.md), [screening-factors](../03-calculations/screening-factors.md), [design-system](../05-ui/design-system.md)
- Data: Yahoo Finance fundamentals pipeline (weekly), Yahoo Finance daily prices pipeline, ECB FX rates pipeline
- API: `GET /watchlists`, `POST /watchlists`, `POST /watchlists/{id}/items`, `DELETE /watchlists/{id}/items/{securityId}`, `POST /screener/run`, `GET /screener/presets`, `GET /securities`, `GET /prices/current`

## Data Requirements

### Tables Read

| Table | Purpose |
|-------|---------|
| `watchlists` | Watchlist names, descriptions, ordering |
| `watchlist_items` | Securities in each watchlist with per-item notes |
| `securities` | Full security catalog for screener universe and display |
| `prices` | Latest prices, historical prices for screener metrics |
| `fx_rates` | EUR conversion for multi-currency comparisons |
| `research_notes` | Moat rating and thesis status for watchlist enrichment |

### Tables Written

| Table | Operation | Trigger |
|-------|-----------|---------|
| `watchlists` | INSERT, UPDATE, DELETE | Create/rename/delete watchlist |
| `watchlist_items` | INSERT, DELETE | Add/remove securities from watchlists |

### Calculations Invoked

- [screening-factors](../03-calculations/screening-factors.md): P/E, P/B, dividend yield, market cap, ROE, ROIC, debt/equity, free cash flow yield, earnings growth, revenue growth, Sharpe ratio, beta, momentum scores

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/watchlists` | List all watchlists with item counts |
| POST | `/watchlists` | Create a new watchlist. Body: `{ "name": "...", "description": "..." }` |
| PUT | `/watchlists/{id}` | Rename or update a watchlist |
| DELETE | `/watchlists/{id}` | Delete a watchlist (cascades to items) |
| GET | `/watchlists/{id}` | Get a watchlist with all items and their current metrics |
| POST | `/watchlists/{id}/items` | Add a security to a watchlist. Body: `{ "securityId": 42, "notes": "..." }` |
| DELETE | `/watchlists/{id}/items/{securityId}` | Remove a security from a watchlist |
| POST | `/screener/run` | Run a screen with factor filters. Body contains filter definitions with AND/OR logic. Returns matching securities as a paginated, sortable list |
| GET | `/screener/presets` | List saved screener presets (built-in + custom) |
| POST | `/screener/presets` | Save a custom screener preset |
| DELETE | `/screener/presets/{id}` | Delete a custom preset |
| GET | `/securities` | Search/browse the securities catalog. Supports `?q` text search, `?assetClass`, `?exchange`, `?country` |

See [api-overview](../01-system/api-overview.md) for full request/response schemas.

## UI Views

### Page Layout (`/watchlist`)

Two-tab layout: **Watchlist** | **Screener**, with a persistent comparison tray at the bottom when comparison mode is active.

### Tab: Watchlist

**Left sidebar (250px):**
- List of watchlists (names with item counts)
- Selected watchlist highlighted with `info` color
- "New Watchlist" button at bottom
- Right-click on watchlist name: Rename, Delete, Set as Default
- Drag to reorder watchlists

**Main area — Watchlist table (DataTable):**

Displays all securities in the selected watchlist.

| Column | Type | Sortable | Description |
|--------|------|----------|-------------|
| Security | ticker + name | Yes | Ticker in monospace, full name below |
| Price | currency | Yes | Latest price in native currency |
| Day Change | currency + % | Yes | Gain/loss colored |
| P/E | number | Yes | Trailing 12-month |
| P/B | number | Yes | Price-to-book ratio |
| Div Yield | percentage | Yes | Trailing 12-month dividend yield |
| Market Cap | abbreviated currency | Yes | e.g., `€4.56B` |
| Moat | badge | Yes | none / narrow / wide (from research notes, if available) |
| Notes | text (truncated) | No | Per-item notes from `watchlist_items` |

**Interactions:**
- Click row to navigate to security detail / research workspace (F06)
- Checkbox column for multi-select; bulk actions: Remove from watchlist, Add to comparison
- "Add Security" button opens a search modal (text search against `securities` table)
- Inline edit on the Notes column (click to edit, blur to save)
- Right-click context menu: Remove, Compare, View Chart, Add to Another Watchlist

### Tab: Screener

**Top section — Filter builder:**

A visual filter builder with rows of conditions connected by AND/OR logic.

Each filter row contains:
1. **Factor dropdown**: P/E, P/B, Dividend Yield, Market Cap, ROE, ROIC, Debt/Equity, FCF Yield, Earnings Growth (5Y), Revenue Growth (5Y), Beta, Momentum (6M), Payout Ratio, Consecutive Dividend Years
2. **Operator**: `>`, `<`, `>=`, `<=`, `=`, `between`
3. **Value input(s)**: Numeric input (one for comparison operators, two for `between`)
4. **AND/OR toggle** between rows

**Preset buttons row** (below filter builder):

| Preset | Description | Filters |
|--------|-------------|---------|
| Munger Quality | Wonderful companies at fair prices | ROE > 15%, ROIC > 12%, Debt/Equity < 1.0, Earnings Growth > 5%, P/E < 25 |
| Boglehead ETF | Low-cost broad index funds | Asset Class = ETF, TER < 0.30% |
| Dividend Aristocrats | 25+ years consecutive dividend increases | Consecutive Dividend Years >= 25, Payout Ratio < 80% |
| High Growth | High-growth companies | Revenue Growth > 15%, Earnings Growth > 15%, P/E < 50 |
| Deep Value | Statistically cheap stocks | P/B < 1.5, P/E < 12, Div Yield > 3% |

Clicking a preset loads its filters into the builder. User can modify and save as a new custom preset.

**Universe selector** (above filter builder):
Multi-select for market scope: Finnish (XHEL), Swedish (XSTO), European (multiple exchanges), US (XNYS, XNAS). Default: All.

**Results table** (below filter builder):

Same column structure as the watchlist table, plus the screened factor values. Sortable by any column.

**Interactions:**
- Click "Run Screen" to execute. Results appear in the table with match count.
- Click "Save Preset" to name and save the current filter configuration.
- Click "Add to Watchlist" (row-level or bulk) to add screened securities to a chosen watchlist.
- Click "Compare" on up to 4 securities to enter comparison mode.

### Comparison Mode

When 1-4 securities are selected for comparison, a bottom tray slides up (40% of viewport height, resizable).

**Comparison layout:** Side-by-side columns, one per security.

| Row | Description |
|-----|-------------|
| Header | Ticker, name, exchange, asset class |
| Price | Current price, day change |
| Valuation | P/E, P/B, EV/EBITDA, PEG |
| Profitability | ROE, ROIC, Net Margin, FCF Yield |
| Growth | Revenue Growth (1Y, 3Y, 5Y), Earnings Growth (1Y, 3Y, 5Y) |
| Dividends | Yield, Payout Ratio, Consecutive Years |
| Risk | Beta, Volatility (1Y), Max Drawdown (1Y) |
| Debt | Debt/Equity, Interest Coverage |
| Moat | Moat rating (if researched) |

Better values are subtly highlighted with `positive-muted` background. Worst values use `negative-muted` background. "Better" is contextual: lower P/E is better, higher ROE is better.

**Interactions:**
- Click "X" on a security column to remove it from comparison
- Click "Add" button (if < 4 selected) to add another via search
- Click "Close" to dismiss the comparison tray
- Click a security header to navigate to its detail page

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `w` | Navigate to Watchlist & Screener page |
| `Tab` | Switch between Watchlist and Screener tabs |
| `n` | Create new watchlist (when on Watchlist tab) |
| `a` | Add security to current watchlist (opens search modal) |
| `c` | Toggle comparison mode for selected securities |
| `Enter` | Run screen (when on Screener tab with filters defined) |
| `Escape` | Close comparison tray |

## Business Rules

1. **Watchlist uniqueness**: A security can appear in multiple watchlists but only once per watchlist (enforced by `uq_watchlist_items_watchlist_security` constraint).

2. **Default watchlist**: Exactly one watchlist can be marked as default (`is_default = TRUE`). Setting a new default clears the flag on the previous default. The default watchlist is shown on page load.

3. **Screener universe**: The screener runs against all active securities in the `securities` table, filtered by the universe selector. Securities without sufficient fundamental data for a filter are excluded from results (not treated as matching or failing).

4. **Filter logic**: Filters within a group are combined with AND by default. The user can toggle individual connections to OR. Nested groups (AND of ORs) are not supported in v1 — flat list only.

5. **Preset immutability**: Built-in presets (Munger Quality, Boglehead ETF, etc.) cannot be deleted or renamed. They can be loaded, modified, and saved as new custom presets.

6. **Screener data freshness**: Fundamental data (P/E, P/B, ROE, etc.) comes from the weekly Yahoo Finance fundamentals pipeline. A "Data as of {date}" label appears on the screener results. If fundamentals are older than 14 days, a warning badge appears.

7. **Comparison limit**: Maximum 4 securities in side-by-side comparison. The "Add" button is disabled when 4 are selected. This limit ensures the columns remain readable on a 1920px viewport.

8. **Multi-currency display**: In comparison mode, all monetary values are converted to EUR for fair comparison. Native currency prices are shown in parentheses.

9. **Dividend aristocrat data**: Consecutive dividend year counts are sourced from Yahoo Finance or manual entry. The screener uses this as a filterable field.

## Edge Cases

1. **Empty watchlist**: Table shows empty state: "This watchlist is empty. Click 'Add Security' or drag from the screener to add." No metrics calculated.

2. **No watchlists exist**: On first visit, auto-create a "Default" watchlist and show it. Prompt: "Your first watchlist has been created. Start adding securities."

3. **Screener returns 0 results**: Show message: "No securities match your filters. Try broadening your criteria." Suggest relaxing the most restrictive filter (the one that eliminated the most candidates, if calculable).

4. **Security in watchlist is delisted**: Show with `is_active = FALSE` styling (dimmed row, strikethrough ticker). Price shows last known close. A "Delisted" badge appears. Include in the list but exclude from comparison and screener.

5. **Missing fundamental data for screener filter**: If a security lacks a data point needed by a filter (e.g., no P/E for a pre-profit company), the security is excluded from results for that screen. The results footer shows: "N securities excluded due to missing data."

6. **Screener performance with large universe**: The `POST /screener/run` endpoint must return within 3 seconds for 500 securities with 5 factors (see architecture performance targets). Pagination with `limit=50` by default. Backend pre-filters on indexed columns (asset class, exchange) before computing derived factors.

7. **Concurrent watchlist edits**: Not applicable (single-user system), but the API uses optimistic concurrency — the frontend re-fetches after mutations.

8. **Comparison with mixed asset classes**: Comparing a stock with an ETF is allowed but may produce `N/A` for non-applicable metrics (e.g., P/E for a broad index ETF). The comparison row shows `—` for unavailable metrics.

## Acceptance Criteria

1. Users can create, rename, and delete watchlists. Deleting a watchlist removes all its items.
2. Users can add securities to a watchlist via search and remove them individually or in bulk.
3. The watchlist table displays all specified columns (price, day change, P/E, P/B, div yield, market cap, moat, notes) with correct values.
4. The screener filter builder supports all listed factors with comparison and `between` operators.
5. AND/OR logic between filters works correctly and produces accurate results.
6. All 5 built-in presets (Munger Quality, Boglehead ETF, Dividend Aristocrats, High Growth, Deep Value) load correct filter configurations.
7. Custom presets can be saved, loaded, and deleted.
8. The universe selector correctly filters screener results by exchange/market.
9. Screener results are sortable by any column and paginated.
10. Side-by-side comparison works for 1-4 securities with all specified metric rows.
11. Better/worse values in comparison are visually distinguished with background color.
12. Securities can be added to a watchlist directly from screener results.
13. The screener returns results within 3 seconds for a 500-security universe with 5 filters.
14. Empty states display appropriate messages for empty watchlists and zero-result screens.
15. Keyboard shortcuts work correctly for navigation, creation, and mode toggling.

## Changelog

| Date | Change |
|------|--------|
| 2026-03-19 | Initial draft |
