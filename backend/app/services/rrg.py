"""Relative Rotation Graph (F23).

Computes JdK-style RS-Ratio and RS-Momentum for the 11 GICS sectors versus SPY,
identifies quadrant transitions over the last 4 weekly bars, and (for movers)
lists top watchlist ETFs by dollar-volume and top watchlist stocks by market cap.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.engine import async_session
from app.db.models.fundamentals import SecurityFundamentals
from app.db.models.prices import Price
from app.db.models.securities import Security
from app.db.models.watchlists import WatchlistItem

BENCHMARK_TICKER = "SPY"

SECTOR_ETFS: dict[str, str] = {
    "XLK": "Information Technology",
    "XLF": "Financials",
    "XLE": "Energy",
    "XLV": "Health Care",
    "XLY": "Consumer Discretionary",
    "XLP": "Consumer Staples",
    "XLI": "Industrials",
    "XLB": "Materials",
    "XLU": "Utilities",
    "XLRE": "Real Estate",
    "XLC": "Communication Services",
}


@dataclass
class SectorRow:
    sector: str
    ticker: str
    name: str
    rs_ratio: float
    rs_momentum: float
    quadrant: str
    quadrant_4w_ago: Optional[str]
    signal: Optional[str]  # "buy" | "sell" | "moved" | None
    tail: list[dict]  # [{date, rsRatio, rsMomentum}]


def _quadrant(rs_ratio: float, rs_momentum: float) -> str:
    """Classify a (rs-ratio, rs-momentum) point into one of the 4 quadrants."""
    if rs_ratio >= 100 and rs_momentum >= 100:
        return "Leading"
    if rs_ratio >= 100 and rs_momentum < 100:
        return "Weakening"
    if rs_ratio < 100 and rs_momentum < 100:
        return "Lagging"
    return "Improving"


def _signal(prev: Optional[str], curr: str) -> Optional[str]:
    """Buy: Improving → Leading. Sell: Weakening → Lagging. Any other change → 'moved'."""
    if prev is None or prev == curr:
        return None
    if prev == "Improving" and curr == "Leading":
        return "buy"
    if prev == "Weakening" and curr == "Lagging":
        return "sell"
    return "moved"


def _resample_weekly(dates: list[date], closes: np.ndarray) -> tuple[list[date], np.ndarray]:
    """Take the last close of each ISO week. Assumes `dates` is sorted ascending."""
    if len(dates) == 0:
        return [], np.array([])
    week_key = [(d.isocalendar().year, d.isocalendar().week) for d in dates]
    out_dates: list[date] = []
    out_closes: list[float] = []
    for i in range(len(dates)):
        is_last_in_week = (i == len(dates) - 1) or week_key[i] != week_key[i + 1]
        if is_last_in_week:
            out_dates.append(dates[i])
            out_closes.append(float(closes[i]))
    return out_dates, np.array(out_closes)


def _sma(arr: np.ndarray, window: int) -> np.ndarray:
    """Simple moving average; first (window-1) values are NaN."""
    result = np.full(len(arr), np.nan)
    if len(arr) < window:
        return result
    cumsum = np.cumsum(arr)
    cumsum = np.insert(cumsum, 0, 0.0)
    result[window - 1:] = (cumsum[window:] - cumsum[:-window]) / window
    return result


def _compute_rrg_series(
    sector_dates: list[date],
    sector_closes: np.ndarray,
    bench_dates: list[date],
    bench_closes: np.ndarray,
    weeks: int,
) -> tuple[list[date], np.ndarray, np.ndarray]:
    """Align sector to benchmark on shared weekly dates, then compute RS-Ratio & RS-Momentum.

    Returns (aligned_dates, rs_ratio, rs_momentum). Arrays are same length; early
    values will be NaN until enough history exists (2 * weeks bars).
    """
    bench_by_date = {d: c for d, c in zip(bench_dates, bench_closes)}
    aligned_dates: list[date] = []
    ratio: list[float] = []
    for d, c in zip(sector_dates, sector_closes):
        b = bench_by_date.get(d)
        if b is None or b == 0:
            continue
        aligned_dates.append(d)
        ratio.append(c / b)
    rs = np.array(ratio)
    sma_rs = _sma(rs, weeks)
    with np.errstate(divide="ignore", invalid="ignore"):
        rs_ratio = 100.0 * rs / sma_rs
    sma_rs_ratio = _sma(np.where(np.isnan(rs_ratio), 0.0, rs_ratio), weeks)
    # Mask sma_rs_ratio where the underlying window still contains NaNs (early)
    valid_from = 2 * weeks - 1
    sma_rs_ratio[:valid_from] = np.nan
    with np.errstate(divide="ignore", invalid="ignore"):
        rs_momentum = 100.0 * rs_ratio / sma_rs_ratio
    return aligned_dates, rs_ratio, rs_momentum


async def compute_rrg(weeks: int = 14, tail: int = 4) -> dict:
    """Compute the full RRG payload."""
    async with async_session() as session:
        # Load benchmark + sector ETF securities
        needed_tickers = [BENCHMARK_TICKER] + list(SECTOR_ETFS.keys())
        result = await session.execute(
            select(Security).where(
                Security.ticker.in_(needed_tickers),
                Security.asset_class == "etf",
            )
        )
        sec_by_ticker: dict[str, Security] = {s.ticker: s for s in result.scalars().all()}

        missing = [t for t in needed_tickers if t not in sec_by_ticker]
        if missing:
            return {"error": "missing_securities", "missing": missing}

        # We need at least ~2*weeks weekly bars → pull ~2.5 years of daily data
        # to be safe (holidays / partial weeks / gaps).
        earliest = date.today() - timedelta(days=int((2 * weeks + tail + 4) * 8))

        # Fetch daily closes for all needed tickers in one query
        sec_ids = [s.id for s in sec_by_ticker.values()]
        price_result = await session.execute(
            select(Price.security_id, Price.date, Price.close_cents)
            .where(Price.security_id.in_(sec_ids), Price.date >= earliest)
            .order_by(Price.security_id, Price.date)
        )
        by_sec: dict[int, list[tuple[date, int]]] = {sid: [] for sid in sec_ids}
        for sid, d, c in price_result.all():
            by_sec[sid].append((d, c))

        # Benchmark weekly series
        bench_sec = sec_by_ticker[BENCHMARK_TICKER]
        bench_rows = by_sec.get(bench_sec.id, [])
        if len(bench_rows) < 2 * weeks:
            return {
                "error": "insufficient_history",
                "missing": [BENCHMARK_TICKER],
                "detail": f"SPY has only {len(bench_rows)} daily bars — need weekly history for {2 * weeks} bars.",
            }
        bench_dates_d = [r[0] for r in bench_rows]
        bench_closes_d = np.array([r[1] / 100.0 for r in bench_rows])
        bench_wk_dates, bench_wk_closes = _resample_weekly(bench_dates_d, bench_closes_d)

        insufficient: list[str] = []
        sectors_out: list[SectorRow] = []

        for etf_ticker, gics_sector in SECTOR_ETFS.items():
            sec = sec_by_ticker[etf_ticker]
            rows = by_sec.get(sec.id, [])
            if len(rows) < 2 * weeks:
                insufficient.append(etf_ticker)
                continue

            d_list = [r[0] for r in rows]
            c_list = np.array([r[1] / 100.0 for r in rows])
            wk_dates, wk_closes = _resample_weekly(d_list, c_list)

            aligned_dates, rs_ratio, rs_momentum = _compute_rrg_series(
                wk_dates, wk_closes, bench_wk_dates, bench_wk_closes, weeks
            )
            # Find last index with valid RS-Momentum
            valid_mask = ~(np.isnan(rs_ratio) | np.isnan(rs_momentum))
            if not valid_mask.any():
                insufficient.append(etf_ticker)
                continue
            last_valid = int(np.where(valid_mask)[0].max())
            if last_valid < 4:  # need at least 4 weekly bars for comparison
                insufficient.append(etf_ticker)
                continue

            curr_ratio = float(rs_ratio[last_valid])
            curr_mom = float(rs_momentum[last_valid])
            curr_quad = _quadrant(curr_ratio, curr_mom)

            prev_idx = last_valid - 4
            prev_quad = None
            if prev_idx >= 0 and valid_mask[prev_idx]:
                prev_quad = _quadrant(float(rs_ratio[prev_idx]), float(rs_momentum[prev_idx]))

            sig = _signal(prev_quad, curr_quad)

            # Build the tail (last `tail` weekly points, oldest → newest)
            tail_start = max(0, last_valid - tail + 1)
            tail_rows = []
            for i in range(tail_start, last_valid + 1):
                if not valid_mask[i]:
                    continue
                tail_rows.append({
                    "date": aligned_dates[i].isoformat(),
                    "rsRatio": round(float(rs_ratio[i]), 3),
                    "rsMomentum": round(float(rs_momentum[i]), 3),
                })

            sectors_out.append(SectorRow(
                sector=gics_sector,
                ticker=etf_ticker,
                name=sec.name,
                rs_ratio=round(curr_ratio, 3),
                rs_momentum=round(curr_mom, 3),
                quadrant=curr_quad,
                quadrant_4w_ago=prev_quad,
                signal=sig,
                tail=tail_rows,
            ))

        # Movers → holdings enrichment
        movers = [s for s in sectors_out if s.signal is not None]
        holdings_by_sector = await _load_watchlist_holdings_for_sectors(
            session, [s.sector for s in movers]
        )

        # Compose response
        payload_sectors = []
        for s in sectors_out:
            entry = {
                "sector": s.sector,
                "ticker": s.ticker,
                "name": s.name,
                "rsRatio": s.rs_ratio,
                "rsMomentum": s.rs_momentum,
                "quadrant": s.quadrant,
                "quadrant4wAgo": s.quadrant_4w_ago,
                "signal": s.signal,
                "tail": s.tail,
            }
            if s.signal is not None:
                sector_holdings = holdings_by_sector.get(s.sector, {"etfs": [], "stocks": []})
                entry["topEtfs"] = sector_holdings["etfs"]
                entry["topStocks"] = sector_holdings["stocks"]
            payload_sectors.append(entry)

        # Sort: signal sectors first (buy → sell → moved), then rest by rs-ratio desc
        signal_rank = {"buy": 0, "sell": 1, "moved": 2, None: 3}
        payload_sectors.sort(key=lambda e: (signal_rank[e["signal"]], -e["rsRatio"]))

        as_of = bench_wk_dates[-1].isoformat() if bench_wk_dates else None

        return {
            "asOf": as_of,
            "benchmark": {"ticker": bench_sec.ticker, "name": bench_sec.name},
            "sectors": payload_sectors,
            "insufficientHistory": insufficient,
        }


async def _load_watchlist_holdings_for_sectors(
    session, sectors: list[str]
) -> dict[str, dict[str, list[dict]]]:
    """For each GICS sector, return top 3 watchlist ETFs (by avg $-volume, 30 sessions)
    and top 3 watchlist stocks (by market cap)."""
    if not sectors:
        return {}

    # All watchlist security IDs whose security.sector is in the given list
    result = await session.execute(
        select(Security)
        .join(WatchlistItem, WatchlistItem.security_id == Security.id)
        .where(Security.sector.in_(sectors))
        .options(selectinload(Security.fundamentals))
        .distinct()
    )
    securities = list(result.scalars().unique().all())
    if not securities:
        return {s: {"etfs": [], "stocks": []} for s in sectors}

    # For ETFs, compute avg dollar-volume over last 30 sessions.
    etf_secs = [s for s in securities if s.asset_class == "etf"]
    etf_dollar_vol: dict[int, float] = {}
    if etf_secs:
        thirty_ago = date.today() - timedelta(days=45)  # session gaps
        pv_result = await session.execute(
            select(Price.security_id, Price.close_cents, Price.volume)
            .where(Price.security_id.in_([s.id for s in etf_secs]), Price.date >= thirty_ago)
        )
        totals: dict[int, tuple[float, int]] = {}
        for sid, cc, vol in pv_result.all():
            if vol is None or vol == 0:
                continue
            dv = (cc / 100.0) * float(vol)
            t, n = totals.get(sid, (0.0, 0))
            totals[sid] = (t + dv, n + 1)
        for sid, (t, n) in totals.items():
            if n > 0:
                etf_dollar_vol[sid] = t / n

    out: dict[str, dict[str, list[dict]]] = {s: {"etfs": [], "stocks": []} for s in sectors}

    for sector in sectors:
        sector_secs = [s for s in securities if s.sector == sector]
        etfs = [s for s in sector_secs if s.asset_class == "etf"]
        stocks = [s for s in sector_secs if s.asset_class == "stock"]

        etf_ranked = sorted(
            [(s, etf_dollar_vol.get(s.id, 0.0)) for s in etfs],
            key=lambda x: -x[1],
        )[:3]
        stock_ranked = sorted(
            [(s, (s.fundamentals.market_cap_cents if s.fundamentals and s.fundamentals.market_cap_cents else 0))
             for s in stocks],
            key=lambda x: -x[1],
        )[:3]

        out[sector]["etfs"] = [
            {
                "securityId": s.id,
                "ticker": s.ticker,
                "name": s.name,
                "avgDollarVolume": int(dv) if dv else None,
            }
            for s, dv in etf_ranked
        ]
        out[sector]["stocks"] = [
            {
                "securityId": s.id,
                "ticker": s.ticker,
                "name": s.name,
                "marketCapCents": int(mcap) if mcap else None,
            }
            for s, mcap in stock_ranked
        ]

    return out
