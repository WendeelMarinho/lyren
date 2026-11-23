"""Per-principal usage accounting and quota enforcement.

Several people share one pay-as-you-go account with no automatic stop, so a quota is not a courtesy
— it is the only thing preventing one principal from spending everyone's budget. Limits are counted
per principal and never pooled.

Two caps, because per-principal limits protect principals from each other and do not protect the
budget: five people at 500 calls a day is 2500 calls a day. So there is also a deployment-wide daily
cap, and the effective limit is whichever binds first.

In-process and therefore per-worker: two API workers each allow the full rate. That is honest rather
than fixed, because fixing it means a shared store, which belongs with the database in Phase 5. The
daily caps are the ones that bound spend, and they are deliberately the conservative ones.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from lyren_core.errors import QuotaExceededError
from lyren_core.identity import Principal

_MINUTE_SECONDS = 60.0


@dataclass(slots=True)
class PrincipalUsage:
    recent_requests: deque[float] = field(default_factory=deque)
    day: date | None = None
    calls_today: int = 0
    prompt_tokens_today: int = 0
    completion_tokens_today: int = 0

    def roll_day(self, today: date) -> None:
        if self.day != today:
            self.day = today
            self.calls_today = 0
            self.prompt_tokens_today = 0
            self.completion_tokens_today = 0


class UsageMeter:
    def __init__(
        self,
        clock: Callable[[], datetime] | None = None,
        *,
        deployment_calls_per_day: int | None = None,
    ) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))
        self._usage: dict[str, PrincipalUsage] = {}
        self._deployment_cap = deployment_calls_per_day
        self._deployment = PrincipalUsage()

    def usage_for(self, principal_id: str) -> PrincipalUsage:
        return self._usage.setdefault(principal_id, PrincipalUsage())

    def deployment_usage(self) -> PrincipalUsage:
        return self._deployment

    def check(self, principal: Principal) -> None:
        """Raises before any provider call, so a refused request costs nothing."""
        now = self._clock()
        usage = self.usage_for(principal.id)
        usage.roll_day(now.date())

        cutoff = now.timestamp() - _MINUTE_SECONDS
        while usage.recent_requests and usage.recent_requests[0] <= cutoff:
            usage.recent_requests.popleft()

        if len(usage.recent_requests) >= principal.quota.requests_per_minute:
            raise QuotaExceededError(
                f"rate limit of {principal.quota.requests_per_minute} requests/minute reached",
                detail=f"principal={principal.id}",
            )
        if usage.calls_today >= principal.quota.calls_per_day:
            raise QuotaExceededError(
                f"daily limit of {principal.quota.calls_per_day} calls reached",
                detail=f"principal={principal.id}",
            )

        self._deployment.roll_day(now.date())
        if (
            self._deployment_cap is not None
            and self._deployment.calls_today >= self._deployment_cap
        ):
            raise QuotaExceededError(
                f"deployment-wide daily limit of {self._deployment_cap} calls reached",
                detail="this protects the shared budget; per-principal quotas do not",
            )

    def record(
        self,
        principal: Principal,
        *,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
    ) -> None:
        now = self._clock()
        usage = self.usage_for(principal.id)
        usage.roll_day(now.date())
        usage.recent_requests.append(now.timestamp())
        usage.calls_today += 1
        usage.prompt_tokens_today += prompt_tokens or 0
        usage.completion_tokens_today += completion_tokens or 0

        self._deployment.roll_day(now.date())
        self._deployment.calls_today += 1
        self._deployment.prompt_tokens_today += prompt_tokens or 0
        self._deployment.completion_tokens_today += completion_tokens or 0
