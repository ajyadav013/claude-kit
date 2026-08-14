# django-service-patterns

Encodes Django project structure and the model/service/view split: the two-tier `config/` +
project-package layout, environment-split settings read through django-environ, apps as domain
units, fat models with a services layer, the custom user model decision, ORM query discipline, and
pytest-django setup — plus how to generate and read a cookiecutter-django project.

## What this skill covers

- Two-tier layout, and the `apps.py` edit that `startapp` does not do for you
- `config/settings/{base,local,production}.py` with django-environ, and why production secrets get
  no defaults
- Custom user model before the first `migrate`
- Where logic goes: model method vs custom QuerySet vs `services.py` vs view
- Explicit `transaction.atomic` boundaries, kept narrow
- `select_related` / `prefetch_related`, and Django 6.1 fetch modes as a safety net
- pytest-django: `django_db`, factories over JSON fixtures, testing services without HTTP
- cookiecutter-django: which prompts change the shape, the `:3000` port trap, bring-up commands

## Provenance

Written for **Django 6.1**, the current release. Features introduced after the 5.2 LTS (`MAILERS`,
fetch modes, `BigAutoField` defaults) name their version so an LTS project can tell what applies.
The cookiecutter section reflects the template's 2026.33.1 documentation.

## How to apply

1. Read this skill when starting a Django project, adding an app, or deciding where a piece of
   logic belongs.
2. For API surfaces, continue to `django-rest-framework-patterns`.
3. For schema changes, `django-migrations` owns the migration rules.
4. For async views, ASGI, or Celery-vs-Tasks, see `django-async-patterns`.
5. For a React or SPA frontend against this backend, see `django-react-integration`.

The installed stack rule `.claude/rules/django-patterns.md` carries the short version of these
conventions and loads automatically on `**/*.py`; this skill is the depth behind it.
