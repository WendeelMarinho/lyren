from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from lyren_api.deps import (
    get_id_token_verifier,
    get_principal_store,
    get_settings,
    get_token_issuer,
    get_usage_meter,
    require_principal,
)
from lyren_core.errors import AuthError, ConfigError
from lyren_core.federation import IdTokenVerifier, SessionTokenIssuer
from lyren_core.identity import Principal, PrincipalStore
from lyren_core.ids import current_request_id
from lyren_core.metering import UsageMeter
from lyren_core.settings import Settings

router = APIRouter(tags=["auth"])


class GoogleSignIn(BaseModel):
    id_token: str = Field(min_length=16, max_length=8192)


@router.post("/lyren/v1/auth/google")
def sign_in_with_google(
    body: GoogleSignIn,
    verifier: IdTokenVerifier = Depends(get_id_token_verifier),
    issuer: SessionTokenIssuer = Depends(get_token_issuer),
    store: PrincipalStore = Depends(get_principal_store),
) -> dict[str, object]:
    """Exchanges a verified Google identity for a principal-bound session token.

    Native namespace on purpose: this is not an OpenAI endpoint and does not pretend to be.

    A Google account that no principal claims is refused. Signing in does not create access, it
    proves identity — permission is something a principal already had to be granted.
    """
    identity = verifier.verify(body.id_token)

    principal = store.resolve_email(identity.email)
    if principal is None:
        raise AuthError(
            "this Google account is not registered with Lyren",
            detail="an administrator must add the address to a principal",
        )

    return {
        "access_token": issuer.issue(principal),
        "token_type": "Bearer",
        "expires_in": issuer.ttl_seconds,
        "principal": {"id": principal.id, "name": principal.name},
        "request_id": current_request_id(),
    }


@router.get("/lyren/v1/me")
def who_am_i(
    principal: Principal = Depends(require_principal),
    meter: UsageMeter = Depends(get_usage_meter),
) -> dict[str, object]:
    """What the caller is, and what they have spent today. The UI needs both."""
    usage = meter.usage_for(principal.id)
    return {
        "id": principal.id,
        "name": principal.name,
        "quota": {
            "requests_per_minute": principal.quota.requests_per_minute,
            "calls_per_day": principal.quota.calls_per_day,
            "max_output_tokens": principal.quota.max_output_tokens,
        },
        "usage_today": {
            "calls": usage.calls_today,
            "prompt_tokens": usage.prompt_tokens_today,
            "completion_tokens": usage.completion_tokens_today,
        },
        "allowed_models": sorted(principal.allowed_models) if principal.allowed_models else None,
    }


@router.get("/lyren/v1/auth/config")
def sign_in_config(settings: Settings = Depends(get_settings)) -> dict[str, object]:
    """What a browser needs to start sign-in. No secret is involved — a client id is public."""
    if not settings.google_sign_in_configured:
        raise ConfigError("Google sign-in is not configured on this deployment")
    return {
        "provider": "google",
        "client_id": settings.google_client_id,
        "allowed_domains": list(settings.google_allowed_domains),
    }
