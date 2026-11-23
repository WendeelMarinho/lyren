"""Principals and API keys.

Lyren serves several people, so an API key identifies *who* rather than merely granting access.
Every downstream concern depends on that: per-principal quotas so one person cannot spend the
shared budget, memory ownership, audit attribution, and revoking one key without rotating
everyone's.

The store is file-backed for now. It moves into the database in Phase 5; the port is what matters,
not the backing.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from lyren_core.errors import ConfigError

DEV_PRINCIPAL_ID = "dev"


def hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.strip().encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Quota:
    """Per-principal limits. Enforced independently, so principals cannot starve each other."""

    requests_per_minute: int = 20
    calls_per_day: int = 500
    max_output_tokens: int = 1024


@dataclass(frozen=True, slots=True)
class Principal:
    id: str
    name: str
    quota: Quota = field(default_factory=Quota)
    allowed_models: frozenset[str] | None = None
    """None means every callable model and alias. A set restricts to those names."""
    emails: frozenset[str] = frozenset()
    """Verified Google addresses that map to this principal. Empty means no web sign-in."""
    enabled: bool = True

    def may_use(self, model: str) -> bool:
        return self.allowed_models is None or model in self.allowed_models


@dataclass(frozen=True, slots=True)
class ApiKeyRecord:
    key_hash: str
    principal_id: str
    label: str
    created_at: date
    revoked_at: date | None = None

    @property
    def active(self) -> bool:
        return self.revoked_at is None


class PrincipalStore:
    """Resolves a presented key hash to a principal, or to nothing.

    Resolution fails identically for an unknown key, a revoked key and a disabled principal: the
    caller learns only that the key does not work, never which of the three it was.
    """

    def __init__(self, principals: tuple[Principal, ...], keys: tuple[ApiKeyRecord, ...]) -> None:
        self._principals = {p.id: p for p in principals}
        orphans = sorted({k.principal_id for k in keys} - self._principals.keys())
        if orphans:
            raise ConfigError(f"api keys reference unknown principals: {orphans}")
        self._keys = {k.key_hash: k for k in keys}

        self._by_email: dict[str, str] = {}
        for principal in principals:
            for email in principal.emails:
                normalised = email.strip().lower()
                claimed = self._by_email.get(normalised)
                if claimed is not None and claimed != principal.id:
                    raise ConfigError(
                        f"{normalised} is claimed by both {claimed} and {principal.id}"
                    )
                self._by_email[normalised] = principal.id

    def __len__(self) -> int:
        return len(self._principals)

    def principals(self) -> tuple[Principal, ...]:
        return tuple(self._principals.values())

    def resolve(self, key_hash: str) -> Principal | None:
        record = self._keys.get(key_hash)
        if record is None or not record.active:
            return None
        principal = self._principals.get(record.principal_id)
        if principal is None or not principal.enabled:
            return None
        return principal

    def resolve_email(self, email: str) -> Principal | None:
        """Maps a verified federated address to a principal, or to nothing.

        No auto-provisioning: an address nobody declared resolves to nothing, so holding a Google
        account is not by itself permission to use this deployment.
        """
        principal_id = self._by_email.get(email.strip().lower())
        if principal_id is None:
            return None
        principal = self._principals.get(principal_id)
        if principal is None or not principal.enabled:
            return None
        return principal

    def resolve_id(self, principal_id: str) -> Principal | None:
        principal = self._principals.get(principal_id)
        if principal is None or not principal.enabled:
            return None
        return principal

    @classmethod
    def single_dev_principal(cls, key_hashes: tuple[str, ...]) -> PrincipalStore:
        """Development shortcut: every listed hash maps to one unrestricted principal.

        Never acceptable outside a local environment — it gives no attribution and no way to revoke
        one person's access, which is the whole point of having principals.
        """
        principal = Principal(id=DEV_PRINCIPAL_ID, name="local development")
        keys = tuple(
            ApiKeyRecord(
                key_hash=key_hash,
                principal_id=DEV_PRINCIPAL_ID,
                label=f"dev-{index}",
                created_at=date.today(),
            )
            for index, key_hash in enumerate(key_hashes)
        )
        return cls((principal,), keys)

    @classmethod
    def from_file(cls, path: Path) -> PrincipalStore:
        raw = json.loads(path.read_text(encoding="utf-8"))
        principals = tuple(
            Principal(
                id=str(entry["id"]),
                name=str(entry["name"]),
                quota=Quota(**entry.get("quota", {})),
                allowed_models=(
                    frozenset(str(m) for m in entry["allowed_models"])
                    if entry.get("allowed_models") is not None
                    else None
                ),
                emails=frozenset(str(e).strip().lower() for e in entry.get("emails", ())),
                enabled=bool(entry.get("enabled", True)),
            )
            for entry in raw.get("principals", [])
        )
        keys = tuple(
            ApiKeyRecord(
                key_hash=str(entry["key_hash"]),
                principal_id=str(entry["principal_id"]),
                label=str(entry.get("label", "")),
                created_at=date.fromisoformat(str(entry["created_at"])),
                revoked_at=(
                    date.fromisoformat(str(entry["revoked_at"]))
                    if entry.get("revoked_at")
                    else None
                ),
            )
            for entry in raw.get("api_keys", [])
        )
        if not principals:
            raise ConfigError(f"{path.name} declares no principals")
        return cls(principals, keys)
