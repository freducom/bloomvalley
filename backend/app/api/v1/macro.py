"""Macro dashboard API — US, Eurozone, and Finland indicators."""

from datetime import date, datetime, timedelta, timezone

import structlog
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select, text

from app.db.engine import async_session
from app.db.models.prices import MacroIndicator

logger = structlog.get_logger()

router = APIRouter()

# Indicator metadata: code -> {name, unit, category, frequency, region}
INDICATOR_META: dict[str, dict] = {
    # --- US Interest Rates ---
    "FEDFUNDS": {"name": "Fed Funds Rate", "unit": "%", "category": "us_interest_rates", "frequency": "monthly", "region": "us"},
    "DFF": {"name": "Fed Funds Effective (Daily)", "unit": "%", "category": "us_interest_rates", "frequency": "daily", "region": "us"},
    # --- US Treasury Yields ---
    "DGS2": {"name": "2-Year Treasury", "unit": "%", "category": "us_treasury_yields", "frequency": "daily", "region": "us"},
    "DGS5": {"name": "5-Year Treasury", "unit": "%", "category": "us_treasury_yields", "frequency": "daily", "region": "us"},
    "DGS10": {"name": "10-Year Treasury", "unit": "%", "category": "us_treasury_yields", "frequency": "daily", "region": "us"},
    "DGS30": {"name": "30-Year Treasury", "unit": "%", "category": "us_treasury_yields", "frequency": "daily", "region": "us"},
    "T10Y2Y": {"name": "10Y-2Y Spread", "unit": "%", "category": "us_treasury_yields", "frequency": "daily", "region": "us"},
    "T10Y3M": {"name": "10Y-3M Spread", "unit": "%", "category": "us_treasury_yields", "frequency": "daily", "region": "us"},
    # --- US Inflation ---
    "CPIAUCSL": {"name": "CPI (All Items)", "unit": "index", "category": "us_inflation", "frequency": "monthly", "region": "us"},
    "CPILFESL": {"name": "Core CPI", "unit": "index", "category": "us_inflation", "frequency": "monthly", "region": "us"},
    "PCEPI": {"name": "PCE Price Index", "unit": "index", "category": "us_inflation", "frequency": "monthly", "region": "us"},
    "T5YIE": {"name": "5Y Breakeven Inflation", "unit": "%", "category": "us_inflation", "frequency": "daily", "region": "us"},
    "T10YIE": {"name": "10Y Breakeven Inflation", "unit": "%", "category": "us_inflation", "frequency": "daily", "region": "us"},
    # --- US GDP ---
    "GDP": {"name": "GDP (Nominal)", "unit": "B USD", "category": "us_gdp", "frequency": "quarterly", "region": "us"},
    "GDPC1": {"name": "Real GDP", "unit": "B USD", "category": "us_gdp", "frequency": "quarterly", "region": "us"},
    # --- US Labor ---
    "UNRATE": {"name": "Unemployment Rate", "unit": "%", "category": "us_labor", "frequency": "monthly", "region": "us"},
    "PAYEMS": {"name": "Nonfarm Payrolls", "unit": "K", "category": "us_labor", "frequency": "monthly", "region": "us"},
    "ICSA": {"name": "Initial Jobless Claims", "unit": "", "category": "us_labor", "frequency": "weekly", "region": "us"},
    # --- US Manufacturing ---
    "MANEMP": {"name": "Manufacturing Employment", "unit": "K", "category": "us_manufacturing", "frequency": "monthly", "region": "us"},
    # --- Credit Spreads (Global) ---
    "BAMLH0A0HYM2": {"name": "HY OAS Spread", "unit": "%", "category": "credit_spreads", "frequency": "daily", "region": "global"},
    "BAMLC0A0CM": {"name": "IG OAS Spread", "unit": "%", "category": "credit_spreads", "frequency": "daily", "region": "global"},

    # --- ECB Rates ---
    "ECB_MRR": {"name": "ECB Main Refi Rate", "unit": "%", "category": "ecb_rates", "frequency": "daily", "region": "ez"},
    "ECB_DFR": {"name": "ECB Deposit Facility Rate", "unit": "%", "category": "ecb_rates", "frequency": "daily", "region": "ez"},
    "ECBMRRFR": {"name": "ECB Main Refi Rate (FRED)", "unit": "%", "category": "ecb_rates", "frequency": "daily", "region": "ez"},
    "ECBDFR": {"name": "ECB Deposit Facility (FRED)", "unit": "%", "category": "ecb_rates", "frequency": "daily", "region": "ez"},
    # --- Eurozone Bond Yields ---
    "EZ_YC_2Y": {"name": "Euro AAA 2-Year", "unit": "%", "category": "ez_bond_yields", "frequency": "daily", "region": "ez"},
    "EZ_YC_5Y": {"name": "Euro AAA 5-Year", "unit": "%", "category": "ez_bond_yields", "frequency": "daily", "region": "ez"},
    "EZ_YC_10Y": {"name": "Euro AAA 10-Year", "unit": "%", "category": "ez_bond_yields", "frequency": "daily", "region": "ez"},
    "EZ_YC_30Y": {"name": "Euro AAA 30-Year", "unit": "%", "category": "ez_bond_yields", "frequency": "daily", "region": "ez"},
    "IRLTLT01DEM156N": {"name": "Germany 10Y Bund", "unit": "%", "category": "ez_bond_yields", "frequency": "monthly", "region": "ez"},
    # --- Eurozone Inflation ---
    "EZ_HICP": {"name": "Eurozone HICP (YoY)", "unit": "%", "category": "ez_inflation", "frequency": "monthly", "region": "ez"},
    "EZ_HICP_CORE": {"name": "Eurozone Core HICP", "unit": "%", "category": "ez_inflation", "frequency": "monthly", "region": "ez"},
    "CP0000EZ19M086NEST": {"name": "Eurozone HICP (FRED)", "unit": "%", "category": "ez_inflation", "frequency": "monthly", "region": "ez"},
    # --- Eurozone GDP ---
    "EZ_GDP_YOY": {"name": "Eurozone GDP (YoY)", "unit": "%", "category": "ez_gdp", "frequency": "quarterly", "region": "ez"},
    "CLVMNACSCAB1GQEA19": {"name": "Eurozone Real GDP", "unit": "M EUR", "category": "ez_gdp", "frequency": "quarterly", "region": "ez"},
    # --- Eurozone Labor ---
    "EZ_UNEMP": {"name": "Eurozone Unemployment", "unit": "%", "category": "ez_labor", "frequency": "monthly", "region": "ez"},
    "LRHUTTTTEZM156S": {"name": "Eurozone Unemployment (FRED)", "unit": "%", "category": "ez_labor", "frequency": "monthly", "region": "ez"},

    # --- Finland ---
    "FI_HICP": {"name": "Finland HICP (YoY)", "unit": "%", "category": "fi_inflation", "frequency": "monthly", "region": "fi"},
    "FPCPITOTLZGFIN": {"name": "Finland CPI (Annual)", "unit": "%", "category": "fi_inflation", "frequency": "annual", "region": "fi"},
    "FI_UNEMP": {"name": "Finland Unemployment", "unit": "%", "category": "fi_labor", "frequency": "monthly", "region": "fi"},
    "LRHUTTTTFIM156S": {"name": "Finland Unemployment (FRED)", "unit": "%", "category": "fi_labor", "frequency": "monthly", "region": "fi"},
    "FI_GDP_YOY": {"name": "Finland GDP (YoY)", "unit": "%", "category": "fi_gdp", "frequency": "quarterly", "region": "fi"},
    "CLVMNACSCAB1GQFI": {"name": "Finland Real GDP", "unit": "M EUR", "category": "fi_gdp", "frequency": "quarterly", "region": "fi"},
}

# Deduplicate: prefer ECB source over FRED mirror when both exist
# The frontend will pick the best available
PREFERRED_CODES: dict[str, list[str]] = {
    "ecb_rates": ["ECB_MRR", "ECB_DFR", "ECBMRRFR", "ECBDFR"],
    "ez_inflation": ["EZ_HICP", "EZ_HICP_CORE", "CP0000EZ19M086NEST"],
    "ez_labor": ["EZ_UNEMP", "LRHUTTTTEZM156S"],
    "ez_gdp": ["EZ_GDP_YOY", "CLVMNACSCAB1GQEA19"],
    "fi_inflation": ["FI_HICP", "FPCPITOTLZGFIN"],
    "fi_labor": ["FI_UNEMP", "LRHUTTTTFIM156S"],
    "fi_gdp": ["FI_GDP_YOY", "CLVMNACSCAB1GQFI"],
}

REGION_ORDER = ["fi", "ez", "us", "global"]
REGION_LABELS = {
    "fi": "Finland",
    "ez": "Eurozone",
    "us": "United States",
    "global": "Global",
}

CATEGORY_ORDER = [
    # Finland
    "fi_inflation", "fi_labor", "fi_gdp",
    # Eurozone
    "ecb_rates", "ez_bond_yields", "ez_inflation", "ez_gdp", "ez_labor",
    # US
    "us_interest_rates", "us_treasury_yields", "us_inflation", "us_gdp", "us_labor", "us_manufacturing",
    # Global
    "credit_spreads",
]

CATEGORY_LABELS = {
    "fi_inflation": "Inflation",
    "fi_labor": "Labor Market",
    "fi_gdp": "GDP",
    "ecb_rates": "ECB Key Rates",
    "ez_bond_yields": "Bond Yields",
    "ez_inflation": "Inflation (HICP)",
    "ez_gdp": "GDP",
    "ez_labor": "Labor Market",
    "us_interest_rates": "Fed Rates",
    "us_treasury_yields": "Treasury Yields",
    "us_inflation": "Inflation",
    "us_gdp": "GDP",
    "us_labor": "Labor Market",
    "us_manufacturing": "Manufacturing",
    "credit_spreads": "Credit Spreads",
}


def _get_region(category: str) -> str:
    for region in REGION_ORDER:
        if category.startswith(region + "_") or category.startswith("ecb_"):
            return "ez" if category.startswith("ecb_") else region
    return "global"


@router.get("/summary")
async def macro_summary(region: str | None = Query(None, description="Filter: fi, ez, us, global")):
    """Latest value for each indicator, grouped by region and category."""
    async with async_session() as session:
        result = await session.execute(text("""
            SELECT DISTINCT ON (indicator_code)
                indicator_code, date, value, unit
            FROM macro_indicators
            ORDER BY indicator_code, date DESC
        """))
        latest = {r[0]: (r[1], float(r[2]), r[3]) for r in result.all()}

        prev_result = await session.execute(text("""
            SELECT indicator_code, date, value
            FROM (
                SELECT indicator_code, date, value,
                       ROW_NUMBER() OVER (PARTITION BY indicator_code ORDER BY date DESC) as rn
                FROM macro_indicators
            ) sub
            WHERE rn = 2
        """))
        prev_map = {r[0]: float(r[2]) for r in prev_result.all()}

    # Deduplicate: for categories with preferred codes, pick the first one that has data
    used_codes: set[str] = set()
    for cat, prefs in PREFERRED_CODES.items():
        found_primary = False
        for code in prefs:
            if code in latest:
                if not found_primary:
                    found_primary = True
                    used_codes.add(code)
                # Skip FRED mirrors if ECB primary exists
                # But include if it provides different data (e.g. core vs headline)
                meta = INDICATOR_META.get(code)
                if meta and "(FRED)" in meta["name"] and found_primary and code not in used_codes:
                    continue
                elif not found_primary:
                    used_codes.add(code)

    # Build grouped output
    regions: dict[str, dict[str, list]] = {}
    for cat in CATEGORY_ORDER:
        r = _get_region(cat)
        if region and r != region:
            continue
        if r not in regions:
            regions[r] = {}

        indicators = []
        for code, meta in INDICATOR_META.items():
            if meta["category"] != cat:
                continue
            if code not in latest:
                continue
            # Skip FRED mirrors if ECB primary has data
            if "(FRED)" in meta["name"]:
                # Check if the primary ECB code exists
                primary_exists = False
                for pref_code in PREFERRED_CODES.get(cat, []):
                    if pref_code in latest and "(FRED)" not in INDICATOR_META.get(pref_code, {}).get("name", ""):
                        primary_exists = True
                        break
                if primary_exists:
                    continue

            dt, val, unit = latest[code]
            prev_val = prev_map.get(code)
            change = round(val - prev_val, 4) if prev_val is not None else None

            indicators.append({
                "code": code,
                "name": meta["name"],
                "value": round(val, 4),
                "unit": meta["unit"],
                "date": dt.isoformat(),
                "change": change,
                "frequency": meta["frequency"],
                "region": meta["region"],
            })

        if indicators:
            regions[r][cat] = indicators

    # Structure as regions -> categories
    output = []
    for r in REGION_ORDER:
        if r not in regions:
            continue
        if region and r != region:
            continue
        categories = []
        for cat in CATEGORY_ORDER:
            if cat in regions.get(r, {}):
                categories.append({
                    "category": cat,
                    "label": CATEGORY_LABELS.get(cat, cat),
                    "indicators": regions[r][cat],
                })
        if categories:
            output.append({
                "region": r,
                "regionLabel": REGION_LABELS.get(r, r),
                "categories": categories,
            })

    return {
        "data": output,
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.get("/series/{indicator_code}")
async def macro_series(
    indicator_code: str,
    period: str = Query("1Y", description="3M, 6M, 1Y, 2Y, 5Y, MAX"),
):
    """Time series data for a single indicator."""
    meta = INDICATOR_META.get(indicator_code)
    if not meta:
        raise HTTPException(status_code=404, detail=f"Unknown indicator: {indicator_code}")

    today = date.today()
    period_map = {"3M": 90, "6M": 180, "1Y": 365, "2Y": 730, "5Y": 1825, "MAX": 36500}
    days = period_map.get(period.upper(), 365)
    from_date = date.fromordinal(max(1, today.toordinal() - days))

    async with async_session() as session:
        result = await session.execute(
            select(MacroIndicator)
            .where(
                MacroIndicator.indicator_code == indicator_code,
                MacroIndicator.date >= from_date,
            )
            .order_by(MacroIndicator.date)
        )
        rows = result.scalars().all()

    data_points = [
        {"time": r.date.isoformat(), "value": round(float(r.value), 4)}
        for r in rows
    ]

    return {
        "data": {
            "code": indicator_code,
            "name": meta["name"],
            "unit": meta["unit"],
            "category": meta["category"],
            "region": meta["region"],
            "points": data_points,
        },
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.get("/yield-curve")
async def yield_curve(
    curve: str = Query("us", description="us or ez"),
    as_of: date | None = Query(None),
):
    """Yield curve snapshot — US Treasuries or Euro AAA sovereign."""
    if curve == "ez":
        tenors = ["EZ_YC_2Y", "EZ_YC_5Y", "EZ_YC_10Y", "EZ_YC_30Y"]
        tenor_labels = {"EZ_YC_2Y": "2Y", "EZ_YC_5Y": "5Y", "EZ_YC_10Y": "10Y", "EZ_YC_30Y": "30Y"}
    else:
        tenors = ["DGS2", "DGS5", "DGS10", "DGS30"]
        tenor_labels = {"DGS2": "2Y", "DGS5": "5Y", "DGS10": "10Y", "DGS30": "30Y"}

    async with async_session() as session:
        points = []
        for tenor in tenors:
            q = select(MacroIndicator).where(MacroIndicator.indicator_code == tenor)
            if as_of:
                q = q.where(MacroIndicator.date <= as_of)
            q = q.order_by(MacroIndicator.date.desc()).limit(1)
            result = await session.execute(q)
            row = result.scalar_one_or_none()
            if row:
                points.append({
                    "tenor": tenor_labels[tenor],
                    "code": tenor,
                    "yield": round(float(row.value), 3),
                    "date": row.date.isoformat(),
                })

        comparisons = []
        for offset_label, offset_days in [("3M ago", 90), ("1Y ago", 365)]:
            target = (as_of or date.today()) - timedelta(days=offset_days)
            comp_points = []
            for tenor in tenors:
                result = await session.execute(
                    select(MacroIndicator)
                    .where(
                        MacroIndicator.indicator_code == tenor,
                        MacroIndicator.date <= target,
                    )
                    .order_by(MacroIndicator.date.desc())
                    .limit(1)
                )
                row = result.scalar_one_or_none()
                if row:
                    comp_points.append({
                        "tenor": tenor_labels[tenor],
                        "yield": round(float(row.value), 3),
                    })
            if comp_points:
                comparisons.append({"label": offset_label, "points": comp_points})

    return {
        "data": {
            "curve": curve,
            "curveLabel": "Euro AAA Sovereign" if curve == "ez" else "US Treasury",
            "current": points,
            "comparisons": comparisons,
        },
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


# ---------------------------------------------------------------------------
# Macro Regime Assessment (F07)
# ---------------------------------------------------------------------------

# Maps regime signal names to numeric scores
_REGIME_SCORES: dict[str, float] = {
    "expansion": 1.0,
    "recovery": 0.5,
    "neutral": 0.0,
    "slowdown": -0.5,
    "recession": -1.0,
}

# Static asset-class implications per regime
_ASSET_IMPLICATIONS: dict[str, dict[str, str]] = {
    "expansion": {
        "equities": "Overweight — expansionary conditions favor risk assets",
        "fixedIncome": "Underweight — rising rates likely",
        "crypto": "Neutral — follow risk sentiment",
        "cash": "Underweight — opportunity cost high",
    },
    "recovery": {
        "equities": "Overweight — early cycle recovery favors equities",
        "fixedIncome": "Neutral — rates stabilizing",
        "crypto": "Neutral — improving sentiment",
        "cash": "Underweight — deploy into risk assets",
    },
    "slowdown": {
        "equities": "Neutral — reduce cyclical exposure, favor defensives",
        "fixedIncome": "Overweight — flight to quality likely",
        "crypto": "Underweight — risk-off environment",
        "cash": "Neutral — preserve optionality",
    },
    "recession": {
        "equities": "Underweight — earnings contraction expected",
        "fixedIncome": "Overweight — rate cuts and flight to safety",
        "crypto": "Underweight — risk assets under pressure",
        "cash": "Overweight — capital preservation priority",
    },
}

# Indicator codes used by the regime model (DB codes)
_REGIME_INDICATORS = {
    "pmi": "UMCSENT",  # U Michigan Consumer Sentiment (>80 = expansion, <80 = contraction)
    "treasury_10y": "DGS10",
    "treasury_2y": "DGS2",
    "hy_oas": "BAMLH0A0HYM2",
    "unemployment": "EZ_UNEMP",
    "hicp": "EZ_HICP",
}


async def _fetch_indicator_history(
    session, code: str, months: int = 6,
) -> list[tuple[date, float]]:
    """Fetch recent data points for an indicator, ordered by date ascending."""
    from_date = date.today() - timedelta(days=months * 31)
    result = await session.execute(
        select(MacroIndicator.date, MacroIndicator.value)
        .where(
            MacroIndicator.indicator_code == code,
            MacroIndicator.date >= from_date,
        )
        .order_by(MacroIndicator.date)
    )
    return [(r[0], float(r[1])) for r in result.all()]


def _latest_and_3m_avg(
    history: list[tuple[date, float]],
) -> tuple[float | None, float | None]:
    """Return (latest_value, 3-month average) from a history list."""
    if not history:
        return None, None
    latest = history[-1][1]
    cutoff = date.today() - timedelta(days=90)
    three_month = [v for d, v in history if d >= cutoff]
    avg = sum(three_month) / len(three_month) if three_month else None
    return latest, avg


def _classify_pmi(latest: float, avg_3m: float) -> tuple[str, str]:
    """Consumer sentiment / PMI regime signal.

    Auto-detects scale:
    - PMI: threshold 50 (values typically 30-70)
    - OECD CLI: threshold 100 (values typically 95-105)
    - U Michigan Consumer Sentiment: threshold 80 (values typically 50-110)
    """
    if latest > 80:
        threshold = 100.0  # OECD CLI scale
    elif latest > 60:
        threshold = 80.0   # Consumer sentiment scale
    else:
        threshold = 50.0   # PMI scale

    rising = latest > avg_3m
    if latest > threshold:
        if rising:
            return "expansion", f"Above {threshold:.0f} ({latest:.1f}) and rising"
        return "slowdown", f"Above {threshold:.0f} ({latest:.1f}) but falling"
    else:
        if rising:
            return "recovery", f"Below {threshold:.0f} ({latest:.1f}) but rising"
        return "recession", f"Below {threshold:.0f} ({latest:.1f}) and falling"


def _classify_yield_curve(spread_bps: float) -> tuple[str, str]:
    """Yield curve spread signal. spread_bps is in basis points."""
    if spread_bps < 0:
        return "recession", f"Inverted ({spread_bps:.0f}bps)"
    if spread_bps <= 50:
        return "slowdown", f"Flat ({spread_bps:.0f}bps)"
    if spread_bps <= 150:
        return "neutral", f"Normal slope ({spread_bps:.0f}bps)"
    return "expansion", f"Steep ({spread_bps:.0f}bps)"


def _classify_credit(latest: float, avg_3m: float | None) -> tuple[str, str]:
    """Credit spread signal. latest is OAS in bps (stored as percentage, multiply by 100)."""
    # BAMLH0A0HYM2 is stored in percentage points (e.g. 3.5 = 350bps)
    bps = latest * 100
    widening = avg_3m is not None and latest > avg_3m
    trend = "widening" if widening else "stable/tightening"
    if bps < 300:
        return "expansion", f"Tight ({bps:.0f}bps, {trend})"
    if bps <= 500:
        if widening:
            return "slowdown", f"Normal but widening ({bps:.0f}bps)"
        return "neutral", f"Normal ({bps:.0f}bps, {trend})"
    return "recession", f"Wide ({bps:.0f}bps, {trend})"


def _classify_unemployment(latest: float, avg_3m: float | None) -> tuple[str, str]:
    """Unemployment regime signal."""
    if avg_3m is None:
        return "neutral", f"Unemployment at {latest:.1f}% (no trend data)"
    diff = latest - avg_3m
    if diff >= 0.5:
        return "recession", f"Rising ({latest:.1f}%, +{diff:.1f}pp vs 3M avg)"
    if diff <= -0.2:
        return "expansion", f"Falling ({latest:.1f}%, {diff:.1f}pp vs 3M avg)"
    return "neutral", f"Stable ({latest:.1f}%, {diff:+.1f}pp vs 3M avg)"


def _classify_inflation(latest: float, avg_3m: float | None) -> tuple[str, str]:
    """HICP inflation regime signal."""
    rising = avg_3m is not None and latest > avg_3m
    if latest > 3 and rising:
        return "slowdown", f"Overheating ({latest:.1f}% and rising)"
    if latest < 1:
        return "recession", f"Deflation risk ({latest:.1f}%)"
    if avg_3m is not None and (avg_3m - latest) > 0.5:
        return "recession", f"Falling fast ({latest:.1f}%, was {avg_3m:.1f}%)"
    return "neutral", f"Stable ({latest:.1f}%)"


@router.get("/regime")
async def macro_regime():
    """Classify the current macro regime using a weighted composite of indicators."""
    async with async_session() as session:
        # Fetch history for all regime indicators
        histories: dict[str, list[tuple[date, float]]] = {}
        for key, code in _REGIME_INDICATORS.items():
            histories[key] = await _fetch_indicator_history(session, code)

    signals: list[dict] = []
    signal_scores: list[tuple[float, float]] = []  # (weight, score)

    # 1. PMI (30%)
    pmi_latest, pmi_avg = _latest_and_3m_avg(histories["pmi"])
    if pmi_latest is not None and pmi_avg is not None:
        sig, detail = _classify_pmi(pmi_latest, pmi_avg)
        signals.append({
            "name": "Sentiment/PMI",
            "weight": 0.30,
            "signal": sig,
            "value": round(pmi_latest, 1),
            "detail": detail,
        })
        signal_scores.append((0.30, _REGIME_SCORES[sig]))
    else:
        signals.append({
            "name": "Sentiment/PMI",
            "weight": 0.30,
            "signal": "unavailable",
            "value": None,
            "detail": "No PMI/CLI data available — run fred_macro_indicators pipeline",
        })

    # 2. Yield Curve (25%)
    t10_latest, _ = _latest_and_3m_avg(histories["treasury_10y"])
    t2_latest, _ = _latest_and_3m_avg(histories["treasury_2y"])
    if t10_latest is not None and t2_latest is not None:
        spread_pct = t10_latest - t2_latest  # in percentage points
        spread_bps = spread_pct * 100
        sig, detail = _classify_yield_curve(spread_bps)
        signals.append({
            "name": "Yield Curve",
            "weight": 0.25,
            "signal": sig,
            "value": round(spread_pct, 4),
            "detail": detail,
        })
        signal_scores.append((0.25, _REGIME_SCORES[sig]))
    else:
        signals.append({
            "name": "Yield Curve",
            "weight": 0.25,
            "signal": "unavailable",
            "value": None,
            "detail": "Insufficient treasury yield data",
        })

    # 3. Credit Spreads (20%)
    hy_latest, hy_avg = _latest_and_3m_avg(histories["hy_oas"])
    if hy_latest is not None:
        sig, detail = _classify_credit(hy_latest, hy_avg)
        signals.append({
            "name": "Credit Spreads",
            "weight": 0.20,
            "signal": sig,
            "value": round(hy_latest, 2),
            "detail": detail,
        })
        signal_scores.append((0.20, _REGIME_SCORES[sig]))
    else:
        signals.append({
            "name": "Credit Spreads",
            "weight": 0.20,
            "signal": "unavailable",
            "value": None,
            "detail": "No HY OAS data available",
        })

    # 4. Unemployment (15%)
    unemp_latest, unemp_avg = _latest_and_3m_avg(histories["unemployment"])
    if unemp_latest is not None:
        sig, detail = _classify_unemployment(unemp_latest, unemp_avg)
        signals.append({
            "name": "Unemployment",
            "weight": 0.15,
            "signal": sig,
            "value": round(unemp_latest, 1),
            "detail": detail,
        })
        signal_scores.append((0.15, _REGIME_SCORES[sig]))
    else:
        signals.append({
            "name": "Unemployment",
            "weight": 0.15,
            "signal": "unavailable",
            "value": None,
            "detail": "No unemployment data available",
        })

    # 5. Inflation (10%)
    hicp_latest, hicp_avg = _latest_and_3m_avg(histories["hicp"])
    if hicp_latest is not None:
        sig, detail = _classify_inflation(hicp_latest, hicp_avg)
        signals.append({
            "name": "Inflation",
            "weight": 0.10,
            "signal": sig,
            "value": round(hicp_latest, 1),
            "detail": detail,
        })
        signal_scores.append((0.10, _REGIME_SCORES[sig]))
    else:
        signals.append({
            "name": "Inflation",
            "weight": 0.10,
            "signal": "unavailable",
            "value": None,
            "detail": "No HICP data available",
        })

    # Compute weighted composite score
    if signal_scores:
        total_weight = sum(w for w, _ in signal_scores)
        composite = sum(w * s for w, s in signal_scores) / total_weight if total_weight > 0 else 0.0
    else:
        composite = 0.0

    # Determine regime from composite score
    if composite > 0.4:
        regime = "expansion"
    elif composite > 0:
        regime = "recovery"
    elif composite > -0.4:
        regime = "slowdown"
    else:
        regime = "recession"

    # Confidence: percentage of available signals that agree with the regime
    available_signals = [s for s in signals if s["signal"] != "unavailable"]
    if available_signals:
        # Map regime to its score, count signals on the same side
        regime_score = _REGIME_SCORES[regime]
        agreeing = sum(
            1 for s in available_signals
            if _REGIME_SCORES.get(s["signal"], 0) * regime_score > 0
            or s["signal"] == regime
        )
        agreement_pct = agreeing / len(available_signals)
        if agreement_pct >= 0.7:
            confidence = "high"
        elif agreement_pct >= 0.5:
            confidence = "medium"
        else:
            confidence = "low"
    else:
        confidence = "low"

    # Previous regime and regime start date — computed from 1-month-ago snapshot
    # by re-evaluating historical data as of ~30 days ago
    previous_regime = None
    regime_start_date = None
    # We approximate by checking if the regime would differ with data from 30 days ago
    # For simplicity, return null — a full implementation would store regime history
    # TODO: persist regime assessments for historical tracking

    return {
        "data": {
            "regime": regime,
            "confidence": confidence,
            "compositeScore": round(composite, 4),
            "signals": signals,
            "assetClassImplications": _ASSET_IMPLICATIONS[regime],
            "previousRegime": previous_regime,
            "regimeStartDate": regime_start_date,
        },
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }
