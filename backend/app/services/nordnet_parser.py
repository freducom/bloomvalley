"""Nordnet portfolio export parser.

Handles tab-separated or semicolon-separated Nordnet exports.
Auto-detects delimiter, decimal format (comma vs period), and encoding.
"""

import re
from decimal import Decimal, InvalidOperation
from typing import Any

import structlog

logger = structlog.get_logger()

# Nordnet account type -> our account type
ACCOUNT_TYPE_MAP = {
    "AF": "regular",
    "AOT": "regular",
    "OST": "osakesaastotili",
    "IPS": "pension",
    "KF": "pension",
    "ISK": "regular",
}

# Known Nordnet column headers (Finnish + Swedish + English)
HEADER_ALIASES = {
    # Ticker
    "tunnus": "ticker",
    "symbol": "ticker",
    "ticker": "ticker",
    # ISIN
    "isin": "isin",
    # Name
    "nimi": "name",
    "namn": "name",
    "name": "name",
    "värdepapper": "name",
    "arvopaperi": "name",
    # Quantity
    "määrä": "quantity",
    "antal": "quantity",
    "quantity": "quantity",
    "kpl": "quantity",
    # Average price / cost basis
    "hankintahinta": "avg_price",
    "gak": "avg_price",
    "avg price": "avg_price",
    "keskihinta": "avg_price",
    "keskikurssi": "avg_price",
    "anskaffningsvärde": "avg_price",
    # Latest price
    "viimeisin": "last_price",
    "senaste": "last_price",
    "last": "last_price",
    # Market value (in EUR)
    "markkina-arvo": "market_value",
    "marknadsvärde": "market_value",
    "market value": "market_value",
    "arvo": "market_value",
    "arvo eur": "market_value",
    # Collateral value
    "lainoitusarvo, eur": "collateral_value",
    "lainoitusarvo": "collateral_value",
    # Day change percent
    "% tänään": "day_change_pct",
    "förändring idag": "day_change_pct",
    # Development percent
    "kehitys": "development_pct",
    # Profit/Loss in EUR
    "tuotto, eur": "profit_eur",
    "tuotto,eur": "profit_eur",
    "tuotto": "profit_eur",
    "tuotto,\u20aceur": "profit_eur",
    # Currency
    "valuutta": "currency",
    "valuta": "currency",
    "currency": "currency",
    # Account type
    "tilin tyyppi": "account_type",
    "kontotyp": "account_type",
    "account type": "account_type",
    "tili": "account_type",
    "konto": "account_type",
}


def _detect_delimiter(text: str) -> str:
    """Detect whether the export uses tabs or semicolons."""
    first_lines = text.strip().split("\n")[:3]
    tab_count = sum(line.count("\t") for line in first_lines)
    semi_count = sum(line.count(";") for line in first_lines)
    return "\t" if tab_count >= semi_count else ";"


def _detect_decimal_format(values: list[str]) -> str:
    """Detect if numbers use comma (1.234,56) or period (1,234.56) as decimal."""
    for v in values:
        # Pattern: digits then comma then 1-4 digits at end → comma decimal
        if re.search(r"\d,\d{1,4}$", v):
            return "comma"
        if re.search(r"\d\.\d{1,4}$", v):
            return "period"
    return "period"  # default


def _parse_number(value: str, decimal_format: str) -> Decimal | None:
    """Parse a number string to Decimal, handling thousand separators."""
    if not value or value.strip() in ("-", "", "—", "0"):
        return None

    cleaned = value.strip()

    # Handle negative sign
    negative = cleaned.startswith("-")
    if negative:
        cleaned = cleaned[1:]

    if decimal_format == "comma":
        # Remove space/period thousand separators, replace comma with period
        cleaned = cleaned.replace(" ", "").replace(".", "").replace(",", ".")
    else:
        # Remove space/comma thousand separators
        cleaned = cleaned.replace(" ", "").replace(",", "")

    if negative:
        cleaned = "-" + cleaned

    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _to_cents(value: Decimal | None) -> int | None:
    """Convert a decimal currency value to integer cents."""
    if value is None:
        return None
    return int(round(value * 100))


def _clean_text(raw_text: str) -> str:
    """Handle UTF-16 BOM and normalize encoding."""
    # Strip BOM (UTF-8 BOM or leftovers from UTF-16 conversion)
    if raw_text.startswith("\ufeff"):
        raw_text = raw_text[1:]
    # Normalize line endings
    raw_text = raw_text.replace("\r\n", "\n").replace("\r", "\n")
    return raw_text


def parse_nordnet_export(raw_text: str) -> list[dict[str, Any]]:
    """Parse Nordnet portfolio export text into structured rows.

    Returns a list of dicts with standardized field names.
    """
    raw_text = _clean_text(raw_text)
    lines = raw_text.strip().split("\n")
    if len(lines) < 2:
        raise ValueError("Export must have at least a header row and one data row")

    delimiter = _detect_delimiter(raw_text)

    # Parse header
    header_line = lines[0]
    raw_headers = [h.strip().lower() for h in header_line.split(delimiter)]
    # Also try matching with the special euro character variants
    mapped_headers = []
    for h in raw_headers:
        # Normalize common variants
        normalized = h.replace("\u20ac", "").strip()
        mapped = HEADER_ALIASES.get(h) or HEADER_ALIASES.get(normalized) or h
        mapped_headers.append(mapped)

    # Detect decimal format from data rows
    all_values = []
    for line in lines[1:]:
        cols = line.split(delimiter)
        all_values.extend(c.strip() for c in cols)
    decimal_format = _detect_decimal_format(all_values)

    logger.info(
        "nordnet_parse_start",
        delimiter="tab" if delimiter == "\t" else "semicolon",
        decimal_format=decimal_format,
        columns=mapped_headers,
        data_rows=len(lines) - 1,
    )

    parsed_rows: list[dict[str, Any]] = []

    for i, line in enumerate(lines[1:], start=1):
        if not line.strip():
            continue

        cols = line.split(delimiter)
        raw_data = {}
        for j, col in enumerate(cols):
            if j < len(raw_headers):
                raw_data[raw_headers[j]] = col.strip()

        # Build structured row
        row: dict[str, Any] = {
            "row_number": i,
            "raw_data": raw_data,
        }

        # Extract known fields
        for j, col in enumerate(cols):
            if j >= len(mapped_headers):
                continue
            field = mapped_headers[j]
            value = col.strip()

            if field == "ticker":
                row["ticker"] = value
            elif field == "isin":
                row["isin"] = value.upper() if value else None
            elif field == "name":
                row["name"] = value
            elif field == "quantity":
                qty = _parse_number(value, decimal_format)
                # Quantity of "0" is unusual but means free shares (e.g. Aktia bonus)
                if qty is None and value.strip() == "0":
                    qty = Decimal("0")
                row["quantity"] = qty
            elif field == "avg_price":
                row["avg_price"] = _parse_number(value, decimal_format)
            elif field == "last_price":
                row["last_price"] = _parse_number(value, decimal_format)
            elif field == "market_value":
                row["market_value"] = _parse_number(value, decimal_format)
            elif field == "currency":
                row["currency"] = value.upper() if value else None
            elif field == "account_type":
                row["account_type"] = value
            elif field == "profit_eur":
                row["profit_eur"] = _parse_number(value, decimal_format)

        # Convert prices to cents
        row["avg_price_cents"] = _to_cents(row.get("avg_price"))
        row["last_price_cents"] = _to_cents(row.get("last_price"))
        row["market_value_cents"] = _to_cents(row.get("market_value"))
        row["profit_eur_cents"] = _to_cents(row.get("profit_eur"))

        parsed_rows.append(row)

    logger.info("nordnet_parse_complete", rows=len(parsed_rows))
    return parsed_rows
