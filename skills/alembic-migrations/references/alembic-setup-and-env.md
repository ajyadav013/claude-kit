# Alembic Setup and env.py

How to configure `alembic.ini` and `env.py` for async SQLAlchemy projects.

## alembic.ini Configuration

Canonical `alembic.ini` pattern:

```ini
[alembic]
script_location = alembic
sqlalchemy.url =

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

**Key points**:
- `script_location = alembic` — points to the `alembic/` directory containing `env.py` and `versions/`
- `sqlalchemy.url =` — left empty; set dynamically in `env.py` from settings/config
- Logging configured for alembic and sqlalchemy; INFO level for alembic, WARN for sqlalchemy

## env.py Async Pattern (Canonical)

Full async env.py pattern (cleanest reference):

```python
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.database import Base
from config.settings import settings

# Import all models so Alembic can see them
from app.users.models import User
from app.organizations.models import Organization
from app.tenants.models import Tenant, UserTenantMapping
from app.permissions.models import Permission
from app.roles.models import PlatformRole, RolePermissionMapping
# ... (all other model imports)

config = context.config
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations():
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

**Key patterns**:
1. **Dynamic URL**: `config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)` — reads from settings instead of alembic.ini
2. **Explicit model imports**: All models imported at the top; Alembic discovers tables via `Base.metadata`
3. **target_metadata**: `target_metadata = Base.metadata` — tells Alembic which models to track
4. **Async engine**: `async_engine_from_config` creates async engine from config dict
5. **NullPool**: `poolclass=pool.NullPool` — no connection pooling for one-shot migrations
6. **run_sync bridge**: `connection.run_sync(do_run_migrations)` — runs sync `context.configure` + `context.run_migrations` inside async connection
7. **asyncio.run**: `asyncio.run(run_async_migrations())` — entry point for online mode

## PostgreSQL+asyncpg URL Replacement

For projects using asyncpg (async driver), convert sync URL to async URL:

```python
# Async service pattern
from config.settings import settings

db_url = str(settings.POSTGRES_DB_URL)
async_db_url = db_url.replace("postgresql://", "postgresql+asyncpg://")
config.set_main_option("sqlalchemy.url", async_db_url)
```

**When to use**: If your `DATABASE_URL` starts with `postgresql://` (psycopg2 format) but you're using asyncpg, replace it with `postgresql+asyncpg://`.

## Sync Engine Pattern (Legacy)

Large production service uses sync engine (not async):

```python
from sqlalchemy import engine_from_config, pool
from alembic import context
from app.database import Base
from config.settings import settings

# Import all models (wildcard imports)
from app.articles.models import *
from app.units.models import *
# ... (40+ wildcard imports)

target_metadata = Base.metadata
config = context.config
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
```

**Note**: This is the sync pattern (no `async_engine_from_config`, no `connection.run_sync`). Use only for sync SQLAlchemy projects; prefer async pattern for new projects.

## target_metadata and Model Discovery

Alembic discovers tables via `Base.metadata`. You must import all models at the top of `env.py`:

```python
# Explicit imports (recommended for production code)
from app.users.models import User
from app.organizations.models import Organization

# Wildcard imports (acceptable in env.py, used in multiple production services)
from myapp.users.models import *
from myapp.tenants.models import *
```

**Critical**: If a model is not imported in `env.py`, Alembic won't detect it for autogenerate.

## compare_type and include_object

Optional `context.configure()` flags:

```python
# Async service pattern
def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,  # Detect column type changes
    )
    with context.begin_transaction():
        context.run_migrations()
```

**compare_type**: Set to `True` to detect column type changes (off by default). Without this, changing a column from `String(50)` to `String(100)` won't generate a migration.

## Directory Structure

Standard Alembic layout:

```
project_root/
├── alembic.ini
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   ├── README (optional)
│   └── versions/
│       ├── __init__.py
│       ├── 0001_create_users.py
│       ├── 0002_add_tenants.py
│       └── ...
```

Or `migrations/` instead of `alembic/` (some services use this name):

```
project_root/
├── alembic.ini
├── migrations/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       └── ...
```

Both are valid; `alembic.ini` `script_location` must match the directory name.
