"""Pinned model registry.

Availability here is empirical. The OCI catalog listed eight apparently live chat entries in
sa-saopaulo-1 on 2026-11-23 and only three answered a real request: duplicate display-names hide
dedicated-cluster variants, and `time-on-demand-retired` at epoch zero means not served on demand.
Catalog metadata is therefore treated as a hint and every entry carries a probe verdict.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date

from lyren_core.errors import ConfigError, ModelDisabledByQuotaError, ModelNotAvailableError
from lyren_inference.ports import ApiFormat, Availability, Capability, ModelSpec

PROVIDER_OCI = "oci_generative_ai"
PROVIDER_LOCAL = "local_llama_cpp"

_PROBED_ON = date(2026, 11, 23)

_SEED: tuple[ModelSpec, ...] = (
    ModelSpec(
        id="cohere.command-a-03-2025",
        vendor="cohere",
        provider=PROVIDER_OCI,
        api_format=ApiFormat.COHERE,
        pinned_version="1.0",
        capabilities=frozenset({Capability.CHAT}),
        availability=Availability.VERIFIED,
        verified_at=_PROBED_ON,
    ),
    ModelSpec(
        id="meta.llama-3.3-70b-instruct",
        vendor="meta",
        provider=PROVIDER_OCI,
        api_format=ApiFormat.GENERIC,
        pinned_version="1.0.0",
        capabilities=frozenset({Capability.CHAT}),
        availability=Availability.VERIFIED,
        verified_at=_PROBED_ON,
    ),
    ModelSpec(
        id="meta.llama-4-scout-17b-16e-instruct",
        vendor="meta",
        provider=PROVIDER_OCI,
        api_format=ApiFormat.GENERIC,
        pinned_version="1.0.0",
        capabilities=frozenset({Capability.CHAT}),
        availability=Availability.VERIFIED,
        verified_at=_PROBED_ON,
        note="MoE, 17B active parameters — cheapest verified chat arm.",
    ),
    ModelSpec(
        id="cohere.embed-v4.0",
        vendor="cohere",
        provider=PROVIDER_OCI,
        api_format=ApiFormat.COHERE,
        pinned_version="4.0",
        capabilities=frozenset({Capability.TEXT_EMBEDDINGS}),
        availability=Availability.VERIFIED,
        verified_at=_PROBED_ON,
        embedding_dimensions=1536,
    ),
    ModelSpec(
        id="cohere.rerank-v4.0-fast",
        vendor="cohere",
        provider=PROVIDER_OCI,
        api_format=ApiFormat.COHERE,
        pinned_version="4.0",
        capabilities=frozenset({Capability.TEXT_RERANK}),
        availability=Availability.VERIFIED,
        verified_at=_PROBED_ON,
    ),
    ModelSpec(
        id="google.gemini-2.5-flash",
        vendor="google",
        provider=PROVIDER_OCI,
        api_format=ApiFormat.GENERIC,
        pinned_version="1.0.0",
        capabilities=frozenset({Capability.CHAT}),
        availability=Availability.QUOTA_ZERO,
        verified_at=_PROBED_ON,
        note="gemini-2-5-flash-requests-per-minute-count is 0 in this tenancy.",
    ),
    ModelSpec(
        id="local/llama-cpp",
        vendor="local",
        provider=PROVIDER_LOCAL,
        api_format=ApiFormat.GENERIC,
        pinned_version="server-declared",
        capabilities=frozenset({Capability.CHAT}),
        availability=Availability.UNVERIFIED,
        bills=False,
        note=(
            "Whichever GGUF the llama.cpp server has loaded. Not callable until probed: a server "
            "that is down or holding no model must not be routed to. The GGUF choice itself waits "
            "for ARM hardware — benchmarking it on x86 answers nothing about 2 ARM OCPUs."
        ),
    ),
    *(
        ModelSpec(
            id=model_id,
            vendor=model_id.split(".", 1)[0],
            provider=PROVIDER_OCI,
            api_format=ApiFormat.GENERIC,
            pinned_version="1.0.0",
            capabilities=frozenset({Capability.CHAT}),
            availability=Availability.NOT_FOUND,
            verified_at=_PROBED_ON,
            note="Listed in the catalog but the inference endpoint returns 404.",
        )
        for model_id in (
            "openai.gpt-oss-120b",
            "openai.gpt-oss-20b",
            "cohere.command-r-08-2024",
            "meta.llama-3.1-70b-instruct",
            "meta.llama-3-70b-instruct",
        )
    ),
)


@dataclass(frozen=True, slots=True)
class AliasPolicy:
    """A Lyren alias is a virtual model: an ordered candidate list plus its spend guardrails."""

    alias: str
    candidates: tuple[str, ...]
    max_output_tokens: int = 1024
    timeout_seconds: float = 120.0
    allow_paid: bool = False


_ALIASES: tuple[AliasPolicy, ...] = (
    AliasPolicy(
        "lyren/fast",
        ("meta.llama-4-scout-17b-16e-instruct", "local/llama-cpp"),
        max_output_tokens=1024,
    ),
    # The only alias on which prompt content never leaves our own host.
    AliasPolicy("lyren/local", ("local/llama-cpp",), max_output_tokens=1024),
    AliasPolicy(
        "lyren/deep",
        ("cohere.command-a-03-2025", "meta.llama-3.3-70b-instruct"),
        max_output_tokens=4096,
    ),
    AliasPolicy(
        "lyren/code",
        ("meta.llama-3.3-70b-instruct", "cohere.command-a-03-2025"),
        max_output_tokens=4096,
    ),
    AliasPolicy(
        "lyren/research",
        ("cohere.command-a-03-2025", "meta.llama-3.3-70b-instruct"),
        max_output_tokens=4096,
    ),
    AliasPolicy(
        "lyren/auto",
        ("meta.llama-4-scout-17b-16e-instruct", "meta.llama-3.3-70b-instruct", "local/llama-cpp"),
    ),
)


class ModelRegistry:
    def __init__(
        self,
        specs: tuple[ModelSpec, ...] = _SEED,
        aliases: tuple[AliasPolicy, ...] = _ALIASES,
    ) -> None:
        self._specs = {spec.id: spec for spec in specs}
        self._aliases = {policy.alias: policy for policy in aliases}
        self._validate_aliases()

    def _validate_aliases(self) -> None:
        for policy in self._aliases.values():
            unknown = [c for c in policy.candidates if c not in self._specs]
            if unknown:
                raise ConfigError(f"alias {policy.alias} references unknown models: {unknown}")

    def specs(self, *, capability: Capability | None = None) -> tuple[ModelSpec, ...]:
        found = tuple(self._specs.values())
        if capability is not None:
            found = tuple(s for s in found if capability in s.capabilities)
        return found

    def callable_specs(self, *, capability: Capability | None = None) -> tuple[ModelSpec, ...]:
        return tuple(s for s in self.specs(capability=capability) if s.callable_now)

    def aliases(self) -> tuple[AliasPolicy, ...]:
        return tuple(self._aliases.values())

    def alias(self, name: str) -> AliasPolicy | None:
        return self._aliases.get(name)

    def spec(self, model_id: str) -> ModelSpec:
        try:
            return self._specs[model_id]
        except KeyError:
            raise ModelNotAvailableError(f"unknown model: {model_id}") from None

    def resolve(self, name: str) -> tuple[ModelSpec, ...]:
        """Resolve an alias or a concrete id into the ordered list of callable candidates."""
        policy = self._aliases.get(name)
        if policy is not None:
            resolved = tuple(
                self._specs[c] for c in policy.candidates if self._specs[c].callable_now
            )
            if not resolved:
                raise ModelNotAvailableError(f"alias {name} has no callable candidate")
            return resolved

        spec = self.spec(name)
        if spec.availability is Availability.QUOTA_ZERO:
            raise ModelDisabledByQuotaError(f"{name} is disabled by a zero tenancy quota")
        if not spec.callable_now:
            raise ModelNotAvailableError(f"{name} is not served on demand ({spec.availability})")
        return (spec,)

    def apply_probe(self, model_id: str, availability: Availability, *, when: date) -> ModelSpec:
        """Record a runtime probe verdict, so availability drift is observed rather than assumed."""
        current = self.spec(model_id)
        updated = replace(current, availability=availability, verified_at=when)
        self._specs[model_id] = updated
        return updated
