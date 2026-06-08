# FastAPI backend patterns

Stack-specific conventions for the backend. This overlay is installed into `.claude/rules/` only
when the **Python · FastAPI** stack is selected. It complements the generic rules — read
`.claude/rules/code-organization.md`, `.claude/rules/design-patterns.md`, and
`.claude/rules/testing.md` first; this file makes them concrete for FastAPI.

## Stack

- **Python 3.11+**, **FastAPI**, async **SQLAlchemy 2.0** (`Mapped` / `mapped_column`), **asyncpg**,
  **Alembic**, **Pydantic v2** + **pydantic-settings**.
- Tests: **pytest** + **pytest-asyncio** (`asyncio_mode = "auto"`), **httpx** `ASGITransport`,
  in-memory **aiosqlite** (no Postgres needed for the suite).
- Tooling: **ruff** (lint + format), **mypy**.

All commands run from the `backend/` directory:

| Task | Command |
|------|---------|
| Install (dev) | `pip install -e '.[dev]'` |
| Run | `uvicorn app.main:app --reload` |
| Test | `pytest` |
| Lint + types | `ruff check . && mypy app` |
| Format | `ruff format .` |
| New migration | `alembic revision --autogenerate -m "<message>"` |
| Apply migrations | `alembic upgrade head` |

## Layered architecture (never skip a layer)

```
router (app/api/routes/)      HTTP only: validate via schema, call service, map errors → HTTP
  → service (app/services/)   business logic; raises DOMAIN errors; no FastAPI imports
    → repository (app/repositories/)  data access only: SQL, returns ORM objects or None
      → model (app/models/)   SQLAlchemy ORM
schema (app/schemas/)         Pydantic v2 request/response models — the API contract
deps (app/api/deps.py)        dependency injection wiring
```

Rules of thumb:
- **Routers stay thin.** No SQL, no business rules. Translate domain exceptions to `HTTPException`.
- **Services never import FastAPI.** They raise domain errors (e.g. `ItemNotFoundError`); the router
  decides the status code. This keeps services unit-testable without HTTP.
- **Repositories `flush`, never `commit`.** The `get_session` dependency owns the transaction —
  it commits on success and rolls back on error. Don't commit inside repositories or services.
- **Schemas are separate from models.** Never return an ORM object directly; build the response with
  `SchemaRead.model_validate(obj)` (schemas set `from_attributes=True`).

## Adding a new resource (the recipe)

The `item` resource is the worked example. To add `<thing>`:

1. **Model** — `app/models/<thing>.py`: subclass `Base`, use `Mapped[...]` / `mapped_column`.
2. **Schemas** — `app/schemas/<thing>.py`: `<Thing>Base`, `<Thing>Create`, `<Thing>Read`
   (`model_config = ConfigDict(from_attributes=True)`).
3. **Repository** — `app/repositories/<thing>.py`: data access; `flush` + `refresh`, never `commit`.
4. **Service** — `app/services/<thing>.py`: business logic; define a `<Thing>NotFoundError`.
5. **Deps** — add `get_<thing>_service` + `<Thing>ServiceDep` in `app/api/deps.py`.
6. **Router** — `app/api/routes/<thing>.py`: thin CRUD; include it in `app/main.py`.
7. **Migration** — bring the database up first (autogenerate diffs against a *live* DB — see
   **Migrations** below), then `alembic revision --autogenerate -m "add <thing>"`, review the
   generated file, and `alembic upgrade head`.
8. **Tests** — `tests/test_<thing>.py`: cover create, list, get-missing (404), validation (422),
   delete. Use the `client` fixture from `conftest.py`. Tests use in-memory SQLite, so a new column
   appears automatically — no migration needed for the suite to pass.

## Migrations

Alembic **autogenerate compares your models to a running database**, so the DB must be up and
reachable before you run it — otherwise it fails with a connection error (e.g. `socket.gaierror`,
because the default `.env` points at the compose hostname `db`).

```bash
docker compose up -d db                 # start just the database
# native runs: point DATABASE_URL at localhost first, e.g.
#   export DATABASE_URL=postgresql+asyncpg://app:app@localhost:5432/<db_name>
alembic revision --autogenerate -m "add <thing>"   # review the generated file
alembic upgrade head                    # apply
```

- **Review every migration.** Autogenerate misses server defaults, type/enum changes, and renames.
- **Can't reach a DB?** Hand-write the migration using `alembic/versions/0001_initial.py` as the
  template (e.g. `op.add_column("items", sa.Column("completed", sa.Boolean(),
  server_default=sa.false(), nullable=False))`).
- For boolean/timestamp columns set a dialect-safe `server_default` (`sa.false()`, `sa.func.now()`)
  so existing rows get a value.

## Conventions

- **Type everything.** Public functions get full annotations and docstrings (args, returns, raises)
  per `.claude/rules/documentation.md`. mypy must pass on `app`.
- **API metadata.** Every route has a `summary` and an explicit `response_model` / `status_code`.
- **Settings via env.** Add config to `app/core/config.py` (`Settings`); never read `os.environ`
  scattered through the code. Document new env vars in `.env.example` and the README.
- **Migrations are reviewed, not trusted.** Always read the autogenerated migration before applying;
  autogenerate misses some changes (server defaults, enum/type changes, renames).
- **Errors:** raise domain exceptions in services; map to `HTTPException` in routers with a clear
  `detail`. Don't leak stack traces or ORM objects in error responses.
