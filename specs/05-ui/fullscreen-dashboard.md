# Fullscreen Dashboard

Always-on portfolio display for TV or secondary monitor — a financial cockpit you glance at throughout the day.

## Dependencies

- [Design System](./design-system.md)
- [Layout & Navigation](./layout-navigation.md)

## Design Philosophy

This is a **passive monitoring screen**, not an interactive workspace. Optimized for readability at 2-3 meters distance on a 40"+ display. No scrolling required — everything fits in one viewport. Information refreshes automatically. The user should be able to glance at the TV and instantly know: how is my portfolio doing, what happened today, and is anything on fire.

## Entering / Exiting

- **Enter**: Cmd+Shift+F (global shortcut), or via Command Palette action "Fullscreen Dashboard", or via sidebar link
- **Exit**: Esc key, or click anywhere on the "Exit" button (top-right corner)
- Hides sidebar, status bar, and all chrome — true fullscreen content
- Uses `document.documentElement.requestFullscreen()` for browser fullscreen (falls back to CSS fullscreen if denied)

## Layout

6-panel grid filling the viewport. Panels sized by information priority.

```
+-------------------------------------------+-------------------+
|                                           |                   |
|           PORTFOLIO SUMMARY               |    MARKET PULSE   |
|           (value, daily P&L,              |  (index changes,  |
|            allocation donut)              |   FX, crypto)     |
|                                           |                   |
+-------------------------------------------+-------------------+
|                                           |                   |
|           TOP MOVERS                      |   RECOMMENDATIONS |
|           (holdings ranked by             |   (latest 5 recs  |
|            daily % change,                |    with action +   |
|            color-coded bars)              |    confidence)     |
|                                           |                   |
+-------------------------------------------+-------------------+
|                                           |                   |
|           NEWS FEED                       |   UPCOMING DATES  |
|           (latest 8 headlines             |   (dividends,     |
|            with sentiment color)          |    earnings, ex-   |
|                                           |    dates, alerts)  |
|                                           |                   |
+-------------------------------------------+-------------------+
```

### Grid Spec

| Property | Value |
|----------|-------|
| Grid | `grid-cols-[2fr_1fr] grid-rows-3` |
| Gap | 2px (hairline dark borders between panels) |
| Panel padding | 24px (comfortable at distance) |
| Background | `bg-primary` (#0A0E17) |
| Panel background | `bg-secondary` (#111827) |

## Panel Specifications

### 1. Portfolio Summary (top-left)

The hero panel — largest text, highest visual weight.

| Element | Style |
|---------|-------|
| Total portfolio value | `font-mono text-5xl font-bold` — e.g., "€127,432.18" |
| Daily P&L | `text-3xl font-mono` — color-coded green/red — e.g., "+€1,247.30 (+0.99%)" |
| Allocation donut | 200px diameter donut chart (equities/fixed income/crypto/cash) with percentage labels |
| Last updated | `text-sm text-tertiary` timestamp bottom-right of panel |

Color rules:
- Daily P&L positive: `text-positive` (#22C55E)
- Daily P&L negative: `text-negative` (#EF4444)
- Daily P&L zero: `text-secondary` (#9CA3AF)

### 2. Market Pulse (top-right)

Key market indices and rates at a glance.

| Row | Content |
|-----|---------|
| S&P 500 | Name + daily % change, color-coded |
| OMXH25 | Helsinki index |
| STOXX 600 | European equities |
| EUR/USD | FX rate + daily change |
| BTC/EUR | Bitcoin price + daily change |
| ECB rate | Current refinancing rate |
| 10Y Bund | Euro benchmark yield |

Each row: name left-aligned, value + change right-aligned.
- Font: `font-mono text-lg`
- Change color: green/red per direction
- Subtle row separators (`border-b border-terminal-border`)

### 3. Top Movers (middle-left)

Holdings ranked by absolute daily % change — what moved the most today.

- Show top 10 holdings by |daily change %|
- Each row: ticker, name (truncated), daily % change, horizontal bar visualization
- Bar width proportional to % change, color-coded:
  - Positive: green bar extending right from center
  - Negative: red bar extending left from center
- Font: `font-mono text-base`
- If no daily data available, show "Market closed" message with last close date

### 4. Recommendations (middle-right)

Latest investment recommendations from the agent team.

- Show 5 most recent recommendations
- Each card:
  - Action badge: **BUY** (green bg), **SELL** (red bg), **HOLD** (yellow bg)
  - Ticker + security name
  - Confidence: High/Medium/Low with color dot (green/yellow/red)
  - One-line rationale (truncated to 80 chars)
- Sorted by creation date, newest first
- If no recommendations exist, show "No recommendations yet"

### 5. News Feed (bottom-left)

Latest financial news with sentiment indicators.

- Show 8 most recent news items
- Each row:
  - Sentiment dot: green (positive), red (negative), gray (neutral)
  - Headline text (truncated to fit one line)
  - Time ago label ("2h", "5h", "1d")
  - If news is about a portfolio holding, highlight the ticker in `text-accent`
- Font: `text-sm` for headlines, `text-xs` for timestamps
- Subtle alternating row backgrounds for readability

### 6. Upcoming Dates (bottom-right)

Calendar of important upcoming events within the next 30 days.

| Event Type | Icon | Color |
|------------|------|-------|
| Dividend ex-date | Coins icon | `text-positive` |
| Dividend payment | Coins icon (filled) | `text-positive` |
| Earnings report | BarChart3 icon | `text-info` |
| Alert triggered | Bell icon | `text-warning` |
| Recommendation expiry | Clock icon | `text-secondary` |

- Each row: date (Mon DD), event type icon, security ticker, description
- Sorted chronologically
- Today's events highlighted with `bg-tertiary` background
- Events within 3 days get a pulsing dot indicator
- If no upcoming events, show "No upcoming events"

## Auto-Refresh

| Data | Interval |
|------|----------|
| Portfolio value / P&L | 60 seconds |
| Market indices / FX / crypto | 60 seconds |
| Top movers | 60 seconds |
| News feed | 5 minutes |
| Recommendations | 5 minutes |
| Upcoming dates | 30 minutes |

Use `setInterval` with the intervals above. Each panel refreshes independently. Show a subtle pulse animation on the "last updated" timestamp when data refreshes.

## Clock

Top-right corner of the viewport (above all panels): current time in `HH:MM:SS` format, `font-mono text-lg text-tertiary`. Updates every second. Shows Helsinki timezone. Also shows market status:
- "Market Open" (green dot) during OMXH trading hours (Mon-Fri 10:00-18:30 EET)
- "Market Closed" (red dot) outside hours
- "Pre-Market" (yellow dot) 09:00-10:00 EET

## Typography Scaling

All text sizes are 1.5x larger than the normal terminal UI to ensure readability at distance:

| Normal UI | Fullscreen |
|-----------|------------|
| text-sm (14px) | text-lg (18px) |
| text-base (14px) | text-xl (20px) |
| text-lg (18px) | text-2xl (24px) |
| text-xl (20px) | text-3xl (30px) |
| Headings | text-4xl+ |

## Data Sources (API Endpoints)

| Panel | Endpoint |
|-------|----------|
| Portfolio Summary | `GET /portfolio/summary` |
| Market Pulse | `GET /macro/summary` + `GET /macro/series/{code}` |
| Top Movers | `GET /portfolio/holdings` (sort by daily change) |
| Recommendations | `GET /recommendations?limit=5&sort=-created_at` |
| News Feed | `GET /news?limit=8` |
| Upcoming Dates | `GET /dividends/events?upcoming=true` + `GET /alerts` |

## Responsive Behavior

| Screen | Layout |
|--------|--------|
| >= 1920px (TV/monitor) | Full 3×2 grid as specified |
| 1280-1919px | 2-column layout, panels stack to 3 rows of 2 |
| < 1280px | Not recommended — show warning "Best viewed on large display" but still render |

## Edge Cases

1. **All data loading**: Show skeleton pulse animations in each panel
2. **API unreachable**: Show "Data unavailable" per panel with retry timestamp, don't crash entire dashboard
3. **Market holiday**: Market Pulse shows "Holiday" status, Top Movers shows last trading day data
4. **No holdings**: Portfolio Summary shows €0 with "Import holdings to get started" message
5. **Browser denies fullscreen**: Fall back to CSS fullscreen (sidebar/statusbar hidden, content fills viewport)
6. **Screen sleep/wake**: Re-fetch all data on `visibilitychange` event when page becomes visible again

## Component

- File: `frontend/src/app/fullscreen/page.tsx`
- Route: `/fullscreen`
- Also accessible via Command Palette action "Fullscreen Dashboard"

## Changelog

| Date | Change |
|------|--------|
| 2026-03-21 | Initial spec |
