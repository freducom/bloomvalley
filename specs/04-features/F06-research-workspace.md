# F06 — Research Workspace

**Status: DRAFT**

Per-security research notes and valuation models supporting the Research Analyst's workflow. Every security under analysis gets a structured research note with a MANDATORY bull case and bear case (per AGENTS.md — no analysis is complete without both), sector-appropriate valuation models, a moat rating, and thesis status tracking. The workspace answers: "What is the investment thesis for this security, what could go right, what could go wrong, and what is it worth?"

## Dependencies

- Specs: [data-model](../01-system/data-model.md), [api-overview](../01-system/api-overview.md), [architecture](../01-system/architecture.md), [spec-conventions](../00-meta/spec-conventions.md), [design-system](../05-ui/design-system.md)
- Data: Yahoo Finance fundamentals pipeline (weekly), Yahoo Finance daily prices pipeline
- API: `GET /research/notes`, `GET /research/notes/{securityId}`, `POST /research/notes`, `PUT /research/notes/{id}`, `GET /securities/{id}`, `GET /prices/{securityId}`

## Data Requirements

### Tables Read

| Table | Purpose |
|-------|---------|
| `research_notes` | All research notes: thesis, bull/bear/base case, intrinsic value, moat rating, tags, status |
| `securities` | Security metadata (name, ticker, sector, industry, asset class, country) for context and valuation model selection |
| `prices` | Historical prices for valuation context (current price vs intrinsic value) |
| `holdings_snapshot` | Whether the security is currently held (affects thesis status context) |
| `watchlist_items` | Whether the security is on a watchlist |

### Tables Written

| Table | Operation | Trigger |
|-------|-----------|---------|
| `research_notes` | INSERT | Create new research note |
| `research_notes` | UPDATE | Edit thesis, bull/bear case, intrinsic value, moat, status, tags |

### Calculations Invoked

None from the calculation specs. Valuation models (DCF, DDM, P/B-based, FFO-based, etc.) are computed client-side or via a dedicated valuation endpoint (future). The workspace stores model inputs and outputs in the `research_notes` fields and the `thesis` text field.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/research/notes` | List all research notes. Supports `?securityId`, `?moatRating`, `?isActive`, `?tags`, `?q` (text search on title/thesis), `?sortBy`, `?sortOrder`. Paginated |
| GET | `/research/notes/{securityId}` | Get all research notes for a specific security (a security may have multiple notes over time) |
| POST | `/research/notes` | Create a new research note. Body: `{ "securityId", "title", "thesis", "bullCase", "bearCase", "baseCase", "intrinsicValueCents", "intrinsicValueCurrency", "marginOfSafetyPct", "moatRating", "tags" }` |
| PUT | `/research/notes/{id}` | Update an existing research note |
| DELETE | `/research/notes/{id}` | Soft-delete a research note (sets `is_active = FALSE`) |
| GET | `/securities/{id}` | Security detail with latest fundamentals (P/E, P/B, ROE, etc.) for valuation context |

See [api-overview](../01-system/api-overview.md) for full request/response schemas.

## UI Views

### Page Layout (`/research`)

Two-panel layout: **List panel** (left, 350px) and **Detail panel** (right, remaining width).

### Left Panel — Research Notes List

A filterable, sortable list of all researched securities.

**Each list item shows:**
- Security ticker and name
- Moat badge: `None` (gray), `Narrow` (yellow), `Wide` (green)
- Thesis status badge: `Active` (green), `Under Review` (yellow), `Closed` (gray)
- Intrinsic value vs current price: `IV: €150 / Price: €120` with margin of safety percentage
- Last updated date
- Tags as small pills

**Filter controls (above list):**
- Text search (searches title, thesis text, ticker, security name)
- Moat rating filter: All / None / Narrow / Wide
- Status filter: All / Active / Under Review / Closed
- Tag filter: multi-select from existing tags
- Sort: by security name, last updated, margin of safety, moat rating

**Actions:**
- "New Research Note" button at top
- Click a list item to load it in the detail panel

### Right Panel — Research Note Detail

When a note is selected, the detail panel shows a structured research workspace.

**Header section:**
- Security: ticker, full name, exchange, asset class, sector, industry, country
- Current price: `€120.45` with day change
- Moat rating: dropdown selector (`None` / `Narrow` / `Wide`)
- Thesis status: dropdown (`Active` / `Under Review` / `Closed`)
- Tags: editable tag input with autocomplete from existing tags
- Last updated: timestamp

**Section 1 — Investment Thesis (rich text editor):**

A text area (Markdown-capable or rich text) for the overall investment thesis. This is the "elevator pitch" for why this security is interesting.

**Section 2 — Bull Case (MANDATORY):**

A dedicated rich text section with a green left border. The label shows: "Bull Case (Required)". If empty when the user attempts to save with status "Active", a validation warning appears: "An active thesis requires both a bull case and a bear case."

**Section 3 — Bear Case (MANDATORY):**

A dedicated rich text section with a red left border. The label shows: "Bear Case (Required)". Same validation as bull case.

**Section 4 — Base Case:**

Optional rich text section with a blue left border. The expected/most-likely scenario.

**Section 5 — Valuation Model:**

A structured section whose content varies by sector (per the AGENTS.md valuation table):

| Security Sector | Primary Model Shown | Secondary Model |
|----------------|--------------------|-----------------|
| Mature / Industrial | DCF (Owner Earnings) | EV/EBITDA multiple |
| Tech / Growth | DCF (with sensitivity) | EV/Revenue, Rule of 40 |
| Banks / Financials | P/B, Excess Return Model | DDM, P/E |
| Insurance | P/B, Embedded Value | Combined Ratio, DDM |
| REITs | NAV, FFO/AFFO | Cap Rate, P/FFO |
| Utilities | DDM, Regulated Asset Base | P/E, EV/EBITDA |
| Mining / Resources | P/NAV of reserves | EV/EBITDA |
| Commodity ETCs | **Flagged as poor long-term** | Total return vs spot divergence |

The system auto-selects the appropriate model template based on `securities.sector`. The user can override and add additional models.

**DCF Model inputs (when applicable):**

| Input | Field Type | Description |
|-------|-----------|-------------|
| Revenue (TTM) | currency | Starting revenue |
| Revenue Growth (Years 1-5) | percentage | Annual growth rates |
| Revenue Growth (Years 6-10) | percentage | Fade-down growth rates |
| Operating Margin (target) | percentage | Steady-state margin |
| Tax Rate | percentage | Effective tax rate (default: 20% for Finland) |
| Reinvestment Rate | percentage | Capex as % of revenue |
| WACC | percentage | Discount rate |
| Terminal Growth Rate | percentage | Long-term growth (default: 2%) |
| Shares Outstanding | number | For per-share value |

**DCF Model outputs (computed on input change):**

| Output | Description |
|--------|-------------|
| Enterprise Value | Present value of future free cash flows |
| Equity Value | Enterprise value - net debt |
| Intrinsic Value Per Share | Equity value / shares outstanding |
| Margin of Safety | (Intrinsic value - current price) / intrinsic value |
| Sensitivity Table | Grid showing intrinsic value at different WACC and terminal growth combinations |

**P/B Model inputs (for banks/financials):**

| Input | Description |
|-------|-------------|
| Book Value Per Share | Current BVPS |
| Sustainable ROE | Expected long-term ROE |
| Cost of Equity | Required return |
| Target P/B | Justified P/B = (ROE - g) / (CoE - g) |

**DDM Model inputs (for utilities/dividend payers):**

| Input | Description |
|-------|-------------|
| Current Dividend Per Share | Last annual dividend |
| Dividend Growth Rate | Expected annual growth |
| Required Return | Cost of equity |
| Intrinsic Value | Gordon Growth: D1 / (r - g) |

Each model section has a "Calculate" button that computes outputs and stores the intrinsic value in `research_notes.intrinsic_value_cents`.

**Section 6 — Intrinsic Value Summary:**

A compact summary bar below the valuation models:
- **Intrinsic Value**: `€150.00` (from the selected model)
- **Current Price**: `€120.45`
- **Margin of Safety**: `19.7%`
- **Verdict**: visual bar showing current price position relative to intrinsic value, with zones marked "deep value", "fair value", "overvalued"

**Auto-save:** The note auto-saves 2 seconds after the user stops typing. A "Saved" / "Saving..." / "Unsaved changes" indicator shows in the header.

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `n` | Create new research note |
| `Ctrl+S` / `Cmd+S` | Force save current note |
| `Escape` | Return to list view (deselect current note) |
| `j` / `k` | Navigate up/down in the notes list |
| `/` | Focus search in the list panel |

## Business Rules

1. **Bull and bear case are MANDATORY**: Per AGENTS.md, every security analysis must have both a bull case and a bear case. The system enforces this by showing a warning when saving a note with status "Active" that lacks either case. Notes with status "Under Review" or "Closed" are exempt from this validation (they may represent incomplete or superseded analysis).

2. **Sector-appropriate valuation models**: The workspace detects the security's sector from `securities.sector` and pre-loads the appropriate valuation model template per the AGENTS.md valuation table. DCF is NOT universal — using DCF for a bank is flagged with a warning: "DCF is not recommended for banks/financials. Consider P/B or Excess Return Model instead."

3. **Commodity ETC warning**: If the security is identified as a commodity ETC (based on sector/industry classification), a permanent red banner appears: "Commodity ETCs are generally poor long-term investments due to contango roll costs eroding returns. Consider the total return vs spot price divergence."

4. **Moat rating definitions**:
   - `None`: No sustainable competitive advantage identified. Business is commodity-like.
   - `Narrow`: Some competitive advantage exists but it is limited in scope or duration (5-10 years).
   - `Wide`: Strong, durable competitive advantage expected to persist for 10+ years. High barriers to entry.

5. **Thesis status lifecycle**: `Active` -> `Under Review` (when conditions change materially) -> `Closed` (when the thesis is no longer valid — position sold, thesis disproven, or company fundamentally changed). Status changes are logged in the `updated_at` timestamp.

6. **Multiple notes per security**: A security can have multiple research notes over time (e.g., initial analysis, updated thesis, sector review). The most recent active note is shown first. Closed notes are retained for historical reference and learning.

7. **Margin of safety calculation**: `(intrinsic_value - current_price) / intrinsic_value * 100`. A positive margin means the stock is undervalued. The value is stored in `research_notes.margin_of_safety_pct` and recalculated whenever intrinsic value is updated (but NOT on every price change — it reflects the analyst's estimate at the time of the note).

8. **Tag taxonomy**: Tags are free-form but the system suggests common tags: `munger-pick`, `boglehead-core`, `dividend-aristocrat`, `deep-value`, `high-growth`, `watchlist-candidate`, `position-held`, `sector-review`.

## Edge Cases

1. **Security with no sector data**: If `securities.sector` is NULL, the valuation model section shows all model templates and asks the user to select the appropriate one. No auto-selection occurs.

2. **No research notes exist**: The list panel shows an empty state: "No research notes yet. Click 'New Research Note' to start your first analysis." The detail panel shows a prompt to select or create a note.

3. **Delisted security**: If a security has `is_active = FALSE`, existing research notes are still accessible. A "Delisted" banner appears in the detail header. The thesis status should typically be "Closed." Price data may be stale or unavailable — the valuation section shows last known data.

4. **Intrinsic value significantly below current price**: If the margin of safety is negative (stock is overvalued per the model), the summary bar shows the position in the "overvalued" zone with `negative` coloring. No automatic recommendation is made — the analyst decides.

5. **DCF with negative free cash flow**: If the model inputs produce negative FCF in early years, the DCF calculation still proceeds (high-growth companies may have negative near-term FCF). A note appears: "Negative free cash flow in projection years {N-M}. Terminal value dominates the valuation — sensitivity analysis is critical."

6. **Auto-save conflict**: Since this is a single-user system, save conflicts are not expected. If the save fails (e.g., network error), the "Unsaved changes" indicator turns red and a retry button appears.

7. **Very long thesis text**: Rich text sections support up to 50,000 characters each. If a section exceeds this, a warning appears. Content is stored in PostgreSQL `TEXT` columns with no practical length limit, but the UI enforces the soft limit for performance.

8. **Security in multiple watchlists**: The detail header shows all watchlists the security belongs to as small pills. This provides context for the analyst.

9. **Valuation model with missing fundamental data**: If required fundamental data (e.g., revenue, book value) is not available from the pipelines, the model input fields show `—` with a tooltip: "Data not available. Enter manually." The user can always override with manual inputs.

## Acceptance Criteria

1. Users can create, edit, and soft-delete research notes for any security in the catalog.
2. The list panel displays all research notes with moat rating, thesis status, intrinsic value vs price, and last updated date.
3. Filtering by text search, moat rating, thesis status, and tags works correctly.
4. The bull case and bear case sections are present and clearly labeled as mandatory.
5. Saving an "Active" note without both bull and bear case produces a validation warning.
6. The valuation model section auto-selects the sector-appropriate model based on `securities.sector`.
7. DCF model correctly computes enterprise value, equity value, intrinsic value per share, and margin of safety from user inputs.
8. The DCF sensitivity table shows intrinsic value across a grid of WACC and terminal growth rate combinations.
9. P/B model (for banks/financials) computes justified P/B and intrinsic value from ROE, cost of equity, and growth inputs.
10. DDM model (for utilities/dividend payers) computes intrinsic value using the Gordon Growth formula.
11. A warning is displayed when DCF is used for a bank/financial sector security.
12. Commodity ETC securities display a permanent warning about contango roll costs.
13. The moat rating dropdown updates the `research_notes.moat_rating` field on change.
14. Thesis status transitions (Active -> Under Review -> Closed) are supported and saved.
15. Auto-save triggers 2 seconds after the last edit with visual feedback.
16. The intrinsic value summary bar correctly shows current price position relative to intrinsic value.
17. Multiple research notes per security are supported, with the most recent active note shown first.
18. Tags can be added, removed, and filtered across all notes.
19. Keyboard shortcuts for navigation (j/k), creation (n), saving (Cmd+S), and search (/) work correctly.
20. The workspace displays correctly for securities with missing sector data, delisted securities, and securities with no fundamental data.

## Changelog

| Date | Change |
|------|--------|
| 2026-03-19 | Initial draft |
