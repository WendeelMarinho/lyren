from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from lyren_api.deps import ProviderUnavailable, get_chat_provider, get_settings
from lyren_core.settings import Settings

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
def readyz(
    response: Response,
    settings: Settings = Depends(get_settings),
    provider: object = Depends(get_chat_provider),
) -> dict[str, object]:
    checks = {
        "api_keys_configured": bool(settings.api_key_hashes),
        "chat_provider": not isinstance(provider, ProviderUnavailable),
    }
    ready = all(checks.values())
    if not ready:
        response.status_code = 503
    payload: dict[str, object] = {"ready": ready, "checks": checks}
    if isinstance(provider, ProviderUnavailable):
        payload["chat_provider_reason"] = provider.reason
    return payload
