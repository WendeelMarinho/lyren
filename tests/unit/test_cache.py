import dataclasses

import pytest

from lyren_core.errors import CacheMissError
from lyren_core.settings import CacheMode
from lyren_inference.cache import CachingProvider, CassetteStore, cache_key
from lyren_inference.ports import (
    ApiFormat,
    Availability,
    Capability,
    ChatRequest,
    ChatResponse,
    Message,
    ModelSpec,
    Role,
    Usage,
)

SPEC = ModelSpec(
    id="meta.llama-3.3-70b-instruct",
    vendor="meta",
    provider="oci_generative_ai",
    api_format=ApiFormat.GENERIC,
    pinned_version="1.0.0",
    capabilities=frozenset({Capability.CHAT}),
    availability=Availability.VERIFIED,
)
REQUEST = ChatRequest(messages=(Message(role=Role.USER, content="ping"),), max_output_tokens=5)


class CountingProvider:
    name = "counting"

    def __init__(self):
        self.calls = 0

    def chat(self, spec, request):
        self.calls += 1
        return ChatResponse(
            model_id=spec.id,
            text=f"pong {self.calls}",
            finish_reason="stop",
            usage=Usage(prompt_tokens=1, completion_tokens=2),
        )


def test_key_is_stable_across_equal_requests():
    assert cache_key(SPEC, REQUEST) == cache_key(SPEC, REQUEST)


def test_key_changes_when_the_pin_moves():
    repinned = dataclasses.replace(SPEC, pinned_version="2.0.0")

    assert cache_key(SPEC, REQUEST) != cache_key(repinned, REQUEST)


def test_key_changes_with_message_content():
    other = ChatRequest(messages=(Message(role=Role.USER, content="pong"),), max_output_tokens=5)

    assert cache_key(SPEC, REQUEST) != cache_key(SPEC, other)


def test_auto_mode_calls_once_then_replays(tmp_path):
    inner = CountingProvider()
    provider = CachingProvider(inner, CassetteStore(tmp_path), CacheMode.AUTO)

    first = provider.chat(SPEC, REQUEST)
    second = provider.chat(SPEC, REQUEST)

    assert inner.calls == 1
    assert first.from_cache is False
    assert second.from_cache is True
    assert second.text == first.text
    assert second.usage.total_tokens == 3


def test_replay_mode_refuses_to_call_the_provider(tmp_path):
    inner = CountingProvider()
    provider = CachingProvider(inner, CassetteStore(tmp_path), CacheMode.REPLAY)

    with pytest.raises(CacheMissError):
        provider.chat(SPEC, REQUEST)
    assert inner.calls == 0


def test_record_mode_always_hits_the_provider(tmp_path):
    inner = CountingProvider()
    provider = CachingProvider(inner, CassetteStore(tmp_path), CacheMode.RECORD)

    provider.chat(SPEC, REQUEST)
    second = provider.chat(SPEC, REQUEST)

    assert inner.calls == 2
    assert second.from_cache is False


def test_off_mode_neither_reads_nor_writes(tmp_path):
    inner = CountingProvider()
    provider = CachingProvider(inner, CassetteStore(tmp_path), CacheMode.OFF)

    provider.chat(SPEC, REQUEST)
    provider.chat(SPEC, REQUEST)

    assert inner.calls == 2
    assert not list(tmp_path.rglob("*.json"))


def test_repeated_attempts_do_not_collapse_into_one_cassette(tmp_path):
    inner = CountingProvider()
    provider = CachingProvider(inner, CassetteStore(tmp_path), CacheMode.AUTO)
    second_attempt = dataclasses.replace(REQUEST, attempt=1)

    first = provider.chat(SPEC, REQUEST)
    second = provider.chat(SPEC, second_attempt)

    assert inner.calls == 2
    assert second.from_cache is False
    assert first.text != second.text
    assert provider.chat(SPEC, second_attempt).from_cache is True


def test_attempt_index_changes_the_key():
    assert cache_key(SPEC, REQUEST) != cache_key(SPEC, dataclasses.replace(REQUEST, attempt=1))


def test_embeddings_are_cached_by_input_type_and_text(tmp_path):
    from lyren_inference.ports import EmbedInputType, EmbedRequest, EmbedResponse

    class CountingEmbedder:
        name = "embedder"

        def __init__(self):
            self.calls = 0

        def chat(self, spec, request):
            raise AssertionError("not reached")

        def embed(self, spec, request):
            self.calls += 1
            return EmbedResponse(model_id=spec.id, vectors=((float(self.calls), 0.5),))

    inner = CountingEmbedder()
    provider = CachingProvider(inner, CassetteStore(tmp_path), CacheMode.AUTO)
    as_document = EmbedRequest(inputs=("ping",), input_type=EmbedInputType.SEARCH_DOCUMENT)
    as_query = EmbedRequest(inputs=("ping",), input_type=EmbedInputType.SEARCH_QUERY)

    first = provider.embed(SPEC, as_document)
    again = provider.embed(SPEC, as_document)
    other = provider.embed(SPEC, as_query)

    assert inner.calls == 2
    assert again.vectors == first.vectors
    assert other.vectors != first.vectors


def test_replay_mode_refuses_to_embed_without_a_cassette(tmp_path):
    from lyren_inference.ports import EmbedInputType, EmbedRequest

    class NeverCalled:
        name = "never"

        def chat(self, spec, request):
            raise AssertionError("not reached")

        def embed(self, spec, request):
            raise AssertionError("not reached")

    provider = CachingProvider(NeverCalled(), CassetteStore(tmp_path), CacheMode.REPLAY)

    with pytest.raises(CacheMissError):
        provider.embed(
            SPEC, EmbedRequest(inputs=("ping",), input_type=EmbedInputType.SEARCH_DOCUMENT)
        )


def test_a_chat_only_provider_cannot_be_asked_to_embed(tmp_path):
    from lyren_core.errors import ProviderError
    from lyren_inference.ports import EmbedInputType, EmbedRequest

    provider = CachingProvider(CountingProvider(), CassetteStore(tmp_path), CacheMode.AUTO)

    with pytest.raises(ProviderError, match="does not serve embeddings"):
        provider.embed(
            SPEC, EmbedRequest(inputs=("ping",), input_type=EmbedInputType.SEARCH_DOCUMENT)
        )
