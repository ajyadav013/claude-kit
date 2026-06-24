# Scenario 05 — The test-coverage gate catches a real defect

Scenario [02](02-devils-advocate-catch.md) showed the *adversary* finding bugs beyond the tests. This
one shows the ordinary **test-coverage gate** doing its job: a developer's first cut of the core logic
was wrong, the suite went **RED**, and the gate refused to advance until the defect loop made it
**GREEN**. The point of contrast: a clean run (scenario 01) is earned, not assumed.

## The defect

The first implementation of two `TaskStore` behaviors was subtly broken:

- `complete(id)` looked the task up but **didn't set `done = True`** — completion was a no-op.
- `list(status="open")` returned **all** tasks instead of filtering out the done ones.

Both compile, both "look right," and a happy-path smoke test (create + list-all) passes. The defects
only surface against tests that assert the *post-conditions*.

## Gate: build-green + test-coverage — **RED** (`../evidence/05-pytest-red.txt`)

The real suite caught all three failing assertions — one integration, two unit:

```
examples/real-run/sample-app/tests/test_api.py ...F.                     [ 41%]
examples/real-run/sample-app/tests/test_store.py ...FF..                 [100%]

FAILED test_api.py::test_complete_task          - assert False is True
FAILED test_store.py::test_complete_marks_done  - assert False is True
FAILED test_store.py::test_list_filters_by_status - assert [1, 2] == [2]

3 failed, 9 passed in 2.59s
```

`test_list_filters_by_status` is the clearest tell: it expects `list(status="open")` to return `[2]`
after task 1 is completed, but got `[1, 2]` — the filter wasn't applied. A RED suite **blocks** the
pipeline; per the quality-gates rule a gate is PASS only with the suite green, so testing cannot
"mostly pass."

## The fix → **GREEN** (`../evidence/05-pytest-green.txt`)

The defect loop corrected both behaviors in `store.py`:

```python
def complete(self, task_id: int) -> Task:
    task = self._tasks[task_id]
    task.done = True          # was missing — completion was a no-op
    return task

def list(self, status: str | None = None) -> list[Task]:
    ...
    want_done = status == "done"
    return [t for t in tasks if t.done is want_done]   # was: return tasks (no filter)
```

Re-running the suite:

```
12 passed in 2.56s
```

## Why this matters

This is the unglamorous gate that earns the right to the clean run in scenario 01. The kit treats a
partially-green suite as a **block**, not a "9/12, good enough" — and the verdict is the actual pytest
output (`../evidence/05-pytest-red.txt` → `../evidence/05-pytest-green.txt`), not a summary of it. The
tests assert post-conditions (`done` flipped, filter applied), which is exactly what catches logic that
*looks* correct but isn't.
