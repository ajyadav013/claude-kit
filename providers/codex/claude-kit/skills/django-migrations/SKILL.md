---
name: django-migrations
description: Django migration safety — schema and data never mixed, idempotent RunPython, atomic=False, batched backfills, expand/contract for zero downtime, the safe squash sequence, a CI drift check. Use when changing models or writing a migration.
---

Migrations are the part of a Django change that runs against production data once and cannot be
retried casually. This skill is the set of rules that keeps that safe.

## When to use

- Any model change that produces a migration
- Writing a data migration or a backfill
- Making a schema change without taking downtime
- Squashing an app's migration history
- A migration that timed out, locked a table, or half-applied

## The rules

### One migration does one thing

Never mix a schema change and a data migration in one file. They have different failure modes and
different rollback stories: a schema change is usually reversible by another schema change, while a
data migration may be irreversible. Mixed together, a failure halfway leaves you with neither a
clean schema nor clean data.

Split into: schema migration → data migration → (later) schema cleanup.

### Review the generated file, always

`makemigrations` guesses. It is very good at additive changes and unreliable at renames — a field
rename is frequently emitted as a drop plus an add, which is silent data loss.

Read every generated migration before committing. Look at:

- `RemoveField` / `AddField` pairs that should have been `RenameField`
- Defaults on a new non-nullable column, which rewrite every row
- `unique=True` added to a populated column, which fails on the first duplicate
- Anything referencing a model in another app, which creates a cross-app dependency

### CI must fail on missing migrations

```bash
uv run python manage.py makemigrations --check --dry-run
```

Non-zero exit means a model change was committed without its migration. Without this check the
failure surfaces at deploy time on someone else's branch.

### Data migrations: idempotent, batched, and reversible-or-explicit

```python
def backfill_slugs(apps, schema_editor):
    Article = apps.get_model("content", "Article")
    batch = []
    for article in Article.objects.filter(slug="").iterator(chunk_size=2000):
        article.slug = slugify(article.title)
        batch.append(article)
        if len(batch) >= 2000:
            Article.objects.bulk_update(batch, ["slug"])
            batch.clear()
    if batch:
        Article.objects.bulk_update(batch, ["slug"])

class Migration(migrations.Migration):
    atomic = False
    operations = [migrations.RunPython(backfill_slugs, migrations.RunPython.noop)]
```

Four things matter here:

- **`apps.get_model`, never a direct import.** The historical model matches the schema at this
  point in history; your current model class does not.
- **Filter to the un-migrated rows** (`slug=""`). That is what makes a re-run after a partial
  failure safe, and it is essential once `atomic = False` means partial application is possible.
- **`.iterator()` + `bulk_update`** so a large table does not load into memory or issue one UPDATE
  per row.
- **A reverse function**, even if it is `RunPython.noop`. Omitting it makes the migration
  irreversible and blocks `migrate <app> <previous>` entirely.

`atomic = False` is what lets a long backfill avoid holding one transaction across millions of
rows — at the cost of partial application on failure, which is exactly why the idempotent filter is
not optional.

Note that zero-downtime migration backends improve schema and `RunSQL` operations but do **not**
change `RunPython` behaviour, and they generally do not wrap migrations in a transaction except
around `RunPython`.

### Zero downtime: expand, migrate, contract

Old and new code run simultaneously during a deploy, so every intermediate state must be valid for
both.

Adding a non-nullable column:

1. **Expand** — add it nullable, no default. (A default on a populated table rewrites every row and
   takes a lock.)
2. **Backfill** — separate data migration, batched as above.
3. **Deploy code** that writes the column on every path.
4. **Contract** — set `NOT NULL` once no rows are null.

Removing a column:

1. Deploy code that no longer reads or writes it.
2. *Then* drop it. Dropping first breaks the still-running old instances mid-deploy.

Renaming anything is the same shape: add new, dual-write, backfill, switch reads, drop old. There
is no safe atomic rename across a rolling deploy.

### The safe squash sequence

Squashing is safe only if every environment passes through the state where both the squash and the
originals exist.

1. `squashmigrations <app> <start> <end>`
2. Deploy the squash **with `replaces=[...]` intact and the old files still present**.
3. Wait until every environment — including the slowest staging box and any long-lived branch —
   has applied it.
4. Delete the replaced migration files.
5. Remove the `replaces=[...]` entry.
6. Deploy the cleanup.

Collapsing steps 2–6 into one deploy is how an environment that had not yet applied the originals
ends up unable to resolve its history.

## Anti-patterns to avoid

1. **Schema and data in one migration** — no clean recovery from a half-failure.
2. **Importing the real model in `RunPython`** — it reflects today's schema, not this point in
   history.
3. **A backfill with no filter** — cannot be safely re-run, which matters most under
   `atomic = False`.
4. **`bulk_update` over an unbatched queryset** — loads the table into memory.
5. **Adding a non-nullable column with a default to a large table** — full rewrite plus a lock.
6. **`unique=True` on a populated column in one step** — fails on the first duplicate, after
   partially applying.
7. **Dropping a column in the same deploy that stops using it** — old instances are still running.
8. **Editing an already-applied migration** — environments that ran the old version diverge
   silently.
9. **No reverse function** — blocks rollback of that app entirely.
10. **Squashing and deleting the originals in one deploy** — strands any environment that had not
    caught up.
11. **No `makemigrations --check` in CI** — missing migrations are found at deploy time.

## References

- `django-service-patterns` — model and app layout that these migrations act on
- `risk-classification` — DB migrations classify as sensitive; high-risk changes
  need rollback notes
- `django-patterns` — the installed overlay rule
