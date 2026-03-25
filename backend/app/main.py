from contextlib import asynccontextmanager

import redis.asyncio as aioredis
import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

from app.config import settings
from app.db.engine import engine

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting Bloomvalley backend")

    # Verify DB engine is connectable
    async with engine.begin() as conn:
        await conn.execute(
            __import__("sqlalchemy").text("SELECT 1")
        )
    logger.info("Database connected")

    # Connect Redis
    app.state.redis = aioredis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
    )
    await app.state.redis.ping()
    logger.info("Redis connected")

    yield

    # Shutdown
    logger.info("Shutting down Bloomvalley backend")
    await app.state.redis.close()
    await engine.dispose()
    logger.info("Shutdown complete")


app = FastAPI(
    title="Bloomvalley",
    description="Personal Bloomberg terminal API",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API key authentication middleware
@app.middleware("http")
async def check_api_key(request: Request, call_next):
    # Skip auth if no API_KEY configured (backwards compatible)
    if not settings.API_KEY:
        return await call_next(request)

    # Allow health, root, docs without auth
    if request.url.path in ("/", "/docs", "/openapi.json", "/api/v1/health"):
        return await call_next(request)

    # Only protect /api/* routes
    if request.url.path.startswith("/api/"):
        key = request.headers.get("X-API-Key")
        if key != settings.API_KEY:
            return JSONResponse(status_code=401, content={"detail": "Invalid or missing API key"})

    return await call_next(request)


# Include v1 router
from app.api.v1.router import router as v1_router  # noqa: E402

app.include_router(v1_router, prefix="/api/v1")


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/api/v1/health")
