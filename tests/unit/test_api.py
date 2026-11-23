from datetime import date

import pytest
from fastapi.testclient import TestClient

from lyren_api.deps import (
    ProviderUnavailable,
    get_chat_provider,
    get_principal_store,
    get_registry,
    get_settings,
    get_usage_meter,
)
from lyren_api.main import create_app
from lyren_core.errors import ModelNotAvailableError
from lyren_core.identity import ApiKeyRecord, Principal, PrincipalStore, Quota, hash_key
from lyren_core.metering import UsageMeter
from lyren_core.settings import Settings
from lyren_inference.ports import Availability, ChatResponse, Usage
from lyren_inference.registry import ModelRegistry

ANA_KEY = "ana-key"
BRUNO_KEY = "bruno-key"
ANA = {"Authorization": f"Bearer {ANA_KEY}"}
BRUNO = {"Authorization": f"Bearer {BRUNO_KEY}"}


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


def _store(ana_quota=None):
    ana = Principal(id="ana", name="Ana", quota=ana_quota or Quota())
    bruno = Principal(id="bruno", name="Bruno", allowed_models=frozenset({"lyren/fast"}))
    keys = (
        ApiKeyRecord(hash_key(ANA_KEY), "ana", "k", date(2026, 11, 24)),
        ApiKeyRecord(hash_key(BRUNO_KEY), "bruno", "k", date(2026, 11, 24)),
    )
    return PrincipalStore((ana, bruno), keys)


def build(provider=None, *, store=None, registry=None, meter=None, settings=None):
    registry = registry or ModelRegistry()
    provider = provider if provider is not None else StubProvider()
    # One meter for the whole client: a fresh one per request would never accumulate a quota.
    meter = meter or UsageMeter()
    store = store or _store()
    settings = settings or Settings(oci_enabled=False)

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_registry] = lambda: registry
    app.dependency_overrides[get_chat_provider] = lambda: provider
    app.dependency_overrides[get_principal_store] = lambda: store
    app.dependency_overrides[get_usage_meter] = lambda: meter
    return TestClient(app, raise_server_exceptions=False), registry, provider


def test_healthz_is_public():
    client, _, _ = build()

    assert client.get("/healthz").json() == {"status": "ok"}


def test_readyz_reports_the_reason_a_provider_is_missing():
    client, _, _ = build(provider=ProviderUnavailable("no compartment configured"))

    body = client.get("/readyz").json()

    assert body["ready"] is False
    assert body["chat_provider_reason"] == "no compartment configured"


def test_models_requires_a_bearer_key():
    client, _, _ = build()

    assert client.get("/v1/models").status_code == 401


def test_an_unknown_key_is_rejected():
    client, _, _ = build()

    response = client.get("/v1/models", headers={"Authorization": "Bearer guessed"})

    assert response.status_code == 401


def test_models_lists_callable_models_and_aliases_only():
    client, _, _ = build()

    ids = {entry["id"] for entry in client.get("/v1/models", headers=ANA).json()["data"]}

    assert "meta.llama-3.3-70b-instruct" in ids
    assert "lyren/fast" in ids
    assert "google.gemini-2.5-flash" not in ids
    assert "openai.gpt-oss-120b" not in ids


def test_the_listing_is_narrowed_to_what_the_principal_may_use():
    client, _, _ = build()

    ids = {entry["id"] for entry in client.get("/v1/models", headers=BRUNO).json()["data"]}

    assert ids == {"lyren/fast"}


def test_a_principal_cannot_call_a_model_it_is_not_permitted_to_use():
    client, _, _ = build()

    response = client.post(
        "/v1/chat/completions",
        headers=BRUNO,
        json={"model": "lyren/deep", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


def test_native_listing_exposes_why_a_model_is_unavailable():
    client, _, _ = build()

    by_id = {m["id"]: m for m in client.get("/lyren/v1/models", headers=ANA).json()["models"]}

    assert by_id["google.gemini-2.5-flash"]["availability"] == "quota_zero"
    assert by_id["openai.gpt-oss-120b"]["availability"] == "not_found"


def test_a_non_streaming_provider_refuses_a_streamed_request_up_front():
    """Streaming now exists, but a provider that cannot do it says so before any byte is sent."""
    client, _, _ = build()

    response = client.post(
        "/v1/chat/completions",
        headers=ANA,
        json={
            "model": "lyren/fast",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
    )

    assert response.status_code == 502
    assert "does not support streaming" in response.json()["error"]["message"]


def test_chat_returns_an_openai_shaped_completion_attributed_to_its_principal():
    client, _, _ = build()

    body = client.post(
        "/v1/chat/completions",
        headers=ANA,
        json={"model": "lyren/fast", "messages": [{"role": "user", "content": "ping"}]},
    ).json()

    assert body["object"] == "chat.completion"
    assert body["model"] == "meta.llama-4-scout-17b-16e-instruct"
    assert body["choices"][0]["message"] == {"role": "assistant", "content": "pong"}
    assert body["usage"]["total_tokens"] == 4
    assert body["lyren"]["principal"] == "ana"


def test_a_principal_over_its_rate_limit_is_refused_without_reaching_a_provider():
    provider = StubProvider()
    client, _, _ = build(provider=provider, store=_store(Quota(requests_per_minute=1)))
    payload = {"model": "lyren/fast", "messages": [{"role": "user", "content": "ping"}]}

    assert client.post("/v1/chat/completions", headers=ANA, json=payload).status_code == 200
    second = client.post("/v1/chat/completions", headers=ANA, json=payload)

    assert second.status_code == 429
    assert second.json()["error"]["code"] == "quota_exceeded"
    assert len(provider.seen) == 1


def test_one_principal_exhausting_its_quota_does_not_block_another():
    client, _, _ = build(store=_store(Quota(requests_per_minute=1)))
    payload = {"model": "lyren/fast", "messages": [{"role": "user", "content": "ping"}]}

    client.post("/v1/chat/completions", headers=ANA, json=payload)

    assert client.post("/v1/chat/completions", headers=ANA, json=payload).status_code == 429
    assert client.post("/v1/chat/completions", headers=BRUNO, json=payload).status_code == 200


def test_the_principal_quota_caps_output_below_the_alias_budget():
    captured = {}

    class Capturing(StubProvider):
        def chat(self, spec, request):
            captured["max_output_tokens"] = request.max_output_tokens
            return super().chat(spec, request)

    client, _, _ = build(provider=Capturing(), store=_store(Quota(max_output_tokens=128)))
    client.post(
        "/v1/chat/completions",
        headers=ANA,
        json={
            "model": "lyren/deep",
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 9000,
        },
    )

    assert captured["max_output_tokens"] == 128


def test_alias_falls_back_to_the_next_candidate_and_records_the_verdict():
    provider = StubProvider(fail_for={"cohere.command-a-03-2025"})
    client, registry, _ = build(provider=provider)

    body = client.post(
        "/v1/chat/completions",
        headers=ANA,
        json={"model": "lyren/deep", "messages": [{"role": "user", "content": "ping"}]},
    ).json()

    assert body["model"] == "meta.llama-3.3-70b-instruct"
    assert provider.seen == ["cohere.command-a-03-2025", "meta.llama-3.3-70b-instruct"]
    assert registry.spec("cohere.command-a-03-2025").availability is Availability.NOT_FOUND


def test_request_id_is_echoed_back():
    client, _, _ = build()

    response = client.get("/healthz", headers={"x-request-id": "req_fixed"})

    assert response.headers["x-request-id"] == "req_fixed"


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_the_dev_auth_shortcut_is_refused_outside_a_local_environment(environment, monkeypatch):
    from lyren_api.deps import get_principal_store

    get_principal_store.cache_clear()
    monkeypatch.setenv("LYREN_ENVIRONMENT", environment)
    monkeypatch.setenv("LYREN_API_KEY_HASHES", hash_key("k"))
    monkeypatch.delenv("LYREN_PRINCIPALS_FILE", raising=False)
    from lyren_api.deps import get_settings

    get_settings.cache_clear()

    with pytest.raises(Exception, match="development shortcut"):
        get_principal_store()

    get_settings.cache_clear()
    get_principal_store.cache_clear()
