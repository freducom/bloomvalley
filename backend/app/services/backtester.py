"""Backtesting engine — historical simulation of investment strategies.

Replays real historical prices, dividends, FX rates, and transaction costs
to evaluate how a strategy would have performed. Supports glidepath-aware
allocation, rebalancing, contributions, and tax simulation.

All monetary values are integer cents. All calculations are server-side.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

import numpy as np
import structlog
from sqlalchemy import select

from app.db.engine import async_session
from app.db.models.dividends import DividendEvent
from app.db.models.prices import FxRate, Price
from app.db.models.securities import Security

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Glidepath targets by age (mirrors risk.py)
# ---------------------------------------------------------------------------

GLIDEPATH = {
    45: {"equity": 0.75, "fixed_income": 0.15, "crypto": 0.07, "cash": 0.03},
    50: {"equity": 0.65, "fixed_income": 0.22, "crypto": 0.06, "cash": 0.07},
    55: {"equity": 0.50, "fixed_income": 0.38, "crypto": 0.04, "cash": 0.08},
    60: {"equity": 0.30, "fixed_income": 0.60, "crypto": 0.02, "cash": 0.08},
}

ASSET_CLASS_MAP = {
    "stock": "equity",
    "etf": "equity",
    "bond": "fixed_income",
    "crypto": "crypto",
}

# Maximum consecutive missing-price days before we skip a security for a day
MAX_FORWARD_FILL_DAYS = 5

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class StrategyConfig:
    """Full specification of a backtestable strategy."""

    name: str
    start_date: date
    end_date: date
    initial_capital_cents: int
    monthly_contribution_cents: int = 0
    contribution_growth_rate: float = 0.0  # annual % increase of contributions
    rebalance_frequency: str = "quarterly"  # monthly / quarterly / annually / drift
    drift_threshold_pct: float = 5.0
    allocation: dict[str, float] = field(default_factory=dict)  # asset_class -> weight
    security_tickers: dict[str, list[str]] = field(default_factory=dict)  # asset_class -> tickers
    use_glidepath: bool = True
    birth_date: date = date(1981, 3, 19)
    transaction_cost_pct: float = 0.001  # 0.1 %
    tax_rate: float = 0.30  # simplified flat rate for backtest
    reinvest_dividends: bool = True


@dataclass
class BacktestResult:
    """Output of a single backtest run."""

    daily_values: list[dict]  # [{date, valueCents, cashCents}]
    metrics: dict  # computed performance metrics
    trades: list[dict]  # all simulated trades
    annual_returns: list[dict]  # [{year, returnPct}]
    tax_paid_cents: int
    dividends_received_cents: int
    transaction_costs_cents: int


@dataclass
class ComparisonResult:
    """Side-by-side comparison of multiple strategies."""

    strategies: list[dict]  # [{name, metrics, equityCurve}]
    comparison_table: dict  # metric -> {strategy_name: value}


@dataclass
class RollingResult:
    """Rolling window backtest output."""

    distribution: dict  # min, p25, median, p75, max CAGR
    periods: list[dict]  # [{startDate, endDate, cagr}]


# ---------------------------------------------------------------------------
# Helpers — data loading
# ---------------------------------------------------------------------------


async def _load_securities_by_ticker(tickers: list[str]) -> dict[str, Security]:
    """Return {ticker: Security} for requested tickers."""
    if not tickers:
        return {}
    async with async_session() as session:
        result = await session.execute(
            select(Security).where(Security.ticker.in_(tickers))
        )
        return {s.ticker: s for s in result.scalars().all()}


async def _load_prices(
    security_ids: list[int],
    start_date: date,
    end_date: date,
) -> dict[int, dict[date, int]]:
    """Return {security_id: {date: close_cents}} for the date range."""
    prices: dict[int, dict[date, int]] = {sid: {} for sid in security_ids}
    async with async_session() as session:
        result = await session.execute(
            select(Price.security_id, Price.date, Price.close_cents)
            .where(
                Price.security_id.in_(security_ids),
                Price.date >= start_date,
                Price.date <= end_date,
            )
            .order_by(Price.date)
        )
        for row in result.all():
            prices[row.security_id][row.date] = row.close_cents
    return prices


async def _load_fx_rates(
    currencies: set[str],
    start_date: date,
    end_date: date,
) -> dict[str, dict[date, Decimal]]:
    """Return {quote_currency: {date: rate}} where base is EUR."""
    currencies_needed = currencies - {"EUR"}
    if not currencies_needed:
        return {}
    rates: dict[str, dict[date, Decimal]] = {c: {} for c in currencies_needed}
    async with async_session() as session:
        result = await session.execute(
            select(FxRate.quote_currency, FxRate.date, FxRate.rate)
            .where(
                FxRate.base_currency == "EUR",
                FxRate.quote_currency.in_(currencies_needed),
                FxRate.date >= start_date,
                FxRate.date <= end_date,
            )
            .order_by(FxRate.date)
        )
        for row in result.all():
            rates[row.quote_currency][row.date] = row.rate
    return rates


async def _load_dividend_events(
    security_ids: list[int],
    start_date: date,
    end_date: date,
) -> dict[int, list[dict]]:
    """Return {security_id: [{ex_date, amount_cents, currency}]}."""
    divs: dict[int, list[dict]] = {sid: [] for sid in security_ids}
    async with async_session() as session:
        result = await session.execute(
            select(
                DividendEvent.security_id,
                DividendEvent.ex_date,
                DividendEvent.amount_cents,
                DividendEvent.currency,
            )
            .where(
                DividendEvent.security_id.in_(security_ids),
                DividendEvent.ex_date >= start_date,
                DividendEvent.ex_date <= end_date,
            )
            .order_by(DividendEvent.ex_date)
        )
        for row in result.all():
            divs[row.security_id].append({
                "ex_date": row.ex_date,
                "amount_cents": row.amount_cents,
                "currency": row.currency,
            })
    return divs


# ---------------------------------------------------------------------------
# Helpers — forward-fill prices
# ---------------------------------------------------------------------------


def _forward_fill_prices(
    raw: dict[date, int],
    all_dates: list[date],
) -> dict[date, int | None]:
    """Forward-fill prices up to MAX_FORWARD_FILL_DAYS gaps.

    Returns a dict with an entry for every date in *all_dates*.
    Value is None if no price and beyond the fill window.
    """
    filled: dict[date, int | None] = {}
    last_known: int | None = None
    gap = 0
    for d in all_dates:
        if d in raw:
            last_known = raw[d]
            gap = 0
            filled[d] = last_known
        elif last_known is not None and gap < MAX_FORWARD_FILL_DAYS:
            gap += 1
            filled[d] = last_known
        else:
            filled[d] = None
    return filled


# ---------------------------------------------------------------------------
# Helpers — glidepath interpolation
# ---------------------------------------------------------------------------


def _interpolate_glidepath(age: float) -> dict[str, float]:
    """Linearly interpolate glidepath targets for a fractional age."""
    ages = sorted(GLIDEPATH.keys())
    if age <= ages[0]:
        return dict(GLIDEPATH[ages[0]])
    if age >= ages[-1]:
        return dict(GLIDEPATH[ages[-1]])
    # Find bracketing ages
    lower = ages[0]
    upper = ages[-1]
    for i in range(len(ages) - 1):
        if ages[i] <= age <= ages[i + 1]:
            lower, upper = ages[i], ages[i + 1]
            break
    t = (age - lower) / (upper - lower) if upper != lower else 0.0
    result = {}
    for cat in GLIDEPATH[lower]:
        lo = GLIDEPATH[lower][cat]
        hi = GLIDEPATH[upper][cat]
        result[cat] = lo + t * (hi - lo)
    return result


# ---------------------------------------------------------------------------
# Helpers — rebalancing logic
# ---------------------------------------------------------------------------


def _should_rebalance(
    current_date: date,
    last_rebalance: date | None,
    frequency: str,
    weights_current: dict[str, float],
    weights_target: dict[str, float],
    drift_threshold_pct: float,
) -> bool:
    """Determine whether a rebalance is due."""
    if last_rebalance is None:
        return True  # initial allocation

    if frequency == "drift":
        for cat in weights_target:
            cur = weights_current.get(cat, 0.0)
            tgt = weights_target.get(cat, 0.0)
            if abs(cur - tgt) * 100 > drift_threshold_pct:
                return True
        return False

    freq_days = {"monthly": 28, "quarterly": 90, "annually": 365}
    threshold = freq_days.get(frequency, 90)
    return (current_date - last_rebalance).days >= threshold


# ---------------------------------------------------------------------------
# Helpers — trade generation date range
# ---------------------------------------------------------------------------


def _generate_trading_dates(start: date, end: date) -> list[date]:
    """Generate all calendar dates from start to end inclusive."""
    dates: list[date] = []
    d = start
    while d <= end:
        dates.append(d)
        d += timedelta(days=1)
    return dates


# ---------------------------------------------------------------------------
# Core engine
# ---------------------------------------------------------------------------


async def run_backtest(config: StrategyConfig) -> BacktestResult:
    """Run a full daily backtest simulation.

    Returns a BacktestResult with daily equity curve, all trades,
    annual returns, and aggregate metrics.
    """
    logger.info(
        "backtest.start",
        strategy=config.name,
        start=config.start_date.isoformat(),
        end=config.end_date.isoformat(),
        initial_cents=config.initial_capital_cents,
    )

    # ── Resolve tickers to securities ──
    all_tickers: list[str] = []
    for tickers in config.security_tickers.values():
        all_tickers.extend(tickers)
    all_tickers = list(set(all_tickers))

    sec_map = await _load_securities_by_ticker(all_tickers)
    if not sec_map:
        raise ValueError(f"No securities found for tickers: {all_tickers}")

    # Build ticker -> security_id and asset_class maps
    ticker_to_sid: dict[str, int] = {}
    ticker_to_currency: dict[str, str] = {}
    ticker_to_asset_class: dict[str, str] = {}
    for ticker, sec in sec_map.items():
        ticker_to_sid[ticker] = sec.id
        ticker_to_currency[ticker] = sec.currency
        ticker_to_asset_class[ticker] = sec.asset_class

    security_ids = list(ticker_to_sid.values())
    currencies_needed = set(ticker_to_currency.values())

    # ── Load market data ──
    raw_prices = await _load_prices(security_ids, config.start_date, config.end_date)
    fx_rates_raw = await _load_fx_rates(currencies_needed, config.start_date, config.end_date)
    dividend_events = await _load_dividend_events(security_ids, config.start_date, config.end_date)

    # Build dividend lookup: (security_id, date) -> amount_cents in EUR
    div_lookup: dict[tuple[int, date], int] = {}
    for sid, events in dividend_events.items():
        for ev in events:
            # Convert dividend to EUR if needed
            div_eur = ev["amount_cents"]
            if ev["currency"] != "EUR":
                # Use FX rate on ex_date or closest prior
                fx_data = fx_rates_raw.get(ev["currency"], {})
                fx = _get_fx_on_date(fx_data, ev["ex_date"])
                if fx:
                    div_eur = int(ev["amount_cents"] / float(fx))
            div_lookup[(sid, ev["ex_date"])] = div_eur

    # ── Forward-fill prices ──
    all_dates = _generate_trading_dates(config.start_date, config.end_date)
    filled_prices: dict[int, dict[date, int | None]] = {}
    for sid in security_ids:
        filled_prices[sid] = _forward_fill_prices(raw_prices[sid], all_dates)

    # Forward-fill FX rates
    filled_fx: dict[str, dict[date, Decimal | None]] = {}
    for ccy, raw_fx in fx_rates_raw.items():
        fx_filled: dict[date, Decimal | None] = {}
        last_fx: Decimal | None = None
        gap = 0
        for d in all_dates:
            if d in raw_fx:
                last_fx = raw_fx[d]
                gap = 0
                fx_filled[d] = last_fx
            elif last_fx is not None and gap < MAX_FORWARD_FILL_DAYS:
                gap += 1
                fx_filled[d] = last_fx
            else:
                fx_filled[d] = last_fx  # keep last known FX rate (broader fill)
        filled_fx[ccy] = fx_filled

    # ── Build reverse maps ──
    sid_to_ticker: dict[int, str] = {v: k for k, v in ticker_to_sid.items()}

    # Build asset_class -> list of tickers for allocation
    class_tickers: dict[str, list[str]] = {}
    for asset_class, tickers in config.security_tickers.items():
        valid = [t for t in tickers if t in sec_map]
        if valid:
            class_tickers[asset_class] = valid

    # ── Simulation state ──
    # Holdings: ticker -> {shares (float), cost_basis_cents (int, EUR)}
    holdings: dict[str, dict] = {}
    cash_cents: int = config.initial_capital_cents
    last_rebalance: date | None = None
    last_contribution_month: tuple[int, int] | None = None
    current_contribution_cents = config.monthly_contribution_cents

    # Accumulators
    daily_values: list[dict] = []
    trades: list[dict] = []
    total_tax_paid_cents = 0
    total_dividends_cents = 0
    total_transaction_costs_cents = 0
    year_start_value: dict[int, int] = {}  # year -> portfolio value at start

    def _price_eur(ticker: str, d: date) -> int | None:
        """Get price in EUR cents for ticker on date."""
        sid = ticker_to_sid[ticker]
        px = filled_prices[sid].get(d)
        if px is None:
            return None
        ccy = ticker_to_currency[ticker]
        if ccy == "EUR":
            return px
        fx_data = filled_fx.get(ccy, {})
        fx = fx_data.get(d)
        if fx is None:
            return None
        return int(px / float(fx))

    def _portfolio_value(d: date) -> int:
        """Total portfolio value in EUR cents (holdings + cash)."""
        total = cash_cents
        for ticker, pos in holdings.items():
            px = _price_eur(ticker, d)
            if px is not None:
                total += int(pos["shares"] * px)
        return total

    def _current_weights(d: date) -> dict[str, float]:
        """Current allocation weights by glidepath category."""
        total = _portfolio_value(d)
        if total <= 0:
            return {}
        weights: dict[str, float] = {}
        for ac, tickers in class_tickers.items():
            gp_cat = _map_asset_class_to_glidepath(ac)
            for ticker in tickers:
                px = _price_eur(ticker, d)
                if px is not None and ticker in holdings:
                    val = int(holdings[ticker]["shares"] * px)
                    weights[gp_cat] = weights.get(gp_cat, 0.0) + val / total
        weights["cash"] = cash_cents / total
        return weights

    def _target_allocation(d: date) -> dict[str, float]:
        """Target allocation based on glidepath or fixed config."""
        if config.use_glidepath:
            age = (d - config.birth_date).days / 365.25
            return _interpolate_glidepath(age)
        return dict(config.allocation)

    # ── Daily simulation loop ──
    for d in all_dates:
        # a. Track year start
        if d.year not in year_start_value:
            year_start_value[d.year] = _portfolio_value(d)

        # b. Process dividends
        for ticker, pos in list(holdings.items()):
            sid = ticker_to_sid[ticker]
            div_eur = div_lookup.get((sid, d))
            if div_eur and pos["shares"] > 0:
                div_amount = int(pos["shares"] * div_eur)
                total_dividends_cents += div_amount
                if config.reinvest_dividends:
                    # Reinvest by buying more shares (after tax)
                    after_tax = int(div_amount * (1 - config.tax_rate))
                    total_tax_paid_cents += div_amount - after_tax
                    px = _price_eur(ticker, d)
                    if px and px > 0:
                        new_shares = after_tax / px
                        cost = int(new_shares * px)
                        tc = int(cost * config.transaction_cost_pct)
                        total_transaction_costs_cents += tc
                        actual_cost = cost + tc
                        if actual_cost <= after_tax:
                            holdings[ticker]["shares"] += new_shares
                            holdings[ticker]["cost_basis_cents"] += actual_cost
                            trades.append({
                                "date": d.isoformat(),
                                "ticker": ticker,
                                "action": "dividend_reinvest",
                                "shares": round(new_shares, 6),
                                "priceCents": px,
                                "totalCents": actual_cost,
                            })
                        else:
                            cash_cents += after_tax
                    else:
                        cash_cents += after_tax
                else:
                    cash_cents += div_amount

        # c. Monthly contribution
        ym = (d.year, d.month)
        if config.monthly_contribution_cents > 0 and ym != last_contribution_month:
            if d.day >= 1:  # First trading day of month
                # Annual increase of contributions
                years_elapsed = (d - config.start_date).days / 365.25
                growth_factor = (1 + config.contribution_growth_rate) ** int(years_elapsed)
                current_contribution_cents = int(
                    config.monthly_contribution_cents * growth_factor
                )
                cash_cents += current_contribution_cents
                last_contribution_month = ym

        # d. Check rebalance
        target = _target_allocation(d)
        cur_weights = _current_weights(d)
        if _should_rebalance(d, last_rebalance, config.rebalance_frequency,
                             cur_weights, target, config.drift_threshold_pct):
            _execute_rebalance(
                d, target, holdings, class_tickers,
                _price_eur, cash_cents, config,
                trades, sid_to_ticker, ticker_to_sid,
            )
            # Rebalance modifies cash — recalculate from trades
            cash_cents = _recalculate_cash_after_rebalance(
                cash_cents, trades, d, config,
            )
            # Track tax from sells
            tax_and_costs = _compute_rebalance_tax_and_costs(trades, d, config)
            total_tax_paid_cents += tax_and_costs["tax"]
            total_transaction_costs_cents += tax_and_costs["costs"]
            last_rebalance = d

        # e. Record daily value
        portfolio_val = _portfolio_value(d)
        daily_values.append({
            "date": d.isoformat(),
            "valueCents": portfolio_val,
            "cashCents": cash_cents,
        })

    # ── Annual returns ──
    annual_returns = _compute_annual_returns(daily_values)

    # ── Metrics ──
    metrics = compute_metrics(daily_values)

    logger.info(
        "backtest.complete",
        strategy=config.name,
        total_return_pct=metrics.get("totalReturnPct"),
        cagr=metrics.get("cagr"),
        sharpe=metrics.get("sharpeRatio"),
        max_drawdown=metrics.get("maxDrawdownPct"),
        trades_count=len(trades),
    )

    return BacktestResult(
        daily_values=daily_values,
        metrics=metrics,
        trades=trades,
        annual_returns=annual_returns,
        tax_paid_cents=total_tax_paid_cents,
        dividends_received_cents=total_dividends_cents,
        transaction_costs_cents=total_transaction_costs_cents,
    )


# ---------------------------------------------------------------------------
# Rebalancing execution
# ---------------------------------------------------------------------------


def _map_asset_class_to_glidepath(asset_class: str) -> str:
    """Map a strategy asset class key to glidepath category."""
    mapping = {
        "equity": "equity",
        "stock": "equity",
        "etf": "equity",
        "fixed_income": "fixed_income",
        "bond": "fixed_income",
        "bonds": "fixed_income",
        "crypto": "crypto",
        "cash": "cash",
    }
    return mapping.get(asset_class, "equity")


def _execute_rebalance(
    d: date,
    target: dict[str, float],
    holdings: dict[str, dict],
    class_tickers: dict[str, list[str]],
    price_fn,
    cash_cents: int,
    config: StrategyConfig,
    trades: list[dict],
    sid_to_ticker: dict[int, str],
    ticker_to_sid: dict[str, int],
) -> None:
    """Execute rebalance trades in-place on holdings dict.

    Sells overweight positions first, then buys underweight positions.
    Trade records are appended to trades list.
    """
    # Total portfolio value
    total = cash_cents
    for ticker, pos in holdings.items():
        px = price_fn(ticker, d)
        if px is not None:
            total += int(pos["shares"] * px)
    if total <= 0:
        return

    # Determine target value per glidepath category
    target_values: dict[str, int] = {}
    for cat, weight in target.items():
        target_values[cat] = int(total * weight)

    # Current value per category
    current_cat_values: dict[str, int] = {}
    ticker_values: dict[str, int] = {}
    for ac, tickers in class_tickers.items():
        gp_cat = _map_asset_class_to_glidepath(ac)
        for ticker in tickers:
            px = price_fn(ticker, d)
            val = 0
            if px is not None and ticker in holdings:
                val = int(holdings[ticker]["shares"] * px)
            ticker_values[ticker] = val
            current_cat_values[gp_cat] = current_cat_values.get(gp_cat, 0) + val

    # Compute needed adjustments per category
    adjustments: dict[str, int] = {}  # gp_cat -> delta cents (positive = buy)
    for cat in target:
        if cat == "cash":
            continue
        current = current_cat_values.get(cat, 0)
        needed = target_values.get(cat, 0)
        adjustments[cat] = needed - current

    # Distribute adjustments equally among tickers in each category
    for ac, tickers in class_tickers.items():
        gp_cat = _map_asset_class_to_glidepath(ac)
        delta = adjustments.get(gp_cat, 0)
        if delta == 0 or not tickers:
            continue
        valid_tickers = [t for t in tickers if price_fn(t, d) is not None]
        if not valid_tickers:
            continue

        per_ticker = delta // len(valid_tickers)
        for ticker in valid_tickers:
            px = price_fn(ticker, d)
            if px is None or px <= 0:
                continue

            if per_ticker > 0:
                # Buy
                shares_to_buy = per_ticker / px
                if shares_to_buy > 0:
                    if ticker not in holdings:
                        holdings[ticker] = {"shares": 0.0, "cost_basis_cents": 0}
                    cost = int(shares_to_buy * px)
                    holdings[ticker]["shares"] += shares_to_buy
                    holdings[ticker]["cost_basis_cents"] += cost
                    trades.append({
                        "date": d.isoformat(),
                        "ticker": ticker,
                        "action": "rebalance_buy",
                        "shares": round(shares_to_buy, 6),
                        "priceCents": px,
                        "totalCents": cost,
                    })
            elif per_ticker < 0:
                # Sell
                if ticker not in holdings or holdings[ticker]["shares"] <= 0:
                    continue
                sell_value = abs(per_ticker)
                shares_to_sell = min(sell_value / px, holdings[ticker]["shares"])
                if shares_to_sell > 0:
                    proceeds = int(shares_to_sell * px)
                    # Compute gain for tax
                    avg_cost_per_share = (
                        holdings[ticker]["cost_basis_cents"] / holdings[ticker]["shares"]
                        if holdings[ticker]["shares"] > 0
                        else 0
                    )
                    cost_of_sold = int(shares_to_sell * avg_cost_per_share)
                    holdings[ticker]["shares"] -= shares_to_sell
                    holdings[ticker]["cost_basis_cents"] -= cost_of_sold
                    # Clean up zero positions
                    if holdings[ticker]["shares"] < 0.0001:
                        holdings[ticker]["shares"] = 0.0
                        holdings[ticker]["cost_basis_cents"] = 0
                    trades.append({
                        "date": d.isoformat(),
                        "ticker": ticker,
                        "action": "rebalance_sell",
                        "shares": round(shares_to_sell, 6),
                        "priceCents": px,
                        "totalCents": proceeds,
                        "gainCents": proceeds - cost_of_sold,
                    })


def _recalculate_cash_after_rebalance(
    cash_before: int,
    trades: list[dict],
    d: date,
    config: StrategyConfig,
) -> int:
    """Recalculate cash after rebalance trades on a given date."""
    cash = cash_before
    d_iso = d.isoformat()
    for t in trades:
        if t["date"] != d_iso:
            continue
        if t["action"] == "rebalance_buy":
            tc = int(t["totalCents"] * config.transaction_cost_pct)
            cash -= t["totalCents"] + tc
        elif t["action"] == "rebalance_sell":
            tc = int(t["totalCents"] * config.transaction_cost_pct)
            proceeds = t["totalCents"] - tc
            # Tax on gains
            gain = t.get("gainCents", 0)
            tax = int(max(0, gain) * config.tax_rate) if gain > 0 else 0
            cash += proceeds - tax
    return cash


def _compute_rebalance_tax_and_costs(
    trades: list[dict],
    d: date,
    config: StrategyConfig,
) -> dict:
    """Sum tax and transaction costs from rebalance trades on a date."""
    d_iso = d.isoformat()
    tax = 0
    costs = 0
    for t in trades:
        if t["date"] != d_iso:
            continue
        if t["action"] in ("rebalance_buy", "rebalance_sell"):
            tc = int(t["totalCents"] * config.transaction_cost_pct)
            costs += tc
            if t["action"] == "rebalance_sell":
                gain = t.get("gainCents", 0)
                if gain > 0:
                    tax += int(gain * config.tax_rate)
    return {"tax": tax, "costs": costs}


# ---------------------------------------------------------------------------
# Helpers — FX rate lookup
# ---------------------------------------------------------------------------


def _get_fx_on_date(fx_data: dict[date, Decimal], d: date) -> Decimal | None:
    """Get FX rate on date, or closest prior date within 5 days."""
    for offset in range(MAX_FORWARD_FILL_DAYS + 1):
        check = d - timedelta(days=offset)
        if check in fx_data:
            return fx_data[check]
    return None


# ---------------------------------------------------------------------------
# Annual returns
# ---------------------------------------------------------------------------


def _compute_annual_returns(daily_values: list[dict]) -> list[dict]:
    """Compute annual returns from daily equity curve."""
    if len(daily_values) < 2:
        return []

    years: dict[int, dict] = {}  # year -> {first_value, last_value}
    for dv in daily_values:
        d = date.fromisoformat(dv["date"])
        y = d.year
        if y not in years:
            years[y] = {"first": dv["valueCents"], "last": dv["valueCents"]}
        else:
            years[y]["last"] = dv["valueCents"]

    results: list[dict] = []
    prev_year_end: int | None = None
    for year in sorted(years.keys()):
        start_val = prev_year_end if prev_year_end else years[year]["first"]
        end_val = years[year]["last"]
        if start_val > 0:
            ret_pct = round(((end_val - start_val) / start_val) * 100, 2)
        else:
            ret_pct = 0.0
        results.append({"year": year, "returnPct": ret_pct})
        prev_year_end = end_val

    return results


# ---------------------------------------------------------------------------
# Performance metrics
# ---------------------------------------------------------------------------


def compute_metrics(daily_values: list[dict], risk_free_rate: float = 0.03) -> dict:
    """Compute comprehensive performance metrics from a daily equity curve.

    Returns a dict with camelCase keys suitable for JSON response.
    """
    if len(daily_values) < 2:
        return {
            "totalReturnPct": 0.0,
            "cagr": 0.0,
            "sharpeRatio": 0.0,
            "sortinoRatio": 0.0,
            "maxDrawdownPct": 0.0,
            "maxDrawdownStart": None,
            "maxDrawdownEnd": None,
            "calmarRatio": 0.0,
            "winRate": 0.0,
            "bestYear": None,
            "worstYear": None,
            "tradingDays": len(daily_values),
        }

    values = np.array([dv["valueCents"] for dv in daily_values], dtype=np.float64)
    dates = [date.fromisoformat(dv["date"]) for dv in daily_values]

    # Total return
    start_val = values[0]
    end_val = values[-1]
    total_return_pct = ((end_val - start_val) / start_val * 100) if start_val > 0 else 0.0

    # CAGR
    years = (dates[-1] - dates[0]).days / 365.25
    if years > 0 and start_val > 0 and end_val > 0:
        cagr = ((end_val / start_val) ** (1 / years) - 1) * 100
    else:
        cagr = 0.0

    # Daily returns (simple)
    daily_returns = np.diff(values) / values[:-1]
    # Filter out infinite/nan
    daily_returns = daily_returns[np.isfinite(daily_returns)]

    ann_factor = 252
    daily_mean = float(np.mean(daily_returns)) if len(daily_returns) > 0 else 0.0
    daily_std = float(np.std(daily_returns, ddof=1)) if len(daily_returns) > 1 else 0.0

    ann_return = daily_mean * ann_factor
    ann_vol = daily_std * math.sqrt(ann_factor)

    # Sharpe
    rf_daily = risk_free_rate / ann_factor
    excess = daily_returns - rf_daily
    sharpe = (float(np.mean(excess)) * ann_factor) / ann_vol if ann_vol > 0 else 0.0

    # Sortino
    downside = excess[excess < 0]
    downside_std = float(np.std(downside, ddof=1)) * math.sqrt(ann_factor) if len(downside) > 1 else 0.0
    sortino = (float(np.mean(excess)) * ann_factor) / downside_std if downside_std > 0 else 0.0

    # Max drawdown
    running_max = np.maximum.accumulate(values)
    drawdowns = (values - running_max) / running_max
    max_dd_idx = int(np.argmin(drawdowns))
    max_dd_pct = float(drawdowns[max_dd_idx]) * 100

    # Find drawdown start (peak before the trough)
    peak_idx = int(np.argmax(values[:max_dd_idx + 1])) if max_dd_idx > 0 else 0
    max_dd_start = dates[peak_idx].isoformat()
    max_dd_end = dates[max_dd_idx].isoformat()

    # Calmar
    calmar = abs(cagr / max_dd_pct) if max_dd_pct != 0 else 0.0

    # Win rate (% of positive daily returns)
    positive_days = int(np.sum(daily_returns > 0))
    win_rate = (positive_days / len(daily_returns) * 100) if len(daily_returns) > 0 else 0.0

    # Best / worst year from annual returns
    annual = _compute_annual_returns(daily_values)
    best_year = max(annual, key=lambda a: a["returnPct"]) if annual else None
    worst_year = min(annual, key=lambda a: a["returnPct"]) if annual else None

    return {
        "totalReturnPct": round(total_return_pct, 2),
        "cagr": round(cagr, 2),
        "annualizedVolatility": round(ann_vol * 100, 2),
        "sharpeRatio": round(sharpe, 2),
        "sortinoRatio": round(sortino, 2),
        "maxDrawdownPct": round(max_dd_pct, 2),
        "maxDrawdownStart": max_dd_start,
        "maxDrawdownEnd": max_dd_end,
        "calmarRatio": round(calmar, 2),
        "winRate": round(win_rate, 1),
        "bestYear": best_year,
        "worstYear": worst_year,
        "tradingDays": len(daily_values),
    }


# ---------------------------------------------------------------------------
# Strategy comparison
# ---------------------------------------------------------------------------


async def compare_strategies(configs: list[StrategyConfig]) -> ComparisonResult:
    """Run multiple strategies and compare their results side-by-side."""
    logger.info("backtest.compare", count=len(configs))

    results: list[BacktestResult] = []
    for cfg in configs:
        r = await run_backtest(cfg)
        results.append(r)

    strategies = []
    for cfg, res in zip(configs, results):
        strategies.append({
            "name": cfg.name,
            "metrics": res.metrics,
            "equityCurve": res.daily_values,
            "annualReturns": res.annual_returns,
            "taxPaidCents": res.tax_paid_cents,
            "dividendsReceivedCents": res.dividends_received_cents,
            "transactionCostsCents": res.transaction_costs_cents,
        })

    # Build comparison table: metric -> {strategy_name: value}
    metric_keys = [
        "totalReturnPct", "cagr", "sharpeRatio", "sortinoRatio",
        "maxDrawdownPct", "calmarRatio", "winRate", "annualizedVolatility",
    ]
    comparison_table: dict[str, dict[str, float]] = {}
    for key in metric_keys:
        comparison_table[key] = {}
        for cfg, res in zip(configs, results):
            comparison_table[key][cfg.name] = res.metrics.get(key, 0.0)

    return ComparisonResult(
        strategies=strategies,
        comparison_table=comparison_table,
    )


# ---------------------------------------------------------------------------
# Rolling backtest
# ---------------------------------------------------------------------------


async def rolling_backtest(
    config: StrategyConfig,
    window_years: int = 10,
    step_months: int = 1,
) -> RollingResult:
    """Slide a fixed-length window across history, collecting CAGR for each.

    Returns distribution statistics and all individual periods.
    """
    logger.info(
        "backtest.rolling",
        strategy=config.name,
        window_years=window_years,
        step_months=step_months,
    )

    window_days = int(window_years * 365.25)
    step_days = int(step_months * 30.44)

    # Determine available date range
    total_days = (config.end_date - config.start_date).days
    if total_days < window_days:
        raise ValueError(
            f"Date range ({total_days}d) is shorter than window ({window_days}d)"
        )

    periods: list[dict] = []
    current_start = config.start_date

    while True:
        window_end = current_start + timedelta(days=window_days)
        if window_end > config.end_date:
            break

        # Create a config for this window
        window_config = StrategyConfig(
            name=f"{config.name}_rolling_{current_start.isoformat()}",
            start_date=current_start,
            end_date=window_end,
            initial_capital_cents=config.initial_capital_cents,
            monthly_contribution_cents=config.monthly_contribution_cents,
            contribution_growth_rate=config.contribution_growth_rate,
            rebalance_frequency=config.rebalance_frequency,
            drift_threshold_pct=config.drift_threshold_pct,
            allocation=config.allocation,
            security_tickers=config.security_tickers,
            use_glidepath=config.use_glidepath,
            birth_date=config.birth_date,
            transaction_cost_pct=config.transaction_cost_pct,
            tax_rate=config.tax_rate,
            reinvest_dividends=config.reinvest_dividends,
        )

        try:
            result = await run_backtest(window_config)
            cagr = result.metrics.get("cagr", 0.0)
            periods.append({
                "startDate": current_start.isoformat(),
                "endDate": window_end.isoformat(),
                "cagr": cagr,
            })
        except Exception as exc:
            logger.warning(
                "backtest.rolling.window_failed",
                start=current_start.isoformat(),
                error=str(exc),
            )

        current_start += timedelta(days=step_days)

    # Compute distribution
    if periods:
        cagrs = [p["cagr"] for p in periods]
        cagrs_arr = np.array(cagrs)
        distribution = {
            "min": round(float(np.min(cagrs_arr)), 2),
            "p25": round(float(np.percentile(cagrs_arr, 25)), 2),
            "median": round(float(np.median(cagrs_arr)), 2),
            "p75": round(float(np.percentile(cagrs_arr, 75)), 2),
            "max": round(float(np.max(cagrs_arr)), 2),
            "count": len(periods),
        }
    else:
        distribution = {"min": 0, "p25": 0, "median": 0, "p75": 0, "max": 0, "count": 0}

    return RollingResult(distribution=distribution, periods=periods)
