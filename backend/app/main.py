from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.forecasts import router as forecasts_router
from app.api.health import router as health_router
from app.api.markets import router as markets_router
from app.api.matching import router as matching_router
from app.api.sports import router as sports_router
from app.db.session import dispose_engine


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Release database resources when the application shuts down."""
    yield
    await dispose_engine()


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    application = FastAPI(
        title="LATM API",
        version="0.5.0",
        lifespan=lifespan,
    )
    application.include_router(health_router)
    application.include_router(markets_router)
    application.include_router(sports_router)
    application.include_router(matching_router)
    application.include_router(forecasts_router)
    return application


app = create_app()
