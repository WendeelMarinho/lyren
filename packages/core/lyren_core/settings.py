from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    api_key_hashes: tuple[str, ...] = ()

    oci_enabled: bool = False
    oci_compartment_id: str | None = None
    oci_region: str = "sa-saopaulo-1"
    oci_auth_mode: OCIAuthMode = OCIAuthMode.SECURITY_TOKEN
    oci_config_profile: str = "DEFAULT"

    allow_paid_providers: bool = Field(
        default=False,
        description="Gate for any provider that bills; fallback never crosses it without consent.",
    )
    max_output_tokens: int = 1024
    request_timeout_seconds: float = 120.0

    cache_mode: CacheMode = CacheMode.OFF
    cache_dir: Path = Path(".lyren-cache")

    @field_validator("api_key_hashes", mode="before")
    @classmethod
    def _split_hashes(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(item.strip() for item in value.split(",") if item.strip())
        return value

    @property
    def oci_ready(self) -> bool:
        return self.oci_enabled and bool(self.oci_compartment_id)
