"""Google sign-in, mapped onto Lyren principals.

Google says *who the person is*. It says nothing about whether that person may use this deployment,
what their quota is, or which models they may reach — that is what a `Principal` holds. So a Google
identity is **matched against an existing principal and rejected when there is none**: auto-creating
a principal on first sign-in would let anyone holding a Google account in, which for a service built
for a named group is not a convenience but a hole.

The browser never carries a shared key. A verified Google ID token is exchanged for a short-lived
token bound to one principal, so per-person attribution survives the web app.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from lyren_core.errors import AuthError, ConfigError
from lyren_core.identity import Principal

GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"

SESSION_TOKEN_PREFIX = "lyst_"  # noqa: S105 — a prefix, not a secret
"""Marks a session token so it is never confused with an API key, and vice versa."""


@dataclass(frozen=True, slots=True)
class GoogleIdentity:
    subject: str
    email: str
    email_verified: bool
    hosted_domain: str | None
    name: str


class IdTokenVerifier:
    """Verifies a Google ID token.

    `key_resolver` exists so tests can sign with their own key instead of reaching Google. In
    production it is PyJWT's JWKS client, which fetches and caches Google's public keys.
    """

    def __init__(
        self,
        client_id: str,
        *,
        allowed_domains: frozenset[str] = frozenset(),
        key_resolver: Callable[[str], Any] | None = None,
        leeway_seconds: int = 10,
    ) -> None:
        if not client_id:
            raise ConfigError("Google sign-in needs LYREN_GOOGLE_CLIENT_ID")
        self._client_id = client_id
        self._allowed_domains = frozenset(d.lower() for d in allowed_domains)
        self._leeway = leeway_seconds
        self._key_resolver = key_resolver or self._google_key

    @staticmethod
    def _google_key(token: str) -> Any:
        client = jwt.PyJWKClient(GOOGLE_JWKS_URL, cache_keys=True)
        return client.get_signing_key_from_jwt(token).key

    def verify(self, id_token: str) -> GoogleIdentity:
        try:
            claims: dict[str, Any] = jwt.decode(
                id_token,
                key=self._key_resolver(id_token),
                algorithms=["RS256"],
                audience=self._client_id,
                issuer=list(GOOGLE_ISSUERS),
                leeway=self._leeway,
                options={"require": ["exp", "iat", "aud", "iss", "sub"]},
            )
        except jwt.PyJWTError as exc:
            raise AuthError("the Google id token could not be verified", detail=str(exc)) from exc

        email = str(claims.get("email") or "").strip().lower()
        if not email:
            raise AuthError("the Google id token carries no email")
        if claims.get("email_verified") is not True:
            raise AuthError("the Google account's email is not verified")

        hosted_domain = claims.get("hd")
        if self._allowed_domains:
            domain = str(hosted_domain or "").lower()
            if domain not in self._allowed_domains:
                raise AuthError(
                    "this Google account is outside the permitted domain",
                    detail=f"hd={domain or 'absent'}",
                )

        return GoogleIdentity(
            subject=str(claims["sub"]),
            email=email,
            email_verified=True,
            hosted_domain=str(hosted_domain) if hosted_domain else None,
            name=str(claims.get("name") or email),
        )


class SessionTokenIssuer:
    """Issues and reads short-lived principal-bound tokens.

    A signed token cannot be withdrawn before it expires, so the TTL is the revocation window:
    disabling a principal takes effect within one TTL, not instantly. Keeping the TTL short is the
    mitigation; a revocation list needs shared state and arrives with the database in Phase 5.
    """

    def __init__(
        self,
        secret: str,
        *,
        ttl_seconds: int = 1800,
        issuer: str = "lyren",
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if len(secret) < 32:
            raise ConfigError("LYREN_SESSION_SECRET must be at least 32 characters")
        self._secret = secret
        self._ttl = ttl_seconds
        self._issuer = issuer
        self._clock = clock or (lambda: datetime.now(UTC))

    @property
    def ttl_seconds(self) -> int:
        return self._ttl

    def issue(self, principal: Principal) -> str:
        now = self._clock()
        payload = {
            "sub": principal.id,
            "iss": self._issuer,
            "typ": "session",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=self._ttl)).timestamp()),
        }
        return SESSION_TOKEN_PREFIX + jwt.encode(payload, self._secret, algorithm="HS256")

    def read(self, token: str) -> str:
        """Returns the principal id a token is bound to."""
        if not token.startswith(SESSION_TOKEN_PREFIX):
            raise AuthError("not a Lyren session token")
        raw = token[len(SESSION_TOKEN_PREFIX) :]
        try:
            claims: dict[str, Any] = jwt.decode(
                raw,
                key=self._secret,
                algorithms=["HS256"],
                issuer=self._issuer,
                options={"require": ["exp", "iat", "iss", "sub"]},
            )
        except jwt.PyJWTError as exc:
            raise AuthError("the session token is not valid", detail=str(exc)) from exc
        if claims.get("typ") != "session":
            raise AuthError("the session token is of the wrong type")
        return str(claims["sub"])
