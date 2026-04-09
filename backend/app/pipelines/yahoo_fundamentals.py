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


def _get_financial_debt(info: dict) -> int | None:
    """
    Return financial debt excluding IFRS 16 lease liabilities.

    Yahoo Finance ``totalDebt`` includes capital-lease obligations, which
    inflates leverage and deflates ROIC for asset-heavy retailers and similar
    companies.  When the balance-sheet breakdown is available we subtract
    lease obligations; otherwise we fall back to ``totalDebt`` as-is.
    """
    total_debt = _safe_get(info, "totalDebt")
    if total_debt is None:
        return None

    # Check balance-sheet field first, then info dict
    lease_obligations = (
        _safe_get(info, "bs_capital_lease_obligations")
        or _safe_get(info, "capitalLeaseObligations")
        or 0
    )
    financial_debt = total_debt - lease_obligations
    # Sanity: if subtraction goes negative (data quirks), fall back
    return financial_debt if financial_debt > 0 else total_debt


def _compute_roic(info: dict) -> float | None:
    """
    Compute ROIC (Return on Invested Capital).

    Preferred: EBIT * (1 - tax_rate) / invested_capital
    Uses financial debt (excluding IFRS 16 leases) to avoid penalising
    companies with large lease portfolios (retailers, airlines, etc.).
    Falls back to balance-sheet values when info dict is incomplete.
    """
    ebit = _safe_get(info, "ebit") or _safe_get(info, "bs_ebit")
    equity = _safe_get(info, "stockholdersEquity") or _safe_get(info, "bs_stockholders_equity")
    total_cash = _safe_get(info, "totalCash")
    financial_debt = _get_financial_debt(info)

    if ebit is not None and financial_debt is not None and equity is not None:
        cash = total_cash if total_cash is not None else 0
        invested_capital = financial_debt + equity - cash
        if invested_capital > 0:
            nopat = ebit * (1 - DEFAULT_TAX_RATE)
            return nopat / invested_capital

    # Fallback: returnOnEquity (better proxy than ROA for capital efficiency)
    roe = _safe_get(info, "returnOnEquity")
    if roe is not None:
        return float(roe)

    # Fallback: returnOnAssets
    roa = _safe_get(info, "returnOnAssets")
    if roa is not None:
        return float(roa)

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
                def _fetch_ticker(t=yahoo_ticker):
                    ticker_obj = yf.Ticker(t)
                    info = ticker_obj.info
                    # Fetch balance sheet & income statement for data the
                    # info dict sometimes omits (equity, EBIT, lease obligations)
                    bs_extras = {}
                    try:
                        bs = ticker_obj.balance_sheet
                        if bs is not None and not bs.empty:
                            col = bs.columns[0]
                            for field, key in [
                                ("Capital Lease Obligations", "bs_capital_lease_obligations"),
                                ("Stockholders Equity", "bs_stockholders_equity"),
                                ("Net Debt", "bs_net_debt"),
                            ]:
                                if field in bs.index:
                                    val = bs.loc[field, col]
                                    if val is not None and val == val:  # not NaN
                                        bs_extras[key] = float(val)
                    except Exception:
                        pass
                    try:
                        inc = ticker_obj.income_stmt
                        if inc is not None and not inc.empty:
                            col = inc.columns[0]
                            if "EBIT" in inc.index:
                                val = inc.loc["EBIT", col]
                                if val is not None and val == val:
                                    bs_extras["bs_ebit"] = float(val)
                    except Exception:
                        pass
                    return {**info, **bs_extras}

                info = await asyncio.to_thread(_fetch_ticker)
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
            # Use trailingAnnualDividendYield (already a decimal, e.g. 0.061 = 6.1%)
            # More reliable than dividendYield which is inconsistently scaled
            dividend_yield = _safe_decimal(_safe_get(info, "trailingAnnualDividendYield"))
            trailing_eps = _safe_get(info, "trailingEps")
            total_revenue = _safe_get(info, "totalRevenue")
            gross_margin = _safe_decimal(_safe_get(info, "grossMargins"))
            operating_margin = _safe_decimal(_safe_get(info, "operatingMargins"))
            net_margin = _safe_decimal(_safe_get(info, "profitMargins"))
            pe_ratio = _safe_decimal(_safe_get(info, "trailingPE"))
            market_cap = _safe_get(info, "marketCap")

            # Computed: net_debt_ebitda (using financial debt excl. IFRS 16 leases)
            financial_debt = _get_financial_debt(info)
            total_cash = _safe_get(info, "totalCash")
            ebitda = _safe_get(info, "ebitda")
            net_debt_ebitda = None
            if financial_debt is not None and total_cash is not None and ebitda is not None and ebitda != 0:
                net_debt_ebitda = (financial_debt - total_cash) / ebitda

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

        # Compute DCF valuations for all securities with positive FCF
        await self._compute_dcf_valuations()

        return rows_affected

    async def _compute_dcf_valuations(self) -> None:
        """
        Compute 2-stage DCF valuations for all securities with positive FCF.

        Stage 1 (years 1-5): FCF growth rate based on ROIC quality tier.
        Stage 2 (terminal): Perpetuity growth at 2.5% (long-term GDP proxy).
        Discount rate: WACC if available, otherwise tiered by ROIC.

        Updates dcf_value_cents, dcf_discount_rate, dcf_terminal_growth,
        and dcf_model_notes in security_fundamentals.
        """
        TERMINAL_GROWTH = 0.025

        async with async_session() as session:
            # Fetch all fundamentals with positive FCF
            result = await session.execute(
                text("""
                    SELECT id, security_id, free_cash_flow_cents, fcf_currency,
                           roic, wacc, market_cap_cents
                    FROM security_fundamentals
                    WHERE free_cash_flow_cents > 0
                """)
            )
            rows = result.fetchall()

        if not rows:
            logger.info("dcf_compute_skip", reason="no securities with positive FCF")
            return

        logger.info("dcf_compute_start", securities=len(rows))

        update_sql = text("""
            UPDATE security_fundamentals
            SET dcf_value_cents = :dcf_value_cents,
                dcf_discount_rate = :dcf_discount_rate,
                dcf_terminal_growth = :dcf_terminal_growth,
                dcf_model_notes = :dcf_model_notes,
                updated_at = now()
            WHERE id = :id
        """)

        updated = 0
        async with async_session() as session:
            for row in rows:
                fund_id = row[0]
                fcf_cents = row[2]
                fcf_currency = row[3] or "USD"
                roic = float(row[4]) if row[4] is not None else None
                wacc = float(row[5]) if row[5] is not None else None
                market_cap_cents = row[6]

                # Determine Stage 1 growth rate based on ROIC
                if roic is not None:
                    if roic > 0.20:
                        growth_rate = 0.15
                    elif roic > 0.15:
                        growth_rate = 0.12
                    elif roic > 0.10:
                        growth_rate = 0.08
                    else:
                        growth_rate = 0.05
                else:
                    # No ROIC data — use conservative default
                    growth_rate = 0.05

                # Cap growth rate at 20%
                growth_rate = min(growth_rate, 0.20)

                # Determine discount rate: WACC if available, else tiered by ROIC
                if wacc is not None and wacc > TERMINAL_GROWTH:
                    discount_rate = wacc
                else:
                    if roic is not None and roic > 0.15:
                        discount_rate = 0.10
                    elif roic is not None and roic > 0.10:
                        discount_rate = 0.11
                    else:
                        discount_rate = 0.12

                # Guard: discount rate must exceed terminal growth
                if discount_rate <= TERMINAL_GROWTH:
                    logger.warning(
                        "dcf_skip_low_discount_rate",
                        fund_id=fund_id,
                        discount_rate=discount_rate,
                        terminal_growth=TERMINAL_GROWTH,
                    )
                    continue

                # Stage 1: project FCF for years 1-5 and discount
                fcf = fcf_cents  # in cents
                pv_stage1 = 0
                for year in range(1, 6):
                    fcf = fcf * (1 + growth_rate)
                    pv_stage1 += fcf / (1 + discount_rate) ** year

                # fcf is now FCF at year 5
                fcf_year5 = fcf

                # Stage 2: terminal value
                terminal_value = fcf_year5 * (1 + TERMINAL_GROWTH) / (discount_rate - TERMINAL_GROWTH)
                pv_terminal = terminal_value / (1 + discount_rate) ** 5

                # Total DCF enterprise value (in cents)
                dcf_value_cents = round(pv_stage1 + pv_terminal)

                # Format FCF for notes (convert cents to human-readable)
                fcf_abs = abs(row[2])  # original FCF cents
                if fcf_abs >= 100_000_000_00:  # >= 1B (in cents)
                    fcf_display = f"{row[2] / 100_000_000_00:.1f}B"
                elif fcf_abs >= 100_000_00:  # >= 1M (in cents)
                    fcf_display = f"{row[2] / 100_000_00:.1f}M"
                else:
                    fcf_display = f"{row[2] / 100:.0f}"

                currency_symbol = {"EUR": "\u20ac", "USD": "$", "SEK": "kr", "GBP": "\u00a3"}.get(
                    fcf_currency, fcf_currency
                )

                growth_pct = round(growth_rate * 100)
                terminal_pct = round(TERMINAL_GROWTH * 100, 1)
                discount_pct = round(discount_rate * 100)
                wacc_label = "WACC" if wacc is not None and wacc > TERMINAL_GROWTH else "est"

                notes = (
                    f"2-stage DCF: {growth_pct}% growth 5yr, "
                    f"{terminal_pct}% terminal, "
                    f"{discount_pct}% {wacc_label}. "
                    f"FCF: {currency_symbol}{fcf_display}"
                )

                await session.execute(
                    update_sql,
                    {
                        "id": fund_id,
                        "dcf_value_cents": dcf_value_cents,
                        "dcf_discount_rate": discount_rate,
                        "dcf_terminal_growth": TERMINAL_GROWTH,
                        "dcf_model_notes": notes,
                    },
                )
                updated += 1

            await session.commit()

        logger.info("dcf_compute_complete", updated=updated)
