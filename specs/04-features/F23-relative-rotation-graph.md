# F23: Sector Rotation (Relative Rotation Graph)

**Status: Implemented — 2026-07-21**
**Created: 2026-07-21**

A single-page view that plots the 11 GICS sectors on a 4-quadrant Relative Rotation Graph (RRG) versus SPY. Highlights sectors that have crossed quadrants over the past 4 weeks and, for each mover, surfaces the top tracked ETFs and stocks in that sector.

The aim is a quick weekly read on where money is rotating: which sectors are gaining leadership, which are losing it, and which of *my* watchlist securities sit in the moving sectors.

---

## 1. Universe

| Ticker | Name | Sector |
|---|---|---|
| SPY | SPDR S&P 500 ETF Trust | Benchmark |
| XLK | Technology Select Sector SPDR | Information Technology |
| XLF | Financial Select Sector SPDR | Financials |
| XLE | Energy Select Sector SPDR | Energy |
| XLV | Health Care Select Sector SPDR | Health Care |
| XLY | Consumer Discretionary Select Sector SPDR | Consumer Discretionary |
| XLP | Consumer Staples Select Sector SPDR | Consumer Staples |
| XLI | Industrial Select Sector SPDR | Industrials |
| XLB | Materials Select Sector SPDR | Materials |
| XLU | Utilities Select Sector SPDR | Utilities |
| XLRE | Real Estate Select Sector SPDR | Real Estate |
| XLC | Communication Services Select Sector SPDR | Communication Services |

All 12 are added to `backend/scripts/seed-securities.py` so `yahoo_daily_prices` populates history on the standard schedule.

---

## 2. Formula (JdK approximation)

Daily closes are resampled to weekly (Friday-close). For each sector ticker:

```
RS_t         = close_sector_t / close_SPY_t
RS_Ratio_t   = 100 * RS_t / SMA_14(RS_t)
RS_Mom_t     = 100 * RS_Ratio_t / SMA_14(RS_Ratio_t)
```

Both series are centered on 100. This is the widely-used open-source approximation of Julius de Kempenaer's proprietary JdK RS-Ratio / RS-Momentum. The window is 14 weekly bars (~14 weeks).

**Quadrants:**

| Quadrant | RS-Ratio | RS-Momentum | Meaning |
|---|---|---|---|
| Leading | > 100 | > 100 | Outperforming and accelerating |
| Weakening | > 100 | < 100 | Outperforming but losing momentum |
| Lagging | < 100 | < 100 | Underperforming and decelerating |
| Improving | < 100 | > 100 | Underperforming but gaining momentum |

**Canonical rotation** (clockwise): Improving → Leading → Weakening → Lagging → Improving.

## 3. Signal detection

For each sector, compare the quadrant at `t` vs `t − 4 weeks`:

- **BUY** — quadrant moved from `Improving` to `Leading` (RS-Ratio crossed up through 100 while momentum stayed above 100).
- **SELL** — quadrant moved from `Weakening` to `Lagging` (RS-Ratio crossed down through 100 while momentum stayed below 100).
- All other transitions are flagged as `moved` without a strong signal.

The response includes the tail of `(RS-Ratio, RS-Momentum)` for the last 4 weekly points so the UI can draw the trajectory.

## 4. "Top 3 tracked in this sector"

For each sector with a quadrant change, the endpoint returns:

- **Top 3 ETFs by average daily dollar-volume (last 30 sessions)** among `watchlist_items` where `asset_class = 'etf'` and `sector = <sector>`. Dollar volume = `close * volume`, averaged over available days.
- **Top 3 stocks by market cap** among `watchlist_items` where `asset_class = 'stock'` and `sector = <sector>`, joined to `security_fundamentals.market_cap_cents`. Stocks without a fundamentals row are skipped.

"Watchlist items" means the union across all watchlists (any security appearing in at least one watchlist).

## 5. API

### `GET /api/v1/rrg`

Query:
- `weeks` — window length. Default `14`.
- `tail` — number of trailing weekly points to return per sector. Default `4`.

Response:

```json
{
  "data": {
    "asOf": "2026-07-17",
    "benchmark": {"ticker": "SPY", "name": "SPDR S&P 500 ETF Trust"},
    "sectors": [
      {
        "sector": "Information Technology",
        "ticker": "XLK",
        "name": "Technology Select Sector SPDR",
        "rsRatio": 103.4,
        "rsMomentum": 101.2,
        "quadrant": "Leading",
        "quadrant4wAgo": "Improving",
        "signal": "buy",
        "tail": [
          {"date": "2026-06-26", "rsRatio": 99.1, "rsMomentum": 100.4},
          {"date": "2026-07-03", "rsRatio": 99.8, "rsMomentum": 100.7},
          {"date": "2026-07-10", "rsRatio": 100.9, "rsMomentum": 101.0},
          {"date": "2026-07-17", "rsRatio": 103.4, "rsMomentum": 101.2}
        ],
        "topEtfs": [
          {"ticker": "QQQ", "name": "Invesco QQQ Trust", "avgDollarVolume": 12345678900}
        ],
        "topStocks": [
          {"ticker": "MSFT", "name": "Microsoft Corporation", "marketCapCents": 350000000000000}
        ]
      }
    ]
  },
  "meta": {"timestamp": "...", "weeks": 14, "tail": 4}
}
```

`signal` is one of `"buy"`, `"sell"`, `"moved"`, `null` (no quadrant change).

## 6. Frontend

Route: `/rrg`. Sidebar link under "Analysis" labeled **"Sector Rotation"** (Compass icon).

- **Scatter (recharts)**: X = RS-Ratio, Y = RS-Momentum, quadrant guides at 100. Each sector rendered as a labeled dot; the 4-week tail drawn as a connecting line with an arrow at the current point.
- **Signals panel**: A small header with counts of BUY, SELL, MOVED sectors.
- **Movers list**: One card per sector with a quadrant change, showing the transition (`Improving → Leading`), the signal, and two small tables — Top 3 ETFs (by avg $-volume) and Top 3 Stocks (by market cap) in that sector from the user's watchlist.
- **InfoTip** tooltips on: "RRG", "RS-Ratio", "RS-Momentum", each quadrant name, and the signal criteria.
- Empty-state: if a sector has fewer than 14 + 4 weekly bars, it is omitted from the plot with a note.

## 7. Data dependencies

Requires daily prices for SPY + 11 sector ETFs. If any is missing on load, the endpoint returns 409 with the missing tickers listed so the user can trigger `yahoo_daily_prices`.

## 8. Non-goals (deferred)

- Custom benchmarks (SPY only for now).
- Sub-industry RRG (only the 11 GICS sectors).
- Historical snapshots / animation of the RRG over time.
- Alerts on quadrant transitions (a natural F22 event type follow-up).
