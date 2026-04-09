"""Seed the securities catalog with initial instruments.

Usage:
    python -m scripts.seed-securities

Run from the backend/ directory with the virtualenv active.
"""

import asyncio
import sys
from pathlib import Path

# Add backend dir to path so app imports work
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.config import settings  # noqa: E402
from app.db.engine import async_session  # noqa: E402
from app.db.models.securities import Security  # noqa: E402

SEED_SECURITIES = [
    # Finnish stocks
    {"ticker": "NOK1V.HE", "name": "Nokia Oyj", "asset_class": "stock", "currency": "EUR", "exchange": "XHEL", "sector": "Information Technology", "country": "FI"},
    {"ticker": "NDA-FI.HE", "name": "Nordea Bank Abp", "asset_class": "stock", "currency": "EUR", "exchange": "XHEL", "sector": "Financials", "country": "FI"},
    {"ticker": "SAMPO.HE", "name": "Sampo Oyj", "asset_class": "stock", "currency": "EUR", "exchange": "XHEL", "sector": "Financials", "country": "FI"},
    {"ticker": "UPM.HE", "name": "UPM-Kymmene Oyj", "asset_class": "stock", "currency": "EUR", "exchange": "XHEL", "sector": "Materials", "country": "FI"},
    {"ticker": "NESTE.HE", "name": "Neste Oyj", "asset_class": "stock", "currency": "EUR", "exchange": "XHEL", "sector": "Energy", "country": "FI"},

    # Swedish stocks
    {"ticker": "INVE-B.ST", "name": "Investor AB", "asset_class": "stock", "currency": "SEK", "exchange": "XSTO", "sector": "Financials", "country": "SE"},
    {"ticker": "VOLV-B.ST", "name": "Volvo AB", "asset_class": "stock", "currency": "SEK", "exchange": "XSTO", "sector": "Industrials", "country": "SE"},
    {"ticker": "ATCO-A.ST", "name": "Atlas Copco AB", "asset_class": "stock", "currency": "SEK", "exchange": "XSTO", "sector": "Industrials", "country": "SE"},
    {"ticker": "ERIC-B.ST", "name": "Telefonaktiebolaget LM Ericsson", "asset_class": "stock", "currency": "SEK", "exchange": "XSTO", "sector": "Information Technology", "country": "SE"},

    # US stocks
    {"ticker": "AAPL", "name": "Apple Inc.", "asset_class": "stock", "currency": "USD", "exchange": "XNAS", "sector": "Information Technology", "country": "US", "isin": "US0378331005"},
    {"ticker": "MSFT", "name": "Microsoft Corporation", "asset_class": "stock", "currency": "USD", "exchange": "XNAS", "sector": "Information Technology", "country": "US", "isin": "US5949181045"},
    {"ticker": "BRK-B", "name": "Berkshire Hathaway Inc.", "asset_class": "stock", "currency": "USD", "exchange": "XNYS", "sector": "Financials", "country": "US", "isin": "US0846707026"},
    {"ticker": "JNJ", "name": "Johnson & Johnson", "asset_class": "stock", "currency": "USD", "exchange": "XNYS", "sector": "Health Care", "country": "US", "isin": "US4781601046"},
    {"ticker": "JPM", "name": "JPMorgan Chase & Co.", "asset_class": "stock", "currency": "USD", "exchange": "XNYS", "sector": "Financials", "country": "US", "isin": "US46625H1005"},

    # European stocks
    {"ticker": "ASML", "name": "ASML Holding N.V.", "asset_class": "stock", "currency": "EUR", "exchange": "XAMS", "sector": "Information Technology", "country": "NL", "isin": "NL0010273215"},
    {"ticker": "NOVO-B.CO", "name": "Novo Nordisk A/S", "asset_class": "stock", "currency": "DKK", "exchange": "XCSE", "sector": "Health Care", "country": "DK", "isin": "DK0062498333"},
    {"ticker": "MC.PA", "name": "LVMH Moet Hennessy Louis Vuitton SE", "asset_class": "stock", "currency": "EUR", "exchange": "XPAR", "sector": "Consumer Discretionary", "country": "FR", "isin": "FR0000121014"},
    {"ticker": "NESN.SW", "name": "Nestle S.A.", "asset_class": "stock", "currency": "CHF", "exchange": "XSWX", "sector": "Consumer Staples", "country": "CH", "isin": "CH0038863350"},

    # ETFs
    {"ticker": "IWDA", "name": "iShares Core MSCI World UCITS ETF", "asset_class": "etf", "currency": "USD", "exchange": "XAMS", "is_accumulating": True, "isin": "IE00B4L5Y983"},
    {"ticker": "VUSA", "name": "Vanguard S&P 500 UCITS ETF", "asset_class": "etf", "currency": "USD", "exchange": "XLON", "is_accumulating": False, "isin": "IE00B3XXRP09"},
    {"ticker": "IEGA", "name": "iShares Core Euro Government Bond UCITS ETF", "asset_class": "etf", "currency": "EUR", "exchange": "XAMS", "is_accumulating": True, "isin": "IE00B4WXJJ64"},

    # Norwegian stocks
    {"ticker": "TEL.OL", "name": "Telenor ASA", "asset_class": "stock", "currency": "NOK", "exchange": "XOSL", "sector": "Communication Services", "country": "NO"},
    {"ticker": "GJF.OL", "name": "Gjensidige Forsikring ASA", "asset_class": "stock", "currency": "NOK", "exchange": "XOSL", "sector": "Financials", "country": "NO"},
    {"ticker": "EPR.OL", "name": "Europris ASA", "asset_class": "stock", "currency": "NOK", "exchange": "XOSL", "sector": "Consumer Discretionary", "country": "NO"},
    {"ticker": "DNB.OL", "name": "DNB Bank ASA", "asset_class": "stock", "currency": "NOK", "exchange": "XOSL", "sector": "Financials", "country": "NO"},
    {"ticker": "VEI.OL", "name": "Veidekke ASA", "asset_class": "stock", "currency": "NOK", "exchange": "XOSL", "sector": "Industrials", "country": "NO"},
    {"ticker": "ORK.OL", "name": "Orkla ASA", "asset_class": "stock", "currency": "NOK", "exchange": "XOSL", "sector": "Consumer Staples", "country": "NO"},
    {"ticker": "SRBNK.OL", "name": "SpareBank 1 SR-Bank ASA", "asset_class": "stock", "currency": "NOK", "exchange": "XOSL", "sector": "Financials", "country": "NO"},
    {"ticker": "EQNR.OL", "name": "Equinor ASA", "asset_class": "stock", "currency": "NOK", "exchange": "XOSL", "sector": "Energy", "country": "NO"},
    {"ticker": "MOWI.OL", "name": "Mowi ASA", "asset_class": "stock", "currency": "NOK", "exchange": "XOSL", "sector": "Consumer Staples", "country": "NO"},
    {"ticker": "KOG.OL", "name": "Kongsberg Gruppen ASA", "asset_class": "stock", "currency": "NOK", "exchange": "XOSL", "sector": "Industrials", "country": "NO"},
    {"ticker": "TOM.OL", "name": "Tomra Systems ASA", "asset_class": "stock", "currency": "NOK", "exchange": "XOSL", "sector": "Industrials", "country": "NO"},
    {"ticker": "YAR.OL", "name": "Yara International ASA", "asset_class": "stock", "currency": "NOK", "exchange": "XOSL", "sector": "Materials", "country": "NO"},
    {"ticker": "SALM.OL", "name": "SalMar ASA", "asset_class": "stock", "currency": "NOK", "exchange": "XOSL", "sector": "Consumer Staples", "country": "NO"},
    {"ticker": "KID.OL", "name": "Kid ASA", "asset_class": "stock", "currency": "NOK", "exchange": "XOSL", "sector": "Consumer Discretionary", "country": "NO"},
    {"ticker": "NHY.OL", "name": "Norsk Hydro ASA", "asset_class": "stock", "currency": "NOK", "exchange": "XOSL", "sector": "Materials", "country": "NO"},
    {"ticker": "MING.OL", "name": "SpareBank 1 SMN", "asset_class": "stock", "currency": "NOK", "exchange": "XOSL", "sector": "Financials", "country": "NO"},
    {"ticker": "AFG.OL", "name": "AF Gruppen ASA", "asset_class": "stock", "currency": "NOK", "exchange": "XOSL", "sector": "Industrials", "country": "NO"},
    {"ticker": "AKRBP.OL", "name": "Aker BP ASA", "asset_class": "stock", "currency": "NOK", "exchange": "XOSL", "sector": "Energy", "country": "NO"},
    {"ticker": "LSG.OL", "name": "Lerøy Seafood Group ASA", "asset_class": "stock", "currency": "NOK", "exchange": "XOSL", "sector": "Consumer Staples", "country": "NO"},
    {"ticker": "PROT.OL", "name": "Protector Forsikring ASA", "asset_class": "stock", "currency": "NOK", "exchange": "XOSL", "sector": "Financials", "country": "NO"},

    # Crypto
    {"ticker": "BTC", "name": "Bitcoin", "asset_class": "crypto", "currency": "USD", "coingecko_id": "bitcoin"},
    {"ticker": "ETH", "name": "Ethereum", "asset_class": "crypto", "currency": "USD", "coingecko_id": "ethereum"},
    {"ticker": "SOL", "name": "Solana", "asset_class": "crypto", "currency": "USD", "coingecko_id": "solana"},
]


async def seed():
    print(f"Seeding {len(SEED_SECURITIES)} securities...")
    async with async_session() as session:
        for data in SEED_SECURITIES:
            # Check if already exists (by ticker + exchange or ticker for crypto)
            ticker = data["ticker"]
            exchange = data.get("exchange")
            if exchange:
                result = await session.execute(
                    select(Security).where(
                        Security.ticker == ticker,
                        Security.exchange == exchange,
                    )
                )
            else:
                result = await session.execute(
                    select(Security).where(
                        Security.ticker == ticker,
                        Security.asset_class == "crypto",
                    )
                )
            existing = result.scalar_one_or_none()

            if existing:
                print(f"  SKIP {ticker} (already exists)")
                continue

            security = Security(**data)
            session.add(security)
            print(f"  ADD  {ticker} — {data['name']}")

        await session.commit()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(seed())
