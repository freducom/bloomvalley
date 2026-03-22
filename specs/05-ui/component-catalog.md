# Component Catalog

Reusable UI component specifications for the Bloomvalley terminal. Each component defines its purpose, props, visual description, states, and sizing. All components follow the design system tokens and are implemented as React/TypeScript components with TailwindCSS.

## Dependencies

- [Spec Conventions](../00-meta/spec-conventions.md)
- [Design System](./design-system.md) -- colors, typography, spacing, number formatting
- [Layout & Navigation](./layout-navigation.md) -- shell structure, where components are placed
- [Architecture](../01-system/architecture.md) -- frontend tech stack (Next.js, TanStack Table, TradingView Lightweight Charts, Recharts)

## Component Index

| # | Component | File Path | Used By |
|---|-----------|-----------|---------|
| 1 | MetricCard | `components/ui/MetricCard.tsx` | F01, F04, F07, F09, F13 |
| 2 | DataTable | `components/ui/DataTable.tsx` | F01, F03, F05, F12, F15, F16 |
| 3 | ChartCard | `components/charts/ChartCard.tsx` | F01, F04, F07, F08 |
| 4 | PriceChart | `components/charts/PriceChart.tsx` | F03, F08 |
| 5 | AllocationRing | `components/charts/AllocationRing.tsx` | F01 |
| 6 | GlidepathChart | `components/charts/GlidepathChart.tsx` | F01, F04 |
| 7 | CorrelationHeatmap | `components/charts/CorrelationHeatmap.tsx` | F04 |
| 8 | AlertBadge | `components/ui/AlertBadge.tsx` | All features with data freshness |
| 9 | CommandPalette | `components/layout/CommandPalette.tsx` | Global (shell) |
| 10 | StatusBar | `components/layout/StatusBar.tsx` | Global (shell) |
| 11 | BullBearCard | `components/ui/BullBearCard.tsx` | F06, F16 |
| 12 | DividendCalendar | `components/charts/DividendCalendar.tsx` | F13 |
| 13 | RecommendationBadge | `components/ui/RecommendationBadge.tsx` | F16, F03 |
| 14 | NewsCard | `components/ui/NewsCard.tsx` | F14, F07 |
| 15 | InsiderTradeRow | `components/ui/InsiderTradeRow.tsx` | F15 |
| 16 | EmptyState | `components/ui/EmptyState.tsx` | All features |
| 17 | LoadingSkeleton | `components/ui/LoadingSkeleton.tsx` | All features |
| 18 | StaleDataOverlay | `components/ui/StaleDataOverlay.tsx` | All features with data freshness |

All file paths are relative to `frontend/src/`.

---

## 1. MetricCard

A compact card displaying a single key metric with optional change indicator and sparkline. The primary building block for dashboards.

### Props

| Prop | Type | Required | Description |
|------|------|----------|-------------|
| `label` | `string` | Yes | Metric name (e.g., "Total Value", "Sharpe Ratio") |
| `value` | `string` | Yes | Pre-formatted display value (e.g., "E1,234,567.89") |
| `change` | `{ value: string; direction: 'up' \| 'down' \| 'flat' }` | No | Change indicator with formatted percentage |
| `sparklineData` | `number[]` | No | Array of values for sparkline (last 30 data points) |
| `size` | `'sm' \| 'md' \| 'lg'` | No | Card size variant. Default: `'md'` |
| `staleAt` | `Date \| null` | No | If set, shows `AlertBadge` in top-right corner |
| `onClick` | `() => void` | No | Makes card clickable with hover state |

### Size Variants

| Size | Dimensions | Content |
|------|------------|---------|
| `sm` | Min 140px wide, 72px tall | Label + value only |
| `md` | Min 180px wide, 88px tall | Label + value + change |
| `lg` | Min 240px wide, 120px tall | Label + value + change + sparkline (48px tall) |

### Visual Specs

- Background: `bg-secondary` (`#111827`)
- Border: 1px `border-default` (`#1F2937`), `rounded-md` (6px)
- Padding: `space-3` (12px)
- Label: Inter, `text-sm`, `font-medium`, `text-secondary`
- Value: JetBrains Mono, `text-xl` (sm: `text-lg`), `font-semibold`, `text-primary`
- Change: JetBrains Mono, `text-sm`, color per gain/loss rules (`positive` / `negative` / `text-tertiary`)
- Change prefix: up arrow, down arrow, or dash character
- Sparkline: 1px line, color matches change direction, no axes or labels
- Clickable hover: `bg-tertiary`, cursor pointer, 150ms transition

### States

| State | Behavior |
|-------|----------|
| Loading | Render `LoadingSkeleton` variant for MetricCard |
| Data present | Normal render |
| Stale data | `AlertBadge` in top-right, `StaleDataOverlay` if critically stale |
| No data | Show value as "--" in `text-tertiary` |
| Error | Show value as "Error" in `negative` color |

---

## 2. DataTable

A full-featured data table with sorting, filtering, virtual scrolling, column visibility toggle, and CSV export. Built on TanStack Table v8.

### Props

| Prop | Type | Required | Description |
|------|------|----------|-------------|
| `columns` | `ColumnDef<T>[]` | Yes | TanStack Table column definitions |
| `data` | `T[]` | Yes | Array of row data |
| `isLoading` | `boolean` | No | Shows skeleton rows. Default: `false` |
| `emptyMessage` | `string` | No | Message when `data` is empty. Default: "No data available" |
| `enableSorting` | `boolean` | No | Default: `true` |
| `enableFiltering` | `boolean` | No | Shows global filter input. Default: `true` |
| `enableColumnVisibility` | `boolean` | No | Shows column toggle dropdown. Default: `true` |
| `enableExport` | `boolean` | No | Shows CSV export button. Default: `true` |
| `enableVirtualization` | `boolean` | No | Enables virtual scrolling. Default: `true` when `data.length > 100` |
| `onRowClick` | `(row: T) => void` | No | Row click handler; adds hover and cursor pointer |
| `rowHeight` | `number` | No | Row height in pixels. Default: `36` |
| `maxHeight` | `string` | No | CSS max-height for scrollable area. Default: `'calc(100vh - 200px)'` |
| `stickyHeader` | `boolean` | No | Sticky header row. Default: `true` |

### Visual Specs

- Table background: transparent (inherits `bg-primary`)
- Header row: `bg-secondary`, `text-sm`, `font-medium`, `text-secondary`, bottom border 1px `border-default`
- Header cell padding: `space-2` vertical, `space-3` horizontal
- Body row: `text-base` (14px), `font-normal`, `text-primary`
- Body cell padding: same as header
- Alternate rows: no striping (too busy for terminal aesthetic)
- Row hover: `bg-tertiary`, 150ms transition
- Selected/clickable row: cursor pointer
- Sort indicator: up/down chevron icon in `text-secondary`, active in `text-primary`
- Column borders: none; rely on padding for separation
- Numeric columns: right-aligned, JetBrains Mono font
- Text columns: left-aligned, Inter font

### Toolbar

Positioned above the table, contains:

| Element | Position | Description |
|---------|----------|-------------|
| Filter input | Left | Text input with search icon, 200ms debounce, placeholder "Filter..." |
| Column toggle | Right | Dropdown with checkboxes for each column |
| CSV export | Right | Download icon button, exports visible columns and filtered data |
| Row count | Right | "N rows" in `text-tertiary`, `text-sm` |

### Virtual Scrolling

- Enabled automatically when row count > 100.
- Uses TanStack Virtual for row virtualization.
- Overscan: 10 rows above and below viewport.
- Scrollbar: styled thin (8px), `bg-tertiary` track, `bg-hover` thumb.

### States

| State | Behavior |
|-------|----------|
| Loading | 10 skeleton rows matching column layout |
| Empty | `EmptyState` component centered in table area |
| Error | `EmptyState` with error icon and retry option |
| Filtered to zero results | "No results match your filter" message |

---

## 3. ChartCard

A wrapper component for chart visualizations with a title bar, timeframe selector, and fullscreen toggle.

### Props

| Prop | Type | Required | Description |
|------|------|----------|-------------|
| `title` | `string` | Yes | Chart title displayed in header |
| `children` | `ReactNode` | Yes | Chart component to render inside |
| `timeframes` | `string[]` | No | Available timeframe options. Default: `['1D','1W','1M','3M','1Y','5Y','Max']` |
| `activeTimeframe` | `string` | No | Currently selected timeframe |
| `onTimeframeChange` | `(tf: string) => void` | No | Timeframe selection callback |
| `enableFullscreen` | `boolean` | No | Show fullscreen toggle. Default: `true` |
| `staleAt` | `Date \| null` | No | Staleness indicator |
| `headerRight` | `ReactNode` | No | Additional controls in header right area |

### Visual Specs

- Background: `bg-secondary`, border 1px `border-default`, `rounded-md`
- Header: 40px tall, `space-3` padding, bottom border 1px `border-default`
- Title: Inter, `text-sm`, `font-semibold`, `text-primary`, left-aligned
- Timeframe buttons: pill-style toggle group, `text-xs`, `font-medium`
  - Active: `bg-tertiary`, `text-primary`
  - Inactive: transparent, `text-secondary`
  - Hover: `text-primary`
- Fullscreen icon: `Maximize2` (Lucide), `text-secondary`, hover `text-primary`
- Chart area: fills remaining height, `space-2` padding

### Fullscreen Mode

- Expands to fill viewport with fixed position overlay.
- Background: `bg-primary`.
- Close button (X icon) in top-right corner.
- `Esc` key closes fullscreen.
- Chart reflows to new dimensions on enter/exit.

### States

| State | Behavior |
|-------|----------|
| Loading | `LoadingSkeleton` chart variant inside chart area |
| Data present | Renders children |
| Error | Error message centered in chart area with retry button |
| Stale | `AlertBadge` in header next to title |

---

## 4. PriceChart

Interactive price chart built on TradingView Lightweight Charts. Supports candlestick and line modes with technical indicators.

### Props

| Prop | Type | Required | Description |
|------|------|----------|-------------|
| `data` | `CandlestickData[] \| LineData[]` | Yes | OHLCV or line data points |
| `mode` | `'candlestick' \| 'line'` | No | Chart display mode. Default: `'candlestick'` |
| `volumeData` | `VolumeData[]` | No | Volume bars overlay |
| `indicators` | `Indicator[]` | No | Technical indicators to overlay |
| `height` | `number \| string` | No | Chart height. Default: `'100%'` |
| `theme` | `'terminal'` | No | Uses design system colors. Default: `'terminal'` |

### Indicator Type

```typescript
type Indicator = {
  type: 'SMA' | 'EMA' | 'RSI' | 'MACD' | 'BB';
  period: number;
  color?: string;
  visible?: boolean;
};
```

### Visual Specs

- Chart background: `bg-primary` (`#0A0E17`)
- Grid lines: `border-subtle` (`#111827`), 1px
- Candlestick up: `positive` (`#22C55E`), body filled
- Candlestick down: `negative` (`#EF4444`), body filled
- Line mode: `info` (`#3B82F6`), 2px, area fill with 10% opacity gradient
- Volume bars: 30% opacity, colored by candle direction
- Crosshair: `text-tertiary` color, dashed line
- Price axis: right side, JetBrains Mono `text-xs`, `text-secondary`
- Time axis: bottom, JetBrains Mono `text-xs`, `text-secondary`
- Indicator lines: configurable color, 1px, legend in top-left

### RSI and MACD Sub-Panels

- RSI: separate panel below main chart, 80px tall, horizontal lines at 30 and 70
- MACD: separate panel below RSI, 80px tall, histogram + signal + MACD lines

### Interactions

- Mouse drag: pan chart
- Scroll wheel: zoom in/out on time axis
- Hover: crosshair with price/date tooltip
- Click: (no default action; parent can handle via callback)

### States

| State | Behavior |
|-------|----------|
| Loading | Gray placeholder rectangle with pulsing animation |
| Data present | Renders chart |
| Empty data | "No price data available" centered message |
| Single data point | Renders as a dot with note "Insufficient data for chart" |

---

## 5. AllocationRing

Donut chart showing portfolio asset allocation. Supports current-only and current-vs-target overlay modes.

### Props

| Prop | Type | Required | Description |
|------|------|----------|-------------|
| `allocations` | `{ label: string; value: number; color: string }[]` | Yes | Current allocation slices (values are percentages, must sum to 100) |
| `target` | `{ label: string; value: number }[]` | No | Target allocation for overlay comparison |
| `size` | `number` | No | Diameter in pixels. Default: `240` |
| `showLabels` | `boolean` | No | Show percentage labels on slices. Default: `true` |
| `centerLabel` | `string` | No | Text shown in donut center (e.g., "Total: E1.2M") |

### Visual Specs

- Built with Recharts `PieChart`.
- Donut thickness: 30% of radius.
- Slice colors: asset class colors from design system (`asset-stocks`, `asset-etfs`, `asset-bonds`, `asset-crypto`, `asset-cash`).
- Slice gap: 2px.
- Labels: `text-xs`, `font-mono`, `text-primary`, positioned outside ring with leader lines.
- Center text: `text-lg`, `font-semibold`, `text-primary`.
- Target overlay: dashed outer ring (2px, `text-tertiary`) showing target percentages. Visible only when `target` prop provided.
- Hover: slice expands outward 4px, tooltip shows label, amount, and percentage.

### States

| State | Behavior |
|-------|----------|
| Loading | Gray ring skeleton with pulse animation |
| Data present | Normal donut chart |
| Empty (no holdings) | Full gray ring with center text "No holdings" |
| Single allocation (100%) | Full ring in single color |

---

## 6. GlidepathChart

Dual-line chart showing target vs actual asset allocation over time, with optional confidence band from Monte Carlo simulation.

### Props

| Prop | Type | Required | Description |
|------|------|----------|-------------|
| `targetPath` | `{ age: number; equities: number; fixedIncome: number; crypto: number; cash: number }[]` | Yes | Target allocation at each age |
| `actualPath` | `{ age: number; equities: number; fixedIncome: number; crypto: number; cash: number }[]` | Yes | Actual historical allocation |
| `confidenceBand` | `{ age: number; p10: number; p90: number }[]` | No | 10th-90th percentile band from Monte Carlo |
| `currentAge` | `number` | Yes | Current age marker (vertical dashed line) |
| `height` | `number` | No | Chart height in pixels. Default: `320` |

### Visual Specs

- Built with Recharts `ComposedChart`.
- X-axis: age (45 to 60), JetBrains Mono `text-xs`, `text-secondary`.
- Y-axis: percentage (0-100%), JetBrains Mono `text-xs`, `text-secondary`.
- Target line: `info` (`#3B82F6`), 2px, dashed.
- Actual line: `accent` (`#8B5CF6`), 2px, solid.
- Confidence band: `info-muted` fill with 20% opacity.
- Current age marker: vertical dashed line in `text-tertiary`, label "Now" above.
- Grid: horizontal lines only, `border-subtle`.
- Legend: bottom, `text-xs`, showing Target/Actual/Confidence labels.

### Hover Tooltip

Shows breakdown at hovered age:

```
Age 50
          Target    Actual
Equities   62%       65%
Fixed Inc  30%       27%
Crypto      5%        6%
Cash        3%        2%
```

Tooltip background: `bg-tertiary`, `rounded-sm`, `shadow-sm`, `text-xs`.

### States

| State | Behavior |
|-------|----------|
| Loading | Skeleton matching chart dimensions |
| Data present | Normal chart |
| No actual data | Only target line shown with note "No historical data yet" |

---

## 7. CorrelationHeatmap

NxN grid showing correlation coefficients between portfolio securities. Used in risk analysis.

### Props

| Prop | Type | Required | Description |
|------|------|----------|-------------|
| `securities` | `string[]` | Yes | Ordered list of security tickers |
| `matrix` | `number[][]` | Yes | NxN correlation matrix (values -1 to +1) |
| `size` | `'compact' \| 'full'` | No | Default: `'full'` |

### Visual Specs

- Grid-based layout (CSS Grid or canvas for large matrices).
- Cell size: `full` = 48px, `compact` = 32px.
- Color scale (diverging):
  - -1.0: `negative` (`#EF4444`)
  - 0.0: `bg-tertiary` (`#1F2937`)
  - +1.0: `positive` (`#22C55E`)
  - Linear interpolation between these stops.
- Cell text: correlation value to 2 decimals, JetBrains Mono `text-xs`, visible in `full` mode, hidden in `compact`.
- Row/column labels: ticker symbols, Inter `text-xs`, `font-medium`, `text-secondary`.
- Diagonal cells: always 1.00, slightly darker background.
- Hover: cell expands to show tooltip with full security names and exact value (e.g., "AAPL vs MSFT: +0.87").

### States

| State | Behavior |
|-------|----------|
| Loading | Gray grid skeleton |
| Data present | Normal heatmap |
| Single security | 1x1 grid showing "1.00" -- not particularly useful, show suggestion to add more holdings |
| Too many securities (> 25) | Switch to `compact` mode automatically, warn user |

---

## 8. AlertBadge

A small status dot indicating data freshness. Used inline next to labels or in component corners.

### Props

| Prop | Type | Required | Description |
|------|------|----------|-------------|
| `lastUpdated` | `Date` | Yes | Timestamp of last successful data refresh |
| `freshThreshold` | `number` | No | Minutes before data is considered approaching stale. Default: `30` |
| `staleThreshold` | `number` | No | Minutes before data is considered stale. Default: `60` |
| `showTooltip` | `boolean` | No | Show tooltip on hover. Default: `true` |

### Visual Specs

| Status | Color | Condition |
|--------|-------|-----------|
| Fresh | `positive` (`#22C55E`) | Age < `freshThreshold` |
| Warning | `warning` (`#F59E0B`) | `freshThreshold` <= age < `staleThreshold` |
| Stale | `negative` (`#EF4444`) | Age >= `staleThreshold` |

- Dot size: 8px diameter, `rounded-full`.
- Subtle pulse animation on stale status (1s cycle).
- Tooltip: "Last updated: {relative time}" (e.g., "Last updated: 5 minutes ago"). Background `bg-tertiary`, `shadow-sm`, `text-xs`.

---

## 9. CommandPalette

Global search modal. Full specification in [Layout & Navigation](./layout-navigation.md#command-palette). This entry covers component-level implementation details.

### Props

| Prop | Type | Required | Description |
|------|------|----------|-------------|
| `isOpen` | `boolean` | Yes | Controlled open state |
| `onClose` | `() => void` | Yes | Close callback |
| `features` | `FeatureItem[]` | Yes | Static list of navigable features |
| `onSearch` | `(query: string) => Promise<SearchResult[]>` | Yes | Async search callback for securities |
| `recentItems` | `SearchResult[]` | No | Recently accessed items |

### Implementation Notes

- Rendered via React Portal to `document.body`.
- Focus trapped within modal when open.
- Input auto-focused on open.
- Results virtualized if > 20 items.
- Keyboard events captured at modal level, not bubbled to parent.

---

## 10. StatusBar

Fixed bottom bar showing market status, pipeline health, and portfolio summary.

### Props

| Prop | Type | Required | Description |
|------|------|----------|-------------|
| `markets` | `MarketStatus[]` | Yes | Array of market statuses |
| `pipelines` | `PipelineHealth[]` | Yes | Array of pipeline health indicators |
| `portfolioValue` | `string` | Yes | Pre-formatted total portfolio value |
| `portfolioChange` | `{ value: string; direction: 'up' \| 'down' \| 'flat' }` | No | Daily change |

### Market Status Type

```typescript
type MarketStatus = {
  exchange: string;       // "NYSE", "NASDAQ", "OMX Helsinki", "Crypto"
  status: 'open' | 'closed' | 'pre-market' | 'after-hours';
};
```

### Pipeline Health Type

```typescript
type PipelineHealth = {
  name: string;           // "Yahoo", "FRED", "CoinGecko"
  status: 'healthy' | 'degraded' | 'failed';
  lastRun: Date;
};
```

### Visual Specs

- Height: 32px, fixed bottom, full width.
- Background: `bg-secondary`, top border 1px `border-default`.
- Layout: three sections (left: markets, center: pipelines, right: portfolio value).
- All text: `text-xs`, `font-mono`.
- Market status: exchange abbreviation + colored dot (green=open, yellow=pre/after, gray=closed).
- Pipeline health: small dots (6px) with name tooltip. Green=healthy, yellow=degraded, red=failed.
- Portfolio value: `font-semibold`, `text-primary`, change in gain/loss colors.

---

## 11. BullBearCard

Side-by-side display of bull case and bear case for a security analysis. Used in research workspace and recommendation views.

### Props

| Prop | Type | Required | Description |
|------|------|----------|-------------|
| `ticker` | `string` | Yes | Security ticker |
| `bullCase` | `{ summary: string; points: string[]; targetPrice?: string }` | Yes | Bull case content |
| `bearCase` | `{ summary: string; points: string[]; targetPrice?: string }` | Yes | Bear case content |
| `currentPrice` | `string` | No | Current price for context |

### Visual Specs

- Layout: two equal-width columns, side by side.
- Background: `bg-secondary`, `rounded-md`, 1px `border-default`.
- Bull side (left): left border 3px `positive`, header tinted `positive-muted` (`#166534`).
- Bear side (right): left border 3px `negative`, header tinted `negative-muted` (`#7F1D1D`).
- Header: "Bull Case" / "Bear Case" in `text-sm`, `font-semibold`, with up/down trend icon.
- Summary: `text-base`, `text-primary`, `space-2` below header.
- Points: bulleted list, `text-sm`, `text-secondary`.
- Target price (if provided): `font-mono`, `text-lg`, positioned below points.
- Divider: 1px `border-default` vertical line between columns.

### States

| State | Behavior |
|-------|----------|
| Loading | Two-column skeleton |
| Data present | Normal render |
| Missing one case | Show available case at full width with note "Bear/Bull case not yet written" |

---

## 12. DividendCalendar

Monthly calendar view showing dividend ex-dates and payment dates, color-coded by security.

### Props

| Prop | Type | Required | Description |
|------|------|----------|-------------|
| `events` | `DividendEvent[]` | Yes | Array of dividend events |
| `month` | `Date` | Yes | Current display month |
| `onMonthChange` | `(date: Date) => void` | Yes | Month navigation callback |
| `monthlyTotal` | `string` | No | Formatted monthly income total |
| `annualTotal` | `string` | No | Formatted projected annual income |

### Dividend Event Type

```typescript
type DividendEvent = {
  securityTicker: string;
  securityColor: string;  // from asset class or assigned palette
  exDate: string;          // ISO date
  paymentDate: string;     // ISO date
  amountPerShare: string;  // formatted
  totalAmount: string;     // formatted (shares * amount)
  type: 'ex-date' | 'payment';
};
```

### Visual Specs

- Standard 7-column calendar grid (Mon-Sun, European week start).
- Header: month/year with left/right navigation arrows, `text-lg`, `font-semibold`.
- Day cells: `bg-secondary`, 1px `border-subtle`, min-height 80px.
- Today: border highlighted in `accent`.
- Events shown as small color-coded pills inside day cells: ticker + type icon (ex-date: circle-dot, payment: banknote icon).
- Weekend columns: slightly dimmed (`bg-primary` instead of `bg-secondary`).
- Monthly/annual totals: displayed above calendar in `MetricCard` style (sm size).
- Hover on event pill: tooltip with full details (security name, amount per share, total, dates).

### States

| State | Behavior |
|-------|----------|
| Loading | Calendar grid skeleton with pulsing cells |
| No events this month | Empty calendar with "No dividend events this month" note |
| Many events on one day (> 4) | Show first 3 + "+N more" pill, click to expand |

---

## 13. RecommendationBadge

Compact badge showing buy/sell/hold rating with optional confidence level.

### Props

| Prop | Type | Required | Description |
|------|------|----------|-------------|
| `rating` | `'BUY' \| 'SELL' \| 'HOLD'` | Yes | Recommendation rating |
| `confidence` | `'high' \| 'medium' \| 'low'` | No | Confidence level |
| `size` | `'sm' \| 'md'` | No | Default: `'md'` |

### Visual Specs

| Rating | Background | Text Color |
|--------|------------|------------|
| BUY | `positive-muted` (`#166534`) | `positive` (`#22C55E`) |
| SELL | `negative-muted` (`#7F1D1D`) | `negative` (`#EF4444`) |
| HOLD | `warning-muted` (`#78350F`) | `warning` (`#F59E0B`) |

- Shape: `rounded-sm` (4px), inline-flex.
- Padding: sm = `2px 6px`, md = `4px 10px`.
- Font: Inter, sm = `text-xs`, md = `text-sm`, `font-semibold`, uppercase.
- Confidence indicator (if provided): 3 dots after text. Filled dots indicate confidence level (1=low, 2=medium, 3=high). Filled dots use text color; unfilled use `text-tertiary`.

---

## 14. NewsCard

A card displaying a single news item with metadata and sentiment indicator.

### Props

| Prop | Type | Required | Description |
|------|------|----------|-------------|
| `headline` | `string` | Yes | News headline |
| `source` | `string` | Yes | News source name |
| `timestamp` | `Date` | Yes | Publication time |
| `url` | `string` | No | Link to full article |
| `securities` | `string[]` | No | Related security tickers |
| `sentiment` | `'positive' \| 'negative' \| 'neutral'` | No | AI-detected sentiment |
| `summary` | `string` | No | One-line summary |

### Visual Specs

- Background: `bg-secondary`, `rounded-md`, 1px `border-default`.
- Padding: `space-3`.
- Headline: Inter, `text-base`, `font-medium`, `text-primary`. Truncated to 2 lines with ellipsis.
- Source + timestamp: `text-xs`, `text-tertiary`, separated by a dot.
- Securities: inline tag pills, `text-xs`, `font-mono`, `bg-tertiary`, `rounded-sm`, `space-1` gap.
- Sentiment indicator: small colored dot (8px) left of headline.
  - Positive: `positive`
  - Negative: `negative`
  - Neutral: `text-tertiary`
- Hover: `bg-tertiary` if `url` provided, cursor pointer.
- Summary (if provided): `text-sm`, `text-secondary`, single line below headline.

---

## 15. InsiderTradeRow

Specialized table row component for displaying insider trading activity. Designed to be used inside a `DataTable`.

### Props

| Prop | Type | Required | Description |
|------|------|----------|-------------|
| `insiderName` | `string` | Yes | Name of the insider |
| `role` | `string` | Yes | Role (e.g., "CEO", "CFO", "Board Member") |
| `transactionType` | `'buy' \| 'sell' \| 'option_exercise'` | Yes | Transaction type |
| `shares` | `string` | Yes | Formatted share count |
| `value` | `string` | Yes | Formatted transaction value |
| `date` | `Date` | Yes | Transaction date |
| `ticker` | `string` | Yes | Security ticker |
| `source` | `'FIN-FSA' \| 'Finansinspektionen' \| 'SEC' \| 'Congress'` | Yes | Reporting source |

### Visual Specs

- This component provides column definitions and cell renderers for use within `DataTable`.
- Transaction type: colored badge -- buy in `positive`, sell in `negative`, option exercise in `info`.
- Value column: JetBrains Mono, `font-medium`, colored by transaction type.
- Role: `text-sm`, `text-secondary`, displayed below insider name in the same cell.
- Source: small badge, `text-xs`, `bg-tertiary`.
- Date: formatted per design system date rules (relative if < 24h, otherwise DD MMM YYYY).

---

## 16. EmptyState

Generic placeholder shown when a feature or component has no data to display.

### Props

| Prop | Type | Required | Description |
|------|------|----------|-------------|
| `icon` | `LucideIcon` | No | Icon component. Default: `Inbox` |
| `title` | `string` | Yes | Primary message (e.g., "No transactions yet") |
| `description` | `string` | No | Secondary explanation |
| `action` | `{ label: string; onClick: () => void }` | No | Optional CTA button |

### Visual Specs

- Centered vertically and horizontally within parent container.
- Icon: 48px, `text-tertiary`.
- Title: Inter, `text-lg`, `font-medium`, `text-secondary`, `space-3` below icon.
- Description: Inter, `text-sm`, `text-tertiary`, `space-2` below title, max-width 360px, centered.
- CTA button (if provided): `bg-accent` (`#8B5CF6`), `text-inverse`, `rounded-sm`, `text-sm`, `font-medium`, padding `space-2` vertical, `space-4` horizontal, `space-4` below description. Hover: slightly lighter background.

---

## 17. LoadingSkeleton

Animated placeholder that mimics the layout of the component it replaces. Provides visual continuity during data fetches.

### Props

| Prop | Type | Required | Description |
|------|------|----------|-------------|
| `variant` | `'metric-card' \| 'data-table' \| 'chart' \| 'text-block' \| 'custom'` | Yes | Which component layout to mimic |
| `rows` | `number` | No | Number of rows for `data-table` variant. Default: `10` |
| `columns` | `number` | No | Number of columns for `data-table` variant. Default: `5` |
| `width` | `string` | No | Override width. Default: `'100%'` |
| `height` | `string` | No | Override height. Default: varies by variant |

### Variant Specs

| Variant | Description |
|---------|-------------|
| `metric-card` | Rounded rectangle matching MetricCard dimensions; two gray bars (label, value) |
| `data-table` | Header row + body rows of gray bars with varying widths per cell |
| `chart` | Rounded rectangle with wavy gray line suggesting a chart shape |
| `text-block` | 3 lines of gray bars with varying widths (100%, 85%, 60%) |
| `custom` | Single gray rectangle using provided width/height |

### Animation

- Shimmer effect: gradient slides left-to-right over gray bars.
- Base color: `bg-tertiary` (`#1F2937`).
- Shimmer highlight: `bg-hover` (`#374151`).
- Animation: 1.5s ease-in-out infinite.
- `prefers-reduced-motion`: static gray bars, no animation.

---

## 18. StaleDataOverlay

Semi-transparent overlay applied to any component displaying data that has exceeded its staleness threshold.

### Props

| Prop | Type | Required | Description |
|------|------|----------|-------------|
| `lastUpdated` | `Date` | Yes | When data was last refreshed |
| `onRefresh` | `() => void` | No | Refresh callback. Shows "Refresh" button if provided. |
| `children` | `ReactNode` | Yes | The component to overlay |

### Visual Specs

- Wrapper: `position: relative` around children.
- Overlay: `position: absolute`, inset 0, `bg-primary` with 60% opacity, `rounded-md` matching children.
- Content centered on overlay:
  - Clock icon, 24px, `text-tertiary`.
  - "Last updated: {relative time}" in `text-sm`, `text-secondary`, `space-2` below icon.
  - "Refresh" button (if `onRefresh` provided): `text-sm`, `text-info`, underline on hover, `space-2` below timestamp.
- Overlay does not block the underlying content from being readable (60% opacity chosen for this balance).
- Underlying component is not interactive while overlay is shown (overlay has `pointer-events: all`).

---

## Shared Patterns

### Tooltip Standard

All tooltips across components follow a consistent style:

- Background: `bg-tertiary`, `shadow-sm`, `rounded-sm`.
- Text: `text-xs`, `text-primary`.
- Padding: `space-1` vertical, `space-2` horizontal.
- Delay: 300ms before showing.
- Position: above element by default, flip if insufficient space.

### Error Boundary

Every component above should be wrapped in an error boundary that catches render errors and displays:

- A subtle "Something went wrong" message in `text-tertiary`.
- Does not crash the entire page -- only the affected component.
- Logs error details to console for debugging.

### Accessibility

- All interactive components have `aria-label` or `aria-labelledby`.
- Color-coded information (gain/loss, status) always has a secondary indicator (icon, text, or pattern).
- Focus rings: 2px `accent` outline on keyboard focus, not visible on mouse click.
- Charts include `aria-description` summarizing the data trend for screen readers.

## Edge Cases

1. **MetricCard with extremely large values**: abbreviation kicks in at >= 1M per design system formatting rules. Card width stretches to fit if needed.
2. **DataTable with zero columns visible**: show message "No columns selected" with a reset button.
3. **AllocationRing with very small slices (< 1%)**: group into "Other" slice if more than 2 slices are < 1%.
4. **CorrelationHeatmap with 1 security**: show single cell with "Add more holdings for correlation analysis" message.
5. **DividendCalendar day with > 10 events**: show first 3 events plus "+7 more" expandable pill. Clicking shows popover with full list.
6. **PriceChart with gaps in data (market holidays)**: gaps are expected; TradingView Lightweight Charts handles this natively with time scale business days mode.
7. **StaleDataOverlay on a small component (< 100px)**: hide the text, show only the overlay tint and a small warning icon.
8. **LoadingSkeleton with `prefers-reduced-motion`**: all animations disabled, static gray bars shown instead.
9. **EmptyState in a very small container (< 200px)**: hide description and action, show only icon and title in smaller font.
10. **StatusBar with all pipelines failed**: all dots red; consider adding a subtle pulsing red background tint to draw attention.
11. **NewsCard with no sentiment data**: hide the sentiment dot entirely rather than showing neutral.
12. **Multiple StaleDataOverlays nested**: only the outermost overlay should render; inner overlays suppressed via context.

## Changelog

| Date | Change |
|------|--------|
| 2026-03-19 | Initial draft -- DRAFT |
