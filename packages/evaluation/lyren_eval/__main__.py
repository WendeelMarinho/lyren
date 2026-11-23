"""Benchmark one model against a frozen task set.

This is the command that spends money. Two guards apply by default: a call cap, which needs no price
information, and an optional money cap, which does.
"""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from pathlib import Path

from lyren_core.errors import LyrenError
from lyren_core.logging import configure_logging
from lyren_core.settings import CacheMode, Settings
from lyren_eval.budget import BudgetGuard
from lyren_eval.pricing import PriceBook
from lyren_eval.runner import RunReport, run_taskset
from lyren_eval.tasks import Scoring, TaskSet
from lyren_inference.cache import CachingChatProvider, CassetteStore
from lyren_inference.providers.oci import OCIGenerativeAIProvider
from lyren_inference.registry import ModelRegistry


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lyren_eval", description=__doc__)
    parser.add_argument("--model", default="lyren/fast", help="alias or concrete model id")
    parser.add_argument("--taskset", default="baseline-v2")
    parser.add_argument(
        "--attempts", type=int, default=1, help="repeats per task, to expose variance"
    )
    parser.add_argument(
        "--max-calls", type=int, default=50, help="hard call cap; 0 disables it deliberately"
    )
    parser.add_argument(
        "--max-spend", type=Decimal, default=None, help="money cap, needs a price book"
    )
    parser.add_argument("--price-book", type=Path, default=None)
    parser.add_argument("--cache", choices=[m.value for m in CacheMode], default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings()
    configure_logging(settings.log_level)

    try:
        taskset = TaskSet.load(args.taskset)
        registry = ModelRegistry()
        spec = registry.resolve(args.model)[0]
        provider = OCIGenerativeAIProvider(settings)
    except LyrenError as exc:
        print(f"error [{exc.code}]: {exc.message}", file=sys.stderr)
        if exc.detail:
            print(f"  {exc.detail}", file=sys.stderr)
        return 2

    mode = CacheMode(args.cache) if args.cache else settings.cache_mode
    cached = CachingChatProvider(provider, CassetteStore(settings.cache_dir), mode)
    prices = PriceBook.from_file(args.price_book) if args.price_book else PriceBook.empty()
    guard = BudgetGuard(
        cached,
        prices,
        hard_cap=args.max_spend,
        max_calls=args.max_calls or None,
    )

    print(
        f"taskset={taskset.name} tasks={len(taskset)} "
        f"(discriminating {len(taskset.discriminating())}) attempts={args.attempts} "
        f"model={spec.id} cache={mode.value} "
        f"call_cap={args.max_calls or 'none'} spend_cap={args.max_spend or 'none'}"
    )
    report = run_taskset(guard, spec, taskset, attempts=args.attempts, ledger=guard.ledger)
    _print(report)
    if report.aborted:
        return 3
    return 0 if report.errored == 0 else 1


def _print(report: RunReport) -> None:
    for trial in report.trials:
        if trial.passed:
            continue
        where = (
            f"{trial.task_id}#{trial.attempt}" if report.attempts_per_task > 1 else trial.task_id
        )
        detail = trial.error or repr(trial.answer.strip()[:60])
        print(f"  FAIL  {where:<22} {trial.latency_ms:7.0f}ms  {detail}")

    if report.aborted:
        print(f"\nRUN ABORTED: {report.abort_reason}")
        print("no score is reported — this describes the run, not the model")
        print(f"trials attempted={len(report.trials)} errored={report.errored}")
        return

    print(
        f"\nscore(discriminating)={report.score():.1%}  "
        f"score(weakness_probes)={report.score(scoring=Scoring.WEAKNESS_PROBE):.1%}  "
        f"errored={report.errored}"
    )

    unstable = report.unstable_tasks()
    if unstable:
        detail = ", ".join(f"{o.task_id} {o.passes}/{o.attempts}" for o in unstable)
        print(f"unstable across attempts: {detail}")
    elif report.attempts_per_task > 1:
        print("unstable across attempts: none")

    print(
        f"latency p50={report.latency_percentile(50):.0f}ms "
        f"p95={report.latency_percentile(95):.0f}ms"
    )
    ledger = report.ledger
    print(
        f"calls={ledger.calls} (cached {ledger.cached_calls}) "
        f"tokens in={ledger.prompt_tokens} out={ledger.completion_tokens}"
    )
    cost = report.cost
    print(
        f"cost={cost}"
        if cost is not None
        else f"cost=UNKNOWN ({ledger.unpriced_calls} calls without a configured price)"
    )


if __name__ == "__main__":
    raise SystemExit(main())
