from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from decimal import Decimal
from time import perf_counter

from lyren_core.errors import LyrenError
from lyren_eval.budget import SpendLedger
from lyren_eval.tasks import Scoring, Task, TaskSet
from lyren_inference.ports import ChatProvider, ChatRequest, Message, ModelSpec, Role, Usage


@dataclass(frozen=True, slots=True)
class Trial:
    task_id: str
    model_id: str
    attempt: int
    passed: bool
    latency_ms: float
    tags: tuple[str, ...]
    scoring: Scoring = Scoring.DISCRIMINATING
    usage: Usage = field(default_factory=Usage)
    from_cache: bool = False
    answer: str = ""
    error: str | None = None


@dataclass(frozen=True, slots=True)
class TaskOutcome:
    """One task across all of its attempts."""

    task_id: str
    scoring: Scoring
    attempts: int
    passes: int

    @property
    def pass_rate(self) -> float:
        return self.passes / self.attempts if self.attempts else 0.0

    @property
    def unstable(self) -> bool:
        """The task neither always passes nor always fails — variance the mean would hide."""
        return 0 < self.passes < self.attempts


@dataclass(frozen=True, slots=True)
class RunReport:
    taskset: str
    model: str
    attempts_per_task: int
    trials: tuple[Trial, ...]
    ledger: SpendLedger
    abort_reason: str | None = None

    @property
    def aborted(self) -> bool:
        """The run stopped early, so no score describes the model."""
        return self.abort_reason is not None

    @property
    def errored(self) -> int:
        return sum(1 for t in self.trials if t.error is not None)

    def outcomes(self, *, scoring: Scoring | None = None) -> tuple[TaskOutcome, ...]:
        grouped: dict[str, list[Trial]] = {}
        for trial in self.trials:
            if scoring is not None and trial.scoring is not scoring:
                continue
            grouped.setdefault(trial.task_id, []).append(trial)
        return tuple(
            TaskOutcome(
                task_id=task_id,
                scoring=trials[0].scoring,
                attempts=len(trials),
                passes=sum(1 for t in trials if t.passed),
            )
            for task_id, trials in grouped.items()
        )

    def score(self, *, scoring: Scoring | None = Scoring.DISCRIMINATING) -> float:
        """Mean pass rate, so a task with several attempts counts once, not several times."""
        outcomes = self.outcomes(scoring=scoring)
        if not outcomes:
            return 0.0
        return sum(o.pass_rate for o in outcomes) / len(outcomes)

    def unstable_tasks(self) -> tuple[TaskOutcome, ...]:
        return tuple(o for o in self.outcomes(scoring=None) if o.unstable)

    def latency_percentile(self, percentile: float) -> float:
        """Over calls that reached a model: cache hits measure the disk, not the provider."""
        samples = sorted(t.latency_ms for t in self.trials if not t.from_cache and t.error is None)
        if not samples:
            return 0.0
        if len(samples) >= 100:
            return float(statistics.quantiles(samples, n=100)[int(percentile) - 1])
        index = min(int(len(samples) * percentile / 100), len(samples) - 1)
        return float(samples[index])

    def by_tag(self) -> dict[str, tuple[int, int]]:
        buckets: dict[str, tuple[int, int]] = {}
        for trial in self.trials:
            for tag in trial.tags:
                attempted, passed = buckets.get(tag, (0, 0))
                buckets[tag] = (attempted + 1, passed + (1 if trial.passed else 0))
        return buckets

    @property
    def cost(self) -> Decimal | None:
        """None when any billed call could not be priced — an understated total is not a total."""
        return self.ledger.cost if self.ledger.cost_is_complete else None


def run_taskset(
    provider: ChatProvider,
    spec: ModelSpec,
    taskset: TaskSet,
    *,
    attempts: int = 1,
    ledger: SpendLedger | None = None,
    abort_after_consecutive_errors: int = 5,
) -> RunReport:
    """Runs every task `attempts` times at temperature 0, so variance is observed, not assumed.

    A run that keeps hitting the same error is stopped rather than completed. An expired credential
    would otherwise fail every task and be reported as a score of zero, which reads as a model
    result and is not one.
    """
    if attempts < 1:
        raise ValueError("attempts must be at least 1")

    trials: list[Trial] = []
    streak_code: str | None = None
    streak = 0
    abort_reason: str | None = None

    for task in taskset:
        for attempt in range(attempts):
            trial = _run_one(provider, spec, task, attempt)
            trials.append(trial)

            code = trial.error.split(":", 1)[0] if trial.error else None
            if code is None:
                streak = 0
            elif code == streak_code:
                streak += 1
            else:
                streak = 1
            streak_code = code

            if code is not None and streak >= abort_after_consecutive_errors:
                abort_reason = f"{streak} consecutive {code} errors"
                break
        if abort_reason is not None:
            break

    return RunReport(
        taskset=taskset.name,
        model=spec.id,
        attempts_per_task=attempts,
        trials=tuple(trials),
        ledger=ledger if ledger is not None else SpendLedger(),
        abort_reason=abort_reason,
    )


def _run_one(provider: ChatProvider, spec: ModelSpec, task: Task, attempt: int) -> Trial:
    messages: list[Message] = []
    if task.system:
        messages.append(Message(role=Role.SYSTEM, content=task.system))
    messages.append(Message(role=Role.USER, content=task.prompt))
    request = ChatRequest(
        messages=tuple(messages),
        max_output_tokens=task.max_output_tokens,
        temperature=0.0,
        attempt=attempt,
    )

    started = perf_counter()
    try:
        response = provider.chat(spec, request)
    except LyrenError as exc:
        return Trial(
            task_id=task.id,
            model_id=spec.id,
            attempt=attempt,
            passed=False,
            latency_ms=(perf_counter() - started) * 1000,
            tags=task.tags,
            scoring=task.scoring,
            error=f"{exc.code}: {exc.message}",
        )

    return Trial(
        task_id=task.id,
        model_id=spec.id,
        attempt=attempt,
        passed=task.grade(response.text),
        latency_ms=(perf_counter() - started) * 1000,
        tags=task.tags,
        scoring=task.scoring,
        usage=response.usage,
        from_cache=response.from_cache,
        answer=response.text,
    )
