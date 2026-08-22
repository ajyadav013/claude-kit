# BaseDao and Session Lifecycle

Deep dive into the BaseDao method surface, ConnectionManager/ConnectionHandler patterns, and session lifecycle.

## BaseDao method surface

Production services commonly implement a shared `BaseDao` abstraction that wraps SQLAlchemy ORM operations. The class takes `session: AsyncSession` and `db_model` (the SQLAlchemy model class) in `__init__`.

### Core methods (commonly implemented)

```python
class BaseDao:
    def __init__(self, session: AsyncSession, db_model):
        self.session = session
        self.db_model = db_model

    # Transaction helpers
    async def _flush(self) -> None
    async def _commit(self) -> None
    async def _execute_query(self, query: Union[Select, text]) -> Any

    # Object construction
    def get_orm_object(self, **kwargs) -> Base
    def add_object(self, create_object_dict=None, **create_kwargs) -> Base

    # CRUD
    async def create(self, create_object_dict=None, **create_kwargs) -> Base
    async def get_by_pk(self, pk_value) -> Optional[Base]
    async def update_by_pk(self, pk_values, update_values_dict=None, **update_kwargs)
    async def delete_by_pk(self, pk_value) -> bool

    # Bulk
    def bulk_add_objects(self, create_objects_list: List[dict]) -> List[Base]

    # Pagination
    async def get_paginated_response(self, query, page_size, page_number, sort_by=None, order_by=None, count_field=None)
```

### Advanced methods (in some implementations)

```python
class BaseDao:
    # Query DSL
    def apply_filters(self, query, query_filters: list[QueryFilter])
    def apply_sort(self, query, ordering_clauses: list[OrderingClause])
    def load_columns(self, query, columns: list[str])
    async def get(self, query=None, query_filters=None, columns=None, ordering_clauses=None, limit=None, offset=None)

    # Postgres partitions (raw SQL)
    async def create_partition(self, partition_value) -> str
    async def create_partitions_in_bulk(self, object_ids: List[Any]) -> None

    # Pandas integration (in some implementations)
    async def fetch_from_db(self, query: Union[Select, TextClause]) -> pd.DataFrame

    # Bulk update (ANTI-PATTERN: loops per row)
    async def bulk_update(self, update_objects_list: List[Dict], pk_field_name=None) -> None
```

## Transaction patterns

### Standard flow

Most DAO methods commit explicitly after modifying data:

```python
async def create(self, create_object_dict=None, **create_kwargs):
    orm_object = self.add_object(create_object_dict, **create_kwargs)
    await self._commit()  # Explicit commit
    return orm_object
```

### ANTI-PATTERN: No rollback

Most DAOs do NOT wrap commits in try/except or rollback on failure. The session is left in an inconsistent state if the commit fails.

**Exception** (some implementations of `bulk_insert`, `bulk_update`):

```python
async def bulk_insert(self, create_objects_list: List[Dict]) -> List[Base]:
    try:
        orm_objects = [self.add_object(create_object_dict) for create_object_dict in create_objects_list]
        self.session.add_all(orm_objects)
        await self._commit()
        return orm_objects
    except Exception as e:
        await self.session.rollback()
        raise e
```

### NO unit-of-work

Each DAO method commits independently. There is NO higher-level unit-of-work that batches multiple DAO calls into a single transaction. To perform multi-table writes atomically, you must:

1. Use the same session across multiple DAO instances
2. Call `add_object` / `session.add` for each DAO (do NOT call `create`, which commits immediately)
3. Manually call `await session.commit()` once at the end

## ConnectionManager patterns

### Preferred pattern

```python
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_scoped_session, create_async_engine
from asyncio import current_task
from sqlalchemy.orm import sessionmaker

class ConnectionManager(metaclass=Singleton):
    _db_engine: AsyncEngine
    _db_session_factory: Callable[..., AsyncSession]

    def __init__(self) -> None:
        self._db_engine, self._db_session_factory = self._setup_db()

    def get_session_factory(self) -> Callable[..., AsyncSession]:
        return self._db_session_factory

    @staticmethod
    def _setup_db() -> Tuple[AsyncEngine, Callable[..., AsyncSession]]:
        async_db_url = "postgresql+asyncpg://..."
        engine = create_async_engine(async_db_url, echo=False, pool_pre_ping=True)
        session_factory = async_scoped_session(
            sessionmaker(engine, expire_on_commit=False, class_=AsyncSession),
            scopefunc=current_task,
        )
        return engine, session_factory
```

**Key points:**
- `async_scoped_session` ensures each asyncio task gets its own session
- `scopefunc=current_task` ties session lifecycle to the current asyncio task
- `expire_on_commit=False` prevents lazy-loading after commit (objects remain usable)
- `pool_pre_ping=True` validates connections before use (prevents stale connections)

### ANTI-PATTERN (observed in some services)

```python
class ConnectionManager:
    def _setup_db(self):
        async_engine = create_async_engine(str(self.db_url), echo=self.db_echo, pool_pre_ping=True)
        async_session_factory = sessionmaker(  # Plain sessionmaker, NOT async_scoped_session
            async_engine,
            expire_on_commit=False,
            class_=AsyncSession,
        )
        return async_engine, async_session_factory
```

**Problem:** Without `async_scoped_session`, concurrent requests may share the same session, leading to:
- Session leaks (sessions not closed)
- Race conditions (concurrent tasks modifying the same session)
- Incorrect transaction boundaries

## ConnectionHandler pattern

```python
class ConnectionHandler:
    _session: Optional[AsyncSession]
    _connection_manager: ConnectionManager

    def __init__(self) -> None:
        self._session = None
        self._connection_manager = ConnectionManager()

    @property
    def session(self) -> AsyncSession:
        if not self._session:
            session_factory = self._connection_manager.get_session_factory()
            self._session = session_factory()
        return self._session

    async def close(self) -> None:
        if self._session:
            session = self._session
            self._session = None
            await session.close()
```

The `session` property is lazy: the session is created only on first access. This avoids creating sessions for requests that don't touch the database.

## FastAPI dependency pattern

```python
async def get_connection_handler() -> AsyncGenerator[ConnectionHandler, None]:
    handler = ConnectionHandler()
    try:
        yield handler
    finally:
        await handler.close()

# In a route
@app.get("/users/{user_id}")
async def get_user(user_id: int, handler: ConnectionHandler = Depends(get_connection_handler)):
    dao = UserDao(handler.session)
    user = await dao.get_by_pk(user_id)
    return user
```

The `finally` block ensures the session is closed even if the route raises an exception.

## Pagination implementation

```python
async def get_paginated_response(
    self,
    query: Select,
    page_size: int,
    page_number: int,
    sort_by: str = None,
    order_by: str = None,
    count_field = None,
):
    # 1. Determine count field (defaults to primary key)
    if count_field is None:
        pk_field_name = inspect(self.db_model).primary_key[0].name
        count_field = getattr(self.db_model, pk_field_name)

    # 2. Build count query (strip order_by to avoid unnecessary sorting)
    count_query = query.with_only_columns(
        func.count(func.distinct(count_field))
    ).order_by(None)
    count_result = await self._execute_query(count_query)
    total_records = count_result.scalar()

    # 3. Compute pagination info
    pagination_info = {
        "page_size": page_size,
        "page_number": page_number,
        "has_next": total_records - page_size * page_number > 0,
        "total_records": total_records,
    }

    # 4. Apply sorting
    if sort_by and order_by:
        column_to_sort = getattr(self.db_model, sort_by)
        order_by_clause = desc(column_to_sort) if order_by.lower() == "desc" else asc(column_to_sort)
        query = query.order_by(order_by_clause)

    # 5. Apply pagination
    paginated_query = query.limit(page_size).offset(page_size * (page_number - 1))
    query_result = await self._execute_query(paginated_query)
    result = query_result.unique().all()  # unique() deduplicates joined results

    return result, pagination_info
```

**Key techniques:**
- `with_only_columns(func.count(...))` replaces the select list with a count
- `order_by(None)` strips existing ORDER BY clauses (count doesn't need ordering)
- `func.distinct(count_field)` prevents overcounting in joins
- `unique().all()` deduplicates rows when using joinedload/subqueryload
- Offset formula: `page_size * (page_number - 1)` (page_number is 1-based)

## Bulk operations

### Bulk insert (efficient)

```python
def bulk_add_objects(self, create_objects_list: List[dict]) -> List[Base]:
    orm_objects = [self.get_orm_object(**create_object_dict) for create_object_dict in create_objects_list]
    self.session.add_all(orm_objects)  # Efficient: single roundtrip
    return orm_objects
```

`add_all` batches all inserts into a single database roundtrip.

### Bulk update (ANTI-PATTERN: inefficient)

```python
async def bulk_update(self, update_objects_list: List[Dict], pk_field_name: Optional[str] = None) -> None:
    if not pk_field_name:
        pk_field_name = inspect(self.db_model).primary_key[0].name
    
    for update_obj in update_objects_list:  # ANTI-PATTERN: loop
        pk_value = update_obj.pop(pk_field_name)
        update_query = (
            update(self.db_model)
            .where(getattr(self.db_model, pk_field_name) == pk_value)
            .values(**update_obj)
        )
        await self._execute_query(update_query)  # One UPDATE per row
    await self._commit()
```

**Problem:** This issues one `UPDATE` statement per row. For 1000 rows, this is 1000 roundtrips.

**Better approach:**

```python
# Option 1: bulk_update_mappings (SQLAlchemy Core)
await session.execute(
    update(Model),
    [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}],
    execution_options={"synchronize_session": False}
)

# Option 2: Single update with WHERE IN (if all rows get the same values)
await session.execute(
    update(Model)
    .where(Model.id.in_([1, 2, 3]))
    .values(status="active")
)
```

## Partition management

Postgres declarative partitioning via raw SQL:

```python
async def create_partition(self, partition_value: Any) -> str:
    partition_name = f"{self.db_model.__tablename__}_{partition_value}"
    create_partition_sql = text(
        f"""CREATE TABLE IF NOT EXISTS {partition_name} PARTITION OF {self.db_model.__tablename__} FOR VALUES IN ({partition_value});"""
    )
    await self.session.execute(create_partition_sql)
    await self.session.commit()
    return partition_name

async def create_partitions_in_bulk(self, object_ids: List[Any]) -> None:
    tasks = [self.create_partition(object_id) for object_id in object_ids]
    for task in tasks:
        await task  # Sequential (could be concurrent with asyncio.gather)
```

**Note:** This creates list-partitioned tables. For range partitions, replace `FOR VALUES IN (...)` with `FOR VALUES FROM (...) TO (...)`.

## Copy-paste smell

`BaseDao`, `ConnectionManager`, and `ConnectionHandler` are often nearly identical across services. This is a DRY violation. Consider extracting these to a shared internal library and installing it via pip.
