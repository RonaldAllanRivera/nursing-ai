"""Privacy-safe logging: one JSON line per event, only allowlisted keys, one id per request.

A log line may name an event, a route template, a status, an id or an error class. It never holds
note text, a name, a request body or an exception's message, so anything not on the allowlist is
dropped before it is written, whichever logger it came from (structlog, or stdlib such as
`nursing_core.db`). Event names are constant strings; data goes in a key, never in the name.
"""

import logging
import sys
import time
import uuid
from typing import Any

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from structlog.types import EventDict, Processor

ALLOWED_KEYS = frozenset(
    {
        "event",
        "level",
        "timestamp",
        "request_id",
        "method",
        "route",
        "status",
        "duration_ms",
        "job_id",
        "note_id",
        "error_class",
        "ai_mode",
    }
)
# The Anthropic SDK logs whole requests at DEBUG, and SQLAlchemy logs statement parameters.
QUIET_LOGGERS = ("anthropic", "httpx", "httpx2", "httpcore", "sqlalchemy.engine")
_HANDLER_NAME = "nursing_api.json"
UNMATCHED = "unmatched"


# What structlog's formatter itself adds to a stdlib record and removes again before rendering.
_FORMATTER_META = frozenset({"_record", "_from_structlog"})


def _only_allowed(_logger: object, _method: str, event: EventDict) -> EventDict:
    return {key: value for key, value in event.items() if key in ALLOWED_KEYS | _FORMATTER_META}


LIBRARY_EVENT = "library log"
_PROJECT_LOGGERS = ("nursing_api", "nursing_core")
_SERVER_LOGGERS = ("uvicorn", "uvicorn.error")
# The only uvicorn lines shown as they are (copied from uvicorn's source). Any other uvicorn
# message could be pre-formatted with data, so it becomes the constant.
UVICORN_TEMPLATES = frozenset(
    {
        "Started server process [%d]",
        "Waiting for application startup.",
        "Application startup complete.",
        "Uvicorn running on %s://%s:%d (Press CTRL+C to quit)",
        "Uvicorn running on %s://[%s]:%d (Press CTRL+C to quit)",
        "Shutting down",
        "Waiting for application shutdown.",
        "Application shutdown complete.",
        "Finished server process [%d]",
    }
)
API_PREFIX = "/api/v1/"
HEALTH_PATH = "/api/v1/health"


def _foreign_event(_logger: object, _method: str, event: EventDict) -> EventDict:
    """Makes a stdlib record safe: no data in the event text, no traceback, only the class.

    A project logger's event is its message template (never filled with arguments), and so is
    uvicorn's own start-up and shutdown lines (only the known templates). Any other library's
    message may quote data (asyncio prints the exception it never retrieved), so it becomes a
    constant. A message that is not text (an exception object) is a constant too.
    """
    record = event.get("_record")
    if not isinstance(record, logging.LogRecord):
        return event
    project = record.name.split(".")[0] in _PROJECT_LOGGERS
    message = record.msg
    known = (
        isinstance(message, str)  # an unhashable message must not reach the set lookup
        and record.name in _SERVER_LOGGERS
        and not record.exc_info
        and message in UVICORN_TEMPLATES
    )
    shown = (project or known) and isinstance(message, str)
    event["event"] = message if shown else LIBRARY_EVENT
    # `exc_info` may be False, None or (None, None, None): all mean "no exception".
    error_type = record.exc_info[0] if record.exc_info else None
    if error_type is not None:
        event["error_class"] = error_type.__name__
    return event


class _StdoutHandler(logging.Handler):
    """Writes to whatever `sys.stdout` is when a line is written (so test capture sees it)."""

    def __init__(self) -> None:
        super().__init__()
        self.set_name(_HANDLER_NAME)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            sys.stdout.write(self.format(record) + "\n")
            sys.stdout.flush()
        except Exception:
            self.handleError(record)


def configure_logging() -> None:
    """Send structlog and stdlib logs through the allowlist as JSON on stdout. Safe to repeat.

    Also turns off `logging.raiseExceptions` (process-wide): when a handler fails,
    `Handler.handleError` would otherwise print the record's message and arguments to stderr.
    """
    logging.raiseExceptions = False
    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
    structlog.configure(
        processors=[*shared, _only_allowed, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )
    handler = _StdoutHandler()
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=[
                *shared,
                structlog.stdlib.ExtraAdder(),
                _foreign_event,
                _only_allowed,
            ],
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.JSONRenderer(),
            ],
        )
    )
    root = logging.getLogger()
    for old in [h for h in root.handlers if h.get_name() == _HANDLER_NAME]:
        root.removeHandler(old)
    root.addHandler(handler)
    root.setLevel(min(root.level, logging.INFO))
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    # uvicorn sets its own handlers before it calls the app factory; its "Exception in ASGI
    # application" record carries a traceback, so it must come through the root handler instead.
    for name in ("uvicorn", "uvicorn.error"):
        server = logging.getLogger(name)
        server.handlers.clear()
        server.propagate = True
    # Our own middleware logs each request; uvicorn's access line would carry the raw path.
    access = logging.getLogger("uvicorn.access")
    access.handlers.clear()
    access.propagate = False


class RequestLogMiddleware:
    """Gives each request a fresh id, returns it as X-Request-ID and logs one `request` event."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.log = structlog.get_logger("nursing_api.request")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = uuid.uuid4().hex
        path = str(scope.get("path", ""))
        status = 500
        failure: str | None = None

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message["headers"] = [
                    *message.get("headers", []),
                    (b"x-request-id", request_id.encode()),
                ]
                if path.startswith(API_PREFIX) and path != HEALTH_PATH:
                    # A shared ward PC's browser must not keep notes or drafts after sign-out.
                    message["headers"].append((b"cache-control", b"no-store"))
            await send(message)

        started = time.perf_counter()
        with structlog.contextvars.bound_contextvars(request_id=request_id):
            try:
                await self.app(scope, receive, send_with_id)
            except Exception as error:
                failure = type(error).__name__
                raise
            finally:
                route = scope.get("route")
                template = getattr(route, "path", None)
                details: dict[str, Any] = {
                    "method": scope["method"],
                    "route": template if isinstance(template, str) else UNMATCHED,
                    "status": status,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                }
                if failure is not None:
                    details["error_class"] = failure
                self.log.info("request", **details)
