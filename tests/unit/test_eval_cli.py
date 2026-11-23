from decimal import Decimal

from lyren_eval.__main__ import build_parser, main
from lyren_eval.budget import SpendLedger
from lyren_eval.runner import RunReport, Trial
from lyren_eval.tasks import Scoring


def test_parser_defaults_keep_a_call_cap_on():
    args = build_parser().parse_args([])

    assert (args.taskset, args.model, args.attempts) == ("baseline-v2", "lyren/fast", 1)
    assert args.max_calls == 50
    assert args.max_spend is None


def test_parser_accepts_a_money_cap_as_decimal():
    assert build_parser().parse_args(["--max-spend", "2.50"]).max_spend == Decimal("2.50")


def _report(trials, attempts=1, ledger=None):
    return RunReport(
        taskset="t",
        model="m",
        attempts_per_task=attempts,
        trials=tuple(trials),
        ledger=ledger or SpendLedger(),
    )


def _trial(task_id, passed, *, attempt=0, scoring=Scoring.DISCRIMINATING, error=None):
    return Trial(
        task_id=task_id,
        model_id="m",
        attempt=attempt,
        passed=passed,
        latency_ms=10.0,
        tags=("t",),
        scoring=scoring,
        answer="x",
        error=error,
    )


def test_unknown_taskset_exits_with_a_message_and_does_not_reach_a_provider(capsys):
    code = main(["--taskset", "nope"])

    assert code == 2
    assert "baseline-v2" in capsys.readouterr().err


def test_report_prints_both_scores_and_an_unknown_cost(capsys):
    from lyren_eval.__main__ import _print

    ledger = SpendLedger()
    ledger.record("m", _trial("a", True).usage, None, cached=False)
    _print(
        _report(
            [_trial("a", True), _trial("p", False, scoring=Scoring.WEAKNESS_PROBE)], ledger=ledger
        )
    )

    out = capsys.readouterr().out
    assert "score(discriminating)=100.0%" in out
    assert "score(weakness_probes)=0.0%" in out
    assert "cost=UNKNOWN" in out
    assert "FAIL  p" in out


def test_report_names_unstable_tasks_when_attempts_repeat(capsys):
    from lyren_eval.__main__ import _print

    _print(_report([_trial("a", True), _trial("a", False, attempt=1)], attempts=2))

    assert "unstable across attempts: a 1/2" in capsys.readouterr().out


def test_report_says_none_when_nothing_was_unstable(capsys):
    from lyren_eval.__main__ import _print

    _print(_report([_trial("a", True), _trial("a", True, attempt=1)], attempts=2))

    assert "unstable across attempts: none" in capsys.readouterr().out


def test_errored_trial_shows_its_error_instead_of_an_answer(capsys):
    from lyren_eval.__main__ import _print

    _print(_report([_trial("a", False, error="model_not_available: gone")]))

    assert "model_not_available: gone" in capsys.readouterr().out


def test_aborted_run_prints_no_score(capsys):
    from lyren_eval.__main__ import _print

    report = RunReport(
        taskset="t",
        model="m",
        attempts_per_task=1,
        trials=(_trial("a", False, error="provider_auth_error: expired"),),
        ledger=SpendLedger(),
        abort_reason="5 consecutive provider_auth_error errors",
    )
    _print(report)

    out = capsys.readouterr().out
    assert "RUN ABORTED: 5 consecutive provider_auth_error errors" in out
    assert "describes the run, not the model" in out
    assert "score(discriminating)" not in out
