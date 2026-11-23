import hashlib

from fastapi.testclient import TestClient

from lyren_api.deps import (
    ProviderUnavailable,
    get_chat_provider,
    get_registry,
    get_settings,
)
from lyren_api.main import create_app
from lyren_core.errors import ModelNotAvailableError
from lyren_core.settings import Settings
from lyren_inference.ports import Availability, ChatResponse, Usage
from lyren_inference.registry import ModelRegistry

API_KEY = "test-key"
AUTH = {"Authorization": f"Bearer {API_KEY}"}


class StubProvider:
    name = "stub"

    def __init__(self, fail_for=()):
        self.fail_for = set(fail_for)
        self.seen = []

    def chat(self, spec, request):
        self.seen.append(spec.id)
        if spec.id in self.fail_for:
            raise ModelNotAvailableError(f"{spec.id} is gone")
        return ChatResponse(
            model_id=spec.id,
            text="pong",
            finish_reason="stop",
            usage=Usage(prompt_tokens=3, completion_tokens=1),
        )


def build(provider=None, *, with_keys=True, registry=None):
    settings = Settings(
        api_key_hashes=(hashlib.sha256(API_KEY.encode()).hexdigest(),) if with_keys else (),
        oci_enabled=False,
    )
    registry = registry or ModelRegistry()
    provider = provider if provider is not None else StubProvider()

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_registry] = lambda: registry
    app.dependency_overrides[get_chat_provider] = lambda: provider
    return TestClient(app, raise_server_exceptions=False), registry, provider


def test_healthz_is_public():
    client, _, _ = build()

    assert client.get("/healthz").json() == {"status": "ok"}


def test_readyz_reports_503_when_no_api_keys_are_configured():
    client, _, _ = build(with_keys=False)

    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["checks"]["api_keys_configured"] is False


def test_readyz_reports_the_reason_a_provider_is_missing():
    client, _, _ = build(provider=ProviderUnavailable("no compartment configured"))

    body = client.get("/readyz").json()

    assert body["ready"] is False
    assert body["chat_provider_reason"] == "no compartment configured"


def test_models_requires_a_bearer_key():
    client, _, _ = build()

    assert client.get("/v1/models").status_code == 401


def test_models_lists_callable_models_and_aliases_only():
    client, _, _ = build()

    ids = {entry["id"] for entry in client.get("/v1/models", headers=AUTH).json()["data"]}

    assert "meta.llama-3.3-70b-instruct" in ids
    assert "lyren/fast" in ids
    assert "google.gemini-2.5-flash" not in ids
    assert "openai.gpt-oss-120b" not in ids


def test_native_listing_exposes_why_a_model_is_unavailable():
    client, _, _ = build()

    body = client.get("/lyren/v1/models", headers=AUTH).json()
    by_id = {m["id"]: m for m in body["models"]}

    assert by_id["google.gemini-2.5-flash"]["availability"] == "quota_zero"
    assert by_id["openai.gpt-oss-120b"]["availability"] == "not_found"


def test_streaming_is_refused_instead_of_silently_ignored():
    client, _, _ = build()

    response = client.post(
        "/v1/chat/completions",
        headers=AUTH,
        json={
            "model": "lyren/fast",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
    )

    assert response.status_code == 502
    assert "streaming is not implemented" in response.json()["error"]["message"]


def test_chat_returns_an_openai_shaped_completion():
    client, _, _ = build()

    body = client.post(
        "/v1/chat/completions",
        headers=AUTH,
        json={"model": "lyren/fast", "messages": [{"role": "user", "content": "ping"}]},
    ).json()

    assert body["object"] == "chat.completion"
    assert body["model"] == "meta.llama-4-scout-17b-16e-instruct"
    assert body["choices"][0]["message"] == {"role": "assistant", "content": "pong"}
    assert body["usage"]["total_tokens"] == 4


def test_alias_falls_back_to_the_next_candidate_and_records_the_verdict():
    provider = StubProvider(fail_for={"cohere.command-a-03-2025"})
    client, registry, _ = build(provider=provider)

    body = client.post(
        "/v1/chat/completions",
        headers=AUTH,
        json={"model": "lyren/deep", "messages": [{"role": "user", "content": "ping"}]},
    ).json()

    assert body["model"] == "meta.llama-3.3-70b-instruct"
    assert provider.seen == ["cohere.command-a-03-2025", "meta.llama-3.3-70b-instruct"]
    assert registry.spec("cohere.command-a-03-2025").availability is Availability.NOT_FOUND


def test_alias_output_budget_caps_a_larger_client_request():
    captured = {}

    class Capturing(StubProvider):
        def chat(self, spec, request):
            captured["max_output_tokens"] = request.max_output_tokens
            return super().chat(spec, request)

    client, _, _ = build(provider=Capturing())
    client.post(
        "/v1/chat/completions",
        headers=AUTH,
        json={
            "model": "lyren/fast",
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 9000,
        },
    )

    assert captured["max_output_tokens"] == 1024


def test_request_id_is_echoed_back():
    client, _, _ = build()

    response = client.get("/healthz", headers={"x-request-id": "req_fixed"})

    assert response.headers["x-request-id"] == "req_fixed"
