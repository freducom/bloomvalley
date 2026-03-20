"""Insider tracking endpoints — trades, congress, buybacks, signals."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import structlog
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from app.db.engine import async_session
from app.db.models.insider import BuybackProgram, CongressTrade, InsiderTrade
from app.db.models.securities import Security

logger = structlog.get_logger()

router = APIRouter()

# Significance thresholds
SIGNIFICANT_VALUE_EUR_CENTS = 10_000_000  # €100,000
CLUSTER_WINDOW_DAYS = 30
CLUSTER_MIN_INSIDERS = 3
C_SUITE_ROLES = {"ceo", "cfo"}


class InsiderTradeCreate(BaseModel):
    securityId: int
    insiderName: str
    role: str
    tradeType: str
    jurisdiction: str
    tradeDate: str
    disclosureDate: str
    shares: float
    priceCents: int | None = None
    valueCents: int | None = None
    currency: str = "EUR"
    sharesAfter: float | None = None
    sourceUrl: str | None = None


def _trade_to_dict(t: InsiderTrade, sec: Security | None = None) -> dict:
    return {
        "id": t.id,
        "securityId": t.security_id,
        "ticker": sec.ticker if sec else None,
        "securityName": sec.name if sec else None,
        "insiderName": t.insider_name,
        "role": t.role,
        "tradeType": t.trade_type,
        "jurisdiction": t.jurisdiction,
        "tradeDate": t.trade_date.isoformat(),
        "disclosureDate": t.disclosure_date.isoformat(),
        "shares": str(t.shares),
        "priceCents": t.price_cents,
        "valueCents": t.value_cents,
        "currency": t.currency,
        "sharesAfter": str(t.shares_after) if t.shares_after is not None else None,
        "sourceUrl": t.source_url,
        "source": t.source,
        "isSignificant": t.is_significant,
    }


@router.get("/trades")
async def list_insider_trades(
    security_id: int | None = Query(None, alias="securityId"),
    jurisdiction: str | None = Query(None),
    trade_type: str | None = Query(None, alias="tradeType"),
    role: str | None = Query(None),
    is_significant: bool | None = Query(None, alias="isSignificant"),
    from_date: str | None = Query(None, alias="fromDate"),
    to_date: str | None = Query(None, alias="toDate"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Paginated insider trades with filters."""
    async with async_session() as session:
        query = (
            select(InsiderTrade, Security)
            .join(Security, InsiderTrade.security_id == Security.id)
            .order_by(InsiderTrade.trade_date.desc())
        )

        if security_id:
            query = query.where(InsiderTrade.security_id == security_id)
        if jurisdiction:
            query = query.where(InsiderTrade.jurisdiction == jurisdiction)
        if trade_type:
            query = query.where(InsiderTrade.trade_type == trade_type)
        if role:
            query = query.where(InsiderTrade.role == role)
        if is_significant is not None:
            query = query.where(InsiderTrade.is_significant == is_significant)
        if from_date:
            query = query.where(InsiderTrade.trade_date >= date.fromisoformat(from_date))
        if to_date:
            query = query.where(InsiderTrade.trade_date <= date.fromisoformat(to_date))

        count_q = select(func.count()).select_from(query.subquery())
        total = (await session.execute(count_q)).scalar_one()

        result = await session.execute(query.offset(offset).limit(limit))
        rows = result.all()

    data = [_trade_to_dict(t, sec) for t, sec in rows]

    return {
        "data": data,
        "pagination": {"total": total, "limit": limit, "offset": offset},
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.get("/trades/summary/{security_id}")
async def insider_summary(security_id: int):
    """Net insider buying/selling summary for 3M/6M/12M."""
    today = date.today()

    async with async_session() as session:
        sec = await session.get(Security, security_id)
        if not sec:
            raise HTTPException(404, "Security not found")

        result = await session.execute(
            select(InsiderTrade)
            .where(
                InsiderTrade.security_id == security_id,
                InsiderTrade.trade_date >= today - timedelta(days=365),
                InsiderTrade.trade_type.in_(["buy", "sell"]),  # exclude exercises
            )
            .order_by(InsiderTrade.trade_date.desc())
        )
        trades = result.scalars().all()

    def _summarize(trades_list, days):
        cutoff = today - timedelta(days=days)
        period = [t for t in trades_list if t.trade_date >= cutoff]
        buys = [t for t in period if t.trade_type == "buy"]
        sells = [t for t in period if t.trade_type == "sell"]
        net_shares = sum(float(t.shares) for t in buys) - sum(float(t.shares) for t in sells)
        net_value = sum(t.value_cents or 0 for t in buys) - sum(t.value_cents or 0 for t in sells)
        return {
            "buys": len(buys),
            "sells": len(sells),
            "netShares": round(net_shares, 4),
            "netValueCents": net_value,
        }

    # Detect signals
    signals = _detect_signals(trades, security_id)

    return {
        "data": {
            "securityId": security_id,
            "ticker": sec.ticker,
            "name": sec.name,
            "summary": {
                "3months": _summarize(trades, 90),
                "6months": _summarize(trades, 180),
                "12months": _summarize(trades, 365),
            },
            "signals": signals,
            "recentTrades": [_trade_to_dict(t, sec) for t in trades[:10]],
        },
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


def _detect_signals(trades: list[InsiderTrade], security_id: int) -> list[dict]:
    """Detect significant insider trading signals."""
    signals = []

    buys = [t for t in trades if t.trade_type == "buy"]

    # Cluster buying: 3+ distinct insiders buying within 30 days
    if buys:
        for i, trade in enumerate(buys):
            window_start = trade.trade_date - timedelta(days=CLUSTER_WINDOW_DAYS)
            cluster = [
                t for t in buys
                if window_start <= t.trade_date <= trade.trade_date
            ]
            unique_insiders = set(t.insider_name for t in cluster)
            if len(unique_insiders) >= CLUSTER_MIN_INSIDERS:
                signals.append({
                    "type": "cluster_buying",
                    "message": f"{len(unique_insiders)} insiders bought within 30 days",
                    "date": trade.trade_date.isoformat(),
                })
                break  # Only report once

    # CEO/CFO buys
    for t in buys[:5]:
        if t.role in C_SUITE_ROLES:
            signals.append({
                "type": "csuite_buy",
                "message": f"{t.role.upper()} {t.insider_name} bought {t.shares} shares",
                "date": t.trade_date.isoformat(),
            })

    return signals


@router.post("/trades")
async def create_insider_trade(body: InsiderTradeCreate):
    """Manually add an insider trade."""
    is_sig = False
    if body.valueCents and body.valueCents >= SIGNIFICANT_VALUE_EUR_CENTS:
        is_sig = True
    if body.role in C_SUITE_ROLES and body.tradeType == "buy":
        is_sig = True

    async with async_session() as session:
        sec = await session.get(Security, body.securityId)
        if not sec:
            raise HTTPException(404, "Security not found")

        trade = InsiderTrade(
            security_id=body.securityId,
            insider_name=body.insiderName,
            role=body.role,
            trade_type=body.tradeType,
            jurisdiction=body.jurisdiction,
            trade_date=date.fromisoformat(body.tradeDate),
            disclosure_date=date.fromisoformat(body.disclosureDate),
            shares=Decimal(str(body.shares)),
            price_cents=body.priceCents,
            value_cents=body.valueCents,
            currency=body.currency,
            shares_after=Decimal(str(body.sharesAfter)) if body.sharesAfter else None,
            source_url=body.sourceUrl,
            source="manual",
            is_significant=is_sig,
        )
        session.add(trade)
        await session.commit()
        await session.refresh(trade)

    return {
        "data": _trade_to_dict(trade, sec),
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.get("/congress")
async def list_congress_trades(
    security_id: int | None = Query(None, alias="securityId"),
    party: str | None = Query(None),
    chamber: str | None = Query(None),
    member_name: str | None = Query(None, alias="memberName"),
    trade_type: str | None = Query(None, alias="tradeType"),
    from_date: str | None = Query(None, alias="fromDate"),
    to_date: str | None = Query(None, alias="toDate"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """US Congress trades."""
    async with async_session() as session:
        query = select(CongressTrade).order_by(CongressTrade.trade_date.desc())

        if security_id:
            query = query.where(CongressTrade.security_id == security_id)
        if party:
            query = query.where(CongressTrade.party == party)
        if chamber:
            query = query.where(CongressTrade.chamber == chamber)
        if member_name:
            query = query.where(CongressTrade.member_name.ilike(f"%{member_name}%"))
        if trade_type:
            query = query.where(CongressTrade.trade_type == trade_type)
        if from_date:
            query = query.where(CongressTrade.trade_date >= date.fromisoformat(from_date))
        if to_date:
            query = query.where(CongressTrade.trade_date <= date.fromisoformat(to_date))

        count_q = select(func.count()).select_from(query.subquery())
        total = (await session.execute(count_q)).scalar_one()

        result = await session.execute(query.offset(offset).limit(limit))
        trades = result.scalars().all()

    data = []
    for t in trades:
        lag = (t.disclosure_date - t.trade_date).days
        data.append({
            "id": t.id,
            "securityId": t.security_id,
            "memberName": t.member_name,
            "party": t.party,
            "chamber": t.chamber,
            "state": t.state,
            "tradeType": t.trade_type,
            "tradeDate": t.trade_date.isoformat(),
            "disclosureDate": t.disclosure_date.isoformat(),
            "disclosureLagDays": lag,
            "amountRangeLowCents": t.amount_range_low_cents,
            "amountRangeHighCents": t.amount_range_high_cents,
            "currency": t.currency,
            "tickerReported": t.ticker_reported,
            "assetDescription": t.asset_description,
            "sourceUrl": t.source_url,
        })

    return {
        "data": data,
        "pagination": {"total": total, "limit": limit, "offset": offset},
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.get("/buybacks")
async def list_buybacks(
    security_id: int | None = Query(None, alias="securityId"),
    status: str | None = Query(None),
):
    """Active/recent buyback programs."""
    async with async_session() as session:
        query = (
            select(BuybackProgram, Security)
            .join(Security, BuybackProgram.security_id == Security.id)
            .order_by(BuybackProgram.announced_date.desc())
        )
        if security_id:
            query = query.where(BuybackProgram.security_id == security_id)
        if status:
            query = query.where(BuybackProgram.status == status)

        result = await session.execute(query)
        rows = result.all()

    data = []
    for bb, sec in rows:
        progress = 0
        if bb.authorized_amount_cents and bb.authorized_amount_cents > 0:
            progress = round((bb.executed_amount_cents / bb.authorized_amount_cents) * 100, 1)
        elif bb.authorized_shares and bb.authorized_shares > 0:
            progress = round((bb.executed_shares / bb.authorized_shares) * 100, 1)

        data.append({
            "id": bb.id,
            "securityId": sec.id,
            "ticker": sec.ticker,
            "name": sec.name,
            "announcedDate": bb.announced_date.isoformat(),
            "startDate": bb.start_date.isoformat() if bb.start_date else None,
            "endDate": bb.end_date.isoformat() if bb.end_date else None,
            "authorizedAmountCents": bb.authorized_amount_cents,
            "authorizedShares": bb.authorized_shares,
            "executedAmountCents": bb.executed_amount_cents,
            "executedShares": bb.executed_shares,
            "currency": bb.currency,
            "status": bb.status,
            "progressPct": progress,
            "notes": bb.notes,
        })

    return {
        "data": data,
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.get("/signals")
async def get_signals():
    """Aggregated significant signals across all held securities."""
    today = date.today()

    async with async_session() as session:
        # Recent significant trades (last 30 days)
        result = await session.execute(
            select(InsiderTrade, Security)
            .join(Security, InsiderTrade.security_id == Security.id)
            .where(
                InsiderTrade.is_significant.is_(True),
                InsiderTrade.trade_date >= today - timedelta(days=30),
            )
            .order_by(InsiderTrade.trade_date.desc())
            .limit(20)
        )
        sig_trades = result.all()

        # Check for cluster buying per security (last 30 days)
        cluster_result = await session.execute(
            select(
                InsiderTrade.security_id,
                func.count(func.distinct(InsiderTrade.insider_name)).label("insider_count"),
            )
            .where(
                InsiderTrade.trade_type == "buy",
                InsiderTrade.trade_date >= today - timedelta(days=30),
            )
            .group_by(InsiderTrade.security_id)
            .having(func.count(func.distinct(InsiderTrade.insider_name)) >= CLUSTER_MIN_INSIDERS)
        )
        clusters = cluster_result.all()

        cluster_secs = {}
        if clusters:
            sec_ids = [c.security_id for c in clusters]
            sec_result = await session.execute(
                select(Security).where(Security.id.in_(sec_ids))
            )
            cluster_secs = {s.id: s for s in sec_result.scalars().all()}

    signals = []

    for c in clusters:
        sec = cluster_secs.get(c.security_id)
        signals.append({
            "type": "cluster_buying",
            "severity": "high",
            "ticker": sec.ticker if sec else "?",
            "securityName": sec.name if sec else "?",
            "message": f"{c.insider_count} insiders bought within 30 days",
        })

    for t, sec in sig_trades:
        signals.append({
            "type": "significant_trade",
            "severity": "medium" if t.role not in C_SUITE_ROLES else "high",
            "ticker": sec.ticker,
            "securityName": sec.name,
            "message": f"{t.role.upper()} {t.insider_name} {'bought' if t.trade_type == 'buy' else 'sold'} {t.shares} shares",
            "tradeDate": t.trade_date.isoformat(),
            "valueCents": t.value_cents,
            "currency": t.currency,
        })

    return {
        "data": signals,
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }
