import json
from datetime import date

import pytest

from lyren_core.errors import ConfigError
from lyren_core.identity import (
    ApiKeyRecord,
    Principal,
    PrincipalStore,
    Quota,
    hash_key,
)

ANA = Principal(id="ana", name="Ana", quota=Quota(requests_per_minute=5, calls_per_day=10))
BRUNO = Principal(id="bruno", name="Bruno", allowed_models=frozenset({"lyren/fast"}))


def key(raw, principal_id, revoked=None):
    return ApiKeyRecord(
        key_hash=hash_key(raw),
        principal_id=principal_id,
        label=raw,
        created_at=date(2026, 11, 24),
        revoked_at=revoked,
    )


def test_a_valid_key_resolves_to_its_principal():
    store = PrincipalStore((ANA, BRUNO), (key("ana-key", "ana"),))

    assert store.resolve(hash_key("ana-key")) == ANA


def test_whitespace_around_a_key_does_not_change_it():
    store = PrincipalStore((ANA,), (key("ana-key", "ana"),))

    assert store.resolve(hash_key("  ana-key  ")) == ANA


def test_a_revoked_key_stops_working_without_touching_other_keys():
    store = PrincipalStore(
        (ANA,), (key("old", "ana", revoked=date(2026, 11, 24)), key("new", "ana"))
    )

    assert store.resolve(hash_key("old")) is None
    assert store.resolve(hash_key("new")) == ANA


def test_a_disabled_principal_rejects_its_own_still_valid_key():
    store = PrincipalStore((Principal(id="ana", name="Ana", enabled=False),), (key("k", "ana"),))

    assert store.resolve(hash_key("k")) is None


def test_an_unknown_key_resolves_to_nothing():
    store = PrincipalStore((ANA,), (key("ana-key", "ana"),))

    assert store.resolve(hash_key("guessed")) is None


def test_a_key_pointing_at_a_missing_principal_fails_at_construction():
    with pytest.raises(ConfigError, match="unknown principals"):
        PrincipalStore((ANA,), (key("k", "ghost"),))


def test_allowed_models_restricts_and_none_means_everything():
    assert BRUNO.may_use("lyren/fast") is True
    assert BRUNO.may_use("lyren/deep") is False
    assert ANA.may_use("anything") is True


def test_the_dev_shortcut_maps_every_hash_to_one_principal():
    store = PrincipalStore.single_dev_principal((hash_key("a"), hash_key("b")))

    assert len(store) == 1
    assert store.resolve(hash_key("a")) == store.resolve(hash_key("b"))


def test_a_store_loads_from_file_with_quotas_and_revocations(tmp_path):
    path = tmp_path / "principals.json"
    path.write_text(
        json.dumps(
            {
                "principals": [
                    {
                        "id": "ana",
                        "name": "Ana",
                        "quota": {"requests_per_minute": 3, "calls_per_day": 7},
                        "allowed_models": ["lyren/fast"],
                    }
                ],
                "api_keys": [
                    {
                        "key_hash": hash_key("ana-key"),
                        "principal_id": "ana",
                        "label": "laptop",
                        "created_at": "2026-11-24",
                    },
                    {
                        "key_hash": hash_key("old-key"),
                        "principal_id": "ana",
                        "label": "rotated out",
                        "created_at": "2026-01-01",
                        "revoked_at": "2026-11-20",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    store = PrincipalStore.from_file(path)
    resolved = store.resolve(hash_key("ana-key"))

    assert resolved is not None
    assert resolved.quota.calls_per_day == 7
    assert resolved.may_use("lyren/deep") is False
    assert store.resolve(hash_key("old-key")) is None


def test_a_file_with_no_principals_is_rejected(tmp_path):
    path = tmp_path / "principals.json"
    path.write_text(json.dumps({"principals": [], "api_keys": []}), encoding="utf-8")

    with pytest.raises(ConfigError, match="no principals"):
        PrincipalStore.from_file(path)


def test_a_verified_address_resolves_to_the_principal_that_claims_it():
    ana = Principal(id="ana", name="Ana", emails=frozenset({"ana@example.com"}))
    store = PrincipalStore((ana,), ())

    assert store.resolve_email("Ana@Example.com ") == ana


def test_an_address_nobody_claims_resolves_to_nothing():
    store = PrincipalStore((Principal(id="ana", name="Ana", emails=frozenset({"ana@x.com"})),), ())

    assert store.resolve_email("stranger@gmail.com") is None


def test_a_disabled_principal_cannot_sign_in_with_its_address():
    disabled = Principal(id="ana", name="Ana", emails=frozenset({"ana@example.com"}), enabled=False)
    store = PrincipalStore((disabled,), ())

    assert store.resolve_email("ana@example.com") is None


def test_an_address_claimed_by_two_principals_fails_at_construction():
    first = Principal(id="ana", name="Ana", emails=frozenset({"shared@example.com"}))
    second = Principal(id="bruno", name="Bruno", emails=frozenset({"shared@example.com"}))

    with pytest.raises(ConfigError, match="claimed by both"):
        PrincipalStore((first, second), ())


def test_resolve_id_honours_the_enabled_flag():
    store = PrincipalStore(
        (Principal(id="ana", name="Ana"), Principal(id="old", name="Old", enabled=False)), ()
    )

    assert store.resolve_id("ana") is not None
    assert store.resolve_id("old") is None
    assert store.resolve_id("ghost") is None
