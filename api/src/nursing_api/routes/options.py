from fastapi import APIRouter, Request
from nursing_core.demo import DEMO_PIN

from nursing_api.schemas import SignInOptionsOut
from nursing_api.settings import Settings

router = APIRouter(prefix="/api/v1", tags=["session"])


@router.get("/sign-in-options", response_model=SignInOptionsOut)
async def sign_in_options(request: Request) -> SignInOptionsOut:
    """What the sign-in page offers: Google, the demo personas and their PIN. Reads no database."""
    settings: Settings = request.app.state.settings
    personas = settings.app_env != "prod"
    return SignInOptionsOut(
        google=settings.google_sign_in,
        personas=personas,
        demo=settings.app_env == "demo",
        demo_pin=DEMO_PIN if personas else None,
    )
