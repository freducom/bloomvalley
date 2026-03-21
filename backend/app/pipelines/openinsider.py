"""OpenInsider pipeline — scrapes insider transactions for US-listed securities."""

import asyncio
import re
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import httpx
import structlog
from sqlalchemy import select

from app.db.engine import async_session
from app.db.models.insider import InsiderTrade
from app.db.models.securities import Security
from app.pipelines import register_pipeline
from app.pipelines.base import PipelineAdapter

logger = structlog.get_logger()

US_EXCHANGES = {"XNAS", "XNYS", "NYSE", "NASDAQ"}

# Significance thresholds
SIGNIFICANT_VALUE_CENTS = 10_000_000  # $100,000 in cents
C_SUITE_ROLES = {"ceo", "cfo"}

ROLE_MAP = {
    "CEO": "ceo",
    "CFO": "cfo",
    "CTO": "cto",
    "COO": "coo",
    "Dir": "director",
    "Director": "director",
    "Pres": "ceo",
    "President": "ceo",
    "VP": "vp",
    "EVP": "vp",
    "SVP": "vp",
    "10%": "related_party",
    "Officer": "other_executive",
    "Gen": "other_executive",
    "CAO": "other_executive",
    "CMO": "other_executive",
    "CLO": "other_executive",
    "Chair": "board_chair",
    "Chairman": "board_chair",
}


def _parse_role(title: str) -> str:
    """Map OpenInsider title to our role enum."""
    title_upper = title.strip()
    for key, role in ROLE_MAP.items():
        if key.lower() in title_upper.lower():
            return role
    return "other_executive"


def _parse_trade_type(trade_str: str) -> str | None:
    """Map OpenInsider trade type string."""
    t = trade_str.strip().lower()
    if "purchase" in t or "buy" in t:
        return "buy"
    if "sale" in t or "sell" in t:
        return "sell"
    if "exercise" in t or "option" in t:
        return "exercise"
    if "gift" in t:
        return "gift"
    return None


def _parse_money(s: str) -> int | None:
    """Parse dollar amount like '$1,234,567' or '+$1,234' to cents."""
    cleaned = re.sub(r"[,$+\s]", "", s.strip())
    if not cleaned or cleaned == "-":
        return None
    try:
        return int(float(cleaned) * 100)
    except ValueError:
        return None


def _parse_shares(s: str) -> Decimal | None:
    """Parse share count like '+1,234' or '1,234'."""
    cleaned = re.sub(r"[,+\s]", "", s.strip())
    if not cleaned or cleaned == "-":
        return None
    try:
        return Decimal(cleaned)
    except Exception:
        return None


def _parse_date(s: str) -> date | None:
    """Parse date like '2026-03-15' or '2026-03-15 18:30:10'."""
    cleaned = s.strip().split()[0] if s.strip() else ""
    try:
        return date.fromisoformat(cleaned)
    except ValueError:
        return None


async def _scrape_openinsider(ticker: str, client: httpx.AsyncClient) -> list[dict]:
    """Scrape OpenInsider for a specific ticker using the search endpoint."""
    url = f"http://openinsider.com/search?q={ticker}"

    try:
        resp = await client.get(url, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        logger.warning("openinsider_fetch_error", ticker=ticker, error=str(e))
        return []

    html = resp.text
    records = []

    # Find the data table — it's the table with the most rows (typically 30+)
    tables = list(re.finditer(r"<table[^>]*>(.*?)</table>", html, re.DOTALL))
    data_table = None
    max_rows = 0
    for m in tables:
        row_count = len(re.findall(r"<tr", m.group(1)))
        if row_count > max_rows:
            max_rows = row_count
            data_table = m.group(1)

    if not data_table or max_rows < 2:
        return []

    # Extract rows
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", data_table, re.DOTALL)

    for row in rows[1:]:  # Skip header
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
        if len(cells) < 12:
            continue

        # Clean HTML from cells
        cells = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]

        # OpenInsider /search columns:
        # 0: X (empty), 1: Filing Date+time, 2: Trade Date, 3: Ticker,
        # 4: Insider Name, 5: Title, 6: Trade Type, 7: Price, 8: Qty,
        # 9: Owned, 10: ΔOwn%, 11: Value
        filing_date = _parse_date(cells[1])
        trade_date = _parse_date(cells[2])
        insider_name = cells[4].strip()
        title = cells[5].strip()
        trade_type_raw = cells[6].strip()
        price = _parse_money(cells[7]) if len(cells) > 7 else None
        qty = _parse_shares(cells[8]) if len(cells) > 8 else None
        shares_after = _parse_shares(cells[9]) if len(cells) > 9 else None
        value = _parse_money(cells[11]) if len(cells) > 11 else None

        if not trade_date or not insider_name or not qty:
            continue

        trade_type = _parse_trade_type(trade_type_raw)
        if not trade_type:
            continue

        role = _parse_role(title)

        # Significance check
        is_significant = False
        if value and abs(value) >= SIGNIFICANT_VALUE_CENTS:
            is_significant = True
        if role in C_SUITE_ROLES and trade_type == "buy":
            is_significant = True

        records.append({
            "insider_name": insider_name,
            "role": role,
            "trade_type": trade_type,
            "trade_date": trade_date,
            "disclosure_date": filing_date or trade_date,
            "shares": abs(qty),
            "price_cents": abs(price) if price else None,
            "value_cents": abs(value) if value else None,
            "shares_after": abs(shares_after) if shares_after else None,
            "is_significant": is_significant,
            "source_url": f"http://openinsider.com/screener?s={ticker}",
        })

    return records


@register_pipeline
class OpenInsiderPipeline(PipelineAdapter):
    """Scrapes insider transactions from OpenInsider for US-listed securities."""

    @property
    def source_name(self) -> str:
        return "manual"  # Use 'manual' since 'openinsider' isn't in source enum

    @property
    def pipeline_name(self) -> str:
        return "openinsider"

    async def fetch(
        self,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[dict[str, Any]]:
        # Get US-listed securities
        async with async_session() as session:
            result = await session.execute(
                select(Security).where(
                    Security.is_active.is_(True),
                    Security.exchange.in_(list(US_EXCHANGES)),
                    Security.asset_class == "stock",
                )
            )
            securities = result.scalars().all()

        if not securities:
            return []

        raw: list[dict[str, Any]] = []
        async with httpx.AsyncClient(
            headers={"User-Agent": "Mozilla/5.0 (compatible; WarrenCashett/1.0)"},
            follow_redirects=True,
        ) as client:
            for sec in securities:
                # OpenInsider uses plain ticker (no exchange suffix)
                ticker = sec.ticker.replace("-", ".")  # BRK-B -> BRK.B for OpenInsider
                records = await _scrape_openinsider(ticker, client)
                for rec in records:
                    rec["security_id"] = sec.id
                    rec["ticker"] = sec.ticker
                    rec["currency"] = "USD"
                raw.extend(records)
                logger.info("openinsider_scraped", ticker=sec.ticker, records=len(records))
                await asyncio.sleep(2.0)  # Be polite

        logger.info("openinsider_fetched", total=len(raw))
        return raw

    async def validate(self, raw_records: list[dict]) -> tuple[list[dict], list[str]]:
        valid = []
        errors = []
        for rec in raw_records:
            if not rec.get("trade_date") or not rec.get("insider_name"):
                errors.append(f"Missing required fields: {rec.get('ticker')}")
                continue
            if not rec.get("shares") or float(rec["shares"]) <= 0:
                continue  # Skip zero-share records
            valid.append(rec)
        return valid, errors

    async def transform(self, valid_records: list[dict]) -> list[dict]:
        return valid_records

    async def load(self, transformed_records: list[dict]) -> int:
        if not transformed_records:
            return 0

        # Get existing trades to avoid duplicates (match on security+insider+date+type)
        async with async_session() as session:
            existing = await session.execute(
                select(
                    InsiderTrade.security_id,
                    InsiderTrade.insider_name,
                    InsiderTrade.trade_date,
                    InsiderTrade.trade_type,
                )
            )
            existing_set = {
                (r.security_id, r.insider_name, r.trade_date, r.trade_type)
                for r in existing.all()
            }

        rows = 0
        async with async_session() as session:
            for rec in transformed_records:
                key = (rec["security_id"], rec["insider_name"], rec["trade_date"], rec["trade_type"])
                if key in existing_set:
                    continue

                trade = InsiderTrade(
                    security_id=rec["security_id"],
                    insider_name=rec["insider_name"],
                    role=rec["role"],
                    trade_type=rec["trade_type"],
                    jurisdiction="us",
                    trade_date=rec["trade_date"],
                    disclosure_date=rec["disclosure_date"],
                    shares=rec["shares"],
                    price_cents=rec.get("price_cents"),
                    value_cents=rec.get("value_cents"),
                    currency=rec.get("currency", "USD"),
                    shares_after=rec.get("shares_after"),
                    source_url=rec.get("source_url"),
                    source="openinsider",
                    is_significant=rec.get("is_significant", False),
                )
                session.add(trade)
                existing_set.add(key)
                rows += 1

            await session.commit()

        logger.info("openinsider_loaded", rows=rows)
        return rows
