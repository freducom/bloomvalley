# Layout & Navigation

App shell structure, sidebar navigation, tab system, command palette, keyboard shortcuts, and responsive behavior for the Bloomvalley terminal.

## Dependencies

- [Spec Conventions](../00-meta/spec-conventions.md)
- [Design System](./design-system.md)
- [Architecture](../01-system/architecture.md) -- frontend tech stack, project structure

## App Shell

The app uses a fixed three-zone layout: sidebar, main content area, and status bar.

```
+--------+--------------------------------------------+
| Side-  |                                            |
| bar    |           Main Content Area                |
| (nav)  |  +------+------+------+                    |
|        |  | Tab1 | Tab2 | Tab3 |  (feature tabs)   |
| F01    |  +------+------+------+--------------------+
| F02    |  |                                         |
| F03    |  |  Feature content fills remaining space  |
| ...    |  |                                         |
| F17    |  |                                         |
|        |  |                                         |
+--------+-+-----------------------------------------+
| Status Bar (full width)                             |
+-----------------------------------------------------+
```

### Layout Rules

| Zone | Position | Sizing |
|------|----------|--------|
| Sidebar | Fixed left | 240px expanded, 56px collapsed (icon-only) |
| Main content | Right of sidebar | `calc(100vw - sidebar width)`, fills remaining height |
| Status bar | Fixed bottom, full width | 32px height |

- **No top bar / header** -- vertical space is maximized for data display.
- Main content area uses `overflow-y: auto` for scrolling; sidebar and status bar remain fixed.
- Sidebar and status bar use `bg-secondary` (`#111827`). Main content uses `bg-primary` (`#0A0E17`).

### Implementation

- Root layout: `frontend/src/app/layout.tsx`
- Shell component: `frontend/src/components/layout/Shell.tsx`
- CSS: Tailwind utility classes; no custom CSS files unless unavoidable.

## Sidebar

### Structure

The sidebar displays feature navigation icons grouped by category. Each group has a subtle label visible only in expanded state.

| Group | Features | Icons (suggested Lucide icons) |
|-------|----------|-------------------------------|
| Portfolio | F01 Dashboard, F12 Transactions, F17 Import | `LayoutDashboard`, `ArrowLeftRight`, `Upload` |
| Markets | F02 Data Feeds, F03 Watchlist, F08 Charts | `Radio`, `Eye`, `CandlestickChart` |
| Analysis | F04 Risk, F06 Research, Screener (part of F03) | `ShieldAlert`, `BookOpen`, `Filter` |
| Income | F05 Tax, F09 Fixed Income, F13 Dividends | `Receipt`, `Landmark`, `Coins` |
| Macro | F07 Dashboard, F14 News | `Globe`, `Newspaper` |
| Tracking | F15 Insider, F16 Recommendations, F10 Alerts | `UserSearch`, `ThumbsUp`, `Bell` |
| Other | F11 ESG | `Leaf` |

### States

| State | Behavior |
|-------|----------|
| Expanded (default >= 1440px) | Icons + text labels, group headings visible |
| Collapsed (< 1440px or user toggle) | Icons only, 56px wide, group headings hidden |
| Hover (collapsed) | Tooltip shows feature name, appears right of icon after 300ms delay |
| Active | Left border accent (`accent` / `#8B5CF6`, 3px), icon and label use `text-primary`, background `bg-tertiary` |
| Inactive | Icon and label use `text-secondary` |
| Hover (item) | Background `bg-hover` (`#374151`), 150ms transition |

### Collapse Behavior

- **Auto-collapse**: viewport width < 1440px triggers collapsed state.
- **Manual toggle**: clickable chevron icon at bottom of sidebar. User preference persisted in `localStorage`.
- **Transition**: sidebar width animates over 300ms `ease-in-out`.
- When collapsed, the main content area expands to fill reclaimed space.

### Component

- File: `frontend/src/components/layout/Sidebar.tsx`
- UI state (expanded/collapsed) managed via React Context (`SidebarContext`) in `frontend/src/components/layout/Shell.tsx`.

## Tab System

Features with multiple sub-views use a horizontal tab bar at the top of the main content area.

### Tab Definitions by Feature

| Feature | Tabs |
|---------|------|
| F01 Portfolio Dashboard | Overview, Allocation, Glidepath, Performance |
| F03 Watchlist | Watchlist, Screener |
| F04 Risk | Overview, Correlation, Stress Tests, Monte Carlo |
| F05 Tax | Lots, Gains, Harvesting, Report |
| F06 Research | Theses, Models, Notes |
| F07 Macro Dashboard | Overview, Rates, Indicators |
| F08 Charts | (single view -- no tabs, security selector instead) |
| F09 Fixed Income | Overview, Bond Ladder, Income Projection |
| F12 Transactions | All, Buys, Sells, Dividends, Corporate Actions |
| F13 Dividends | Calendar, History, Projections |
| F15 Insider Tracking | Insider Trades, Congress Trades, Institutional, Buybacks |
| F16 Recommendations | Active, History, Retrospective |

Features not listed above use a single-view layout (no tab bar).

### Tab Bar Specs

| Property | Value |
|----------|-------|
| Height | 40px |
| Background | `bg-secondary` (`#111827`) |
| Bottom border | 1px `border-default` (`#1F2937`) |
| Tab font | Inter, `text-sm` (12px), `font-medium` |
| Active tab | `text-primary`, bottom border 2px `accent` (`#8B5CF6`) |
| Inactive tab | `text-secondary`, no bottom accent |
| Hover | `text-primary`, background `bg-tertiary` |
| Padding | `space-3` (12px) horizontal per tab |
| Transition | color 150ms ease-in-out |

### Tab Routing

- Tabs map to URL segments: `/portfolio`, `/portfolio/allocation`, `/portfolio/glidepath`, etc.
- Default tab (first) loads on bare feature URL.
- Active tab state derived from URL path (Next.js App Router).
- Tab changes do not trigger full page reload (client-side navigation).

## Command Palette

A global search modal for navigating features, finding securities, and triggering actions.

### Opening

- **Shortcut**: `Cmd+K` (macOS) / `Ctrl+K`
- **Trigger**: also accessible via a search icon in the sidebar footer (collapsed and expanded states)

### Layout

```
+---------------------------------------------+
| > Search features, securities, actions...   |
+---------------------------------------------+
| Recent                                       |
|   Portfolio Dashboard                   F01  |
|   AAPL - Apple Inc.              Security    |
|   Run price pipeline              Action     |
+---------------------------------------------+
| Features                                     |
|   ...filtered results...                     |
| Securities                                   |
|   ...filtered results...                     |
| Actions                                      |
|   ...filtered results...                     |
+---------------------------------------------+
```

### Specs

| Property | Value |
|----------|-------|
| Width | 560px, centered horizontally |
| Max height | 480px, scrollable results |
| Background | `bg-secondary` with `shadow-md` |
| Border radius | `rounded-lg` (8px) |
| Backdrop | Semi-transparent overlay `rgba(10, 14, 23, 0.7)` |
| Input font | Inter, `text-base` (14px) |
| Result item height | 40px |

### Search Categories

| Category | Searchable Fields | Result Display |
|----------|------------------|----------------|
| Features | Feature name, description | Icon + name + shortcut badge |
| Securities | Ticker symbol, company name, ISIN | Ticker + name + asset class badge |
| Actions | Action name (e.g., "Add transaction", "Create alert", "Run pipeline") | Action icon + name |

### Behavior

1. On open, show up to 5 recent items (persisted in `localStorage`).
2. As user types, results filter across all categories. Minimum 1 character to start filtering.
3. Results grouped by category with category headers.
4. Maximum 5 results per category displayed; if more exist, show "N more..." link.
5. Security search queries the backend: `GET /api/v1/securities/search?q={query}` with 200ms debounce.
6. Feature and action search is client-side (static list).

### Keyboard Navigation

| Key | Action |
|-----|--------|
| `Arrow Up` / `Arrow Down` | Move highlight through results |
| `Enter` | Select highlighted result (navigate to feature, open security detail, execute action) |
| `Esc` | Close palette |
| `Cmd+K` while open | Close palette (toggle) |

### Component

- File: `frontend/src/components/layout/CommandPalette.tsx`
- Uses a portal to render above all content.

## Keyboard Shortcuts

### Global Shortcuts

| Shortcut | Action |
|----------|--------|
| `Cmd+1` through `Cmd+9` | Navigate to first 9 sidebar features (in display order) |
| `Cmd+K` | Open / close command palette |
| `Cmd+/` | Toggle keyboard shortcut help overlay |
| `Esc` | Close topmost modal or palette; if none open, collapse sidebar |
| `Ctrl+Tab` | Cycle to next tab within current feature |
| `Ctrl+Shift+Tab` | Cycle to previous tab within current feature |

### Feature-Specific Shortcuts

Features may register additional shortcuts. These are shown in the help overlay grouped by active feature.

| Context | Shortcut | Action |
|---------|----------|--------|
| DataTable (any) | `Cmd+F` | Focus table filter input |
| DataTable (any) | `Cmd+E` | Export table to CSV |
| Charts (F08) | `1`-`7` | Switch timeframe (1D, 1W, 1M, 3M, 1Y, 5Y, Max) |
| Charts (F08) | `C` / `L` | Toggle candlestick / line mode |

### Help Overlay

- Triggered by `Cmd+/`.
- Full-screen semi-transparent overlay listing all active shortcuts in a two-column grid.
- Background: `rgba(10, 14, 23, 0.85)`.
- Closes on `Esc` or `Cmd+/` again.
- Shortcut keys displayed in `<kbd>` styled badges: `bg-tertiary`, `rounded-sm`, `text-sm`, `font-mono`.

### Implementation

- Global shortcuts registered via a `useKeyboardShortcuts` hook in the root layout.
- Uses `event.preventDefault()` to avoid browser defaults where needed (e.g., `Cmd+K` would open browser address bar).
- Feature-specific shortcuts registered/unregistered on feature mount/unmount.
- File: `frontend/src/hooks/useKeyboardShortcuts.ts`

## Responsive Behavior

| Viewport Width | Behavior |
|----------------|----------|
| >= 1920px | Full expanded layout, all features comfortable |
| 1440px -- 1919px | Expanded sidebar, content slightly narrower |
| 1280px -- 1439px | Sidebar auto-collapses to icon-only (56px) |
| < 1280px | Not supported; show a "minimum 1280px required" message |

### Content Area Adaptations

- Dashboard grid columns: 4 columns at >= 1920px, 3 columns at 1440px, 2 columns at 1280px.
- DataTable columns: less critical columns hidden via column visibility defaults at narrower widths.
- Chart components fill available width; maintain 16:9 aspect ratio for main charts.

## Edge Cases

1. **All modals closed + Esc pressed**: collapses sidebar if expanded; no-op if already collapsed.
2. **Command palette open + Cmd+1 pressed**: Cmd+1 is ignored while command palette is focused. Palette must be closed first.
3. **Multiple overlays open** (palette + help overlay): Esc closes the topmost one only. Stacking order: help overlay > command palette > feature modals.
4. **Tab cycling at last tab**: `Ctrl+Tab` on the last tab wraps to the first tab.
5. **Feature with no tabs + Ctrl+Tab**: no-op.
6. **Sidebar transition + click during animation**: clicks during the 300ms sidebar transition are debounced; navigation still triggers but layout settles after animation completes.
7. **Browser zoom 150%+**: may trigger collapsed sidebar earlier than 1440px breakpoint. Acceptable -- icon-only mode remains usable.
8. **Security search returns zero results**: show "No securities found" message in the securities section of the command palette.
9. **localStorage unavailable**: sidebar defaults to expanded, recent items list starts empty, no errors thrown.

## Changelog

| Date | Change |
|------|--------|
| 2026-03-19 | Initial draft -- DRAFT |
