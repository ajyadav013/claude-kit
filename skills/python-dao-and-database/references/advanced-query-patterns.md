# Advanced Query Patterns

Advanced SQLAlchemy patterns observed in production services: eager loading, relationship loading strategies, query optimization, and transaction isolation.

## Eager Loading Strategies

### Problem: N+1 Queries

Without eager loading, accessing relationships triggers additional queries:

```python
# BAD: N+1 queries
users = await session.execute(select(User))
for user in users.scalars():
    print(user.organization.name)  # Each access triggers a SELECT
```

For 100 users, this generates 101 queries (1 for users + 100 for organizations).

### Solution 1: selectinload (recommended for collections)

```python
from sqlalchemy.orm import selectinload

query = select(User).options(selectinload(User.organization))
result = await session.execute(query)
users = result.scalars().all()

# Now accessing user.organization does NOT trigger additional queries
for user in users:
    print(user.organization.name)  # No extra SELECT
```

**How it works**: Issues a second query with `WHERE organization_id IN (1, 2, 3, ...)` to load all related organizations in one roundtrip.

**When to use**: Loading one-to-many or many-to-many collections (e.g., `organization.users`).

### Solution 2: joinedload (for many-to-one)

```python
from sqlalchemy.orm import joinedload

query = (
    select(Query)
    .options(
        joinedload(Query.usecase).joinedload(Usecase.service),
        joinedload(Query.audits),
    )
)
result = await session.execute(query)
queries = result.unique().scalars().all()
```

**How it works**: Uses SQL JOINs to load related objects in a single query.

**When to use**: Loading many-to-one relationships (e.g., `user.organization`) or small one-to-many collections.

**CRITICAL**: Always call `.unique()` after `joinedload` to deduplicate rows (JOINs create duplicate rows for one-to-many).

### Solution 3: subqueryload (rarely used)

```python
from sqlalchemy.orm import subqueryload

query = select(Organization).options(subqueryload(Organization.users))
result = await session.execute(query)
orgs = result.scalars().all()
```

**How it works**: Issues a subquery to load related objects.

**When to use**: When `selectinload` doesn't work (complex filter conditions).

### Chaining eager loads

Load nested relationships:

```python
query = select(Query).options(
    joinedload(Query.usecase).joinedload(Usecase.service)
)
```

This loads `query.usecase.service` in a single query.

## Lazy Loading Options

Set the default loading strategy in the relationship definition:

```python
from sqlalchemy.orm import relationship, Mapped

class Organization(Base):
    __tablename__ = "organizations"
    
    # Default: lazy="select" (load on access, N+1 risk)
    users: Mapped[list["User"]] = relationship(back_populates="organization", lazy="select")
    
    # Raise error if accessed without eager load (prevent N+1)
    strict_users: Mapped[list["User"]] = relationship(back_populates="organization", lazy="raise")
    
    # Never load (attribute is always empty list)
    archived_users: Mapped[list["User"]] = relationship(back_populates="organization", lazy="noload")
```

**Recommendation**: Use `lazy="raise"` in development to catch N+1 queries, then add explicit `selectinload` / `joinedload` where needed.

## Query Optimization Techniques

### 1. Load only required columns

```python
from sqlalchemy.orm import Load

query = select(User).options(Load(User).load_only(User.id, User.email))
result = await session.execute(query)
users = result.scalars().all()
```

This generates `SELECT id, email FROM users` instead of `SELECT *`.

### 2. Defer expensive columns

```python
from sqlalchemy.orm import defer

query = select(Article).options(defer(Article.body))
result = await session.execute(query)
articles = result.scalars().all()

# Body is loaded only if accessed
print(articles[0].body)  # Triggers SELECT body FROM articles WHERE id = ...
```

Use for large text/binary columns that are rarely accessed.

### 3. Count without loading rows

```python
count_query = select(func.count()).select_from(User).where(User.is_active == True)
total = (await session.execute(count_query)).scalar()
```

Or on an existing query:

```python
count_query = query.with_only_columns(func.count()).order_by(None)
total = (await session.execute(count_query)).scalar()
```

**Note**: `order_by(None)` strips ORDER BY clauses (count doesn't need ordering).

### 4. Use DISTINCT for joined counts

```python
count_query = query.with_only_columns(func.count(func.distinct(User.id))).order_by(None)
total = (await session.execute(count_query)).scalar()
```

Without `distinct`, JOINs inflate the count.

## Transaction Isolation

### Default isolation level

SQLAlchemy uses the database's default isolation level (Postgres: READ COMMITTED).

### Setting isolation level per session

```python
from sqlalchemy import create_engine

engine = create_async_engine(
    "postgresql+asyncpg://...",
    isolation_level="REPEATABLE READ",  # SERIALIZABLE, READ COMMITTED, READ UNCOMMITTED
)
```

Or per transaction:

```python
async with session.begin():
    await session.connection(execution_options={"isolation_level": "SERIALIZABLE"})
    # ... perform operations
```

### Row-level locking

```python
from sqlalchemy import select

# Pessimistic lock (FOR UPDATE)
query = select(User).where(User.id == user_id).with_for_update()
result = await session.execute(query)
user = result.scalar_one()

# Other transactions block until this transaction commits/rollbacks
user.balance -= 100
await session.commit()
```

**Variants**:
- `with_for_update()`: Exclusive lock (blocks reads and writes)
- `with_for_update(read=True)`: Shared lock (blocks writes, allows reads)
- `with_for_update(nowait=True)`: Raise error instead of waiting
- `with_for_update(skip_locked=True)`: Skip locked rows

**Use case**: Preventing race conditions in balance updates, inventory management, job queues.

## Error Handling Best Practices

### Specific exception handling

```python
from sqlalchemy.exc import IntegrityError, NoResultFound

try:
    user = await session.execute(select(User).where(User.id == user_id))
    user = user.scalar_one()
except NoResultFound:
    raise HTTPException(status_code=404, detail="User not found")

try:
    await session.execute(insert(User).values(email="alice@example.com"))
    await session.commit()
except IntegrityError as e:
    await session.rollback()
    if "unique constraint" in str(e).lower():
        raise HTTPException(status_code=409, detail="Email already exists")
    raise
```

### Generic exception with rollback

**Observed pattern** (`bulk_insert` implementation):

```python
try:
    orm_objects = [self.add_object(obj) for obj in create_objects_list]
    self.session.add_all(orm_objects)
    await self._commit()
    return orm_objects
except Exception as e:
    await self.session.rollback()
    raise e
```

**ANTI-PATTERN**: Most DAO methods do NOT rollback on exception (leaves session in inconsistent state).

### Recommended wrapper

```python
async def safe_commit(session: AsyncSession):
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise
```

## Query Performance Tips

1. **Use `unique()` after JOINs**: `result.unique().all()` deduplicates rows.
2. **Avoid `COUNT(*)` on large tables**: Use approximate counts or cache results.
3. **Index foreign keys**: Postgres doesn't auto-index FKs (unlike MySQL).
4. **Use `EXPLAIN ANALYZE`**: Log query plans with `echo=True` in `create_async_engine`.
5. **Batch updates**: Prefer `bulk_update_mappings` over loops (see `basedao-and-sessions.md`).
6. **Limit eager loads**: Only load relationships you actually use.
7. **Connection pooling**: Set `pool_size` and `max_overflow` based on expected concurrency.

## Alembic Migrations

While not a DAO pattern, migrations are essential for schema evolution. Production services commonly use Alembic for database migrations.

### Generate migration

```bash
alembic revision --autogenerate -m "Add user roles"
```

### Apply migration

```bash
alembic upgrade head
```

### Rollback

```bash
alembic downgrade -1
```

### Migration script example

```python
def upgrade() -> None:
    op.add_column('users', sa.Column('role', sa.String(50), nullable=True))
    op.create_index('ix_users_role', 'users', ['role'])

def downgrade() -> None:
    op.drop_index('ix_users_role', 'users')
    op.drop_column('users', 'role')
```

**Best practice**: Always test migrations on a copy of production data before deploying.

## Anti-patterns to avoid

1. **No eager loading**: Accessing relationships in loops triggers N+1 queries. Always profile with SQL logging (`echo=True`).
2. **Forgot `unique()` after `joinedload`**: Results contain duplicate rows.
3. **Using `joinedload` for large collections**: Cartesian explosion. Use `selectinload` instead.
4. **No isolation level for critical transactions**: Race conditions in balance updates, inventory management. Use `with_for_update()`.
5. **Catching `Exception` without rollback**: Session left in inconsistent state. Always rollback in `except` block.
6. **Loading entire table into memory**: Use pagination or streaming (`yield_per`, `partitions`).
7. **Auto-generated migrations without review**: Alembic sometimes generates incorrect migrations (dropped columns, renamed tables). Always review before applying.

## References

- SQLAlchemy 2.0 Relationship Loading Techniques: https://docs.sqlalchemy.org/en/20/orm/queryguide/relationships.html
- SQLAlchemy 2.0 Query Guide: https://docs.sqlalchemy.org/en/20/orm/queryguide/index.html
- Alembic Documentation: https://alembic.sqlalchemy.org/en/latest/
