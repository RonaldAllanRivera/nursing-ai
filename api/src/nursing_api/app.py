import os
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

from nursing_api.auth import build_google
from nursing_api.auth.oidc import GoogleOidc
from nursing_api.aws.metrics import emit_ai_spend
from nursing_api.aws.ssm import load_ssm_settings
from nursing_api.health import router as health_router
from nursing_api.logging import RequestLogMiddleware, configure_logging
from nursing_api.problems import install_problems
from nursing_api.providers import ProviderFor, check_live_settings, provider_factory
from nursing_api.queue import build_queue
from nursing_api.routes import (
    auth,
    events,
    facility,
    jobs,
    notes,
    options,
    patients,
    rough_notes,
    session,
    test_session,
    users,
)
from nursing_api.settings import Settings
from nursing_api.worker import DraftWorker


def create_app(
    settings: Settings | None = None,
    *,
    clock: Clock | None = None,
    provider_for: ProviderFor | None = None,
    google: GoogleOidc | None = None,
) -> FastAPI:
    """Builds the app. Tests pass their own settings, a clock they can move, a function from a
    patient to an AI provider and a Google client (so nothing reaches the network).

    Without settings it reads them from the environment and SSM.

    Raises ValueError in live mode without a monthly cap or an API key.
    """
    if settings is None:
        # At cold start the secrets and the site address come from SSM, over the environment.
        from_ssm = {name.lower(): value for name, value in load_ssm_settings(os.environ).items()}
        settings = Settings(**from_ssm)  # pyright: ignore[reportCallIssue, reportArgumentType]
    resolved = settings
    the_clock: Clock = clock if clock is not None else SystemClock()
    configure_logging()
    # Fails here, before serving, when live mode has no cap or key.
    check_live_settings(resolved)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        engine = create_engine(
            resolved.database_url,
            null_pool=resolved.db_pool == "null",
            connect_timeout_s=resolved.db_connect_timeout_s,
        )
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
            emit_ai_spend if resolved.app_role == "worker" else None,
        )
        app.state.worker = worker
        queue = build_queue(resolved, worker.run, app.state.notes)
        app.state.queue = queue
        try:
            await queue.start(resolved.db_ping_timeout_s)
            yield
        finally:
            await queue.close()
            await engine.dispose()

    app = FastAPI(
        title="Nursing Documentation AI API",
        version="0.2.0",
        lifespan=lifespan,
        separate_input_output_schemas=False,
    )
    app.state.google = google if google is not None else build_google(resolved)
    app.include_router(health_router)
    for module in (options, auth, facility, session, users, patients, rough_notes, jobs, notes):
        app.include_router(module.router)
    # The e2e harness's sign-in exists only in tests; elsewhere it is a 404.
    if resolved.app_env == "test":
        app.include_router(test_session.router)
    # The worker's SQS records and the ops tasks arrive here; the API never has the route.
    if resolved.app_role in ("worker", "ops"):
        app.include_router(events.router)
    install_problems(app)
    app.add_middleware(RequestLogMiddleware)
    return app
