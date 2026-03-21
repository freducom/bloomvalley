"""Swedish FI (Finansinspektionen) insider pipeline — scrapes PDMR transactions."""

import asyncio
import re
from datetime import date, datetime
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

SE_EXCHANGES = {"XSTO"}

SEARCH_URL = "https://marknadssok.fi.se/Publiceringsklient/en-GB/Search/Search"

# Significance thresholds
SIGNIFICANT_VALUE_CENTS = 10_000_000  # SEK 100,000 in öre
C_SUITE_ROLES = {"ceo", "cfo"}

ROLE_MAP = {
    "chief executive officer": "ceo",
    "ceo": "ceo",
    "verkställande direktör": "ceo",
    "vd": "ceo",
    "chief financial officer": "cfo",
    "cfo": "cfo",
    "chairman": "board_chair",
    "chair of the board": "board_chair",
    "ordförande": "board_chair",
    "member of the board": "director",
    "board member": "director",
    "styrelseledamot": "director",
    "vice president": "vp",
    "evp": "vp",
    "svp": "vp",
}


def _parse_role(position: str) -> str:
    """Map FI position to our role enum."""
    pos_lower = position.strip().lower().replace("\xa0", " ")
    for key, role in ROLE_MAP.items():
        if key in pos_lower:
            return role
    return "other_executive"


def _parse_fi_date(s: str) -> date | None:
    """Parse date like '20/03/2026'."""
    cleaned = s.strip().replace("\xa0", "")
    if not cleaned:
        return None
    try:
        return datetime.strptime(cleaned, "%d/%m/%Y").date()
    except ValueError:
        try:
            return date.fromisoformat(cleaned)
        except ValueError:
            return None


def _parse_fi_volume(s: str) -> Decimal | None:
    """Parse volume like '1,069,931' or '500,000'."""
    cleaned = s.strip().replace(",", "").replace("\xa0", "")
    if not cleaned or cleaned == "-":
        return None
    try:
        return Decimal(cleaned)
    except Exception:
        return None


def _parse_fi_price(s: str) -> float | None:
    """Parse price like '41.20' or '279.69'."""
    cleaned = s.strip().replace(",", "").replace("\xa0", "")
    if not cleaned or cleaned == "-":
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


async def _scrape_fi_register(
    client: httpx.AsyncClient,
    from_date: date | None = None,
    to_date: date | None = None,
    max_pages: int = 20,
) -> list[dict]:
    """Scrape the Swedish FI PDMR register."""
    all_records: list[dict] = []

    for page in range(1, max_pages + 1):
        params: dict[str, str] = {
            "SearchFunctionType": "Insyn",
            "button": "search",
            "paging": "True",
            "page": str(page),
        }
        if from_date:
            params["Transaktionsdatum_From"] = from_date.strftime("%Y-%m-%d")
        if to_date:
            params["Transaktionsdatum_To"] = to_date.strftime("%Y-%m-%d")

        try:
            resp = await client.get(SEARCH_URL, params=params, timeout=20)
            resp.raise_for_status()
        except Exception as e:
            logger.warning("fi_se_fetch_error", page=page, error=str(e))
            break

        html = resp.text

        # Find the data table
        table_match = re.search(
            r"<table[^>]*class=\"[^\"]*table[^\"]*\"[^>]*>(.*?)</table>",
            html,
            re.DOTALL,
        )
        if not table_match:
            break

        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table_match.group(1), re.DOTALL)

        if len(rows) <= 1:  # Only header
            break

        for row in rows[1:]:  # Skip header
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
            if len(cells) < 14:
                continue

            # Clean HTML and normalize whitespace
            cells = [re.sub(r"<[^>]+>", "", c).replace("\xa0", " ").strip() for c in cells]

            # Columns: 0=Publication date, 1=Issuer, 2=Person, 3=Position,
            # 4=Closely associated, 5=Nature, 6=Instrument name, 7=Instrument type,
            # 8=ISIN, 9=Transaction date, 10=Volume, 11=Unit, 12=Price, 13=Currency
            pub_date = _parse_fi_date(cells[0])
            issuer = cells[1].strip()
            person = cells[2].strip()
            position = cells[3].strip()
            nature = cells[5].strip().lower()
            isin = cells[8].strip()
            trade_date = _parse_fi_date(cells[9])
            volume = _parse_fi_volume(cells[10])
            price = _parse_fi_price(cells[12])
            currency = cells[13].strip() if len(cells) > 13 else "SEK"

            if not trade_date or not person or not volume:
                continue

            if "acquisition" in nature:
                trade_type = "buy"
            elif "disposal" in nature or "sale" in nature:
                trade_type = "sell"
            else:
                continue

            price_cents = int(round(price * 100)) if price else None
            value_cents = int(round(float(volume) * price * 100)) if price and volume else None

            role = _parse_role(position)

            is_significant = False
            if value_cents and abs(value_cents) >= SIGNIFICANT_VALUE_CENTS:
                is_significant = True
            if role in C_SUITE_ROLES and trade_type == "buy":
                is_significant = True

            all_records.append({
                "insider_name": person,
                "role": role,
                "trade_type": trade_type,
                "trade_date": trade_date,
                "disclosure_date": pub_date or trade_date,
                "shares": volume,
                "price_cents": price_cents,
                "value_cents": abs(value_cents) if value_cents else None,
                "currency": currency,
                "isin": isin,
                "issuer": issuer,
                "is_significant": is_significant,
            })

        logger.info("fi_se_page_scraped", page=page, records=len(all_records))

        # Check if there are more pages
        if f"page={page + 1}" not in html:
            break

        await asyncio.sleep(1.0)  # Be polite

    return all_records


@register_pipeline
class SwedishFIInsiderPipeline(PipelineAdapter):
    """Scrapes Swedish PDMR transactions from Finansinspektionen register."""

    @property
    def source_name(self) -> str:
        return "manual"

    @property
    def pipeline_name(self) -> str:
        return "fi_se_insider"

    async def fetch(
        self,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[dict[str, Any]]:
        # Default to last 90 days
        if not from_date:
            from_date = date.today() - __import__("datetime").timedelta(days=90)
        if not to_date:
            to_date = date.today()

        # Get Swedish securities with ISINs for matching
        async with async_session() as session:
            result = await session.execute(
                select(Security).where(
                    Security.is_active.is_(True),
                    Security.exchange.in_(list(SE_EXCHANGES)),
                )
            )
            securities = result.scalars().all()

        isin_map: dict[str, Security] = {}
        name_map: dict[str, Security] = {}
        for sec in securities:
            if sec.isin:
                isin_map[sec.isin] = sec
            name_key = sec.name.lower().replace("ab", "").strip()
            name_map[name_key] = sec
            ticker_key = sec.ticker.split(".")[0].lower().replace("-", "")
            name_map[ticker_key] = sec

        if not securities:
            return []

        raw: list[dict[str, Any]] = []
        async with httpx.AsyncClient(
            headers={"User-Agent": "Mozilla/5.0 (compatible; WarrenCashett/1.0)"},
            follow_redirects=True,
        ) as client:
            records = await _scrape_fi_register(client, from_date, to_date)

            for rec in records:
                sec = None
                if rec.get("isin"):
                    sec = isin_map.get(rec["isin"])

                if not sec and rec.get("issuer"):
                    issuer_lower = rec["issuer"].lower().replace("ab", "").strip()
                    sec = name_map.get(issuer_lower)
                    if not sec:
                        for key, s in name_map.items():
                            if key in issuer_lower or issuer_lower in key:
                                sec = s
                                break

                if not sec:
                    continue

                rec["security_id"] = sec.id
                rec["ticker"] = sec.ticker
                raw.append(rec)

        logger.info("fi_se_fetched", total=len(raw))
        return raw

    async def validate(self, raw_records: list[dict]) -> tuple[list[dict], list[str]]:
        valid = []
        errors = []
        for rec in raw_records:
            if not rec.get("trade_date") or not rec.get("insider_name"):
                errors.append(f"Missing required fields: {rec.get('ticker')}")
                continue
            if not rec.get("shares") or float(rec["shares"]) <= 0:
                continue
            valid.append(rec)
        return valid, errors

    async def transform(self, valid_records: list[dict]) -> list[dict]:
        return valid_records

    async def load(self, transformed_records: list[dict]) -> int:
        if not transformed_records:
            return 0

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
                    jurisdiction="se",
                    trade_date=rec["trade_date"],
                    disclosure_date=rec["disclosure_date"],
                    shares=rec["shares"],
                    price_cents=rec.get("price_cents"),
                    value_cents=rec.get("value_cents"),
                    currency=rec.get("currency", "SEK"),
                    source_url="https://marknadssok.fi.se/Publiceringsklient/en-GB/Search/Start/Insyn",
                    source="finansinspektionen",
                    is_significant=rec.get("is_significant", False),
                )
                session.add(trade)
                existing_set.add(key)
                rows += 1

            await session.commit()

        logger.info("fi_se_loaded", rows=rows)
        return rows
