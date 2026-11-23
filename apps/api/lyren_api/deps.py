from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from fastapi import Depends, Header

from lyren_core.errors import AuthError, ConfigError
from lyren_core.identity import Principal, PrincipalStore, hash_key
from lyren_core.metering import UsageMeter
from lyren_core.settings import Settings
from lyren_inference.cache import CachingChatProvider, CassetteStore
from lyren_inference.ports import ChatProvider
from lyren_inference.providers.oci import OCIGenerativeAIProvider
from lyren_inference.registry import ModelRegistry


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


@lru_cache(maxsize=1)
def get_registry() -> ModelRegistry:
    return ModelRegistry()


@lru_cache(maxsize=1)
def get_usage_meter() -> UsageMeter:
    return UsageMeter(deployment_calls_per_day=get_settings().deployment_calls_per_day)


@lru_cache(maxsize=1)
def get_principal_store() -> PrincipalStore:
    settings = get_settings()
    if settings.principals_file is not None:
        return PrincipalStore.from_file(settings.principals_file)
    if not settings.api_key_hashes:
        raise ConfigError(
            "no authentication configured: set LYREN_PRINCIPALS_FILE, "
            "or LYREN_API_KEY_HASHES for local development only"
        )
    if not settings.is_local:
        raise ConfigError(
            "LYREN_API_KEY_HASHES is a single-principal development shortcut and is refused "
            f"in environment {settings.environment}; set LYREN_PRINCIPALS_FILE instead",
            detail="a shared deployment needs per-person attribution, quotas and revocation",
        )
    return PrincipalStore.single_dev_principal(settings.api_key_hashes)


@dataclass(frozen=True, slots=True)
class ProviderUnavailable:
    reason: str


@lru_cache(maxsize=1)
def get_chat_provider() -> ChatProvider | ProviderUnavailable:
    settings = get_settings()
    try:
        provider: ChatProvider = OCIGenerativeAIProvider(settings)
    except ConfigError as exc:
        return ProviderUnavailable(exc.message)
    store = CassetteStore(settings.cache_dir)
    return CachingChatProvider(provider, store, settings.cache_mode)


def require_principal(
    authorization: str | None = Header(default=None),
    store: PrincipalStore = Depends(get_principal_store),
) -> Principal:
    """Identifies who is calling. An unknown, revoked or disabled key is rejected identically."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthError("missing bearer token")

    principal = store.resolve(hash_key(authorization[7:]))
    if principal is None:
        raise AuthError("unknown or revoked api key")
    return principal
