"""Parser for pasted Nordnet transaction-history rows (Finnish web UI).

Handles the block format shown in Nordnet's transaction ledger, e.g.:

    22.7.2026
    Account Holder · 00000000
    Osinko
    EXAMPLE Corp
    100
    0,22
    -
    22,00 EUR
    Klikkaa kuvaketta ladataksesi pdf

Records are separated by the "Klikkaa kuvaketta ladataksesi pdf" marker.
Header lines (Päivä / Tili / Tapahtumatyyppi / Kuvaus / Määrä / Kurssi /
Kulut / Summa / PDF) are stripped if present at the top of the paste.

Distinct from `nordnet_parser.py`, which parses the holdings-snapshot CSV.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.securities import Security
from app.db.models.transactions import Transaction


# ── Static mappings (extend when new accounts / types show up) ────────────

TYPE_MAP: dict[str, str] = {
    "osto": "buy",
    "myynti": "sell",
    "osinko": "dividend",
    "talletus": "deposit",
    "nosto": "withdrawal",
    "palkkio": "fee",
    "korko": "interest",
}

# Nordnet account number → account_id in our DB.
# Loaded from the NORDNET_ACCOUNT_MAP env var (format: "nordnet_id:internal_id,nordnet_id:internal_id").
# Kept out of source to avoid committing personal account identifiers.
def _load_account_map() -> dict[str, int]:
    raw = os.environ.get("NORDNET_ACCOUNT_MAP", "").strip()
    if not raw:
        return {}
    result: dict[str, int] = {}
    for pair in raw.split(","):
        if ":" not in pair:
            continue
        k, v = pair.split(":", 1)
        k = k.strip()
        v = v.strip()
        if k and v.isdigit():
            result[k] = int(v)
    return result


ACCOUNT_NUMBER_MAP: dict[str, int] = _load_account_map()

HEADER_STRINGS: set[str] = {
    "päivä", "tili", "tapahtumatyyppi", "kuvaus",
    "määrä", "kurssi", "kulut", "summa", "pdf",
}

DELIMITER_MARKER = "klikkaa kuvaketta"  # start-of-line, after lower()

# Types that require a security_id
NEEDS_SECURITY = {"buy", "sell", "dividend"}

# Types where Nordnet's shown total is money leaving the account
NEGATIVE_CASH_TYPES = {"buy", "withdrawal", "fee"}


# ── Data structure ────────────────────────────────────────────────────────

@dataclass
class ParsedRow:
    index: int
    raw: list[str] = field(default_factory=list)

    # Parsed fields
    trade_date: Optional[str] = None       # ISO YYYY-MM-DD
    account_number: Optional[str] = None
    type_finnish: Optional[str] = None
    tx_type: Optional[str] = None           # internal enum value
    security_name: Optional[str] = None
    quantity: Optional[Decimal] = None
    price_value: Optional[Decimal] = None
    price_currency: Optional[str] = None
    fee_value: Decimal = Decimal("0")
    fee_currency: str = "EUR"
    total_value: Optional[Decimal] = None   # signed as-shown in Nordnet
    total_currency: Optional[str] = None

    # Resolution
    account_id: Optional[int] = None
    security_id: Optional[int] = None
    security_ticker: Optional[str] = None
    security_match_confidence: str = "none"  # high | medium | ambiguous | none

    # Diagnostics
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    # Post-commit / duplicate check
    existing_transaction_id: Optional[int] = None
    committed_transaction_id: Optional[int] = None
    status: str = "pending"  # pending | ok | duplicate | needs_review | error | committed

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "raw": self.raw,
            "parsed": {
                "tradeDate": self.trade_date,
                "accountNumber": self.account_number,
                "typeFinnish": self.type_finnish,
                "type": self.tx_type,
                "securityName": self.security_name,
                "quantity": str(self.quantity) if self.quantity is not None else None,
                "price": str(self.price_value) if self.price_value is not None else None,
                "priceCurrency": self.price_currency,
                "fee": str(self.fee_value),
                "feeCurrency": self.fee_currency,
                "total": str(self.total_value) if self.total_value is not None else None,
                "totalCurrency": self.total_currency,
            },
            "resolution": {
                "accountId": self.account_id,
                "securityId": self.security_id,
                "securityTicker": self.security_ticker,
                "securityMatchConfidence": self.security_match_confidence,
            },
            "status": self.status,
            "warnings": self.warnings,
            "errors": self.errors,
            "existingTransactionId": self.existing_transaction_id,
            "committedTransactionId": self.committed_transaction_id,
        }


# ── Text-level parsing ────────────────────────────────────────────────────

def _normalize_chars(text: str) -> str:
    return (
        text.replace("−", "-")   # unicode minus
            .replace("–", "-")   # en dash
            .replace("—", "-")   # em dash
            .replace(" ", " ")   # nbsp
    )


def _split_records(text: str) -> list[list[str]]:
    text = _normalize_chars(text)
    records: list[list[str]] = []
    current: list[str] = []

    for line in text.splitlines():
        stripped = line.strip()
        low = stripped.lower()
        if not stripped:
            continue
        if low in HEADER_STRINGS:
            continue
        if low.startswith(DELIMITER_MARKER):
            if current:
                records.append(current)
                current = []
            continue
        current.append(stripped)

    # Trailing record without delimiter — only accept if it looks complete
    if current and len(current) >= 8:
        records.append(current)
    return records


_DATE_RE = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$")
_ACCOUNT_RE = re.compile(r"·\s*(\d+)")


def _parse_finnish_number(text: str) -> Optional[Decimal]:
    """Parse '1 119' → 1119, '30,595' → 30.595, '-9 185,84 EUR' → -9185.84."""
    s = text.strip()
    if not s or s == "-":
        return None
    s = re.sub(r"\s*[A-Z]{3}\s*$", "", s)  # strip trailing currency code
    s = s.replace(" ", "").replace(",", ".")
    try:
        return Decimal(s)
    except Exception:
        return None


def _parse_amount(text: str) -> tuple[Optional[Decimal], Optional[str]]:
    s = text.strip()
    if not s or s == "-":
        return None, None
    m = re.search(r"([A-Z]{3})\s*$", s)
    ccy = m.group(1) if m else None
    return _parse_finnish_number(s), ccy


def _parse_one(lines: list[str], index: int) -> ParsedRow:
    row = ParsedRow(index=index, raw=list(lines))
    if len(lines) != 8:
        row.errors.append(
            f"expected 8 non-empty lines per record, got {len(lines)}"
        )
        row.status = "error"
        return row

    (
        date_str, account_line, type_str, security_str,
        qty_str, price_str, fee_str, total_str,
    ) = lines

    m = _DATE_RE.match(date_str)
    if not m:
        row.errors.append(f"unparseable date: {date_str!r}")
    else:
        d, mo, y = m.groups()
        row.trade_date = f"{y}-{int(mo):02d}-{int(d):02d}"

    m = _ACCOUNT_RE.search(account_line)
    if m:
        row.account_number = m.group(1)
    else:
        row.errors.append(f"no Nordnet account number in: {account_line!r}")

    row.type_finnish = type_str
    row.tx_type = TYPE_MAP.get(type_str.lower())
    if not row.tx_type:
        row.errors.append(f"unknown Finnish transaction type: {type_str!r}")

    row.security_name = security_str

    qty = _parse_finnish_number(qty_str)
    if qty is None:
        row.warnings.append(f"unparseable quantity: {qty_str!r}")
    else:
        row.quantity = qty

    row.price_value, row.price_currency = _parse_amount(price_str)

    fee_val, fee_ccy = _parse_amount(fee_str)
    if fee_val is not None:
        row.fee_value = fee_val
        row.fee_currency = fee_ccy or "EUR"

    total_val, total_ccy = _parse_amount(total_str)
    if total_val is None:
        row.errors.append(f"unparseable total: {total_str!r}")
    else:
        row.total_value = total_val
        row.total_currency = total_ccy or "EUR"

    if row.errors:
        row.status = "error"
    return row


def parse_paste(text: str) -> list[ParsedRow]:
    return [_parse_one(rec, i) for i, rec in enumerate(_split_records(text))]


# ── Security matching ────────────────────────────────────────────────────

_CLASS_SUFFIX_RE = re.compile(r"^(.*?)\s+([A-Z])$")


async def resolve_security(session: AsyncSession, name: str) -> tuple[
    Optional[Security], str
]:
    """Look up the security matching a Nordnet-shown name.

    Returns (security_or_None, confidence_label).
    """
    stripped = name.strip()
    m = _CLASS_SUFFIX_RE.match(stripped)
    base = m.group(1) if m else stripped
    class_suffix = m.group(2) if m else None

    q = select(Security).where(
        func.lower(Security.name).like(f"%{base.lower()}%"),
        Security.is_active.is_(True),
    )
    candidates = (await session.execute(q)).scalars().all()

    if not candidates:
        return None, "none"

    if class_suffix:
        with_suffix = [
            c for c in candidates
            if c.name.rstrip().lower().endswith(f" {class_suffix.lower()}")
        ]
        if len(with_suffix) == 1:
            return with_suffix[0], "high"
        if len(with_suffix) > 1:
            return None, "ambiguous"
        # fall through if no share-class exact match

    if len(candidates) == 1:
        return candidates[0], "high" if class_suffix is None else "medium"

    return None, "ambiguous"


# ── Amount → cents ────────────────────────────────────────────────────────

def to_cents(value: Optional[Decimal]) -> Optional[int]:
    if value is None:
        return None
    return int((value * 100).to_integral_value(rounding=ROUND_HALF_UP))


def compute_total_cents(tx_type: str, total_value: Decimal, fee_value: Decimal) -> int:
    """Convert Nordnet's shown total into our stored `total_cents`.

    Conventions in this repo:
      - buy:   gross paid (positive)    = |total| − fee
      - sell:  gross received (positive) = |total| + fee
      - dividend: net received (positive) = |total|
      - deposit: positive
      - withdrawal / fee: negative
    """
    fee = fee_value or Decimal("0")
    abs_total = abs(total_value)
    if tx_type == "buy":
        return to_cents(abs_total - fee) or 0
    if tx_type == "sell":
        return to_cents(abs_total + fee) or 0
    if tx_type == "dividend":
        return to_cents(abs_total) or 0
    if tx_type == "deposit":
        return to_cents(abs_total) or 0
    if tx_type in ("withdrawal", "fee"):
        return -(to_cents(abs_total) or 0)
    return to_cents(total_value) or 0


def external_ref_for(row: ParsedRow) -> str:
    """Deterministic key for idempotent re-runs of the same paste."""
    return (
        f"nordnet-paste:{row.account_number}:{row.trade_date}"
        f":{row.tx_type}:{row.quantity or 0}"
        f":{to_cents(row.total_value) or 0}"
    )


# ── Duplicate detection ───────────────────────────────────────────────────

async def find_duplicate(
    session: AsyncSession,
    row: ParsedRow,
    tolerance_days: int = 10,
) -> Optional[int]:
    """Return an existing transaction id if a probable duplicate exists.

    Matches on (account, type, |total_cents|) within ±tolerance_days, plus
    security_id when the type requires one. Also matches on external_ref
    exactly (same paste re-submitted).
    """
    if not row.trade_date or row.total_value is None or not row.tx_type:
        return None
    if row.account_id is None:
        return None

    ref = external_ref_for(row)
    ref_hit = (await session.execute(
        select(Transaction.id).where(Transaction.external_ref == ref)
    )).scalar_one_or_none()
    if ref_hit:
        return ref_hit

    tdate = date.fromisoformat(row.trade_date)
    # Compare against the value we'd actually store — for buys/sells this is
    # gross-before-fee, not the raw Nordnet number which includes the fee.
    stored_total_cents = abs(
        compute_total_cents(row.tx_type, row.total_value, row.fee_value)
    )

    q = select(Transaction.id).where(
        Transaction.account_id == row.account_id,
        Transaction.type == row.tx_type,
        func.abs(Transaction.total_cents) == stored_total_cents,
        Transaction.trade_date >= tdate - timedelta(days=tolerance_days),
        Transaction.trade_date <= tdate + timedelta(days=tolerance_days),
    )
    if row.tx_type in NEEDS_SECURITY and row.security_id is not None:
        q = q.where(Transaction.security_id == row.security_id)

    return (await session.execute(q)).scalars().first()
