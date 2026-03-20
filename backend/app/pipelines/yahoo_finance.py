"""Yahoo Finance data pipeline — daily OHLCV prices for all active securities."""

import asyncio
import math
from datetime import date, timedelta
from typing import Any

import structlog
import yfinance as yf
from sqlalchemy import select, text

from app.db.engine import async_session
from app.db.models.securities import Security
from app.pipelines import register_pipeline
from app.pipelines.base import PipelineAdapter, RetryableError

logger = structlog.get_logger()

# Yahoo exchange code → MIC mapping
# Yahoo minor currency units → major currency + divisor
# GBp = British pence (1 GBP = 100 GBp), ILA = Israeli agorot (1 ILS = 100 ILA)
MINOR_CURRENCY_MAP = {
    "GBp": ("GBP", 100),
    "GBX": ("GBP", 100),
    "ILA": ("ILS", 100),
    "ZAc": ("ZAR", 100),
}

YAHOO_TO_MIC = {
    "NMS": "XNAS",
    "NGM": "XNAS",
    "NCM": "XNAS",
    "NYQ": "XNYS",
    "GER": "XFRA",
    "HEL": "XHEL",
    "LSE": "XLON",
    "PAR": "XPAR",
    "AMS": "XAMS",
    "STO": "XSTO",
    "CPH": "XCSE",
    "EBS": "XSWX",
    "SWX": "XSWX",
}

# MIC → Yahoo ticker suffix
MIC_TO_SUFFIX = {
    "XHEL": ".HE",
    "XSTO": ".ST",
    "XFRA": ".DE",
    "XLON": ".L",
    "XPAR": ".PA",
    "XAMS": ".AS",
    "XCSE": ".CO",
    "XSWX": ".SW",
    # US exchanges have no suffix
    "XNAS": "",
    "XNYS": "",
}


def _build_yahoo_ticker(ticker: str, exchange: str | None, asset_class: str) -> str:
    """Build the Yahoo Finance ticker symbol from our DB ticker + exchange."""
    if asset_class == "crypto":
        return f"{ticker}-USD"

    # If ticker already contains a suffix (e.g. NOK1V.HE), use as-is
    if "." in ticker and exchange:
        return ticker

    # Append suffix based on exchange
    if exchange and exchange in MIC_TO_SUFFIX:
        suffix = MIC_TO_SUFFIX[exchange]
        if suffix and not ticker.endswith(suffix):
            return f"{ticker}{suffix}"

    return ticker


@register_pipeline
class YahooFinancePrices(PipelineAdapter):
    """Fetches daily OHLCV prices from Yahoo Finance for all active securities."""

    @property
    def source_name(self) -> str:
        return "yahoo_finance"

    @property
    def pipeline_name(self) -> str:
        return "yahoo_daily_prices"

    async def fetch(
        self,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch prices for all active securities using yfinance batch download."""
        # Load securities from DB
        async with async_session() as session:
            result = await session.execute(
                select(Security).where(Security.is_active.is_(True))
            )
            securities = result.scalars().all()

        if not securities:
            return []

        # Build ticker mapping: yahoo_ticker -> security
        ticker_map: dict[str, Security] = {}
        for sec in securities:
            yahoo_ticker = _build_yahoo_ticker(sec.ticker, sec.exchange, sec.asset_class)
            ticker_map[yahoo_ticker] = sec

        # Determine date range
        if from_date is None:
            from_date = date.today() - timedelta(days=7)
        if to_date is None:
            to_date = date.today()

        # yfinance end date is exclusive, add 1 day
        end_str = (to_date + timedelta(days=1)).isoformat()
        start_str = from_date.isoformat()

        yahoo_tickers = list(ticker_map.keys())

        logger.info(
            "yahoo_fetch_start",
            tickers=len(yahoo_tickers),
            from_date=start_str,
            to_date=to_date.isoformat(),
        )

        # Detect Yahoo currency per ticker (for GBp/ILA handling)
        yahoo_currencies: dict[str, str] = {}
        for ticker in yahoo_tickers:
            try:
                info = await asyncio.to_thread(lambda t=ticker: yf.Ticker(t).info)
                yc = info.get("currency", "")
                if yc:
                    yahoo_currencies[ticker] = yc
            except Exception:
                pass
            await asyncio.sleep(0.1)

        # Fetch in batches to avoid overloading
        raw_records: list[dict[str, Any]] = []
        batch_size = 20

        for i in range(0, len(yahoo_tickers), batch_size):
            batch = yahoo_tickers[i : i + batch_size]
            try:
                data = await asyncio.to_thread(
                    yf.download,
                    tickers=batch,
                    start=start_str,
                    end=end_str,
                    auto_adjust=False,
                    threads=False,
                    progress=False,
                )
            except Exception as e:
                raise RetryableError(f"yfinance download failed: {e}") from e

            if data is None or data.empty:
                continue

            def _make_record(ticker, sec, idx, row):
                price_date = idx.date() if hasattr(idx, "date") else idx
                yahoo_ccy = yahoo_currencies.get(ticker, sec.currency)
                minor = MINOR_CURRENCY_MAP.get(yahoo_ccy)
                divisor = minor[1] if minor else 1
                currency = minor[0] if minor else yahoo_ccy

                def adj(v):
                    """Adjust value from minor to major currency unit."""
                    if v is None:
                        return None
                    return v / divisor if divisor != 1 else v

                return {
                    "security_id": sec.id,
                    "ticker": ticker,
                    "date": price_date,
                    "open": adj(row.get("Open")),
                    "high": adj(row.get("High")),
                    "low": adj(row.get("Low")),
                    "close": adj(row.get("Close")),
                    "adj_close": adj(row.get("Adj Close")),
                    "volume": row.get("Volume"),
                    "currency": currency,
                }

            # Handle single vs multi-ticker response
            if len(batch) == 1:
                ticker = batch[0]
                sec = ticker_map[ticker]
                for idx, row in data.iterrows():
                    raw_records.append(_make_record(ticker, sec, idx, row))
            else:
                # Multi-ticker: columns are MultiIndex (field, ticker)
                if hasattr(data.columns, "levels"):
                    for ticker in batch:
                        if ticker not in data.columns.get_level_values(1):
                            continue
                        sec = ticker_map[ticker]
                        ticker_data = data.xs(ticker, level=1, axis=1)
                        for idx, row in ticker_data.iterrows():
                            raw_records.append(_make_record(ticker, sec, idx, row))
                else:
                    # Fallback: single ticker returned despite batch
                    ticker = batch[0]
                    sec = ticker_map[ticker]
                    for idx, row in data.iterrows():
                        raw_records.append(_make_record(ticker, sec, idx, row))

            # Rate limiting: 200ms delay between batches
            await asyncio.sleep(0.2)

        logger.info("yahoo_fetch_complete", records=len(raw_records))
        return raw_records

    async def validate(
        self, raw_records: list[dict]
    ) -> tuple[list[dict], list[str]]:
        """Validate price records per spec rules."""
        valid = []
        errors = []
        today = date.today()

        for rec in raw_records:
            ticker = rec.get("ticker", "?")
            rec_date = rec.get("date")

            # close is required
            close = rec.get("close")
            if close is None or (isinstance(close, float) and math.isnan(close)):
                errors.append(f"{ticker} {rec_date}: missing close price")
                continue

            if close <= 0:
                errors.append(f"{ticker} {rec_date}: close <= 0 ({close})")
                continue

            # Date not in the future (1-day tolerance for timezone differences)
            if rec_date and rec_date > today + timedelta(days=1):
                errors.append(f"{ticker} {rec_date}: date in the future")
                continue

            # OHLC sanity checks
            o = rec.get("open")
            h = rec.get("high")
            low = rec.get("low")
            c = close

            # Clean NaN values
            def clean(v):
                if v is None:
                    return None
                if isinstance(v, float) and math.isnan(v):
                    return None
                return v

            rec["open"] = clean(o)
            rec["high"] = clean(h)
            rec["low"] = clean(low)
            rec["adj_close"] = clean(rec.get("adj_close"))

            vol = rec.get("volume")
            if vol is not None:
                if isinstance(vol, float) and (math.isnan(vol) or vol < 0):
                    rec["volume"] = None
                else:
                    rec["volume"] = int(vol)

            h_val = rec["high"]
            l_val = rec["low"]

            if h_val is not None and l_val is not None and h_val < l_val:
                errors.append(f"{ticker} {rec_date}: high < low ({h_val} < {l_val})")
                continue

            valid.append(rec)

        return valid, errors

    async def transform(self, valid_records: list[dict]) -> list[dict]:
        """Convert float prices to integer cents and enforce OHLC constraints."""
        transformed = []

        for rec in valid_records:
            def to_cents(v):
                if v is None:
                    return None
                return round(float(v) * 100)

            open_cents = to_cents(rec.get("open"))
            high_cents = to_cents(rec.get("high"))
            low_cents = to_cents(rec.get("low"))
            close_cents = to_cents(rec["close"])

            if close_cents is not None and close_cents <= 0:
                close_cents = 1  # Penny stock minimum

            # Fix OHLC constraint violations from rounding
            # DB constraint: high >= low, high >= open, high >= close,
            #                low <= open, low <= close
            all_vals = [v for v in [open_cents, high_cents, low_cents, close_cents] if v is not None]
            if all_vals:
                actual_high = max(all_vals)
                actual_low = min(all_vals)
                if high_cents is not None:
                    high_cents = actual_high
                if low_cents is not None:
                    low_cents = actual_low

            transformed.append(
                {
                    "security_id": rec["security_id"],
                    "date": rec["date"],
                    "open_cents": open_cents,
                    "high_cents": high_cents,
                    "low_cents": low_cents,
                    "close_cents": close_cents,
                    "adjusted_close_cents": to_cents(rec.get("adj_close")),
                    "volume": rec.get("volume"),
                    "currency": rec["currency"],
                    "source": "yahoo_finance",
                }
            )

        return transformed

    async def load(self, transformed_records: list[dict]) -> int:
        """Upsert prices using ON CONFLICT DO UPDATE."""
        if not transformed_records:
            return 0

        upsert_sql = text("""
            INSERT INTO prices (
                security_id, date, open_cents, high_cents, low_cents,
                close_cents, adjusted_close_cents, volume, currency, source
            ) VALUES (
                :security_id, :date, :open_cents, :high_cents, :low_cents,
                :close_cents, :adjusted_close_cents, :volume, :currency, :source
            )
            ON CONFLICT (security_id, date) DO UPDATE SET
                open_cents = EXCLUDED.open_cents,
                high_cents = EXCLUDED.high_cents,
                low_cents = EXCLUDED.low_cents,
                close_cents = EXCLUDED.close_cents,
                adjusted_close_cents = EXCLUDED.adjusted_close_cents,
                volume = EXCLUDED.volume,
                currency = EXCLUDED.currency,
                source = EXCLUDED.source
        """)

        rows_affected = 0
        async with async_session() as session:
            for rec in transformed_records:
                await session.execute(upsert_sql, rec)
                rows_affected += 1
            await session.commit()

        logger.info("yahoo_prices_loaded", rows=rows_affected)
        return rows_affected
