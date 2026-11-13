from fastapi import APIRouter

from nursing_api.problems import problems
from nursing_api.routes import not_built
from nursing_api.schemas import PersonaOut, SessionIn, SessionOut, ShiftChoiceIn

router = APIRouter(prefix="/api/v1", tags=["session"])


@router.get("/personas", response_model=list[PersonaOut])
async def list_personas() -> list[PersonaOut]:
    """The demo people a visitor can sign in as, each with their role."""
    not_built()


@router.post("/session", status_code=201, response_model=SessionOut, responses=problems(404, 422))
async def start_session(body: SessionIn) -> SessionOut:
    """Signs in as a demo persona and sets the session cookie."""
    not_built()


@router.get("/session", response_model=SessionOut, responses=problems(401))
async def get_session() -> SessionOut:
    not_built()


@router.delete("/session", status_code=204)
async def end_session() -> None:
    not_built()


@router.put("/session/shift", response_model=SessionOut, responses=problems(401, 403, 422))
async def change_shift(body: ShiftChoiceIn) -> SessionOut:
    """A nurse switches her session to the previous, current or next shift."""
    not_built()
