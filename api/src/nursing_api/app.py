from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from nursing_core.db import create_engine

from nursing_api.health import router as health_router
from nursing_api.settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings if settings is not None else Settings()  # pyright: ignore[reportCallIssue]

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        app.state.settings = resolved
        app.state.engine = create_engine(resolved.database_url)
        try:
            yield
        finally:
            await app.state.engine.dispose()

    app = FastAPI(title="Nursing Documentation AI API", version="0.1.0", lifespan=lifespan)
    app.include_router(health_router)
    return app
