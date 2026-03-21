from fastapi import APIRouter

from app.api.v1.accounts import router as accounts_router
from app.api.v1.alerts import router as alerts_router
from app.api.v1.backtest import router as backtest_router
from app.api.v1.factors import router as factors_router
from app.api.v1.dividends import router as dividends_router
from app.api.v1.fixed_income import router as fixed_income_router
from app.api.v1.fundamentals import router as fundamentals_router
from app.api.v1.optimization import router as optimization_router
from app.api.v1.projections import router as projections_router
from app.api.v1.health import router as health_router
from app.api.v1.insider import router as insider_router
from app.api.v1.imports import router as imports_router
from app.api.v1.pipelines import router as pipelines_router
from app.api.v1.portfolio import router as portfolio_router
from app.api.v1.prices import router as prices_router
from app.api.v1.charts import router as charts_router
from app.api.v1.macro import router as macro_router
from app.api.v1.news import router as news_router
from app.api.v1.transactions import router as transactions_router
from app.api.v1.risk import router as risk_router
from app.api.v1.securities import router as securities_router
from app.api.v1.research import router as research_router
from app.api.v1.tax import router as tax_router
from app.api.v1.recommendations import router as recommendations_router
from app.api.v1.reports import router as reports_router
from app.api.v1.screener import router as screener_router
from app.api.v1.technical import router as technical_router
from app.api.v1.watchlists import router as watchlists_router

# Import pipelines to trigger registration
import app.pipelines.yahoo_finance  # noqa: F401
import app.pipelines.ecb  # noqa: F401
import app.pipelines.coingecko  # noqa: F401
import app.pipelines.fred  # noqa: F401
import app.pipelines.ecb_macro  # noqa: F401
import app.pipelines.yahoo_dividends  # noqa: F401
import app.pipelines.google_news  # noqa: F401
import app.pipelines.openinsider  # noqa: F401
import app.pipelines.nasdaq_nordic_insider  # noqa: F401
import app.pipelines.fi_se_insider  # noqa: F401
import app.pipelines.alpha_vantage  # noqa: F401
import app.pipelines.justetf  # noqa: F401
import app.pipelines.sec_edgar  # noqa: F401
import app.pipelines.quiver_congress  # noqa: F401
import app.pipelines.gdelt  # noqa: F401
import app.pipelines.morningstar  # noqa: F401
import app.pipelines.french_factors  # noqa: F401

router = APIRouter()

router.include_router(health_router, tags=["Health"])
router.include_router(securities_router, prefix="/securities", tags=["Securities"])
router.include_router(accounts_router, prefix="/accounts", tags=["Accounts"])
router.include_router(pipelines_router, tags=["Pipelines"])
router.include_router(prices_router, prefix="/prices", tags=["Prices"])
router.include_router(imports_router, prefix="/imports", tags=["Imports"])
router.include_router(portfolio_router, prefix="/portfolio", tags=["Portfolio"])
router.include_router(watchlists_router, prefix="/watchlists", tags=["Watchlists"])
router.include_router(charts_router, prefix="/charts", tags=["Charts"])
router.include_router(macro_router, prefix="/macro", tags=["Macro"])
router.include_router(transactions_router, prefix="/transactions", tags=["Transactions"])
router.include_router(risk_router, prefix="/risk", tags=["Risk"])
router.include_router(dividends_router, prefix="/dividends", tags=["Dividends"])
router.include_router(research_router, prefix="/research", tags=["Research"])
router.include_router(news_router, prefix="/news", tags=["News"])
router.include_router(tax_router, prefix="/tax", tags=["Tax"])
router.include_router(insider_router, prefix="/insiders", tags=["Insiders"])
router.include_router(recommendations_router, prefix="/recommendations", tags=["Recommendations"])
router.include_router(alerts_router, prefix="/alerts", tags=["Alerts"])
router.include_router(fixed_income_router, prefix="/fixed-income", tags=["Fixed Income"])
router.include_router(fundamentals_router, prefix="/fundamentals", tags=["Fundamentals"])
router.include_router(projections_router, prefix="/projections", tags=["Projections"])
router.include_router(factors_router, prefix="/factors", tags=["Factors"])
router.include_router(optimization_router, prefix="/optimization", tags=["Optimization"])
router.include_router(backtest_router, prefix="/backtest", tags=["Backtest"])
router.include_router(reports_router, prefix="/reports", tags=["Reports"])
router.include_router(technical_router, prefix="/technical", tags=["Technical Analysis"])
router.include_router(screener_router, prefix="/screener", tags=["Screener"])
