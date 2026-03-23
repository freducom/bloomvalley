"""Live quotes endpoint — fetches current prices from Finnhub with Redis caching."""

import asyncio
import json
from datetime import datetime, timezone

import httpx
import structlog
from fastapi import APIRouter, Request

from app.config import settings
from app.db.engine import async_session
from app.db.models.securities import Security
from sqlalchemy import select

logger = structlog.get_logger()
router = APIRouter()

FINNHUB_BASE = "https://finnhub.io/api/v1"
CACHE_TTL = 300  # 5 minutes

# Map exchange suffixes to Finnhub-compatible tickers
_EXCHANGE_MAP = {
    ".HE": ".HE",   # Helsinki — Finnhub uses same
    ".ST": ".ST",   # Stockholm
    ".DE": ".DE",   # Frankfurt
    ".PA": ".PA",   # Paris
    ".L": ".L",     # London
    ".CO": ".CO",   # Copenhagen
    ".OL": ".OL",   # Oslo
}


def _to_finnhub_ticker(ticker: str) -> str:
    """Convert Yahoo-style ticker to Finnhub format."""
    # Most Yahoo tickers work directly with Finnhub
    # Crypto needs special handling
    if ticker.endswith("-USD"):
        return f"BINANCE:{ticker.replace('-USD', '')}USDT"
    return ticker


async def _fetch_quote(client: httpx.AsyncClient, ticker: str) -> dict | None:
    """Fetch a single quote from Finnhub."""
    fh_ticker = _to_finnhub_ticker(ticker)
    try:
        resp = await client.get(
            f"{FINNHUB_BASE}/quote",
            params={"symbol": fh_ticker, "token": settings.FINNHUB_API_KEY},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        # Finnhub returns c=0 for unknown tickers
        if not data or data.get("c", 0) == 0:
            return None
        return {
            "current": data["c"],       # Current price
            "change": data["d"],        # Change
            "changePercent": data["dp"], # Change %
            "high": data["h"],          # Day high
            "low": data["l"],           # Day low
            "open": data["o"],          # Day open
            "previousClose": data["pc"],# Previous close
            "timestamp": data.get("t", 0),
        }
    except Exception as e:
        logger.debug("finnhub_quote_error", ticker=ticker, error=str(e))
        return None


@router.get("/live")
async def get_live_quotes(request: Request):
    """Get current quotes for all held securities. Cached 5 min in Redis."""
    redis = request.app.state.redis
    cache_key = "quotes:live:all"

    # Check cache
    cached = await redis.get(cache_key)
    if cached:
        return json.loads(cached)

    # Load active held securities (those with transactions)
    async with async_session() as session:
        result = await session.execute(
            select(Security.id, Security.ticker, Security.name, Security.currency)
            .where(Security.is_active.is_(True))
            .where(Security.ticker.isnot(None))
        )
        securities = result.all()

    if not securities:
        return {"data": [], "meta": {"timestamp": datetime.now(timezone.utc).isoformat(), "cached": False}}

    # Fetch quotes in batches (respect 60/min rate limit)
    quotes = []
    async with httpx.AsyncClient() as client:
        # Process in batches of 10 with small delays
        batch_size = 10
        for i in range(0, len(securities), batch_size):
            batch = securities[i:i + batch_size]
            tasks = [_fetch_quote(client, sec.ticker) for sec in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for sec, result in zip(batch, results):
                if isinstance(result, Exception) or result is None:
                    continue
                quotes.append({
                    "securityId": sec.id,
                    "ticker": sec.ticker,
                    "name": sec.name,
                    "currency": sec.currency,
                    **result,
                })

            # Rate limit: ~10 per second is safe for 60/min
            if i + batch_size < len(securities):
                await asyncio.sleep(1.0)

    response = {
        "data": quotes,
        "meta": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cached": False,
            "count": len(quotes),
            "total": len(securities),
        },
    }

    # Cache for 5 minutes
    await redis.set(cache_key, json.dumps(response), ex=CACHE_TTL)

    return response


@router.get("/live/{ticker}")
async def get_single_quote(ticker: str, request: Request):
    """Get current quote for a single ticker."""
    redis = request.app.state.redis
    cache_key = f"quotes:live:{ticker}"

    cached = await redis.get(cache_key)
    if cached:
        return json.loads(cached)

    async with httpx.AsyncClient() as client:
        quote = await _fetch_quote(client, ticker)

    if not quote:
        return {
            "data": None,
            "meta": {"timestamp": datetime.now(timezone.utc).isoformat(), "error": "Quote not available"},
        }

    response = {
        "data": {"ticker": ticker, **quote},
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat(), "cached": False},
    }

    await redis.set(cache_key, json.dumps(response), ex=CACHE_TTL)
    return response
