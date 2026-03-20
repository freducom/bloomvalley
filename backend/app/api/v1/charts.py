"""Charts API — price data with server-side technical indicators."""

from datetime import date, datetime, timezone
from typing import Optional

import numpy as np
import structlog
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.db.engine import async_session
from app.db.models.prices import Price
from app.db.models.securities import Security

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
