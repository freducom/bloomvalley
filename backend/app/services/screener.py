"""Quantitative security screener — Munger quality + Boglehead ETF screens.

Computes factor scores, z-score normalisation, composite ranking,
owner-earnings-based intrinsic value, and margin-of-safety.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import structlog
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import async_session
from app.db.models.fundamentals import SecurityFundamentals, EarningsReport
from app.db.models.prices import Price
from app.db.models.research_notes import ResearchNote
from app.db.models.securities import Security

logger = structlog.get_logger()

# ── Constants ───────────────────────────────────────────────────────────────

FINANCIAL_SECTORS = {"Financial Services", "Banks", "Insurance", "Financial"}

MUNGER_FACTOR_NAMES = [
    "roic", "roe", "debtEquity", "earningsGrowth10y",
    "earningsConsistency", "fcfYield", "grossMargin",
    "ownerEarningsGrowth", "pe", "pFcf",
]

# Direction: True = higher is better, False = lower is better
MUNGER_DIRECTION: dict[str, bool] = {
    "roic": True,
    "roe": True,
    "debtEquity": False,
    "earningsGrowth10y": True,
    "earningsConsistency": True,
    "fcfYield": True,
    "grossMargin": True,
    "ownerEarningsGrowth": True,
    "pe": False,
    "pFcf": False,
}

# Factors excluded for financial-sector companies
FINANCIAL_EXCLUDED = {"debtEquity", "grossMargin"}

ETF_SCORING_WEIGHTS = {"ter": 0.35, "trackingDifference": 0.35, "aum": 0.30}

WINSORIZE_LO = 2.5
WINSORIZE_HI = 97.5
MIN_UNIVERSE_FOR_ZSCORE = 5

# Staleness threshold (18 months)
STALE_MONTHS = 18


# ── Data classes ────────────────────────────────────────────────────────────

@dataclass
class MungerResult:
    security_id: int
    ticker: str
    name: str
    sector: str | None
    currency: str
    is_financial: bool
    factors: dict[str, float | None]
    z_scores: dict[str, float | None] = field(default_factory=dict)
    composite_score: float = 0.0
    intrinsic_value_cents: int | None = None
    margin_of_safety: float | None = None
    rank: int = 0
    available_factor_count: int = 0
    stale_fundamentals: bool = False
    earnings_years: int = 0


@dataclass
class EtfResult:
    security_id: int
    ticker: str
    name: str
    factors: dict[str, Any]
    z_scores: dict[str, float | None] = field(default_factory=dict)
    composite_score: float = 0.0
    rank: int = 0


# ── Helpers ─────────────────────────────────────────────────────────────────

def _winsorize(values: np.ndarray) -> np.ndarray:
    """Clip values at 2.5/97.5 percentile."""
    if len(values) < 2:
        return values
    lo = float(np.percentile(values, WINSORIZE_LO))
    hi = float(np.percentile(values, WINSORIZE_HI))
    return np.clip(values, lo, hi)


def _zscore_array(values: np.ndarray) -> np.ndarray:
    """Z-score an already-winsorised array. Returns zeros if std == 0."""
    std = float(np.std(values, ddof=0))
    if std == 0:
        return np.zeros_like(values)
    mean = float(np.mean(values))
    return (values - mean) / std


def _cagr(start_val: float, end_val: float, years: float) -> float | None:
    """Compound annual growth rate. Returns None on invalid inputs."""
    if start_val <= 0 or end_val <= 0 or years <= 0:
        return None
    return (end_val / start_val) ** (1.0 / years) - 1.0


def _owner_earnings(net_income: float, depreciation: float, capex: float) -> float:
    """Buffett owner earnings: net_income + D&A - min(capex, D&A)."""
    return net_income + depreciation - min(abs(capex), depreciation)


def _intrinsic_value(owner_earnings_ttm: float, growth_rate_pct: float) -> int | None:
    """Simple owner-earnings multiple. Returns cents."""
    if owner_earnings_ttm <= 0:
        return None
    # growth_rate_pct is e.g. 12 for 12%
    multiple = min(max(10, growth_rate_pct * 2), 25)
    return int(owner_earnings_ttm * multiple)


def _margin_of_safety(intrinsic_cents: int | None, market_cap_cents: int | None) -> float | None:
    if intrinsic_cents is None or market_cap_cents is None or intrinsic_cents <= 0:
        return None
    return (intrinsic_cents - market_cap_cents) / intrinsic_cents


# ── Annual EPS aggregation ──────────────────────────────────────────────────

def _annualise_eps(reports: list[EarningsReport]) -> dict[int, int]:
    """Aggregate quarterly eps_cents into annual totals.

    Returns {fiscal_year: annual_eps_cents} for years with >= 3 quarters.
    """
    by_year: dict[int, list[int]] = {}
    for r in reports:
        if r.eps_cents is not None:
            by_year.setdefault(r.fiscal_year, []).append(r.eps_cents)

    annual: dict[int, int] = {}
    for year, vals in sorted(by_year.items()):
        if len(vals) >= 3:
            # Annualise if fewer than 4 quarters
            annual[year] = int(sum(vals) * (4 / len(vals)))
        elif len(vals) == 4:
            annual[year] = sum(vals)
    return annual


def _annual_gross_margin(reports: list[EarningsReport]) -> dict[int, float]:
    """Latest annual gross margin by year (average of quarters)."""
    by_year: dict[int, list[float]] = {}
    for r in reports:
        if r.gross_margin_pct is not None:
            by_year.setdefault(r.fiscal_year, []).append(float(r.gross_margin_pct))
    return {y: sum(v) / len(v) for y, v in by_year.items() if v}


# ── Munger Screen ───────────────────────────────────────────────────────────

async def run_munger_screen(
    *,
    min_roic: float | None = None,
    min_roe: float | None = None,
    max_debt_equity: float | None = None,
    min_fcf_yield: float | None = None,
    min_gross_margin: float | None = None,
    max_pe: float | None = None,
    max_pfcf: float | None = None,
    sort_by: str = "composite",
    weights: dict[str, float] | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Execute the Munger/Buffett quality screen."""
    results: list[MungerResult] = []

    async with async_session() as session:
        # ── Load active stocks with fundamentals ──
        stocks = (await session.execute(
            select(Security)
            .where(Security.asset_class == "stock", Security.is_active.is_(True))
        )).scalars().all()

        if not stocks:
            return _empty_munger()

        sec_map = {s.id: s for s in stocks}
        sec_ids = list(sec_map.keys())

        # ── Fundamentals ──
        fund_rows = (await session.execute(
            select(SecurityFundamentals).where(
                SecurityFundamentals.security_id.in_(sec_ids)
            )
        )).scalars().all()
        fund_map: dict[int, SecurityFundamentals] = {f.security_id: f for f in fund_rows}

        # ── Earnings reports (all years) ──
        earnings_rows = (await session.execute(
            select(EarningsReport).where(
                EarningsReport.security_id.in_(sec_ids)
            ).order_by(EarningsReport.fiscal_year, EarningsReport.quarter)
        )).scalars().all()

        earnings_by_sec: dict[int, list[EarningsReport]] = {}
        for e in earnings_rows:
            earnings_by_sec.setdefault(e.security_id, []).append(e)

        # ── Latest prices (for market cap proxy / P/E) ──
        latest_prices = await _get_latest_prices(session, sec_ids)

        # ── Compute factors per security ──
        for sid, sec in sec_map.items():
            fund = fund_map.get(sid)
            reports = earnings_by_sec.get(sid, [])
            price_cents = latest_prices.get(sid)

            is_fin = sec.sector in FINANCIAL_SECTORS if sec.sector else False

            factors = _compute_munger_factors(
                sec=sec,
                fund=fund,
                reports=reports,
                price_cents=price_cents,
                is_financial=is_fin,
            )

            # Staleness check
            stale = False
            if fund and fund.updated_at:
                stale = fund.updated_at < datetime.now(timezone.utc) - timedelta(days=STALE_MONTHS * 30)

            annual_eps = _annualise_eps(reports)
            earnings_years = len(annual_eps)

            result = MungerResult(
                security_id=sid,
                ticker=sec.ticker,
                name=sec.name,
                sector=sec.sector,
                currency=sec.currency,
                is_financial=is_fin,
                factors=factors,
                stale_fundamentals=stale,
                earnings_years=earnings_years,
            )
            results.append(result)

    # ── Apply threshold filters ──
    filtered = _apply_munger_filters(
        results,
        min_roic=min_roic,
        min_roe=min_roe,
        max_debt_equity=max_debt_equity,
        min_fcf_yield=min_fcf_yield,
        min_gross_margin=min_gross_margin,
        max_pe=max_pe,
        max_pfcf=max_pfcf,
    )

    universe_size = len(results)
    passed_filters = len(filtered)

    # ── Z-score normalisation ──
    if len(filtered) >= MIN_UNIVERSE_FOR_ZSCORE:
        _compute_zscore_ranking(filtered, weights)
    else:
        # Raw values only — assign equal composite from raw factors
        for r in filtered:
            avail = {k: v for k, v in r.factors.items() if v is not None}
            r.available_factor_count = len(avail)
            r.composite_score = 0.0
            r.z_scores = {k: None for k in r.factors}

    # ── Intrinsic value & margin of safety ──
    for r in filtered:
        _compute_intrinsic_value(r)

    # ── Sort ──
    if sort_by == "composite":
        filtered.sort(key=lambda r: r.composite_score, reverse=True)
    elif sort_by in MUNGER_FACTOR_NAMES:
        filtered.sort(key=lambda r: r.factors.get(sort_by) or -1e9, reverse=MUNGER_DIRECTION.get(sort_by, True))
    else:
        filtered.sort(key=lambda r: r.composite_score, reverse=True)

    # ── Assign ranks ──
    for i, r in enumerate(filtered):
        r.rank = i + 1

    # ── Paginate ──
    page = filtered[offset: offset + limit]

    return {
        "results": [_munger_to_dict(r) for r in page],
        "universeSize": universe_size,
        "passedFilters": passed_filters,
    }


def _compute_munger_factors(
    *,
    sec: Security,
    fund: SecurityFundamentals | None,
    reports: list[EarningsReport],
    price_cents: int | None,
    is_financial: bool,
) -> dict[str, float | None]:
    """Compute all 10 Munger factors from available data."""
    factors: dict[str, float | None] = {k: None for k in MUNGER_FACTOR_NAMES}

    annual_eps = _annualise_eps(reports)
    years = sorted(annual_eps.keys())

    # ── M1: ROIC ──
    # Approximation: we don't have full balance-sheet data.
    # Use ROE from earnings if available. ROIC ~= ROE for low-debt companies.
    # When FCF and market-cap proxy are available, we can refine.
    # For now, skip ROIC if no data — will be None.

    # ── M2: ROE ──
    # Not directly stored. Skip unless we can derive from EPS / book value.
    # P/B from fundamentals + price can give us equity; ROE = EPS / (Price / P/B)
    if fund and fund.price_to_book is not None and price_cents and price_cents > 0 and annual_eps:
        latest_year = max(years) if years else None
        if latest_year and annual_eps[latest_year] > 0:
            pb = float(fund.price_to_book)
            if pb > 0:
                # book_value_per_share = price / P/B
                book_cents = price_cents / pb
                roe = annual_eps[latest_year] / book_cents if book_cents > 0 else None
                if roe is not None:
                    factors["roe"] = roe
                    # ROIC approximation (same as ROE when no debt detail)
                    factors["roic"] = roe

    # ── M3: Debt/Equity ──
    if not is_financial:
        # Not directly available; use P/B as a proxy signal.
        # D/E requires balance-sheet data we don't have per-column.
        pass

    # ── M4: 10Y Earnings Growth CAGR ──
    if len(years) >= 5:
        start_year = years[0]
        end_year = years[-1]
        span = end_year - start_year
        start_eps = annual_eps[start_year]
        end_eps = annual_eps[end_year]
        cagr = _cagr(float(start_eps), float(end_eps), float(span))
        if cagr is not None:
            factors["earningsGrowth10y"] = cagr
            # Apply confidence penalty if < 10 years
            if span < 10:
                factors["earningsGrowth10y"] = cagr * (span / 10.0)

    # ── M5: Earnings Consistency ──
    if len(years) >= 5:
        eps_vals = [float(annual_eps[y]) for y in years]
        growths = []
        for i in range(1, len(eps_vals)):
            if eps_vals[i - 1] != 0:
                growths.append((eps_vals[i] - eps_vals[i - 1]) / abs(eps_vals[i - 1]))
        if growths:
            mean_g = np.mean(growths)
            std_g = np.std(growths, ddof=0)
            if abs(mean_g) > 1e-9:
                cv = abs(std_g / mean_g)
                factors["earningsConsistency"] = 1.0 - min(cv, 2.0) / 2.0  # Normalise to 0..1
            else:
                factors["earningsConsistency"] = 0.5

    # ── M6: FCF Yield ──
    if fund and fund.free_cash_flow_cents is not None and price_cents and price_cents > 0:
        # FCF yield = FCF / market_cap.  We don't have shares outstanding,
        # so use FCF_cents / price_cents as a per-share proxy.
        fcf = fund.free_cash_flow_cents
        if fcf > 0:
            factors["fcfYield"] = fcf / price_cents

    # ── M7: Gross Margin ──
    if not is_financial:
        gm_by_year = _annual_gross_margin(reports)
        if gm_by_year:
            latest_gm_year = max(gm_by_year.keys())
            factors["grossMargin"] = gm_by_year[latest_gm_year] / 100.0  # Convert pct to ratio

    # ── M8: Owner Earnings Growth ──
    # Requires net_income and D&A which we don't have directly.
    # Approximate: owner_earnings ~= EPS (per share) since D&A and maintenance capex
    # roughly cancel when min(capex, D&A) is used.
    # Use EPS growth over 5 years as proxy.
    if len(years) >= 3:
        recent_years = years[-min(5, len(years)):]
        if len(recent_years) >= 3:
            start_eps = float(annual_eps[recent_years[0]])
            end_eps = float(annual_eps[recent_years[-1]])
            span = recent_years[-1] - recent_years[0]
            oe_cagr = _cagr(start_eps, end_eps, float(span))
            if oe_cagr is not None:
                factors["ownerEarningsGrowth"] = oe_cagr

    # ── M9: P/E ──
    if price_cents and price_cents > 0 and annual_eps:
        latest_year = max(years) if years else None
        if latest_year and annual_eps[latest_year] > 0:
            factors["pe"] = price_cents / annual_eps[latest_year]

    # ── M10: P/FCF ──
    if fund and fund.free_cash_flow_cents and fund.free_cash_flow_cents > 0 and price_cents and price_cents > 0:
        factors["pFcf"] = price_cents / fund.free_cash_flow_cents

    return factors


def _apply_munger_filters(
    results: list[MungerResult],
    *,
    min_roic: float | None,
    min_roe: float | None,
    max_debt_equity: float | None,
    min_fcf_yield: float | None,
    min_gross_margin: float | None,
    max_pe: float | None,
    max_pfcf: float | None,
) -> list[MungerResult]:
    """Apply user-specified threshold filters."""
    filtered = []
    for r in results:
        f = r.factors
        if min_roic is not None and (f["roic"] is None or f["roic"] < min_roic):
            continue
        if min_roe is not None and (f["roe"] is None or f["roe"] < min_roe):
            continue
        if max_debt_equity is not None and not r.is_financial:
            if f["debtEquity"] is not None and f["debtEquity"] > max_debt_equity:
                continue
        if min_fcf_yield is not None and (f["fcfYield"] is None or f["fcfYield"] < min_fcf_yield):
            continue
        if min_gross_margin is not None and not r.is_financial:
            if f["grossMargin"] is not None and f["grossMargin"] < min_gross_margin:
                continue
        if max_pe is not None and (f["pe"] is None or f["pe"] > max_pe):
            continue
        if max_pfcf is not None and (f["pFcf"] is None or f["pFcf"] > max_pfcf):
            continue
        filtered.append(r)
    return filtered


def _compute_zscore_ranking(
    results: list[MungerResult],
    weights: dict[str, float] | None,
) -> None:
    """Compute z-scores and composite for a list of MungerResults in-place."""
    if not results:
        return

    # Determine which factors have enough non-None values
    factor_arrays: dict[str, list[float | None]] = {k: [] for k in MUNGER_FACTOR_NAMES}
    for r in results:
        for k in MUNGER_FACTOR_NAMES:
            factor_arrays[k].append(r.factors.get(k))

    # Compute z-scores per factor
    z_lookup: dict[str, np.ndarray | None] = {}
    for fname in MUNGER_FACTOR_NAMES:
        vals = factor_arrays[fname]
        non_none_idx = [i for i, v in enumerate(vals) if v is not None]
        if len(non_none_idx) < MIN_UNIVERSE_FOR_ZSCORE:
            z_lookup[fname] = None
            continue

        raw = np.array([vals[i] for i in non_none_idx], dtype=float)
        win = _winsorize(raw)
        zs = _zscore_array(win)

        # Flip direction if lower is better
        if not MUNGER_DIRECTION.get(fname, True):
            zs = -zs

        # Map back to full array
        full_z = np.full(len(results), np.nan)
        for j, idx in enumerate(non_none_idx):
            full_z[idx] = zs[j]
        z_lookup[fname] = full_z

    # Normalise weights
    w = _normalise_weights(weights)

    # Assign z-scores and composite
    for i, r in enumerate(results):
        excluded = FINANCIAL_EXCLUDED if r.is_financial else set()
        z_dict: dict[str, float | None] = {}
        weighted_sum = 0.0
        weight_sum = 0.0

        for fname in MUNGER_FACTOR_NAMES:
            if fname in excluded:
                z_dict[fname] = None
                continue
            zarr = z_lookup.get(fname)
            if zarr is None or np.isnan(zarr[i]):
                z_dict[fname] = None
                continue
            z_val = float(zarr[i])
            z_dict[fname] = round(z_val, 4)
            factor_weight = w.get(fname, 1.0)
            if factor_weight > 0:
                weighted_sum += z_val * factor_weight
                weight_sum += factor_weight

        r.z_scores = z_dict
        r.available_factor_count = sum(1 for v in z_dict.values() if v is not None)
        r.composite_score = round(weighted_sum / weight_sum, 4) if weight_sum > 0 else 0.0


def _normalise_weights(weights: dict[str, float] | None) -> dict[str, float]:
    """Normalise user weights to sum to 1. Default: equal weight."""
    if not weights:
        return {k: 1.0 for k in MUNGER_FACTOR_NAMES}
    total = sum(abs(v) for v in weights.values() if v > 0)
    if total == 0:
        return {k: 1.0 for k in MUNGER_FACTOR_NAMES}
    return {k: max(v, 0) / total for k, v in weights.items()}


def _compute_intrinsic_value(r: MungerResult) -> None:
    """Set intrinsic_value_cents and margin_of_safety on a MungerResult."""
    # Use owner_earnings_growth as the growth rate for the multiple
    growth = r.factors.get("ownerEarningsGrowth")
    if growth is None:
        growth = r.factors.get("earningsGrowth10y")
    if growth is None:
        return

    # Need a proxy for owner earnings TTM — use latest annual EPS (in cents)
    # stored indirectly via the pe factor:  EPS = price / PE
    pe = r.factors.get("pe")
    if pe is None or pe <= 0:
        return

    # We don't have price_cents here, but we can store during factor computation.
    # Instead, use FCF as the owner-earnings proxy:
    fcf_yield = r.factors.get("fcfYield")
    if fcf_yield is not None and fcf_yield > 0:
        # owner_earnings ~ FCF (per-share basis relative to price)
        # intrinsic = owner_earnings * multiple,  where owner_earnings = fcfYield * price
        # margin_of_safety = (intrinsic - price) / intrinsic
        growth_pct = growth * 100  # convert ratio to percent
        multiple = min(max(10, growth_pct * 2), 25)
        # intrinsic / price = fcfYield * multiple
        intrinsic_over_price = fcf_yield * multiple
        if intrinsic_over_price > 0:
            r.margin_of_safety = round((intrinsic_over_price - 1.0) / intrinsic_over_price, 4)
            # Store intrinsic as a ratio to make it useful without absolute price
            r.intrinsic_value_cents = None  # Cannot determine without absolute market cap
        return

    # Fallback: use P/E-based estimation
    # EPS = price / PE;  owner_earnings ~= EPS
    # intrinsic = EPS * multiple = (price/PE) * multiple
    # margin = 1 - PE / multiple
    growth_pct = growth * 100
    multiple = min(max(10, growth_pct * 2), 25)
    if pe > 0:
        r.margin_of_safety = round(1.0 - (pe / multiple), 4)


def _munger_to_dict(r: MungerResult) -> dict[str, Any]:
    """Serialise a MungerResult to camelCase dict."""
    return {
        "securityId": r.security_id,
        "ticker": r.ticker,
        "name": r.name,
        "sector": r.sector,
        "currency": r.currency,
        "isFinancial": r.is_financial,
        "factors": {k: round(v, 6) if v is not None else None for k, v in r.factors.items()},
        "zScores": r.z_scores,
        "compositeScore": r.composite_score,
        "intrinsicValueCents": r.intrinsic_value_cents,
        "marginOfSafety": r.margin_of_safety,
        "rank": r.rank,
        "availableFactorCount": r.available_factor_count,
        "staleFundamentals": r.stale_fundamentals,
        "earningsYears": r.earnings_years,
    }


def _empty_munger() -> dict[str, Any]:
    return {"results": [], "universeSize": 0, "passedFilters": 0}


# ── Boglehead ETF Screen ───────────────────────────────────────────────────

async def run_etf_screen(
    *,
    max_ter: float | None = None,
    min_aum: float | None = None,
    domicile: str | None = None,
    sort_by: str = "composite",
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Execute the Boglehead ETF screen."""

    async with async_session() as session:
        # ── Load ETFs ──
        etfs = (await session.execute(
            select(Security)
            .where(Security.asset_class == "etf", Security.is_active.is_(True))
        )).scalars().all()

        if not etfs:
            return _empty_etf()

        sec_map = {s.id: s for s in etfs}
        sec_ids = list(sec_map.keys())

        # ── Load research notes tagged with etf_profile / justetf ──
        notes = (await session.execute(
            select(ResearchNote).where(
                ResearchNote.security_id.in_(sec_ids),
                ResearchNote.is_active.is_(True),
            )
        )).scalars().all()

        notes_by_sec: dict[int, list[ResearchNote]] = {}
        for n in notes:
            if n.security_id:
                notes_by_sec.setdefault(n.security_id, []).append(n)

    # ── Parse ETF profiles from research notes ──
    universe_size = len(etfs)
    candidates: list[EtfResult] = []

    for sid, sec in sec_map.items():
        profile = _extract_etf_profile(sec, notes_by_sec.get(sid, []))
        if profile is None:
            continue

        # ── Hard filters ──
        # B3: Distribution policy — ACC only
        dist = profile.get("distributionPolicy", "").lower()
        if dist not in ("accumulating", "acc"):
            continue

        # B4: Replication — Physical only
        repl = profile.get("replicationMethod", "").lower()
        if "physical" not in repl:
            continue

        # B5: Domicile — IE or LU
        dom = profile.get("domicile", "").upper()
        if domicile:
            # User override
            allowed = [d.strip().upper() for d in domicile.split(",")]
            if dom not in allowed:
                continue
        else:
            if dom not in ("IE", "LU"):
                continue

        # B1: TER threshold (hard filter per spec Phase 1)
        ter = profile.get("ter")
        if ter is None:
            continue
        ter_val = float(ter)
        effective_max_ter = max_ter if max_ter is not None else 0.0030
        if ter_val > effective_max_ter:
            continue

        # B2: AUM threshold (hard filter per spec Phase 1)
        aum = profile.get("aumEur")
        if aum is None:
            continue
        aum_val = float(aum)
        effective_min_aum = min_aum if min_aum is not None else 100_000_000
        if aum_val < effective_min_aum:
            continue

        # B6: Tracking difference
        td = profile.get("trackingDifference")
        td_val = float(td) if td is not None else None

        factors = {
            "ter": ter_val,
            "aumEur": aum_val,
            "distributionPolicy": profile.get("distributionPolicy"),
            "replicationMethod": profile.get("replicationMethod"),
            "domicile": dom,
            "trackingDifference": td_val,
        }

        candidates.append(EtfResult(
            security_id=sid,
            ticker=sec.ticker,
            name=sec.name,
            factors=factors,
        ))

    passed = len(candidates)

    # ── Z-score and composite ──
    if len(candidates) >= MIN_UNIVERSE_FOR_ZSCORE:
        _compute_etf_zscore(candidates)
    else:
        for c in candidates:
            c.z_scores = {"ter": None, "trackingDifference": None, "aum": None}

    # ── Sort ──
    if sort_by == "composite":
        candidates.sort(key=lambda c: c.composite_score, reverse=True)
    elif sort_by == "ter":
        candidates.sort(key=lambda c: c.factors.get("ter", 999))
    elif sort_by == "aum":
        candidates.sort(key=lambda c: c.factors.get("aumEur", 0), reverse=True)
    elif sort_by == "trackingDifference":
        candidates.sort(key=lambda c: c.factors.get("trackingDifference") or 999)
    else:
        candidates.sort(key=lambda c: c.composite_score, reverse=True)

    for i, c in enumerate(candidates):
        c.rank = i + 1

    page = candidates[offset: offset + limit]

    return {
        "results": [_etf_to_dict(c) for c in page],
        "universeSize": universe_size,
        "passedFilters": passed,
    }


def _extract_etf_profile(sec: Security, notes: list[ResearchNote]) -> dict[str, Any] | None:
    """Extract ETF profile data from research notes (justETF/Morningstar JSON).

    Looks for notes tagged with 'etf_profile' or 'justetf' and parses
    the thesis field as JSON.  Falls back to Security model fields.
    """
    profile: dict[str, Any] = {}

    # Try research notes first
    for note in notes:
        tags = note.tags or []
        tags_lower = [t.lower() for t in tags]
        if "etf_profile" in tags_lower or "justetf" in tags_lower or "morningstar" in tags_lower:
            if note.thesis:
                try:
                    parsed = json.loads(note.thesis)
                    if isinstance(parsed, dict):
                        profile.update(parsed)
                except (json.JSONDecodeError, TypeError):
                    pass

    # Enrich from Security model
    if sec.is_accumulating is not None:
        if "distributionPolicy" not in profile:
            profile["distributionPolicy"] = "Accumulating" if sec.is_accumulating else "Distributing"
    if sec.country and "domicile" not in profile:
        profile["domicile"] = sec.country

    if not profile:
        return None

    return profile


def _compute_etf_zscore(candidates: list[EtfResult]) -> None:
    """Z-score the continuous ETF factors and compute composite."""
    # TER: lower is better
    ter_vals = np.array([c.factors["ter"] for c in candidates])
    ter_win = _winsorize(ter_vals)
    ter_z = _zscore_array(ter_win)
    ter_z = -ter_z  # lower TER = higher score

    # AUM: higher is better
    aum_vals = np.array([c.factors["aumEur"] for c in candidates])
    aum_win = _winsorize(aum_vals)
    aum_z = _zscore_array(aum_win)

    # Tracking difference: lower is better (may have Nones)
    td_vals = [c.factors.get("trackingDifference") for c in candidates]
    td_non_none_idx = [i for i, v in enumerate(td_vals) if v is not None]

    td_z_full = np.full(len(candidates), np.nan)
    if len(td_non_none_idx) >= MIN_UNIVERSE_FOR_ZSCORE:
        td_raw = np.array([td_vals[i] for i in td_non_none_idx])
        td_win = _winsorize(td_raw)
        td_z = -_zscore_array(td_win)  # lower TD = higher score
        for j, idx in enumerate(td_non_none_idx):
            td_z_full[idx] = td_z[j]

    # Composite
    w_ter = ETF_SCORING_WEIGHTS["ter"]
    w_td = ETF_SCORING_WEIGHTS["trackingDifference"]
    w_aum = ETF_SCORING_WEIGHTS["aum"]

    for i, c in enumerate(candidates):
        c.z_scores = {
            "ter": round(float(ter_z[i]), 4),
            "aum": round(float(aum_z[i]), 4),
            "trackingDifference": round(float(td_z_full[i]), 4) if not np.isnan(td_z_full[i]) else None,
        }

        # Composite: re-weight if TD is missing
        score = w_ter * float(ter_z[i]) + w_aum * float(aum_z[i])
        total_w = w_ter + w_aum
        if not np.isnan(td_z_full[i]):
            score += w_td * float(td_z_full[i])
            total_w += w_td
        c.composite_score = round(score / total_w, 4) if total_w > 0 else 0.0


def _etf_to_dict(c: EtfResult) -> dict[str, Any]:
    return {
        "securityId": c.security_id,
        "ticker": c.ticker,
        "name": c.name,
        "factors": c.factors,
        "zScores": c.z_scores,
        "compositeScore": c.composite_score,
        "rank": c.rank,
    }


def _empty_etf() -> dict[str, Any]:
    return {"results": [], "universeSize": 0, "passedFilters": 0}


# ── Single security factor detail ──────────────────────────────────────────

async def get_security_factors(security_id: int) -> dict[str, Any] | None:
    """Compute and return all screening factors for a single security."""
    async with async_session() as session:
        sec = await session.get(Security, security_id)
        if not sec:
            return None

        fund_result = await session.execute(
            select(SecurityFundamentals).where(SecurityFundamentals.security_id == security_id)
        )
        fund = fund_result.scalar_one_or_none()

        earnings_result = await session.execute(
            select(EarningsReport)
            .where(EarningsReport.security_id == security_id)
            .order_by(EarningsReport.fiscal_year, EarningsReport.quarter)
        )
        reports = earnings_result.scalars().all()

        price_cents = (await _get_latest_prices(session, [security_id])).get(security_id)

    is_fin = sec.sector in FINANCIAL_SECTORS if sec.sector else False

    if sec.asset_class == "stock":
        factors = _compute_munger_factors(
            sec=sec, fund=fund, reports=list(reports),
            price_cents=price_cents, is_financial=is_fin,
        )
        annual_eps = _annualise_eps(list(reports))
        return {
            "securityId": sec.id,
            "ticker": sec.ticker,
            "name": sec.name,
            "assetClass": sec.asset_class,
            "sector": sec.sector,
            "isFinancial": is_fin,
            "screenType": "munger",
            "factors": {k: round(v, 6) if v is not None else None for k, v in factors.items()},
            "earningsYears": len(annual_eps),
            "latestPriceCents": price_cents,
        }

    if sec.asset_class == "etf":
        async with async_session() as session:
            notes_result = await session.execute(
                select(ResearchNote).where(
                    ResearchNote.security_id == security_id,
                    ResearchNote.is_active.is_(True),
                )
            )
            notes = notes_result.scalars().all()

        profile = _extract_etf_profile(sec, list(notes))
        return {
            "securityId": sec.id,
            "ticker": sec.ticker,
            "name": sec.name,
            "assetClass": sec.asset_class,
            "screenType": "etf",
            "factors": profile or {},
            "latestPriceCents": price_cents,
        }

    return {
        "securityId": sec.id,
        "ticker": sec.ticker,
        "name": sec.name,
        "assetClass": sec.asset_class,
        "screenType": None,
        "factors": {},
        "latestPriceCents": price_cents,
    }


# ── Shared DB helpers ───────────────────────────────────────────────────────

async def _get_latest_prices(session: AsyncSession, sec_ids: list[int]) -> dict[int, int]:
    """Get latest close_cents for each security."""
    if not sec_ids:
        return {}

    prices: dict[int, int] = {}

    # Subquery: max date per security
    subq = (
        select(Price.security_id, func.max(Price.date).label("max_date"))
        .where(Price.security_id.in_(sec_ids))
        .group_by(Price.security_id)
        .subquery()
    )

    result = await session.execute(
        select(Price.security_id, Price.close_cents)
        .join(subq, and_(
            Price.security_id == subq.c.security_id,
            Price.date == subq.c.max_date,
        ))
    )
    for row in result.all():
        prices[row.security_id] = row.close_cents

    return prices
