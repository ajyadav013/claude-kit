---
name: python-dao-and-database
description: Encodes patterns for data access objects (DAO), async SQLAlchemy session lifecycle, eager loading, pagination, bulk operations, transactions, and MongoDB usage as observed in production Python/FastAPI services. Covers both SQLAlchemy 1.4 and 2.0 idioms, the BaseDao abstraction, ConnectionManager/ConnectionHandler session factory patterns, eager loading strategies (selectinload, joinedload) to prevent N+1 queries, query optimization, row-level locking, and the static-class MongoDB DAO. Use when implementing database access layers, setting up async sessions, building paginated queries, creating DAOs, debugging N+1 queries, optimizing slow queries, migrating SQLAlchemy versions, or integrating MongoDB.
---

Standard DAO patterns and database session lifecycle for async SQLAlchemy and MongoDB.

## When to use

- Implementing a new DAO or data access layer for async SQLAlchemy
- Setting up async session factories (`async_scoped_session`) and connection handlers (`ConnectionHandler`)
- Building paginated queries with sorting, filtering, and count optimization
- Performing bulk inserts, updates, or Postgres partition management
- Debugging session lifecycle issues (leaks, commit/rollback, N+1 queries)
- Integrating MongoDB with sync pymongo and static-class DAOs
- Migrating between SQLAlchemy 1.4 (declarative_base, Column) and 2.0 (DeclarativeBase, Mapped, mapped_column)
- Optimizing queries with eager loading (selectinload, joinedload) to prevent N+1
- Reviewing transaction handling patterns and rollback strategies
- Setting up alembic migrations for schema evolution
- Implementing row-level locking or custom isolation levels for critical transactions

## Core conventions

**BaseDao abstraction**
- Subclass `BaseDao(session: AsyncSession, db_model)` for each domain entity
- Core methods: `create`, `add_object`, `bulk_add_objects`, `get_by_pk`, `update_by_pk`, `delete_by_pk`, `get_paginated_response`, `_flush`, `_commit`, `_execute_query`, `get_orm_object`
- Advanced implementations add `apply_filters(query, filters: list[QueryFilter])`, `apply_sort(query, ordering_clauses: list[OrderingClause])`, `load_columns`, `create_partition`/`create_partitions_in_bulk` via raw `text()` SQL
- QueryFilter DSL: `ComparisonOperator` enum (EQ, NEQ, LT, LE, GT, GE, IN, NOT_IN, IS, IS_NOT, BETWEEN)
- BaseDao is often COPY-PASTED across services (code smell) — consider extracting to a shared library

**Session lifecycle**
- `ConnectionManager(metaclass=Singleton)` builds the engine and session factory once
- Preferred: `async_scoped_session(sessionmaker(engine, expire_on_commit=False, class_=AsyncSession), scopefunc=current_task)`
- ANTI-PATTERN: plain `sessionmaker` (NOT async_scoped_session) → session-leak risk under concurrency
- `ConnectionHandler.session` is a lazy property; instantiate a new handler per request
- Dependency: `async def get_connection_handler() -> AsyncGenerator[ConnectionHandler, None]` yields the handler, closes in `finally`
- Never store `ConnectionHandler` or session in module/class scope

**Pagination**
- `get_paginated_response(query, page_size, page_number, sort_by=None, order_by=None, count_field=None)` returns `(rows, pagination_info)`
- Count query: `query.with_only_columns(func.count(func.distinct(count_field))).order_by(None)`
- Pagination info: `{"page_size": ..., "page_number": ..., "has_next": total - page_size * page_number > 0, "total_records": total}`
- Sorting: `asc(column)` or `desc(column)` in `query.order_by(...)`
- Use `query.unique().all()` to deduplicate joined results (CRITICAL after joinedload)
- For performance on large tables: avoid COUNT(*); consider cached totals or approximate counts

**Transactions**
- Manual `await self._commit()` after write operations (create, update_by_pk, delete_by_pk)
- ANTI-PATTERN: mostly NO explicit rollback or try/except in DAO methods (rare exception: `bulk_insert` with rollback)
- NO unit-of-work pattern; each DAO method commits independently
- When explicit rollback is needed: `await self.session.rollback()` in except block
- MISSING: specific `IntegrityError` handling for unique constraint violations; most methods raise generic exceptions
- For critical transactions: use `with_for_update()` for row-level locking or set isolation level (see `advanced-query-patterns.md`)

**Bulk operations**
- Insert: `bulk_add_objects(create_objects_list: List[dict])` uses `session.add_all(orm_objects)` (efficient)
- Update: `bulk_update(update_objects_list: List[dict], pk_field_name=None)` loops per row with individual `update()` statements (inefficient; flag for optimization)
- Partitions: `create_partition(partition_value)` and `create_partitions_in_bulk(object_ids)` use raw `text()` SQL for Postgres declarative partitioning

**SQLAlchemy 1.4 vs 2.0**
- 1.4: `from sqlalchemy.ext.declarative import declarative_base; Base = declarative_base()`; columns as `Column(Integer, primary_key=True)`, no typing
- 2.0: `from sqlalchemy.orm import DeclarativeBase; class Base(DeclarativeBase): pass`; typed columns `id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, ...)`; relationships `Mapped[list["RelatedModel"]] = relationship(..., lazy="select")`
- Use `Mapped[T]` for nullable=False, `Mapped[Optional[T]]` for nullable=True
- Custom types: `class GUID(TypeDecorator)` pattern for platform-independent UUID handling

**Eager loading**
- Use `selectinload(Model.relationship)` for one-to-many/many-to-many collections (issues `WHERE IN` query)
- Use `joinedload(Model.relationship)` for many-to-one or small collections (single JOIN query; MUST call `.unique()` on results)
- Chain for nested relationships: `joinedload(Query.usecase).joinedload(Usecase.service)`
- Enable `echo=True` in engine config to detect N+1 queries (one SELECT per loop item = missing eager load)
- See `advanced-query-patterns.md` for full details on selectinload, joinedload, subqueryload, load_only, defer

**MongoDB**
- SYNC pymongo (NOT motor/beanie): `mongo_client = MongoClient(MONGO_URI, maxPoolSize=100)` module-level
- Static-class DAO: `class MongoDB` with `@classmethod` methods (`fetch_one`, `insert_bulk`, `aggregate_query`, `create_index`, `fetch_all`, `get_count`)
- Bulk upsert: `insert_bulk(collection_name, write_request, *filter_columns)` builds `UpdateOne(..., upsert=True)` ops, calls `collection.bulk_write(bulk_operations, ordered=False)`
- BSON: use `bson.json_util.dumps` / `json_util.object_hook` for serialization
- Collections + index specs in constants module; indexes created on startup via `MongoDB.create_index(collection["name"], collection["indexes"])`
- Pydantic absent; dict-based flow

### MongoDB advanced patterns

Beyond basic CRUD, production MongoDB DAOs implement aggregation pipelines, bulk upserts, index management, and batched pagination.

**Aggregation pipelines**
- Use `collection.aggregate(pipeline)` to return a **cursor** (must be consumed in a context manager)
- Common stages: `$match` (filter), `$group` (aggregate), `$project` (shape output), `$sort`, `$limit`, `$unwind` (flatten arrays)
- Pattern: `with collection.aggregate(query) as cursor: document_list = list(cursor)`
- The DAO method returns `(success: bool, results: list[dict])` tuple (anti-pattern: boolean tuple returns; prefer Optional or exceptions)

**Bulk upserts**
- Build `UpdateOne` operations with `upsert=True`, call `bulk_write(operations, ordered=False)`
- `ordered=False` continues on errors (doesn't stop at first failure)
- Pattern: loop write requests, construct `match` dict from filter columns, build `{"$set": {k: v for k, v in doc.items() if k != "_id"}}` update dict
- `UpdateOne(match, {"$set": update_dict}, upsert=True)` inserts if no match, updates if match
- Append to `bulk_operations` list, then `collection.bulk_write(bulk_operations, ordered=False)`

**Index creation**
- Use `IndexModel` to specify fields and options, call `collection.create_indexes(index_models)`
- Index spec formats: simple `[("field", ASCENDING)]`, compound `[("field1", ASCENDING), ("field2", DESCENDING)]`, with options `([("field", ASCENDING)], {"unique": True})`
- Create indexes on **startup** by looping collection definitions and calling `MongoDB.create_index(collection_name, indexes)`
- The method handles both plain field lists and `(fields, options)` tuples

**Batched pagination**
- Use `skip` and `limit` cursor methods for offset-based pagination
- Pattern: `collection.find(query, skip=skip_count, limit=page_size)` where `skip_count = max(0, (page_number - 1) * page_size)`
- Wrap cursor in context manager: `with collection.find(...) as cursor: documents = list(cursor)`
- For large datasets, prefer cursor-based pagination (filtering by `_id` or timestamp) over offset-based (skip is slow for high offsets)

**Example skeleton**

```python
from pymongo import MongoClient, UpdateOne, IndexModel, ASCENDING, DESCENDING

# Aggregation pipeline
pipeline = [
    {"$match": {"status": "active"}},
    {"$group": {"_id": "$category", "count": {"$sum": 1}}},
    {"$sort": {"count": -1}},
    {"$limit": 10}
]
with collection.aggregate(pipeline) as cursor:
    results = list(cursor)

# Bulk upsert
bulk_operations = []
for document in write_requests:
    match = {filter_col: document[filter_col] for filter_col in filter_columns}
    update_op = UpdateOne(
        match,
        {"$set": {k: v for k, v in document.items() if k != "_id"}},
        upsert=True,
    )
    bulk_operations.append(update_op)

collection.bulk_write(bulk_operations, ordered=False)

# Index creation
index_models = []
for index_spec in indexes:
    if isinstance(index_spec, tuple) and len(index_spec) == 2:
        fields, options = index_spec
        index_models.append(IndexModel(fields, **options))
    else:
        index_models.append(IndexModel(index_spec))

collection.create_indexes(index_models)

# Batched pagination
page_number = 1
page_size = 100
skip_count = max(0, (page_number - 1) * page_size)

with collection.find(query, skip=skip_count, limit=page_size) as cursor:
    documents = list(cursor)
```

See `mongodb-advanced.md` for full pipeline examples, bulk operation details, and index patterns.

## Skeleton / example

```python
# SQLAlchemy 2.0 model
from sqlalchemy import String, Integer
from sqlalchemy.orm import Mapped, mapped_column, DeclarativeBase

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

# Connection lifecycle with async_scoped_session
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_scoped_session
from sqlalchemy.orm import sessionmaker
from asyncio import current_task
from typing import AsyncGenerator

class ConnectionManager:
    def __init__(self) -> None:
        self._db_engine, self._db_session_factory = self._setup_db()
    
    def _setup_db(self):
        engine = create_async_engine("postgresql+asyncpg://...", echo=False, pool_pre_ping=True)
        session_factory = async_scoped_session(
            sessionmaker(engine, expire_on_commit=False, class_=AsyncSession),
            scopefunc=current_task,
        )
        return engine, session_factory

class ConnectionHandler:
    def __init__(self) -> None:
        self._session = None
        self._connection_manager = ConnectionManager()
    
    @property
    def session(self) -> AsyncSession:
        if not self._session:
            self._session = self._connection_manager.get_session_factory()()
        return self._session
    
    async def close(self) -> None:
        if self._session:
            await self._session.close()
            self._session = None

async def get_connection_handler() -> AsyncGenerator[ConnectionHandler, None]:
    handler = ConnectionHandler()
    try:
        yield handler
    finally:
        await handler.close()

# BaseDao
from sqlalchemy import select, update, delete, func, asc, desc
from sqlalchemy.inspection import inspect

class BaseDao:
    def __init__(self, session: AsyncSession, db_model):
        self.session = session
        self.db_model = db_model
    
    async def _commit(self):
        await self.session.commit()
    
    async def _execute_query(self, query):
        return await self.session.execute(query)
    
    def get_orm_object(self, **kwargs):
        return self.db_model(**kwargs)
    
    def add_object(self, create_object_dict=None, **create_kwargs):
        kwargs = create_object_dict or create_kwargs
        orm_object = self.get_orm_object(**kwargs)
        self.session.add(orm_object)
        return orm_object
    
    async def create(self, create_object_dict=None, **create_kwargs):
        orm_object = self.add_object(create_object_dict, **create_kwargs)
        await self._commit()
        return orm_object
    
    async def get_by_pk(self, pk_value):
        return await self.session.get(self.db_model, pk_value)
    
    async def update_by_pk(self, pk_values, update_values_dict=None, **update_kwargs):
        if not isinstance(pk_values, list):
            pk_values = [pk_values]
        pk_field = getattr(self.db_model, inspect(self.db_model).primary_key[0].name)
        kwargs = update_values_dict or update_kwargs
        query = update(self.db_model).where(pk_field.in_(pk_values)).values(**kwargs)
        return await self._execute_query(query)
    
    async def get_paginated_response(self, query, page_size: int, page_number: int, sort_by=None, order_by=None, count_field=None):
        if count_field is None:
            count_field = getattr(self.db_model, inspect(self.db_model).primary_key[0].name)
        
        count_query = query.with_only_columns(func.count(func.distinct(count_field))).order_by(None)
        total_records = (await self._execute_query(count_query)).scalar()
        
        if sort_by and order_by:
            column_to_sort = getattr(self.db_model, sort_by)
            order_by_clause = desc(column_to_sort) if order_by.lower() == "desc" else asc(column_to_sort)
            query = query.order_by(order_by_clause)
        
        paginated_query = query.limit(page_size).offset(page_size * (page_number - 1))
        result = (await self._execute_query(paginated_query)).unique().all()
        
        pagination_info = {
            "page_size": page_size,
            "page_number": page_number,
            "has_next": total_records - page_size * page_number > 0,
            "total_records": total_records,
        }
        return result, pagination_info

# Concrete DAO
class UserDao(BaseDao):
    def __init__(self, session: AsyncSession):
        super().__init__(session, User)
    
    async def get_by_email(self, email: str):
        query = select(User).where(User.email == email)
        result = await self._execute_query(query)
        return result.unique().scalar_one_or_none()
    
    async def get_users_with_organizations(self, page_size: int, page_number: int):
        """Get users with their organizations eagerly loaded (prevents N+1)."""
        from sqlalchemy.orm import selectinload
        
        query = select(User).options(selectinload(User.organization))
        users, pagination_info = await self.get_paginated_response(
            query, page_size, page_number, sort_by="created_at", order_by="desc"
        )
        return users, pagination_info
```

## Anti-patterns to avoid

- **NO async_scoped_session**: plain `sessionmaker` without scoping leads to session leaks under concurrent requests; always use `async_scoped_session(..., scopefunc=current_task)`
- **Missing rollback**: Most DAO methods commit but do NOT rollback on exception; if you modify data and call `_commit()`, wrap in try/except with `await self.session.rollback()` in the except block
- **No specific IntegrityError handling**: Catching generic `Exception` instead of `IntegrityError` for unique constraint violations loses context; handle `sqlalchemy.exc.IntegrityError` explicitly
- **Inefficient bulk update**: looping per row with individual `update()` statements is slow; prefer `session.bulk_update_mappings` or a single multi-row `update().where(pk.in_(...)).values(...)`
- **Module-level session**: NEVER store `AsyncSession` or `ConnectionHandler` at module/class scope; always create per-request via dependency injection
- **Forgotten `unique()`**: when joining tables (especially with `joinedload`), always call `.unique()` before `.all()` to deduplicate results
- **N+1 queries**: Accessing relationships in loops without eager loading (`selectinload` / `joinedload`) triggers one query per item; enable `echo=True` to detect
- **Copy-pasted BaseDao**: if BaseDao is identical across services, extract to a shared library (DRY violation)

## References

- [repo-evidence.md](./references/repo-evidence.md) — file paths and short snippets from source repos
- [basedao-and-sessions.md](./references/basedao-and-sessions.md) — BaseDao method surface, ConnectionManager patterns, pagination/bulk/partition details
- [sqlalchemy-1x-vs-2x.md](./references/sqlalchemy-1x-vs-2x.md) — side-by-side comparison of 1.4 vs 2.0 model and query idioms
- [other-db-mongodb.md](./references/other-db-mongodb.md) — static-class MongoDB DAO pattern (sync pymongo)
- [advanced-query-patterns.md](./references/advanced-query-patterns.md) — eager loading (selectinload, joinedload), query optimization, transaction isolation, row-level locking, alembic migrations, N+1 prevention
- [mongodb-advanced.md](./references/mongodb-advanced.md) — aggregation pipelines, bulk upserts (UpdateOne + bulk_write), index creation (IndexModel), batched/cursor pagination
