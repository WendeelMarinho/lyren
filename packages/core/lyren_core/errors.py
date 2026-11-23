from __future__ import annotations


class LyrenError(Exception):
    code = "lyren_error"
    http_status = 500

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail


class ConfigError(LyrenError):
    code = "config_error"


class AuthError(LyrenError):
    code = "invalid_api_key"
    http_status = 401


class ProviderError(LyrenError):
    code = "provider_error"
    http_status = 502


class ModelNotAvailableError(ProviderError):
    """Model is absent from the provider's on-demand serving set."""

    code = "model_not_available"
    http_status = 404


class ModelDisabledByQuotaError(ProviderError):
    """Model exists but the tenancy quota for it is zero."""

    code = "model_disabled_by_quota"
    http_status = 403


class CacheMissError(LyrenError):
    code = "cache_miss"
