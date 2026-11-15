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
from nursing_api.providers import ProviderFor, check_live_settings, provider_factory
from nursing_api.routes import facility, jobs, notes, patients, rough_notes, session
from nursing_api.settings import Settings
from nursing_api.worker import DraftWorker, InProcessQueue


def create_app(
    settings: Settings | None = None,
    *,
    clock: Clock | None = None,
    provider_for: ProviderFor | None = None,
) -> FastAPI:
    """Builds the app. Tests pass their own settings, a clock they can move and, to replace the
    AI provider (so nothing reaches the network), a function from a patient to a provider.

    Raises ValueError in live mode without a monthly cap or an API key.
    """
    resolved = settings if settings is not None else Settings()  # pyright: ignore[reportCallIssue]
    the_clock: Clock = clock if clock is not None else SystemClock()
    configure_logging()
    # Fails here, before serving, when live mode has no cap or key.
    check_live_settings(resolved)

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
        worker = DraftWorker(
            app.state.notes,
            app.state.patients,
            app.state.usage,
            the_clock,
            provider_factory(resolved, app.state.usage, the_clock, provider_for),
        )
        queue = InProcessQueue(worker.run, app.state.notes)
        app.state.worker = worker
        app.state.queue = queue
        try:
            await queue.start(resolved.db_ping_timeout_s)
            yield
        finally:
            await queue.close()
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
