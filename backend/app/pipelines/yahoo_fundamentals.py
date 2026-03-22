"""Yahoo Finance fundamentals pipeline — fetches key financial metrics for all active stocks."""

import asyncio
from datetime import date
from typing import Any

import structlog
import yfinance as yf
from sqlalchemy import select, text

from app.db.engine import async_session
from app.db.models.securities import Security
from app.pipelines import register_pipeline
from app.pipelines.base import PipelineAdapter, RetryableError
from app.pipelines.yahoo_finance import _build_yahoo_ticker

logger = structlog.get_logger()

# Default tax rate for ROIC NOPAT calculation (Finnish corporate tax rate)
DEFAULT_TAX_RATE = 0.20


def _safe_get(info: dict, key: str, default=None):
    """Get a value from yfinance info dict, treating None and 'N/A' as missing."""
    val = info.get(key, default)
    if val is None or val == "N/A":
        return default
    return val


def _to_cents(value, currency: str = "USD") -> int | None:
    """Convert a monetary float value to integer cents."""
    if value is None:
        return None
    try:
        return round(float(value) * 100)
    except (ValueError, TypeError):
        return None


def _safe_decimal(value) -> float | None:
    """Convert a value to float, returning None if not possible."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _compute_roic(info: dict) -> float | None:
    """
    Compute ROIC (Return on Invested Capital).

    Preferred: EBIT * (1 - tax_rate) / (totalDebt + stockholdersEquity - totalCash)
    Fallback 1: returnOnAssets as proxy
    Fallback 2: returnOnEquity as proxy
    """
    ebit = _safe_get(info, "ebit")
    total_debt = _safe_get(info, "totalDebt")
    equity = _safe_get(info, "stockholdersEquity")
    total_cash = _safe_get(info, "totalCash")

    if ebit is not None and total_debt is not None and equity is not None:
        cash = total_cash if total_cash is not None else 0
        invested_capital = total_debt + equity - cash
        if invested_capital > 0:
            nopat = ebit * (1 - DEFAULT_TAX_RATE)
            return nopat / invested_capital

    # Fallback: returnOnAssets
    roa = _safe_get(info, "returnOnAssets")
    if roa is not None:
        return float(roa)

    # Fallback: returnOnEquity
    roe = _safe_get(info, "returnOnEquity")
    if roe is not None:
        return float(roe)

    return None


@register_pipeline
class YahooFundamentals(PipelineAdapter):
    """Fetches fundamental financial metrics from Yahoo Finance for all active stocks."""

    @property
    def source_name(self) -> str:
        return "yahoo_finance"

    @property
    def pipeline_name(self) -> str:
        return "yahoo_fundamentals"

    async def fetch(
        self,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch fundamental data for all active stock securities."""
        async with async_session() as session:
            result = await session.execute(
                select(Security).where(
                    Security.is_active.is_(True),
                    Security.asset_class == "stock",
                )
            )
            securities = result.scalars().all()

        if not securities:
            logger.info("yahoo_fundamentals_fetch_skip", reason="no active stocks")
            return []

        logger.info("yahoo_fundamentals_fetch_start", securities=len(securities))

        raw_records: list[dict[str, Any]] = []

        for sec in securities:
            yahoo_ticker = _build_yahoo_ticker(sec.ticker, sec.exchange, sec.asset_class)
            try:
                info = await asyncio.to_thread(lambda t=yahoo_ticker: yf.Ticker(t).info)
                if not info or info.get("regularMarketPrice") is None:
                    logger.warning(
                        "yahoo_fundamentals_no_data",
                        ticker=yahoo_ticker,
                        security_id=sec.id,
                    )
                    await asyncio.sleep(0.5)
                    continue

                raw_records.append(
                    {
                        "security_id": sec.id,
                        "ticker": yahoo_ticker,
                        "currency": sec.currency,
                        "info": info,
                    }
                )
            except Exception as e:
                logger.error(
                    "yahoo_fundamentals_fetch_error",
                    ticker=yahoo_ticker,
                    security_id=sec.id,
                    error=str(e),
                )

            # Rate limiting: 0.5s between tickers
            await asyncio.sleep(0.5)

        logger.info("yahoo_fundamentals_fetch_complete", records=len(raw_records))
        return raw_records

    async def validate(
        self, raw_records: list[dict]
    ) -> tuple[list[dict], list[str]]:
        """Validate fetched records — require at least one usable metric."""
        valid = []
        errors = []

        for rec in raw_records:
            ticker = rec.get("ticker", "?")
            info = rec.get("info", {})

            # Must have at least one fundamental metric to be useful
            has_any = any(
                _safe_get(info, key) is not None
                for key in [
                    "returnOnEquity",
                    "freeCashflow",
                    "priceToBook",
                    "trailingPE",
                    "marketCap",
                    "totalRevenue",
                    "trailingEps",
                    "dividendYield",
                    "grossMargins",
                    "operatingMargins",
                    "profitMargins",
                ]
            )

            if not has_any:
                errors.append(f"{ticker}: no fundamental metrics available")
                continue

            # Sanity checks on key ratios
            pe = _safe_get(info, "trailingPE")
            if pe is not None and (pe < 0 or pe > 10000):
                logger.warning("yahoo_fundamentals_pe_outlier", ticker=ticker, pe=pe)
                # Don't reject, just log — negative PE is legitimate for loss-making companies
                # but extreme values may indicate bad data

            pb = _safe_get(info, "priceToBook")
            if pb is not None and pb < 0:
                logger.warning("yahoo_fundamentals_pb_negative", ticker=ticker, pb=pb)
                # Negative P/B can happen with negative book value — keep it

            valid.append(rec)

        return valid, errors

    async def transform(self, valid_records: list[dict]) -> list[dict]:
        """Extract and compute fundamental metrics from raw yfinance info."""
        transformed = []

        for rec in valid_records:
            info = rec["info"]
            currency = rec["currency"]
            security_id = rec["security_id"]

            # Direct mappings
            roe = _safe_decimal(_safe_get(info, "returnOnEquity"))
            free_cash_flow = _safe_get(info, "freeCashflow")
            price_to_book = _safe_decimal(_safe_get(info, "priceToBook"))
            dividend_yield = _safe_decimal(_safe_get(info, "dividendYield"))
            trailing_eps = _safe_get(info, "trailingEps")
            total_revenue = _safe_get(info, "totalRevenue")
            gross_margin = _safe_decimal(_safe_get(info, "grossMargins"))
            operating_margin = _safe_decimal(_safe_get(info, "operatingMargins"))
            net_margin = _safe_decimal(_safe_get(info, "profitMargins"))
            pe_ratio = _safe_decimal(_safe_get(info, "trailingPE"))
            market_cap = _safe_get(info, "marketCap")

            # Computed: net_debt_ebitda
            total_debt = _safe_get(info, "totalDebt")
            total_cash = _safe_get(info, "totalCash")
            ebitda = _safe_get(info, "ebitda")
            net_debt_ebitda = None
            if total_debt is not None and total_cash is not None and ebitda is not None and ebitda != 0:
                net_debt_ebitda = (total_debt - total_cash) / ebitda

            # Computed: fcf_yield
            fcf_yield = None
            if free_cash_flow is not None and market_cap is not None and market_cap > 0:
                fcf_yield = free_cash_flow / market_cap

            # Computed: ROIC
            roic = _compute_roic(info)

            # WACC: cannot be reliably computed from yfinance alone
            wacc = None

            transformed.append(
                {
                    "security_id": security_id,
                    "roe": roe,
                    "free_cash_flow_cents": _to_cents(free_cash_flow, currency),
                    "fcf_currency": currency,
                    "fcf_yield": fcf_yield,
                    "net_debt_ebitda": net_debt_ebitda,
                    "price_to_book": price_to_book,
                    "dividend_yield": dividend_yield,
                    "eps_cents": _to_cents(trailing_eps, currency),
                    "revenue_cents": _to_cents(total_revenue, currency),
                    "gross_margin": gross_margin,
                    "operating_margin": operating_margin,
                    "net_margin": net_margin,
                    "pe_ratio": pe_ratio,
                    "market_cap_cents": _to_cents(market_cap, currency),
                    "roic": roic,
                    "wacc": wacc,
                }
            )

        return transformed

    async def load(self, transformed_records: list[dict]) -> int:
        """Upsert fundamentals into security_fundamentals using ON CONFLICT on security_id."""
        if not transformed_records:
            return 0

        upsert_sql = text("""
            INSERT INTO security_fundamentals (
                security_id, roe, free_cash_flow_cents, fcf_currency, fcf_yield,
                net_debt_ebitda, price_to_book, dividend_yield, eps_cents, revenue_cents,
                gross_margin, operating_margin, net_margin, pe_ratio, market_cap_cents,
                roic, wacc
            ) VALUES (
                :security_id, :roe, :free_cash_flow_cents, :fcf_currency, :fcf_yield,
                :net_debt_ebitda, :price_to_book, :dividend_yield, :eps_cents, :revenue_cents,
                :gross_margin, :operating_margin, :net_margin, :pe_ratio, :market_cap_cents,
                :roic, :wacc
            )
            ON CONFLICT (security_id) DO UPDATE SET
                roe = EXCLUDED.roe,
                free_cash_flow_cents = EXCLUDED.free_cash_flow_cents,
                fcf_currency = EXCLUDED.fcf_currency,
                fcf_yield = EXCLUDED.fcf_yield,
                net_debt_ebitda = EXCLUDED.net_debt_ebitda,
                price_to_book = EXCLUDED.price_to_book,
                dividend_yield = EXCLUDED.dividend_yield,
                eps_cents = EXCLUDED.eps_cents,
                revenue_cents = EXCLUDED.revenue_cents,
                gross_margin = EXCLUDED.gross_margin,
                operating_margin = EXCLUDED.operating_margin,
                net_margin = EXCLUDED.net_margin,
                pe_ratio = EXCLUDED.pe_ratio,
                market_cap_cents = EXCLUDED.market_cap_cents,
                roic = EXCLUDED.roic,
                wacc = EXCLUDED.wacc,
                updated_at = now()
        """)

        rows_affected = 0
        async with async_session() as session:
            for rec in transformed_records:
                await session.execute(upsert_sql, rec)
                rows_affected += 1
            await session.commit()

        logger.info("yahoo_fundamentals_loaded", rows=rows_affected)
        return rows_affected
