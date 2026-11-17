from fastapi import APIRouter, Response
from fastapi.responses import RedirectResponse

from nursing_api.problems import not_built, problems
from nursing_api.routes import location_header

router = APIRouter(prefix="/api/v1/auth/google", tags=["session"])


@router.get(
    "/start",
    status_code=302,
    response_class=RedirectResponse,
    responses={302: {"headers": location_header("Google's account chooser")}, **problems(404)},
)
async def google_start() -> Response:
    """Sends the browser to Google (404 when Google sign-in is off). Reads no database."""
    return not_built()


# Google's answer arrives as query parameters (code, state, or error), read from the request:
# declared ones would add a 422 that no browser can act on. Every refusal redirects instead.
@router.get(
    "/callback",
    status_code=302,
    response_class=RedirectResponse,
    responses={
        302: {
            "description": (
                "To the app, or to /sign-in?error=no_access, /sign-in?error=expired or "
                "/sign-in?error=cancelled (SignInError in schemas.py)"
            ),
            "headers": location_header("The app, or the sign-in page with ?error="),
        }
    },
)
async def google_callback() -> Response:
    """Google's redirect back: an invited person gets a session; anyone else, a reason."""
    return not_built()
