# kafka-config-driven

Config-driven Kafka consumer and producer implementation patterns extracted from production Python/FastAPI services.

## What this skill covers

This skill documents the config-driven approach to Kafka integration used across production Python/FastAPI backend services:

- **Consumer config maps**: Python dict-based topic-to-handler routing with per-message or batch processing modes
- **Producer config**: Idempotent producer settings with exactly-once semantics (acks: all, enable_idempotence)
- **Eventbridge wrapper**: `AsyncEventBridge` singleton wrapping `eventbridge.emitter.AsyncEventEmitter` for producer abstraction
- **SASL_SSL + GSSAPI Kerberos authentication**: Full certificate management, keytab handling, krb5.conf rewriting, and kinit automation
- **Consumer bootstrap patterns**: Both sync (kafka-python with manual poll/commit) and async (eventbridge-delegated) consumer loops
- **Config flow and offset management**: Manual offset commit patterns for at-least-once or at-most-once delivery guarantees

## Provenance

All conventions in this skill are derived from real-world production Python/FastAPI services implementing Kafka integration.

## How to apply

1. **Read the SKILL.md** to understand the core conventions (config map shape, producer config, eventbridge wrapper, SASL_SSL+GSSAPI setup).
2. **Consult the reference files** under `references/` for detailed patterns:
   - `repo-evidence.md` — Example code patterns from production services
   - `consumer-producer-patterns.md` — Deep inventory of consumer map variants, producer config, eventbridge wrapper, and bootstrap loops
   - `config-and-sasl-kerberos.md` — Full SASL_SSL+GSSAPI wiring including entrypoint certificate writing and kinit automation
3. **Adapt to your project**: Copy the config map skeleton from SKILL.md, adjust topic names and handler functions, configure Kerberos if needed, and choose sync vs async consumer bootstrap based on your eventbridge library availability.
4. **Maintain security**: Always redact credentials, never disable TLS verification in production (use proper CA trust or cert pinning instead of `check_hostname=False` and `verify_mode=CERT_NONE`), and store keytabs/certificates in secrets management (not in code or env vars directly).

### Codebase-derived

All patterns in this skill are directly extracted from production Python/FastAPI services:

- Consumer config map shapes (flat per-consumer and nested SERVICE_NAME -> consumer variants)
- Producer config with idempotence
- Eventbridge wrapper Singleton pattern
- SASL_SSL+GSSAPI setup with entrypoint certificate writing and kinit automation
- Consumer bootstrap loops (sync poll/commit and eventbridge-delegated async patterns)
- Config flow from docker_config -> constants.py -> consumer/config.py -> consumer.py

### Internet-confirmed

The following external facts were confirmed against official documentation:

> Confirmed against: https://kafka.apache.org/documentation/#producerconfigs
> 
> - `enable_idempotence: True` and `acks: "all"` together provide exactly-once producer semantics (Kafka 0.11+)
> - `retries` and `acks` must be set appropriately for idempotent producers

> Confirmed against: https://kafka-python.readthedocs.io/ and https://docs.confluent.io/kafka-clients/python/current/overview.html
> 
> - kafka-python uses underscore keys (`bootstrap_servers`, `enable_auto_commit`); confluent-kafka uses dot keys (`bootstrap.servers`, `enable.auto.commit`)
> - `enable_auto_commit: False` requires manual `consumer.commit()` calls

> Confirmed against: https://web.mit.edu/kerberos/krb5-latest/doc/admin/conf_files/krb5_conf.html
> 
> - `KRB5_CONFIG` env var overrides default krb5.conf location
> - `kinit -kt <keytab> <principal>` acquires a Kerberos ticket using a keytab file

> Confirmed against: https://aiokafka.readthedocs.io/en/stable/
> 
> - aiokafka supports `compression_type: "gzip"` for producer compression

All other patterns (config map structure, eventbridge wrapper, certificate handling) are production-service-derived and not from public documentation.
