# Troubleshooting Guide

Common issues when implementing the design patterns from this skill, with diagnostics and fixes.

---

## 1. Session Leaks / "Session is not bound to a connection"

**Symptom:**
- Error: `Session is not bound to a connection`
- Memory leaks (session objects not closed)
- Stale data returned after updates

**Root Cause:**
- Using unscoped sessionmaker (no `scopefunc`) in async context
- Multiple concurrent requests sharing the same session
- Not closing sessions in `finally` block

**Diagnosis:**
```bash
# Check if sessionmaker uses scopefunc
grep -A10 "sessionmaker" app/connection.py | grep scopefunc
# If no output, you have unscoped sessions
```

**Fix:**
```python
# BEFORE (anti-pattern):
async_session_factory = sessionmaker(
    async_engine,
    expire_on_commit=False,
    class_=AsyncSession,
)  # NO scopefunc

# AFTER (correct pattern):
from sqlalchemy.ext.asyncio import async_scoped_session
from asyncio import current_task

session_factory = async_scoped_session(
    sessionmaker(async_engine, expire_on_commit=False, class_=AsyncSession),
    scopefunc=current_task,
)
```

**Prevention:**
- Always use `async_scoped_session(scopefunc=current_task)` for async applications
- Always close sessions in `finally` block or use context managers
- Use `Depends(get_connection_handler_for_app)` to ensure automatic cleanup

---

## 2. Event Loop Blocked / Slow API Responses

**Symptom:**
- API responses take 5-10+ seconds for simple queries
- Other concurrent requests are delayed
- `asyncio` warning: "Task was destroyed but it is pending"

**Root Cause:**
- Calling synchronous blocking I/O (BigQuery, GCS, `requests`) inside async route handlers
- Blocking the event loop starves other requests

**Diagnosis:**
```bash
# Find sync clients in async code
grep -rE "from google.cloud import (bigquery|storage)" app/ | xargs grep -l "async def"
grep -r "import requests" app/ | xargs grep -l "async def"
```

**Fix:**
```python
# BEFORE (sync BigQuery client in async route):
from google.cloud import bigquery

@router.get("/query")
async def run_query():
    client = bigquery.Client()
    result = client.query("SELECT * FROM table")  # BLOCKS event loop
    return list(result)

# AFTER (run in executor):
import asyncio
from google.cloud import bigquery

client = bigquery.Client()

@router.get("/query")
async def run_query():
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, client.query, "SELECT * FROM table")
    rows = await loop.run_in_executor(None, list, result)
    return rows

# BETTER (use async client):
from google.cloud.bigquery import AsyncClient

async_client = AsyncClient()

@router.get("/query")
async def run_query():
    result = await async_client.query("SELECT * FROM table")
    return [row async for row in result]
```

**Prevention:**
- Use async clients: `httpx.AsyncClient`, `aiohttp`, `aiokafka`, `asyncpg`, `aiofiles`
- If async client unavailable, use `asyncio.to_thread()` or `loop.run_in_executor()`
- Audit: `ruff check --select ASYNC` (detects blocking calls in async functions)

---

## 3. Duplicate Endpoints / Router Registered Twice

**Symptom:**
- FastAPI raises `HTTPException: Route already exists` on startup
- OpenAPI docs show duplicate endpoints
- Confusing routing behavior (which handler executes?)

**Root Cause:**
- Same router included multiple times (copy-paste error)
- Example: `webhook_callback_router` included twice in production service

**Diagnosis:**
```bash
# Find duplicate include_router calls
grep -n "include_router" src/routers.py | sort | uniq -c | awk '$1 > 1 {print}'
```

**Fix:**
```python
# BEFORE (anti-pattern):
api_router_v1_prefix.include_router(webhook_callback_router, prefix="/webhooks", tags=["webhooks-callback"])
# ... 3 lines later ...
api_router_v1_prefix.include_router(webhook_callback_router, prefix="/webhooks", tags=["webhooks-callback"])  # DUPLICATE

# AFTER:
api_router_v1_prefix.include_router(webhook_callback_router, prefix="/webhooks", tags=["webhooks-callback"])
# (Remove the duplicate line)
```

**Prevention:**
- Keep a single `routers.py` or `app/router.py` file
- Review `include_router()` calls during code review
- Add a pre-commit hook to detect duplicates

---

## 4. Hardcoded Secrets in Logs / Version Control

**Symptom:**
- Secrets appear in application logs
- Credentials committed to Git
- Security audit findings

**Root Cause:**
- Hardcoding secrets in Dockerfiles, config defaults, or logging request bodies without redaction

**Diagnosis:**
```bash
# Find hardcoded secrets
grep -rE "(password|token|secret|api_key).*=.*['\"]" --include="*.py" --include="Dockerfile" .
# Check logs for sensitive data
grep -r "logger.info.*request" app/ | grep -v "redact"
```

**Fix:**
```python
# BEFORE:
class Settings(BaseSettings):
    API_TOKEN: str = "sk_live_<REDACTED>"  # HARDCODED — never do this

# AFTER:
class Settings(BaseSettings):
    API_TOKEN: str  # No default; must come from environment

# BEFORE (logging sensitive data):
logger.info(f"Request data: {request_data}")

# AFTER (redact sensitive fields):
SENSITIVE_FIELDS = {"password", "token", "authorization", "x-api-key", "secret"}

def redact_sensitive(data: dict) -> dict:
    return {k: "<REDACTED>" if k.lower() in SENSITIVE_FIELDS else v for k, v in data.items()}

logger.info("Request data", extra={"request_data": redact_sensitive(request_data)})
```

**Prevention:**
- Use environment variables for all secrets
- Add `.env` to `.gitignore`
- Use secret scanning tools: `git-secrets`, `truffleHog`, `detect-secrets`
- Redact sensitive fields before logging

---

## 5. CORS Errors in Browser

**Symptom:**
- Browser console: `Access to fetch at 'http://api.example.com' from origin 'http://app.example.com' has been blocked by CORS policy`
- API works in Postman/curl but not in browser

**Root Cause:**
- Missing or misconfigured `CORSMiddleware`
- `allow_origins=["*"]` in dev but restricted origins in production

**Diagnosis:**
```bash
# Check CORS config
grep -A5 "CORSMiddleware" app/main.py
```

**Fix:**
```python
# BEFORE (overly permissive):
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows any origin (security risk)
    allow_credentials=True,
)

# AFTER (production-safe):
from config.docker_config import loaded_config

app.add_middleware(
    CORSMiddleware,
    allow_origins=loaded_config.ALLOWED_ORIGINS.split(","),  # Env var: "https://app.example.com,https://admin.example.com"
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**Prevention:**
- Load `allow_origins` from environment variable
- Never use `["*"]` in production
- Test CORS config with browser DevTools Network tab

---

## 6. Deprecated Lifecycle Hook Warnings

**Symptom:**
- FastAPI startup warning: `DeprecationWarning: @app.on_event("startup") is deprecated, use lifespan instead`
- Application works but logs deprecation warnings

**Root Cause:**
- Using `@app.on_event("startup")` / `@app.on_event("shutdown")` (deprecated in FastAPI 0.109+)

**Diagnosis:**
```bash
# Find deprecated hooks
grep -rn "@.*\.on_event" --include="*.py" .
```

**Fix:**
```python
# BEFORE (anti-pattern):
@app.on_event("startup")
def startup_event():
    print("Application starting...")

@app.on_event("shutdown")
def shutdown_event():
    print("Application shutting down...")

# AFTER (lifespan context manager):
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic
    print("Application starting...")
    # Setup code here (e.g., initialize ConnectionManager, start Kafka producer)
    yield
    # Shutdown logic
    print("Application shutting down...")
    # Cleanup code here (e.g., close database connections, stop Kafka producer)

app = FastAPI(lifespan=lifespan)
```

**Prevention:**
- Migrate to `lifespan` context manager
- Run `ruff check` to detect deprecated patterns
- See FastAPI docs: https://fastapi.tiangolo.com/advanced/events/

---

## 7. Kafka Consumer Not Receiving Messages

**Symptom:**
- Kafka consumer runs but no messages are processed
- Producer sends messages successfully (verified in Kafka UI)

**Root Cause:**
- Wrong topic name (typo or env var not set)
- Consumer group already has committed offsets (skips old messages)
- Kafka broker unreachable or authentication failed

**Diagnosis:**
```bash
# Check consumer logs
docker logs <consumer-container-id> | grep -i "error\|exception"

# Verify topic exists
docker exec -it <kafka-container> kafka-topics --list --bootstrap-server localhost:9092

# Check consumer group offsets
docker exec -it <kafka-container> kafka-consumer-groups --bootstrap-server localhost:9092 --group <group-id> --describe
```

**Fix:**
```python
# BEFORE (hardcoded topic):
consumer.subscribe(["user-events"])  # Typo or wrong env

# AFTER (config-driven):
from config.docker_config import loaded_config

consumer.subscribe(loaded_config.KAFKA_CONSUMER_TOPICS.split(","))

# Reset consumer group offsets to consume from beginning (dev only):
# docker exec -it <kafka-container> kafka-consumer-groups --bootstrap-server localhost:9092 --group <group-id> --reset-offsets --to-earliest --execute --topic user-events
```

**Prevention:**
- Use environment variables for topics and consumer groups
- Log consumer subscription on startup: `logger.info(f"Subscribed to topics: {topics}")`
- Monitor consumer lag (Kafka UI, Prometheus metrics)

---

## 8. Temporal Worker Not Picking Up Workflows

**Symptom:**
- Temporal workflows stuck in "Running" state
- Worker logs show no activity
- Workflows time out

**Root Cause:**
- Worker registered with wrong task queue
- Worker not running (crashed or not started)
- Workflow/activity name mismatch

**Diagnosis:**
```bash
# Check worker logs
docker logs <temporal-worker-container> | grep -i "error\|exception"

# Verify task queue in Temporal UI
# Navigate to workflows, check task queue name
```

**Fix:**
```python
# BEFORE (hardcoded task queue):
worker = Worker(client, task_queue="my-queue", ...)  # Wrong queue

# AFTER (config-driven):
from config.docker_config import loaded_config

worker = Worker(client, task_queue=loaded_config.TEMPORAL_TASK_QUEUE, ...)

# Verify worker registration:
logger.info(f"Worker started on task queue: {loaded_config.TEMPORAL_TASK_QUEUE}")
```

**Prevention:**
- Use environment variables for task queues
- Log worker startup with task queue name
- Monitor worker health (Temporal UI, Prometheus metrics)

---

## 9. Missing Transaction Rollback / Partial Commits

**Symptom:**
- Database has partial/inconsistent data after an error
- Some records created, others missing (from the same transaction)

**Root Cause:**
- Manual `await session.commit()` scattered without try/except and rollback
- No unit-of-work pattern

**Diagnosis:**
```bash
# Find manual commits without rollback
grep -rn "session.commit()" app/ | xargs -I {} grep -L "rollback" {}
```

**Fix:**
```python
# BEFORE (no rollback):
async def create_order(order_data, session):
    order = await dao.create_order(order_data, session)
    await session.commit()  # If next line fails, order is committed but items are not
    await dao.create_order_items(order.id, order_data.items, session)
    await session.commit()

# AFTER (rollback on exception):
async def create_order(order_data, session):
    try:
        order = await dao.create_order(order_data, session)
        await dao.create_order_items(order.id, order_data.items, session)
        await session.commit()
    except Exception as e:
        await session.rollback()
        raise

# BETTER (unit-of-work via Depends generator):
async def get_connection_handler_for_app():
    connection_handler = ConnectionHandler()
    try:
        yield connection_handler
        await connection_handler.session.commit()  # Auto-commit on success
    except Exception:
        await connection_handler.session.rollback()  # Auto-rollback on error
        raise
    finally:
        await connection_handler.close()
```

**Prevention:**
- Use a Depends generator that handles commit/rollback
- Or use `async with session.begin():` context manager
- Never scatter manual commits; centralize transaction management

---

## 10. Multi-Mode Entrypoint Not Working / Wrong Mode Runs

**Symptom:**
- Set `MODE=consumer` but server starts instead
- Both server and consumer run simultaneously

**Root Cause:**
- `MODE` environment variable not set or typo
- Entrypoint doesn't check MODE correctly
- Multiple processes started (Docker CMD runs both)

**Diagnosis:**
```bash
# Check environment variable
docker exec <container> env | grep MODE

# Check entrypoint logic
grep -A10 "if.*MODE" entrypoint.py
```

**Fix:**
```python
# BEFORE (no MODE check):
# entrypoint.py
from app.main import main as server_main
server_main()  # Always runs server

# AFTER (mode-driven):
from config.docker_config import loaded_config
from app.main import main as server_main
from services.kafka.consumer.consumer import main as consumer_main

if loaded_config.MODE == "server":
    server_main()
elif loaded_config.MODE == "consumer":
    consumer_main()
else:
    raise ValueError(f"Unknown MODE: {loaded_config.MODE}")

# Dockerfile CMD:
CMD ["python", "entrypoint.py"]  # Not both server.py and consumer.py
```

**Prevention:**
- Validate MODE at startup; fail fast if invalid
- Log the selected mode: `logger.info(f"Starting in {loaded_config.MODE} mode")`
- Use separate Docker Compose services for each mode (same image, different MODE env var)

---

## Diagnostic Commands Cheat Sheet

```bash
# Database connections
ps aux | grep postgres  # Check active connections
SELECT count(*) FROM pg_stat_activity;  # PostgreSQL active connections

# Kafka
kafka-topics --list --bootstrap-server localhost:9092
kafka-consumer-groups --describe --group <group-id> --bootstrap-server localhost:9092
kafka-console-consumer --topic <topic> --from-beginning --bootstrap-server localhost:9092

# Temporal
temporal workflow list  # List all workflows
temporal workflow describe --workflow-id <id>  # Workflow details

# Logs
docker logs <container> --tail 100 --follow
grep -i "error\|exception" /var/log/app.log

# Code audits
ruff check --select F,E,ASYNC  # Linting + async checks
grep -rn "TODO\|FIXME\|XXX" app/  # Find TODOs
```

---

## Summary

| Issue | Symptom | Quick Fix |
|-------|---------|-----------|
| Session leaks | "Session not bound" | Use `async_scoped_session(scopefunc=current_task)` |
| Blocked event loop | Slow responses | Use async clients or `run_in_executor()` |
| Duplicate routes | "Route already exists" | Remove duplicate `include_router()` calls |
| Hardcoded secrets | Secrets in logs/git | Use environment variables, redact before logging |
| CORS errors | Browser blocks requests | Restrict `allow_origins` to known domains |
| Deprecated hooks | Deprecation warnings | Migrate to `lifespan` context manager |
| Kafka not consuming | No messages processed | Check topic, consumer group, offsets |
| Temporal worker idle | Workflows stuck | Verify task queue matches workflow |
| Partial commits | Inconsistent data | Wrap transactions in try/except with rollback |
| Wrong MODE runs | Server runs when expecting consumer | Validate MODE env var, fail fast on unknown |
