"""Import all models so Alembic and SQLAlchemy can discover them."""

from app.db.models.accounts import Account  # noqa: F401
from app.db.models.alerts import Alert  # noqa: F401
from app.db.models.corporate_actions import CorporateAction  # noqa: F401
from app.db.models.dividends import Dividend  # noqa: F401
from app.db.models.esg_scores import EsgScore  # noqa: F401
from app.db.models.holdings_snapshot import HoldingsSnapshot  # noqa: F401
from app.db.models.pipeline_runs import PipelineRun  # noqa: F401
from app.db.models.prices import FxRate, MacroIndicator, Price  # noqa: F401
from app.db.models.insider import InsiderTrade, CongressTrade, BuybackProgram  # noqa: F401
from app.db.models.news import NewsItem, NewsItemSecurity  # noqa: F401
from app.db.models.research_notes import ResearchNote  # noqa: F401
from app.db.models.securities import Security  # noqa: F401
from app.db.models.tax_lots import TaxLot  # noqa: F401
from app.db.models.transactions import Transaction  # noqa: F401
from app.db.models.watchlists import Watchlist, WatchlistItem  # noqa: F401
