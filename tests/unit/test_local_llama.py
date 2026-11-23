import json
import re

import httpx
import pytest

from lyren_core.errors import ProviderError
from lyren_inference.ports import (
    ApiFormat,
    Availability,
    Capability,
    ChatRequest,
    Message,
    ModelSpec,
    Role,
)
from lyren_inference.providers.local_llama import LocalLlamaProvider

SPEC = ModelSpec(
    id="local/llama-cpp",
    vendor="local",
    provider="local_llama_cpp",
    api_format=ApiFormat.GENERIC,
    pinned_version="server-declared",
    capabilities=frozenset({Capability.CHAT}),
    availability=Availability.VERIFIED,
    bills=False,
)
REQUEST = ChatRequest(messages=(Message(role=Role.USER, content="ping"),), max_output_tokens=8)


def provider_with(handler):
    return LocalLlamaProvider(
        "http://127.0.0.1:8080", client=httpx.Client(transport=httpx.MockTransport(handler))
    )


def test_probe_verifies_a_healthy_server():
    provider = provider_with(lambda request: httpx.Response(200, json={"status": "ok"}))

    assert provider.probe() is Availability.VERIFIED


def test_probe_rejects_a_server_that_is_not_ready():
    provider = provider_with(lambda request: httpx.Response(503, text="loading model"))

    assert provider.probe() is Availability.NOT_FOUND


def test_probe_rejects_an_unreachable_server():
    def refuse(request):
        raise httpx.ConnectError("connection refused", request=request)

    assert provider_with(refuse).probe() is Availability.NOT_FOUND


def test_chat_parses_an_openai_shaped_reply():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "pong"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 4, "completion_tokens": 1},
            },
        )

    response = provider_with(handler).chat(SPEC, REQUEST)

    assert (response.text, response.finish_reason) == ("pong", "stop")
    assert response.usage.total_tokens == 5
    assert response.model_id == "local/llama-cpp"


def test_chat_sends_the_request_without_streaming_and_with_the_token_budget():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}
        )

    stop_request = ChatRequest(
        messages=(
            Message(role=Role.SYSTEM, content="be terse"),
            Message(role=Role.USER, content="hi"),
        ),
        max_output_tokens=8,
        stop=("END",),
    )
    provider_with(handler).chat(SPEC, stop_request)

    assert seen["stream"] is False
    assert seen["max_tokens"] == 8
    assert seen["stop"] == ["END"]
    assert [m["role"] for m in seen["messages"]] == ["system", "user"]


def test_a_loading_server_is_reported_as_such():
    provider = provider_with(lambda request: httpx.Response(503, text="loading model"))

    with pytest.raises(ProviderError, match="still loading"):
        provider.chat(SPEC, REQUEST)


def test_an_unreachable_server_is_reported_with_its_address():
    def refuse(request):
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(ProviderError, match=re.escape("127.0.0.1:8080")):
        provider_with(refuse).chat(SPEC, REQUEST)


def test_an_empty_choice_list_is_an_error_rather_than_an_empty_answer():
    provider = provider_with(lambda request: httpx.Response(200, json={"choices": []}))

    with pytest.raises(ProviderError, match="no choices"):
        provider.chat(SPEC, REQUEST)


def test_an_unsupported_role_is_refused_instead_of_dropped():
    provider = provider_with(lambda request: httpx.Response(200, json={"choices": []}))
    tool_request = ChatRequest(messages=(Message(role=Role.TOOL, content="x"),))

    with pytest.raises(ProviderError, match="not supported"):
        provider.chat(SPEC, tool_request)


def _sse(lines):
    def handler(request):
        return httpx.Response(
            200,
            content="".join(f"data: {line}\n\n" for line in lines),
            headers={"content-type": "text/event-stream"},
        )

    return handler


def test_streaming_reassembles_deltas_and_reports_the_finish_reason():
    lines = [
        '{"choices":[{"delta":{"content":"po"},"finish_reason":null}]}',
        '{"choices":[{"delta":{"content":"ng"},"finish_reason":null}]}',
        '{"choices":[{"delta":{},"finish_reason":"stop"}]}',
        "[DONE]",
    ]

    chunks = list(provider_with(_sse(lines)).stream_chat(SPEC, REQUEST))

    assert "".join(c.text for c in chunks) == "pong"
    assert [c.finish_reason for c in chunks if c.finish_reason] == ["stop"]


def test_streaming_stops_at_the_done_sentinel():
    lines = [
        '{"choices":[{"delta":{"content":"a"}}]}',
        "[DONE]",
        '{"choices":[{"delta":{"content":"b"}}]}',
    ]

    chunks = list(provider_with(_sse(lines)).stream_chat(SPEC, REQUEST))

    assert "".join(c.text for c in chunks) == "a"


def test_streaming_skips_an_unparseable_line():
    lines = ["not json", '{"choices":[{"delta":{"content":"ok"}}]}', "[DONE]"]

    chunks = list(provider_with(_sse(lines)).stream_chat(SPEC, REQUEST))

    assert "".join(c.text for c in chunks) == "ok"


def test_a_streaming_error_status_is_reported_before_any_chunk():
    provider = provider_with(lambda request: httpx.Response(500, text="boom"))

    with pytest.raises(ProviderError, match="returned 500"):
        list(provider.stream_chat(SPEC, REQUEST))
