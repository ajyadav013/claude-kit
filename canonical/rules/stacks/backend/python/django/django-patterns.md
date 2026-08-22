# Django backend patterns

Stack-specific conventions for the backend. This overlay is installed into `artifact://rules-directory/` only
when the **Python · Django** stack is selected. It complements the generic rules — read
`rule://code-organization`, `rule://design-patterns`, and
`rule://testing` first; this file makes them concrete for Django.

Depth lives in the skills this stack installs: `django-service-patterns` (layout, settings,
services), `django-rest-framework-patterns` (the API layer), `django-migrations`,
`django-async-patterns`, and `django-react-integration`. This rule carries only the decisions that
must not be got wrong, and points at the skill for the rest.

## Stack

- **Python 3.12+**, **Django 6.1**, **Django REST Framework (DRF)**, and the **Django ORM** as the
  data layer. Version-sensitive advice below names the release it landed in, so a project pinned to
  the **5.2 LTS** can tell what does not yet apply.
- Dependencies: **uv**. Tests: **pytest-django**. Lint/format: **ruff** (+ **mypy**).

Run the project's own commands for these tasks (see the **Commands** section of `artifact://project-instructions`):
install, run/dev, test, lint, format, migrate, make-migration.

## Project layout

Two tiers, and do not collapse them:

```
config/            project package — settings/, urls.py, wsgi.py, asgi.py
  settings/
    base.py        everything shared
    local.py       DEBUG, dev-only apps           } each imports from base
    production.py  hardened, secrets from env     }
<project>/         your apps live here, one directory per domain unit
  users/           models.py managers.py services.py serializers.py views.py urls.py tests/
  orders/
```

- **Split settings, never one `settings.py` with `if DEBUG:` branches.** The branchy single file is
  how a dev-only default reaches production.
- **Read config through `django-environ`**, and only inside `config/settings/`. No `os.environ`
  anywhere else — a setting read at import time in an app module is unmockable in tests and
  invisible to `check --deploy`.
- **An app is a domain unit**, not a layer. `orders/`, not `models/`.

## Define a custom user model in the first migration

```python
# users/models.py
class User(AbstractUser): ...

# config/settings/base.py
AUTH_USER_MODEL = "users.User"
```

Swapping `AUTH_USER_MODEL` after the initial migration is one of the genuinely painful migrations in
Django — it is a hard dependency of `auth`, `admin`, and every `ForeignKey` already pointing at it.
Do it on day one even when the model is empty. Reference the user model as
`settings.AUTH_USER_MODEL` in FKs and `get_user_model()` at runtime; never import `User` directly.

## Layered architecture (never skip a layer)

```
view/viewset (app/views.py)   HTTP only: validate/deserialize via Serializer, call service/manager, map errors → HTTP
→ service (app/services.py) business logic; raises domain errors; no DRF/HTTP imports
→ manager (app/managers.py) custom QuerySets and database query scopes
→ model (app/models.py)     Django ORM models & database schemas
serializer (app/serializers.py) DRF serializer — the API contract
urls (app/urls.py)            explicit URL routing mapping endpoints to views
```

Rules of thumb:

- **Views stay thin.** No raw database queries and no business logic. Translate domain exceptions
  into DRF's `APIException` subclasses.
- **Services and managers never import DRF or views.** They raise domain errors; the view alone
  decides the status code. This is what keeps the logic callable from a management command, a
  Celery task, or a test without an HTTP request.
- **Fat models, thin views.** Behaviour belongs on the model, a custom `QuerySet`/manager, or
  `services.py` — reach for `services.py` once the logic spans more than one model.
- **Transactions are explicit.** Django autocommits per query. Wrap multi-write operations in
  `transaction.atomic`, and use `transaction.on_commit()` for anything with an external side effect
  (email, task enqueue, webhook) so it cannot fire for a rolled-back write.
- **Serializers are the boundary.** Validate everything inbound and shape everything outbound
  through them; never return a model `__dict__` or `values()` straight to the client.

## Adding a new resource (the recipe)

To add `<thing>`:

1. **Model** — declare `<Thing>` in `app/models.py` (or `app/models/<thing>.py`).
2. **Manager / QuerySet** — add `<Thing>QuerySet` for any query scope used more than once.
3. **Service** — put the business rules in `app/services.py` if they span models or have side effects.
4. **Serializer** — define `<Thing>Serializer` with an **explicit** `fields` tuple.
5. **View / ViewSet** — define `<Thing>ViewSet` in `app/views.py`; select/prefetch in `get_queryset()`.
6. **URLs** — register on the router in `app/urls.py`.
7. **Migration** — generate it, then **read it** before committing.
8. **Tests** — `app/tests/` covering the service, the serializer, and the endpoint's status codes.

## Conventions

- **Type everything.** Annotate public functions and methods per `rule://documentation`.
- **Errors:** raise Django or domain exceptions (`ValidationError`, `ObjectDoesNotExist`,
  `PermissionDenied`), then map them in the view. Never let a traceback reach a client.
- **Migrations are reviewed, not trusted.** `makemigrations` guesses, and it guesses worst at
  renames — a field rename frequently emits as a drop plus an add, which is silent data loss. Read
  every generated file. See the `django-migrations` skill.
- **`makemigrations --check --dry-run` runs in CI.** Non-zero exit means a model change was
  committed without its migration. Without this gate, that surfaces at deploy time on someone
  else's branch.

## HTTP status & error mapping

The concrete mapping the view applies when translating domain results and errors to HTTP:

**Method → success status:**

| Operation | Method | Success status |
|---|---|---|
| Create | `POST` | `201 Created` |
| Read / list | `GET` | `200 OK` |
| Full/partial update | `PUT` / `PATCH` | `200 OK` (return the updated resource) |
| Delete | `DELETE` | `204 No Content` |

**Domain exception → status:**

| Domain exception | Status |
|---|---|
| `ObjectDoesNotExist` / `<Thing>NotFoundError` | `404 Not Found` |
| `ValidationError` (bad inputs) | `400 Bad Request` |
| `PermissionDenied` | `403 Forbidden` |
| `IntegrityError` / domain conflict | `409 Conflict` |

## ORM conventions

- **Fix N+1 in `get_queryset()`, not in the serializer.** A nested serializer issues one query per
  row, and the serializer is the wrong place to notice:
  - `select_related(*fields)` — forward `ForeignKey` and `OneToOne` (SQL join).
  - `prefetch_related(*fields)` — `ManyToMany` and reverse `ForeignKey` (second query).
- **Assert the query count** with `django_assert_num_queries`. An N+1 that is only slow does not
  fail a test; a pinned count does.
- **`.only()` / `.defer()` are a trap without care** — a deferred field touched later triggers a
  per-row query, which is the N+1 you were avoiding.
- **Soft delete via a custom manager** (e.g. `ActiveManager`) filtering `is_deleted=True` by
  default. Keep an unfiltered manager available for admin and data repair.
- **`bulk_create` / `bulk_update` skip `save()` and signals.** That is the point, and it is also
  the bug when something downstream depended on a signal.

## Naming on the wire

Keep field names **`snake_case` end to end** across models, serializers, and JSON, matching the
Django and Python ecosystem default. Do not camel-case at the serializer boundary just to suit a
JavaScript client — see `django-react-integration` for generating a typed client instead.

## WSGI or ASGI

Pick deliberately; it constrains everything downstream.

| Workload | Deploy under |
|---|---|
| CRUD over a database, server-rendered or JSON | **WSGI** — gunicorn sync workers. Simpler, and correct. |
| WebSockets, SSE, long-lived connections | **ASGI** — WSGI cannot express these. |
| A view fanning out to several slow third-party APIs | **ASGI** for concurrency on that path. |
| High volume, all database-bound | **WSGI** — the ceiling is the connection pool, and async does not raise it. |

Under ASGI, **`CONN_MAX_AGE` must be `0`** — persistent connections bind to a thread that the async
request path does not guarantee, so the pool leaks under load and only under load. DRF is sync-only;
see `django-async-patterns` before converting anything.

## Which tests to run for a change

Route by what changed (`pytest` scoped to the area; see `artifact://project-instructions` Commands):

| Changed | Run |
|---|---|
| a model / manager | that app's `tests/test_models.py` |
| a service | that app's `tests/test_services.py` |
| a serializer | serializer tests **and** the API tests — the serializer is the wire contract |
| a view / URL | that app's `tests/test_views.py` |
| settings, middleware, or cross-cutting | the full suite |

Use `pytest.mark.django_db` deliberately: a test that does not need the database should not take
it, and one that does should say so rather than relying on a fixture side effect.

## Reading live database state

Use Django's own entry points, so settings, apps, and connection routing are loaded:

```bash
uv run python manage.py shell        # or shell_plus with django-extensions
uv run python manage.py dbshell      # raw SQL, through Django's configured credentials
```

Never point an ad-hoc script at the database URL directly — it bypasses database routers, the
connection settings, and any test-database guard.

## The `:3000` trap (projects with a bundled frontend pipeline)

If the project was generated with a cookiecutter-django frontend pipeline (Gulp or Webpack),
`npm run dev` runs the asset build and Django together and the URL to open is
**`http://localhost:3000`**. Opening `:8000` serves pages — Django is up — but unstyled with every
static asset 404ing, which reads as a broken install. Check the port before reinstalling anything.
With no frontend pipeline, `:8000` is correct. See `django-react-integration`.

## Pre-removal search recipe

Before deleting a symbol or endpoint, sweep every surface:

```bash
SYM=TheSymbolOrPath           # e.g. OrderViewSet  or  /api/v1/orders/

grep -rn "$SYM" <project>/                     # views, models, services, serializers, urls
grep -rn "$SYM" <project>/*/tasks.py           # Celery tasks and management commands
grep -rn "$SYM" <project>/*/migrations/        # migration history references
grep -rn "$SYM" config/                        # settings, root urls, middleware paths
grep -rn "patch(.*$SYM\|from .*import.*$SYM" <project>/*/tests/   # test mocks and import patches
```

Two Django-specific ways a removal fails silently: a `unittest.mock.patch("...OrderService")`
target that no longer resolves patches nothing and the test still passes, and a migration
referencing a deleted model breaks history for anyone who has not applied it yet. Remove one symbol
at a time and run that area's tests.
