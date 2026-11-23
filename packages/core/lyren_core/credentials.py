"""Password credentials for direct sign-up, until Google sign-in takes over.

Three properties drive the shape of this module.

**Registration does not create permission.** A password can only be set for an address a principal
already claims, exactly as with Google sign-in. Open registration on a pay-as-you-go account with no
automatic stop would let a stranger spend the group's budget.

**Login must not reveal whether an account exists.** A failed attempt hashes a dummy password so the
response time does not distinguish "no such account" from "wrong password", and both answer the same
way.

**Hashing is deliberately expensive, which makes login a denial-of-service surface** on two ARM
OCPUs. Hence the attempt throttle: it protects the passwords and the CPU at once.
"""

from __future__ import annotations

import json
import os
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from argon2 import PasswordHasher as Argon2Hasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from lyren_core.errors import AuthError, ConfigError, ForbiddenError

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 1024
"""Long passphrases are the good case. The ceiling only stops a hashing-cost attack."""

_DUMMY_HASH_INPUT = "lyren-timing-equaliser"


def _tuned_hasher() -> Argon2Hasher:
    """Argon2id at parameters a 2-OCPU ARM instance can serve.

    The library defaults assume more CPU than the target has. 64 MiB and two passes cost roughly
    120 ms on a development x86 machine and more on ARM, which is the intended order of magnitude:
    expensive for an attacker, tolerable for a person signing in.
    """
    return Argon2Hasher(time_cost=2, memory_cost=65536, parallelism=1, hash_len=32, salt_len=16)


@dataclass(frozen=True, slots=True)
class PasswordRecord:
    principal_id: str
    password_hash: str
    updated_at: str


def validate_password(password: str, *, email: str) -> None:
    """Length and obvious-reuse checks only.

    Composition rules (a digit, a symbol, mixed case) push people towards `Password1!` and are
    not applied, following current guidance. Length is what matters.
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ForbiddenError(f"the password must be at least {MIN_PASSWORD_LENGTH} characters")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise ForbiddenError(f"the password must be at most {MAX_PASSWORD_LENGTH} characters")

    local_part = email.split("@", 1)[0].strip().lower()
    folded = password.strip().lower()
    if local_part and (folded == local_part or folded == email.strip().lower()):
        raise ForbiddenError("the password must not be the address itself")


class CredentialStore:
    """Password hashes on disk, written atomically.

    A registration flow needs durable mutable state, and the project has no database yet. A JSON
    file replaced atomically (`os.replace`) under an in-process lock is correct for the
    single-worker deployment that per-principal metering already requires. It moves into the
    database in Phase 5; the methods are the port.
    """

    def __init__(self, path: Path, *, hasher: Argon2Hasher | None = None) -> None:
        self._path = path
        self._hasher = hasher or _tuned_hasher()
        self._lock = threading.Lock()
        self._records: dict[str, PasswordRecord] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.is_file():
            return
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        for entry in raw.get("passwords", []):
            record = PasswordRecord(
                principal_id=str(entry["principal_id"]),
                password_hash=str(entry["password_hash"]),
                updated_at=str(entry.get("updated_at", "")),
            )
            self._records[record.principal_id] = record

    def _flush(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "passwords": [
                {
                    "principal_id": r.principal_id,
                    "password_hash": r.password_hash,
                    "updated_at": r.updated_at,
                }
                for r in sorted(self._records.values(), key=lambda r: r.principal_id)
            ]
        }
        temporary = self._path.with_suffix(f"{self._path.suffix}.tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(temporary, self._path)
        self._path.chmod(0o600)

    def has_password(self, principal_id: str) -> bool:
        return principal_id in self._records

    def set_password(self, principal_id: str, password: str) -> None:
        with self._lock:
            self._records[principal_id] = PasswordRecord(
                principal_id=principal_id,
                password_hash=self._hasher.hash(password),
                updated_at=datetime.now(UTC).isoformat(timespec="seconds"),
            )
            self._flush()

    def verify(self, principal_id: str | None, password: str) -> bool:
        """Always does the work, so a missing account costs the same as a wrong password."""
        record = self._records.get(principal_id) if principal_id else None
        candidate = record.password_hash if record else self._hasher.hash(_DUMMY_HASH_INPUT)
        try:
            self._hasher.verify(candidate, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False
        if record is None:
            return False
        if self._hasher.check_needs_rehash(record.password_hash):
            self.set_password(principal_id or "", password)
        return True


class LoginThrottle:
    """Attempt limiter for pre-authentication endpoints.

    Keyed on the address rather than the principal, because at this point there is no principal yet
    — and keying on something only real accounts have would leak which addresses exist.
    """

    def __init__(
        self,
        *,
        max_attempts: int = 5,
        window_seconds: float = 300.0,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if max_attempts < 1:
            raise ConfigError("max_attempts must be at least 1")
        self._max = max_attempts
        self._window = window_seconds
        self._clock = clock or (lambda: datetime.now(UTC).timestamp())
        self._attempts: dict[str, deque[float]] = {}

    def _recent(self, key: str) -> deque[float]:
        attempts = self._attempts.setdefault(key, deque())
        cutoff = self._clock() - self._window
        while attempts and attempts[0] <= cutoff:
            attempts.popleft()
        return attempts

    def check(self, email: str) -> None:
        if len(self._recent(email.strip().lower())) >= self._max:
            raise AuthError(
                "too many failed sign-in attempts; try again later",
                detail=f"limit {self._max} per {int(self._window)}s",
            )

    def record_failure(self, email: str) -> None:
        self._recent(email.strip().lower()).append(self._clock())

    def clear(self, email: str) -> None:
        self._attempts.pop(email.strip().lower(), None)
