---
name: kafka-config-driven
description: Config-driven Kafka consumer/producer implementation patterns from production Python/FastAPI services. Covers consumer config maps with topic-to-handler routing, producer config with idempotence guarantees, eventbridge wrapper library (AsyncEventEmitter), and SASL_SSL+GSSAPI Kerberos authentication. Use when implementing Kafka consumers with batch or per-message processing, setting up Kafka producers with exactly-once semantics, organizing Kafka code under services/kafka/ directory structure, configuring SASL_SSL Kerberos authentication with keytabs and certificates, or integrating with an eventbridge library for Kafka abstraction.
---

# kafka-config-driven

Config-driven Kafka consumer and producer implementation patterns derived from production Python/FastAPI services.

## When to use

- Implementing Kafka consumers with topic-to-handler routing
- Setting up Kafka producers with idempotence guarantees
- Configuring SASL_SSL + GSSAPI Kerberos authentication for Kafka
- Organizing Kafka code under `services/kafka/` with consumer/producer split
- Using eventbridge wrapper library for producer abstraction
- Setting up certificate-based Kafka authentication with keytabs

## Core conventions

### Directory structure
- Organize Kafka code under `services/kafka/` with `consumer/` and `producer/` subdirectories.
- Place consumer config maps in `services/kafka/consumer/config.py` and producer config in `services/kafka/producer/config.py`.
- Store Kafka constants (topic names, offset reset strategy, session timeout, serialization format) in `services/kafka/constants.py`.

### Consumer config map shape
- Define a Python dict mapping consumer IDs or service names to their configuration, including `service_name`, `deserialization_format`, `consumer_config`, `topics_configurations`, optional `async_kafka`, and optional `custom_commit_offset`.
- Structure `topics_configurations` as `{ topic_name: { "tasks": [handler_fn] } }` for per-message processing or `{ topic_name: { "batch_tasks": [handler_fn] } }` for batch processing.
- Set `enable_auto_commit: False` in `consumer_config` for manual offset management.
- Use `custom_commit_offset: "pre"` to commit before processing (at-most-once) or omit/set `"post"` for after-processing commit (at-least-once).
- Support both aiokafka (underscore keys like `bootstrap_servers`) and confluent-kafka (dot keys like `bootstrap.servers`) config styles.

### Producer config shape
- Define `KAFKA_COMMON_PRODUCER_CONFIG` with `service_name` and `producer_config` containing `bootstrap_servers`, `enable_idempotence: True`, and `acks: "all"` for exactly-once semantics.
- For confluent-kafka producers, include `retries` and `socket.timeout.ms` in producer_config for resilience.
- For aiokafka producers, add `compression_type: "gzip"` to reduce network overhead.

### Eventbridge wrapper (AsyncEventBridge)
- Wrap `eventbridge.emitter.AsyncEventEmitter` in a Singleton class `AsyncEventBridge` to manage producer lifecycle.
- Expose async `get_event_emitter()` method to lazily initialize the `AsyncEventEmitter` with producer settings.
- Use `AsyncEventEmitter` API methods like `add_event_to_queue(topics, partition_value, event, event_meta, serialization_format, hash_flag, callback, headers)` and `emit_events()` to queue and flush events.

### Consumer bootstrap
- Read consumer config via `get_consumer_config()[CONSUMER_NAME]` where `CONSUMER_NAME` comes from environment or config.
- For sync consumers, instantiate `kafka.KafkaConsumer` (as `SyncKafkaConsumer`) with explicit auth params, subscribe to topics, poll in a loop, dispatch to handlers from `topics_configurations[topic]["tasks"]` or accumulate for `["batch_tasks"]`, then manually call `consumer.commit()` after handlers succeed.
- For async consumers, delegate to `eventbridge.consumer.setup_and_start_consumer(settings)` which handles the poll/dispatch/commit loop internally.
- Run consumer, healthz, and readyz coroutines concurrently via `asyncio.gather(consumer, healthz, readyz)`.

### SASL_SSL + GSSAPI Kerberos authentication
- Build SSL context with `ssl.create_default_context(cafile=CA_PEM_PATH)`, load client cert with `load_cert_chain(certfile=CERT_PEM, keyfile=KEY_FILE)`.
- **Security note**: Some patterns set `check_hostname=False` and `verify_mode=ssl.CERT_NONE` for internal networks with self-signed CAs. **This is insecure for production** — prefer adding your internal CA to the system trust store and enabling full TLS verification, or use properly-issued certificates with correct SANs.
- Construct auth dict with `security_protocol: "SASL_SSL"`, `sasl_mechanism: "GSSAPI"`, `sasl_kerberos_service_name: "kafka"`, and `ssl_context`.
- Write certificate files at entrypoint startup: restore PEM/key from env vars (space-separated, inserting newlines around BEGIN/END markers), base64-decode keytab from env var, write to cert directory with `chmod 0o600`.
- Rewrite `krb5.conf` to strip `includedir`, inject KDC hosts from config, switch ccache from `KEYRING` to `FILE`, set `KRB5_CONFIG` env var, and run `kinit -kt <keytab> <principal>`.
- REDACT all cert/keytab bytes, broker hosts, and principals in code and configs.

### Config flow and offset management
- Load config hierarchy: `docker_config.loaded_config` -> `constants.py` (offset reset, session timeout, topic names) -> `consumer/config.py` (the config map) -> `consumer.py` (bootstrap).
- Use `auto_offset_reset` (earliest/latest) from constants; set `enable_auto_commit: False` and manually commit after successful processing.
- Retry/DLQ is NOT wired at the consumer layer; handle retries at application level in handler functions.

### Serialization and error handling
- Use `deserialization_format` or `KAFKA_SERIALIZATION_FORMAT` (typically "JSON") to control message deserialization.
- For sync consumers, deserialize values with lambda deserializers or parse JSON in handler; for async consumers, eventbridge handles deserialization.
- Catch `kafka.errors.CommitFailedError` after batch processing; log and continue (partition reassigned, messages will be reprocessed).

## Skeleton / example

```python
# services/kafka/constants.py
from config.docker_config import loaded_config

KAFKA_OFFSET_RESET_STRATEGY = "earliest"
KAFKA_SESSION_TIMEOUT_IN_MS = 30000
KAFKA_SERIALIZATION_FORMAT = "JSON"
CONSUMER_TOPIC = "my-topic"

# services/kafka/consumer/config.py
from services.kafka.constants import KAFKA_OFFSET_RESET_STRATEGY, KAFKA_SERIALIZATION_FORMAT
from my_module.handlers import process_message

def get_consumer_config():
    return {
        "my_consumer": {
            "service_name": "my_service",
            "deserialization_format": KAFKA_SERIALIZATION_FORMAT,
            "consumer_config": {
                "bootstrap_servers": loaded_config.KAFKA_BROKERS,
                "group_id": "my_consumer_group",
                "auto_offset_reset": KAFKA_OFFSET_RESET_STRATEGY,
                "enable_auto_commit": False,
                "session_timeout_ms": 30000,
            },
            "topics_configurations": {
                "my-topic": {"tasks": [process_message]}
            },
            "async_kafka": True,
            "custom_commit_offset": "pre",
        }
    }

# services/kafka/consumer/consumer.py (async pattern, eventbridge)
import asyncio
from eventbridge.consumer import setup_and_start_consumer
from services.kafka.consumer.config import get_consumer_config

async def main():
    consumer_name = "my_consumer"
    config = get_consumer_config()[consumer_name]
    await setup_and_start_consumer(config)

# services/kafka/producer/config.py
KAFKA_COMMON_PRODUCER_CONFIG = {
    "service_name": "my_service",
    "producer_config": {
        "bootstrap_servers": loaded_config.KAFKA_BROKERS,
        "enable_idempotence": True,
        "acks": "all",
    },
}

# services/kafka/producer/producer.py (eventbridge wrapper)
from eventbridge.emitter import AsyncEventEmitter

class Singleton(type):
    _instances = {}
    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]

class AsyncEventBridge(metaclass=Singleton):
    async def get_event_emitter(self):
        if not hasattr(self, "event_emitter"):
            from services.kafka.producer.config import KAFKA_COMMON_PRODUCER_CONFIG
            self.event_emitter = AsyncEventEmitter(KAFKA_COMMON_PRODUCER_CONFIG)
        return self.event_emitter

# entrypoint.py (SASL_SSL + GSSAPI setup)
import os
import ssl
import base64
import subprocess
from pathlib import Path

def _write_certificates():
    cert_dir = Path("/tmp/kafka_certs")
    cert_dir.mkdir(exist_ok=True, mode=0o700)
    
    # Restore PEM from env (space-separated -> newline-separated)
    pem_content = os.environ["KAFKA_CA_PEM"].replace(" ", "\n")
    (cert_dir / "ca.pem").write_text(pem_content)
    (cert_dir / "ca.pem").chmod(0o600)
    
    keytab = base64.b64decode(os.environ["KAFKA_KEYTAB_B64"])
    (cert_dir / "kafka.keytab").write_bytes(keytab)
    (cert_dir / "kafka.keytab").chmod(0o600)

def _setup_kerberos():
    krb5_conf = Path("/tmp/krb5.conf")
    # Read, strip includedir, inject KDC hosts, write to krb5_conf
    # (see references/config-and-sasl-kerberos.md for full logic)
    os.environ["KRB5_CONFIG"] = str(krb5_conf)
    subprocess.run(["kinit", "-kt", "/tmp/kafka_certs/kafka.keytab", "<REDACTED>"], check=True)

def start_consumer():
    _write_certificates()
    _setup_kerberos()
    from services.kafka.consumer.consumer import main
    asyncio.run(main())
```

## Anti-patterns to avoid

- DO NOT hard-code broker hosts, keytabs, or certificates in code; always load from environment or config.
- DO NOT use `enable_auto_commit: True` for critical data pipelines; manual commit after successful processing prevents data loss on rebalance.
- DO NOT implement retry/DLQ logic at the consumer layer; handle retries and dead-letter logic in application handlers.
- DO NOT mix aiokafka and confluent-kafka config keys in a single config dict without understanding which library you're using; some implementations mix keys for eventbridge compatibility, but this is library-specific.
- DO NOT skip Kerberos kinit before starting a SASL_GSSAPI consumer; ticket must be acquired at entrypoint or consumer startup.
- DO NOT ignore `CommitFailedError`; log and continue because partition reassignment means messages will be reprocessed.
- DO NOT expose sensitive data (broker hosts, principals, keytabs) in logs or code; redact all credentials.
- **DO NOT disable TLS verification (`check_hostname=False`, `verify_mode=ssl.CERT_NONE`) in production**; this allows man-in-the-middle attacks. Some patterns use this for internal networks with self-signed CAs, but production should use proper CA trust or properly-issued certificates.

## References

- [Repo Evidence](references/repo-evidence.md) — Real file paths and snippets from source repos
- [Consumer and Producer Patterns](references/consumer-producer-patterns.md) — Deep inventory of config map variants and bootstrap loops
- [Config and SASL Kerberos](references/config-and-sasl-kerberos.md) — Full SASL_SSL+GSSAPI wiring with certificate management
- [Troubleshooting and Patterns](references/troubleshooting-and-patterns.md) — Common issues, solutions, performance tuning, and migration strategies
