import json

import pytest

from lyren_core.errors import ConfigError, ModelNotAvailableError
from lyren_eval.runner import run_taskset
from lyren_eval.tasks import Task, TaskSet
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
        self.answers = answers
        self.systems_seen = []

    def chat(self, spec, request):
        self.systems_seen.append([str(m.role) for m in request.messages])
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
            Task(id="c", prompt="boom", grader="exact", expected="x", tags=("math",)),
        ),
    )


def test_report_counts_passes_failures_and_errors():
    provider = Scripted(["4", "nope", ModelNotAvailableError("gone")])

    report = run_taskset(provider, SPEC, taskset())

    assert (report.passed, report.attempted, report.errored) == (1, 3, 1)
    assert report.success_rate == pytest.approx(1 / 3)


def test_errored_trial_records_the_error_code_and_does_not_pass():
    provider = Scripted(["4", "ok", ModelNotAvailableError("gone")])

    report = run_taskset(provider, SPEC, taskset())
    failed = next(t for t in report.trials if t.task_id == "c")

    assert failed.passed is False
    assert failed.error is not None
    assert failed.error.startswith("model_not_available")


def test_per_tag_breakdown_groups_trials():
    provider = Scripted(["4", "ok", "x"])

    assert run_taskset(provider, SPEC, taskset()).by_tag() == {"math": (2, 2), "instr": (1, 1)}


def test_system_prompt_is_sent_when_the_task_defines_one():
    provider = Scripted(["ok"])
    task = Task(id="s", prompt="p", grader="exact", expected="ok", system="be terse")

    run_taskset(provider, SPEC, TaskSet(name="t", tasks=(task,)))

    assert provider.systems_seen[0] == ["system", "user"]


def test_frozen_baseline_taskset_loads_and_is_internally_valid():
    loaded = TaskSet.load("baseline-v1")

    assert len(loaded) == 14
    assert len({t.id for t in loaded}) == 14


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
    with pytest.raises(ConfigError, match="baseline-v1"):
        TaskSet.load("does-not-exist")
