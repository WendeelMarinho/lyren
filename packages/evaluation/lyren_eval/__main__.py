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
from lyren_eval.tasks import TaskSet
from lyren_inference.cache import CachingChatProvider, CassetteStore
from lyren_inference.providers.oci import OCIGenerativeAIProvider
from lyren_inference.registry import ModelRegistry


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lyren_eval", description=__doc__)
    parser.add_argument("--model", default="lyren/fast", help="alias or concrete model id")
    parser.add_argument("--taskset", default="baseline-v1")
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
        f"taskset={taskset.name} tasks={len(taskset)} model={spec.id} cache={mode.value} "
        f"call_cap={args.max_calls or 'none'} spend_cap={args.max_spend or 'none'}"
    )
    report = run_taskset(guard, spec, taskset, ledger=guard.ledger)
    _print(report)
    return 0 if report.errored == 0 else 1


def _print(report: RunReport) -> None:
    for trial in report.trials:
        mark = "PASS" if trial.passed else "FAIL"
        suffix = f" error={trial.error}" if trial.error else f" -> {trial.answer.strip()[:60]!r}"
        print(f"  {mark}  {trial.task_id:<12} {trial.latency_ms:7.0f}ms{suffix}")

    ledger = report.ledger
    print(
        f"\n{report.passed}/{report.attempted} passed "
        f"({report.success_rate:.0%}), {report.errored} errored"
    )
    print(
        f"latency p50={report.latency_percentile(50):.0f}ms "
        f"p95={report.latency_percentile(95):.0f}ms"
    )
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

    for tag, (attempted, passed) in sorted(report.by_tag().items()):
        print(f"  {tag:<12} {passed}/{attempted}")


if __name__ == "__main__":
    raise SystemExit(main())
