from datetime import date

import pytest

from lyren_core.errors import (
    ConfigError,
    ModelDisabledByQuotaError,
    ModelNotAvailableError,
)
from lyren_inference.ports import ApiFormat, Availability, Capability, ModelSpec
from lyren_inference.registry import AliasPolicy, ModelRegistry


def test_alias_resolves_to_callable_candidates_in_order():
    registry = ModelRegistry()

    resolved = registry.resolve("lyren/deep")

    assert [spec.id for spec in resolved] == [
        "cohere.command-a-03-2025",
        "meta.llama-3.3-70b-instruct",
    ]


def test_quota_zero_model_raises_its_own_error():
    registry = ModelRegistry()

    with pytest.raises(ModelDisabledByQuotaError):
        registry.resolve("google.gemini-2.5-flash")


def test_catalog_listed_but_unserved_model_is_not_callable():
    registry = ModelRegistry()

    with pytest.raises(ModelNotAvailableError):
        registry.resolve("openai.gpt-oss-120b")


def test_openai_shaped_listing_excludes_unavailable_models():
    registry = ModelRegistry()

    callable_ids = {spec.id for spec in registry.callable_specs(capability=Capability.CHAT)}

    assert callable_ids == {
        "cohere.command-a-03-2025",
        "meta.llama-3.3-70b-instruct",
        "meta.llama-4-scout-17b-16e-instruct",
    }


def test_probe_result_overrides_seeded_availability():
    registry = ModelRegistry()

    updated = registry.apply_probe(
        "meta.llama-3.3-70b-instruct", Availability.NOT_FOUND, when=date(2026, 12, 1)
    )

    assert updated.availability is Availability.NOT_FOUND
    with pytest.raises(ModelNotAvailableError):
        registry.resolve("meta.llama-3.3-70b-instruct")


def test_alias_pointing_at_unknown_model_fails_at_construction():
    spec = ModelSpec(
        id="only.model",
        vendor="only",
        provider="p",
        api_format=ApiFormat.GENERIC,
        pinned_version="1",
        capabilities=frozenset({Capability.CHAT}),
        availability=Availability.VERIFIED,
    )

    with pytest.raises(ConfigError):
        ModelRegistry(specs=(spec,), aliases=(AliasPolicy("lyren/x", ("missing.model",)),))


def test_alias_with_no_callable_candidate_raises():
    spec = ModelSpec(
        id="dead.model",
        vendor="dead",
        provider="p",
        api_format=ApiFormat.GENERIC,
        pinned_version="1",
        capabilities=frozenset({Capability.CHAT}),
        availability=Availability.NOT_FOUND,
    )
    registry = ModelRegistry(specs=(spec,), aliases=(AliasPolicy("lyren/x", ("dead.model",)),))

    with pytest.raises(ModelNotAvailableError):
        registry.resolve("lyren/x")
