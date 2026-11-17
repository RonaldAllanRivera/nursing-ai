from fastapi import APIRouter, Response

from nursing_api.problems import not_built

# Registered only when APP_ENV=test, and never in openapi.json: the e2e harness's way to sign in a
# throwaway e2e-<uuid>@example.com Google user without Google.
router = APIRouter(prefix="/api/v1/test", include_in_schema=False)


@router.post("/session", status_code=201)
async def start_test_session() -> Response:
    return not_built()
