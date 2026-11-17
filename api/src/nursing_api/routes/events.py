import json
from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Request, Response

from nursing_api.problems import not_built
from nursing_api.worker import DraftWorker

log = structlog.get_logger("nursing_api.events")

# Registered only when APP_ROLE is worker (SQS records) or ops (migrate, seed-demo, smoke), and
# never in openapi.json: the Lambda Web Adapter posts each event here.
router = APIRouter(include_in_schema=False)


def _job_ids(payload: object) -> list[UUID]:
    """The job ids in an SQS batch. A record that isn't `{"job_id": <uuid>}` is logged (its class
    only, never its body) and left out: SQS must not deliver it again."""
    batch: Any = payload
    ids: list[UUID] = []
    try:
        records: list[Any] = list(batch["Records"])
    except (KeyError, TypeError, ValueError) as error:
        log.warning("queue batch dropped", error_class=type(error).__name__)
        return ids
    for record in records:
        try:
            ids.append(UUID(json.loads(record["body"])["job_id"]))
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            log.warning("queue record dropped", error_class=type(error).__name__)
    return ids


@router.post("/events")
async def handle_events(request: Request) -> Response:
    if request.app.state.settings.app_role != "worker":
        return not_built()  # the ops tasks arrive with the deploy lane's work
    try:
        payload: object = await request.json()
    except ValueError as error:
        log.warning("queue batch dropped", error_class=type(error).__name__)
        return Response(status_code=200)
    worker: DraftWorker = request.app.state.worker
    for job_id in _job_ids(payload):
        # `run` fails a job it can't finish. What escapes (the database still asleep after the
        # worker's attempts) answers 5xx, so SQS delivers the message again later.
        await worker.run(job_id)
    return Response(status_code=200)
