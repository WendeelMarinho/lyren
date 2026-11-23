from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from lyren_core.errors import AuthError, ConfigError
from lyren_core.federation import SESSION_TOKEN_PREFIX, IdTokenVerifier, SessionTokenIssuer
from lyren_core.identity import Principal, Quota

CLIENT_ID = "lyren-web.apps.googleusercontent.com"
SECRET = "x" * 48
ANA = Principal(id="ana", name="Ana", quota=Quota(calls_per_day=9))

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def id_token(**overrides):
    now = datetime.now(UTC)
    claims = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "sub": "123",
        "email": "Ana@Example.com",
        "email_verified": True,
        "name": "Ana",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
    }
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, _KEY, algorithm="RS256")


def verifier(**kwargs):
    return IdTokenVerifier(CLIENT_ID, key_resolver=lambda _token: _KEY.public_key(), **kwargs)


def test_a_valid_token_yields_a_normalised_identity():
    identity = verifier().verify(id_token())

    assert identity.email == "ana@example.com"
    assert (identity.subject, identity.email_verified) == ("123", True)


def test_a_client_id_is_required():
    with pytest.raises(ConfigError, match="GOOGLE_CLIENT_ID"):
        IdTokenVerifier("")


def test_a_token_for_another_audience_is_refused():
    with pytest.raises(AuthError, match="could not be verified"):
        verifier().verify(id_token(aud="someone-else.apps.googleusercontent.com"))


def test_a_token_from_another_issuer_is_refused():
    with pytest.raises(AuthError, match="could not be verified"):
        verifier().verify(id_token(iss="https://evil.example.com"))


def test_an_expired_token_is_refused():
    stale = datetime.now(UTC) - timedelta(hours=1)
    with pytest.raises(AuthError, match="could not be verified"):
        verifier().verify(id_token(exp=int(stale.timestamp()), iat=int(stale.timestamp())))


def test_a_token_signed_by_another_key_is_refused():
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged = IdTokenVerifier(CLIENT_ID, key_resolver=lambda _t: other.public_key())

    with pytest.raises(AuthError, match="could not be verified"):
        forged.verify(id_token())


def test_an_unverified_email_is_refused():
    with pytest.raises(AuthError, match="not verified"):
        verifier().verify(id_token(email_verified=False))


def test_a_token_without_an_email_is_refused():
    with pytest.raises(AuthError, match="no email"):
        verifier().verify(id_token(email=None))


def test_a_permitted_workspace_domain_passes():
    restricted = verifier(allowed_domains=frozenset({"example.com"}))

    assert restricted.verify(id_token(hd="Example.com")).hosted_domain == "Example.com"


def test_an_account_outside_the_permitted_domain_is_refused():
    restricted = verifier(allowed_domains=frozenset({"example.com"}))

    with pytest.raises(AuthError, match="outside the permitted domain"):
        restricted.verify(id_token(hd="other.com"))


def test_a_personal_account_is_refused_when_a_domain_is_required():
    restricted = verifier(allowed_domains=frozenset({"example.com"}))

    with pytest.raises(AuthError, match="outside the permitted domain"):
        restricted.verify(id_token())


def test_a_session_token_round_trips_to_its_principal():
    issuer = SessionTokenIssuer(SECRET)

    token = issuer.issue(ANA)

    assert token.startswith(SESSION_TOKEN_PREFIX)
    assert issuer.read(token) == "ana"


def test_a_short_secret_is_refused():
    with pytest.raises(ConfigError, match="at least 32"):
        SessionTokenIssuer("too-short")


def test_an_expired_session_token_is_refused():
    past = datetime.now(UTC) - timedelta(hours=2)
    issuer = SessionTokenIssuer(SECRET, ttl_seconds=60, clock=lambda: past)
    token = issuer.issue(ANA)

    with pytest.raises(AuthError, match="not valid"):
        SessionTokenIssuer(SECRET).read(token)


def test_a_token_signed_with_another_secret_is_refused():
    token = SessionTokenIssuer("a" * 48).issue(ANA)

    with pytest.raises(AuthError, match="not valid"):
        SessionTokenIssuer("b" * 48).read(token)


def test_an_api_key_is_not_mistaken_for_a_session_token():
    with pytest.raises(AuthError, match="not a Lyren session token"):
        SessionTokenIssuer(SECRET).read("abcdef0123456789")


def test_a_token_of_another_type_is_refused():
    now = datetime.now(UTC)
    raw = jwt.encode(
        {
            "sub": "ana",
            "iss": "lyren",
            "typ": "refresh",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
        },
        SECRET,
        algorithm="HS256",
    )

    with pytest.raises(AuthError, match="wrong type"):
        SessionTokenIssuer(SECRET).read(SESSION_TOKEN_PREFIX + raw)
