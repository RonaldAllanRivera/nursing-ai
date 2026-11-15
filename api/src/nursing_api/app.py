from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from nursing_core.clock import SystemClock
from nursing_core.db import create_engine
from nursing_core.ports import Clock
from nursing_core.storage.repositories import (
    PgFacilityRepository,
    PgNoteRepository,
    PgPatientRepository,
    PgSessionRepository,
    PgUsageRepository,
    PgUserRepository,
)

from nursing_api.health import router as health_router
from nursing_api.logging import RequestLogMiddleware, configure_logging
from nursing_api.problems import install_problems
from nursing_api.routes import facility, jobs, notes, patients, rough_notes, session
from nursing_api.settings import Settings


def create_app(settings: Settings | None = None, *, clock: Clock | None = None) -> FastAPI:
    """Builds the app. Tests pass their own settings and a clock they can move."""
    resolved = settings if settings is not None else Settings()  # pyright: ignore[reportCallIssue]
    the_clock: Clock = clock if clock is not None else SystemClock()
    configure_logging()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        engine = create_engine(resolved.database_url)
        app.state.settings = resolved
        app.state.clock = the_clock
        app.state.engine = engine
        app.state.users = PgUserRepository(engine)
        app.state.sessions = PgSessionRepository(engine)
        app.state.usage = PgUsageRepository(engine)
        app.state.facilities = PgFacilityRepository(engine, the_clock)
        app.state.patients = PgPatientRepository(engine, the_clock)
        app.state.notes = PgNoteRepository(engine, the_clock)
        try:
            yield
        finally:
            await engine.dispose()

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
    app.add_middleware(RequestLogMiddleware)
    return app
