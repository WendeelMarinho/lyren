from datetime import UTC, datetime, timedelta

import pytest

from lyren_core.errors import QuotaExceededError
from lyren_core.identity import Principal, Quota
from lyren_core.metering import UsageMeter

ANA = Principal(
    id="ana", name="Ana", quota=Quota(requests_per_minute=2, calls_per_day=3, max_output_tokens=256)
)
BRUNO = Principal(id="bruno", name="Bruno", quota=Quota(requests_per_minute=2, calls_per_day=3))

START = datetime(2026, 11, 24, 12, 0, 0, tzinfo=UTC)


class Clock:
    def __init__(self, start=START):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, **kwargs):
        self.now += timedelta(**kwargs)


def test_requests_within_the_rate_limit_pass():
    meter = UsageMeter(Clock())

    for _ in range(2):
        meter.check(ANA)
        meter.record(ANA)


def test_exceeding_the_rate_limit_raises_before_any_call():
    meter = UsageMeter(Clock())
    for _ in range(2):
        meter.check(ANA)
        meter.record(ANA)

    with pytest.raises(QuotaExceededError, match="requests/minute"):
        meter.check(ANA)


def test_the_rate_window_slides():
    clock = Clock()
    meter = UsageMeter(clock)
    for _ in range(2):
        meter.check(ANA)
        meter.record(ANA)

    clock.advance(seconds=61)
    meter.check(ANA)


def test_the_daily_cap_outlives_the_rate_window():
    clock = Clock()
    meter = UsageMeter(clock)
    for _ in range(3):
        meter.check(ANA)
        meter.record(ANA)
        clock.advance(seconds=61)

    with pytest.raises(QuotaExceededError, match="daily limit"):
        meter.check(ANA)


def test_the_daily_counter_resets_on_a_new_day():
    clock = Clock()
    meter = UsageMeter(clock)
    for _ in range(3):
        meter.check(ANA)
        meter.record(ANA)
        clock.advance(seconds=61)

    clock.advance(days=1)
    meter.check(ANA)
    assert meter.usage_for("ana").calls_today == 0


def test_one_principal_cannot_consume_another_s_quota():
    meter = UsageMeter(Clock())
    for _ in range(2):
        meter.check(ANA)
        meter.record(ANA)

    meter.check(BRUNO)
    meter.record(BRUNO)

    assert meter.usage_for("bruno").calls_today == 1


def test_tokens_are_attributed_per_principal():
    meter = UsageMeter(Clock())

    meter.record(ANA, prompt_tokens=10, completion_tokens=4)
    meter.record(ANA, prompt_tokens=5, completion_tokens=None)

    usage = meter.usage_for("ana")
    assert (usage.prompt_tokens_today, usage.completion_tokens_today) == (15, 4)


def test_the_deployment_cap_binds_even_when_no_principal_is_near_its_own():
    meter = UsageMeter(Clock(), deployment_calls_per_day=3)
    for principal in (ANA, BRUNO, ANA):
        meter.check(principal)
        meter.record(principal)

    with pytest.raises(QuotaExceededError, match="deployment-wide"):
        meter.check(BRUNO)
    assert meter.deployment_usage().calls_today == 3


def test_the_deployment_counter_resets_on_a_new_day():
    clock = Clock()
    meter = UsageMeter(clock, deployment_calls_per_day=1)
    meter.check(ANA)
    meter.record(ANA)

    clock.advance(days=1)
    meter.check(BRUNO)
    assert meter.deployment_usage().calls_today == 0


def test_no_deployment_cap_means_only_per_principal_limits_apply():
    meter = UsageMeter(Clock())
    for _ in range(2):
        meter.check(ANA)
        meter.record(ANA)
    meter.check(BRUNO)
    meter.record(BRUNO)

    assert meter.deployment_usage().calls_today == 3
