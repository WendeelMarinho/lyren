import tempfile
from datetime import date
from pathlib import Path

from argon2 import PasswordHasher as Argon2Hasher
from fastapi.testclient import TestClient

from lyren_api.deps import (
    get_chat_provider,
    get_credential_store,
    get_id_token_verifier,
    get_login_throttle,
    get_optional_token_issuer,
    get_principal_store,
    get_registry,
    get_settings,
    get_token_issuer,
    get_usage_meter,
)
from lyren_api.main import create_app
from lyren_core.credentials import CredentialStore, LoginThrottle
from lyren_core.federation import SessionTokenIssuer
from lyren_core.identity import ApiKeyRecord, Principal, PrincipalStore, Quota, hash_key
from lyren_core.metering import UsageMeter
from lyren_core.settings import Settings
from lyren_inference.ports import ChatResponse, Usage

SECRET = "s" * 48
API_KEY = "ana-api-key"


class VerifierStub:
    def __init__(self, email="ana@example.com"):
        self.email = email
        self.seen = []

    def verify(self, id_token):
        from lyren_core.federation import GoogleIdentity

        self.seen.append(id_token)
        return GoogleIdentity(
            subject="123",
            email=self.email,
            email_verified=True,
            hosted_domain="example.com",
            name="Ana",
        )


class ChatStub:
    name = "stub"

    def chat(self, spec, request):
        return ChatResponse(
            model_id=spec.id,
            text="pong",
            finish_reason="stop",
            usage=Usage(prompt_tokens=2, completion_tokens=1),
        )


def build(
    verifier=None,
    *,
    emails=("ana@example.com",),
    tmp_path=None,
    registration_token_hash=None,
    max_attempts=5,
):
    ana = Principal(
        id="ana",
        name="Ana Souza",
        quota=Quota(requests_per_minute=9, calls_per_day=11, max_output_tokens=321),
        emails=frozenset(emails),
        registration_token_hash=registration_token_hash,
    )
    store = PrincipalStore(
        (ana,), (ApiKeyRecord(hash_key(API_KEY), "ana", "k", date(2026, 11, 24)),)
    )
    issuer = SessionTokenIssuer(SECRET)
    meter = UsageMeter()
    # Cheap argon2 parameters: the tuned ones cost ~120 ms a hash.
    credentials = CredentialStore(
        (tmp_path or Path(tempfile.mkdtemp())) / "creds.json",
        hasher=Argon2Hasher(time_cost=1, memory_cost=8, parallelism=1, hash_len=16, salt_len=8),
    )
    throttle = LoginThrottle(max_attempts=max_attempts)
    settings = Settings(
        oci_enabled=False,
        session_secret=SECRET,
        google_client_id="client.apps.googleusercontent.com",
    )
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_principal_store] = lambda: store
    app.dependency_overrides[get_token_issuer] = lambda: issuer
    app.dependency_overrides[get_optional_token_issuer] = lambda: issuer
    app.dependency_overrides[get_id_token_verifier] = lambda: verifier or VerifierStub()
    app.dependency_overrides[get_usage_meter] = lambda: meter
    app.dependency_overrides[get_credential_store] = lambda: credentials
    app.dependency_overrides[get_login_throttle] = lambda: throttle
    app.dependency_overrides[get_chat_provider] = lambda: ChatStub()
    from lyren_inference.registry import ModelRegistry

    app.dependency_overrides[get_registry] = lambda: ModelRegistry()
    return TestClient(app, raise_server_exceptions=False), issuer, credentials


def sign_in(client):
    return client.post("/lyren/v1/auth/google", json={"id_token": "x" * 32})


def test_sign_in_returns_a_principal_bound_session_token():
    client, issuer, _ = build()

    body = sign_in(client).json()

    assert body["token_type"] == "Bearer"
    assert body["principal"] == {"id": "ana", "name": "Ana Souza"}
    assert body["expires_in"] == issuer.ttl_seconds
    assert issuer.read(body["access_token"]) == "ana"


def test_a_google_account_no_principal_claims_is_refused():
    client, _, _ = build(verifier=VerifierStub(email="stranger@example.com"))

    response = sign_in(client)

    assert response.status_code == 401
    assert "not registered" in response.json()["error"]["message"]


def test_a_session_token_authenticates_the_identity_endpoint():
    client, _, _ = build()
    token = sign_in(client).json()["access_token"]

    body = client.get("/lyren/v1/me", headers={"Authorization": f"Bearer {token}"}).json()

    assert body["id"] == "ana"
    assert body["quota"]["calls_per_day"] == 11
    assert body["usage_today"]["calls"] == 0


def test_an_api_key_authenticates_the_same_endpoint():
    client, _, _ = build()

    body = client.get("/lyren/v1/me", headers={"Authorization": f"Bearer {API_KEY}"}).json()

    assert body["id"] == "ana"


def test_a_session_token_can_call_chat_and_is_attributed():
    client, _, _ = build()
    token = sign_in(client).json()["access_token"]

    body = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {token}"},
        json={"model": "lyren/fast", "messages": [{"role": "user", "content": "ping"}]},
    ).json()

    assert body["lyren"]["principal"] == "ana"


def test_usage_reported_by_the_identity_endpoint_reflects_real_calls():
    client, _, _ = build()
    headers = {"Authorization": f"Bearer {API_KEY}"}
    client.post(
        "/v1/chat/completions",
        headers=headers,
        json={"model": "lyren/fast", "messages": [{"role": "user", "content": "ping"}]},
    )

    body = client.get("/lyren/v1/me", headers=headers).json()

    assert body["usage_today"] == {"calls": 1, "prompt_tokens": 2, "completion_tokens": 1}


def test_a_tampered_session_token_is_refused():
    client, _, _ = build()
    token = sign_in(client).json()["access_token"]

    response = client.get("/lyren/v1/me", headers={"Authorization": f"Bearer {token}x"})

    assert response.status_code == 401


def test_the_sign_in_config_exposes_only_the_public_client_id():
    client, _, _ = build()

    body = client.get("/lyren/v1/auth/config").json()

    assert body == {
        "provider": "google",
        "client_id": "client.apps.googleusercontent.com",
        "allowed_domains": [],
    }


def test_the_identity_endpoint_needs_a_credential():
    client, _, _ = build()

    assert client.get("/lyren/v1/me").status_code == 401


PASSWORD = "uma-senha-bem-comprida"


def register(client, email="ana@example.com", password=PASSWORD, token=None):
    body = {"email": email, "password": password}
    if token is not None:
        body["registration_token"] = token
    return client.post("/lyren/v1/auth/register", json=body)


def login(client, email="ana@example.com", password=PASSWORD):
    return client.post("/lyren/v1/auth/login", json={"email": email, "password": password})


def test_registering_a_claimed_address_returns_a_session_token(tmp_path):
    client, issuer, _ = build(tmp_path=tmp_path)

    body = register(client).json()

    assert body["principal"]["id"] == "ana"
    assert issuer.read(body["access_token"]) == "ana"


def test_an_unclaimed_address_cannot_register(tmp_path):
    client, _, _ = build(tmp_path=tmp_path)

    response = register(client, email="stranger@example.com")

    assert response.status_code == 401
    assert response.json()["error"]["message"] == "this address cannot be registered"


def test_registering_twice_is_refused_with_the_same_message(tmp_path):
    """Indistinguishable from an unclaimed address, so the endpoint cannot enumerate accounts."""
    client, _, _ = build(tmp_path=tmp_path)
    register(client)

    second = register(client)
    unclaimed = register(client, email="stranger@example.com")

    assert second.status_code == unclaimed.status_code == 401
    assert second.json()["error"]["message"] == unclaimed.json()["error"]["message"]


def test_a_weak_password_is_refused(tmp_path):
    client, _, _ = build(tmp_path=tmp_path)

    response = register(client, password="curta")

    assert response.status_code == 403
    assert "at least" in response.json()["error"]["message"]


def test_a_registration_token_is_required_when_the_principal_declares_one(tmp_path):
    client, _, _ = build(tmp_path=tmp_path, registration_token_hash=hash_key("invite-123"))

    without = register(client)
    wrong = register(client, token="guessed")
    right = register(client, token="invite-123")

    assert without.status_code == 401
    assert wrong.status_code == 401
    assert right.status_code == 200


def test_signing_in_with_the_registered_password_works(tmp_path):
    client, issuer, _ = build(tmp_path=tmp_path)
    register(client)

    body = login(client).json()

    assert issuer.read(body["access_token"]) == "ana"


def test_a_wrong_password_and_an_unknown_address_answer_identically(tmp_path):
    client, _, _ = build(tmp_path=tmp_path)
    register(client)

    wrong = login(client, password="outra-senha-comprida")
    unknown = login(client, email="stranger@example.com")

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"]


def test_repeated_failures_lock_the_address_out(tmp_path):
    client, _, _ = build(tmp_path=tmp_path, max_attempts=2)
    register(client)

    login(client, password="errada-mas-comprida")
    login(client, password="errada-mas-comprida")
    locked = login(client)

    assert locked.status_code == 401
    assert "too many failed" in locked.json()["error"]["message"]


def test_a_successful_sign_in_clears_the_lockout_counter(tmp_path):
    client, _, _ = build(tmp_path=tmp_path, max_attempts=2)
    register(client)
    login(client, password="errada-mas-comprida")

    assert login(client).status_code == 200
    assert login(client, password="errada-mas-comprida").status_code == 401
    assert login(client).status_code == 200


def test_a_session_token_from_password_sign_in_reaches_the_identity_endpoint(tmp_path):
    client, _, _ = build(tmp_path=tmp_path)
    token = register(client).json()["access_token"]

    body = client.get("/lyren/v1/me", headers={"Authorization": f"Bearer {token}"}).json()

    assert body["id"] == "ana"


def test_changing_the_password_requires_the_current_one(tmp_path):
    client, _, _ = build(tmp_path=tmp_path)
    token = register(client).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    wrong = client.post(
        "/lyren/v1/auth/password",
        headers=headers,
        json={"current_password": "errada-mas-comprida", "new_password": "nova-senha-comprida"},
    )

    assert wrong.status_code == 401
    assert "current password is wrong" in wrong.json()["error"]["message"]


def test_a_changed_password_replaces_the_old_one(tmp_path):
    client, _, _ = build(tmp_path=tmp_path)
    token = register(client).json()["access_token"]

    changed = client.post(
        "/lyren/v1/auth/password",
        headers={"Authorization": f"Bearer {token}"},
        json={"current_password": PASSWORD, "new_password": "nova-senha-bem-comprida"},
    )

    assert changed.status_code == 200
    assert login(client, password=PASSWORD).status_code == 401
    assert login(client, password="nova-senha-bem-comprida").status_code == 200


def test_changing_a_password_needs_a_credential(tmp_path):
    client, _, _ = build(tmp_path=tmp_path)

    response = client.post(
        "/lyren/v1/auth/password",
        json={"current_password": PASSWORD, "new_password": "nova-senha-comprida"},
    )

    assert response.status_code == 401
