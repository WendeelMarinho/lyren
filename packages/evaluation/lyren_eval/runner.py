from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field
from decimal import Decimal

from lyren_core.errors import LyrenError
from lyren_eval.budget import SpendLedger
from lyren_eval.tasks import Task, TaskSet
from lyren_inference.ports import ChatProvider, ChatRequest, Message, ModelSpec, Role, Usage


@dataclass(frozen=True, slots=True)
class Trial:
    task_id: str
    model_id: str
    passed: bool
    latency_ms: float
    tags: tuple[str, ...]
    usage: Usage = field(default_factory=Usage)
    from_cache: bool = False
    answer: str = ""
    error: str | None = None


@dataclass(frozen=True, slots=True)
class RunReport:
    taskset: str
    model: str
    trials: tuple[Trial, ...]
    ledger: SpendLedger

    @property
    def attempted(self) -> int:
        return len(self.trials)

    @property
    def passed(self) -> int:
        return sum(1 for t in self.trials if t.passed)

    @property
    def errored(self) -> int:
        return sum(1 for t in self.trials if t.error is not None)

    @property
    def success_rate(self) -> float:
        return self.passed / self.attempted if self.attempted else 0.0

    def latency_percentile(self, percentile: float) -> float:
        """Latency over calls that actually reached a model, excluding cache hits."""
        samples = sorted(t.latency_ms for t in self.trials if not t.from_cache and t.error is None)
        if not samples:
            return 0.0
        return (
            float(statistics.quantiles(samples, n=100)[int(percentile) - 1])
            if len(samples) >= 100
            else float(samples[min(int(len(samples) * percentile / 100), len(samples) - 1)])
        )

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
    ledger: SpendLedger | None = None,
) -> RunReport:
    """Runs every task once against one model. Deterministic by construction: temperature 0."""
    trials: list[Trial] = []
    for task in taskset:
        trials.append(_run_one(provider, spec, task))
    return RunReport(
        taskset=taskset.name,
        model=spec.id,
        trials=tuple(trials),
        ledger=ledger if ledger is not None else SpendLedger(),
    )


def _run_one(provider: ChatProvider, spec: ModelSpec, task: Task) -> Trial:
    messages: list[Message] = []
    if task.system:
        messages.append(Message(role=Role.SYSTEM, content=task.system))
    messages.append(Message(role=Role.USER, content=task.prompt))
    request = ChatRequest(
        messages=tuple(messages), max_output_tokens=task.max_output_tokens, temperature=0.0
    )

    started = time.perf_counter()
    try:
        response = provider.chat(spec, request)
    except LyrenError as exc:
        return Trial(
            task_id=task.id,
            model_id=spec.id,
            passed=False,
            latency_ms=(time.perf_counter() - started) * 1000,
            tags=task.tags,
            error=f"{exc.code}: {exc.message}",
        )

    return Trial(
        task_id=task.id,
        model_id=spec.id,
        passed=task.grade(response.text),
        latency_ms=(time.perf_counter() - started) * 1000,
        tags=task.tags,
        usage=response.usage,
        from_cache=response.from_cache,
        answer=response.text,
    )
