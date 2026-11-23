from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from functools import lru_cache

from fastapi import Depends, Header

from lyren_core.errors import AuthError, ConfigError
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


def require_api_key(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> str:
    if not settings.api_key_hashes:
        raise ConfigError("LYREN_API_KEY_HASHES is empty; the API refuses to run unauthenticated")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthError("missing bearer token")

    presented = hashlib.sha256(authorization[7:].strip().encode("utf-8")).hexdigest()
    for known in settings.api_key_hashes:
        if hmac.compare_digest(presented, known):
            return presented
    raise AuthError("unknown api key")
