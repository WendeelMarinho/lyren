from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from lyren_core.errors import ConfigError
from lyren_eval.graders import GRADERS

TASKSETS_DIR = Path(__file__).resolve().parent / "tasksets"


@dataclass(frozen=True, slots=True)
class Task:
    id: str
    prompt: str
    grader: str
    expected: object
    tags: tuple[str, ...] = ()
    system: str | None = None
    max_output_tokens: int = 64

    def grade(self, answer: str) -> bool:
        return GRADERS[self.grader](answer, self.expected)


@dataclass(frozen=True, slots=True)
class TaskSet:
    name: str
    tasks: tuple[Task, ...]

    def __iter__(self) -> Iterator[Task]:
        return iter(self.tasks)

    def __len__(self) -> int:
        return len(self.tasks)

    @classmethod
    def from_jsonl(cls, path: Path) -> TaskSet:
        tasks: list[Task] = []
        seen: set[str] = set()
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip() or line.lstrip().startswith("//"):
                continue
            raw = json.loads(line)
            grader = str(raw["grader"])
            if grader not in GRADERS:
                raise ConfigError(f"{path.name}:{line_number} unknown grader {grader!r}")
            task_id = str(raw["id"])
            if task_id in seen:
                raise ConfigError(f"{path.name}:{line_number} duplicate task id {task_id!r}")
            seen.add(task_id)
            tasks.append(
                Task(
                    id=task_id,
                    prompt=str(raw["prompt"]),
                    grader=grader,
                    expected=raw["expected"],
                    tags=tuple(str(t) for t in raw.get("tags", ())),
                    system=raw.get("system"),
                    max_output_tokens=int(raw.get("max_output_tokens", 64)),
                )
            )
        if not tasks:
            raise ConfigError(f"{path.name} contains no tasks")
        return cls(name=path.stem, tasks=tuple(tasks))

    @classmethod
    def load(cls, name: str) -> TaskSet:
        path = TASKSETS_DIR / f"{name}.jsonl"
        if not path.is_file():
            available = sorted(p.stem for p in TASKSETS_DIR.glob("*.jsonl"))
            raise ConfigError(f"no taskset {name!r}; available: {available}")
        return cls.from_jsonl(path)
