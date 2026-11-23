import json

import pytest
from argon2 import PasswordHasher as Argon2Hasher

from lyren_core.credentials import (
    MIN_PASSWORD_LENGTH,
    CredentialStore,
    LoginThrottle,
    validate_password,
)
from lyren_core.errors import AuthError, ConfigError, ForbiddenError

GOOD = "uma-senha-bem-comprida"


def fast_store(path):
    """Cheap parameters: the tuned ones cost ~120 ms a hash and would dominate the suite."""
    return CredentialStore(
        path,
        hasher=Argon2Hasher(time_cost=1, memory_cost=8, parallelism=1, hash_len=16, salt_len=8),
    )


def test_a_long_password_is_accepted():
    validate_password(GOOD, email="ana@example.com")


def test_a_short_password_is_refused():
    with pytest.raises(ForbiddenError, match=str(MIN_PASSWORD_LENGTH)):
        validate_password("curta", email="ana@example.com")


def test_an_absurdly_long_password_is_refused():
    with pytest.raises(ForbiddenError, match="at most"):
        validate_password("a" * 2000, email="ana@example.com")


# Both values clear the length check, so the address check is what rejects them.
@pytest.mark.parametrize("password", ["anabeatrizsouza", "anabeatrizsouza@example.com"])
def test_a_password_that_is_the_address_is_refused(password):
    with pytest.raises(ForbiddenError, match="the address itself"):
        validate_password(password, email="anabeatrizsouza@example.com")


def test_a_short_password_reports_its_length_before_anything_else():
    """Order matters only for the message: a short password is refused either way."""
    with pytest.raises(ForbiddenError, match="at least"):
        validate_password("ana", email="ana@example.com")


def test_a_password_round_trips(tmp_path):
    store = fast_store(tmp_path / "creds.json")

    store.set_password("ana", GOOD)

    assert store.has_password("ana") is True
    assert store.verify("ana", GOOD) is True


def test_a_wrong_password_is_refused(tmp_path):
    store = fast_store(tmp_path / "creds.json")
    store.set_password("ana", GOOD)

    assert store.verify("ana", "outra-senha-comprida") is False


def test_an_unknown_principal_still_performs_a_hash_and_returns_false(tmp_path):
    store = fast_store(tmp_path / "creds.json")

    assert store.verify("ghost", GOOD) is False
    assert store.verify(None, GOOD) is False


def test_the_hash_is_persisted_and_reloaded(tmp_path):
    path = tmp_path / "creds.json"
    fast_store(path).set_password("ana", GOOD)

    reloaded = fast_store(path)

    assert reloaded.verify("ana", GOOD) is True


def test_the_stored_file_contains_a_hash_and_not_the_password(tmp_path):
    path = tmp_path / "creds.json"
    fast_store(path).set_password("ana", GOOD)

    raw = path.read_text(encoding="utf-8")
    entry = json.loads(raw)["passwords"][0]

    assert GOOD not in raw
    assert entry["password_hash"].startswith("$argon2")
    assert entry["principal_id"] == "ana"


def test_the_stored_file_is_not_world_readable(tmp_path):
    path = tmp_path / "creds.json"
    fast_store(path).set_password("ana", GOOD)

    assert path.stat().st_mode & 0o077 == 0


def test_no_temporary_file_is_left_behind(tmp_path):
    path = tmp_path / "creds.json"
    fast_store(path).set_password("ana", GOOD)

    assert [p.name for p in tmp_path.iterdir()] == ["creds.json"]


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_attempts_below_the_limit_pass():
    throttle = LoginThrottle(max_attempts=3, clock=Clock())

    for _ in range(2):
        throttle.check("ana@example.com")
        throttle.record_failure("ana@example.com")

    throttle.check("ana@example.com")


def test_reaching_the_limit_locks_out():
    throttle = LoginThrottle(max_attempts=2, clock=Clock())
    for _ in range(2):
        throttle.record_failure("ana@example.com")

    with pytest.raises(AuthError, match="too many failed"):
        throttle.check("ana@example.com")


def test_the_lockout_window_slides():
    clock = Clock()
    throttle = LoginThrottle(max_attempts=2, window_seconds=300, clock=clock)
    for _ in range(2):
        throttle.record_failure("ana@example.com")

    clock.now += 301
    throttle.check("ana@example.com")


def test_a_successful_sign_in_clears_the_counter():
    throttle = LoginThrottle(max_attempts=2, clock=Clock())
    throttle.record_failure("ana@example.com")
    throttle.record_failure("ana@example.com")

    throttle.clear("ANA@example.com ")

    throttle.check("ana@example.com")


def test_one_address_being_locked_out_does_not_lock_another():
    throttle = LoginThrottle(max_attempts=1, clock=Clock())
    throttle.record_failure("ana@example.com")

    throttle.check("bruno@example.com")


def test_a_zero_attempt_limit_is_a_configuration_error():
    with pytest.raises(ConfigError, match="at least 1"):
        LoginThrottle(max_attempts=0)
