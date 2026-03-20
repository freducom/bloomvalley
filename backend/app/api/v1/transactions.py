"""Transaction list and detail endpoints."""

from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from app.db.engine import async_session
from app.db.models.accounts import Account
from app.db.models.securities import Security
from app.db.models.transactions import Transaction

logger = structlog.get_logger()

router = APIRouter()


@router.get("")
async def list_transactions(
    account_id: int | None = Query(None, alias="accountId"),
    security_id: int | None = Query(None, alias="securityId"),
    type: str | None = Query(None, description="buy, sell, dividend, transfer_in, etc."),
    from_date: str | None = Query(None, alias="fromDate"),
    to_date: str | None = Query(None, alias="toDate"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """List transactions with optional filters."""
    async with async_session() as session:
        query = select(Transaction).order_by(Transaction.trade_date.desc(), Transaction.id.desc())

        if account_id is not None:
            query = query.where(Transaction.account_id == account_id)
        if security_id is not None:
            query = query.where(Transaction.security_id == security_id)
        if type is not None:
            query = query.where(Transaction.type == type)
        if from_date:
            query = query.where(Transaction.trade_date >= from_date)
        if to_date:
            query = query.where(Transaction.trade_date <= to_date)

        # Count total
        count_q = select(func.count()).select_from(query.subquery())
        total = (await session.execute(count_q)).scalar_one()

        # Paginate
        query = query.offset(offset).limit(limit)
        result = await session.execute(query)
        txns = result.scalars().all()

        # Load related securities and accounts
        sec_ids = {t.security_id for t in txns if t.security_id}
        acct_ids = {t.account_id for t in txns}

        securities = {}
        if sec_ids:
            sec_result = await session.execute(select(Security).where(Security.id.in_(sec_ids)))
            securities = {s.id: s for s in sec_result.scalars().all()}

        accounts = {}
        if acct_ids:
            acct_result = await session.execute(select(Account).where(Account.id.in_(acct_ids)))
            accounts = {a.id: a for a in acct_result.scalars().all()}

    data = []
    for t in txns:
        sec = securities.get(t.security_id) if t.security_id else None
        acct = accounts.get(t.account_id)
        data.append({
            "id": t.id,
            "accountId": t.account_id,
            "accountName": acct.name if acct else None,
            "accountType": acct.type if acct else None,
            "securityId": t.security_id,
            "ticker": sec.ticker if sec else None,
            "securityName": sec.name if sec else None,
            "type": t.type,
            "tradeDate": t.trade_date.isoformat(),
            "settlementDate": t.settlement_date.isoformat() if t.settlement_date else None,
            "quantity": str(t.quantity),
            "priceCents": t.price_cents,
            "priceCurrency": t.price_currency,
            "totalCents": t.total_cents,
            "feeCents": t.fee_cents,
            "feeCurrency": t.fee_currency,
            "currency": t.currency,
            "notes": t.notes,
            "createdAt": t.created_at.isoformat(),
        })

    return {
        "data": data,
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
        "pagination": {
            "total": total,
            "limit": limit,
            "offset": offset,
            "hasMore": (offset + limit) < total,
        },
    }


@router.get("/summary")
async def transaction_summary():
    """Aggregate transaction stats."""
    async with async_session() as session:
        # Total count by type
        result = await session.execute(
            select(Transaction.type, func.count(Transaction.id))
            .group_by(Transaction.type)
        )
        type_counts = {r[0]: r[1] for r in result.all()}

        # Total count
        total_result = await session.execute(select(func.count(Transaction.id)))
        total = total_result.scalar_one()

        # Date range
        range_result = await session.execute(
            select(func.min(Transaction.trade_date), func.max(Transaction.trade_date))
        )
        date_range = range_result.one()

    return {
        "data": {
            "totalTransactions": total,
            "byType": type_counts,
            "earliestDate": date_range[0].isoformat() if date_range[0] else None,
            "latestDate": date_range[1].isoformat() if date_range[1] else None,
        },
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }
