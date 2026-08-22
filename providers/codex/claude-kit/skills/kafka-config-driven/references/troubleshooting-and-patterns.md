# Troubleshooting and Common Patterns

Additional patterns, troubleshooting tips, and best practices derived from production Python/FastAPI Kafka implementations.

## Common issues and solutions

### 1. CommitFailedError during processing

**Symptom:**
```
kafka.errors.CommitFailedError: Commit cannot be completed since the group has already rebalanced and assigned the partitions to another member
```

**Root cause:** Partition was reassigned to another consumer in the group while processing was ongoing.

**Solution:**
```python
try:
    consumer.commit()
except CommitFailedError:
    logger.warning("[consumer] CommitFailedError — partition reassigned, messages will be reprocessed")
    # Continue processing — rebalanced partition will be handled by the new owner
```

**Prevention:**
- Keep processing time under `max_poll_interval_ms` (default: 300000 = 5 minutes)
- Increase `max_poll_interval_ms` if batch processing takes longer
- Reduce `max_poll_records` to process smaller batches

---

### 2. Kerberos ticket expiration

**Symptom:**
```
[Errno -1765328377] Ticket expired
```

**Root cause:** Kerberos ticket acquired via `kinit` has expired (typically TTL is 10-24 hours).

**Common pattern:** Run `kinit` once at startup; consumer fails after TTL expires.

**Solutions:**

**Option 1: Periodic ticket renewal (background thread)**
```python
import threading
import subprocess
import time

def _renew_kerberos_ticket_periodically(keytab_path, principal, interval_seconds=3600):
    """Renew Kerberos ticket every hour in a background thread."""
    while True:
        time.sleep(interval_seconds)
        result = subprocess.run(
            ["kinit", "-R"],  # Renew existing ticket
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            # Renewal failed (ticket non-renewable?), acquire fresh ticket
            subprocess.run(
                ["kinit", "-kt", str(keytab_path), principal],
                check=True,
            )
        logger.info("[kerberos] Ticket renewed")

# Start renewal thread at consumer startup
renewal_thread = threading.Thread(
    target=_renew_kerberos_ticket_periodically,
    args=(keytab_path, principal, 3600),
    daemon=True,
)
renewal_thread.start()
```

**Option 2: Increase ticket TTL via KDC policy**
- Configure KDC to issue longer-lived tickets (requires KDC admin access)

**Option 3: Restart consumer before TTL expires**
- Use container orchestrator (Kubernetes CronJob, systemd timer) to restart consumer every 8-10 hours

---

### 3. SSL certificate verification failures

**Symptom:**
```
ssl.SSLError: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed
```

**Root cause:** Broker certificate doesn't match hostname or CA is not trusted.

**Insecure pattern (some services):**
```python
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE
```

**Security risk:** Allows man-in-the-middle attacks.

**Better solutions:**

**Option 1: Add internal CA to system trust store**
```bash
# Copy CA cert to system trust store
sudo cp ca-certificate.pem /usr/local/share/ca-certificates/kafka-ca.crt
sudo update-ca-certificates
```
```python
# Enable verification
ssl_context = ssl.create_default_context()
ssl_context.load_cert_chain(certfile=CERT_PEM, keyfile=KEY_FILE)
# Don't disable check_hostname or verify_mode
```

**Option 2: Use proper broker certificates with correct SANs**
- Issue broker certificates with correct `subjectAltName` entries matching broker hostnames
- Enable `check_hostname = True` and `verify_mode = ssl.CERT_REQUIRED`

**Option 3: Specify CA explicitly for verification**
```python
ssl_context = ssl.create_default_context(cafile=CA_PEM)
ssl_context.verify_mode = ssl.CERT_REQUIRED
ssl_context.check_hostname = True
ssl_context.load_cert_chain(certfile=CERT_PEM, keyfile=KEY_FILE)
```

---

### 4. Consumer group rebalance storms

**Symptom:** Frequent rebalances causing duplicate message processing or consumer lag.

**Root causes:**
- `session_timeout_ms` too short (consumer considered dead before it can heartbeat)
- `heartbeat_interval_ms` too long relative to `session_timeout_ms`
- Long processing time exceeding `max_poll_interval_ms`

**Solution:**
```python
# Production-tested defaults
consumer_config = {
    "session_timeout_ms": 30000,  # 30 seconds
    "heartbeat_interval_ms": 3000,  # 3 seconds (should be < session_timeout_ms / 3)
    "max_poll_interval_ms": 300000,  # 5 minutes (must be > processing time per batch)
    "max_poll_records": 100,  # Limit batch size to keep processing time predictable
}
```

**Tuning guidelines:**
- `heartbeat_interval_ms` should be < `session_timeout_ms / 3`
- `session_timeout_ms` should be > network round-trip time × 3
- `max_poll_interval_ms` should be > 95th percentile batch processing time
- Monitor rebalance frequency via consumer metrics

---

### 5. Message deserialization errors

**Symptom:**
```
json.JSONDecodeError: Expecting value: line 1 column 1 (char 0)
```

**Root cause:** Message value is not valid JSON (or wrong serialization format assumed).

**Solution (graceful degradation):**
```python
def safe_deserialize(value: bytes, format: str = "JSON") -> dict | None:
    """Safely deserialize Kafka message with error handling."""
    if not value:
        return None
    
    try:
        if format == "JSON":
            return json.loads(value)
        elif format == "MSGPACK":
            return msgpack.unpackb(value)
        else:
            logger.error(f"Unknown deserialization format: {format}")
            return None
    except Exception as e:
        logger.error(
            "kafka.deserialization_error",
            error=str(e),
            value_preview=value[:100].decode("utf-8", errors="replace"),
        )
        return None
```

**Prevention:**
- Enforce schema validation on producer side
- Use Avro/Protobuf with schema registry for strict typing
- Add message format version to headers

---

## Pattern variations across repos

### Consumer bootstrap: sync vs async

**Pattern A (sync kafka-python in thread):**
```python
# Sync consumer in thread + asyncio bridge for handlers
def _run_kafka_consumer(loop, consumer_state):
    consumer = SyncKafkaConsumer(...)
    while True:
        records = consumer.poll(timeout_ms=5000)
        # ... accumulate batch
        future = asyncio.run_coroutine_threadsafe(
            _upload_batch(upload_coros), loop
        )
        future.result()
        consumer.commit()

async def main():
    await asyncio.gather(
        asyncio.to_thread(_run_kafka_consumer, loop, consumer_state),
        _healthz(consumer_state),
    )
```

**Pattern B (eventbridge-delegated async):**
```python
# Eventbridge handles consumer lifecycle
from eventbridge.consumer import setup_and_start_consumer

async def main():
    config = get_consumer_config()[consumer_name]
    await setup_and_start_consumer(config)
```

**When to use which:**
- **Sync pattern**: Fine-grained control over poll/commit, custom batching logic, no eventbridge dependency
- **Async pattern**: Simpler code, eventbridge handles lifecycle, built-in health checks

---

### Offset commit strategies

**At-least-once (commit after processing):**
```python
# Sync consumer pattern
while True:
    records = consumer.poll(timeout_ms=5000)
    # Process batch
    for topic, payloads in batch_payloads.items():
        for task_fn in topics_config[topic]["batch_tasks"]:
            await task_fn(payloads)
    # Commit after successful processing
    consumer.commit()
```

**At-most-once (commit before processing):**
```python
# Async eventbridge pattern
{
    "custom_commit_offset": "pre"
}
# Eventbridge commits offset BEFORE calling handler
```

**Trade-offs:**
- **At-least-once**: Message may be reprocessed on failure (need idempotent handlers)
- **At-most-once**: Message may be lost on failure (acceptable for non-critical events)

**Recommendation:** Use at-least-once with idempotent handlers for critical data pipelines.

---

### Producer idempotence patterns

**Basic idempotence:**
```python
KAFKA_COMMON_PRODUCER_CONFIG = {
    "producer_config": {
        "enable_idempotence": True,
        "acks": "all",
    },
}
```

**Conditional idempotence (some services):**
```python
# Default producer (non-idempotent, faster)
event_bridge_obj = AsyncEventBridge()

# Idempotent producer (slower, stronger guarantees)
idempotent_event_bridge_obj = IdempotentAsyncEventBridge()

def get_async_event_bridge_obj(idempotence: bool = False):
    return idempotent_event_bridge_obj if idempotence else event_bridge_obj

# Usage
bridge = get_async_event_bridge_obj(idempotence=True)
```

**When to use idempotence:**
- Critical events (payments, inventory updates, user state changes)
- Events where duplicate processing causes data corruption
- Acceptable trade-off: ~20-30% lower throughput for guaranteed exactly-once

---

## Health check patterns

### Pattern A: liveness via last activity timestamp

```python
consumer_state = {"last_activity": time.time()}

async def _healthz(consumer_state):
    """Health check: consumer is alive if poll activity within last 60s."""
    app = aiohttp.web.Application()
    app.router.add_get("/healthz", lambda req: _health_handler(consumer_state))
    runner = aiohttp.web.AppRunner(app)
    await runner.setup()
    site = aiohttp.web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()
    while True:
        await asyncio.sleep(3600)  # Keep alive

def _health_handler(consumer_state):
    last_activity = consumer_state.get("last_activity", 0)
    if time.time() - last_activity > 60:
        return aiohttp.web.Response(status=503, text="Consumer stalled")
    return aiohttp.web.Response(status=200, text="OK")
```

### Eventbridge: readyz endpoint

```python
from eventbridge.health import _healthz, _readyz

async def main():
    await asyncio.gather(
        setup_and_start_consumer(config),
        _healthz(),  # Liveness probe
        _readyz(),   # Readiness probe
    )
```

**Best practice:** Expose both liveness and readiness probes for Kubernetes deployments.

---

## Config organization best practices

### 1. Layer config hierarchy

```
docker-compose.yml / k8s manifest
        ↓ (environment variables)
config/docker_config.py (loaded_config)
        ↓ (global settings)
services/kafka/constants.py
        ↓ (topic names, timeouts, serialization format)
services/kafka/consumer/config.py (consumer map)
services/kafka/producer/config.py (producer settings)
        ↓ (runtime)
services/kafka/consumer/consumer.py (bootstrap)
```

**Benefit:** Easy to override settings per environment (dev/staging/prod) without code changes.

### 2. Separate service-specific config

```python
# services/kafka/config.py — topic mappings per service
KAFKA_SERVICE_CONFIG_MAPPING = {
    SERVICE_NAME: {
        "common_consumer": {
            "topics": ["test_topic"],
            "group_id": COMMON_GROUP_ID,
        },
        "audit_consumer": {
            "topics": ["audit_log"],
            "group_id": AUDIT_GROUP_ID,
        },
    },
    NOTIFICATION_SERVICE: {
        "email_notifications": {
            "topics": ["notification-email-high"],
            "group_id": NOTIFICATION_GROUP_ID,
        },
    },
}
```

**Benefit:** Multi-service repos can define different consumers per service in one place.

### 3. Use environment-based consumer selection

```python
# consumer.py
consumer_name = os.getenv("CONSUMER_NAME", "default_consumer")
config = get_consumer_config()[consumer_name]
```

**Benefit:** Run different consumers in different containers/pods from the same image.

---

## Testing strategies

### Unit testing consumer handlers

```python
# Test handler in isolation (no Kafka)
async def test_process_message():
    payload = {
        "topic": "test-topic",
        "partition": 0,
        "offset": 123,
        "value": {"user_id": "123", "action": "login"},
    }
    await process_message(payload)
    # Assert side effects (DB writes, API calls, etc.)
```

### Integration testing with testcontainers

```python
import pytest
from testcontainers.kafka import KafkaContainer

@pytest.fixture(scope="module")
def kafka_broker():
    with KafkaContainer() as kafka:
        yield kafka.get_bootstrap_server()

async def test_consumer_integration(kafka_broker):
    # Start consumer pointing at test broker
    config = get_consumer_config()["test_consumer"]
    config["consumer_config"]["bootstrap_servers"] = kafka_broker
    # Produce test message, assert consumer processes it
```

### Manual testing with kcat (kafkacat)

```bash
# Produce test message
echo '{"user_id": "123", "action": "login"}' | \
  kcat -P -b localhost:9092 -t test-topic

# Consume and verify
kcat -C -b localhost:9092 -t test-topic -o beginning
```

---

## Performance tuning

### Producer batching

```python
# Increase batch size for higher throughput
producer_config = {
    "linger_ms": 100,  # Wait up to 100ms to batch messages
    "batch_size": 32768,  # 32KB batches
    "compression_type": "gzip",  # Compress batches
}
```

### Consumer throughput

```python
# Process larger batches per poll
consumer_config = {
    "max_poll_records": 500,  # Up from default 100
    "fetch_min_bytes": 1024,  # Wait for at least 1KB before returning
    "fetch_max_wait_ms": 500,  # But don't wait more than 500ms
}
```

**Trade-off:** Larger batches = higher throughput but higher latency and memory usage.

---

## Monitoring and observability

### Metrics to track

**Consumer metrics:**
- `kafka.consumer.lag` — how far behind the consumer is
- `kafka.consumer.records_consumed_rate` — throughput
- `kafka.consumer.commit_rate` — offset commit frequency
- `kafka.consumer.rebalance_rate` — rebalance frequency (should be low)

**Producer metrics:**
- `kafka.producer.record_send_rate` — throughput
- `kafka.producer.batch_size_avg` — batching efficiency
- `kafka.producer.compression_rate_avg` — compression efficiency
- `kafka.producer.record_error_rate` — failed sends

**Example (using structlog for events):**
```python
import structlog

logger = structlog.get_logger(__name__)

# In consumer loop
logger.info(
    "kafka.consumer.batch_processed",
    topic=topic,
    batch_size=len(payloads),
    processing_time_ms=elapsed_ms,
    lag=consumer.lag(),
)
```

### Distributed tracing

```python
# Propagate trace context via Kafka headers
import opentelemetry.trace as trace

tracer = trace.get_tracer(__name__)

# Producer
with tracer.start_as_current_span("kafka.produce") as span:
    headers = {"traceparent": span.get_span_context().trace_id}
    await emitter.emit(topics=["my-topic"], headers=headers, ...)

# Consumer
def _handle_message(message):
    trace_id = message.headers.get("traceparent")
    with tracer.start_as_current_span("kafka.consume", trace_id=trace_id):
        # ... process message
```

---

## Security hardening beyond the basics

### 1. Secrets management

**Current pattern:** Certificates/keytabs in environment variables (base64-encoded).

**Better alternatives:**

**Kubernetes Secrets (mounted as files):**
```yaml
# deployment.yaml
volumes:
  - name: kafka-certs
    secret:
      secretName: kafka-certificates
      defaultMode: 0400  # read-only

volumeMounts:
  - name: kafka-certs
    mountPath: /etc/kafka/certs
    readOnly: true
```
```python
# No need to write files from env — read directly
ssl_context.load_cert_chain(
    certfile="/etc/kafka/certs/client.pem",
    keyfile="/etc/kafka/certs/client.key"
)
```

**HashiCorp Vault integration:**
```python
import hvac

client = hvac.Client(url=VAULT_URL, token=VAULT_TOKEN)
secret = client.secrets.kv.v2.read_secret_version(path="kafka/certs")
cert_data = secret["data"]["data"]["client_pem"]
```

### 2. Certificate rotation

**Pattern: Reload certs without downtime**
```python
import signal

def reload_ssl_context(signum, frame):
    """Reload SSL context on SIGHUP signal."""
    global ssl_context
    ssl_context = ssl.create_default_context(cafile=CA_PEM)
    ssl_context.load_cert_chain(certfile=CERT_PEM, keyfile=KEY_FILE)
    logger.info("[consumer] SSL context reloaded")

signal.signal(signal.SIGHUP, reload_ssl_context)
```

### 3. Audit logging for Kafka access

```python
logger.info(
    "kafka.consumer.started",
    consumer_id=consumer_name,
    group_id=group_id,
    topics=topics,
    user=os.getenv("USER"),
    hostname=socket.gethostname(),
)
```

---

## Migration patterns

### Migrating from sync to async consumer

**Before (sync kafka-python):**
```python
from kafka import KafkaConsumer

consumer = KafkaConsumer(...)
for message in consumer:
    process_message(message.value)
```

**After (eventbridge async):**
```python
from eventbridge.consumer import setup_and_start_consumer

async def process_message(payload):
    # ... existing logic (now async)

config = {
    "consumer_config": {...},
    "topics_configurations": {
        "my-topic": {"tasks": [process_message]}
    },
}
await setup_and_start_consumer(config)
```

**Migration checklist:**
1. Convert handler functions to async
2. Build eventbridge config map from existing consumer settings
3. Install eventbridge library dependency
4. Test in staging with same consumer group (will rebalance with old consumers)
5. Deploy async version, scale down sync version

---

## References to other files

- [Repo Evidence](repo-evidence.md) — File paths and snippets from source repos
- [Consumer and Producer Patterns](consumer-producer-patterns.md) — Deep inventory of config shapes and bootstrap patterns
- [Config and SASL Kerberos](config-and-sasl-kerberos.md) — Full SASL_SSL+GSSAPI wiring with certificate management
