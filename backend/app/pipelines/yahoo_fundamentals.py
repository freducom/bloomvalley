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


# Yahoo emits two overlapping taxonomies — GICS on European tickers,
# an older "Yahoo Sector" set on US tickers. Normalise to GICS so a
# single sector filter matches all peers.
_SECTOR_CANONICAL: dict[str, str] = {
    "Financial Services": "Financials",
    "Consumer Cyclical": "Consumer Discretionary",
    "Consumer Defensive": "Consumer Staples",
    "Technology": "Information Technology",
    "Healthcare": "Health Care",
    "Basic Materials": "Materials",
}


def _canonicalize_sector(name: str | None) -> str | None:
    if not name:
        return None
    return _SECTOR_CANONICAL.get(name.strip(), name.strip())


# Yahoo returns full country names; securities.country is VARCHAR(2) ISO.
_COUNTRY_NAME_TO_ISO2: dict[str, str] = {
    "United States": "US", "Germany": "DE", "France": "FR", "United Kingdom": "GB",
    "Italy": "IT", "Spain": "ES", "Netherlands": "NL", "Belgium": "BE",
    "Switzerland": "CH", "Sweden": "SE", "Finland": "FI", "Denmark": "DK",
    "Norway": "NO", "Ireland": "IE", "Luxembourg": "LU", "Portugal": "PT",
    "Austria": "AT", "Poland": "PL", "Czech Republic": "CZ", "Czechia": "CZ",
    "Greece": "GR", "Hungary": "HU", "Romania": "RO", "Turkey": "TR",
    "Japan": "JP", "China": "CN", "Taiwan": "TW", "South Korea": "KR",
    "Hong Kong": "HK", "Singapore": "SG", "India": "IN", "Indonesia": "ID",
    "Vietnam": "VN", "Malaysia": "MY", "Thailand": "TH", "Philippines": "PH",
    "Australia": "AU", "New Zealand": "NZ",
    "Brazil": "BR", "Mexico": "MX", "Argentina": "AR", "Chile": "CL",
    "Canada": "CA", "Israel": "IL", "United Arab Emirates": "AE",
    "Saudi Arabia": "SA", "South Africa": "ZA", "Georgia": "GE",
    "Russia": "RU", "Ukraine": "UA", "Iceland": "IS", "Estonia": "EE",
    "Latvia": "LV", "Lithuania": "LT", "Malta": "MT", "Cyprus": "CY",
    "Slovakia": "SK", "Slovenia": "SI", "Bulgaria": "BG", "Croatia": "HR",
}


def _country_to_iso2(name: str | None) -> str | None:
    """Convert Yahoo's country name to ISO-3166 alpha-2. Returns None if unmapped
    to avoid truncation errors (better to skip than mis-code)."""
    if not name:
        return None
    name = name.strip()
    if len(name) == 2 and name.isupper():
        return name  # Already an ISO code
    return _COUNTRY_NAME_TO_ISO2.get(name)


def _extract_dividend_yield(info: dict) -> float | None:
    """Return dividend yield as a decimal (0.061 = 6.1%).

    Yahoo exposes three dividend fields with distinct problems:
      * ``dividendYield`` — reliably in percent form (e.g. 2.83 for a
        2.83% yielder); works for ADRs where the other fields don't.
      * ``trailingAnnualDividendRate`` / ``regularMarketPrice`` — needs
        GBp scaling on UK stocks and produces raw-Swiss / ADR-price
        garbage for ADRs (Yahoo returns local-currency dividend rate
        against ADR-currency price).
      * ``trailingAnnualDividendYield`` — same ADR pitfall as above.

    Prefer ``dividendYield`` first, then fall through to the computed
    yield (with GBp scaling), then trailingAnnualDividendYield. Gate
    everything on plausibility (0.05%–30%).
    """
    ccy = (_safe_get(info, "currency") or "").strip()

    # 1. Yahoo's dividendYield (usually percent form; older yfinance
    # versions returned ratios). Try both interpretations and take
    # whichever lands in the plausible range — prefer the percent
    # interpretation (divide by 100) since that's the current format.
    raw = _safe_decimal(_safe_get(info, "dividendYield"))
    if raw is not None:
        for candidate in (raw / 100, raw):
            if 0.0005 <= candidate <= 0.30:
                return candidate

    # 2. Compute from rate / price with GBp scaling
    rate = _safe_get(info, "trailingAnnualDividendRate")
    price = _safe_get(info, "regularMarketPrice") or _safe_get(info, "currentPrice")
    if rate is not None and price is not None:
        try:
            r = float(rate)
            p = float(price)
            if r > 0 and p > 0:
                if ccy == "GBp":
                    r = r * 100
                computed = r / p
                if 0.0005 <= computed <= 0.30:
                    return computed
        except (ValueError, TypeError):
            pass

    # 3. Last resort: trailing yield (unreliable for ADRs)
    trailing = _safe_decimal(_safe_get(info, "trailingAnnualDividendYield"))
    if trailing is not None and 0.0005 <= trailing <= 0.30:
        return trailing

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
            # Plausibility gate for P/B — Yahoo occasionally serves absurd
            # values (e.g. BRK-B reporting 0.001 on 2026-07-22). Real listed
            # equities land in roughly 0.05–30; anything outside is corrupt
            # or a share-class quirk and shouldn't be laundered downstream.
            if price_to_book is not None and not (0.05 <= price_to_book <= 30):
                ticker_str = rec.get("ticker") or "?"
                logger.warning(
                    "yahoo_fundamentals_pb_implausible",
                    ticker=ticker_str,
                    price_to_book=price_to_book,
                )
                price_to_book = None
            # Dividend yield extraction — Yahoo scales inconsistently across markets:
            #   - Most markets: trailingAnnualDividendYield is a decimal (0.061 = 6.1%)
            #   - UK (GBp) stocks: trailingAnnualDividendRate is in pounds but
            #     regularMarketPrice is in pence, so trailingAnnualDividendYield
            #     comes back off by 100x (e.g. LGEN.L shows 0.0007 instead of 0.073).
            # Prefer computing yield ourselves from rate/price with currency-aware
            # scaling; fall back to trailingAnnualDividendYield only when the
            # computed value is unavailable and the trailing value looks plausible.
            dividend_yield = _extract_dividend_yield(info)
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

            # Computed: fcf_yield. Gate on plausibility — FCF yield above 100%
            # is almost always a currency-mismatch upstream (e.g. KT ADR:
            # Yahoo returned FCF in Korean-won-worth of dollars while market
            # cap tracked only the ADR shell). Reject rather than store noise.
            fcf_yield = None
            if free_cash_flow is not None and market_cap is not None and market_cap > 0:
                candidate = free_cash_flow / market_cap
                if -1.0 <= candidate <= 1.0:
                    fcf_yield = candidate
                else:
                    logger.warning(
                        "yahoo_fundamentals_fcfy_implausible",
                        ticker=rec.get("ticker") or "?",
                        fcf_yield=candidate,
                    )
                    # If FCF yield is nonsense we can't trust the underlying
                    # FCF or market-cap pairing either. Null both so screens
                    # don't inherit the bad data.
                    free_cash_flow = None
                    market_cap = None

            # Plausibility gate on P/E — real listed equities land in
            # roughly -50..150 (Yahoo occasionally serves 200-1000+ for
            # micro-caps or during data glitches, e.g. AKTIA.HE showing
            # 281 in 2026-07). Keep negative P/E (loss-makers) but drop
            # extreme positives that are almost always bad data.
            if pe_ratio is not None and (pe_ratio > 200 or pe_ratio < -50):
                logger.warning(
                    "yahoo_fundamentals_pe_implausible",
                    ticker=rec.get("ticker") or "?",
                    pe_ratio=pe_ratio,
                )
                pe_ratio = None

            # Computed: ROIC
            roic = _compute_roic(info)

            # WACC: cannot be reliably computed from yfinance alone
            wacc = None

            # Metadata backfill — Yahoo returns sector/industry/country in
            # `info`. The securities table often lacks these because they
            # weren't set at create-time. Passed through the record so
            # load() can update securities.* only when the current value
            # is NULL (never overwrite user-set data).
            sector = _canonicalize_sector(_safe_get(info, "sector"))
            industry = _safe_get(info, "industry") or None
            country = _country_to_iso2(_safe_get(info, "country"))

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
                    "_sector": sector,
                    "_industry": industry,
                    "_country": country,
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

        # Backfill missing sector/industry/country on the securities table
        # (never overwrite values already set by the user or a previous run).
        # Explicit CAST()s are required so asyncpg can infer parameter types
        # when the value is None — otherwise ``:sector IS NOT NULL`` becomes
        # ambiguous and raises AmbiguousParameterError.
        securities_backfill_sql = text("""
            UPDATE securities
            SET sector = COALESCE(sector, CAST(:sector AS TEXT)),
                industry = COALESCE(industry, CAST(:industry AS TEXT)),
                country = COALESCE(country, CAST(:country AS TEXT))
            WHERE id = :security_id
              AND (
                (sector IS NULL AND CAST(:sector AS TEXT) IS NOT NULL)
                OR (industry IS NULL AND CAST(:industry AS TEXT) IS NOT NULL)
                OR (country IS NULL AND CAST(:country AS TEXT) IS NOT NULL)
              )
        """)

        rows_affected = 0
        metadata_updates = 0
        async with async_session() as session:
            for rec in transformed_records:
                # Strip meta-only keys before passing to the fundamentals upsert
                fund_rec = {k: v for k, v in rec.items() if not k.startswith("_")}
                await session.execute(upsert_sql, fund_rec)
                rows_affected += 1

                # Metadata backfill on securities table
                meta = {
                    "security_id": rec["security_id"],
                    "sector": rec.get("_sector"),
                    "industry": rec.get("_industry"),
                    "country": rec.get("_country"),
                }
                if any(meta[k] is not None for k in ("sector", "industry", "country")):
                    result = await session.execute(securities_backfill_sql, meta)
                    if result.rowcount > 0:
                        metadata_updates += 1
            await session.commit()

        logger.info(
            "yahoo_fundamentals_loaded",
            rows=rows_affected,
            metadata_backfilled=metadata_updates,
        )

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
