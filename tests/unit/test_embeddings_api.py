from datetime import date

from fastapi.testclient import TestClient

from lyren_api.deps import (
    get_chat_provider,
    get_principal_store,
    get_registry,
    get_settings,
    get_usage_meter,
)
from lyren_api.main import create_app
from lyren_core.identity import ApiKeyRecord, Principal, PrincipalStore, Quota, hash_key
from lyren_core.metering import UsageMeter
from lyren_core.settings import Settings
from lyren_inference.ports import EmbedResponse, Usage
from lyren_inference.registry import ModelRegistry

ANA_KEY = "ana-key"
BRUNO_KEY = "bruno-key"
ANA = {"Authorization": f"Bearer {ANA_KEY}"}
BRUNO = {"Authorization": f"Bearer {BRUNO_KEY}"}


class EmbedStub:
    name = "stub"

    def __init__(self):
        self.requests = []

    def chat(self, spec, request):
        raise AssertionError("chat should not be reached from the embeddings route")

    def embed(self, spec, request):
        self.requests.append(request)
        return EmbedResponse(
            model_id=spec.id,
            vectors=tuple((0.1, 0.2, 0.3) for _ in request.inputs),
            usage=Usage(prompt_tokens=7),
        )


class ChatOnlyStub:
    name = "chat-only"

    def chat(self, spec, request):
        raise AssertionError("not reached")


def build(provider=None, quota=None):
    ana = Principal(id="ana", name="Ana", quota=quota or Quota())
    bruno = Principal(id="bruno", name="Bruno", allowed_models=frozenset({"lyren/fast"}))
    store = PrincipalStore(
        (ana, bruno),
        (
            ApiKeyRecord(hash_key(ANA_KEY), "ana", "k", date(2026, 11, 24)),
            ApiKeyRecord(hash_key(BRUNO_KEY), "bruno", "k", date(2026, 11, 24)),
        ),
    )
    provider = provider if provider is not None else EmbedStub()
    meter = UsageMeter()
    registry = ModelRegistry()

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(oci_enabled=False)
    app.dependency_overrides[get_registry] = lambda: registry
    app.dependency_overrides[get_chat_provider] = lambda: provider
    app.dependency_overrides[get_principal_store] = lambda: store
    app.dependency_overrides[get_usage_meter] = lambda: meter
    return TestClient(app, raise_server_exceptions=False), provider, meter


def test_embeddings_requires_a_bearer_key():
    client, _, _ = build()

    assert (
        client.post("/v1/embeddings", json={"model": "lyren/embed", "input": "x"}).status_code
        == 401
    )


def test_a_single_string_returns_one_vector_in_openai_shape():
    client, _, _ = build()

    body = client.post(
        "/v1/embeddings", headers=ANA, json={"model": "lyren/embed", "input": "ping"}
    ).json()

    assert body["object"] == "list"
    assert len(body["data"]) == 1
    assert body["data"][0] == {"object": "embedding", "index": 0, "embedding": [0.1, 0.2, 0.3]}
    assert body["model"] == "cohere.embed-v4.0"
    assert body["usage"]["total_tokens"] == 7
    assert body["lyren"]["dimensions"] == 3


def test_a_list_returns_one_vector_per_input_in_order():
    client, _, _ = build()

    body = client.post(
        "/v1/embeddings", headers=ANA, json={"model": "lyren/embed", "input": ["a", "b", "c"]}
    ).json()

    assert [entry["index"] for entry in body["data"]] == [0, 1, 2]


def test_the_input_type_defaults_to_document_and_is_reported_back():
    client, provider, _ = build()

    body = client.post(
        "/v1/embeddings", headers=ANA, json={"model": "lyren/embed", "input": "ping"}
    ).json()

    assert str(provider.requests[0].input_type) == "SEARCH_DOCUMENT"
    assert body["lyren"]["input_type"] == "SEARCH_DOCUMENT"


def test_a_query_input_type_reaches_the_provider():
    client, provider, _ = build()

    client.post(
        "/v1/embeddings",
        headers=ANA,
        json={"model": "lyren/embed", "input": "ping", "input_type": "SEARCH_QUERY"},
    )

    assert str(provider.requests[0].input_type) == "SEARCH_QUERY"


def test_a_chat_model_is_refused_on_the_embeddings_route():
    client, _, _ = build()

    response = client.post(
        "/v1/embeddings", headers=ANA, json={"model": "lyren/fast", "input": "ping"}
    )

    assert response.status_code == 502
    assert "not an embedding model" in response.json()["error"]["message"]


def test_a_provider_without_embeddings_is_refused_rather_than_crashing():
    client, _, _ = build(provider=ChatOnlyStub())

    response = client.post(
        "/v1/embeddings", headers=ANA, json={"model": "lyren/embed", "input": "ping"}
    )

    assert response.status_code == 502
    assert "does not serve embeddings" in response.json()["error"]["message"]


def test_an_empty_input_is_refused():
    client, _, _ = build()

    response = client.post(
        "/v1/embeddings", headers=ANA, json={"model": "lyren/embed", "input": "   "}
    )

    assert response.status_code == 502
    assert "empty input" in response.json()["error"]["message"]


def test_too_many_inputs_are_rejected_at_the_boundary():
    client, _, _ = build()

    response = client.post(
        "/v1/embeddings", headers=ANA, json={"model": "lyren/embed", "input": ["x"] * 97}
    )

    assert response.status_code == 422


def test_a_principal_not_permitted_to_use_the_model_is_refused():
    client, _, _ = build()

    response = client.post(
        "/v1/embeddings", headers=BRUNO, json={"model": "lyren/embed", "input": "ping"}
    )

    assert response.status_code == 403


def test_embeddings_count_against_the_principal_quota():
    client, provider, _ = build(quota=Quota(requests_per_minute=1))
    payload = {"model": "lyren/embed", "input": "ping"}

    assert client.post("/v1/embeddings", headers=ANA, json=payload).status_code == 200
    second = client.post("/v1/embeddings", headers=ANA, json=payload)

    assert second.status_code == 429
    assert len(provider.requests) == 1
