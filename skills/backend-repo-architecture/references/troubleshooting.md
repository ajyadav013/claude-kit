# Troubleshooting and Common Pitfalls

Common issues, debugging techniques, and solutions when working with the backend archetype.

## Connection issues

### "asyncpg.exceptions.TooManyConnectionsError"

**Symptom**: Service crashes or hangs after sustained load. Logs show "sorry, too many clients already".

**Root cause**: ConnectionManager not properly closing sessions, or pool size too small.

**Fix**:
1. Verify `get_connection_handler()` dependency always calls `handler.close()` in finally block.
2. Increase pool size: `DB_POOL_SIZE=50` (default 30), `DB_MAX_OVERFLOW=50` (default 40).
3. Check for leaked sessions: add `ConnectionHandler.__del__` that warns if session not closed.

```python
class ConnectionHandler:
    def __del__(self):
        if self._session and not self._session.is_active:
            logger.warning("ConnectionHandler garbage collected without close()")
```

---

### "Redis connection pool exhausted"

**Symptom**: `redis.exceptions.ConnectionError: Error while reading from socket`.

**Root cause**: Redis client not configured with connection pool, or max connections too low.

**Fix**:
```python
# In ConnectionManager
self._redis = Redis.from_url(
    settings.REDIS_URL,
    max_connections=100,  # Add explicit pool size
    socket_connect_timeout=5,
    socket_keepalive=True,
)
```

---

### "sqlalchemy.exc.InvalidRequestError: This session is already closed"

**Symptom**: Intermittent 500 errors on routes.

**Root cause**: Accessing session after `handler.close()` called, or session used across async context boundaries.

**Fix**:
1. Never store session in module-level variables or class attributes.
2. Always inject `ConnectionHandler` via `Depends(get_connection_handler)` per-request.
3. Check for `await` on async DAO methods - forgetting `await` can cause session to close prematurely.

---

## Routing issues

### "404 Not Found" on valid route

**Symptom**: Route works in local dev but 404 in production.

**Root cause**: Router not included in `api_router`, or wrong prefix.

**Debug**:
```python
# Add to application.py
@app.on_event("startup")
async def log_routes():
    for route in app.routes:
        if hasattr(route, "path"):
            logger.info(f"Registered route: {route.methods} {route.path}")
```

**Fix**: Verify `app/router.py` includes the domain router:
```python
api_router.include_router(domain_router, prefix="/v1", tags=["Domain"])
```

---

### "307 Temporary Redirect" on POST

**Symptom**: POST/PUT/PATCH requests return 307, redirect to same URL with trailing slash.

**Root cause**: FastAPI's `redirect_slashes=True` (default) redirects `/foo` to `/foo/` if only latter is registered.

**Fix**: Set `redirect_slashes=False` in application factory:
```python
app = FastAPI(
    debug=settings.DEBUG,
    redirect_slashes=False,  # Prevent ambiguous routing
)
```

**Alternative**: Ensure route paths are consistent (all with or all without trailing slash).

---

### "422 Unprocessable Entity" on valid JSON

**Symptom**: Request body validation fails even though JSON matches schema.

**Root cause**: Pydantic schema field mismatch (snake_case vs camelCase), or missing alias.

**Debug**:
```python
# Enable request body logging in routing.py
logger.debug(f"Request body: {await request.body()}")
```

**Fix**: Add `model_config` to schema:
```python
class SizeSchema(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,  # Accept both snake_case and alias
        alias_generator=to_camel,  # Auto-generate camelCase aliases
    )
```

---

## DAO issues

### "DetachedInstanceError: Instance is not bound to a Session"

**Symptom**: Accessing model attributes after session closed raises error.

**Root cause**: Model returned from DAO, session closed, then attributes accessed.

**Fix**: Use `selectinload()` or `joinedload()` to eagerly load relationships, or commit before closing:
```python
# Bad
user = await dao.get_by_pk(user_id)
await handler.close()
return user.groups  # Error: groups not loaded

# Good
user = await dao.get_by_pk(user_id, load_relationships=True)
# Or explicitly load
stmt = select(User).where(User.id == user_id).options(selectinload(User.groups))
result = await session.execute(stmt)
user = result.scalar_one()
```

---

### "PendingRollbackError: This Session's transaction has been rolled back"

**Symptom**: Second query in a route raises error after first query fails.

**Root cause**: First query raised exception, session auto-rolled back, second query attempted on rolled-back session.

**Fix**: Let `_execute_query` handle rollback, or manually rollback and start new transaction:
```python
try:
    await dao.create(item)
except Exception:
    await session.rollback()
    # Start new transaction or re-raise
```

**Better**: Structure code so each route has single transaction boundary, use service layer to orchestrate multiple DAO calls.

---

## Async issues

### "RuntimeError: no running event loop"

**Symptom**: Calling async code from sync context raises error.

**Root cause**: Mixing sync and async incorrectly, or calling `asyncio.run()` inside async function.

**Fix**:
1. Never call `asyncio.run()` inside async function - use `await` instead.
2. If must call async from sync (e.g., `__init__`), use `asyncio.create_task()` or move logic to async method.
3. Use `@asynccontextmanager` for lifespan, not sync context manager.

---

### "Task was destroyed but it is pending"

**Symptom**: Warning on shutdown, tasks left running.

**Root cause**: Background tasks created but not awaited or cancelled on shutdown.

**Fix**: Track background tasks and cancel on shutdown:
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    tasks = []
    
    # Startup
    task = asyncio.create_task(background_worker())
    tasks.append(task)
    
    yield
    
    # Shutdown: cancel and wait
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
```

---

## Config issues

### "ValidationError: field required"

**Symptom**: Service fails to start, pydantic validation error on Settings.

**Root cause**: Required env var not set.

**Fix**:
1. Add default value for non-secrets: `DEBUG: bool = False`.
2. For secrets, fail fast: raise exception if missing, never default to unsafe value.
3. Use `.env.example` to document all required vars.

---

### "Config mismatch between docker_config and config_parser"

**Symptom**: Value set in YAML not respected, env var used instead.

**Root cause**: Precedence confusion - env > YAML, but code reads wrong source.

**Fix**: Understand precedence (CLI > env > YAML > default), always import from `loaded_config`:
```python
# Wrong
worker_mode = os.environ.get("WORKER_MODE")

# Right
from config.docker_config import loaded_config
worker_mode = loaded_config.WORKER_MODE
```

---

## MODE dispatcher issues

### "MODE server not available" but MODE="server"

**Symptom**: Entrypoint prints "MODE server not available" even though MODE is set.

**Root cause**: Lazy import failure, module doesn't exist, or entrypoint.py has wrong if/elif chain.

**Debug**:
```python
MODE = os.environ.get("MODE")
print(f"MODE={MODE}, type={type(MODE)}")

if MODE == "server":
    try:
        from src.main import main as server_main
        print("Imported server_main successfully")
        server_main()
    except Exception as e:
        print(f"Failed to import or run server_main: {e}")
        raise
```

**Fix**: Verify imports work, check for circular dependencies.

---

### "Consumer starts but doesn't consume messages"

**Symptom**: Consumer process runs but no messages processed from Kafka.

**Root cause**: Consumer group ID conflict, wrong topic, or Kafka connection failure.

**Debug**:
```python
# Add to consumer.py
logger.info(f"Consumer starting: group={CONSUMER_GROUP}, topics={TOPICS}, brokers={BROKERS}")
logger.info(f"Subscribed to topics: {consumer.subscription()}")

# Enable Kafka debug logs
import logging
logging.getLogger("aiokafka").setLevel(logging.DEBUG)
```

**Fix**:
1. Verify `KAFKA_BOOTSTRAP_SERVERS`, `KAFKA_CONSUMER_GROUP`, topic names.
2. Check Kafka cluster reachable: `telnet kafka 9092`.
3. Use unique consumer group ID per environment (dev/staging/prod).

---

## Alembic migration issues

### "Target database is not up to date"

**Symptom**: Alembic refuses to run migration, says current revision != expected.

**Root cause**: Deployed code expects newer schema version than DB has.

**Fix**:
1. Run migrations before deploying new code: `alembic upgrade head`.
2. Use init container in k8s to run migrations before app starts:
```yaml
initContainers:
- name: migrate
  image: myservice:latest
  command: ["alembic", "upgrade", "head"]
  env:
  - name: DATABASE_URL
    valueFrom:
      secretKeyRef:
        name: myservice-secrets
        key: database-url
```

---

### "Can't locate revision identified by 'xxxxx'"

**Symptom**: Alembic can't find migration file.

**Root cause**: Migration file deleted, or alembic.ini `version_locations` wrong.

**Fix**:
1. Never delete migration files - revert via new migration.
2. Verify `alembic/versions/` contains all migrations.
3. Check `alembic.ini` `version_locations = alembic/versions`.

---

## Performance issues

### "High latency on simple queries"

**Symptom**: `SELECT * FROM users WHERE id = ?` takes >100ms.

**Root cause**: Missing index, N+1 queries, or connection pool exhaustion.

**Debug**:
1. Enable query logging: `DB_ECHO=True`.
2. Check for N+1: if query count scales with result count, add `selectinload()`.
3. Run `EXPLAIN ANALYZE` on slow queries.

**Fix**:
1. Add indexes on frequently queried columns (foreign keys, filter columns).
2. Use `selectinload()` or `joinedload()` for relationships.
3. Add caching layer (Redis) for hot data.

---

### "Memory leak: RSS grows unbounded"

**Symptom**: Container OOMKilled after hours/days, RSS grows linearly.

**Root cause**: Sessions not closed, or large objects not garbage collected.

**Debug**:
1. Use `tracemalloc` to profile memory:
```python
import tracemalloc
tracemalloc.start()

# ... run app ...

snapshot = tracemalloc.take_snapshot()
top_stats = snapshot.statistics('lineno')
for stat in top_stats[:10]:
    print(stat)
```

2. Check for leaked sessions: add `__del__` to `ConnectionHandler` that warns.

**Fix**:
1. Verify `get_connection_handler()` always closes session.
2. Avoid storing large objects (query results) in module-level variables.
3. Use `expire_on_commit=False` in session factory to prevent implicit lazy loads after commit.

---

## Debugging techniques

### Enable verbose SQL logging

```python
# config/settings.py
DB_ECHO: bool = True  # Log all SQL queries

# In ConnectionManager
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DB_ECHO,  # SQLAlchemy query logging
    pool_pre_ping=True,  # Verify connections before use
)
```

---

### Structured logging with context

```python
# config/logging.py
import structlog

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ],
)

# In routes
logger = structlog.get_logger()
logger.info("processing_request", user_id=user_id, action="create")
```

---

### Request/response logging

```python
# app/routing.py
class CustomRequestRoute(APIRoute):
    async def custom_route_handler(self, request: Request):
        start = time.time()
        body = await request.body()
        logger.debug(f"Request body: {body.decode()}")
        
        response = await original_route_handler(request)
        
        duration = time.time() - start
        logger.info(
            f"{request.method} {request.url.path} -> {response.status_code} ({duration:.3f}s)"
        )
        return response
```

---

### Distributed tracing

```python
# app/telemetry.py
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

def instrument_app(app: FastAPI):
    FastAPIInstrumentor.instrument_app(app)
    SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)

# In routes
tracer = trace.get_tracer(__name__)
with tracer.start_as_current_span("fetch_user"):
    user = await dao.get_by_pk(user_id)
```

---

## Best practices for debugging

1. **Fail fast**: Validate config on startup, never swallow exceptions silently.
2. **Structured logging**: Use JSON logs with context (user_id, request_id, trace_id).
3. **Metrics**: Expose `/metrics` endpoint (Prometheus), track query latency, error rate, pool size.
4. **Health checks**: Implement `/_readyz` that actually checks dependencies (DB, Redis, Kafka).
5. **Request IDs**: Add `X-Request-ID` header to all requests, propagate through logs/traces.
6. **Circuit breakers**: Wrap external calls (third-party APIs) with timeout and retry logic.
7. **Graceful degradation**: If Redis down, serve stale cache or bypass cache, never fail hard.
