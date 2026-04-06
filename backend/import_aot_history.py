"""
Import AOT (Nordnet Regular account) transaction history from Nordnet export.

Usage:
  # Pipe the tab-separated Nordnet export data:
  docker exec -i bloomvalley-backend-1 python import_aot_history.py < nordnet_export.tsv

  # Or with the data file inside the container:
  docker exec bloomvalley-backend-1 python import_aot_history.py /path/to/export.tsv

The Nordnet export should be tab-separated with Finnish column names.
"""

import asyncio
import sys
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select, delete, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ---------------------------------------------------------------------------
# Database setup (standalone, not using app.config to keep script portable)
# ---------------------------------------------------------------------------
DATABASE_URL = "postgresql+asyncpg://warren:warren@db:5432/warren"
ACCOUNT_ID = 1  # Nordnet - Regular

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# ---------------------------------------------------------------------------
# Nordnet event type → our transaction type mapping
# ---------------------------------------------------------------------------
EVENT_TYPE_MAP = {
    "OSTO": "buy",
    "MYYNTI": "sell",
    "OSINKO": "dividend",
    "TALLETUS": "deposit",
    "LUNASTUS AP KÄT.": "corporate_action",
    "LUNASTUS AP KÄT./OTTO": "corporate_action",
    "OSINKO AP JÄTTÖ": "corporate_action",
    "ETF_KK SÄÄSTÖN PALVELUMAKSU": "fee",
}

# These event types are handled specially (not inserted directly)
SKIP_EVENT_TYPES = {
    "ENNAKKOPIDÄTYS",       # withholding tax - merged into OSINKO
    "LUNASTUS AP OTTO",     # warrant redemption debit - KÄT has the value
}

# ---------------------------------------------------------------------------
# ISIN → security mapping for securities that might need to be created
# ticker, name, asset_class, currency, exchange, country
# ---------------------------------------------------------------------------
SECURITY_DEFAULTS = {
    # Already in DB (fallback if ISIN lookup fails)
    "US5949181045": ("MSFT", "Microsoft Corporation", "stock", "USD", "NASDAQ", "US"),
    "FI0009000202": ("KESKOB.HE", "Kesko Oyj B", "stock", "EUR", "OMXH", "FI"),
    "US0494681010": ("TEAM", "Atlassian Corp", "stock", "USD", "NASDAQ", "US"),
    "US0079031078": ("AMD", "Advanced Micro Devices Inc", "stock", "USD", "NASDAQ", "US"),
    "US7134481081": ("PEP", "PepsiCo Inc", "stock", "USD", "NASDAQ", "US"),
    "US75734B1008": ("RDDT", "Reddit Inc", "stock", "USD", "NYSE", "US"),
    "US0846707026": ("BRK-B", "Berkshire Hathaway Inc", "stock", "USD", "NYSE", "US"),
    # Need to be created
    "FI0008808340": ("ALYK", "Ålandsbanken Lyhyt Yrityskorko B", "fund", "EUR", "OMXH", "FI"),
    "FI4000297767": ("NDA-FI.HE", "Nordea Bank Abp", "stock", "EUR", "OMXH", "FI"),
    "FI4000369442": ("SPRING", "Springvest Oyj", "stock", "EUR", "FNFI", "FI"),
    "FI4000517461": ("WITTED", "Witted Megacorp Oyj", "stock", "EUR", "FNFI", "FI"),
    "FI4000577192": ("SFOODS.HE", "Solar Foods Oyj", "stock", "EUR", "OMXH", "FI"),
    "FR0000120628": ("CS.PA", "AXA SA", "stock", "EUR", "XPAR", "FR"),
    "IE00B4ND3602": ("PPFB.DE", "iShares Physical Gold ETC", "etf", "EUR", "XETR", "IE"),
    "IE00B1XNHC34": ("INRG.L", "iShares Global Clean Energy Transition UCITS ETF", "etf", "EUR", "XLON", "IE"),
    "JE00BN7KB664": ("WHEAT.L", "WisdomTree Wheat", "etf", "EUR", "XLON", "JE"),
    "SE0002756973": ("NORDSVIX", "Nordnet Sverige Index", "fund", "SEK", None, "SE"),
    "SE0017078447": ("SHRT-TSLA", "Short Tesla Nordnet F30", "etf", "EUR", "XSTO", "SE"),
    "SE0023289046": ("SHRT-NVDA", "Short NVIDIA Nordnet F28", "etf", "EUR", "XSTO", "SE"),
    "US02079K1079": ("GOOG", "Alphabet Inc Class C", "stock", "USD", "NASDAQ", "US"),
    "US02079K3059": ("GOOGL", "Alphabet Inc Class A", "stock", "USD", "NASDAQ", "US"),
    "US0231351067": ("AMZN", "Amazon.com Inc", "stock", "USD", "NASDAQ", "US"),
    "US26740W1099": ("QBTS", "D-Wave Quantum Inc", "stock", "USD", "NYSE", "US"),
    "US7731211089": ("RKLB", "Rocket Lab USA Inc", "stock", "USD", "NASDAQ", "US"),
    "US91324P1021": ("UNH", "UnitedHealth Group Inc", "stock", "USD", "NYSE", "US"),
}


def parse_finnish_decimal(s: str) -> Decimal:
    """Parse a Finnish-format number: 1.234,56 → 1234.56"""
    if not s or s.strip() in ("", "-"):
        return Decimal("0")
    s = s.strip().replace("\xa0", "").replace(" ", "")
    # Finnish: dot as thousand separator, comma as decimal
    s = s.replace(".", "").replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        print(f"  WARNING: Could not parse number: '{s}'", file=sys.stderr)
        return Decimal("0")


def parse_finnish_date(s: str) -> date | None:
    """Parse date in Finnish format: 2025-01-30 or 30.01.2025 or similar."""
    if not s or s.strip() in ("", "-"):
        return None
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    print(f"  WARNING: Could not parse date: '{s}'", file=sys.stderr)
    return None


def to_cents(amount: Decimal) -> int:
    """Convert a decimal amount to cents (integer)."""
    return int((amount * 100).to_integral_value())


def parse_rows(raw_text: str) -> list[dict]:
    """Parse tab-separated Nordnet export into list of dicts."""
    lines = raw_text.strip().split("\n")
    if not lines:
        return []

    # Find header line (contains 'Tapahtumatyyppi')
    header_idx = 0
    for i, line in enumerate(lines):
        if "Tapahtumatyyppi" in line or "Id\t" in line:
            header_idx = i
            break

    headers = lines[header_idx].split("\t")
    # Clean BOM and whitespace from headers
    headers = [h.strip().strip("\ufeff") for h in headers]
    # Deduplicate repeated column names (e.g., multiple "Valuutta" columns)
    seen = {}
    for i, h in enumerate(headers):
        if h in seen:
            seen[h] += 1
            headers[i] = f"{h}_{seen[h]}"
        else:
            seen[h] = 0

    rows = []
    for line in lines[header_idx + 1:]:
        if not line.strip():
            continue
        cols = line.split("\t")
        row = {}
        for i, h in enumerate(headers):
            row[h] = cols[i].strip() if i < len(cols) else ""
        rows.append(row)

    return rows


async def ensure_security(session: AsyncSession, isin: str, name: str,
                          isin_to_id: dict[str, int]) -> int | None:
    """Look up or create a security by ISIN. Returns security_id."""
    if not isin or isin.strip() == "":
        return None

    if isin in isin_to_id:
        return isin_to_id[isin]

    # Look up in DB
    result = await session.execute(
        text("SELECT id FROM securities WHERE isin = :isin"),
        {"isin": isin},
    )
    row = result.fetchone()
    if row:
        isin_to_id[isin] = row[0]
        return row[0]

    # Create new security
    defaults = SECURITY_DEFAULTS.get(isin)
    if defaults:
        ticker, sec_name, asset_class, currency, exchange, country = defaults
    else:
        # Best-effort defaults from the transaction data
        ticker = isin[:6]  # placeholder
        sec_name = name or isin
        asset_class = "stock"
        currency = "EUR"
        exchange = None
        country = None
        print(f"  WARNING: Unknown ISIN {isin} ({name}), creating with defaults",
              file=sys.stderr)

    result = await session.execute(
        text("""
            INSERT INTO securities (ticker, isin, name, asset_class, currency, exchange, country)
            VALUES (:ticker, :isin, :name, :asset_class, :currency, :exchange, :country)
            ON CONFLICT DO NOTHING
            RETURNING id
        """),
        {
            "ticker": ticker, "isin": isin, "name": sec_name,
            "asset_class": asset_class, "currency": currency,
            "exchange": exchange, "country": country,
        },
    )
    row = result.fetchone()
    if row:
        sec_id = row[0]
        print(f"  Created security: {ticker} ({sec_name}) [ISIN: {isin}] → id={sec_id}")
    else:
        # ON CONFLICT - re-fetch
        result = await session.execute(
            text("SELECT id FROM securities WHERE isin = :isin"),
            {"isin": isin},
        )
        row = result.fetchone()
        sec_id = row[0] if row else None

    if sec_id:
        isin_to_id[isin] = sec_id
    return sec_id


async def main():
    # Read input
    if len(sys.argv) > 1:
        with open(sys.argv[1], "r", encoding="utf-8-sig") as f:
            raw_text = f.read()
    else:
        raw_text = sys.stdin.read()

    if not raw_text.strip():
        print("ERROR: No input data provided.", file=sys.stderr)
        print(__doc__)
        sys.exit(1)

    rows = parse_rows(raw_text)
    print(f"Parsed {len(rows)} rows from Nordnet export")

    # ---------------------------------------------------------------------------
    # Group dividend + withholding tax entries by confirmation number
    # ---------------------------------------------------------------------------
    # Key: vahvistusnumero → list of rows
    confirmation_groups: dict[str, list[dict]] = defaultdict(list)
    regular_rows: list[dict] = []

    for row in rows:
        event_type = row.get("Tapahtumatyyppi", "").strip()
        # For dividend/withholding rows, confirmation number may be in
        # Vahvistusnumero or Tapahtumateksti (column shift in Nordnet export)
        conf_num = row.get("Vahvistusnumero", "").strip()
        if not conf_num or not conf_num.isdigit():
            conf_num = row.get("Tapahtumateksti", "").strip()
        if not conf_num or not conf_num.isdigit():
            conf_num = row.get("Laskelma", "").strip()

        if event_type == "OSINKO" and conf_num:
            confirmation_groups[conf_num].append(row)
        elif event_type == "ENNAKKOPIDÄTYS" and conf_num:
            confirmation_groups[conf_num].append(row)
        elif event_type in SKIP_EVENT_TYPES:
            print(f"  Skipping: {event_type} - {row.get('Arvopaperi', '')} "
                  f"({row.get('Kauppapäivä', '')})")
            continue
        else:
            regular_rows.append(row)

    # ---------------------------------------------------------------------------
    # Process
    # ---------------------------------------------------------------------------
    async with async_session() as session:
        isin_to_id: dict[str, int] = {}

        # Pre-load all securities
        result = await session.execute(text("SELECT isin, id FROM securities WHERE isin IS NOT NULL"))
        for r in result.fetchall():
            isin_to_id[r[0]] = r[1]
        print(f"Loaded {len(isin_to_id)} securities from DB")

        transactions_to_insert = []

        # --- Process dividend groups ---
        for conf_num, group in confirmation_groups.items():
            dividend_row = None
            withholding_rows = []
            for r in group:
                if r["Tapahtumatyyppi"].strip() == "OSINKO":
                    dividend_row = r
                elif r["Tapahtumatyyppi"].strip() == "ENNAKKOPIDÄTYS":
                    withholding_rows.append(r)

            if not dividend_row:
                print(f"  WARNING: Confirmation {conf_num} has no OSINKO row, skipping",
                      file=sys.stderr)
                continue

            isin = dividend_row.get("ISIN", "").strip()
            name = dividend_row.get("Arvopaperi", "").strip()
            security_id = await ensure_security(session, isin, name, isin_to_id)

            trade_date = parse_finnish_date(dividend_row.get("Kauppapäivä", ""))
            settlement_date = parse_finnish_date(dividend_row.get("Maksupäivä", ""))
            quantity = parse_finnish_decimal(dividend_row.get("Määrä", ""))

            # Nordnet dividend rows have fewer columns — the gross amount is in the
            # "Valuutta" column position (col 13, header dedupped as "Valuutta").
            # Try both "Summa" and "Valuutta" to find the numeric amount.
            div_summa = parse_finnish_decimal(dividend_row.get("Summa", ""))
            if div_summa == Decimal("0"):
                # Dividend amount shifted to Valuutta column (Nordnet formatting quirk)
                div_summa = parse_finnish_decimal(dividend_row.get("Valuutta", ""))
            if div_summa == Decimal("0"):
                div_summa = parse_finnish_decimal(dividend_row.get("Kokonaiskulut", ""))
            fx_rate_str = dividend_row.get("Vaihtokurssi", "").strip()
            fx_rate = parse_finnish_decimal(fx_rate_str) if fx_rate_str else None

            # Withholding tax (absolute value - ENNAKKOPIDÄTYS amount is negative)
            withholding_total = Decimal("0")
            for wr in withholding_rows:
                wh_amount = parse_finnish_decimal(wr.get("Summa", ""))
                if wh_amount == Decimal("0"):
                    wh_amount = parse_finnish_decimal(wr.get("Valuutta", ""))
                if wh_amount == Decimal("0"):
                    wh_amount = parse_finnish_decimal(wr.get("Kokonaiskulut", ""))
                withholding_total += abs(wh_amount)

            # Net dividend = gross - withholding
            gross_cents = to_cents(abs(div_summa))
            withholding_cents = to_cents(withholding_total)
            net_cents = gross_cents - withholding_cents

            # Price per share in dividend currency
            price = parse_finnish_decimal(dividend_row.get("Kurssi", ""))
            price_cents = to_cents(price) if price else None

            # Determine the dividend currency from the Kurssi context
            # For Finnish stocks it's EUR, for US stocks it might be USD
            # The "Hankinta-arvo" column has the foreign currency total
            hankinta = parse_finnish_decimal(dividend_row.get("Hankinta-arvo", ""))

            # Detect currency: if there's a fx_rate and hankinta > 0, the dividend
            # is in foreign currency
            if fx_rate and fx_rate != Decimal("0") and fx_rate != Decimal("1") and hankinta:
                # Foreign currency dividend
                currency = "USD"  # Most common; Nordnet export doesn't cleanly separate
                total_cents_txn = to_cents(abs(hankinta))
            else:
                currency = "EUR"
                total_cents_txn = net_cents

            transactions_to_insert.append({
                "account_id": ACCOUNT_ID,
                "security_id": security_id,
                "type": "dividend",
                "trade_date": trade_date,
                "settlement_date": settlement_date,
                "quantity": quantity,
                "price_cents": price_cents,
                "price_currency": currency,
                "total_cents": net_cents,  # Net in EUR as per user's request
                "fee_cents": 0,
                "fee_currency": "EUR",
                "currency": "EUR",  # total_cents is always in EUR for dividends
                "fx_rate": fx_rate if fx_rate and fx_rate != Decimal("0") else None,
                "withholding_tax_cents": withholding_cents,
                "notes": f"Nordnet conf# {conf_num}",
                "external_ref": conf_num,
            })

        # --- Process regular rows ---
        for row in regular_rows:
            event_type = row.get("Tapahtumatyyppi", "").strip()
            mapped_type = EVENT_TYPE_MAP.get(event_type)

            if not mapped_type:
                print(f"  WARNING: Unknown event type '{event_type}', skipping: "
                      f"{row.get('Arvopaperi', '')} ({row.get('Kauppapäivä', '')})",
                      file=sys.stderr)
                continue

            isin = row.get("ISIN", "").strip()
            name = row.get("Arvopaperi", "").strip()
            conf_num = row.get("Vahvistusnumero", "").strip()

            # Security lookup (deposits don't have securities)
            security_id = None
            if mapped_type != "deposit" and isin:
                security_id = await ensure_security(session, isin, name, isin_to_id)

            trade_date = parse_finnish_date(row.get("Kauppapäivä", ""))
            settlement_date = parse_finnish_date(row.get("Maksupäivä", ""))
            quantity = abs(parse_finnish_decimal(row.get("Määrä", "")))
            price = parse_finnish_decimal(row.get("Kurssi", ""))
            fees = abs(parse_finnish_decimal(row.get("Kokonaiskulut", "")))
            summa = parse_finnish_decimal(row.get("Summa", ""))  # EUR total
            hankinta = parse_finnish_decimal(row.get("Hankinta-arvo", ""))  # Foreign currency total
            fx_rate_str = row.get("Vaihtokurssi", "").strip()
            fx_rate = parse_finnish_decimal(fx_rate_str) if fx_rate_str else None

            price_cents = to_cents(abs(price)) if price else None

            # Determine if foreign currency transaction
            is_foreign = (fx_rate and fx_rate != Decimal("0")
                          and fx_rate != Decimal("1")
                          and hankinta and hankinta != Decimal("0"))

            if is_foreign:
                # Foreign currency: total_cents is in transaction currency
                # hankinta-arvo has the foreign currency total
                total_cents = to_cents(abs(hankinta))
                # Detect currency from ISIN prefix
                if isin.startswith("US"):
                    currency = "USD"
                elif isin.startswith("SE"):
                    currency = "SEK"
                elif isin.startswith("GB"):
                    currency = "GBP"
                else:
                    currency = "USD"  # default for foreign
            else:
                # EUR transaction
                total_cents = to_cents(abs(summa))
                currency = "EUR"

            fee_cents = to_cents(fees)

            # For deposits, total_cents = summa, no security
            if mapped_type == "deposit":
                total_cents = to_cents(abs(summa))
                currency = "EUR"
                price_cents = None

            # For fees (ETF savings plan service fee)
            if mapped_type == "fee":
                total_cents = to_cents(abs(summa))
                currency = "EUR"

            # For corporate actions
            if mapped_type == "corporate_action":
                if not total_cents:
                    total_cents = to_cents(abs(summa)) if summa else 0

            transactions_to_insert.append({
                "account_id": ACCOUNT_ID,
                "security_id": security_id,
                "type": mapped_type,
                "trade_date": trade_date,
                "settlement_date": settlement_date,
                "quantity": quantity,
                "price_cents": price_cents,
                "price_currency": currency if price_cents else None,
                "total_cents": total_cents,
                "fee_cents": fee_cents,
                "fee_currency": "EUR",
                "currency": currency,
                "fx_rate": fx_rate if fx_rate and fx_rate != Decimal("0") else None,
                "withholding_tax_cents": 0,
                "notes": f"Nordnet {event_type}" + (f" conf# {conf_num}" if conf_num else ""),
                "external_ref": conf_num if conf_num else None,
            })

        # ---------------------------------------------------------------------------
        # Delete existing transfer_in placeholder transactions for account_id=1
        # ---------------------------------------------------------------------------
        # Delete ALL existing transactions for this account (replacing with full history)
        result = await session.execute(
            text("SELECT COUNT(*) FROM transactions WHERE account_id = :aid"),
            {"aid": ACCOUNT_ID},
        )
        existing_count = result.scalar()
        print(f"\nFound {existing_count} existing transactions for account_id={ACCOUNT_ID}")

        if existing_count > 0:
            # Delete dependent tax_lots first
            await session.execute(
                text("""
                    DELETE FROM tax_lots WHERE open_transaction_id IN (
                        SELECT id FROM transactions WHERE account_id = :aid
                    ) OR close_transaction_id IN (
                        SELECT id FROM transactions WHERE account_id = :aid
                    )
                """),
                {"aid": ACCOUNT_ID},
            )
            # Delete dependent dividends
            await session.execute(
                text("""
                    DELETE FROM dividends WHERE transaction_id IN (
                        SELECT id FROM transactions WHERE account_id = :aid
                    )
                """),
                {"aid": ACCOUNT_ID},
            )
            await session.execute(
                text("DELETE FROM transactions WHERE account_id = :aid"),
                {"aid": ACCOUNT_ID},
            )
            print(f"  Deleted {existing_count} existing transactions")

        # ---------------------------------------------------------------------------
        # Insert new transactions
        # ---------------------------------------------------------------------------
        print(f"\nInserting {len(transactions_to_insert)} transactions...")
        inserted = 0
        for txn in transactions_to_insert:
            if txn["trade_date"] is None:
                print(f"  WARNING: Skipping transaction with no trade date: {txn}",
                      file=sys.stderr)
                continue

            await session.execute(
                text("""
                    INSERT INTO transactions (
                        account_id, security_id, type, trade_date, settlement_date,
                        quantity, price_cents, price_currency, total_cents,
                        fee_cents, fee_currency, currency, fx_rate,
                        withholding_tax_cents, notes, external_ref
                    ) VALUES (
                        :account_id, :security_id, :type, :trade_date, :settlement_date,
                        :quantity, :price_cents, :price_currency, :total_cents,
                        :fee_cents, :fee_currency, :currency, :fx_rate,
                        :withholding_tax_cents, :notes, :external_ref
                    )
                """),
                txn,
            )
            inserted += 1

        await session.commit()
        print(f"\nDone! Inserted {inserted} transactions for account_id={ACCOUNT_ID}")

        # Summary by type
        result = await session.execute(
            text("""
                SELECT type, COUNT(*), SUM(total_cents)
                FROM transactions
                WHERE account_id = :aid
                GROUP BY type
                ORDER BY type
            """),
            {"aid": ACCOUNT_ID},
        )
        print("\nTransaction summary for account_id=1:")
        for r in result.fetchall():
            total_eur = r[2] / 100 if r[2] else 0
            print(f"  {r[0]:20s}: {r[1]:4d} transactions, total: {total_eur:>12,.2f} EUR")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
