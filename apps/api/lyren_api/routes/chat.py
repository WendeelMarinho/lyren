from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from lyren_api.deps import (
    ProviderUnavailable,
    get_chat_provider,
    get_registry,
    get_usage_meter,
    require_principal,
)
from lyren_core.errors import ForbiddenError, ProviderError
from lyren_core.identity import Principal
from lyren_core.ids import current_request_id
from lyren_core.metering import UsageMeter
from lyren_inference.ports import (
    Availability,
    ChatProvider,
    ChatRequest,
    ChatResponse,
    Message,
    ModelSpec,
    Role,
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


@router.post("/v1/chat/completions")
def chat_completions(
    body: ChatCompletionIn,
    principal: Principal = Depends(require_principal),
    registry: ModelRegistry = Depends(get_registry),
    meter: UsageMeter = Depends(get_usage_meter),
    provider: ChatProvider | ProviderUnavailable = Depends(get_chat_provider),
) -> dict[str, object]:
    if body.stream:
        raise ProviderError(
            "streaming is not implemented yet; call with stream=false",
            detail="SSE lands with the Phase 2 inference gateway",
        )

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
