# Writing Migrations

How to create, structure, and name Alembic migration files.

## Revision Naming Conventions

Three patterns observed across repos:

### Pattern 1: Sequential Numbers

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
└── ...
```

**Format**: `{sequential_number}_{description}.py`

**Pros**: Easy to understand chronological order; clean history.

**Cons**: Merge conflicts when multiple developers create migrations simultaneously.

**When to use**: Small teams, single-developer projects, core schema migrations.

### Pattern 2: Timestamp-Hash

```
alembic/versions/
├── 202407301751-ad610b2bab70_add_event_log_table.py
├── 202408011255-e848fe551d9b_add_category_mapping_tables.py
├── 202408012159-c3f783a32f7c_add_username_to_event_log_table.py
├── 202408052213-943a94fc4f73_add_is_active_to_mapping_tables.py
├── 202409031128-0fc8dde689fe_add_source_cluster.py
└── ...
```

**Format**: `{YYYYMMDDHHmm}-{hash}_{description}.py`

**Pros**: Timestamp resolves merge conflicts; multiple developers can work in parallel.

**Cons**: Longer filenames; harder to eyeball chronological order.

**When to use**: Large teams with parallel development; frequent migrations.

### Pattern 3: Auto-Generated Hash

```
migrations/versions/
├── 554395de0772_added_data_models.py
├── 9d07416cb3d0_modified_generated_file_model.py
├── cb876bd3ff47_added_watermark_model.py
└── d5885c4539c2_updated_watermark_table.py
```

**Format**: `{auto_hash}_{description}.py` (default Alembic behavior)

**Pros**: No manual numbering; Alembic handles uniqueness.

**Cons**: No inherent ordering information in filename.

**When to use**: Standard workflow; let Alembic manage revision IDs.

## Migration File Structure (script.py.mako)

Standard template:

```python
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision: str = ${repr(up_revision)}
down_revision: Union[str, None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

**Key fields**:
- **Docstring**: Migration description (from `-m "message"`)
- **revision**: Unique ID for this migration
- **down_revision**: Parent migration ID (forms the chain)
- **branch_labels**: For branching (rarely used)
- **depends_on**: Cross-branch dependencies (rarely used)
- **upgrade()**: Apply changes
- **downgrade()**: Revert changes

## Creating Migrations

### Manual Migration

```bash
alembic revision -m "create users table"
```

Generates empty migration with `upgrade()` and `downgrade()` as `pass`. You write the table creation/modification logic manually.

### Autogenerate Migration

```bash
alembic revision --autogenerate -m "add email_verified to users"
```

Alembic compares `Base.metadata` (models) to current DB schema and generates upgrade/downgrade. **Always review the generated migration before applying.**

## Migration Examples

### Example 1: Table Creation

```python
"""create users and organizations tables

Revision ID: 0001
Revises:
Create Date: 2026-04-22
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(255), nullable=False, unique=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("config", JSONB, nullable=True),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_organizations_slug", "organizations", ["slug"])

    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(512), nullable=False),
        sa.Column("first_name", sa.String(100), nullable=False),
        sa.Column("last_name", sa.String(100), nullable=False),
        sa.Column("phone_number", sa.String(20), nullable=True),
        sa.Column("organization_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_users_email", "users", ["email"])


def downgrade() -> None:
    op.drop_table("users")
    op.drop_table("organizations")
```

**Patterns**:
- UUID primary keys with `server_default=sa.text("gen_random_uuid()")`
- JSONB columns for flexible config
- Soft delete (`is_deleted`, `deleted_at`)
- Timestamp columns with `CURRENT_TIMESTAMP` default
- Foreign key to parent table (`organizations.id`)
- Indexes on lookup columns (`email`, `slug`)

### Example 2: Autogenerated Migration

```python
"""add event log table

Revision ID: ad610b2bab70
Revises: 715448122adf
Create Date: 2024-07-30 17:51:24.929156
"""
from typing import Sequence, Union
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "ad610b2bab70"
down_revision: Union[str, None] = "715448122adf"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "event_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("user_role", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table("event_log")
    # ### end Alembic commands ###
```

**Autogenerate markers**: `# ### commands auto generated by Alembic - please adjust! ###` comments indicate autogenerated code. **Review and adjust** before applying.

## Applying and Reverting Migrations

```bash
# Apply all pending migrations
alembic upgrade head

# Apply to specific revision
alembic upgrade 0005

# Revert one migration
alembic downgrade -1

# Revert to specific revision
alembic downgrade 0003

# Show current revision
alembic current

# Show migration history
alembic history

# Generate SQL without applying (offline mode)
alembic upgrade head --sql > migration.sql
```

## Best Practices

1. **Always review autogenerated migrations** — Alembic can't detect renamed columns, data transformations, or custom SQL.
2. **Import PostgreSQL types explicitly** — `from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY`.
3. **Use server_default for timestamps** — `server_default=sa.text("CURRENT_TIMESTAMP")` ensures DB sets the value.
4. **Implement downgrade() properly** — For loop-based migrations (RLS policies, seed data), use `reversed()` in downgrade.
5. **Test migrations on staging** — Apply upgrade, run tests, apply downgrade, verify data integrity.
6. **Don't edit applied migrations** — Create a new migration to fix issues; editing breaks the revision chain.
