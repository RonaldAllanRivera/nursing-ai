"""The live provider: asks Claude for a structured FDAR draft.

The SDK's own retries are off. This provider retries the failures worth retrying, never retries
a spend limit, and never lets the key, the note or the model's words into an error message.
"""

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import perf_counter

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

_MAX_OUTPUT_TOKENS = 16000
_MAX_RETRIES = 2  # three attempts in all
_MAX_BACKOFF_SECONDS = 8
_MAX_RETRY_AFTER_SECONDS = 30
_JITTER_SECONDS = 0.5


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


def _read_message(response: anthropic.types.Message) -> _Message | None:
    """Read the answer's fields once, or None if it isn't a message. The SDK builds the answer
    without checking its shape, so a 200 that isn't a message fails here, and only here."""
    try:
        usage = response.usage
        return _Message(
            stop_reason=response.stop_reason,
            text="".join(block.text for block in response.content if block.type == "text"),
            model=response.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_creation=usage.cache_creation_input_tokens or 0,
            cache_read=usage.cache_read_input_tokens or 0,
        )
    except (AttributeError, TypeError):
        return None


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
        self._schema = anthropic.transform_schema(ModelFdarDraft)
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
        attempt = 0
        while True:
            wait: float | None = None
            unreadable = False
            try:
                response = await self._client.messages.create(
                    model=self.model,
                    max_tokens=_MAX_OUTPUT_TOKENS,
                    system=load_prompt(request.prompt_version),
                    messages=[{"role": "user", "content": _user_text(request)}],
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
            except anthropic.APIConnectionError:
                pass
            except ValueError:
                unreadable = True  # a 200 body that isn't JSON; never retried
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
        if message.stop_reason == "refusal":
            raise ModelRefused("the model declined this request")
        if message.stop_reason == "max_tokens":
            raise InvalidModelOutput("the model's answer was cut off")
        try:
            output = ModelFdarDraft.model_validate_json(message.text)
        except ValidationError:
            raise InvalidModelOutput("the model's answer did not match the draft schema") from None
        return ProviderResult(
            output=output,
            generation=GenerationInfo(
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
            ),
        )
