"""Technical analysis endpoints — indicators, signals, and summaries."""

from datetime import date, datetime, timezone

import numpy as np
import structlog
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.db.engine import async_session
from app.db.models.prices import Price
from app.db.models.securities import Security
from app.services.technical import (
    bollinger,
    ema,
    find_support_resistance,
    generate_signals,
    macd,
    rsi,
    sma,
    vwap,
)

logger = structlog.get_logger()

router = APIRouter()

PERIOD_DAYS = {
    "1M": 30,
    "3M": 90,
    "6M": 180,
    "1Y": 365,
    "2Y": 730,
    "5Y": 1825,
    "MAX": 36500,
}


async def _load_prices(security_id: int, period: str):
    """Load price rows for a security and period. Returns (security, rows)."""
    async with async_session() as session:
        sec = await session.get(Security, security_id)
        if not sec:
            raise HTTPException(status_code=404, detail="Security not found")

        today = date.today()
        days = PERIOD_DAYS.get(period.upper(), 365)
        from_date = date.fromordinal(max(1, today.toordinal() - days))

        result = await session.execute(
            select(Price)
            .where(Price.security_id == security_id, Price.date >= from_date)
            .order_by(Price.date)
        )
        rows = result.scalars().all()

    return sec, rows


def _nan_to_none(arr: np.ndarray) -> list[float | None]:
    """Convert numpy array to list, replacing NaN with None and rounding."""
    return [round(float(v), 4) if not np.isnan(v) else None for v in arr]


def _nan_to_none_rsi(arr: np.ndarray) -> list[float | None]:
    """Same as _nan_to_none but rounds to 2 decimals (for RSI)."""
    return [round(float(v), 2) if not np.isnan(v) else None for v in arr]


@router.get("/{security_id}/indicators")
async def get_indicators(
    security_id: int,
    period: str = Query("1Y", description="1M, 3M, 6M, 1Y, 2Y, 5Y, MAX"),
    indicators: str = Query("all", description="Comma-separated: sma,ema,rsi,macd,bollinger,vwap,sr — or 'all'"),
):
    """All technical indicators for a security."""
    sec, rows = await _load_prices(security_id, period)

    if not rows:
        raise HTTPException(status_code=404, detail="No price data for this security and period")

    logger.info(
        "technical.indicators",
        security_id=security_id,
        ticker=sec.ticker,
        period=period,
        data_points=len(rows),
    )

    # Extract arrays
    dates = [r.date.isoformat() for r in rows]
    closes = np.array([r.close_cents / 100.0 for r in rows])
    highs = np.array([(r.high_cents / 100.0 if r.high_cents else r.close_cents / 100.0) for r in rows])
    lows = np.array([(r.low_cents / 100.0 if r.low_cents else r.close_cents / 100.0) for r in rows])
    volumes = np.array([(r.volume or 0) for r in rows], dtype=np.float64)

    ind_set = {s.strip().lower() for s in indicators.split(",") if s.strip()}
    want_all = "all" in ind_set

    data: dict = {"dates": dates}

    # SMA
    if want_all or "sma" in ind_set:
        data["sma20"] = _nan_to_none(sma(closes, 20))
        data["sma50"] = _nan_to_none(sma(closes, 50))
        data["sma200"] = _nan_to_none(sma(closes, 200))

    # EMA
    if want_all or "ema" in ind_set:
        data["ema12"] = _nan_to_none(ema(closes, 12))
        data["ema26"] = _nan_to_none(ema(closes, 26))

    # RSI
    if want_all or "rsi" in ind_set:
        data["rsi"] = _nan_to_none_rsi(rsi(closes, 14))

    # MACD
    if want_all or "macd" in ind_set:
        macd_line, signal_line, histogram = macd(closes)
        data["macd"] = {
            "line": _nan_to_none(macd_line),
            "signal": _nan_to_none(signal_line),
            "histogram": _nan_to_none(histogram),
        }

    # Bollinger
    if want_all or "bollinger" in ind_set:
        bb_upper, bb_middle, bb_lower = bollinger(closes)
        data["bollinger"] = {
            "upper": _nan_to_none(bb_upper),
            "middle": _nan_to_none(bb_middle),
            "lower": _nan_to_none(bb_lower),
        }

    # VWAP
    if want_all or "vwap" in ind_set:
        data["vwap"] = _nan_to_none(vwap(highs, lows, closes, volumes))

    # Support / Resistance
    if want_all or "sr" in ind_set:
        sr = find_support_resistance(closes)
        data["supportResistance"] = {
            "support": [s["price"] for s in sr["support"]],
            "resistance": [r["price"] for r in sr["resistance"]],
        }

    # Signals (always include with 'all')
    signals = []
    if want_all:
        signals = generate_signals(closes, volumes, dates)

    return {
        "data": data,
        "signals": signals,
        "meta": {
            "securityId": sec.id,
            "ticker": sec.ticker,
            "period": period,
            "dataPoints": len(rows),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    }


@router.get("/{security_id}/signals")
async def get_signals(
    security_id: int,
    period: str = Query("1Y", description="1M, 3M, 6M, 1Y, 2Y, 5Y, MAX"),
):
    """Current trading signals for a security."""
    sec, rows = await _load_prices(security_id, period)

    if not rows:
        raise HTTPException(status_code=404, detail="No price data for this security and period")

    logger.info(
        "technical.signals",
        security_id=security_id,
        ticker=sec.ticker,
        data_points=len(rows),
    )

    dates = [r.date.isoformat() for r in rows]
    closes = np.array([r.close_cents / 100.0 for r in rows])
    volumes = np.array([(r.volume or 0) for r in rows], dtype=np.float64)

    signals = generate_signals(closes, volumes, dates)

    return {
        "data": signals,
        "meta": {
            "securityId": sec.id,
            "ticker": sec.ticker,
            "period": period,
            "dataPoints": len(rows),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    }


@router.get("/{security_id}/summary")
async def get_summary(
    security_id: int,
    period: str = Query("1Y", description="1M, 3M, 6M, 1Y, 2Y, 5Y, MAX"),
):
    """Quick technical summary — trend, RSI, MACD status, MA alignment."""
    sec, rows = await _load_prices(security_id, period)

    if not rows:
        raise HTTPException(status_code=404, detail="No price data for this security and period")

    logger.info(
        "technical.summary",
        security_id=security_id,
        ticker=sec.ticker,
        data_points=len(rows),
    )

    closes = np.array([r.close_cents / 100.0 for r in rows])
    current_price = closes[-1]

    # RSI
    rsi_vals = rsi(closes, 14)
    valid_rsi = rsi_vals[~np.isnan(rsi_vals)]
    rsi_reading = round(float(valid_rsi[-1]), 2) if len(valid_rsi) > 0 else None
    rsi_status = "neutral"
    if rsi_reading is not None:
        if rsi_reading > 70:
            rsi_status = "overbought"
        elif rsi_reading < 30:
            rsi_status = "oversold"

    # MACD
    macd_line, signal_line, histogram = macd(closes)
    valid_hist = histogram[~np.isnan(histogram)]
    macd_status = "neutral"
    if len(valid_hist) >= 2:
        if valid_hist[-1] > 0:
            macd_status = "bullish" if valid_hist[-1] > valid_hist[-2] else "bullish_weakening"
        else:
            macd_status = "bearish" if valid_hist[-1] < valid_hist[-2] else "bearish_weakening"

    # Moving average alignment
    sma20_val = _last_valid_np(sma(closes, 20))
    sma50_val = _last_valid_np(sma(closes, 50))
    sma200_val = _last_valid_np(sma(closes, 200))

    ma_alignment = "mixed"
    if sma20_val and sma50_val and sma200_val:
        if current_price > sma20_val > sma50_val > sma200_val:
            ma_alignment = "bullish"
        elif current_price < sma20_val < sma50_val < sma200_val:
            ma_alignment = "bearish"

    # Overall trend determination
    bullish_count = 0
    bearish_count = 0

    if rsi_status == "oversold":
        bullish_count += 1
    elif rsi_status == "overbought":
        bearish_count += 1

    if macd_status.startswith("bullish"):
        bullish_count += 1
    elif macd_status.startswith("bearish"):
        bearish_count += 1

    if ma_alignment == "bullish":
        bullish_count += 1
    elif ma_alignment == "bearish":
        bearish_count += 1

    if bullish_count > bearish_count:
        trend = "bullish"
    elif bearish_count > bullish_count:
        trend = "bearish"
    else:
        trend = "neutral"

    return {
        "data": {
            "trend": trend,
            "currentPrice": round(current_price, 4),
            "rsi": {
                "value": rsi_reading,
                "status": rsi_status,
            },
            "macd": {
                "status": macd_status,
                "histogram": round(float(valid_hist[-1]), 4) if len(valid_hist) > 0 else None,
            },
            "movingAverages": {
                "alignment": ma_alignment,
                "sma20": round(sma20_val, 4) if sma20_val else None,
                "sma50": round(sma50_val, 4) if sma50_val else None,
                "sma200": round(sma200_val, 4) if sma200_val else None,
                "priceVsSma20": _pct_diff(current_price, sma20_val),
                "priceVsSma50": _pct_diff(current_price, sma50_val),
                "priceVsSma200": _pct_diff(current_price, sma200_val),
            },
        },
        "meta": {
            "securityId": sec.id,
            "ticker": sec.ticker,
            "period": period,
            "dataPoints": len(rows),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    }


def _last_valid_np(arr: np.ndarray) -> float | None:
    """Return last non-NaN value or None."""
    valid = arr[~np.isnan(arr)]
    return float(valid[-1]) if len(valid) > 0 else None


def _pct_diff(price: float, reference: float | None) -> float | None:
    """Percentage difference of price vs reference."""
    if reference is None or reference == 0:
        return None
    return round((price - reference) / reference * 100, 2)
