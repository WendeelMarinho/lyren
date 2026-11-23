from __future__ import annotations

import json
import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from lyren_api.deps import (
    ProviderUnavailable,
    get_chat_provider,
    get_registry,
    get_usage_meter,
    require_principal,
)
from lyren_core.errors import ForbiddenError, LyrenError, ProviderError
from lyren_core.identity import Principal
from lyren_core.ids import current_request_id
from lyren_core.metering import UsageMeter
from lyren_inference.ports import (
    Availability,
    ChatChunk,
    ChatProvider,
    ChatRequest,
    ChatResponse,
    Message,
    ModelSpec,
    Role,
    StreamingChatProvider,
)
from lyren_inference.registry import ModelRegistry

router = APIRouter(tags=["chat"])

_RETRYABLE_AVAILABILITY = {
    "model_not_available": Availability.NOT_FOUND,
    "model_disabled_by_quota": Availability.QUOTA_ZERO,
}


class ChatMessageIn(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatCompletionIn(BaseModel):
    model: str
    messages: Annotated[list[ChatMessageIn], Field(min_length=1)]
    max_tokens: int | None = Field(default=None, ge=1, le=32_000)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    stop: list[str] | None = None
    stream: bool = False


# response_model=None: the handler returns either a JSON body or a StreamingResponse, and
# FastAPI cannot derive one schema from both.
@router.post("/v1/chat/completions", response_model=None)
def chat_completions(
    body: ChatCompletionIn,
    principal: Principal = Depends(require_principal),
    registry: ModelRegistry = Depends(get_registry),
    meter: UsageMeter = Depends(get_usage_meter),
    provider: ChatProvider | ProviderUnavailable = Depends(get_chat_provider),
) -> Response | dict[str, object]:
    if not principal.may_use(body.model):
        raise ForbiddenError(f"{principal.id} is not permitted to use {body.model}")

    meter.check(principal)

    if isinstance(provider, ProviderUnavailable):
        raise ProviderError("no chat provider is configured", detail=provider.reason)

    alias = registry.alias(body.model)
    candidates = registry.resolve(body.model)
    budget = min(
        alias.max_output_tokens if alias else principal.quota.max_output_tokens,
        principal.quota.max_output_tokens,
    )
    request = ChatRequest(
        messages=tuple(Message(role=Role(m.role), content=m.content) for m in body.messages),
        max_output_tokens=min(body.max_tokens or budget, budget),
        temperature=body.temperature,
        stop=tuple(body.stop or ()),
    )

    if body.stream:
        if not isinstance(provider, StreamingChatProvider):
            raise ProviderError(f"{provider.name} does not support streaming")
        completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
        return StreamingResponse(
            _sse(provider, registry, meter, principal, candidates, request, completion_id),
            media_type="text/event-stream",
            headers={"cache-control": "no-store", "x-accel-buffering": "no"},
        )

    response = _call_with_fallback(provider, registry, candidates, request)
    if not response.from_cache:
        meter.record(
            principal,
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
        )

    payload: dict[str, object] = {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": response.model_id,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": response.text},
                "finish_reason": response.finish_reason,
            }
        ],
        "lyren": {
            "request_id": current_request_id(),
            "from_cache": response.from_cache,
            "principal": principal.id,
        },
    }
    if response.usage.total_tokens is not None:
        payload["usage"] = {
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
        }
    return payload


def _sse(
    provider: StreamingChatProvider,
    registry: ModelRegistry,
    meter: UsageMeter,
    principal: Principal,
    candidates: tuple[ModelSpec, ...],
    request: ChatRequest,
    completion_id: str,
) -> Iterator[str]:
    """Emits an OpenAI-shaped SSE stream.

    Two properties are deliberate. **Usage is recorded in `finally`**, so a client that disconnects
    part-way still spends its quota — the tokens were generated regardless, and not counting them
    would make cancellation a way around the limit. OCI reports no token counts on a stream, so the
    call is counted and the tokens are left unknown rather than reported as zero.

    **A failure after the first byte cannot become an HTTP status**, because the headers are long
    gone. It is emitted as an error frame inside the stream instead, which is the only honest option
    once the response has started.
    """
    created = int(time.time())
    model_id = candidates[0].id
    prompt_tokens: int | None = None
    completion_tokens: int | None = None

    try:
        yield _frame(completion_id, created, model_id, {"role": "assistant"})
        for spec, chunk in _stream_with_fallback(provider, registry, candidates, request):
            model_id = spec.id
            if chunk.usage is not None:
                prompt_tokens = chunk.usage.prompt_tokens or prompt_tokens
                completion_tokens = chunk.usage.completion_tokens or completion_tokens
            if chunk.text:
                yield _frame(completion_id, created, model_id, {"content": chunk.text})
            if chunk.finish_reason is not None:
                yield _frame(
                    completion_id, created, model_id, {}, finish_reason=chunk.finish_reason
                )
        yield "data: [DONE]\n\n"
    except LyrenError as exc:
        yield (
            "data: "
            + json.dumps(
                {
                    "error": {
                        "message": exc.message,
                        "type": exc.code,
                        "code": exc.code,
                        "request_id": current_request_id(),
                    }
                }
            )
            + "\n\n"
        )
        yield "data: [DONE]\n\n"
    finally:
        meter.record(principal, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)


def _frame(
    completion_id: str,
    created: int,
    model_id: str,
    delta: dict[str, str],
    *,
    finish_reason: str | None = None,
) -> str:
    body = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model_id,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    return f"data: {json.dumps(body, ensure_ascii=False)}\n\n"


def _stream_with_fallback(
    provider: StreamingChatProvider,
    registry: ModelRegistry,
    candidates: tuple[ModelSpec, ...],
    request: ChatRequest,
) -> Iterator[tuple[ModelSpec, ChatChunk]]:
    """Falls back only before the first chunk.

    Once a byte has reached the client the model is committed: switching mid-answer would splice two
    different completions into one reply, which is worse than failing.
    """
    last: ProviderError | None = None
    for spec in candidates:
        emitted = False
        try:
            for chunk in provider.stream_chat(spec, request):
                emitted = True
                yield spec, chunk
            return
        except ProviderError as exc:
            if emitted:
                raise
            verdict = _RETRYABLE_AVAILABILITY.get(exc.code)
            if verdict is None:
                raise
            registry.apply_probe(spec.id, verdict, when=datetime.now(UTC).date())
            last = exc
    raise last if last is not None else ProviderError("no candidate model could be reached")


def _call_with_fallback(
    provider: ChatProvider,
    registry: ModelRegistry,
    candidates: tuple[ModelSpec, ...],
    request: ChatRequest,
) -> ChatResponse:
    """Walk the alias candidates, recording availability verdicts so drift is observed."""
    last: ProviderError | None = None
    for spec in candidates:
        try:
            return provider.chat(spec, request)
        except ProviderError as exc:
            verdict = _RETRYABLE_AVAILABILITY.get(exc.code)
            if verdict is None:
                raise
            registry.apply_probe(spec.id, verdict, when=datetime.now(UTC).date())
            last = exc
    raise last if last is not None else ProviderError("no candidate model could be reached")
