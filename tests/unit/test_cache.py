import dataclasses

import pytest

from lyren_core.errors import CacheMissError
from lyren_core.settings import CacheMode
from lyren_inference.cache import CachingChatProvider, CassetteStore, cache_key
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
    provider = CachingChatProvider(inner, CassetteStore(tmp_path), CacheMode.AUTO)

    first = provider.chat(SPEC, REQUEST)
    second = provider.chat(SPEC, REQUEST)

    assert inner.calls == 1
    assert first.from_cache is False
    assert second.from_cache is True
    assert second.text == first.text
    assert second.usage.total_tokens == 3


def test_replay_mode_refuses_to_call_the_provider(tmp_path):
    inner = CountingProvider()
    provider = CachingChatProvider(inner, CassetteStore(tmp_path), CacheMode.REPLAY)

    with pytest.raises(CacheMissError):
        provider.chat(SPEC, REQUEST)
    assert inner.calls == 0


def test_record_mode_always_hits_the_provider(tmp_path):
    inner = CountingProvider()
    provider = CachingChatProvider(inner, CassetteStore(tmp_path), CacheMode.RECORD)

    provider.chat(SPEC, REQUEST)
    second = provider.chat(SPEC, REQUEST)

    assert inner.calls == 2
    assert second.from_cache is False


def test_off_mode_neither_reads_nor_writes(tmp_path):
    inner = CountingProvider()
    provider = CachingChatProvider(inner, CassetteStore(tmp_path), CacheMode.OFF)

    provider.chat(SPEC, REQUEST)
    provider.chat(SPEC, REQUEST)

    assert inner.calls == 2
    assert not list(tmp_path.rglob("*.json"))
