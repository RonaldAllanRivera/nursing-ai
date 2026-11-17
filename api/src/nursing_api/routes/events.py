from fastapi import APIRouter, Response

from nursing_api.problems import not_built

# Registered only when APP_ROLE is worker (SQS records) or ops (migrate, seed-demo, smoke), and
# never in openapi.json: the Lambda Web Adapter posts each event here.
router = APIRouter(include_in_schema=False)


@router.post("/events")
async def handle_events() -> Response:
    return not_built()
