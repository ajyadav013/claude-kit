# cookiecutter-django — generating and reading a project

[cookiecutter-django](https://github.com/cookiecutter/cookiecutter-django) is the dominant Django
project template. It targets **Django 6.0**, works on Python 3.14, manages dependencies with
**uv**, ships pre-commit configured, and starts at 100% test coverage.

Two situations bring you here: generating a new project, or landing in one someone else generated
and needing to read it.

## The prompts that actually change the shape

Most prompts are cosmetic. These are the ones that commit you to something.

| Prompt | Options | What it decides |
|---|---|---|
| `rest_api` | None · **DRF** · Django Ninja | DRF is the default choice and has no first-class async. Ninja is async-first on Pydantic v2. See `django-rest-framework-patterns`. |
| `use_async` | y / n | Adds `config/asgi.py` and switches the run command to uvicorn. See `django-async-patterns`. |
| `frontend_pipeline` | None · Django Compressor · **Gulp** · **Webpack** | Gulp and Webpack move the dev URL to **`:3000`**. See the port trap below. |
| `use_celery` | y / n | Celery + Flower + django-celerybeat. Still the answer for periodic tasks, chains, and retry policies — Django 6.0's Tasks framework does not replace it. |
| `username_type` | username · email | Changes the auth flow and is painful to reverse after users exist. |
| `cloud_provider` | AWS · GCP · Azure · None | Wires django-storages for media. `None` keeps media on local disk. |
| `postgresql_version` | 18 · 17 · 16 · 15 · 14 | Django 6.x requires PostgreSQL 15+; picking 14 here locks you out of upgrading Django later. |
| `use_docker` | y / n | Out of scope for claude-kit's overlay, which is container-optional. |

## The `:3000` trap

With `frontend_pipeline` set to Gulp or Webpack, `npm run dev` runs the asset build **and** Django
together, and the URL you open is `http://localhost:3000`.

Opening `:8000` still returns pages — Django is running — but they are unstyled and every static
asset 404s. It presents as a broken install. It is the wrong port.

With `frontend_pipeline: None` or Django Compressor, `:8000` is correct.

## Generated layout

```
manage.py
config/
  settings/{base,local,production}.py
  urls.py  wsgi.py  [asgi.py]
<django_project_root>/
  users/            # custom user model + allauth wiring, already done for you
  <app>/{migrations,admin,apps,models,tests,views}.py
requirements/{base,local,production}.txt   # mirrored by uv
```

## Bring-up

```bash
uv sync                                    # dependencies
pre-commit install                         # hooks the template already configured
createdb <project> -U postgres             # or point DATABASE_URL at an existing server
uv run python manage.py migrate
uv run python manage.py createsuperuser
uv run python manage.py runserver 0.0.0.0:8000
```

Async variant, when `use_async` was `y`:

```bash
uv run uvicorn config.asgi:application --host 0.0.0.0 --reload --reload-include '*.html'
```

The `--reload-include '*.html'` matters: uvicorn's reloader watches Python files only, so template
edits will not refresh without it.

## Adding an app to a generated project

```bash
uv run python manage.py startapp billing
mv billing <django_project_root>/
```

Then edit `billing/apps.py` so the config reads `name = "<django_project_root>.billing"`, and add
`"<django_project_root>.billing"` to `LOCAL_APPS` in `config/settings/base.py`. Both steps are
required; the first is the one people forget.

## What ships in the box

django-allauth (custom user model, email verification), django-environ (12-factor settings),
Anymail, django-storages, whitenoise, Celery + Flower + django-celerybeat, Sentry, Bootstrap 5,
and Mailpit for local mail capture.

Knowing these are present matters mostly so you do not add a second library that does the same
job — the template has already chosen for you.

## Extension points

The template marks its own seams with a "your stuff" comment in `base.py`, `urls.py`, and the
static and template directories. Put project-specific configuration there rather than editing the
generated blocks around it, so a later template upgrade produces a readable diff.
