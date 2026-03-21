"""Nasdaq Nordic insider pipeline — fetches Finnish PDMR transactions from Nasdaq News API."""

import asyncio
import re
from datetime import date
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

FI_EXCHANGES = {"XHEL"}

NEWS_API = "https://api.news.eu.nasdaq.com/news/query.action"

# Significance thresholds
SIGNIFICANT_VALUE_CENTS = 10_000_000  # €100,000 in cents
C_SUITE_ROLES = {"ceo", "cfo"}

ROLE_MAP = {
    "chief executive officer": "ceo",
    "ceo": "ceo",
    "toimitusjohtaja": "ceo",
    "chief financial officer": "cfo",
    "cfo": "cfo",
    "chief technology officer": "cto",
    "cto": "cto",
    "chief operating officer": "coo",
    "coo": "coo",
    "member of the board": "director",
    "board member": "director",
    "hallituksen jäsen": "director",
    "chairman": "board_chair",
    "chair of the board": "board_chair",
    "hallituksen puheenjohtaja": "board_chair",
    "vice president": "vp",
    "evp": "vp",
    "svp": "vp",
    "other senior manager": "other_executive",
}


def _parse_role(position: str) -> str:
    """Map PDMR position to our role enum."""
    pos_lower = position.strip().lower()
    for key, role in ROLE_MAP.items():
        if key in pos_lower:
            return role
    return "other_executive"


def _parse_detail_page(text: str) -> list[dict]:
    """Parse a Nasdaq Nordic managers' transaction detail page (plain text).

    Returns one record per transaction block in the disclosure.
    """
    # Extract person info from the top section
    name_match = re.search(r"Name:\s*(.+)", text)
    position_match = re.search(r"Position:\s*(.+)", text)
    issuer_match = re.search(r"Issuer:\s*(.+)", text)

    if not name_match:
        return []

    insider_name = name_match.group(1).strip()
    position = position_match.group(1).strip() if position_match else ""
    issuer = issuer_match.group(1).strip() if issuer_match else ""

    # Split on separator lines to find transaction blocks
    blocks = re.split(r"_{10,}", text)

    records = []
    for block in blocks:
        trade_date_match = re.search(r"Transaction date:\s*(\d{4}-\d{2}-\d{2})", block)
        nature_match = re.search(r"Nature of transaction:\s*(ACQUISITION|DISPOSAL)", block, re.IGNORECASE)
        isin_match = re.search(r"ISIN:\s*([A-Z]{2}[A-Z0-9]{10})", block)

        if not trade_date_match or not nature_match:
            continue

        # Get aggregated volume and VWAP
        agg_match = re.search(
            r"Volume:\s*([\d,\.]+)\s*Volume weighted average price:\s*([\d,\.]+)\s*(\w+)",
            block,
        )
        if not agg_match:
            # Try individual transaction line
            ind_match = re.search(
                r"\(\d+\):\s*Volume:\s*([\d,\.]+)\s*Unit price:\s*([\d,\.]+)\s*(\w+)",
                block,
            )
            if not ind_match:
                continue
            volume_str = ind_match.group(1)
            price_str = ind_match.group(2)
            currency = ind_match.group(3)
        else:
            volume_str = agg_match.group(1)
            price_str = agg_match.group(2)
            currency = agg_match.group(3)

        volume = Decimal(volume_str.replace(",", ""))
        price = float(price_str.replace(",", ""))
        price_cents = int(round(price * 100))
        value_cents = int(round(float(volume) * price * 100))

        trade_type = "buy" if "ACQUISITION" in nature_match.group(1).upper() else "sell"
        trade_date = date.fromisoformat(trade_date_match.group(1))

        role = _parse_role(position)

        is_significant = False
        if abs(value_cents) >= SIGNIFICANT_VALUE_CENTS:
            is_significant = True
        if role in C_SUITE_ROLES and trade_type == "buy":
            is_significant = True

        records.append({
            "insider_name": insider_name,
            "role": role,
            "trade_type": trade_type,
            "trade_date": trade_date,
            "disclosure_date": trade_date,  # Updated later from API releaseTime
            "shares": volume,
            "price_cents": price_cents,
            "value_cents": abs(value_cents),
            "currency": currency,
            "isin": isin_match.group(1) if isin_match else None,
            "issuer": issuer,
            "is_significant": is_significant,
        })

    return records


async def _fetch_transactions(
    client: httpx.AsyncClient,
    company_names: set[str],
    max_age: str = "90d",
    max_pages: int = 10,
) -> list[dict]:
    """Fetch managers' transaction disclosures from Nasdaq Nordic News API.

    Only fetches detail pages for companies matching our securities (by name).
    """
    all_records: list[dict] = []
    start = 0
    limit = 20
    pages = 0

    while pages < max_pages:
        params = {
            "type": "json",
            "maximumAge": max_age,
            "market": "Main Market, Helsinki",
            "cnscategory": "Managers' Transactions",
            "limit": str(limit),
            "start": str(start),
        }

        try:
            resp = await client.get(NEWS_API, params=params, timeout=20)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning("nasdaq_nordic_api_error", error=str(e), start=start)
            break

        items = data.get("results", {}).get("item", [])
        if not items:
            break

        for item in items:
            message_url = item.get("messageUrl", "")
            release_time = item.get("releaseTime", "")
            company = item.get("company", "")

            if not message_url or not company:
                continue

            # Skip companies we don't track (avoid fetching thousands of detail pages)
            company_lower = company.lower()
            matched = any(name in company_lower for name in company_names)
            if not matched:
                continue

            # Fetch and parse the detail page
            try:
                detail_resp = await client.get(message_url, timeout=20)
                detail_resp.raise_for_status()
                # Convert HTML to plain text
                text = re.sub(r"<[^>]+>", " ", detail_resp.text)
                text = re.sub(r"&nbsp;", " ", text)
                text = re.sub(r"&#\d+;", " ", text)
                text = re.sub(r"\s+", " ", text)
                # Restore line breaks for key fields
                for label in ["Name:", "Position:", "Issuer:", "LEI:", "Transaction date:",
                              "Venue:", "Instrument type:", "ISIN:", "Nature of transaction:",
                              "Aggregated transactions", "Volume:", "Further information"]:
                    text = text.replace(f" {label}", f"\n{label}")
                # Restore transaction detail numbering
                text = re.sub(r" \((\d+)\):", r"\n(\1):", text)
            except Exception as e:
                logger.warning("nasdaq_nordic_detail_error", url=message_url, error=str(e))
                continue

            records = _parse_detail_page(text)

            # Parse disclosure date from API releaseTime
            disclosure_date = None
            if release_time:
                try:
                    disclosure_date = date.fromisoformat(release_time.split()[0])
                except (ValueError, IndexError):
                    pass

            for rec in records:
                if disclosure_date:
                    rec["disclosure_date"] = disclosure_date
                rec["source_url"] = message_url
                rec["company"] = company

            all_records.extend(records)
            await asyncio.sleep(0.5)  # Be polite to detail pages

        logger.info("nasdaq_nordic_batch", start=start, items=len(items), records=len(all_records))

        pages += 1
        start += limit
        if len(items) < limit:
            break
        await asyncio.sleep(1.0)

    return all_records


@register_pipeline
class NasdaqNordicInsiderPipeline(PipelineAdapter):
    """Fetches Finnish insider (PDMR) transactions from Nasdaq Nordic News API."""

    @property
    def source_name(self) -> str:
        return "manual"

    @property
    def pipeline_name(self) -> str:
        return "nasdaq_nordic_insider"

    async def fetch(
        self,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[dict[str, Any]]:
        # Get Finnish securities with ISINs for matching
        async with async_session() as session:
            result = await session.execute(
                select(Security).where(
                    Security.is_active.is_(True),
                    Security.exchange.in_(list(FI_EXCHANGES)),
                )
            )
            securities = result.scalars().all()

        # Build lookup maps: ISIN -> security, company name -> security
        isin_map: dict[str, Security] = {}
        name_map: dict[str, Security] = {}
        for sec in securities:
            if sec.isin:
                isin_map[sec.isin] = sec
            # Normalize company names for fuzzy matching
            name_key = sec.name.lower().replace("oyj", "").replace("abp", "").strip()
            name_map[name_key] = sec
            # Also map by ticker prefix (e.g., "nokia" from "NOKIA.HE")
            ticker_key = sec.ticker.split(".")[0].lower()
            name_map[ticker_key] = sec

        if not securities:
            return []

        # Build set of lowercase company name keywords for filtering API results
        company_names: set[str] = set()
        for sec in securities:
            # Extract key part of name (e.g., "nokia" from "Nokia Oyj")
            name_parts = sec.name.lower().replace("oyj", "").replace("abp", "").strip().split()
            if name_parts:
                company_names.add(name_parts[0])
            ticker_key = sec.ticker.split(".")[0].lower()
            company_names.add(ticker_key)

        raw: list[dict[str, Any]] = []
        async with httpx.AsyncClient(
            headers={"User-Agent": "Mozilla/5.0 (compatible; WarrenCashett/1.0)"},
            follow_redirects=True,
        ) as client:
            records = await _fetch_transactions(client, company_names)

            for rec in records:
                # Match to security by ISIN first, then by company name
                sec = None
                if rec.get("isin"):
                    sec = isin_map.get(rec["isin"])

                if not sec and rec.get("company"):
                    company_lower = rec["company"].lower().replace("oyj", "").replace("abp", "").strip()
                    sec = name_map.get(company_lower)
                    if not sec:
                        # Try partial matching
                        for key, s in name_map.items():
                            if key in company_lower or company_lower in key:
                                sec = s
                                break

                if not sec:
                    logger.debug("nasdaq_nordic_no_match", company=rec.get("company"), isin=rec.get("isin"))
                    continue

                rec["security_id"] = sec.id
                rec["ticker"] = sec.ticker
                if not rec.get("currency"):
                    rec["currency"] = sec.currency
                raw.append(rec)

        logger.info("nasdaq_nordic_fetched", total=len(raw))
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
                    jurisdiction="fi",
                    trade_date=rec["trade_date"],
                    disclosure_date=rec["disclosure_date"],
                    shares=rec["shares"],
                    price_cents=rec.get("price_cents"),
                    value_cents=rec.get("value_cents"),
                    currency=rec.get("currency", "EUR"),
                    source_url=rec.get("source_url"),
                    source="nasdaq_nordic",
                    is_significant=rec.get("is_significant", False),
                )
                session.add(trade)
                existing_set.add(key)
                rows += 1

            await session.commit()

        logger.info("nasdaq_nordic_loaded", rows=rows)
        return rows
