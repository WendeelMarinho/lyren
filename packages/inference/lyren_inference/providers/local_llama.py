"""Chat against a local llama.cpp server.

The reason to have this is not only cost. It is the only provider that keeps prompt content on our
own host, which matters once the platform holds other people's data: everything sent to an
OCI-backed alias is processed by Oracle as a third party.

The server is assumed to expose llama.cpp's OpenAI-compatible endpoint. Which GGUF is loaded is
declared in configuration rather than inferred, because the server will happily answer for whatever
it has and silently attributing a benchmark to the wrong model is worse than refusing to guess.
"""

from __future__ import annotations

from typing import Any

import httpx

from lyren_core.errors import ProviderError
from lyren_inference.ports import (
    Availability,
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

    def chat(self, spec: ModelSpec, request: ChatRequest) -> ChatResponse:
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
