# Example Patterns from Production Services

Code snippets demonstrating each Alembic pattern observed in production FastAPI services.

## Reference Service A (Cleanest Canonical Reference)

Multi-tenant async service with sequential migration naming and RLS policies.

### alembic.ini

Standard configuration:

- `script_location = alembic`
- `sqlalchemy.url =` (empty, set in env.py)

### env.py (Async Pattern)

Key snippets:

```python
# Imports
import asyncio
from logging.config import fileConfig
from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config
from app.database import Base
from config.settings import settings

# All model imports (explicit, not wildcard)
from app.users.models import User
from app.organizations.models import Organization
from app.tenants.models import Tenant, UserTenantMapping
from app.permissions.models import Permission
from app.roles.models import PlatformRole, RolePermissionMapping
# ... 20+ explicit imports

# Dynamic URL
config = context.config
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

# target_metadata
target_metadata = Base.metadata

# Async migration runner
async def run_async_migrations():
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()

# Online mode
def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())
```

### Revision Naming (Sequential)

```
alembic/versions/
├── 0001_create_users_and_organizations.py
├── 0002_add_user_role.py
├── 0003_add_tenants_and_extend_roles.py
├── 0004_flexible_tenant_roles.py
├── 0005_add_org_hierarchy_and_sub_org_admin.py
├── 0006_create_access_core_tables.py
├── 0007_seed_system_permissions.py
├── 0008_phase4_auth_tables.py
```

### Migration Example: Table Creation

```python
# Explicit type imports
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

# Table creation with UUID, JSONB, server_default
def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(255), nullable=False, unique=True),
        sa.Column("config", JSONB, nullable=True),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_organizations_slug", "organizations", ["slug"])
```

### Migration Example: RLS Policies

```python
# Tenant-scoped tables list
TENANT_SCOPED_TABLES = [
    "tenant_configs",
    "tenant_lifecycle_transitions",
    "tenant_feature_overrides",
    "tenant_audit_logs",
    "tenant_roles",
    "user_tenant_mappings",
    "user_tenant_role_assignments",
]

# RLS upgrade
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

# RLS downgrade (reversed order)
def downgrade() -> None:
    for table in reversed(TENANT_SCOPED_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
```

## Reference Service B (Large Production Service)

~110 migrations, timestamp-hash naming, sync engine pattern with include_object filtering.

### env.py (Sync Pattern + include_object)

Key snippets:

```python
# Sync engine imports (no asyncio)
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context
from app.database import Base
from config.settings import settings

# Wildcard model imports
from app.items.models import *
from app.units.models import *
from app.catalog.models import *
# ... 40+ wildcard imports

# target_metadata
target_metadata = Base.metadata

# include_object filter
def include_object(object, name, type_, reflected, compare_to):
    if type_ == "table" and object.name == "__monitoring_heartbeat":
        return False
    return True

# Sync online migration
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
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()
```

### Revision Naming (Timestamp-Hash)

```
alembic/versions/
├── 05db5b50a602_add_cluster_mappings.py
├── 061ae53df0df_init_add_models.py
├── 202407301751-ad610b2bab70_add_event_log_table.py
├── 202408011255-e848fe551d9b_add_mapping_tables.py
├── 202408012159-c3f783a32f7c_add_username_to_event_log_table.py
├── 202408052213-943a94fc4f73_add_is_active_to_mapping_tables.py
├── 202409031128-0fc8dde689fe_add_source_cluster.py
```

Format: `{YYYYMMDDHHmm}-{hash}_{description}.py`

### Migration Example: Autogenerated Table

```python
# Autogenerate docstring
"""add event log table

Revision ID: ad610b2bab70
Revises: 715448122adf
Create Date: 2024-07-30 17:51:24.929156
"""

# Autogenerate markers
def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "event_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    # ### end Alembic commands ###
```

## Reference Service C (Async + compare_type)

Async service with URL replacement and compare_type.

### env.py (Async + URL Replacement)

Key snippets:

```python
# Async imports
import asyncio
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from alembic import context
from config.settings import settings

# Wildcard model imports
from app.invoices.models import *
from app.queries.models import *
from app.vendors.models import *
# ... 14 wildcard imports

# URL replacement for asyncpg
db_url = str(settings.POSTGRES_DB_URL)
async_db_url = db_url.replace("postgresql://", "postgresql+asyncpg://")
config.set_main_option(
    "sqlalchemy.url",
    async_db_url,
)

# compare_type flag
def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
```

## Reference Service D (Async + Auto-Hash Naming)

Async service with auto-hash revision naming.

### Revision Naming (Auto-Hash)

```
migrations/versions/
├── 554395de0772_added_data_models.py
├── 9d07416cb3d0_modified_generated_file_model.py
├── cb876bd3ff47_added_watermark_model.py
└── d5885c4539c2_updated_watermark_table.py
```

Format: `{auto_hash}_{description}.py` (Alembic default)

## Summary: Pattern Coverage

| Pattern | Services | Evidence |
|---------|----------|----------|
| Async env.py (async_engine_from_config + run_sync) | Multiple async services | All async services use identical pattern |
| Sync env.py (engine_from_config) | Large production service | Sync pattern shown above |
| Sequential revision naming (0001, 0002, ...) | Service A | Sequential numbered migrations |
| Timestamp-hash naming (202407301751-ad610b2bab70_...) | Service B | Large production service with parallel dev |
| Auto-hash naming (554395de0772_...) | Services C, D | Standard Alembic workflow |
| compare_type flag | Services C, D | Type change detection enabled |
| include_object filtering | Service B | Heartbeat table exclusion |
| RLS policy migrations | Service A | Multi-tenant isolation pattern |
| postgresql+asyncpg URL replacement | Services C, D | Async driver URL conversion |
| NullPool for migrations | All services | All env.py files use poolclass=pool.NullPool |
| target_metadata = Base.metadata | All services | All env.py files |
