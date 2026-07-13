---
paths:
  - "**/*.py"
---

# Django backend patterns

Stack-specific conventions for the backend. This overlay is installed into `.claude/rules/` only
when the **Python · Django** stack is selected. It complements the generic rules — read
`.claude/rules/code-organization.md`, `.claude/rules/design-patterns.md`, and
`.claude/rules/testing.md` first; this file makes them concrete for Django.

## Stack

- **Python 3.11+**, **Django 4.2+ / 5.0+**, **Django REST Framework (DRF)** (or standard Django views), and **Django ORM** as the data layer.
- Tests: Django built-in test runner (`django.test.TestCase`) or **pytest-django**.
- Tooling: **black** (formatting), **flake8** (linting) or **ruff**.

Run the project's own commands for these tasks (see the **Commands** section of `CLAUDE.md`):
install, run/dev, test, lint, format, migrate.

## Layered architecture (never skip a layer)

```
view/viewset (app/views.py)   HTTP only: validate/deserialize via Serializer, call service/manager, map errors → HTTP
→ service (app/services.py) optional business logic; raises domain errors; no DRF/HTTP imports
→ manager (app/managers.py) custom QuerySets and database query scopes
→ model (app/models.py)   Django ORM models & database schemas
serializer (app/serializers.py) DRF serializer models — the API contract
urls (app/urls.py)            explicit URL routing mapping endpoints to Views
```

Rules of thumb:
- **Views stay thin.** No raw database queries or complex business logic. Translate domain exceptions to DRF's `APIException` or HTTP status-specific exceptions.
- **Services/Managers never import DRF views.** They raise domain errors (e.g. `ObjectDoesNotExist`); the view decides the HTTP response status code.
- **Use transactions explicitly.** Django auto-commits transactions by default. Use `transaction.atomic` block wrappers in your services or views for multiple dependent database writes.
- **Serializers are separate from raw database outputs.** Always validate inbound data and sanitize outbound response shapes through DRF Serializers.

## Adding a new resource (the recipe)

To add `<thing>`:

1. **Model** — Declare class `<Thing>` in `app/models.py` (or `app/models/<thing>.py`).
2. **Serializer** — Define `<Thing>Serializer` in `app/serializers.py` with explicit fields.
3. **Manager / QuerySet** — (Optional) Add custom `<Thing>QuerySet` for encapsulated query scopes.
4. **View / ViewSet** — Define `<Thing>ViewSet` (or view functions) in `app/views.py`.
5. **URLs** — Map route in `app/urls.py` using DRF `DefaultRouter` or standard `path()`.
6. **Migration** — Generate database migration via `python manage.py makemigrations` and review it.
7. **Tests** — Create unit/integration tests in `app/tests/` covering serialization, business logic, and API HTTP responses.

## Conventions

- **Type everything.** Annotate public functions and methods per `.claude/rules/documentation.md`.
- **Settings via env.** Rely on `django-environ` or `python-decouple` in `settings.py`; never call `os.environ` directly outside settings.
- **Errors:** Raise standard Django exceptions (`ValidationError`, `ObjectDoesNotExist`) or domain-specific exceptions, then map them properly in your views to avoid leaking internal tracebacks.
- **Migrations are reviewed, not trusted.** Always run `makemigrations` and inspect the generated migration file before running `migrate`. Look closely at defaults, column renames, and nullable constraints.

## HTTP status & error mapping

This is the concrete mapping the view applies when translating domain results/errors to HTTP:

**Method → success status:**

| Operation | Method | Success status |
|---|---|---|
| Create | `POST` | `201 Created` |
| Read / list | `GET` | `200 OK` |
| Full/partial update | `PUT` / `PATCH` | `200 OK` (return the updated resource) |
| Delete | `DELETE` | `204 No Content` or `200 OK` |

**Domain exception → status:**

| Domain exception | Status |
|---|---|
| `ObjectDoesNotExist` / `<Thing>NotFoundError` | `404 Not Found` |
| `ValidationError` (e.g. bad inputs) | `400 Bad Request` / `422 Unprocessable Entity` |
| `PermissionDenied` | `403 Forbidden` |
| Conflict / IntegrityError | `409 Conflict` |

## Service-layer & ORM conventions

- **Avoid N+1 Queries.** When fetching related data, always use:
  * `select_related(*fields)` for forward Foreign Key and One-to-One relationships.
  * `prefetch_related(*fields)` for Many-to-Many and reverse Foreign Key relations.
- **Fat Models, Thin Views.** Enforce business logic inside Model methods, Custom QuerySets, or dedicated Service files. Keep Views focused only on request parsing and response mapping.
- **Soft delete.** If soft-deleting, use a custom Manager (e.g. `ActiveManager`) that filters out `is_deleted=True` by default.

## Naming on the wire

Keep field names **`snake_case` end to end** across models, serializers, and JSON outputs to match Django and Python ecosystem defaults.

## Reading live database state

When inspecting live database states, always use Django’s official tools:
* Use the Django interactive shell: `python manage.py shell`.
* Never run raw external scripts that bypass Django's configuration wrapper.

## Which tests to run for a change

Route by what changed:

| Changed | Run |
|---|---|
| a model/manager | `python manage.py test app.tests.test_models` |
| a serializer | `python manage.py test app.tests.test_serializers` |
| a view / URL | `python manage.py test app.tests.test_views` |
| cross-cutting changes | the full test suite via `python manage.py test` |

## Pre-removal search recipe

Before deleting any symbol or endpoint, run grep checks to clean up references across the project:

```bash
SYM=TheSymbolOrPath           # e.g. OrderViewSet  or  /api/v1/orders/

grep -rn "$SYM" app/                       # views, models, serializers, urls
grep -rn "$SYM" app/tasks/                 # background tasks or Celery workers
grep -rn "$SYM" app/migrations/            # migration history references
grep -rn "patch(.*$SYM\Vert{}from .*import.*$SYM" app/tests/   # test mocks and import patches