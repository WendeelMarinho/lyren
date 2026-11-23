from datetime import date

from fastapi.testclient import TestClient

from lyren_api.deps import (
    get_chat_provider,
    get_id_token_verifier,
    get_optional_token_issuer,
    get_principal_store,
    get_registry,
    get_settings,
    get_token_issuer,
    get_usage_meter,
)
from lyren_api.main import create_app
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


def build(verifier=None, *, emails=("ana@example.com",)):
    ana = Principal(
        id="ana",
        name="Ana Souza",
        quota=Quota(requests_per_minute=9, calls_per_day=11, max_output_tokens=321),
        emails=frozenset(emails),
    )
    store = PrincipalStore(
        (ana,), (ApiKeyRecord(hash_key(API_KEY), "ana", "k", date(2026, 11, 24)),)
    )
    issuer = SessionTokenIssuer(SECRET)
    meter = UsageMeter()
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
    app.dependency_overrides[get_chat_provider] = lambda: ChatStub()
    from lyren_inference.registry import ModelRegistry

    app.dependency_overrides[get_registry] = lambda: ModelRegistry()
    return TestClient(app, raise_server_exceptions=False), issuer


def sign_in(client):
    return client.post("/lyren/v1/auth/google", json={"id_token": "x" * 32})


def test_sign_in_returns_a_principal_bound_session_token():
    client, issuer = build()

    body = sign_in(client).json()

    assert body["token_type"] == "Bearer"  # noqa: S105 — a scheme name, not a secret
    assert body["principal"] == {"id": "ana", "name": "Ana Souza"}
    assert body["expires_in"] == issuer.ttl_seconds
    assert issuer.read(body["access_token"]) == "ana"


def test_a_google_account_no_principal_claims_is_refused():
    client, _ = build(verifier=VerifierStub(email="stranger@example.com"))

    response = sign_in(client)

    assert response.status_code == 401
    assert "not registered" in response.json()["error"]["message"]


def test_a_session_token_authenticates_the_identity_endpoint():
    client, _ = build()
    token = sign_in(client).json()["access_token"]

    body = client.get("/lyren/v1/me", headers={"Authorization": f"Bearer {token}"}).json()

    assert body["id"] == "ana"
    assert body["quota"]["calls_per_day"] == 11
    assert body["usage_today"]["calls"] == 0


def test_an_api_key_authenticates_the_same_endpoint():
    client, _ = build()

    body = client.get("/lyren/v1/me", headers={"Authorization": f"Bearer {API_KEY}"}).json()

    assert body["id"] == "ana"


def test_a_session_token_can_call_chat_and_is_attributed():
    client, _ = build()
    token = sign_in(client).json()["access_token"]

    body = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {token}"},
        json={"model": "lyren/fast", "messages": [{"role": "user", "content": "ping"}]},
    ).json()

    assert body["lyren"]["principal"] == "ana"


def test_usage_reported_by_the_identity_endpoint_reflects_real_calls():
    client, _ = build()
    headers = {"Authorization": f"Bearer {API_KEY}"}
    client.post(
        "/v1/chat/completions",
        headers=headers,
        json={"model": "lyren/fast", "messages": [{"role": "user", "content": "ping"}]},
    )

    body = client.get("/lyren/v1/me", headers=headers).json()

    assert body["usage_today"] == {"calls": 1, "prompt_tokens": 2, "completion_tokens": 1}


def test_a_tampered_session_token_is_refused():
    client, _ = build()
    token = sign_in(client).json()["access_token"]

    response = client.get("/lyren/v1/me", headers={"Authorization": f"Bearer {token}x"})

    assert response.status_code == 401


def test_the_sign_in_config_exposes_only_the_public_client_id():
    client, _ = build()

    body = client.get("/lyren/v1/auth/config").json()

    assert body == {
        "provider": "google",
        "client_id": "client.apps.googleusercontent.com",
        "allowed_domains": [],
    }


def test_the_identity_endpoint_needs_a_credential():
    client, _ = build()

    assert client.get("/lyren/v1/me").status_code == 401
