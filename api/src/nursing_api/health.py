from typing import Literal

from fastapi import APIRouter, Request, Response
from nursing_core.db import ping
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncEngine

from nursing_api.settings import Settings

router = APIRouter()


class HealthResponse(BaseModel):
    status: Literal["healthy", "unhealthy"]
    database: Literal["ok", "unreachable", "not_checked"]


@router.get(
    "/api/v1/health",
    response_model=HealthResponse,
    responses={503: {"model": HealthResponse}},
)
async def health(request: Request, response: Response) -> HealthResponse:
    """Live (demo and prod) it never opens a connection: a crawler polling it would otherwise keep
    a paused database awake. The ops function's `smoke` task checks the database there instead."""
    settings: Settings = request.app.state.settings
    if settings.app_env in ("demo", "prod"):
        return HealthResponse(status="healthy", database="not_checked")
    engine: AsyncEngine = request.app.state.engine
    if await ping(engine, settings.db_ping_timeout_s):
        return HealthResponse(status="healthy", database="ok")
    response.status_code = 503
    return HealthResponse(status="unhealthy", database="unreachable")
