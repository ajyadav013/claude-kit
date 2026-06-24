"""In-memory task store — the pure-Python domain layer.

No third-party dependencies; everything here is standard library so the example
runs anywhere (including CI) with no install step.
"""

from __future__ import annotations

from dataclasses import dataclass, field

PRIORITIES = ("low", "medium", "high")
STATUS_FILTERS = ("open", "done")


class ValidationError(ValueError):
    """Raised when a task cannot be created from the given input."""


@dataclass
class Task:
    """A single to-do item."""

    id: int
    title: str
    priority: str = "medium"
    done: bool = False

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "priority": self.priority,
            "done": self.done,
        }


@dataclass
class TaskStore:
    """A minimal in-memory task collection with id assignment and filtering."""

    _tasks: dict[int, Task] = field(default_factory=dict)
    _next_id: int = 1

    def add(self, title: str, priority: str = "medium") -> Task:
        title = (title or "").strip()
        if not title:
            raise ValidationError("title must not be empty")
        if priority not in PRIORITIES:
            raise ValidationError(f"priority must be one of {', '.join(PRIORITIES)}")
        task = Task(id=self._next_id, title=title, priority=priority)
        self._tasks[task.id] = task
        self._next_id += 1
        return task

    def get(self, task_id: int) -> Task:
        return self._tasks[task_id]

    def complete(self, task_id: int) -> Task:
        task = self._tasks[task_id]
        task.done = True
        return task

    def list(self, status: str | None = None) -> list[Task]:
        tasks = sorted(self._tasks.values(), key=lambda t: t.id)
        if status is None:
            return tasks
        if status not in STATUS_FILTERS:
            raise ValidationError("status filter must be 'open', 'done', or omitted")
        want_done = status == "done"
        return [t for t in tasks if t.done is want_done]
