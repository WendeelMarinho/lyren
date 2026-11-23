"""Record/replay cache for model calls.

Without deterministic replay no experiment is reproducible and no CI is affordable, so the cache is
infrastructure rather than an optimisation. The key covers the pinned model version: refreshing a
pin invalidates its cassettes instead of silently reusing another model's answers.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path
from typing import Any

from lyren_core.errors import CacheMissError, ProviderError
from lyren_core.settings import CacheMode
from lyren_inference.ports import (
    ChatProvider,
    ChatRequest,
    ChatResponse,
    EmbeddingProvider,
    EmbedRequest,
    EmbedResponse,
    ModelSpec,
    Usage,
)


def _digest(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def cache_key(spec: ModelSpec, request: ChatRequest) -> str:
    payload = {
        "provider": spec.provider,
        "model_id": spec.id,
        "pinned_version": spec.pinned_version,
        "api_format": str(spec.api_format),
        "messages": [[str(m.role), m.content] for m in request.messages],
        "max_output_tokens": request.max_output_tokens,
        "temperature": request.temperature,
        "stop": list(request.stop),
        "attempt": request.attempt,
    }
    return _digest(payload)


def embed_cache_key(spec: ModelSpec, request: EmbedRequest) -> str:
    return _digest(
        {
            "kind": "embed",
            "provider": spec.provider,
            "model_id": spec.id,
            "pinned_version": spec.pinned_version,
            "input_type": str(request.input_type),
            "inputs": list(request.inputs),
        }
    )


class CassetteStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    def _path(self, key: str) -> Path:
        return self._root / key[:2] / f"{key}.json"

    def get(self, key: str) -> ChatResponse | None:
        path = self._path(key)
        if not path.is_file():
            return None
        raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        usage = raw.get("usage") or {}
        return ChatResponse(
            model_id=raw["model_id"],
            text=raw["text"],
            finish_reason=raw["finish_reason"],
            usage=Usage(
                prompt_tokens=usage.get("prompt_tokens"),
                completion_tokens=usage.get("completion_tokens"),
            ),
            from_cache=True,
        )

    def get_embed(self, key: str) -> EmbedResponse | None:
        path = self._path(key)
        if not path.is_file():
            return None
        raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return EmbedResponse(
            model_id=raw["model_id"],
            vectors=tuple(tuple(float(v) for v in row) for row in raw["vectors"]),
        )

    def put_embed(self, key: str, response: EmbedResponse) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"model_id": response.model_id, "vectors": [list(v) for v in response.vectors]},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def put(self, key: str, response: ChatResponse) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "model_id": response.model_id,
            "text": response.text,
            "finish_reason": response.finish_reason,
            "usage": dataclasses.asdict(response.usage),
        }
        path.write_text(
            json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
        )


class CachingProvider:
    """Caches chat and embeddings alike: both are deterministic inputs to an experiment."""

    def __init__(self, inner: ChatProvider, store: CassetteStore, mode: CacheMode) -> None:
        self._inner = inner
        self._store = store
        self._mode = mode
        self.name = f"cached:{inner.name}"

    def inner_providers(self) -> tuple[str, ...]:
        """What the wrapped provider actually serves, for readiness reporting."""
        inner = getattr(self._inner, "providers", None)
        return inner() if callable(inner) else (self._inner.name,)

    def chat(self, spec: ModelSpec, request: ChatRequest) -> ChatResponse:
        if self._mode is CacheMode.OFF:
            return self._inner.chat(spec, request)

        key = cache_key(spec, request)

        if self._mode is not CacheMode.RECORD:
            hit = self._store.get(key)
            if hit is not None:
                return hit
            if self._mode is CacheMode.REPLAY:
                raise CacheMissError(f"no cassette for {spec.id} (key {key[:12]})")

        response = self._inner.chat(spec, request)
        self._store.put(key, response)
        return response

    def embed(self, spec: ModelSpec, request: EmbedRequest) -> EmbedResponse:
        inner = self._inner
        if not isinstance(inner, EmbeddingProvider):
            raise ProviderError(f"{inner.name} does not serve embeddings")

        if self._mode is CacheMode.OFF:
            return inner.embed(spec, request)

        key = embed_cache_key(spec, request)

        if self._mode is not CacheMode.RECORD:
            hit = self._store.get_embed(key)
            if hit is not None:
                return hit
            if self._mode is CacheMode.REPLAY:
                raise CacheMissError(f"no embedding cassette for {spec.id} (key {key[:12]})")

        response = inner.embed(spec, request)
        self._store.put_embed(key, response)
        return response
