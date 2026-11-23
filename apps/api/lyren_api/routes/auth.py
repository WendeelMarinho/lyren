from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr, Field

from lyren_api.deps import (
    get_credential_store,
    get_id_token_verifier,
    get_login_throttle,
    get_principal_store,
    get_settings,
    get_token_issuer,
    get_usage_meter,
    require_principal,
)
from lyren_core.credentials import CredentialStore, LoginThrottle, validate_password
from lyren_core.errors import AuthError, ConfigError
from lyren_core.federation import IdTokenVerifier, SessionTokenIssuer
from lyren_core.identity import Principal, PrincipalStore, hash_key
from lyren_core.ids import current_request_id
from lyren_core.metering import UsageMeter
from lyren_core.settings import Settings

router = APIRouter(tags=["auth"])


def _session(issuer: SessionTokenIssuer, principal: Principal) -> dict[str, object]:
    return {
        "access_token": issuer.issue(principal),
        "token_type": "Bearer",
        "expires_in": issuer.ttl_seconds,
        "principal": {"id": principal.id, "name": principal.name},
        "request_id": current_request_id(),
    }


class Registration(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=2048)
    registration_token: str | None = Field(default=None, max_length=512)


class PasswordSignIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=2048)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=2048)
    new_password: str = Field(min_length=1, max_length=2048)


@router.post("/lyren/v1/auth/register")
def register(
    body: Registration,
    store: PrincipalStore = Depends(get_principal_store),
    credentials: CredentialStore = Depends(get_credential_store),
    issuer: SessionTokenIssuer = Depends(get_token_issuer),
    throttle: LoginThrottle = Depends(get_login_throttle),
) -> dict[str, object]:
    """Sets the first password for an address a principal already claims.

    Refusals are deliberately indistinguishable. An address nobody claims, an address that already
    has a password, and a wrong registration token all answer the same way, so this endpoint cannot
    be used to discover which addresses exist on the deployment.
    """
    email = str(body.email).strip().lower()
    throttle.check(email)

    principal = store.resolve_email(email)
    refused = (
        principal is None
        or credentials.has_password(principal.id)
        or not _registration_token_ok(principal, body.registration_token)
    )
    if refused or principal is None:
        throttle.record_failure(email)
        raise AuthError(
            "this address cannot be registered",
            detail="it is not registered with Lyren, already has a password, or the token is wrong",
        )

    validate_password(body.password, email=email)
    credentials.set_password(principal.id, body.password)
    throttle.clear(email)
    return _session(issuer, principal)


def _registration_token_ok(principal: Principal, presented: str | None) -> bool:
    if principal.registration_token_hash is None:
        return True
    if not presented:
        return False
    return hmac.compare_digest(hash_key(presented), principal.registration_token_hash)


@router.post("/lyren/v1/auth/login")
def sign_in_with_password(
    body: PasswordSignIn,
    store: PrincipalStore = Depends(get_principal_store),
    credentials: CredentialStore = Depends(get_credential_store),
    issuer: SessionTokenIssuer = Depends(get_token_issuer),
    throttle: LoginThrottle = Depends(get_login_throttle),
) -> dict[str, object]:
    """Exchanges an address and password for a principal-bound session token.

    A missing account and a wrong password answer identically and cost the same: the store hashes a
    dummy when there is no record, so timing does not distinguish them either.
    """
    email = str(body.email).strip().lower()
    throttle.check(email)

    principal = store.resolve_email(email)
    if not credentials.verify(principal.id if principal else None, body.password):
        throttle.record_failure(email)
        raise AuthError("the address or password is wrong")
    if principal is None:
        throttle.record_failure(email)
        raise AuthError("the address or password is wrong")

    throttle.clear(email)
    return _session(issuer, principal)


@router.post("/lyren/v1/auth/password")
def change_password(
    body: PasswordChange,
    principal: Principal = Depends(require_principal),
    credentials: CredentialStore = Depends(get_credential_store),
) -> dict[str, object]:
    """Changes the caller's own password. The current one is required."""
    if not credentials.verify(principal.id, body.current_password):
        raise AuthError("the current password is wrong")

    email = next(iter(sorted(principal.emails)), "")
    validate_password(body.new_password, email=email)
    credentials.set_password(principal.id, body.new_password)
    return {"changed": True, "principal": principal.id, "request_id": current_request_id()}


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

    return _session(issuer, principal)


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
