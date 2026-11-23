from __future__ import annotations

import time

from fastapi import APIRouter, Depends

from lyren_api.deps import get_registry, require_api_key
from lyren_inference.ports import Capability
from lyren_inference.registry import ModelRegistry

router = APIRouter(tags=["models"])

_CREATED = int(time.time())


@router.get("/v1/models")
def list_models(
    _: str = Depends(require_api_key),
    registry: ModelRegistry = Depends(get_registry),
) -> dict[str, object]:
    """OpenAI-shaped listing. Only callable models and aliases appear here."""
    entries = [
        {"id": spec.id, "object": "model", "created": _CREATED, "owned_by": spec.vendor}
        for spec in registry.callable_specs(capability=Capability.CHAT)
    ]
    entries += [
        {"id": policy.alias, "object": "model", "created": _CREATED, "owned_by": "lyren"}
        for policy in registry.aliases()
    ]
    return {"object": "list", "data": entries}


@router.get("/lyren/v1/models")
def list_models_native(
    _: str = Depends(require_api_key),
    registry: ModelRegistry = Depends(get_registry),
) -> dict[str, object]:
    """Native listing: the whole registry, including what is not callable and why."""
    return {
        "models": [
            {
                "id": spec.id,
                "vendor": spec.vendor,
                "provider": spec.provider,
                "api_format": str(spec.api_format),
                "pinned_version": spec.pinned_version,
                "capabilities": sorted(str(c) for c in spec.capabilities),
                "availability": str(spec.availability),
                "verified_at": spec.verified_at.isoformat() if spec.verified_at else None,
                "embedding_dimensions": spec.embedding_dimensions,
                "max_context_tokens": spec.max_context_tokens,
                "bills": spec.bills,
                "note": spec.note,
            }
            for spec in registry.specs()
        ],
        "aliases": [
            {
                "alias": policy.alias,
                "candidates": list(policy.candidates),
                "max_output_tokens": policy.max_output_tokens,
                "timeout_seconds": policy.timeout_seconds,
                "allow_paid": policy.allow_paid,
            }
            for policy in registry.aliases()
        ],
    }
