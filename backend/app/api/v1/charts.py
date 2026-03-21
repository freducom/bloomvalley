"""Charts API — price data with server-side technical indicators."""

from datetime import date, datetime, timezone
from typing import Optional

import numpy as np
import structlog
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from sqlalchemy import func

from app.db.engine import async_session
from app.db.models.holdings_snapshot import HoldingsSnapshot
from app.db.models.prices import Price
from app.db.models.securities import Security
from app.db.models.transactions import Transaction
from app.db.models.watchlists import Watchlist, WatchlistItem

logger = structlog.get_logger()

router = APIRouter()


def _sma(close: np.ndarray, period: int) -> list[float | None]:
    """Simple Moving Average."""
    result: list[float | None] = [None] * len(close)
    if len(close) < period:
        return result
    cumsum = np.cumsum(close)
    cumsum = np.insert(cumsum, 0, 0)
    for i in range(period - 1, len(close)):
        result[i] = float((cumsum[i + 1] - cumsum[i + 1 - period]) / period)
    return result


def _ema(close: np.ndarray, period: int) -> list[float | None]:
    """Exponential Moving Average."""
    result: list[float | None] = [None] * len(close)
    if len(close) < period:
        return result
    k = 2.0 / (period + 1)
    # Start EMA with SMA of first `period` values
    result[period - 1] = float(np.mean(close[:period]))
    for i in range(period, len(close)):
        result[i] = float(close[i] * k + result[i - 1] * (1 - k))  # type: ignore[operator]
    return result


def _bollinger(close: np.ndarray, period: int = 20, num_std: float = 2.0):
    """Bollinger Bands — returns (upper, middle, lower) lists."""
    middle = _sma(close, period)
    upper: list[float | None] = [None] * len(close)
    lower: list[float | None] = [None] * len(close)
    for i in range(period - 1, len(close)):
        window = close[i + 1 - period : i + 1]
        std = float(np.std(window, ddof=0))
        if middle[i] is not None:
            upper[i] = middle[i] + num_std * std
            lower[i] = middle[i] - num_std * std
    return upper, middle, lower


def _rsi(close: np.ndarray, period: int = 14) -> list[float | None]:
    """Relative Strength Index."""
    result: list[float | None] = [None] * len(close)
    if len(close) < period + 1:
        return result
    deltas = np.diff(close)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    avg_gain = float(np.mean(gains[:period]))
    avg_loss = float(np.mean(losses[:period]))

    if avg_loss == 0:
        result[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        result[period] = float(100 - 100 / (1 + rs))

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            result[i + 1] = 100.0
        else:
            rs = avg_gain / avg_loss
            result[i + 1] = float(100 - 100 / (1 + rs))

    return result


def _macd(
    close: np.ndarray,
    fast: int = 12,
    slow: int = 26,
    signal_period: int = 9,
):
    """MACD — returns (macd_line, signal_line, histogram) lists."""
    ema_fast = _ema(close, fast)
    ema_slow = _ema(close, slow)

    macd_line: list[float | None] = [None] * len(close)
    for i in range(len(close)):
        if ema_fast[i] is not None and ema_slow[i] is not None:
            macd_line[i] = ema_fast[i] - ema_slow[i]

    # Signal line = EMA of MACD line
    valid_macd = [(i, v) for i, v in enumerate(macd_line) if v is not None]
    signal_line: list[float | None] = [None] * len(close)
    histogram: list[float | None] = [None] * len(close)

    if len(valid_macd) >= signal_period:
        macd_vals = np.array([v for _, v in valid_macd])
        sig = _ema(macd_vals, signal_period)
        for j, (orig_idx, _) in enumerate(valid_macd):
            if sig[j] is not None:
                signal_line[orig_idx] = sig[j]
                histogram[orig_idx] = macd_line[orig_idx] - sig[j]  # type: ignore[operator]

    return macd_line, signal_line, histogram


@router.get("/{security_id}/ohlc")
async def get_ohlc(
    security_id: int,
    period: str = Query("1Y", description="1M, 3M, 6M, 1Y, 2Y, 5Y, MAX"),
    indicators: str = Query("", description="Comma-separated: sma20,sma50,ema20,bollinger,rsi,macd"),
):
    """Get OHLC price data with optional technical indicators."""
    async with async_session() as session:
        sec = await session.get(Security, security_id)
        if not sec:
            raise HTTPException(status_code=404, detail="Security not found")

        # Determine date range
        today = date.today()
        period_map = {
            "1M": 30,
            "3M": 90,
            "6M": 180,
            "1Y": 365,
            "2Y": 730,
            "5Y": 1825,
            "MAX": 36500,
        }
        days = period_map.get(period.upper(), 365)
        from_date = date.fromordinal(max(1, today.toordinal() - days))

        result = await session.execute(
            select(Price)
            .where(Price.security_id == security_id, Price.date >= from_date)
            .order_by(Price.date)
        )
        prices = result.scalars().all()

    if not prices:
        return {
            "data": {
                "security": {"id": sec.id, "ticker": sec.ticker, "name": sec.name, "currency": sec.currency},
                "candles": [],
                "indicators": {},
            },
            "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
        }

    # Build candle data (convert cents to decimal for charting)
    candles = []
    closes = []
    for p in prices:
        candle = {
            "time": p.date.isoformat(),
            "open": p.open_cents / 100 if p.open_cents else p.close_cents / 100,
            "high": p.high_cents / 100 if p.high_cents else p.close_cents / 100,
            "low": p.low_cents / 100 if p.low_cents else p.close_cents / 100,
            "close": p.close_cents / 100,
            "volume": p.volume,
        }
        candles.append(candle)
        closes.append(p.close_cents / 100)

    close_arr = np.array(closes)
    ind_list = [s.strip().lower() for s in indicators.split(",") if s.strip()]

    indicator_data: dict = {}

    for ind in ind_list:
        if ind.startswith("sma"):
            try:
                p = int(ind[3:])
            except ValueError:
                p = 20
            values = _sma(close_arr, p)
            indicator_data[ind] = [
                {"time": candles[i]["time"], "value": round(v, 4)} if v is not None else None
                for i, v in enumerate(values)
            ]

        elif ind.startswith("ema"):
            try:
                p = int(ind[3:])
            except ValueError:
                p = 20
            values = _ema(close_arr, p)
            indicator_data[ind] = [
                {"time": candles[i]["time"], "value": round(v, 4)} if v is not None else None
                for i, v in enumerate(values)
            ]

        elif ind == "bollinger":
            upper, middle, lower = _bollinger(close_arr)
            indicator_data["bollinger"] = {
                "upper": [
                    {"time": candles[i]["time"], "value": round(v, 4)} if v is not None else None
                    for i, v in enumerate(upper)
                ],
                "middle": [
                    {"time": candles[i]["time"], "value": round(v, 4)} if v is not None else None
                    for i, v in enumerate(middle)
                ],
                "lower": [
                    {"time": candles[i]["time"], "value": round(v, 4)} if v is not None else None
                    for i, v in enumerate(lower)
                ],
            }

        elif ind == "rsi":
            values = _rsi(close_arr)
            indicator_data["rsi"] = [
                {"time": candles[i]["time"], "value": round(v, 2)} if v is not None else None
                for i, v in enumerate(values)
            ]

        elif ind == "macd":
            macd_line, signal_line, hist = _macd(close_arr)
            indicator_data["macd"] = {
                "macd": [
                    {"time": candles[i]["time"], "value": round(v, 4)} if v is not None else None
                    for i, v in enumerate(macd_line)
                ],
                "signal": [
                    {"time": candles[i]["time"], "value": round(v, 4)} if v is not None else None
                    for i, v in enumerate(signal_line)
                ],
                "histogram": [
                    {"time": candles[i]["time"], "value": round(v, 4)} if v is not None else None
                    for i, v in enumerate(hist)
                ],
            }

    # Filter out None entries from indicator arrays
    for key in indicator_data:
        if isinstance(indicator_data[key], list):
            indicator_data[key] = [x for x in indicator_data[key] if x is not None]
        elif isinstance(indicator_data[key], dict):
            for subkey in indicator_data[key]:
                indicator_data[key][subkey] = [
                    x for x in indicator_data[key][subkey] if x is not None
                ]

    return {
        "data": {
            "security": {
                "id": sec.id,
                "ticker": sec.ticker,
                "name": sec.name,
                "currency": sec.currency,
            },
            "candles": candles,
            "indicators": indicator_data,
        },
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.get("/heatmap")
async def get_heatmap(
    source: str = Query("holdings", description="holdings, watchlist, or watchlist ID"),
    period: str = Query("1D", description="1D, 1W, 1M, 3M, 6M, 1Y, YTD"),
    watchlist_id: int | None = Query(None, alias="watchlistId"),
):
    """Heatmap data — % change per security for a given period and source.

    source=holdings: securities currently held in portfolio (weight = portfolio value)
    source=watchlist: all watchlist securities (weight = market cap proxy via volume * price)
    source=all: all securities with price data
    """
    from sqlalchemy import case as sa_case
    from decimal import Decimal
    from app.db.models.prices import FxRate

    async with async_session() as session:
        # Determine which securities to include
        security_ids: list[int] = []
        # Holdings weights: security_id -> market value in EUR cents
        holdings_weights: dict[int, int] = {}

        if source == "holdings":
            # Get net quantity per security from transactions
            result = await session.execute(
                select(
                    Transaction.security_id,
                    func.sum(
                        sa_case(
                            (Transaction.type.in_(["buy", "transfer_in"]), Transaction.quantity),
                            (Transaction.type.in_(["sell", "transfer_out"]), -Transaction.quantity),
                            else_=0,
                        )
                    ).label("net_qty"),
                )
                .where(Transaction.security_id.isnot(None))
                .group_by(Transaction.security_id)
                .having(
                    func.sum(
                        sa_case(
                            (Transaction.type.in_(["buy", "transfer_in"]), Transaction.quantity),
                            (Transaction.type.in_(["sell", "transfer_out"]), -Transaction.quantity),
                            else_=0,
                        )
                    ) > 0
                )
            )
            qty_rows = result.all()
            holdings_qty: dict[int, float] = {r[0]: float(r[1]) for r in qty_rows}
            security_ids = list(holdings_qty.keys())

        elif source == "watchlist":
            query = select(WatchlistItem.security_id)
            if watchlist_id:
                query = query.where(WatchlistItem.watchlist_id == watchlist_id)
            result = await session.execute(query)
            security_ids = list({r[0] for r in result.all()})

        else:  # "all"
            result = await session.execute(select(Security.id).where(Security.is_active == True))
            security_ids = [r[0] for r in result.all()]

        if not security_ids:
            return {
                "data": [],
                "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
            }

        # Determine lookback period
        today = date.today()
        if period == "YTD":
            from_date = date(today.year, 1, 1)
        else:
            period_days = {
                "1D": 5,
                "1W": 10,
                "1M": 35,
                "3M": 100,
                "6M": 200,
                "1Y": 370,
            }.get(period, 5)
            from_date = date.fromordinal(max(1, today.toordinal() - period_days))

        # Get prices for all securities in one go
        result = await session.execute(
            select(Price.security_id, Price.date, Price.close_cents, Price.volume)
            .where(Price.security_id.in_(security_ids), Price.date >= from_date)
            .order_by(Price.security_id, Price.date)
        )
        price_rows = result.all()

        # Group by security
        prices_by_sec: dict[int, list[tuple]] = {}
        for sid, dt, close, vol in price_rows:
            prices_by_sec.setdefault(sid, []).append((dt, close, vol))

        # Get security metadata
        result = await session.execute(
            select(Security).where(Security.id.in_(security_ids))
        )
        sec_map = {s.id: s for s in result.scalars().all()}

        # Get FX rates for EUR conversion
        fx_rates: dict[str, Decimal] = {"EUR": Decimal("1.0")}
        subq = (
            select(FxRate.quote_currency, func.max(FxRate.date).label("max_date"))
            .where(FxRate.base_currency == "EUR")
            .group_by(FxRate.quote_currency)
            .subquery()
        )
        fx_result = await session.execute(
            select(FxRate).join(
                subq,
                (FxRate.quote_currency == subq.c.quote_currency)
                & (FxRate.date == subq.c.max_date)
                & (FxRate.base_currency == "EUR"),
            )
        )
        for fx in fx_result.scalars().all():
            fx_rates[fx.quote_currency] = fx.rate

    # Calculate holdings weights (portfolio value in EUR cents)
    if source == "holdings":
        for sid, qty in holdings_qty.items():
            if sid in prices_by_sec and prices_by_sec[sid]:
                latest_price = prices_by_sec[sid][-1][1]  # close_cents
                sec = sec_map.get(sid)
                if sec:
                    fx = float(fx_rates.get(sec.currency, Decimal("1")))
                    value_eur = int(qty * latest_price / fx) if fx > 0 else int(qty * latest_price)
                    holdings_weights[sid] = value_eur

    # Calculate % change and build heatmap data
    heatmap_data = []
    for sid, price_list in prices_by_sec.items():
        if len(price_list) < 2:
            continue
        sec = sec_map.get(sid)
        if not sec:
            continue

        if period == "1D":
            end_price = price_list[-1][1]
            start_price = price_list[-2][1]
        elif period == "YTD":
            start_price = price_list[0][1]
            end_price = price_list[-1][1]
        else:
            start_price = price_list[0][1]
            end_price = price_list[-1][1]

        if start_price == 0:
            continue

        change_pct = round((end_price - start_price) / start_price * 100, 2)

        # Weight calculation
        if source == "holdings":
            # Weight = portfolio market value in EUR cents
            weight = holdings_weights.get(sid, 0)
        else:
            # Weight = market cap proxy: latest price * average daily volume
            # This gives relative sizing proportional to market cap
            volumes = [v for _, _, v in price_list if v and v > 0]
            avg_vol = sum(volumes) / len(volumes) if volumes else 1
            weight = int(end_price * avg_vol)

        heatmap_data.append({
            "securityId": sid,
            "ticker": sec.ticker,
            "name": sec.name,
            "sector": sec.sector,
            "assetClass": sec.asset_class,
            "currency": sec.currency,
            "currentPriceCents": end_price,
            "changePct": change_pct,
            "startPriceCents": start_price,
            "endPriceCents": end_price,
            "weight": weight,
        })

    # Sort by weight descending (largest positions first)
    heatmap_data.sort(key=lambda x: x["weight"], reverse=True)

    return {
        "data": heatmap_data,
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }
