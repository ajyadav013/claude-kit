---
name: django-service-patterns
description: Django project structure — two-tier layout, split settings, apps as domain units, fat models and thin views, a services layer, custom user model, pytest-django, cookiecutter bootstrap. Use when building or restructuring a Django project.
---

Standardize Django project structure, settings layering, and the model/service/view split so a
project stays navigable as it grows past its first few apps.

Targets **Django 6.1** (current). Features newer than the 5.2 LTS are marked with the version that
introduced them, so a project on LTS can tell what it cannot use yet.

## When to use

- Starting a Django project, or generating one from cookiecutter-django
- Adding an app and deciding what belongs in models, services, or views
- Splitting a `settings.py` that has grown environment conditionals
- Deciding where business logic lives when views and models both look plausible
- Setting up pytest-django on a project using the built-in test runner

## Core conventions

### Two-tier layout

Configuration and application code are separate trees. `config/` holds the project's wiring;
the project package holds the apps.

```
manage.py
config/
  settings/
    base.py          # everything shared
    local.py         # DEBUG, dev-only apps
    production.py    # hardened; fails loudly on a missing secret
  urls.py
  wsgi.py
  asgi.py            # only if you serve async — see django-async-patterns
<project>/
  users/             # one app per domain concept
    migrations/
    models.py
    services.py
    selectors.py
    admin.py
    apps.py
    tests/
```

`manage.py startapp` drops the app in the repo root. Move it under `<project>/`, then set
`name = "<project>.<app>"` in its `apps.py` `AppConfig` and register it in `LOCAL_APPS` in
`config/settings/base.py`. Skipping the `apps.py` edit is the usual cause of a confusing
`ModuleNotFoundError` at startup.

### Settings: split by environment, read by django-environ

`base.py` holds every shared setting. `local.py` and `production.py` import from it and override.
Nothing reads `os.environ` outside the settings package.

```python
# config/settings/base.py
import environ

env = environ.Env()
DEBUG = env.bool("DJANGO_DEBUG", default=False)
DATABASES = {"default": env.db("DATABASE_URL")}

LOCAL_APPS = ["myproject.users", "myproject.billing"]
INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS
```

```python
# config/settings/production.py
from .base import *  # noqa: F403

SECRET_KEY = env("DJANGO_SECRET_KEY")   # no default — fail at boot, not at first request
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS")
```

Give production settings **no defaults** for secrets. A default is how a placeholder key reaches
production and stays there unnoticed.

**Django 6.1** replaces the flat `EMAIL_*` settings with a `MAILERS` dict, shaped like `DATABASES`
and `CACHES`, and deprecates the old ones. New projects should write `MAILERS`; a project on 5.2
keeps `EMAIL_BACKEND` and friends.

### Custom user model from the first commit

```python
# myproject/users/models.py
from django.contrib.auth.models import AbstractUser

class User(AbstractUser):
    pass
```

Set `AUTH_USER_MODEL = "users.User"` in `base.py` before the first `migrate`. Swapping the user
model after tables exist is a migration surgery job — the cheapest correct decision in a Django
project is making this one on day one, even if the model is empty.

### Fat models, thin views, and a services layer

Three homes for logic, in order of preference:

| Logic | Home |
|---|---|
| Invariants and behaviour of one object | Model method |
| Reusable query scopes | Custom `QuerySet` / `Manager` |
| A workflow spanning several models, or with side effects | `services.py` |
| HTTP concerns only | View |

A service function takes plain arguments, does the work in a transaction, and raises domain
errors. It never imports from `views.py` and never returns an HTTP response.

```python
# myproject/billing/services.py
from django.db import transaction

@transaction.atomic
def refund_order(*, order: Order, reason: str) -> Refund:
    """Reverse a captured payment. Raises AlreadyRefunded if one exists."""
    if order.refunds.exists():
        raise AlreadyRefunded(order.pk)
    refund = Refund.objects.create(order=order, amount=order.total, reason=reason)
    order.mark_refunded()
    return refund
```

Some teams also split **selectors** (read paths) from **services** (write paths). Worth doing once
read logic grows conditional; not worth it on day one.

### Transactions are explicit

Django autocommits each query. Any operation where two writes must both land needs
`transaction.atomic` — as a decorator on the service, or a `with` block around the narrowest
region that needs it. Wrapping an entire view in `atomic` holds the connection for the whole
request, including template rendering; keep the block tight.

### ORM query discipline

- `select_related` for forward FK and one-to-one; `prefetch_related` for M2M and reverse FK.
- Fix N+1 in the queryset that feeds the view, not in the template or serializer.
- `.only()` / `.defer()` are for genuinely wide rows, and they bite when a deferred field is
  touched later — measure before reaching for them.
- **Django 6.1** adds *fetch modes*: `FETCH_PEERS` collapses most accidental N+1 into two queries.
  It is a safety net, not a substitute for saying what you need.
- `.exists()` beats `len(qs)` for presence; `.count()` beats loading rows to count them.
- All new models default to 64-bit `BigAutoField` as of **Django 6.0**.

### Testing with pytest-django

```python
# pyproject.toml
[tool.pytest.ini_options]
DJANGO_SETTINGS_MODULE = "config.settings.local"
python_files = ["test_*.py"]
```

- `@pytest.mark.django_db` for anything touching the ORM; the default is no database access, which
  keeps pure tests honest and fast.
- `django_db(transaction=True)` only when testing transaction behaviour itself — it is much slower.
- Build objects with factories, not fixtures loaded from JSON, so a schema change breaks the
  factory once rather than every fixture file.
- Test services directly. They take plain arguments and raise domain errors, so most business
  logic needs no HTTP client at all.

## Bootstrapping from cookiecutter-django

cookiecutter-django generates exactly the layout above, with batteries attached (allauth,
django-environ, Celery, whitenoise, Anymail, Sentry). The prompts that shape the result — and what
each one commits you to — are in
[cookiecutter-django.md](references/cookiecutter-django.md).

The trap worth stating up front: if you pick a `frontend_pipeline` of **Gulp or Webpack**, the dev
server you open is **`:3000`**, not `:8000`. Hitting `:8000` gives you unstyled pages and 404s on
static files, which reads like a broken install rather than the wrong port.

## Anti-patterns to avoid

1. **A single `settings.py` with `if DEBUG:` branches** — the production path is then only ever
   exercised in production.
2. **Deferring the custom user model** — cheap now, migration surgery later.
3. **Business logic in views** — untestable without an HTTP client, and unreusable from a
   management command or Celery task.
4. **Business logic in serializers** — the same problem, plus it only runs on the API path.
5. **`os.environ` outside settings** — configuration becomes undiscoverable.
6. **A default value for a production secret** — placeholders reach production silently.
7. **Fat `utils.py`** — a module named for its lack of a concept accretes everything. Name modules
   after what they do.
8. **Apps split by layer** (`models/`, `views/` at project level) — Django apps are domain units;
   layer-splitting scatters one feature across the tree.
9. **Catching `Exception` in a view** — hides real errors as 500s with no signal.
10. **`--noinput` on `migrate` in a deploy script without reviewing the plan** — the prompt is the
    last chance to notice a destructive operation.

## References

- [cookiecutter-django.md](references/cookiecutter-django.md) — the generator's prompts, what each
  option adds, the generated layout, and bring-up
- `django-patterns` — the installed stack rule this skill expands on
