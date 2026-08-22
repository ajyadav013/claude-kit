# Troubleshooting and Debugging Migrations

Common Alembic migration issues and how to fix them.

## Down Revision Chain Errors

### Error: "Can't locate revision identified by 'xyz'"

**Cause**: Migration file references a `down_revision` that doesn't exist in your `versions/` folder.

**Fix**:
1. Check the missing revision ID in the error message
2. Find all migrations: `alembic history`
3. If the revision is from a branch merge conflict, update `down_revision` to the correct parent
4. If the file is missing, restore from git or regenerate the migration

```bash
# Check current state
alembic current
alembic history --verbose

# Find the broken link
grep -r "down_revision.*xyz" alembic/versions/
```

### Error: "Multiple head revisions are present"

**Cause**: Two migrations have no child (both are "head"), creating a branch in the migration history.

**Fix**: Merge the branches with a merge migration:

```bash
# Show heads
alembic heads

# Merge them
alembic merge -m "merge heads" head1_id head2_id
```

This creates a new migration with `down_revision = ('head1_id', 'head2_id')` (tuple of both parents).

## Autogenerate Issues

### Problem: Autogenerate doesn't detect my new model

**Cause**: Model not imported in `env.py`.

**Fix**: Add explicit import at the top of `env.py`:

```python
# env.py
from myapp.products.models import Product  # Add this
```

Then run autogenerate again:

```bash
alembic revision --autogenerate -m "add products table"
```

### Problem: Autogenerate doesn't detect column type changes

**Cause**: `compare_type=True` flag not set in `context.configure()`.

**Fix**: Update `env.py`:

```python
def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,  # Add this
    )
```

### Problem: Autogenerate creates unwanted migrations for internal tables

**Cause**: Alembic sees tables in the database that aren't in your models (monitoring tables, temporary tables, etc.).

**Fix**: Add `include_object` filter in `env.py`:

```python
def include_object(object, name, type_, reflected, compare_to):
    """Filter out tables that shouldn't be tracked."""
    if type_ == "table":
        # Exclude monitoring/heartbeat tables
        if object.name in ["__monitoring_heartbeat", "__temp_migration_data"]:
            return False
        # Exclude alembic's own version table
        if object.name == "alembic_version":
            return False
    return True

# In context.configure():
context.configure(
    connection=connection,
    target_metadata=target_metadata,
    include_object=include_object,
)
```

## Connection and Engine Errors

### Error: "asyncpg.exceptions.InvalidCatalogNameError: database does not exist"

**Cause**: Database URL points to a non-existent database.

**Fix**: Create the database first:

```bash
# PostgreSQL
createdb mydb

# Or via psql
psql -U postgres -c "CREATE DATABASE mydb;"
```

Then run migrations:

```bash
alembic upgrade head
```

### Error: "Can't use AsyncConnection with Alembic" (or similar async-related error)

**Cause**: Using sync engine pattern (`engine_from_config`) with async SQLAlchemy models.

**Fix**: Switch to async engine pattern in `env.py`:

```python
# Replace sync pattern
from sqlalchemy import engine_from_config

# With async pattern
import asyncio
from sqlalchemy.ext.asyncio import async_engine_from_config

# And update run_migrations_online()
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
```

### Error: "No module named 'asyncpg'" (or "psycopg2")

**Cause**: Database driver not installed.

**Fix**: Install the driver:

```bash
# For async (asyncpg)
pip install asyncpg

# For sync (psycopg2)
pip install psycopg2-binary
```

And ensure URL matches driver:
- `postgresql+asyncpg://...` → requires `asyncpg`
- `postgresql://...` (or `postgresql+psycopg2://...`) → requires `psycopg2`

## Migration Application Errors

### Error: "Target database is not up to date"

**Cause**: Trying to run a migration out of order, or local DB is behind.

**Fix**: Upgrade to head first:

```bash
# Check current revision
alembic current

# Show pending migrations
alembic history

# Upgrade to latest
alembic upgrade head
```

### Error: Column/table already exists (on upgrade)

**Cause**: Running a migration that was partially applied, or DB was manually modified.

**Fix**: Mark the migration as applied without running it:

```bash
# Stamp the DB as if this revision was applied
alembic stamp <revision_id>

# Or upgrade to next revision only
alembic upgrade +1
```

**Alternative**: Edit the migration to add `IF NOT EXISTS` checks:

```python
# Before
op.create_table("products", ...)

# After (manual check)
from sqlalchemy import inspect
inspector = inspect(op.get_bind())
if "products" not in inspector.get_table_names():
    op.create_table("products", ...)
```

### Error: Downgrade fails with foreign key constraint violation

**Cause**: Dropping a table that other tables reference, or downgrade order is wrong.

**Fix**: Drop child tables before parent tables in `downgrade()`:

```python
def upgrade() -> None:
    op.create_table("organizations", ...)
    op.create_table("users", ...)  # Has FK to organizations

def downgrade() -> None:
    op.drop_table("users")  # Drop child first
    op.drop_table("organizations")  # Then parent
```

## RLS and Multi-Tenant Errors

### Error: "new row violates row-level security policy"

**Cause**: Trying to insert/update a row without setting the tenant context, or the tenant_id doesn't match the session variable.

**Fix**: Set session variable before the query:

```python
# In application code (not migration)
await session.execute(
    text("SET LOCAL app.tenant_id = :tid"),
    {"tid": str(tenant_id)}
)
```

Or bypass RLS for admin operations:

```python
await session.execute(text("SET LOCAL app.bypass_rls = 'true'"))
```

### Problem: RLS policy blocks migrations

**Cause**: Migration runner doesn't set tenant context; RLS blocks all operations.

**Fix**: Migrations run as superuser by default and bypass RLS automatically. If using a non-superuser role:

1. Grant BYPASSRLS to the migration user:
   ```sql
   ALTER ROLE migration_user BYPASSRLS;
   ```

2. Or disable RLS temporarily during migrations:
   ```python
   def upgrade() -> None:
       op.execute("ALTER TABLE products DISABLE ROW LEVEL SECURITY")
       # ... migration operations ...
       op.execute("ALTER TABLE products ENABLE ROW LEVEL SECURITY")
   ```

## Debugging Commands

```bash
# Show current revision
alembic current

# Show full history
alembic history --verbose

# Show only heads (most recent migrations)
alembic heads

# Show branches (if any)
alembic branches

# Show SQL without applying (dry run)
alembic upgrade head --sql > migration.sql

# Downgrade one step (for testing)
alembic downgrade -1

# Upgrade one step (for debugging)
alembic upgrade +1

# Stamp DB to specific revision (without running migrations)
alembic stamp <revision_id>
```

## Best Practices to Avoid Issues

1. **Always review autogenerated migrations** before applying — catch issues early
2. **Test migrations on a copy of production data** — find edge cases before deployment
3. **Run upgrade then downgrade on staging** — verify reversibility
4. **Use transactions** — migrations run in a transaction by default; don't disable unless necessary
5. **Backup before production migrations** — safety net for rollback
6. **Keep migrations idempotent where possible** — add `IF NOT EXISTS` checks for safety
7. **Don't edit applied migrations** — create a new migration to fix issues

## References

- [Alembic Official Docs](https://alembic.sqlalchemy.org/)
- [Alembic Common Gotchas](https://alembic.sqlalchemy.org/en/latest/tutorial.html#downgrading)
- [PostgreSQL RLS Troubleshooting](https://www.postgresql.org/docs/current/ddl-rowsecurity.html)
