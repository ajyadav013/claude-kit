# sample-app — task tracker (stdlib only)

The real application the [`/sdlc` run](../README.md) was executed against. Deliberately tiny and
**dependency-free** (Python standard library only) so every gate check reproduces anywhere.

```
tasktracker/
  store.py    # domain layer: Task + TaskStore (add / get / complete / list+filter, validation)
  api.py      # transport layer: http.server JSON API (/health, GET+POST /tasks, complete)
tests/
  test_store.py   # unit tests for the domain
  test_api.py     # integration tests — a real server on an ephemeral port
run-checks.sh      # the exact lint + test commands whose output backs the gate verdicts
```

## Run the checks

```bash
bash run-checks.sh
# or, from the repo root:
python -m pytest examples/real-run/sample-app/tests -v
ruff check examples/real-run/sample-app/tasktracker examples/real-run/sample-app/tests
```

## The API

| Method & path | Behavior |
|---|---|
| `GET /health` | `{"status": "ok", "version": "0.1.0"}` |
| `POST /tasks` | create a task from `{"title": ..., "priority": "low\|medium\|high"}` → `201` |
| `GET /tasks?status=open\|done` | list tasks, optional status filter |
| `POST /tasks/{id}/complete` | mark a task done → `200` (or `404`) |

Invalid input (empty title, bad priority, unknown status filter, a non-object JSON body, or a
malformed `Content-Length`) returns a `4xx` with an `{"error": ...}` message rather than crashing —
the last two were [hardened after the Devil's Advocate found them](../scenarios/02-devils-advocate-catch.md).

> It's a demo: in-memory only, no auth, single-process. The [security review](../scenarios/04-security-block.md)
> spells out what production would additionally require.
