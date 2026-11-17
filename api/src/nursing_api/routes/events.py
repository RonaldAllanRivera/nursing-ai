import json
from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from nursing_api.ops import TASKS, Ops
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


async def _ops_answer(request: Request) -> Response:
    """Run the ops task in the body: 200 when it worked, 500 when it didn't, 400 for any other."""
    try:
        body: Any = await request.json()
        task = body["task"]
    except (ValueError, KeyError, TypeError):
        task = None
    if not isinstance(task, str) or task not in TASKS:
        log.warning("ops task unknown")
        return JSONResponse({"task": "unknown", "ok": False, "failed": []}, status_code=400)
    ops: Ops = request.app.state.ops
    result = await ops.run(task)
    status = 400 if result.refused else 200 if result.ok else 500
    return JSONResponse(
        {"task": result.task, "ok": result.ok, "failed": result.failed}, status_code=status
    )


async def _worker_answer(request: Request) -> Response:
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


@router.post("/events")
async def handle_events(request: Request) -> Response:
    # Each role is routed by name; any other answers 501 and runs nothing.
    match request.app.state.settings.app_role:
        case "ops":
            return await _ops_answer(request)
        case "worker":
            return await _worker_answer(request)
        case _:
            return not_built()
