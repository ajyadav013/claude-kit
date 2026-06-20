# Consumer and Producer Patterns

Deep inventory of consumer config map variants, producer config, eventbridge wrapper, and bootstrap loops from production Python/FastAPI services.

## Consumer config map variants

### Pattern A: flat, batch_tasks, async_kafka

**Shape:**
```python
{
    "consumer_id": {
        "service_name": str,
        "deserialization_format": str,  # "JSON"
        "consumer_config": {
            # Auth (SASL_SSL + GSSAPI)
            "security_protocol": "SASL_SSL",
            "sasl_mechanism": "GSSAPI",
            "sasl_kerberos_service_name": "kafka",
            "ssl_context": ssl.SSLContext,
            
            # Brokers and consumer settings
            "bootstrap_servers": str | list[str],
            "group_id": str,
            "enable_auto_commit": False,
            "auto_offset_reset": "earliest" | "latest",
            "session_timeout_ms": int,
            "request_timeout_ms": int,
            "heartbeat_interval_ms": int,
            "api_version": tuple,  # (2, 8, 2)
        },
        "topics_configurations": {
            "topic_name": {
                "batch_tasks": [callable]  # List of async functions taking list of payloads
            }
        },
        "async_kafka": bool,  # True for aiokafka
    }
}
```

**Example (from a production service using batch processing):**
```python
"app_batch_consumer": {
    "service_name": "app_batch_consumer",
    "deserialization_format": KAFKA_SERIALIZATION_FORMAT,
    "consumer_config": {
        **KAFKA_KERBEROS_CONFIG,
        "bootstrap_servers": loaded_config.KAFKA_BROKER_LIST,
        "session_timeout_ms": KAFKA_SESSION_TIMEOUT_IN_MS,
        "auto_offset_reset": KAFKA_OFFSET_RESET_STRATEGY,
        "group_id": "app_consumer_group",
        "enable_auto_commit": False,
        "request_timeout_ms": 40000,
        "heartbeat_interval_ms": 3000,
        "api_version": "2.8.2",
    },
    "topics_configurations": {
        "app-topic": {"batch_tasks": [process_batch]}
    },
    "async_kafka": True,
}
```

**Key features:**
- Flat dict keyed by consumer_id
- `batch_tasks` for batch processing (accumulate messages, call handler once per poll)
- SASL_SSL + GSSAPI auth dict spread into consumer_config
- Manual offset commit (enable_auto_commit: False), commit after batch processing

---

### Pattern B: nested, tasks (per-message), custom_commit_offset "pre"

**Shape:**
```python
{
    SERVICE_NAME: {
        "consumer_id": {
            "service_name": str,
            "deserialization_format": str,
            "consumer_config": {
                # Aiokafka keys (underscore)
                "bootstrap_servers": list[str],
                "session_timeout_ms": int,
                "auto_offset_reset": str,
                "group_id": str,
                "enable_auto_commit": False,
                
                # OR confluent-kafka keys (dot notation)
                "bootstrap.servers": str,
                "session.timeout.ms": int,
                "auto.offset.reset": str,
                "group.id": str,
                "enable.auto.commit": False,
            },
            "topics_configurations": {
                "topic_name": {
                    "tasks": [callable]  # List of async functions taking single payload
                }
            },
            "async_kafka": bool,
            "custom_commit_offset": "pre" | "post",
        }
    }
}
```

**Example (from a production service using per-message processing):**
```python
KAFKA_CONSUMER_CONFIG = {
    SERVICE_NAME: {
        "common_consumer": {
            "service_name": SERVICE_NAME,
            "deserialization_format": KAFKA_SERIALIZATION_FORMAT,
            "consumer_config": COMMON_CONSUMER_CONFIG,  # aiokafka underscore keys
            "topics_configurations": {
                KAFKA_SERVICE_CONFIG_MAPPING[SERVICE_NAME]["common_consumer"]["topics"][0]: {
                    "tasks": [test_consumer]
                }
            },
            "async_kafka": True,
            "custom_commit_offset": "pre",
        },
        "audit_consumer": {
            "service_name": SERVICE_NAME,
            "deserialization_format": KAFKA_SERIALIZATION_FORMAT,
            "consumer_config": CHANGELOG_CONSUMER_CONFIG,  # confluent dot keys
            "topics_configurations": {
                KAFKA_SERVICE_CONFIG_MAPPING[SERVICE_NAME]["db_events"]["topics"][0]: {
                    "tasks": [process_db_changes_message]
                }
            },
            "async_kafka": False,
            "custom_commit_offset": "pre",
        },
    }
}
```

**Key features:**
- Nested dict: SERVICE_NAME -> consumer_id -> config
- `tasks` for per-message processing (handler called once per message)
- `custom_commit_offset: "pre"` to commit offset before processing (at-most-once delivery)
- Mixed aiokafka and confluent-kafka config keys across different consumers (eventbridge supports both)
- `async_kafka: True` for aiokafka consumers, `False` for confluent sync consumers

---

### Pattern C: confluent with default.topic.config

**Shape:**
```python
{
    SERVICE_NAME: {
        CONSUMER_NAME: {
            "service_name": str,
            "deserialization_format": str,
            "consumer_config": {
                "bootstrap.servers": str,
                "session.timeout.ms": int,
                "group.id": str,
                "default.topic.config": {
                    "auto.offset.reset": str
                }
            },
            "topics_configurations": {
                "topic_name": {"tasks": [callable]}
            },
            "custom_commit_offset": "pre",
        }
    }
}
```

**Example (from a production service using confluent-kafka):**
```python
COMMON_CONSUMER_CONFIG = {
    "bootstrap.servers": loaded_config.KAFKA_BROKER_LIST,
    "session.timeout.ms": KAFKA_SESSION_TIMEOUT_IN_MS,
    "default.topic.config": {"auto.offset.reset": KAFKA_OFFSET_RESET_STRATEGY}
}

CONSUMER_CONFIG = {"group.id": "app_data_consumer_group"}
CONSUMER_CONFIG.update(COMMON_CONSUMER_CONFIG)

KAFKA_CONSUMER_CONFIG = {
    SERVICE_NAME: {
        CONSUMER_NAME: {
            "service_name": SERVICE_NAME,
            "deserialization_format": KAFKA_SERIALIZATION_FORMAT,
            "consumer_config": CONSUMER_CONFIG,
            "topics_configurations": {
                CONSUMER_TOPICS[0]: {"tasks": [process_planogram_data]}
            },
            "custom_commit_offset": "pre",
        }
    }
}
```

**Key features:**
- Nested SERVICE_NAME -> CONSUMER_NAME structure
- Confluent-kafka config with `default.topic.config` for offset reset
- `custom_commit_offset: "pre"` for commit-before-processing
- No `async_kafka` key (handled by eventbridge consumer wrapper)

---

## Producer config variants

### Pattern A: idempotent producer (aiokafka)

**File:** `services/kafka/producer/config.py`

```python
KAFKA_COMMON_PRODUCER_CONFIG = {
    "service_name": "myapp",
    "producer_config": {
        "bootstrap_servers": loaded_config.KAFKA_BROKER_LIST,
        "enable_idempotence": True,
        "acks": "all",
    },
}
```

**Key features:**
- `enable_idempotence: True` + `acks: "all"` for exactly-once semantics
- Minimal config (eventbridge adds defaults)

### Pattern B: aiokafka with compression

**File:** `services/kafka/producer/config.py`

```python
AIO_KAFKA_COMMON_PRODUCER_SETTINGS = {
    "service_name": "myapp",
    "producer_config": {
        "bootstrap_servers": BOOTSTRAP_SERVERS,
        "compression_type": "gzip",
        "enable_idempotence": True,
        "acks": "all",
    },
}

IDEMPOTENCE_CONFIG = {
    "enable_idempotence": True,
    "acks": "all",
}
```

**Key features:**
- `compression_type: "gzip"` to reduce network overhead
- Separate `IDEMPOTENCE_CONFIG` for optional idempotent producer variant

### Pattern C: confluent-kafka producer

```python
KAFKA_PRODUCER_CONFIG = {
    "service_name": "service_name",
    "producer_config": {
        "bootstrap.servers": "broker1:9092,broker2:9092",
        "acks": "all",
        "retries": 3,
        "socket.timeout.ms": 30000,
        "enable.idempotence": True,
    },
}
```

**Key features:**
- Dot-notation keys for confluent-kafka
- `retries` and `socket.timeout.ms` for resilience

---

## Eventbridge wrapper patterns

### Pattern A: Singleton AsyncEventBridge with lazy init

**File:** `services/kafka/producer/producer.py`

```python
from eventbridge.emitter import AsyncEventEmitter

class Singleton(type):
    _instances: Dict[type, type] = {}
    
    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]

class AsyncEventBridge(metaclass=Singleton):
    async def get_event_emitter(self):
        if not hasattr(self, "event_emitter") or self.event_emitter is None:
            print("no event_emitter found")
            self.event_emitter = AsyncEventEmitter(AIO_KAFKA_COMMON_PRODUCER_SETTINGS)
        return self.event_emitter

class IdempotentAsyncEventBridge(metaclass=Singleton):
    async def get_event_emitter(self):
        if not hasattr(self, "event_emitter") or self.event_emitter is None:
            aio_kafka_producer_settings = deepcopy(AIO_KAFKA_COMMON_PRODUCER_SETTINGS)
            aio_kafka_producer_settings.get("producer_config", {}).update(IDEMPOTENCE_CONFIG)
            self.event_emitter = AsyncEventEmitter(aio_kafka_producer_settings)
        return self.event_emitter

event_bridge_obj = AsyncEventBridge()
idempotent_event_bridge_obj = IdempotentAsyncEventBridge()

def get_async_event_bridge_obj(idempotence: bool = False):
    return idempotent_event_bridge_obj if idempotence else event_bridge_obj
```

**Usage:**
```python
from services.kafka.producer.producer import get_async_event_bridge_obj

async def publish_event(topic, event):
    bridge = get_async_event_bridge_obj(idempotence=True)
    emitter = await bridge.get_event_emitter()
    await emitter.add_event_to_queue(
        topics=[topic],
        partition_value=event["id"],
        event=event,
        serialization_format="JSON",
    )
    await emitter.emit_events()
```

**Key features:**
- Singleton ensures one producer instance per process
- Lazy initialization in `get_event_emitter()`
- Separate idempotent variant with enhanced config
- Global instances (`event_bridge_obj`, `idempotent_event_bridge_obj`)

---

### Pattern B: simpler wrapper, no Singleton

**File:** `services/kafka/producer/event_bridge.py`

```python
from eventbridge.emitter import AsyncEventEmitter

class AsyncEventBridge:
    def __init__(self, configurations, *args, **kwargs):
        self.event_emitter = AsyncEventEmitter(configurations=configurations)

    async def stop_producer(self):
        if (
            self.event_emitter.kafka_producer
            and self.event_emitter.kafka_producer.producer
        ):
            await self.event_emitter.kafka_producer.stop_producer()
```

**Usage:**
```python
from services.kafka.producer.event_bridge import AsyncEventBridge
from services.kafka.producer.config import KAFKA_PRODUCER_CONFIG

bridge = AsyncEventBridge(KAFKA_PRODUCER_CONFIG)
await bridge.event_emitter.add_event_to_queue(...)
await bridge.event_emitter.emit_events()
await bridge.stop_producer()  # Explicit shutdown
```

**Key features:**
- No Singleton (caller manages instance lifecycle)
- Init-time AsyncEventEmitter creation
- Explicit `stop_producer()` for graceful shutdown

---

## Consumer bootstrap patterns

### Pattern A: sync kafka-python with manual poll/commit

**File:** `services/kafka/consumer/consumer.py`

```python
from kafka import KafkaConsumer as SyncKafkaConsumer
from kafka.errors import CommitFailedError

def _run_kafka_consumer(loop: asyncio.AbstractEventLoop, consumer_state: dict) -> None:
    consumer_name = loaded_config.CONSUMER_NAME
    config = get_consumer_config()[consumer_name]
    consumer_cfg = config["consumer_config"]
    topics_config = config["topics_configurations"]
    topics = list(topics_config.keys())

    brokers = consumer_cfg["bootstrap_servers"]
    if isinstance(brokers, str):
        brokers = [b.strip() for b in brokers.split(",")]

    consumer = SyncKafkaConsumer(
        bootstrap_servers=brokers,
        security_protocol=consumer_cfg["security_protocol"],
        sasl_mechanism=consumer_cfg["sasl_mechanism"],
        sasl_kerberos_service_name=consumer_cfg["sasl_kerberos_service_name"],
        ssl_context=consumer_cfg["ssl_context"],
        group_id=consumer_cfg["group_id"],
        auto_offset_reset=consumer_cfg["auto_offset_reset"],
        enable_auto_commit=False,
        request_timeout_ms=consumer_cfg["request_timeout_ms"],
        max_poll_records=100,
        key_deserializer=lambda k: k.decode("utf-8") if k else None,
        value_deserializer=lambda v: v.decode("utf-8") if v else None,
    )

    consumer.subscribe(topics)
    print(f"[consumer] Subscribed to {topics}", flush=True)

    try:
        while True:
            records = consumer.poll(timeout_ms=5000)
            consumer_state["last_activity"] = time.time()

            if not records:
                continue

            # Accumulate batch payloads
            batch_payloads = {}
            for tp, messages in records.items():
                for msg in messages:
                    payload = {
                        "topic": msg.topic,
                        "partition": msg.partition,
                        "offset": msg.offset,
                        "key": msg.key,
                        "value": json.loads(msg.value) if msg.value else None,
                    }
                    
                    if topics_config.get(msg.topic, {}).get("batch_tasks"):
                        batch_payloads.setdefault(msg.topic, []).append(payload)

            # Execute batch handlers
            upload_coros = []
            for topic, payloads in batch_payloads.items():
                for task_fn in topics_config[topic]["batch_tasks"]:
                    upload_coros.append(task_fn(payloads))

            if upload_coros:
                async def _upload_batch(coros):
                    return await asyncio.gather(*coros)

                future = asyncio.run_coroutine_threadsafe(
                    _upload_batch(upload_coros), loop
                )
                future.result()

            # Manual commit after successful processing
            try:
                consumer.commit()
            except CommitFailedError:
                print("[consumer] CommitFailedError — partition reassigned", flush=True)
    finally:
        consumer.close()


async def main() -> NoReturn:
    if loaded_config.KERBEROS_AUTH_ENABLED:
        _setup_kerberos_auth()

    loop = asyncio.get_running_loop()
    consumer_state = {}

    await asyncio.gather(
        asyncio.to_thread(_run_kafka_consumer, loop, consumer_state),
        _healthz(consumer_state),
        _readyz(),
    )
```

**Key features:**
- Sync `kafka.KafkaConsumer` running in a thread via `asyncio.to_thread`
- Manual poll loop with batch accumulation
- Async handlers scheduled on main loop via `run_coroutine_threadsafe`
- Manual `commit()` after successful batch processing
- `CommitFailedError` handling (partition reassignment, log and continue)
- Health checks (`_healthz`, `_readyz`) run concurrently

---

### Pattern B: eventbridge-delegated async consumer

**File:** `services/kafka/consumer/consumer.py`

```python
from eventbridge.consumer import setup_and_start_consumer
from eventbridge.health import _healthz, _readyz
from services.kafka.consumer.config import KAFKA_CONSUMER_SETTINGS

async def main():
    consumer_name = CONSUMER_NAME
    settings = KAFKA_CONSUMER_SETTINGS[SERVICE_NAME][consumer_name]
    
    await asyncio.gather(
        setup_and_start_consumer(settings),
        _healthz(),
        _readyz(),
    )

if __name__ == "__main__":
    asyncio.run(main())
```

**Key features:**
- Delegate to `eventbridge.consumer.setup_and_start_consumer(settings)` which handles:
  - Consumer instantiation (aiokafka or confluent-kafka based on `async_kafka` flag)
  - Topic subscription
  - Poll/dispatch/commit loop
  - Deserialization (based on `deserialization_format`)
  - Offset commit (based on `custom_commit_offset`: "pre" or "post")
- Health checks run concurrently
- No manual poll loop in application code

---

## AsyncEventEmitter API (eventbridge library)

### Queue and emit pattern

```python
# Add events to internal queue
await emitter.add_event_to_queue(
    topics=["my-topic"],
    partition_value="partition-key",
    event={"field": "value"},
    event_meta={"meta_field": "meta_value"},  # Optional metadata
    serialization_format="JSON",  # or "AVRO", "MSGPACK"
    hash_flag=True,  # Hash partition_value for partition assignment
    callback=async_callback_fn,  # Optional callback after emit
    headers={"header_key": "header_value"},  # Optional headers
)

# Flush all queued events to Kafka
await emitter.emit_events()
```

### Single emit pattern

```python
# Emit single event (bypasses queue, immediate send)
await emitter.emit(
    topics=["my-topic"],
    partition_value="partition-key",
    event={"field": "value"},
    serialization_format="JSON",
)
```

**Key features:**
- `add_event_to_queue()` for batching (collect multiple events, flush once)
- `emit_events()` to flush all queued events
- `emit()` for immediate single-event send
- Partition assignment via hash of `partition_value` if `hash_flag=True`
- Optional callbacks executed after successful emit

---

## Summary comparison

| Feature | Pattern A | Pattern B | Pattern C |
|---------|----------|------------|----------|
| Config nesting | Flat (consumer_id -> config) | Nested (SERVICE_NAME -> consumer_id -> config) | Nested (SERVICE_NAME -> CONSUMER_NAME -> config) |
| Task mode | `batch_tasks` (batch processing) | `tasks` (per-message) | `tasks` (per-message) |
| Kafka client | kafka-python (sync) | aiokafka/confluent (mixed) | confluent-kafka |
| Config keys | Underscore (aiokafka) | Mixed underscore + dot | Dot (confluent) |
| Offset commit | Manual after batch | `custom_commit_offset: "pre"` | `custom_commit_offset: "pre"` |
| Auth | SASL_SSL + GSSAPI (Kerberos) | (not shown, assumed SASL_PLAIN or none) | (not shown) |
| Consumer bootstrap | Manual poll loop in thread | eventbridge `setup_and_start_consumer` | eventbridge `setup_and_start_consumer` |
| Producer wrapper | (not shown) | Singleton AsyncEventBridge | Simple AsyncEventBridge |
| Idempotence | Producer config | Producer + IdempotentAsyncEventBridge | (not shown) |
