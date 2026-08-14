# django-async-patterns

Encodes when async Django is worth it and how to do it safely: the WSGI-vs-ASGI decision, the
`a`-prefixed queryset API, why `CONN_MAX_AGE` must be zero under ASGI, the transaction trap in
`sync_to_async`, Django 6.0's Tasks framework versus Celery, and the real state of async DRF.

Much of this skill is about *not* going async. Async is not a performance upgrade for
database-bound Django — it relocates the concurrency ceiling rather than raising it.

## What this skill covers

- A decision table for WSGI vs ASGI, including the workloads where WSGI is the right answer
- The ~1 ms cost of each sync/async context switch, and why it dominates chatty views
- `CONN_MAX_AGE = 0` under ASGI — the failure that hides in development and appears under load
- `aget` / `acreate` / `aexists` / `async for`, `AsyncPaginator`, and `SynchronousOnlyOperation`
  as a feature rather than an obstacle
- `sync_to_async` opening its own transaction context, and collapsing multi-write work into one
  sync function
- `channels.db.database_sync_to_async` for long-lived consumers
- Django 6.0 Tasks (DB-backed enqueue, **no worker process**) vs Celery for scheduling, chains,
  and retries
- Async DRF via `adrf`, its partial coverage, and the three honest options

## Provenance

Written for **Django 6.1**; the Tasks framework is noted as 6.0+. `adrf` is third-party
(github.com/em1208/adrf) and is presented with its limits rather than as a drop-in.

## How to apply

1. Start with the decision table. If the answer is WSGI, stop — the rest is not needed.
2. If deploying ASGI, set `CONN_MAX_AGE = 0` before anything else.
3. Keep transactional work inside a single sync function crossed once via `sync_to_async`.
4. For the API layer, see `django-rest-framework-patterns`.
