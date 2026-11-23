"""Dispatch a call to the provider that serves the model.

Needed the moment there is more than one provider: a `ModelSpec` already names its provider, so the
route should not know which concrete client to use. This also makes alias fallback meaningful — a
candidate list can cross provider boundaries, so a hosted model can fall back to a local one.
"""

from __future__ import annotations

from lyren_core.errors import ProviderError
from lyren_inference.ports import ChatProvider, ChatRequest, ChatResponse, ModelSpec


class ProviderRouter:
    """A `ChatProvider` that owns several, keyed by `ModelSpec.provider`."""

    name = "router"

    def __init__(self, providers: dict[str, ChatProvider]) -> None:
        self._providers = dict(providers)

    def providers(self) -> tuple[str, ...]:
        return tuple(self._providers)

    def serves(self, spec: ModelSpec) -> bool:
        return spec.provider in self._providers

    def chat(self, spec: ModelSpec, request: ChatRequest) -> ChatResponse:
        provider = self._providers.get(spec.provider)
        if provider is None:
            raise ProviderError(
                f"no provider is configured for {spec.provider}",
                detail=f"model {spec.id}; configured: {sorted(self._providers)}",
            )
        return provider.chat(spec, request)
