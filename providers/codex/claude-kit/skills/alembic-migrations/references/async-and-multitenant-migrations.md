# Async and Multi-Tenant Migrations

Advanced Alembic patterns for async SQLAlchemy and multi-tenant architectures.

## Async Migration Pattern Deep Dive

### The Three-Function Pattern

All async services use the same three-function pattern:

```python
def run_migrations_offline() -> None:
    """Offline mode: generate SQL without DB connection."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    """Sync wrapper called inside async connection.run_sync()."""
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations():
    """Async entry point: create engine, connect, run sync migrations via run_sync."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Online mode: run async migrations."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

**Why three functions?**
1. `run_migrations_online()` — sync entry point called by Alembic CLI
2. `run_async_migrations()` — async context manager for engine + connection
3. `do_run_migrations(connection)` — sync function that runs inside `connection.run_sync()`

**Why run_sync?** Alembic's `context.configure()` and `context.run_migrations()` are sync APIs; `connection.run_sync()` bridges async connection → sync Alembic context.

### compare_type Flag

Detects column type changes (disabled by default):

```python
def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,  # Enable type comparison
    )
    with context.begin_transaction():
        context.run_migrations()
```

**Without compare_type**: Changing a model from `String(50)` to `String(255)` won't generate a migration.

**With compare_type**: Alembic detects the type change and generates `op.alter_column()`.

### include_object Filtering

Exclude internal/temporary tables from autogenerate:

```python
def include_object(object, name, type_, reflected, compare_to):
    """Filter out tables that should not be tracked by migrations."""
    if type_ == "table" and object.name == "__monitoring_heartbeat":
        return False
    return True


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,  # Add filter
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,  # Add filter
        )
        with context.begin_transaction():
            context.run_migrations()
```

**Use case**: Exclude monitoring tables (heartbeat tables), temporary tables, or tables managed by external tools.

## Row-Level Security (RLS) Migrations

### Enabling RLS on Tenant-Scoped Tables

Multi-tenant service pattern:

```python
"""Enable Row-Level Security on tenant-scoped tables.

Adds RLS policies that filter rows by the PostgreSQL session
variable ``app.tenant_id``.  A bypass policy allows platform
admin operations when ``app.bypass_rls`` is set to ``'true'``.

Revision ID: 0010
Revises: 0009
Create Date: 2026-04-25
"""
from alembic import op

revision: str = "0010"
down_revision: str = "0009"

TENANT_SCOPED_TABLES = [
    "tenant_configs",
    "tenant_lifecycle_transitions",
    "tenant_feature_overrides",
    "tenant_audit_logs",
    "tenant_roles",
    "user_tenant_mappings",
    "user_tenant_role_assignments",
]


def upgrade() -> None:
    for table in TENANT_SCOPED_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")

        op.execute(f"""
            CREATE POLICY tenant_isolation_{table}
            ON {table}
            FOR ALL
            USING (
                tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::uuid
                OR current_setting('app.bypass_rls', TRUE) = 'true'
            )
        """)


def downgrade() -> None:
    for table in reversed(TENANT_SCOPED_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
```

### RLS Policy Breakdown

```sql
CREATE POLICY tenant_isolation_<table>
ON <table>
FOR ALL
USING (
    tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::uuid
    OR current_setting('app.bypass_rls', TRUE) = 'true'
)
```

**Components**:
1. **Policy name**: `tenant_isolation_<table>` — unique per table
2. **FOR ALL**: Applies to SELECT, INSERT, UPDATE, DELETE
3. **USING clause**: Row visibility condition
4. **current_setting('app.tenant_id', TRUE)**: Read session variable; `TRUE` = don't error if unset
5. **NULLIF(..., '')**: Convert empty string to NULL (unset session var returns '')
6. **::uuid**: Cast to UUID type
7. **tenant_id = ...**: Match row's tenant_id to session variable
8. **OR current_setting('app.bypass_rls', TRUE) = 'true'**: Admin bypass flag

### Setting Session Variables (Application Code)

Multi-tenant service connection handler pattern (not in migration, but shows how session variables are set):

```python
async def set_tenant_context(self, tenant_id: UUID) -> None:
    """Set tenant_id session variable for RLS."""
    await self.session.execute(
        text("SET LOCAL app.tenant_id = :tid"),
        {"tid": str(tenant_id)},
    )

async def bypass_rls(self) -> AsyncContextManager:
    """Context manager to bypass RLS for platform admin queries."""
    @asynccontextmanager
    async def _bypass():
        await self.session.execute(text("SET LOCAL app.bypass_rls = 'true'"))
        yield
        await self.session.execute(text("SET LOCAL app.bypass_rls = 'false'"))
    return _bypass()
```

**Usage**:
```python
# Normal tenant-scoped query
await connection_handler.set_tenant_context(tenant_id)
users = await session.execute(select(User))  # Only sees users for tenant_id

# Platform admin cross-tenant query
async with connection_handler.bypass_rls():
    all_users = await session.execute(select(User))  # Sees all users
```

### RLS Migration Best Practices

1. **List tenant-scoped tables explicitly** — Don't enable RLS on all tables; only tables with `tenant_id` column.
2. **Use reversed() in downgrade** — Drop policies in reverse order for consistency.
3. **Test bypass flag** — Verify platform admin queries work with `app.bypass_rls = true`.
4. **Document RLS behavior** — Add migration docstring explaining session variables.

## Multi-Schema Migrations (Not Observed)

Observed production services use either:
- **RLS isolation** (multi-tenant service): One schema, shared tables, row-level filtering
- **Multi-pool isolation** (some services): Separate databases per tenant, standard migrations per DB

**If implementing multi-schema tenancy**, you'd need custom migration logic:

```python
# Hypothetical multi-schema migration (NOT FROM REPOS)
def upgrade() -> None:
    # Get list of tenant schemas from DB
    connection = op.get_bind()
    result = connection.execute(
        "SELECT schema_name FROM information_schema.schemata WHERE schema_name LIKE 'tenant_%'"
    )
    tenant_schemas = [row[0] for row in result]
    
    # Apply migration to each tenant schema
    for schema in tenant_schemas:
        op.execute(f"SET search_path TO {schema}")
        op.create_table(
            "products",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("name", sa.String(255)),
        )
```

**Caution**: This pattern is speculative (not derived from real code). Multi-schema migrations are complex; prefer RLS or multi-pool patterns.

## URL Replacement for Async Drivers

Multiple async services use this pattern:

```python
from config.settings import settings

# Read URL from config (may be postgresql:// for sync driver)
db_url = str(settings.POSTGRES_DB_URL)

# Replace with asyncpg driver
async_db_url = db_url.replace("postgresql://", "postgresql+asyncpg://")

# Set for Alembic
config.set_main_option("sqlalchemy.url", async_db_url)
```

**Why needed**: If your config stores a sync URL (`postgresql://user:pass@host/db`) but you're using asyncpg, Alembic needs the async URL (`postgresql+asyncpg://...`).

**Alternative**: Store the async URL directly in config; no replacement needed.
