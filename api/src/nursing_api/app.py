from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from nursing_core.db import create_engine

from nursing_api.health import router as health_router
from nursing_api.problems import install_problems
from nursing_api.routes import facility, jobs, notes, patients, rough_notes, session
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

    app = FastAPI(
        title="Nursing Documentation AI API",
        version="0.1.0",
        lifespan=lifespan,
        separate_input_output_schemas=False,
    )
    app.include_router(health_router)
    for module in (facility, session, patients, rough_notes, jobs, notes):
        app.include_router(module.router)
    install_problems(app)
    return app
