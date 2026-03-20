# F08 — Technical Charts

Interactive price charting module built on TradingView Lightweight Charts, providing the Technical Analyst with candlestick and line charts, configurable technical indicators, drawing tools, and multi-chart layouts. This module supports timing analysis for entry and exit decisions on both Munger satellite positions and broad market monitoring.

**Status: DRAFT**

## Dependencies

- [Data Model](../01-system/data-model.md) — `prices` hypertable (OHLCV), `securities` table
- [API Overview](../01-system/api-overview.md) — `/prices`, `/charts`, `/securities` endpoint groups
- [Spec Conventions](../00-meta/spec-conventions.md) — date/time, monetary format
- F02 — Market Data Feeds (price data pipeline)

## Data Requirements

### Price Data

- Source: `prices` hypertable (daily OHLCV data per security)
- Fields used: `open_cents`, `high_cents`, `low_cents`, `close_cents`, `adjusted_close_cents`, `volume`, `date`
- All price values converted from cents to decimal for chart rendering (e.g., 15234 cents -> 152.34)
- Currency displayed alongside the price axis label (e.g., "USD", "EUR")

### Indicator Calculations

All indicator calculations are performed server-side in Python (numpy/pandas) and returned via the API. The frontend does not compute indicators.

| Indicator | Type | Parameters | Default |
|-----------|------|------------|---------|
| SMA | Overlay | Period | 50, 200 |
| EMA | Overlay | Period | 12, 26 |
| Bollinger Bands | Overlay | Period, StdDev multiplier | 20, 2.0 |
| RSI | Oscillator | Period | 14 |
| MACD | Oscillator | Fast, Slow, Signal | 12, 26, 9 |
| Volume | Bar chart | None | N/A |

### Timeframe Mapping

| Timeframe | Data Range | Data Points (approx) |
|-----------|-----------|---------------------|
| 1D | Last trading day | 1 (single bar context with intraday if available) |
| 1W | Last 5 trading days | 5 |
| 1M | Last ~22 trading days | 22 |
| 3M | Last ~66 trading days | 66 |
| 1Y | Last ~252 trading days | 252 |
| 5Y | Last ~1260 trading days | 1260 |
| Max | All available history | Variable |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/prices/{securityId}` | OHLCV price data with date range; supports `fromDate`, `toDate`, `timeframe` query params |
| GET | `/charts/indicators` | Compute technical indicators for a security; query params: `securityId`, `indicator` (SMA, EMA, BB, RSI, MACD), `params` (JSON-encoded parameters), `fromDate`, `toDate` |
| GET | `/charts/comparison` | Price data for two securities normalized to a common base (percentage change from start date); query params: `securityId1`, `securityId2`, `fromDate`, `toDate` |
| GET | `/securities` | Security search for the selector; supports `q` (text search), `assetClass` filter |

### Response: `GET /charts/indicators`

```json
{
  "data": {
    "securityId": 42,
    "indicator": "SMA",
    "params": { "period": 50 },
    "series": [
      { "date": "2026-03-18", "value": 15234 },
      { "date": "2026-03-17", "value": 15198 }
    ]
  }
}
```

### Response: `GET /charts/comparison`

```json
{
  "data": {
    "baseDate": "2025-03-19",
    "securities": [
      {
        "securityId": 42,
        "ticker": "AAPL",
        "series": [
          { "date": "2025-03-19", "changePercent": 0.0 },
          { "date": "2025-03-20", "changePercent": 1.23 }
        ]
      },
      {
        "securityId": 87,
        "ticker": "MSFT",
        "series": [
          { "date": "2025-03-19", "changePercent": 0.0 },
          { "date": "2025-03-20", "changePercent": 0.87 }
        ]
      }
    ]
  }
}
```

## UI Views

### Security Selector

- **Search input** at the top of the chart area with typeahead autocomplete
- Searches by ticker, ISIN, or company name (uses the `securities` trigram index)
- Results show: ticker, name, exchange, asset class badge
- Recently viewed securities listed below the search input (stored in localStorage, max 10)

### Chart Area

- **TradingView Lightweight Charts** library for price rendering
- **Chart modes** (toggle buttons):
  - Candlestick (default): OHLC candles with green (close > open) and red (close < open) coloring
  - Line: closing price as a continuous line
- **Timeframe selector** (button group): 1D | 1W | 1M | 3M | 1Y | 5Y | Max
- **Price axis** (right side): auto-scaled, shows currency, crosshair with exact price on hover
- **Time axis** (bottom): auto-formatted dates based on timeframe zoom level
- **Volume bars**: displayed in a separate pane below the main chart, colored to match candle direction

### Overlay Indicators

- Rendered directly on the main price chart
- **SMA**: solid lines; default 50-day (blue) and 200-day (orange)
- **EMA**: dashed lines; configurable period
- **Bollinger Bands**: upper band, middle band (SMA), lower band as filled region with low opacity
- Each overlay can be toggled on/off and has configurable parameters via a settings popover

### Oscillator Indicators

- Rendered in **separate panes** below the main chart (stacked vertically)
- **RSI pane**: line chart with horizontal reference lines at 30 (oversold) and 70 (overbought); zone shading between 30-70
- **MACD pane**: MACD line, signal line, and histogram bars (green/red for positive/negative divergence)
- Each oscillator pane has its own Y-axis and can be collapsed or removed

### Drawing Tools

- **Toolbar** (vertical, left side of chart):
  - Trend line: click two points to draw a line
  - Horizontal line: click one point to draw a horizontal price level
  - Fibonacci retracement: click two points (swing high and swing low); renders 0%, 23.6%, 38.2%, 50%, 61.8%, 78.6%, 100% levels
- Drawings persist per security in localStorage
- Right-click on a drawing to delete it
- Drawings have configurable line color and style (solid, dashed)

### Multi-Chart Layout

- **Layout selector** (button group in toolbar): 1 | 2 | 4
  - 1-chart: full width single chart (default)
  - 2-chart: side-by-side, each 50% width
  - 4-chart: 2x2 grid, each 25% of the area
- Each chart in a multi-chart layout is an independent instance with its own security, timeframe, and indicators
- Clicking a chart makes it the "active" chart (highlighted border); indicator/drawing controls apply to the active chart

### Comparison Mode

- Activated from the chart toolbar ("Compare" button)
- Opens a security search to select a second security
- Both securities plotted as percentage change from the start of the selected timeframe
- Y-axis shows percentage change; legend shows both tickers with their total return over the period
- Exiting comparison mode returns to the standard price chart

## Business Rules

1. **Default chart state**: when a security is first loaded, display a 1Y candlestick chart with SMA 50 and SMA 200 overlays and volume bars.

2. **Indicator parameter validation**:
   - SMA/EMA period: integer, 1-500; reject if period > available data points
   - Bollinger Bands period: integer, 5-200; StdDev multiplier: float, 0.5-5.0
   - RSI period: integer, 2-100
   - MACD fast < slow (reject if fast >= slow); signal: integer, 1-50

3. **Price adjustment**: charts use `adjusted_close_cents` when available (accounts for splits and dividends). If `adjusted_close_cents` is NULL, fall back to `close_cents`.

4. **Missing data handling**: weekends and market holidays produce gaps in daily data. The chart library handles this natively by skipping missing dates on the time axis (no interpolation).

5. **Comparison normalization**: both securities are rebased to 0% at the start date. If one security has fewer data points (e.g., newer listing), the comparison starts from the first date where both have data.

6. **Multi-currency comparison**: when comparing securities in different currencies, both are converted to EUR using the `fx_rates` table before computing percentage changes.

7. **Chart performance**: for Max timeframe on long-history securities (20+ years of data), the API may downsample to weekly data points if the total exceeds 5000 points to maintain rendering performance. A "Downsampled to weekly" notice appears in the chart footer.

## Edge Cases

1. **New security with insufficient history**: if a security has fewer data points than the requested indicator period (e.g., 30 days of data but SMA 50 requested), the indicator line starts at the first computable point and a tooltip explains the gap.
2. **Crypto 24/7 data**: crypto securities have data for every day including weekends. The chart renders these without gaps, unlike stock charts.
3. **Delisted security**: if `securities.is_active = FALSE`, the chart renders all available historical data with a "DELISTED" badge in the header. No live price updates.
4. **Stock split in chart range**: if a split occurred within the visible timeframe, all pre-split prices are displayed as adjusted (using `adjusted_close_cents`). A split annotation marker appears on the time axis at the split date.
5. **Zero or extremely low volume days**: volume bars for days with zero volume are not rendered. Days with abnormally low volume (<10% of 20-day average) show a "Low volume" flag on hover.
6. **Multiple charts with same security**: allowed in multi-chart layout (e.g., same security with different timeframes or indicator configurations).
7. **Drawing persistence across sessions**: drawings stored in localStorage keyed by `securityId`. Clearing browser data removes all drawings. No server-side persistence.
8. **Comparison with missing overlap**: if two securities share zero overlapping trading dates (e.g., one only traded before the other was listed), display an error message instead of an empty chart.

## Acceptance Criteria

1. Candlestick chart renders correctly for all timeframes (1D through Max) with proper OHLC coloring and volume bars.
2. Line chart mode toggles cleanly and displays closing prices.
3. SMA 50/200, EMA, and Bollinger Bands render as overlays on the main chart with configurable parameters.
4. RSI and MACD render in separate panes below the main chart with correct reference lines and histogram.
5. Drawing tools (trend line, horizontal line, Fibonacci) work correctly, persist per security, and can be deleted.
6. Multi-chart layout switches between 1, 2, and 4 charts with independent security/indicator state per chart.
7. Comparison mode normalizes two securities to percentage change and handles multi-currency conversion.
8. Security selector provides typeahead search by ticker, name, or ISIN with results within 300ms.
9. Chart loads within 1 second for a 1Y timeframe on a security with full price history.
10. All price values display in the security's native currency with correct formatting per spec conventions.

## Changelog

| Date | Change |
|------|--------|
| 2026-03-19 | Initial draft |
