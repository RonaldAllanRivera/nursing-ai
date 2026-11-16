"""The live provider: asks Claude for a structured FDAR draft.

The SDK's own retries are off. This provider retries only a call that was never billed (a
connection that failed, a 429 or a 5xx), never a timeout (the server may have finished and billed
an answer the client stopped waiting for) or a spend limit, and never lets the key, the note or
the model's words into an error message.
"""

import asyncio
import json
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Literal

import anthropic
import httpx2
from pydantic import SecretStr, ValidationError

from nursing_core.domain.errors import (
    AiBudgetReached,
    InvalidModelOutput,
    ModelRefused,
    ProviderUnavailable,
)
from nursing_core.domain.model_output import DraftRequest, ModelFdarDraft, ProviderResult
from nursing_core.domain.notes import GenerationInfo
from nursing_core.prompts import load_prompt
from nursing_core.providers.pricing import cost_usd

MAX_OUTPUT_TOKENS = 16000  # the ceiling on one answer; the budget guard reads it too
_MAX_RETRIES = 2  # three attempts in all
_MAX_BACKOFF_SECONDS = 8
_MAX_RETRY_AFTER_SECONDS = 30
_JITTER_SECONDS = 0.5


def output_schema() -> dict[str, Any]:
    """The JSON schema sent with every request, so its size can be counted before a call."""
    return anthropic.transform_schema(ModelFdarDraft)


def _is_spend_limit(error: anthropic.APIStatusError) -> bool:
    if isinstance(error, anthropic.EnforcedSpendLimitReachedError):
        return True
    return isinstance(error, anthropic.BadRequestError) and "api usage limits" in (
        error.message.lower()
    )


def _is_transient(error: anthropic.APIStatusError) -> bool:
    return error.status_code == 429 or error.status_code >= 500


def _retry_after(response: httpx2.Response) -> float | None:
    try:
        seconds = float(response.headers["retry-after"])
    except (KeyError, ValueError):
        return None
    return min(max(seconds, 0.0), _MAX_RETRY_AFTER_SECONDS)


def _backoff(attempt: int) -> float:
    jitter = random.uniform(0, _JITTER_SECONDS)  # noqa: S311 - spreads retries, not a secret
    return min(2**attempt, _MAX_BACKOFF_SECONDS) + jitter


def _user_text(request: DraftRequest) -> str:
    return (
        f"Note format: {request.note_format.value}\n"
        f"Locale: {request.locale.value}\n\n"
        f"<rough_note>\n{request.redacted_text}\n</rough_note>"
    )


@dataclass(frozen=True)
class _Message:
    """What the provider needs from an answer, as plain values."""

    stop_reason: str | None
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_creation: int
    cache_read: int


def _count(value: object, *, optional: bool = False) -> int | None:
    """A token count, or None if it isn't a whole number of zero or more (a missing optional count
    is 0)."""
    if value is None and optional:
        return 0
    return value if type(value) is int and value >= 0 else None


def _word(value: object) -> str | Literal[False] | None:
    """A string field as is, None if it is null, or False if it isn't a string at all."""
    if value is None or isinstance(value, str):
        return value
    return False


def _read_message(response: anthropic.types.Message) -> _Message | None:
    """Read the answer's fields once, or None if it isn't a message. The SDK builds the answer
    without checking its shape, so each field is read and type-checked here, and only here."""
    try:
        usage = response.usage
        stop_reason = _word(response.stop_reason)
        model = _word(response.model)
        text = "".join(block.text for block in response.content if block.type == "text")
        counts = (
            _count(usage.input_tokens),
            _count(usage.output_tokens),
            _count(usage.cache_creation_input_tokens, optional=True),
            _count(usage.cache_read_input_tokens, optional=True),
        )
    except (AttributeError, TypeError):
        return None
    input_tokens, output_tokens, cache_creation, cache_read = counts
    if (
        input_tokens is None
        or output_tokens is None
        or cache_creation is None
        or cache_read is None
        or not isinstance(model, str)
        or stop_reason is False
    ):
        return None
    return _Message(
        stop_reason=stop_reason,
        text=text,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation=cache_creation,
        cache_read=cache_read,
    )


class AnthropicProvider:
    def __init__(
        self,
        api_key: SecretStr,
        model: str = "claude-opus-5-5",
        http_client: httpx2.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        cost_usd(model, 0, 0)  # an unknown model fails here, not on the first note
        self.model = model
        self._sleep = sleep
        self._schema = output_schema()
        if http_client is None:
            self._client = anthropic.AsyncAnthropic(
                api_key=api_key.get_secret_value(), max_retries=0
            )
        else:
            self._client = anthropic.AsyncAnthropic(
                api_key=api_key.get_secret_value(), max_retries=0, http_client=http_client
            )

    async def draft_fdar(self, request: DraftRequest) -> ProviderResult:
        started = perf_counter()
        system = load_prompt(request.prompt_version)
        user_text = _user_text(request)
        attempt = 0
        while True:
            wait: float | None = None
            unreadable = False
            try:
                response = await self._client.messages.create(
                    model=self.model,
                    max_tokens=MAX_OUTPUT_TOKENS,
                    system=system,
                    messages=[{"role": "user", "content": user_text}],
                    output_config={
                        "effort": "medium",
                        "format": {"type": "json_schema", "schema": self._schema},
                    },
                )
            except anthropic.APIStatusError as error:
                if _is_spend_limit(error):
                    raise AiBudgetReached("the AI usage limit is reached") from None
                if not _is_transient(error):
                    raise ProviderUnavailable("the AI service rejected the request") from None
                wait = _retry_after(error.response)
            except anthropic.APITimeoutError:
                # The server may have finished, and billed, an answer the client stopped waiting
                # for: asking again could pay twice for a draft whose usage is recorded once.
                raise ProviderUnavailable("the AI service did not answer in time") from None
            except anthropic.APIConnectionError:
                pass  # never reached the server, so nothing was billed
            except (json.JSONDecodeError, UnicodeDecodeError):
                unreadable = True  # a 200 body that isn't JSON text; never retried
            except anthropic.APIError:
                # Anything else from the SDK, such as an answer it couldn't read; never retried.
                raise ProviderUnavailable("the AI service call failed") from None
            else:
                latency_ms = round((perf_counter() - started) * 1000)
                return self._result(request, response, latency_ms)
            if unreadable:
                raise ProviderUnavailable("the AI service call failed") from None
            if attempt >= _MAX_RETRIES:
                raise ProviderUnavailable("the AI service is unavailable")
            await self._sleep(_backoff(attempt) if wait is None else wait)
            attempt += 1

    def _result(
        self, request: DraftRequest, response: anthropic.types.Message, latency_ms: int
    ) -> ProviderResult:
        message = _read_message(response)
        if message is None:
            # Raised outside the except, so the unreadable answer isn't kept as the context.
            raise ProviderUnavailable("the AI service call failed") from None
        generation = GenerationInfo(
            provider="anthropic",
            model=message.model,
            prompt_version=request.prompt_version,
            input_tokens=message.input_tokens + message.cache_creation + message.cache_read,
            output_tokens=message.output_tokens,
            cost_usd=cost_usd(
                self.model,
                message.input_tokens,
                message.output_tokens,
                message.cache_creation,
                message.cache_read,
            ),
            latency_ms=latency_ms,
        )
        # From here the answer was billed, so each failure carries its cost.
        if message.stop_reason == "refusal":
            raise ModelRefused("the model declined this request", generation=generation)
        if message.stop_reason == "max_tokens":
            raise InvalidModelOutput("the model's answer was cut off", generation=generation)
        try:
            output = ModelFdarDraft.model_validate_json(message.text)
        except ValidationError:
            raise InvalidModelOutput(
                "the model's answer did not match the draft schema", generation=generation
            ) from None
        return ProviderResult(output=output, generation=generation)
