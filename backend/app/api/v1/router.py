from fastapi import APIRouter

from app.api.v1.accounts import router as accounts_router
from app.api.v1.dividends import router as dividends_router
from app.api.v1.health import router as health_router
from app.api.v1.imports import router as imports_router
from app.api.v1.pipelines import router as pipelines_router
from app.api.v1.portfolio import router as portfolio_router
from app.api.v1.prices import router as prices_router
from app.api.v1.charts import router as charts_router
from app.api.v1.macro import router as macro_router
from app.api.v1.transactions import router as transactions_router
from app.api.v1.risk import router as risk_router
from app.api.v1.securities import router as securities_router
from app.api.v1.watchlists import router as watchlists_router

# Import pipelines to trigger registration
import app.pipelines.yahoo_finance  # noqa: F401
import app.pipelines.ecb  # noqa: F401
import app.pipelines.coingecko  # noqa: F401
import app.pipelines.fred  # noqa: F401
import app.pipelines.ecb_macro  # noqa: F401
import app.pipelines.yahoo_dividends  # noqa: F401

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
