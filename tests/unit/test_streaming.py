import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from lyren_api.deps import (
    get_chat_provider,
    get_principal_store,
    get_registry,
    get_settings,
    get_usage_meter,
)
from lyren_api.main import create_app
from lyren_core.errors import ModelNotAvailableError, ProviderError
from lyren_core.identity import ApiKeyRecord, Principal, PrincipalStore, Quota, hash_key
from lyren_core.metering import UsageMeter
from lyren_core.settings import CacheMode, Settings
from lyren_inference.cache import CachingProvider, CassetteStore
from lyren_inference.ports import (
    ApiFormat,
    Availability,
    Capability,
    ChatChunk,
    ChatRequest,
    ChatResponse,
    Message,
    ModelSpec,
    Role,
    Usage,
)
from lyren_inference.registry import ModelRegistry

KEY = "ana-key"
AUTH = {"Authorization": f"Bearer {KEY}"}
SPEC = ModelSpec(
    id="m",
    vendor="v",
    provider="p",
    api_format=ApiFormat.GENERIC,
    pinned_version="1",
    capabilities=frozenset({Capability.CHAT}),
    availability=Availability.VERIFIED,
)
REQUEST = ChatRequest(messages=(Message(role=Role.USER, content="ping"),))


class StreamStub:
    name = "stream-stub"

    def __init__(self, script=None, fail_for=None, fail_after=None):
        self.script = script or ["po", "ng"]
        self.fail_for = set(fail_for or ())
        self.fail_after = fail_after
        self.seen = []
        self.consumed = 0

    def chat(self, spec, request):
        return ChatResponse(model_id=spec.id, text="".join(self.script), finish_reason="stop")

    def stream_chat(self, spec, request):
        self.seen.append(spec.id)
        if spec.id in self.fail_for:
            raise ModelNotAvailableError(f"{spec.id} is gone")
        for index, piece in enumerate(self.script):
            if self.fail_after is not None and index == self.fail_after:
                raise ProviderError("upstream died mid-answer")
            self.consumed += 1
            yield ChatChunk(text=piece)
        yield ChatChunk(finish_reason="stop", usage=Usage(prompt_tokens=3, completion_tokens=2))


class NotStreaming:
    name = "plain"

    def chat(self, spec, request):
        return ChatResponse(model_id=spec.id, text="pong", finish_reason="stop")


def build(provider, quota=None):
    ana = Principal(id="ana", name="Ana", quota=quota or Quota())
    store = PrincipalStore((ana,), (ApiKeyRecord(hash_key(KEY), "ana", "k", date(2026, 11, 24)),))
    meter = UsageMeter()
    registry = ModelRegistry()
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(oci_enabled=False)
    app.dependency_overrides[get_registry] = lambda: registry
    app.dependency_overrides[get_chat_provider] = lambda: provider
    app.dependency_overrides[get_principal_store] = lambda: store
    app.dependency_overrides[get_usage_meter] = lambda: meter
    return TestClient(app, raise_server_exceptions=False), meter, registry


def frames(text):
    out = []
    for line in text.splitlines():
        if not line.startswith("data: "):
            continue
        payload = line[6:]
        out.append("[DONE]" if payload == "[DONE]" else json.loads(payload))
    return out


def post_stream(client, model="lyren/fast"):
    return client.post(
        "/v1/chat/completions",
        headers=AUTH,
        json={"model": model, "messages": [{"role": "user", "content": "ping"}], "stream": True},
    )


def test_a_stream_opens_with_a_role_delta_and_closes_with_done():
    client, _, _ = build(StreamStub())

    response = post_stream(client)
    received = frames(response.text)

    assert response.headers["content-type"].startswith("text/event-stream")
    assert received[0]["choices"][0]["delta"] == {"role": "assistant"}
    assert received[-1] == "[DONE]"


def test_the_content_deltas_reassemble_into_the_answer():
    client, _, _ = build(StreamStub(script=["po", "ng", "!"]))

    received = [f for f in frames(post_stream(client).text) if f != "[DONE]"]
    text = "".join(f["choices"][0]["delta"].get("content", "") for f in received)

    assert text == "pong!"


def test_the_finish_reason_arrives_on_its_own_frame():
    client, _, _ = build(StreamStub())

    received = [f for f in frames(post_stream(client).text) if f != "[DONE]"]
    finishes = [f["choices"][0]["finish_reason"] for f in received]

    assert finishes[-1] == "stop"
    assert all(f is None for f in finishes[:-1])


def test_a_stream_counts_against_the_quota():
    client, meter, _ = build(StreamStub())

    post_stream(client)

    assert meter.usage_for("ana").calls_today == 1


def test_a_client_that_disconnects_still_spends_its_quota():
    client, meter, _ = build(StreamStub(script=["a"] * 50))

    with client.stream(
        "POST",
        "/v1/chat/completions",
        headers=AUTH,
        json={
            "model": "lyren/fast",
            "messages": [{"role": "user", "content": "ping"}],
            "stream": True,
        },
    ) as response:
        next(response.iter_lines())

    assert meter.usage_for("ana").calls_today == 1


def test_a_failure_after_the_first_byte_becomes_an_error_frame_not_a_status():
    client, _, _ = build(StreamStub(script=["po", "ng"], fail_after=1))

    response = post_stream(client)
    received = frames(response.text)

    assert response.status_code == 200
    assert any(isinstance(f, dict) and "error" in f for f in received)
    assert received[-1] == "[DONE]"


def test_a_failure_before_the_first_chunk_falls_back_to_the_next_candidate():
    stub = StreamStub(fail_for={"cohere.command-a-03-2025"})
    client, _, registry = build(stub)

    received = [f for f in frames(post_stream(client, "lyren/deep").text) if f != "[DONE]"]

    assert stub.seen == ["cohere.command-a-03-2025", "meta.llama-3.3-70b-instruct"]
    assert received[-1]["model"] == "meta.llama-3.3-70b-instruct"
    assert registry.spec("cohere.command-a-03-2025").availability is Availability.NOT_FOUND


def test_a_provider_without_streaming_is_refused_before_the_response_starts():
    client, _, _ = build(NotStreaming())

    response = post_stream(client)

    assert response.status_code == 502
    assert "does not support streaming" in response.json()["error"]["message"]


def test_a_streamed_answer_is_recorded_and_replayed_as_one_chunk(tmp_path):
    inner = StreamStub(script=["po", "ng"])
    provider = CachingProvider(inner, CassetteStore(tmp_path), CacheMode.AUTO)

    first = list(provider.stream_chat(SPEC, REQUEST))
    replayed = list(provider.stream_chat(SPEC, REQUEST))

    assert "".join(c.text for c in first) == "pong"
    assert len(replayed) == 1
    assert replayed[0].text == "pong"
    assert replayed[0].finish_reason == "stop"


def test_a_cancelled_stream_is_not_recorded(tmp_path):
    inner = StreamStub(script=["po", "ng"])
    provider = CachingProvider(inner, CassetteStore(tmp_path), CacheMode.AUTO)

    stream = provider.stream_chat(SPEC, REQUEST)
    next(stream)
    stream.close()

    assert not list(tmp_path.rglob("*.json"))


def test_a_replayed_stream_shares_its_cassette_with_a_non_streamed_call(tmp_path):
    inner = StreamStub(script=["po", "ng"])
    provider = CachingProvider(inner, CassetteStore(tmp_path), CacheMode.AUTO)

    list(provider.stream_chat(SPEC, REQUEST))
    plain = provider.chat(SPEC, REQUEST)

    assert plain.from_cache is True
    assert plain.text == "pong"


def test_streaming_is_refused_when_the_provider_cannot_stream(tmp_path):
    provider = CachingProvider(NotStreaming(), CassetteStore(tmp_path), CacheMode.AUTO)

    with pytest.raises(ProviderError, match="does not support streaming"):
        list(provider.stream_chat(SPEC, REQUEST))
