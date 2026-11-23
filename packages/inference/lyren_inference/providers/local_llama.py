"""Chat against a local llama.cpp server.

The reason to have this is not only cost. It is the only provider that keeps prompt content on our
own host, which matters once the platform holds other people's data: everything sent to an
OCI-backed alias is processed by Oracle as a third party.

The server is assumed to expose llama.cpp's OpenAI-compatible endpoint. Which GGUF is loaded is
declared in configuration rather than inferred, because the server will happily answer for whatever
it has and silently attributing a benchmark to the wrong model is worse than refusing to guess.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx

from lyren_core.errors import ProviderError
from lyren_inference.ports import (
    Availability,
    ChatChunk,
    ChatRequest,
    ChatResponse,
    ModelSpec,
    Role,
    Usage,
)

_ROLES = {Role.SYSTEM: "system", Role.USER: "user", Role.ASSISTANT: "assistant"}


class LocalLlamaProvider:
    name = "local_llama_cpp"

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 300.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._client = client or httpx.Client(timeout=timeout_seconds)

    def probe(self) -> Availability:
        """Whether the server is up and holding a model. Availability is never assumed."""
        try:
            response = self._client.get(f"{self._base_url}/health")
        except httpx.HTTPError:
            return Availability.NOT_FOUND
        if response.status_code != 200:
            return Availability.NOT_FOUND
        return Availability.VERIFIED

    @staticmethod
    def _payload(request: ChatRequest) -> dict[str, Any]:
        messages = []
        for message in request.messages:
            role = _ROLES.get(message.role)
            if role is None:
                raise ProviderError(f"role {message.role} is not supported by the local provider")
            messages.append({"role": role, "content": message.content})

        payload: dict[str, Any] = {
            "messages": messages,
            "max_tokens": request.max_output_tokens,
            "temperature": request.temperature,
            "stream": False,
        }
        if request.stop:
            payload["stop"] = list(request.stop)
        return payload

    def chat(self, spec: ModelSpec, request: ChatRequest) -> ChatResponse:
        payload = self._payload(request)

        try:
            response = self._client.post(f"{self._base_url}/v1/chat/completions", json=payload)
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"the local llama.cpp server at {self._base_url} is unreachable",
                detail=str(exc),
            ) from exc

        if response.status_code == 503:
            raise ProviderError(
                "the local llama.cpp server is still loading a model", detail=response.text[:200]
            )
        if response.status_code >= 400:
            raise ProviderError(
                f"the local llama.cpp server returned {response.status_code}",
                detail=response.text[:200],
            )

        return self._to_response(spec, response.json())

    def stream_chat(self, spec: ModelSpec, request: ChatRequest) -> Iterator[ChatChunk]:
        payload = self._payload(request)
        payload["stream"] = True
        try:
            with self._client.stream(
                "POST", f"{self._base_url}/v1/chat/completions", json=payload
            ) as response:
                if response.status_code >= 400:
                    response.read()
                    raise ProviderError(
                        f"the local llama.cpp server returned {response.status_code}",
                        detail=response.text[:200],
                    )
                for line in response.iter_lines():
                    chunk = _chunk_from_sse_line(line)
                    if chunk is _DONE:
                        return
                    if chunk is not None:
                        yield chunk
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"the local llama.cpp server at {self._base_url} is unreachable", detail=str(exc)
            ) from exc

    @staticmethod
    def _to_response(spec: ModelSpec, body: dict[str, Any]) -> ChatResponse:
        choices = body.get("choices") or []
        if not choices:
            raise ProviderError(f"{spec.id} returned no choices")
        first = choices[0]
        usage = body.get("usage") or {}
        return ChatResponse(
            model_id=spec.id,
            text=str((first.get("message") or {}).get("content") or ""),
            finish_reason=str(first.get("finish_reason") or "stop"),
            usage=Usage(
                prompt_tokens=usage.get("prompt_tokens"),
                completion_tokens=usage.get("completion_tokens"),
            ),
        )


_DONE = ChatChunk(text="\x00done")
"""Sentinel: the stream's terminator is distinct from an empty delta."""


def _chunk_from_sse_line(line: str) -> ChatChunk | None:
    if not line.startswith("data:"):
        return None
    payload = line[5:].strip()
    if payload == "[DONE]":
        return _DONE
    try:
        body = json.loads(payload)
    except json.JSONDecodeError:
        return None
    choices = body.get("choices") or []
    if not choices:
        return None
    delta = choices[0].get("delta") or {}
    text = str(delta.get("content") or "")
    finish_reason = choices[0].get("finish_reason")
    if not text and finish_reason is None:
        return None
    return ChatChunk(text=text, finish_reason=finish_reason)
