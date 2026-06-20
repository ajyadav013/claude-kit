# Example Patterns

Representative code patterns from production Python/FastAPI services that ground this skill.

## Service A: Sync consumer with batch processing and Kerberos

### Consumer config map (flat, batch_tasks, SASL_SSL+GSSAPI)

**File:** `services/kafka/consumer/config.py`

```python
def _build_consumer_config() -> Dict[str, Dict[str, any]]:
    # Build SSL context for SASL_SSL + GSSAPI
    ssl_context = ssl.create_default_context(cafile=KAFKA_SSL_CA_FILE)
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    ssl_context.load_cert_chain(certfile=KAFKA_SSL_CERT_FILE, keyfile=KAFKA_SSL_KEY_FILE)

    KAFKA_KERBEROS_CONFIG = {
        "security_protocol": "SASL_SSL",
        "sasl_mechanism": "GSSAPI",
        "sasl_kerberos_service_name": "kafka",
        "ssl_context": ssl_context,
    }

    return {
        "app_consumer": {
            "service_name": "app_consumer",
            "deserialization_format": KAFKA_SERIALIZATION_FORMAT,
            "consumer_config": {**KAFKA_KERBEROS_CONFIG,
                "bootstrap_servers": loaded_config.KAFKA_BROKER_LIST,
                "group_id": "app_consumer_group",
                "enable_auto_commit": False,
                # ... timeouts and api_version
            },
            "topics_configurations": {
                "app-topic": {"batch_tasks": [process_batch]}
            },
            "async_kafka": True,
        },
        # ... more consumers
    }
```

**What to copy:** SSL context setup with SASL_GSSAPI, flat consumer config dict, `batch_tasks` for batch processing, `enable_auto_commit: False`.

### Consumer bootstrap (sync, manual commit)

**File:** `services/kafka/consumer/consumer.py`

```python
def _run_kafka_consumer(loop: asyncio.AbstractEventLoop, consumer_state: dict) -> None:
    consumer_name = loaded_config.CONSUMER_NAME
    config = get_consumer_config()[consumer_name]
    consumer_cfg = config["consumer_config"]
    topics_config = config["topics_configurations"]
    topics = list(topics_config.keys())

    consumer = SyncKafkaConsumer(
        bootstrap_servers=brokers,
        security_protocol=consumer_cfg["security_protocol"],
        sasl_mechanism=consumer_cfg["sasl_mechanism"],
        sasl_kerberos_service_name=consumer_cfg["sasl_kerberos_service_name"],
        ssl_context=consumer_cfg["ssl_context"],
        group_id=consumer_cfg["group_id"],
        enable_auto_commit=False,
        max_poll_records=100,
        # ... deserializers
    )

    consumer.subscribe(topics)
    
    while True:
        records = consumer.poll(timeout_ms=5000)
        # ... accumulate batch_payloads
        for topic, payloads in batch_payloads.items():
            for task_fn in topics_config[topic]["batch_tasks"]:
                upload_coros.append(task_fn(payloads))
        
        # Execute handlers
        future = asyncio.run_coroutine_threadsafe(_upload_batch(upload_coros), loop)
        future.result()
        
        # Commit after successful processing
        consumer.commit()
```

**What to copy:** Sync kafka-python consumer with manual poll/commit, batch accumulation, asyncio bridge to run async handlers.

### Kerberos setup (entrypoint certificate writing, kinit)

**File:** `entrypoint.py`

```python
def _write_kafka_certificates() -> None:
    CERT_DIR.mkdir(parents=True, exist_ok=True)
    
    # Restore PEM files from env vars (space-separated -> newline-separated)
    pem_files = {
        "server.pem": loaded_config.KAFKA_CERTIFICATES_SERVER_PEM,
        "ca-certificate.pem": loaded_config.KAFKA_CERTIFICATES_CA_CERTIFICATE_PEM,
        "ca-certificate.key": loaded_config.KAFKA_CERTIFICATES_CA_CERTIFICATE_KEY,
    }
    for filename, content in pem_files.items():
        path = CERT_DIR / filename
        path.write_text(_restore_pem(content))
        os.chmod(path, 0o600)
    
    # Keytab — base64-decode from env
    keytab_path = CERT_DIR / "app.keytab"
    keytab_path.write_bytes(base64.b64decode(loaded_config.KAFKA_CERTIFICATES_KEYTAB))
    os.chmod(keytab_path, 0o600)
```

**File:** `services/kafka/consumer/consumer.py`

```python
def _setup_kerberos_auth() -> None:
    # Rewrite krb5.conf: strip includedir, inject KDC hosts, switch ccache KEYRING -> FILE
    with open(krb5_conf_src, "r", encoding="utf-8") as fp:
        content = fp.read()
    
    fixed_lines = []
    for line in content.splitlines():
        if line.strip().startswith("includedir"):
            continue
        fixed_lines.append(line.replace("KEYRING:persistent:%{uid}", "FILE:/tmp/krb5cc_%{uid}"))
    
    # Inject KDC hosts
    kdc_hosts = loaded_config.KAFKA_KDC_HOSTS.split(",")
    # ... (insert kdc lines into realm section)
    
    with open(krb5_conf_fixed, "w", encoding="utf-8") as fp:
        fp.write("\n".join(final_lines) + "\n")
    
    os.environ["KRB5_CONFIG"] = str(krb5_conf_fixed)
    
    # Acquire Kerberos ticket
    result = subprocess.run(
        ["kinit", "-kt", str(keytab_path), kerberos_principal],
        capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise RuntimeError("Kerberos authentication failed via kinit")
```

**What to copy:** Entrypoint writes certs/keytab from env with chmod 0o600; consumer rewrites krb5.conf and runs kinit before starting.

### Producer config

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

**What to copy:** Idempotent producer with acks=all for exactly-once semantics.

---

## Service B: Async consumer with eventbridge

### Consumer config map (nested, mixed aiokafka/confluent keys)

**File:** `services/kafka/consumer/config.py`

```python
COMMON_CONSUMER_CONFIG = {
    "bootstrap_servers": BOOTSTRAP_SERVERS,  # aiokafka underscore keys
    "session_timeout_ms": KAFKA_SESSION_TIMEOUT_IN_MS,
    "auto_offset_reset": KAFKA_OFFSET_RESET_STRATEGY,
    "group_id": COMMON_GROUP_ID,
    "enable_auto_commit": False,
}

SYNC_CONSUMER_CONFIG = {
    "bootstrap.servers": SYNC_BOOTSTRAP_SERVERS,  # confluent dot keys
    "session.timeout.ms": KAFKA_SESSION_TIMEOUT_IN_MS,
    "auto.offset.reset": KAFKA_OFFSET_RESET_STRATEGY,
    "group.id": COMMON_GROUP_ID,
    "enable.auto.commit": False,
}

KAFKA_CONSUMER_CONFIG = {
    SERVICE_NAME: {
        "common_consumer": {
            "service_name": SERVICE_NAME,
            "deserialization_format": KAFKA_SERIALIZATION_FORMAT,
            "consumer_config": COMMON_CONSUMER_CONFIG,
            "topics_configurations": {
                KAFKA_SERVICE_CONFIG_MAPPING[SERVICE_NAME]["common_consumer"]["topics"][0]: {
                    "tasks": [test_consumer]
                }
            },
            "async_kafka": True,
            "custom_commit_offset": "pre",
        },
        "mapping_consumer": {
            # ... (nested structure, confluent config, custom_commit_offset "pre")
            "consumer_config": MAPPING_CONSUMER_CONFIG,
            "topics_configurations": {
                # ... topics map to tasks
            },
            "async_kafka": False,
            "custom_commit_offset": "pre",
        },
        # ... more consumers
    }
}
```

**What to copy:** Nested SERVICE_NAME -> consumer_id structure, mixed aiokafka/confluent config keys, `custom_commit_offset: "pre"` for commit-before-processing.

### Service config mapping (topics per consumer)

**File:** `services/kafka/config.py`

```python
KAFKA_SERVICE_CONFIG_MAPPING = {
    SERVICE_NAME: {
        "common_consumer": {
            "topics": ["test_topic"],
            "group_id": COMMON_GROUP_ID,
        },
        "mapping_event": {
            "topics": ONBOARDING_TOPIC,
            "group_id": COMMON_GROUP_ID,
        },
        # ... more consumer topic mappings
    },
    NOTIFICATION_SERVICE: {
        "email_notifications": {
            "topics": ["notification-email-high"],
            "group_id": COMMON_GROUP_ID,
        },
    },
}
```

**What to copy:** Separate config mapping for topics/group_id per consumer; referenced in consumer config.

### Eventbridge wrapper (Singleton AsyncEventBridge)

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
            self.event_emitter = AsyncEventEmitter(AIO_KAFKA_COMMON_PRODUCER_SETTINGS)
        return self.event_emitter

event_bridge_obj = AsyncEventBridge()
```

**What to copy:** Singleton wrapper around AsyncEventEmitter, lazy initialization in get_event_emitter.

---

## Service C: Confluent-kafka consumer

### Consumer config map (confluent, default.topic.config)

**File:** `services/kafka/consumer/config.py`

```python
COMMON_CONSUMER_CONFIG = {
    "bootstrap.servers": loaded_config.KAFKA_BROKER_LIST,
    "session.timeout.ms": KAFKA_SESSION_TIMEOUT_IN_MS,
    "default.topic.config": {"auto.offset.reset": KAFKA_OFFSET_RESET_STRATEGY}
}

CONSUMER_CONFIG = {
    "group.id": "app_data_consumer_group"
}
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

**What to copy:** Confluent-kafka config with `default.topic.config` for offset reset, `custom_commit_offset: "pre"`.

### Eventbridge wrapper (simpler, no Singleton)

**File:** `services/kafka/producer/event_bridge.py`

```python
from eventbridge.emitter import AsyncEventEmitter

class AsyncEventBridge:
    def __init__(self, configurations, *args, **kwargs):
        self.event_emitter = AsyncEventEmitter(configurations=configurations)

    async def stop_producer(self):
        if (self.event_emitter.kafka_producer and 
            self.event_emitter.kafka_producer.producer):
            await self.event_emitter.kafka_producer.stop_producer()
```

**What to copy:** Simpler wrapper (no Singleton), init-time AsyncEventEmitter creation, explicit stop_producer.

---

## Common patterns across services

### Config flow
1. `config/docker_config.py` (loaded_config) → environment/docker-compose config
2. `services/kafka/constants.py` → offset reset, session timeout, topic names, serialization format
3. `services/kafka/consumer/config.py` → consumer config map (get_consumer_config)
4. `services/kafka/consumer/consumer.py` → bootstrap consumer from config[CONSUMER_NAME]

### Manual offset commit
- `enable_auto_commit: False` (aiokafka) or `enable.auto.commit: False` (confluent)
- Manual `consumer.commit()` after handlers succeed (sync consumer pattern)
- `custom_commit_offset: "pre"` to commit before processing (async eventbridge pattern)

### No retry/DLQ at consumer layer
- Application handlers are responsible for retries and dead-letter logic
- Consumer layer only handles poll/dispatch/commit cycle
