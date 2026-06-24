# Scenario 01 — Standard feature (happy path)

**Request:** *"Build a task tracker: create tasks with a title and priority, list them with an
optional open/done filter, complete them, and expose it over a small HTTP API with a health check."*

This is the full pipeline on a clean change — spec → story breakdown → implementation → blind code
review → build/test gates → independent acceptance. The implemented result is
[`../sample-app/`](../sample-app/).

## Spec (abridged)

**Acceptance criteria**

1. `POST /tasks` creates a task from `{title, priority?}`; `priority ∈ {low, medium, high}`, default `medium`.
2. `GET /tasks` lists tasks; optional `?status=open|done` filter.
3. `POST /tasks/{id}/complete` marks a task done.
4. Invalid input (empty title, bad priority, unknown status) → `4xx` with an `{error}` message.
5. `GET /health` returns status + version.

**Non-goals (explicit):** persistence, authentication, multi-process concurrency — it's a demo.

## Story breakdown (`story-planner`)

| Story | Maps to criteria | Lane |
|---|---|---|
| Domain: `Task` + `TaskStore` (add/get/complete/list+filter, validation) | 1–4 | backend |
| Transport: stdlib HTTP API over the store | 1–3, 5 | backend |
| Unit tests (domain) + integration tests (API on an ephemeral port) | 1–5 | test |

Every acceptance criterion maps to ≥1 story (coverage gate **1f** satisfied) before implementation.

## Gate: build-green + test-coverage — **PASS**

Real output (`../evidence/01-pytest-green.txt`, `../evidence/01-lint.txt`):

```
12 passed in 2.59s
```
`ruff check` → `All checks passed!`

## Gate: code review (`sdlc-code-reviewer`) — **PASS** (with noted demo limitations)

The real review approved the code for its purpose and flagged, at the right severities, what would
matter in production — **thread-unsafe shared state** (`store.py`), **unbounded memory growth**, and a
**missing request-size cap** (`api.py`) — as documented demo limitations, nothing blocking. (Full
findings were also the seed for scenario 02.)

## Gate: acceptance (`acceptance-reviewer`) — **ACCEPT**

Independent, criterion-by-criterion verdict against the real code **and** tests — every criterion
**MET** with cited evidence:

| Criterion | Verdict | Evidence (file:line) |
|---|---|---|
| 1 create w/ priority | MET | `api.py` POST handler + `store.add` allowlist; `test_api.py::test_create_and_list_task`, `test_store.py::test_add_and_get` |
| 2 list + filter | MET | `store.list(status=...)`; `test_store.py::test_list_filters_by_status` |
| 3 complete | MET | `store.complete`; `test_api.py::test_complete_task`, `test_complete_missing_returns_404` |
| 4 invalid → 4xx | MET | `ValidationError` → 400; `test_create_rejects_empty_title`, `test_add_rejects_bad_priority`, `test_list_rejects_unknown_status` |
| 5 health | MET | `/health` → status+version; `test_api.py::test_health` |

> A clean run is the baseline. Scenario [02](02-devils-advocate-catch.md) is what happened when the
> kit refused to trust that clean run.
