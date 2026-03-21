"""Quiver Congress pipeline — scrapes US Congress member stock trades."""

import asyncio
import re
from datetime import date, timedelta
from typing import Any

import httpx
import structlog
from sqlalchemy import select

from app.db.engine import async_session
from app.db.models.insider import CongressTrade
from app.db.models.securities import Security
from app.pipelines import register_pipeline
from app.pipelines.base import PipelineAdapter, RetryableError

logger = structlog.get_logger()

QUIVER_URL = "https://www.quiverquant.com/congresstrading/"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Amount range mappings from Congress disclosure form ranges to cents
AMOUNT_RANGES: dict[str, tuple[int, int]] = {
    "$1,001 - $15,000": (100_100, 1_500_000),
    "$1,001 -": (100_100, 1_500_000),
    "$15,001 - $50,000": (1_500_100, 5_000_000),
    "$15,001 -": (1_500_100, 5_000_000),
    "$50,001 - $100,000": (5_000_100, 10_000_000),
    "$50,001 -": (5_000_100, 10_000_000),
    "$100,001 - $250,000": (10_000_100, 25_000_000),
    "$100,001 -": (10_000_100, 25_000_000),
    "$250,001 - $500,000": (25_000_100, 50_000_000),
    "$250,001 -": (25_000_100, 50_000_000),
    "$500,001 - $1,000,000": (50_000_100, 100_000_000),
    "$500,001 -": (50_000_100, 100_000_000),
    "$1,000,001 - $5,000,000": (100_000_100, 500_000_000),
    "$1,000,001 -": (100_000_100, 500_000_000),
    "$5,000,001 - $25,000,000": (500_000_100, 2_500_000_000),
    "$5,000,001 -": (500_000_100, 2_500_000_000),
    "$25,000,001 - $50,000,000": (2_500_000_100, 5_000_000_000),
    "$25,000,001 -": (2_500_000_100, 5_000_000_000),
    "$50,000,001+": (5_000_000_100, 10_000_000_000),
    "Over $50,000,000": (5_000_000_100, 10_000_000_000),
}


def _parse_amount_range(amount_str: str) -> tuple[int, int] | None:
    """Parse Congress disclosure amount range string to (low_cents, high_cents)."""
    cleaned = amount_str.strip()
    if not cleaned:
        return None

    # Try exact match first
    for pattern, (low, high) in AMOUNT_RANGES.items():
        if pattern.lower() in cleaned.lower():
            return (low, high)

    # Try to extract dollar amounts with regex
    amounts = re.findall(r"\$?([\d,]+)", cleaned)
    if len(amounts) >= 2:
        try:
            low = int(amounts[0].replace(",", "")) * 100
            high = int(amounts[1].replace(",", "")) * 100
            return (low, high)
        except ValueError:
            pass
    elif len(amounts) == 1:
        try:
            val = int(amounts[0].replace(",", "")) * 100
            return (val, val)
        except ValueError:
            pass

    return None


def _parse_trade_type(trade_str: str) -> str | None:
    """Map trade type string to buy/sell."""
    t = trade_str.strip().lower()
    if "purchase" in t or "buy" in t:
        return "buy"
    if "sale" in t or "sell" in t:
        return "sell"
    if "exchange" in t:
        return "sell"
    return None


def _parse_date(s: str) -> date | None:
    """Parse date string in common formats."""
    cleaned = s.strip().split()[0] if s.strip() else ""
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return date.fromisoformat(cleaned) if fmt == "%Y-%m-%d" else None
        except ValueError:
            pass
    # Try other formats
    from datetime import datetime as dt

    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return dt.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def _parse_chamber(s: str) -> str:
    """Normalize chamber to 'senate' or 'house'."""
    t = s.strip().lower()
    if "senate" in t or "sen" in t:
        return "senate"
    if "house" in t or "rep" in t:
        return "house"
    return "house"


def _parse_party(s: str) -> str:
    """Normalize party affiliation."""
    t = s.strip().lower()
    if t.startswith("d") or "democrat" in t:
        return "democrat"
    if t.startswith("r") or "republican" in t:
        return "republican"
    if t.startswith("i") or "independent" in t:
        return "independent"
    return "unknown"


async def _scrape_quiver_page(client: httpx.AsyncClient) -> list[dict]:
    """Scrape the Quiver Quantitative congress trading page."""
    try:
        resp = await client.get(QUIVER_URL, timeout=30)
        if resp.status_code == 429:
            raise RetryableError("Quiver rate limited (429)")
        resp.raise_for_status()
    except RetryableError:
        raise
    except httpx.TimeoutException as e:
        raise RetryableError(f"Quiver timeout: {e}") from e
    except Exception as e:
        logger.warning("quiver_congress_fetch_error", error=str(e))
        return []

    html = resp.text
    records: list[dict] = []

    # Find data tables in the HTML
    tables = list(re.finditer(r"<table[^>]*>(.*?)</table>", html, re.DOTALL))
    data_table = None
    max_rows = 0
    for m in tables:
        row_count = len(re.findall(r"<tr", m.group(1)))
        if row_count > max_rows:
            max_rows = row_count
            data_table = m.group(1)

    if not data_table or max_rows < 2:
        logger.warning("quiver_congress_no_table_found")
        return []

    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", data_table, re.DOTALL)

    for row in rows[1:]:  # Skip header
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
        if len(cells) < 5:
            continue

        # Clean HTML tags from cells
        cells = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]

        # Quiver page columns vary; attempt a best-effort parse
        # Typical: Politician, Party, Chamber, Ticker, Trade Type, Amount, Date
        if len(cells) >= 7:
            politician = cells[0]
            party = _parse_party(cells[1])
            chamber = _parse_chamber(cells[2])
            ticker = cells[3].strip().upper()
            trade_type = _parse_trade_type(cells[4])
            amount_range = _parse_amount_range(cells[5])
            trade_date = _parse_date(cells[6])
            disclosure_date = _parse_date(cells[7]) if len(cells) > 7 else trade_date
            asset_desc = cells[8].strip() if len(cells) > 8 else None
        elif len(cells) >= 5:
            politician = cells[0]
            party = "unknown"
            chamber = "house"
            ticker = cells[1].strip().upper()
            trade_type = _parse_trade_type(cells[2])
            amount_range = _parse_amount_range(cells[3])
            trade_date = _parse_date(cells[4])
            disclosure_date = trade_date
            asset_desc = None
        else:
            continue

        if not trade_type or not trade_date or not ticker:
            continue

        if not amount_range:
            amount_range = (0, 0)

        records.append({
            "member_name": politician,
            "party": party,
            "chamber": chamber,
            "ticker_reported": ticker,
            "trade_type": trade_type,
            "trade_date": trade_date,
            "disclosure_date": disclosure_date or trade_date,
            "amount_range_low_cents": amount_range[0],
            "amount_range_high_cents": amount_range[1],
            "asset_description": asset_desc,
            "source_url": QUIVER_URL,
        })

    return records


@register_pipeline
class QuiverCongressPipeline(PipelineAdapter):
    """Scrapes US Congress member stock trades from Quiver Quantitative."""

    @property
    def source_name(self) -> str:
        return "quiver"

    @property
    def pipeline_name(self) -> str:
        return "quiver_congress_trades"

    async def fetch(
        self,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[dict[str, Any]]:
        logger.info("quiver_congress_fetch_start")

        raw: list[dict[str, Any]] = []
        async with httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        ) as client:
            records = await _scrape_quiver_page(client)
            raw.extend(records)
            await asyncio.sleep(5)  # Polite delay

        # Filter by date range if provided
        if from_date or to_date:
            filtered = []
            for rec in raw:
                td = rec["trade_date"]
                if from_date and td < from_date:
                    continue
                if to_date and td > to_date:
                    continue
                filtered.append(rec)
            raw = filtered

        logger.info("quiver_congress_fetch_complete", records=len(raw))
        return raw

    async def validate(self, raw_records: list[dict]) -> tuple[list[dict], list[str]]:
        valid = []
        errors = []
        today = date.today()

        for rec in raw_records:
            ticker = rec.get("ticker_reported", "?")

            if not rec.get("member_name"):
                errors.append(f"{ticker}: missing member name")
                continue

            if not rec.get("trade_date"):
                errors.append(f"{ticker}: missing trade date")
                continue

            if rec["trade_date"] > today + timedelta(days=1):
                errors.append(f"{ticker}: future trade date {rec['trade_date']}")
                continue

            if not rec.get("trade_type"):
                errors.append(f"{ticker}: missing trade type")
                continue

            if not rec.get("ticker_reported"):
                errors.append("missing ticker")
                continue

            valid.append(rec)

        return valid, errors

    async def transform(self, valid_records: list[dict]) -> list[dict]:
        """Match tickers to securities in the database."""
        if not valid_records:
            return []

        # Collect unique tickers
        tickers = {rec["ticker_reported"] for rec in valid_records}

        # Look up securities by ticker
        async with async_session() as session:
            result = await session.execute(
                select(Security).where(
                    Security.is_active.is_(True),
                    Security.ticker.in_(list(tickers)),
                )
            )
            securities = result.scalars().all()

        ticker_to_id = {sec.ticker: sec.id for sec in securities}

        transformed = []
        for rec in valid_records:
            sec_id = ticker_to_id.get(rec["ticker_reported"])
            rec["security_id"] = sec_id  # May be None if not in our universe
            transformed.append(rec)

        return transformed

    async def load(self, transformed_records: list[dict]) -> int:
        if not transformed_records:
            return 0

        # Get existing trades to avoid duplicates
        async with async_session() as session:
            existing = await session.execute(
                select(
                    CongressTrade.member_name,
                    CongressTrade.ticker_reported,
                    CongressTrade.trade_date,
                    CongressTrade.trade_type,
                )
            )
            existing_set = {
                (r.member_name, r.ticker_reported, r.trade_date, r.trade_type)
                for r in existing.all()
            }

        rows = 0
        async with async_session() as session:
            for rec in transformed_records:
                key = (
                    rec["member_name"],
                    rec["ticker_reported"],
                    rec["trade_date"],
                    rec["trade_type"],
                )
                if key in existing_set:
                    continue

                trade = CongressTrade(
                    security_id=rec.get("security_id"),
                    member_name=rec["member_name"],
                    party=rec["party"],
                    chamber=rec["chamber"],
                    state=None,
                    trade_type=rec["trade_type"],
                    trade_date=rec["trade_date"],
                    disclosure_date=rec["disclosure_date"],
                    amount_range_low_cents=rec["amount_range_low_cents"],
                    amount_range_high_cents=rec["amount_range_high_cents"],
                    currency="USD",
                    ticker_reported=rec["ticker_reported"],
                    asset_description=rec.get("asset_description"),
                    source_url=rec.get("source_url"),
                    source="quiver_quantitative",
                )
                session.add(trade)
                existing_set.add(key)
                rows += 1

            await session.commit()

        logger.info("quiver_congress_loaded", rows=rows)
        return rows
