---
schema_version: 1
id: django-async-patterns
description: Async Django — when ASGI beats WSGI, async views, the a-prefixed QuerySet API, disabling CONN_MAX_AGE, sync_to_async vs database_sync_to_async, Tasks vs Celery, async DRF via adrf. Use when adding async views or choosing ASGI.
invocation: implicit
capabilities: []
request_input:
  mode: none
pause_for_human: []
references:
- rule://django-patterns
---

Async Django is worth it for a specific set of workloads and a liability everywhere else. This
skill is mostly about telling those apart, then doing it correctly when the answer is yes.

Targets **Django 6.1**. Features newer than the 5.2 LTS name their version.

## When to use

- Deciding between WSGI and ASGI for a deployment
- Adding an `async def` view, or converting a sync one
- A view that fans out to several slow HTTP calls
- Choosing between Django 6.0's Tasks framework and Celery
- Making DRF work in an async project
- Debugging `SynchronousOnlyOperation` or connection exhaustion under ASGI

## First: do you actually need ASGI?

| Workload | Answer |
|---|---|
| CRUD over a database, server-rendered or JSON | **WSGI.** gunicorn with sync workers is correct and simpler. |
| WebSockets, Server-Sent Events, long-lived connections | **ASGI.** WSGI cannot express these. |
| One view fanning out to several slow third-party APIs | **ASGI**, for that view. Concurrency is the point. |
| High request volume, all database-bound | **WSGI.** The bottleneck is the database and its connections, and async does not add any. |
| "It feels more modern" | **WSGI.** |

Async is not a performance upgrade for database-bound Django. It moves the concurrency limit from
worker processes to the connection pool, and if the pool is the constraint you have gained a more
complicated way to hit the same ceiling.

Each transition between sync and async context costs roughly **1 ms**. A view that crosses that
boundary a handful of times per request has spent more than it saved.

## Running under ASGI

```bash
uv run uvicorn config.asgi:application --host 0.0.0.0 --reload --reload-include '*.html'
```

`--reload-include '*.html'` is needed because uvicorn's reloader watches Python files only;
without it template edits do not refresh.

### Disable `CONN_MAX_AGE`

```python
DATABASES["default"]["CONN_MAX_AGE"] = 0
```

Persistent connections must be **off** under async. `CONN_MAX_AGE` binds a connection to a thread,
and the async request path does not have the same thread-per-request guarantee, so connections leak
and the pool exhausts under load. Use the database backend's own pooling instead.

This is the single most common way an async Django deployment fails in production rather than in
development, because low traffic hides it.

## The async ORM surface

Every queryset method has an `a`-prefixed async twin:

```python
order = await Order.objects.aget(pk=pk)
await Order.objects.acreate(customer=user, total=0)
orders = [o async for o in Order.objects.filter(status="open")]
exists = await Order.objects.filter(pk=pk).aexists()
```

`AsyncPaginator` and `AsyncPage` are the paginator equivalents.

Querysets are still lazy; `async for` is what evaluates them. Forgetting the `await` on `aget()`
yields a coroutine that fails somewhere later and confusingly.

Calling the sync ORM from async context raises `SynchronousOnlyOperation`. That error is a
feature — it is Django refusing to block the event loop.

### `sync_to_async` and its transaction trap

`sync_to_async` opens **its own transaction context**. Code that needs transactional semantics
should therefore be a single sync function called through one `sync_to_async`, not several
separate calls that each get their own transaction:

```python
# Wrong — three transactions, no atomicity across them
await sync_to_async(order.save)()
await sync_to_async(payment.save)()

# Right — one sync function, one transaction, one crossing
@transaction.atomic
def _place(order, payment):
    order.save()
    payment.save()

await sync_to_async(_place)(order, payment)
```

This also minimises the ~1 ms crossings.

In a long-lived consumer (a WebSocket handler), use `channels.db.database_sync_to_async` instead.
It is `sync_to_async` plus `close_old_connections()`, which is what prevents a consumer from
holding a stale connection for the life of the socket.

## Background work: Tasks vs Celery

**Django 6.0** shipped a built-in Tasks framework (`django.tasks`) with database-backed enqueue.
It has **no built-in worker process** — enqueueing is solved, execution is not, and you still
supply infrastructure to run the tasks.

| Need | Use |
|---|---|
| Fire-and-forget, already have a worker story | `django.tasks` (6.0+) |
| Periodic / scheduled jobs | **Celery** (+ django-celerybeat) |
| Chains, groups, chords | **Celery** |
| Per-task retry policies, backoff | **Celery** |
| Result backend, monitoring (Flower) | **Celery** |

Tasks is not a Celery replacement for anything beyond simple enqueue. cookiecutter-django still
offers Celery for exactly this reason.

## DRF in an async project

DRF has **no first-class async support**. Its views, permissions, and serializers are sync.

[`adrf`](https://github.com/em1208/adrf) bridges the gap with async class- and function-based
views. It works, but it is third-party, it does not cover the whole DRF surface, and mixing async
views with sync permission classes reintroduces the crossings you were trying to avoid.

Three honest options:

1. **Keep DRF sync under WSGI**, and run genuinely async work elsewhere. Best for a mostly-CRUD
   API with a few slow endpoints.
2. **DRF + `adrf`** for the handful of views that need it. Accept the partial coverage.
3. **Django Ninja** if the API is async throughout. It is async-first on Pydantic v2 — see
   `django-rest-framework-patterns` for the tradeoff.

Do not convert an entire DRF API to `adrf` expecting a speedup. A database-bound API gets slower,
because every ORM call becomes a boundary crossing.

## Anti-patterns to avoid

1. **`CONN_MAX_AGE` left non-zero under ASGI** — connection leak that only appears under load.
2. **Sync ORM calls in an `async def` view** — `SynchronousOnlyOperation`, or a blocked event loop
   if wrapped carelessly.
3. **Several `sync_to_async` calls where one transaction was needed** — each gets its own
   transaction context.
4. **`sync_to_async` in a long-lived consumer** — use `database_sync_to_async` so connections are
   closed.
5. **Choosing ASGI for a database-bound CRUD app** — moves the ceiling without raising it.
6. **Sprinkling `async def` on views that only touch the ORM** — pure overhead.
7. **Treating `django.tasks` as a Celery replacement** — no worker, no scheduling, no chains.
8. **Converting a whole DRF API to `adrf`** — partial coverage and more crossings.
9. **Forgetting `await` on an `a`-prefixed call** — fails later, far from the cause.
10. **Blocking calls (`requests`, `time.sleep`) in an async view** — stalls the entire event loop,
    not just that request.

## References

- `django-rest-framework-patterns` — the sync DRF layer and the Ninja alternative
- `django-service-patterns` — the services layer these views call
- `rule://django-patterns` — the installed overlay rule, incl. the WSGI/ASGI decision
