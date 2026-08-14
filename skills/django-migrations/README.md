# django-migrations

Encodes migration safety for Django: keeping schema and data changes in separate migrations,
reviewing what `makemigrations` guessed, writing idempotent batched `RunPython` backfills under
`atomic = False`, sequencing expand/contract so a rolling deploy never sees an invalid state, and
the multi-deploy squash sequence that does not strand a lagging environment.

## What this skill covers

- One migration, one thing — why mixing schema and data has no clean recovery
- Reviewing generated migrations: rename-as-drop-plus-add, defaults on large tables, `unique=True`
  on populated columns
- `makemigrations --check --dry-run` as a CI gate
- Data migrations: `apps.get_model`, filtering to un-migrated rows, `.iterator()` + `bulk_update`,
  and always supplying a reverse (even `noop`)
- Why `atomic = False` makes the idempotent filter mandatory rather than nice to have
- Expand → backfill → deploy → contract for adding a non-nullable column; reverse order for drops
- The six-step safe squash, and why steps 2–6 cannot collapse into one deploy

## Provenance

Written for **Django 6.1**. Notes that zero-downtime migration backends improve schema and `RunSQL`
operations but do not change `RunPython` semantics — a distinction that is easy to assume away when
such a backend is installed.

## How to apply

1. Read before writing any migration that touches a populated table.
2. Split schema from data as the first move, not as cleanup.
3. Add the `makemigrations --check` step to CI once, so the rule is enforced rather than
   remembered.
4. For the models these migrations act on, see `django-service-patterns`.
5. Migrations classify as sensitive under `.claude/rules/risk-classification.md`; high-risk ones
   need rollback notes before they ship.
