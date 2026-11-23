from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from lyren_api.deps import (
    ProviderUnavailable,
    get_chat_provider,
    get_principal_store,
    get_settings,
    get_usage_meter,
)
from lyren_core.errors import ConfigError
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
    auth_reason: str | None = None
    principal_count = 0
    try:
        principal_count = len(get_principal_store())
    except ConfigError as exc:
        auth_reason = exc.message

    checks = {
        "authentication": auth_reason is None,
        "chat_provider": not isinstance(provider, ProviderUnavailable),
    }
    ready = all(checks.values())
    if not ready:
        response.status_code = 503

    payload: dict[str, object] = {
        "ready": ready,
        "checks": checks,
        "principals": principal_count,
        "single_principal_dev_mode": settings.principals_file is None,
        "providers": sorted(provider.inner_providers())
        if hasattr(provider, "inner_providers")
        else [],
        "deployment_calls_today": get_usage_meter().deployment_usage().calls_today,
        "deployment_calls_per_day": settings.deployment_calls_per_day,
    }
    if auth_reason is not None:
        payload["authentication_reason"] = auth_reason
    if isinstance(provider, ProviderUnavailable):
        payload["chat_provider_reason"] = provider.reason
    return payload
