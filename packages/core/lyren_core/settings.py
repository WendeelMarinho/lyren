from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Environment(StrEnum):
    LOCAL = "local"
    STAGING = "staging"
    PRODUCTION = "production"


class CacheMode(StrEnum):
    OFF = "off"
    RECORD = "record"
    REPLAY = "replay"
    AUTO = "auto"


class OCIAuthMode(StrEnum):
    SECURITY_TOKEN = "security_token"  # noqa: S105
    API_KEY = "api_key"
    INSTANCE_PRINCIPAL = "instance_principal"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LYREN_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    environment: Environment = Environment.LOCAL
    log_level: str = "INFO"

    principals_file: Path | None = None
    """The real authentication mechanism for a shared deployment."""

    session_secret: str | None = None
    """Signs browser session tokens. Required for Google sign-in."""
    session_ttl_seconds: int = 1800
    """Also the revocation window: a signed token cannot be withdrawn before it expires."""

    google_client_id: str | None = None
    google_allowed_domains: Annotated[tuple[str, ...], NoDecode] = ()
    """Restricts sign-in to Workspace domains. Empty permits any verified Google account that a
    principal already claims."""

    api_key_hashes: Annotated[tuple[str, ...], NoDecode] = ()
    """Single-principal development shortcut. Refused outside a local environment."""

    oci_enabled: bool = False
    oci_compartment_id: str | None = None
    oci_region: str = "sa-saopaulo-1"
    oci_auth_mode: OCIAuthMode = OCIAuthMode.SECURITY_TOKEN
    oci_config_profile: str = "DEFAULT"

    allow_paid_providers: bool = Field(
        default=False,
        description="Gate for any provider that bills; fallback never crosses it without consent.",
    )
    deployment_calls_per_day: int = 2000
    """Binds the whole deployment, because the sum of per-principal quotas does not."""

    max_output_tokens: int = 1024
    request_timeout_seconds: float = 120.0

    local_enabled: bool = False
    local_base_url: str = "http://127.0.0.1:8080"
    local_model_id: str = "local/unspecified"
    """Which GGUF the llama.cpp server has loaded. Declared, never guessed."""

    cache_mode: CacheMode = CacheMode.OFF
    cache_dir: Path = Path(".lyren-cache")

    @field_validator("api_key_hashes", "google_allowed_domains", mode="before")
    @classmethod
    def _split_hashes(cls, value: object) -> object:
        """Comma-separated, not JSON.

        `NoDecode` is what makes this validator reachable: without it pydantic-settings tries to
        JSON-decode a complex field straight from the environment and fails before any validator
        runs, so the documented `LYREN_API_KEY_HASHES=<hash>,<hash>` form never worked.
        """
        if isinstance(value, str):
            return tuple(item.strip() for item in value.split(",") if item.strip())
        return value

    @property
    def oci_ready(self) -> bool:
        return self.oci_enabled and bool(self.oci_compartment_id)

    @property
    def is_local(self) -> bool:
        return self.environment is Environment.LOCAL

    @property
    def google_sign_in_configured(self) -> bool:
        return bool(self.google_client_id) and bool(self.session_secret)

    @property
    def auth_configured(self) -> bool:
        return self.principals_file is not None or bool(self.api_key_hashes)
