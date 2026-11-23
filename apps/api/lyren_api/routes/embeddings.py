from __future__ import annotations

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
from lyren_inference.ports import Capability, EmbeddingProvider, EmbedInputType, EmbedRequest
from lyren_inference.registry import ModelRegistry

router = APIRouter(tags=["embeddings"])

MAX_INPUTS = 96
"""A conservative client-side bound, not a claim about the provider's documented batch limit."""


class EmbeddingsIn(BaseModel):
    model: str
    input: str | Annotated[list[str], Field(min_length=1, max_length=MAX_INPUTS)]
    input_type: EmbedInputType = EmbedInputType.SEARCH_DOCUMENT
    """Required by retrieval correctness: a document indexed as a query degrades recall silently."""
    encoding_format: Literal["float"] = "float"

    def texts(self) -> tuple[str, ...]:
        return (self.input,) if isinstance(self.input, str) else tuple(self.input)


@router.post("/v1/embeddings")
def create_embeddings(
    body: EmbeddingsIn,
    principal: Principal = Depends(require_principal),
    registry: ModelRegistry = Depends(get_registry),
    meter: UsageMeter = Depends(get_usage_meter),
    provider: object = Depends(get_chat_provider),
) -> dict[str, object]:
    if not principal.may_use(body.model):
        raise ForbiddenError(f"{principal.id} is not permitted to use {body.model}")

    meter.check(principal)

    if isinstance(provider, ProviderUnavailable):
        raise ProviderError("no provider is configured", detail=provider.reason)
    if not isinstance(provider, EmbeddingProvider):
        raise ProviderError("the configured provider does not serve embeddings")

    spec = registry.resolve(body.model)[0]
    if Capability.TEXT_EMBEDDINGS not in spec.capabilities:
        raise ProviderError(
            f"{spec.id} is not an embedding model",
            detail="use /v1/chat/completions for chat models",
        )

    texts = body.texts()
    if any(not text.strip() for text in texts):
        raise ProviderError("an empty input cannot be embedded")

    response = provider.embed(spec, EmbedRequest(inputs=texts, input_type=body.input_type))
    meter.record(principal, prompt_tokens=response.usage.prompt_tokens)

    payload: dict[str, object] = {
        "object": "list",
        "data": [
            {"object": "embedding", "index": index, "embedding": list(vector)}
            for index, vector in enumerate(response.vectors)
        ],
        "model": response.model_id,
        "lyren": {
            "request_id": current_request_id(),
            "principal": principal.id,
            "dimensions": response.dimensions,
            "input_type": str(body.input_type),
        },
    }
    if response.usage.prompt_tokens is not None:
        payload["usage"] = {
            "prompt_tokens": response.usage.prompt_tokens,
            "total_tokens": response.usage.prompt_tokens,
        }
    return payload
