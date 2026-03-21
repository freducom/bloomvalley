"""Nordnet portfolio import endpoints.

Supports multi-file import (one file per account), name-based security matching,
and reconciliation against existing holdings to detect changes.
"""

from datetime import date, datetime, timezone
from decimal import Decimal

import structlog
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import case, func, literal_column, select

from app.db.engine import async_session
from app.db.models.accounts import Account
from app.db.models.imports import Import, ImportRow
from app.db.models.securities import Security
from app.db.models.transactions import Transaction
from app.services.nordnet_parser import ACCOUNT_TYPE_MAP, parse_nordnet_export

logger = structlog.get_logger()

router = APIRouter()


# ── Name matching helpers ────────────────────────────────────────────────

def _normalize_name(name: str) -> str:
    """Normalize a security name for fuzzy matching."""
    n = name.lower().strip()
    # Remove common suffixes
    for suffix in [" oyj", " abp", " plc", " inc.", " inc", " ltd", " sa",
                   " ab", " ag", " se", " nv", " n.v.", " corp", " corp."]:
        if n.endswith(suffix):
            n = n[: -len(suffix)].strip()
    # Remove class designators like "A", "B" at end
    # But keep them for matching — "Kesko A" != "Kesko B"
    return n


def _match_security(
    name: str,
    currency: str | None,
    securities: list,
    name_index: dict[str, list],
) -> tuple | None:
    """Try to match a Nordnet name to a security.

    Returns (security, match_status) or None.
    Strategy:
    1. Exact normalized name match
    2. Name starts-with match (Nordnet names are often longer)
    3. Security name starts-with the import name
    """
    norm = _normalize_name(name)

    # 1. Exact match
    if norm in name_index:
        candidates = name_index[norm]
        if len(candidates) == 1:
            return candidates[0], "auto_matched"
        # Multiple matches — try currency disambiguation
        if currency:
            for s in candidates:
                if s.currency == currency:
                    return s, "auto_matched"
        return candidates[0], "auto_matched"

    # 2. Import name starts with security name (e.g. "Berkshire Hathaway B" matches "Berkshire Hathaway")
    best_match = None
    best_len = 0
    for sec_norm, secs in name_index.items():
        if norm.startswith(sec_norm) and len(sec_norm) > best_len:
            best_match = secs[0]
            best_len = len(sec_norm)
        elif sec_norm.startswith(norm) and len(norm) > best_len:
            best_match = secs[0]
            best_len = len(norm)

    if best_match and best_len >= 4:  # Require at least 4 chars overlap
        return best_match, "auto_matched"

    return None


def _guess_asset_class(name: str) -> str:
    """Guess asset class from the security name."""
    n = name.lower()
    etf_keywords = ["etf", "ucits", "ishares", "xtrackers", "vanguard", "amundi",
                     "spdr", "lyxor", "wisdomtree", "invesco"]
    fund_keywords = ["rahasto", "fond", "fund", "yrityskorko", "korkorahasto"]
    if any(k in n for k in etf_keywords):
        return "etf"
    if any(k in n for k in fund_keywords):
        return "etf"  # treat funds as etf for simplicity
    return "stock"


def _generate_ticker(name: str) -> str:
    """Generate a placeholder ticker from the name (e.g. 'Kesko B' -> 'KESKO-B')."""
    # Take first meaningful words, uppercase, join with dash
    words = name.split()[:3]
    ticker = "-".join(w.upper().rstrip(".,") for w in words if len(w) > 1)
    # Limit length
    return ticker[:20] if ticker else "UNKNOWN"


def _build_name_index(securities: list) -> dict[str, list]:
    """Build a normalized-name -> [Security] index."""
    index: dict[str, list] = {}
    for s in securities:
        norm = _normalize_name(s.name)
        index.setdefault(norm, []).append(s)
        # Also index by ticker base (without exchange suffix)
        ticker_base = s.ticker.split(".")[0].lower()
        index.setdefault(ticker_base, []).append(s)
    return index


# ── Reconciliation ───────────────────────────────────────────────────────

async def _get_current_holdings(account_id: int) -> dict[int, Decimal]:
    """Get current holdings for an account: {security_id: net_quantity}."""
    async with async_session() as session:
        qty_case = case(
            (Transaction.type.in_(["buy", "transfer_in"]), Transaction.quantity),
            (Transaction.type.in_(["sell", "transfer_out"]), -Transaction.quantity),
            else_=literal_column("0"),
        )
        result = await session.execute(
            select(
                Transaction.security_id,
                func.sum(qty_case).label("net_qty"),
            )
            .where(
                Transaction.account_id == account_id,
                Transaction.security_id.isnot(None),
                Transaction.type.in_(["buy", "sell", "transfer_in", "transfer_out"]),
            )
            .group_by(Transaction.security_id)
        )
        holdings = {}
        for row in result.all():
            qty = row.net_qty
            if qty and qty > 0:
                holdings[row.security_id] = qty
        return holdings


# ── Request models ───────────────────────────────────────────────────────

class ParseRequest(BaseModel):
    text: str
    account_type: str | None = None  # "regular", "osakesaastotili", etc.
    account_name: str | None = None


class ParseMultiRequest(BaseModel):
    files: list[ParseRequest]


class MapRowRequest(BaseModel):
    security_id: int


# ── Endpoints ────────────────────────────────────────────────────────────

@router.post("/parse")
async def parse_import(req: ParseRequest):
    """Parse a single Nordnet export and create an import record with matched rows."""
    try:
        parsed_rows = parse_nordnet_export(req.text)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not parsed_rows:
        raise HTTPException(status_code=400, detail="No data rows found")

    async with async_session() as session:
        # Load all securities for matching
        result = await session.execute(
            select(Security).where(Security.is_active.is_(True))
        )
        all_securities = result.scalars().all()

        isin_map = {s.isin: s for s in all_securities if s.isin}
        ticker_map = {s.ticker.upper(): s for s in all_securities}
        name_index = _build_name_index(all_securities)

        # Determine account type
        acct_type = req.account_type or "regular"

        # Find or create account
        acct_result = await session.execute(
            select(Account).where(
                Account.type == acct_type,
                Account.institution == "Nordnet",
                Account.is_active.is_(True),
            )
        )
        account = acct_result.scalar_one_or_none()
        if not account:
            type_labels = {
                "regular": "AOT",
                "osakesaastotili": "OST",
                "pension": "Pension",
            }
            account = Account(
                name=req.account_name or f"Nordnet {type_labels.get(acct_type, acct_type)}",
                type=acct_type,
                institution="Nordnet",
                currency="EUR",
            )
            session.add(account)
            await session.flush()

        # Get current holdings for reconciliation
        current_holdings = await _get_current_holdings(account.id)

        # Create import record
        import_record = Import(
            source="nordnet",
            status="parsing",
            account_id=account.id,
            raw_text=req.text,
            total_rows=len(parsed_rows),
        )
        session.add(import_record)
        await session.flush()

        matched = 0
        unmatched = 0
        new_holdings: dict[int, Decimal] = {}  # security_id -> imported qty

        for row in parsed_rows:
            # Try matching: ISIN → ticker → name
            security = None
            match_status = "unrecognized"

            isin = row.get("isin")
            ticker = row.get("ticker", "")
            name = row.get("name", "")
            currency = row.get("currency")

            if isin and isin in isin_map:
                security = isin_map[isin]
                match_status = "auto_matched"
            elif ticker and ticker.upper() in ticker_map:
                security = ticker_map[ticker.upper()]
                match_status = "ticker_matched"
            elif name:
                match = _match_security(name, currency, all_securities, name_index)
                if match:
                    security, match_status = match

            # Auto-create unknown securities so imports always succeed
            if not security and name:
                asset_class = _guess_asset_class(name)
                new_sec = Security(
                    ticker=_generate_ticker(name),
                    name=name,
                    asset_class=asset_class,
                    currency=currency or "EUR",
                )
                session.add(new_sec)
                await session.flush()  # get the id
                security = new_sec
                match_status = "auto_created"
                # Update indexes for subsequent rows
                all_securities.append(new_sec)
                norm = _normalize_name(name)
                name_index.setdefault(norm, []).append(new_sec)
                ticker_map[new_sec.ticker.upper()] = new_sec
                logger.info("security_auto_created", name=name, ticker=new_sec.ticker,
                            currency=currency, asset_class=asset_class)

            # Determine action based on reconciliation
            action = "transfer_in"
            imported_qty = row.get("quantity") or Decimal("0")

            if security:
                matched += 1
                new_holdings[security.id] = imported_qty
                old_qty = current_holdings.get(security.id, Decimal("0"))

                if old_qty == 0:
                    action = "transfer_in"  # New position
                elif imported_qty > old_qty:
                    action = "buy"  # Increased position
                elif imported_qty < old_qty:
                    action = "sell"  # Decreased position
                else:
                    action = "skip"  # No change
            else:
                unmatched += 1

            import_row = ImportRow(
                import_id=import_record.id,
                row_number=row["row_number"],
                raw_data=row["raw_data"],
                parsed_ticker=row.get("ticker"),
                parsed_isin=row.get("isin"),
                parsed_name=row.get("name"),
                parsed_quantity=imported_qty,
                parsed_avg_price_cents=row.get("avg_price_cents"),
                parsed_market_value_cents=row.get("market_value_cents"),
                parsed_currency=row.get("currency"),
                parsed_account_type=req.account_type,
                match_status=match_status,
                action=action,
                security_id=security.id if security else None,
            )
            session.add(import_row)

        # Detect closed positions (in old holdings but not in new import)
        closed_securities = set(current_holdings.keys()) - set(new_holdings.keys())
        for sec_id in closed_securities:
            sec = await session.get(Security, sec_id)
            if not sec:
                continue
            old_qty = current_holdings[sec_id]
            # Add a synthetic "sell all" row
            import_row = ImportRow(
                import_id=import_record.id,
                row_number=len(parsed_rows) + 1,
                raw_data={"_synthetic": True, "reason": "position_closed"},
                parsed_ticker=sec.ticker,
                parsed_name=sec.name,
                parsed_quantity=Decimal("0"),
                parsed_avg_price_cents=None,
                parsed_market_value_cents=0,
                parsed_currency=sec.currency,
                parsed_account_type=req.account_type,
                match_status="auto_matched",
                action="sell",
                security_id=sec_id,
            )
            session.add(import_row)
            matched += 1

        import_record.status = "parsed"
        import_record.matched_rows = matched
        import_record.unmatched_rows = unmatched
        import_record.import_metadata = {
            "account_type": acct_type,
            "account_id": account.id,
            "current_holdings_count": len(current_holdings),
            "new_holdings_count": len(new_holdings),
            "closed_positions": len(closed_securities),
        }

        await session.commit()
        await session.refresh(import_record)

    return {
        "data": {
            "id": import_record.id,
            "status": import_record.status,
            "accountId": account.id,
            "accountName": account.name,
            "totalRows": import_record.total_rows,
            "matchedRows": import_record.matched_rows,
            "unmatchedRows": import_record.unmatched_rows,
            "metadata": import_record.import_metadata,
        },
        "meta": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cacheAge": None,
            "stale": False,
        },
    }


@router.post("/parse-multi")
async def parse_multi_import(req: ParseMultiRequest):
    """Parse multiple Nordnet exports (one per account) in one request."""
    results = []
    for file_req in req.files:
        single_req = ParseRequest(
            text=file_req.text,
            account_type=file_req.account_type,
            account_name=file_req.account_name,
        )
        result = await parse_import(single_req)
        results.append(result["data"])

    return {
        "data": results,
        "meta": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cacheAge": None,
            "stale": False,
        },
    }


@router.get("/{import_id}")
async def get_import(import_id: int):
    """Get import details with all rows."""
    async with async_session() as session:
        import_record = await session.get(Import, import_id)
        if not import_record:
            raise HTTPException(status_code=404, detail="Import not found")

        result = await session.execute(
            select(ImportRow)
            .where(ImportRow.import_id == import_id)
            .order_by(ImportRow.row_number)
        )
        rows = result.scalars().all()

    return {
        "data": {
            "id": import_record.id,
            "source": import_record.source,
            "status": import_record.status,
            "accountId": import_record.account_id,
            "totalRows": import_record.total_rows,
            "matchedRows": import_record.matched_rows,
            "unmatchedRows": import_record.unmatched_rows,
            "metadata": import_record.import_metadata,
            "createdAt": import_record.created_at.isoformat(),
            "rows": [
                {
                    "id": r.id,
                    "rowNumber": r.row_number,
                    "ticker": r.parsed_ticker,
                    "isin": r.parsed_isin,
                    "name": r.parsed_name,
                    "quantity": str(r.parsed_quantity) if r.parsed_quantity is not None else None,
                    "avgPriceCents": r.parsed_avg_price_cents,
                    "marketValueCents": r.parsed_market_value_cents,
                    "currency": r.parsed_currency,
                    "accountType": r.parsed_account_type,
                    "matchStatus": r.match_status,
                    "action": r.action,
                    "securityId": r.security_id,
                    "errorMessage": r.error_message,
                }
                for r in rows
            ],
        },
        "meta": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cacheAge": None,
            "stale": False,
        },
    }


@router.post("/{import_id}/rows/{row_id}/map")
async def map_import_row(import_id: int, row_id: int, req: MapRowRequest):
    """Manually map an unrecognized row to a security."""
    async with async_session() as session:
        row = await session.get(ImportRow, row_id)
        if not row or row.import_id != import_id:
            raise HTTPException(status_code=404, detail="Import row not found")

        security = await session.get(Security, req.security_id)
        if not security:
            raise HTTPException(status_code=404, detail="Security not found")

        old_status = row.match_status
        row.security_id = security.id
        row.match_status = "manual_mapped"
        if row.action == "skip":
            row.action = "transfer_in"

        import_record = await session.get(Import, import_id)
        if import_record and old_status == "unrecognized":
            import_record.matched_rows += 1
            import_record.unmatched_rows = max(0, import_record.unmatched_rows - 1)

        await session.commit()

    return {
        "data": {"rowId": row_id, "securityId": req.security_id, "matchStatus": "manual_mapped"},
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat(), "cacheAge": None, "stale": False},
    }


@router.post("/{import_id}/confirm")
async def confirm_import(import_id: int):
    """Confirm import — creates reconciliation transactions.

    For each matched row:
    - transfer_in: new position → create transfer_in transaction
    - buy: quantity increased → create buy for the difference
    - sell: quantity decreased → create sell for the difference
    - sell (closed): position gone → sell all remaining
    - skip: no change → no transaction
    """
    async with async_session() as session:
        import_record = await session.get(Import, import_id)
        if not import_record:
            raise HTTPException(status_code=404, detail="Import not found")
        if import_record.status != "parsed":
            raise HTTPException(
                status_code=400,
                detail=f"Import is '{import_record.status}', expected 'parsed'",
            )

        account_id = import_record.account_id
        if not account_id:
            raise HTTPException(status_code=400, detail="No account linked to import")

        result = await session.execute(
            select(ImportRow)
            .where(ImportRow.import_id == import_id)
            .where(ImportRow.security_id.isnot(None))
            .order_by(ImportRow.row_number)
        )
        rows = result.scalars().all()

        # Get current holdings for delta calculation
        current_holdings = await _get_current_holdings(account_id)

        transactions_created = 0
        today = date.today()

        for row in rows:
            action = row.action
            if action == "skip":
                continue

            security_id = row.security_id
            imported_qty = row.parsed_quantity or Decimal("0")
            old_qty = current_holdings.get(security_id, Decimal("0"))
            currency = row.parsed_currency or "EUR"

            if action == "transfer_in":
                # New position — transfer in full quantity
                if imported_qty <= 0:
                    continue
                delta_qty = imported_qty
                tx_type = "transfer_in"
                price_cents = row.parsed_avg_price_cents
                # Cost basis = avg price * quantity (not market value)
                if price_cents and price_cents > 0:
                    total_cents = int(price_cents * float(delta_qty))
                else:
                    total_cents = row.parsed_market_value_cents or 0

            elif action == "buy":
                # Increased position — buy the difference
                delta_qty = imported_qty - old_qty
                if delta_qty <= 0:
                    continue
                tx_type = "buy"
                # Estimate price from avg cost or market value
                if row.parsed_avg_price_cents:
                    price_cents = row.parsed_avg_price_cents
                    total_cents = int(price_cents * float(delta_qty))
                else:
                    price_cents = None
                    total_cents = 0

            elif action == "sell":
                # Decreased or closed position — sell the difference
                if imported_qty == 0:
                    delta_qty = old_qty  # Sell all
                else:
                    delta_qty = old_qty - imported_qty
                if delta_qty <= 0:
                    continue
                tx_type = "sell"
                if row.parsed_avg_price_cents:
                    price_cents = row.parsed_avg_price_cents
                    total_cents = int(price_cents * float(delta_qty))
                else:
                    price_cents = None
                    total_cents = 0

            else:
                continue

            tx = Transaction(
                account_id=account_id,
                security_id=security_id,
                type=tx_type,
                trade_date=today,
                quantity=delta_qty,
                price_cents=price_cents,
                price_currency=currency,
                total_cents=total_cents,
                currency=currency,
                notes=f"Nordnet import #{import_record.id} ({tx_type})",
                external_ref=f"nordnet_import_{import_record.id}",
            )
            session.add(tx)
            transactions_created += 1

        import_record.status = "confirmed"
        await session.commit()

    return {
        "data": {
            "importId": import_id,
            "status": "confirmed",
            "transactionsCreated": transactions_created,
            "accountId": account_id,
        },
        "meta": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cacheAge": None,
            "stale": False,
        },
    }


@router.post("/{import_id}/cancel")
async def cancel_import(import_id: int):
    """Cancel a pending import."""
    async with async_session() as session:
        import_record = await session.get(Import, import_id)
        if not import_record:
            raise HTTPException(status_code=404, detail="Import not found")
        if import_record.status not in ("parsing", "parsed"):
            raise HTTPException(status_code=400, detail="Cannot cancel this import")

        import_record.status = "cancelled"
        await session.commit()

    return {
        "data": {"importId": import_id, "status": "cancelled"},
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat(), "cacheAge": None, "stale": False},
    }


@router.get("/")
async def list_imports(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """List all imports, newest first."""
    async with async_session() as session:
        result = await session.execute(
            select(Import)
            .order_by(Import.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        imports = result.scalars().all()

    return {
        "data": [
            {
                "id": i.id,
                "source": i.source,
                "status": i.status,
                "accountId": i.account_id,
                "totalRows": i.total_rows,
                "matchedRows": i.matched_rows,
                "unmatchedRows": i.unmatched_rows,
                "createdAt": i.created_at.isoformat(),
            }
            for i in imports
        ],
        "meta": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cacheAge": None,
            "stale": False,
        },
    }
