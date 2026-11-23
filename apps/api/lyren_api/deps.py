from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from functools import lru_cache

from fastapi import Depends, Header

from lyren_core.errors import AuthError, ConfigError
from lyren_core.identity import Principal, PrincipalStore, hash_key
from lyren_core.metering import UsageMeter
from lyren_core.settings import Settings
from lyren_inference.cache import CachingChatProvider, CassetteStore
from lyren_inference.ports import Availability, ChatProvider
from lyren_inference.providers.local_llama import LocalLlamaProvider
from lyren_inference.providers.oci import OCIGenerativeAIProvider
from lyren_inference.registry import PROVIDER_LOCAL, ModelRegistry
from lyren_inference.router import ProviderRouter


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


LOCAL_MODEL_ID = "local/llama-cpp"


@lru_cache(maxsize=1)
def get_chat_provider() -> ChatProvider | ProviderUnavailable:
    """Builds the router over whichever providers are configured.

    The local provider is probed here rather than trusted: a llama.cpp server that is down or
    holding no model must not be routed to, and the registry records the verdict so the alias
    candidate list skips it. The cache sits outermost, so a hit never reaches dispatch.
    """
    settings = get_settings()
    providers: dict[str, ChatProvider] = {}
    reasons: list[str] = []

    try:
        providers[OCIGenerativeAIProvider.name] = OCIGenerativeAIProvider(settings)
    except ConfigError as exc:
        reasons.append(exc.message)

    if settings.local_enabled:
        local = LocalLlamaProvider(
            settings.local_base_url, timeout_seconds=settings.request_timeout_seconds
        )
        verdict = local.probe()
        get_registry().apply_probe(LOCAL_MODEL_ID, verdict, when=date.today())
        if verdict is Availability.VERIFIED:
            providers[PROVIDER_LOCAL] = local
        else:
            reasons.append(f"no llama.cpp server answered at {settings.local_base_url}")
    else:
        reasons.append("the local provider is disabled (LYREN_LOCAL_ENABLED)")

    if not providers:
        return ProviderUnavailable("; ".join(reasons))

    router = ProviderRouter(providers)
    return CachingChatProvider(router, CassetteStore(settings.cache_dir), settings.cache_mode)


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
