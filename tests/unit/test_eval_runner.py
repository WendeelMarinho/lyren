import json

import pytest

from lyren_core.errors import ConfigError, ModelNotAvailableError
from lyren_eval.runner import run_taskset
from lyren_eval.tasks import Scoring, Task, TaskSet
from lyren_inference.ports import (
    ApiFormat,
    Availability,
    Capability,
    ChatResponse,
    ModelSpec,
    Usage,
)

SPEC = ModelSpec(
    id="m",
    vendor="v",
    provider="p",
    api_format=ApiFormat.GENERIC,
    pinned_version="1",
    capabilities=frozenset({Capability.CHAT}),
    availability=Availability.VERIFIED,
)


class Scripted:
    name = "scripted"

    def __init__(self, answers):
        self.answers = list(answers)
        self.requests = []

    def chat(self, spec, request):
        self.requests.append(request)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return ChatResponse(
            model_id=spec.id,
            text=answer,
            finish_reason="stop",
            usage=Usage(prompt_tokens=2, completion_tokens=3),
        )


def taskset():
    return TaskSet(
        name="t",
        tasks=(
            Task(id="a", prompt="2+2?", grader="numeric", expected=4, tags=("math",)),
            Task(id="b", prompt="say ok", grader="exact", expected="ok", tags=("instr",)),
            Task(
                id="p",
                prompt="reverse",
                grader="exact",
                expected="zyx",
                tags=("tokenization",),
                scoring=Scoring.WEAKNESS_PROBE,
            ),
        ),
    )


def test_weakness_probes_are_scored_apart_from_the_discriminating_set():
    provider = Scripted(["4", "ok", "wrong"])

    report = run_taskset(provider, SPEC, taskset())

    assert report.score() == pytest.approx(1.0)
    assert report.score(scoring=Scoring.WEAKNESS_PROBE) == pytest.approx(0.0)


def test_a_failing_probe_does_not_drag_the_headline_score():
    provider = Scripted(["4", "nope", "wrong"])

    assert run_taskset(provider, SPEC, taskset()).score() == pytest.approx(0.5)


def test_repeated_attempts_each_reach_the_provider_with_a_distinct_attempt_index():
    provider = Scripted(["4", "4", "ok", "ok", "zyx", "zyx"])

    report = run_taskset(provider, SPEC, taskset(), attempts=2)

    assert len(report.trials) == 6
    assert sorted({r.attempt for r in provider.requests}) == [0, 1]
    assert report.attempts_per_task == 2


def test_a_task_that_passes_only_sometimes_is_reported_as_unstable():
    provider = Scripted(["4", "wrong", "ok", "ok", "zyx", "zyx"])

    report = run_taskset(provider, SPEC, taskset(), attempts=2)
    unstable = report.unstable_tasks()

    assert [o.task_id for o in unstable] == ["a"]
    assert unstable[0].pass_rate == pytest.approx(0.5)
    assert report.score() == pytest.approx(0.75)


def test_errored_trial_records_the_code_and_does_not_pass():
    provider = Scripted(["4", "ok", ModelNotAvailableError("gone")])

    report = run_taskset(provider, SPEC, taskset())
    failed = next(t for t in report.trials if t.task_id == "p")

    assert (failed.passed, report.errored) == (False, 1)
    assert failed.error is not None
    assert failed.error.startswith("model_not_available")


def test_attempts_below_one_is_rejected():
    with pytest.raises(ValueError, match="at least 1"):
        run_taskset(Scripted([]), SPEC, taskset(), attempts=0)


def test_system_prompt_is_sent_when_the_task_defines_one():
    provider = Scripted(["ok"])
    task = Task(id="s", prompt="p", grader="exact", expected="ok", system="be terse")

    run_taskset(provider, SPEC, TaskSet(name="t", tasks=(task,)))

    assert [str(m.role) for m in provider.requests[0].messages] == ["system", "user"]


def test_frozen_tasksets_load_and_have_unique_ids():
    v1, v2 = TaskSet.load("baseline-v1"), TaskSet.load("baseline-v2")

    assert len(v1) == 14
    assert (len(v2), len(v2.discriminating())) == (22, 20)
    assert len({t.id for t in v2}) == 22


def test_duplicate_task_id_is_rejected(tmp_path):
    row = {"id": "dup", "prompt": "p", "grader": "exact", "expected": "x"}
    path = tmp_path / "bad.jsonl"
    path.write_text(f"{json.dumps(row)}\n{json.dumps(row)}\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="duplicate task id"):
        TaskSet.from_jsonl(path)


def test_unknown_grader_is_rejected(tmp_path):
    path = tmp_path / "bad.jsonl"
    path.write_text(
        json.dumps({"id": "a", "prompt": "p", "grader": "vibes", "expected": "x"}), encoding="utf-8"
    )

    with pytest.raises(ConfigError, match="unknown grader"):
        TaskSet.from_jsonl(path)


def test_unknown_taskset_name_lists_what_exists():
    with pytest.raises(ConfigError, match="baseline-v2"):
        TaskSet.load("does-not-exist")


def test_a_run_of_repeated_errors_is_aborted_and_reports_no_score():
    failures = [ModelNotAvailableError("creds") for _ in range(6)]
    report = run_taskset(
        Scripted(failures), SPEC, taskset(), attempts=2, abort_after_consecutive_errors=3
    )

    assert report.aborted is True
    assert report.abort_reason == "3 consecutive model_not_available errors"
    assert len(report.trials) == 3


def test_scattered_errors_do_not_abort_a_run():
    provider = Scripted(["4", ModelNotAvailableError("x"), "ok", "ok", "zyx", "zyx"])

    report = run_taskset(provider, SPEC, taskset(), attempts=2, abort_after_consecutive_errors=3)

    assert report.aborted is False
    assert report.errored == 1
    assert len(report.trials) == 6


def test_a_completed_run_has_no_abort_reason():
    report = run_taskset(Scripted(["4", "ok", "zyx"]), SPEC, taskset())

    assert (report.aborted, report.abort_reason) == (False, None)
