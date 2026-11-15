"""The live provider, driven only through a mock transport: no network and no real key."""

import json
from collections.abc import Callable
from decimal import Decimal
from typing import Any, NoReturn

import anthropic
import httpx2
import pytest
from anthropic.resources.messages import AsyncMessages
from nursing_core.domain.errors import (
    AiBudgetReached,
    InvalidModelOutput,
    ModelRefused,
    ProviderUnavailable,
)
from nursing_core.domain.facility import Locale, NoteFormat
from nursing_core.domain.model_output import DraftRequest
from nursing_core.ports import LlmProvider
from nursing_core.prompts import load_prompt
from nursing_core.providers.anthropic import AnthropicProvider
from nursing_core.providers.pricing import cost_usd
from pydantic import SecretStr

KEY = "sk-ant-synthetic-test-key-0000"
MODEL = "claude-opus-5-5"

GOOD_JSON = json.dumps(
    {
        "entries": [
            {
                "focus": {"text": "Pain", "source_quotes": [], "own_wording": True},
                "data": [
                    {"text": "Pain 6/10", "source_quotes": ["pain 6/10"], "own_wording": False}
                ],
                "action": [],
                "response": [],
            }
        ]
    }
)

Responder = Callable[[httpx2.Request], httpx2.Response]


def _message(
    text: str | None = GOOD_JSON,
    stop_reason: str = "end_turn",
    usage: dict[str, Any] | None = None,
    model: str = MODEL,
) -> httpx2.Response:
    return httpx2.Response(
        200,
        json={
            "id": "msg_synthetic",
            "type": "message",
            "role": "assistant",
            "model": model,
            "content": [] if text is None else [{"type": "text", "text": text}],
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": usage
            or {
                "input_tokens": 10,
                "output_tokens": 5,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            },
        },
    )


def _error(
    status: int,
    kind: str,
    message: str,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> httpx2.Response:
    error: dict[str, Any] = {"type": kind, "message": message}
    if details is not None:
        error["details"] = details
    return httpx2.Response(status, json={"type": "error", "error": error}, headers=headers)


class _Server:
    """Answers each request with the next queued response (or the last one, repeated)."""

    def __init__(self, *responses: httpx2.Response | Exception) -> None:
        self.responses = list(responses)
        self.bodies: list[dict[str, Any]] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.bodies.append(json.loads(request.content))
        item = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(item, Exception):
            raise item
        return item


def _provider(server: _Server, delays: list[float] | None = None) -> AnthropicProvider:
    async def sleep(seconds: float) -> None:
        if delays is not None:
            delays.append(seconds)

    client = httpx2.AsyncClient(transport=httpx2.MockTransport(server))
    return AnthropicProvider(SecretStr(KEY), http_client=client, sleep=sleep)


def _request(text: str = "[PATIENT_1] has pain 6/10") -> DraftRequest:
    return DraftRequest(
        redacted_text=text,
        note_format=NoteFormat.FDAR,
        locale=Locale.EN_US,
        prompt_version="fdar-v1",
    )


def test_provider_satisfies_the_port_and_hides_its_key() -> None:
    provider: LlmProvider = AnthropicProvider(SecretStr(KEY))
    assert KEY not in repr(provider)
    assert KEY not in str(vars(provider).keys())


def test_unknown_model_fails_at_construction() -> None:
    with pytest.raises(ValueError, match="no price"):
        AnthropicProvider(SecretStr(KEY), model="claude-made-up")


@pytest.mark.asyncio
async def test_a_good_answer_becomes_a_provider_result() -> None:
    server = _Server(_message())
    result = await _provider(server).draft_fdar(_request())
    assert result.output.entries[0].focus.text == "Pain"
    assert result.output.entries[0].data[0].source_quotes == ["pain 6/10"]
    assert result.generation.provider == "anthropic"
    assert result.generation.prompt_version == "fdar-v1"
    assert len(server.bodies) == 1


@pytest.mark.asyncio
async def test_usage_and_cost_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    ticks = iter([100.0, 100.25])
    monkeypatch.setattr("nursing_core.providers.anthropic.perf_counter", lambda: next(ticks))
    usage = {
        "input_tokens": 1000,
        "output_tokens": 500,
        "cache_creation_input_tokens": 200,
        "cache_read_input_tokens": 300,
    }
    server = _Server(_message(usage=usage, model="claude-opus-5-5"))
    generation = (await _provider(server).draft_fdar(_request())).generation
    assert generation.model == "claude-opus-5-5"
    assert generation.input_tokens == 1500
    assert generation.output_tokens == 500
    assert generation.cost_usd == cost_usd(MODEL, 1000, 500, 200, 300)
    assert generation.cost_usd > Decimal(0)
    assert generation.latency_ms == 250


@pytest.mark.asyncio
async def test_missing_cache_counts_are_zero() -> None:
    usage = {"input_tokens": 40, "output_tokens": 7}
    result = await _provider(_Server(_message(usage=usage))).draft_fdar(_request())
    assert result.generation.input_tokens == 40
    assert result.generation.cost_usd == cost_usd(MODEL, 40, 7)


@pytest.mark.asyncio
async def test_request_carries_schema_effort_and_no_sampling_params() -> None:
    server = _Server(_message())
    await _provider(server).draft_fdar(_request("[PATIENT_1] has pain 6/10"))
    body = server.bodies[0]
    assert body["model"] == MODEL
    assert body["max_tokens"] == 16000
    assert body["system"] == load_prompt("fdar-v1")
    assert body["output_config"]["effort"] == "medium"
    schema_format = body["output_config"]["format"]
    assert schema_format["type"] == "json_schema"
    assert "entries" in schema_format["schema"]["properties"]
    for forbidden in ("thinking", "temperature", "top_p", "top_k", "fallbacks", "stream"):
        assert forbidden not in body
    (message,) = body["messages"]
    assert message["role"] == "user"
    assert message["content"] == (
        "Note format: fdar\nLocale: en-US\n\n<rough_note>\n[PATIENT_1] has pain 6/10\n</rough_note>"
    )


@pytest.mark.asyncio
async def test_two_patients_send_the_same_output_schema() -> None:
    server = _Server(_message())
    provider = _provider(server)
    await provider.draft_fdar(_request("[PATIENT_1] has pain 6/10"))
    await provider.draft_fdar(_request("[PATIENT_2] ate well, BP 120/80 mmHg"))
    first, second = (body["output_config"]["format"] for body in server.bodies)
    assert first == second
    assert "PATIENT" not in json.dumps(first)
    assert "pain" not in json.dumps(first)


@pytest.mark.asyncio
async def test_spend_limit_400_is_budget_reached_and_not_retried() -> None:
    server = _Server(
        _error(400, "invalid_request_error", "You have reached your specified API usage limits.")
    )
    with pytest.raises(AiBudgetReached):
        await _provider(server).draft_fdar(_request())
    assert len(server.bodies) == 1


@pytest.mark.asyncio
async def test_enforced_spend_limit_429_is_budget_reached_and_not_retried() -> None:
    server = _Server(
        _error(
            429,
            "rate_limit_error",
            "Spend limit reached",
            details={"error_code": "enforced_spend_limit_reached"},
        )
    )
    with pytest.raises(AiBudgetReached):
        await _provider(server).draft_fdar(_request())
    assert len(server.bodies) == 1


@pytest.mark.asyncio
async def test_other_429_is_retried_then_succeeds() -> None:
    server = _Server(_error(429, "rate_limit_error", "Slow down"), _message())
    delays: list[float] = []
    result = await _provider(server, delays).draft_fdar(_request())
    assert result.generation.provider == "anthropic"
    assert len(server.bodies) == 2
    assert len(delays) == 1
    assert 1.0 <= delays[0] <= 1.5


@pytest.mark.asyncio
async def test_retry_after_header_sets_the_wait_and_is_capped() -> None:
    delays: list[float] = []
    server = _Server(
        _error(429, "rate_limit_error", "Slow down", headers={"retry-after": "7"}),
        _error(429, "rate_limit_error", "Slow down", headers={"retry-after": "120"}),
        _message(),
    )
    await _provider(server, delays).draft_fdar(_request())
    assert delays == [7.0, 30.0]


@pytest.mark.asyncio
async def test_unreadable_retry_after_falls_back_to_the_backoff() -> None:
    delays: list[float] = []
    server = _Server(
        _error(429, "rate_limit_error", "Slow down", headers={"retry-after": "soon"}),
        _message(),
    )
    await _provider(server, delays).draft_fdar(_request())
    assert 1.0 <= delays[0] <= 1.5


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [500, 503, 529])
async def test_server_errors_retried_twice_then_unavailable(status: int) -> None:
    server = _Server(_error(status, "api_error", "Overloaded"))
    delays: list[float] = []
    with pytest.raises(ProviderUnavailable):
        await _provider(server, delays).draft_fdar(_request())
    assert len(server.bodies) == 3
    assert len(delays) == 2
    assert 1.0 <= delays[0] <= 1.5
    assert 2.0 <= delays[1] <= 2.5


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [httpx2.ConnectError("down"), httpx2.ReadTimeout("slow")])
async def test_connection_errors_and_timeouts_are_retried(failure: Exception) -> None:
    server = _Server(failure, _message())
    delays: list[float] = []
    result = await _provider(server, delays).draft_fdar(_request())
    assert result.generation.provider == "anthropic"
    assert len(server.bodies) == 2
    assert len(delays) == 1


@pytest.mark.asyncio
async def test_connection_errors_exhaust_into_unavailable() -> None:
    server = _Server(httpx2.ConnectError("down"))
    with pytest.raises(ProviderUnavailable):
        await _provider(server).draft_fdar(_request())
    assert len(server.bodies) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "kind", "message"),
    [
        (401, "authentication_error", "invalid x-api-key"),
        (403, "permission_error", "not allowed"),
        (404, "not_found_error", "model: nope"),
        (400, "invalid_request_error", "messages: bad shape"),
    ],
)
async def test_other_api_errors_are_unavailable_without_retry(
    status: int, kind: str, message: str
) -> None:
    server = _Server(_error(status, kind, message))
    with pytest.raises(ProviderUnavailable) as caught:
        await _provider(server).draft_fdar(_request())
    assert len(server.bodies) == 1
    assert KEY not in str(caught.value)
    assert message not in str(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("text", [None, "I can't help with that."])
async def test_refusal_is_model_refused(text: str | None) -> None:
    server = _Server(_message(text=text, stop_reason="refusal"))
    with pytest.raises(ModelRefused):
        await _provider(server).draft_fdar(_request())
    assert len(server.bodies) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "stop_reason"),
    [
        (GOOD_JSON, "max_tokens"),
        ('{"entries": [{"focus": {"text": "Pa', "max_tokens"),
        ("this is not json", "end_turn"),
        ('{"entries": 3}', "end_turn"),
        (None, "end_turn"),
    ],
)
async def test_max_tokens_or_invalid_json_is_invalid_output(
    text: str | None, stop_reason: str
) -> None:
    server = _Server(_message(text=text, stop_reason=stop_reason))
    with pytest.raises(InvalidModelOutput) as caught:
        await _provider(server).draft_fdar(_request())
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None or caught.value.__suppress_context__
    assert "this is not json" not in str(caught.value)


@pytest.mark.asyncio
async def test_a_thinking_block_before_the_answer_is_ignored() -> None:
    body = json.loads(_message().content)
    body["content"].insert(
        0, {"type": "thinking", "thinking": "Reading the note first.", "signature": "c3lu"}
    )
    server = _Server(httpx2.Response(200, json=body))
    result = await _provider(server).draft_fdar(_request())
    assert result.output.entries[0].data[0].text == "Pain 6/10"
    assert result.output.entries[0].data[0].source_quotes == ["pain 6/10"]


_LEAKY = "the note says [PATIENT_1] has pain"


def _unreadable_answer(request: httpx2.Request) -> anthropic.APIError:
    return anthropic.APIResponseValidationError(
        response=httpx2.Response(200, request=request), body={"text": _LEAKY}, message=_LEAKY
    )


def _plain_api_error(request: httpx2.Request) -> anthropic.APIError:
    return anthropic.APIError(_LEAKY, request, body={"text": _LEAKY})


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [_unreadable_answer, _plain_api_error])
async def test_any_other_sdk_error_is_unavailable_without_retry_or_its_text(
    monkeypatch: pytest.MonkeyPatch, error: Callable[[httpx2.Request], anthropic.APIError]
) -> None:
    calls: list[dict[str, object]] = []

    async def create(self: AsyncMessages, **kwargs: object) -> NoReturn:
        calls.append(kwargs)
        raise error(httpx2.Request("POST", "https://api.anthropic.com/v1/messages"))

    monkeypatch.setattr(AsyncMessages, "create", create)
    raised: BaseException | None = None
    try:
        await _provider(_Server(_message())).draft_fdar(_request())
    except Exception as caught:  # the test is that only ProviderUnavailable comes out
        raised = caught
    assert isinstance(raised, ProviderUnavailable)
    assert len(calls) == 1
    assert _LEAKY not in str(raised)
    assert raised.__cause__ is None
    assert raised.__suppress_context__


_UNREADABLE_BODIES = [
    "not json",
    "[]",
    '"text"',
    "null",
    "42",
    "{}",
    '{"content": 5, "stop_reason": "end_turn", "note": "SYNTHETIC-LEAK"}',
    '{"content": [5], "stop_reason": "end_turn", "note": "SYNTHETIC-LEAK"}',
    '{"content": [], "stop_reason": "end_turn", "model": "SYNTHETIC-LEAK"}',
]


@pytest.mark.asyncio
@pytest.mark.parametrize("body", _UNREADABLE_BODIES)
async def test_an_unreadable_200_answer_is_unavailable_without_retry_or_its_text(
    body: str,
) -> None:
    server = _Server(
        httpx2.Response(200, content=body, headers={"content-type": "application/json"})
    )
    raised: BaseException | None = None
    try:
        await _provider(server).draft_fdar(_request())
    except Exception as caught:  # the test is that only ProviderUnavailable comes out
        raised = caught
    assert type(raised) is ProviderUnavailable
    assert str(raised) == "the AI service call failed"
    assert len(server.bodies) == 1
    for shown in (str(raised), repr(raised)):
        assert body not in shown
        assert "SYNTHETIC-LEAK" not in shown
    assert raised.__cause__ is None
    assert raised.__context__ is None
    assert raised.__suppress_context__


@pytest.mark.asyncio
async def test_a_message_without_usage_is_unavailable() -> None:
    response = _message()
    body = json.loads(response.content)
    del body["usage"]
    server = _Server(httpx2.Response(200, json=body))
    with pytest.raises(ProviderUnavailable, match="the AI service call failed"):
        await _provider(server).draft_fdar(_request())
    assert len(server.bodies) == 1
