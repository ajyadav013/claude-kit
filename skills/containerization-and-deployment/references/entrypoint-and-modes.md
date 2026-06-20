# Entrypoint MODE Dispatch

One Docker image, multiple deployment roles via `MODE` env var.

## Complete Multi-Mode Pattern

**Example from a production service**:

```python
import os
from opentelemetry.instrumentation import auto_instrumentation
import sentry_config
from src.config.docker_config import loaded_config
from src.metrics.service_init import (
    execute_mode,
    init_metrics_for_service,
    log_metrics_status,
)

MODE = os.environ.get("MODE")

sentry_config.initialize()
auto_instrumentation.initialize()

# Initialize metrics for all service modes
print(f"Initializing metrics for service mode: {MODE}")
metrics_port = init_metrics_for_service(MODE or "unknown")
log_metrics_status(MODE or "unknown", metrics_port)

if MODE == "server":
    import asyncio
    from src.main import main as server_main

    if __name__ == "__main__":
        server_main()

elif MODE == "consumer":
    import asyncio
    from src.services.kafka.consumer.consumer import main as consumer_main

    print("Starting Consumer")
    asyncio.run(execute_mode(consumer_main))

elif MODE == "worker":
    import asyncio
    from src.workers.run import main as worker_main

    worker_mode = loaded_config.WORKER_MODE
    print(f"Starting {worker_mode} Worker")
    asyncio.run(execute_mode(worker_main))

elif MODE == "cron":
    import asyncio
    from src.crons.run import main as cron_main

    cron_job = loaded_config.CRON_JOB
    print(f"Starting {cron_job} Cron Job")
    asyncio.run(execute_mode(cron_main))

elif MODE == "temporal_worker":
    import asyncio
    from src.temporal.run import worker_main

    print("Starting Temporal Worker")
    worker_mode = loaded_config.WORKER_MODE
    temporal_queue = loaded_config.TEMPORAL_QUEUE
    asyncio.run(execute_mode(worker_main, worker_mode, temporal_queue))
else:
    print(f"MODE {MODE} not available")
```

**Modes**:
- `server` → FastAPI application (uvicorn)
- `consumer` → Kafka consumer
- `worker` → Background task worker (uses `WORKER_MODE` to select which worker pool)
- `cron` → Scheduled job (uses `CRON_JOB` to select which cron function)
- `temporal_worker` → Temporal workflow worker (uses `WORKER_MODE` and `TEMPORAL_QUEUE`)

**Common bootstrap**: Sentry, OpenTelemetry, and metrics initialization happen BEFORE mode dispatch (shared across all modes).

## Extended Mode Pattern

**Example from a production service**:

```python
import asyncio
import os
from opentelemetry.instrumentation import asgi
import sentry_sdk
import ssl

from config.docker_config import loaded_config
from config.logging import initialize_opentelemetry
from app.main import main as server_main
from services.kafka.consumer.consumer import main as consumer_main
from services.temporal.run_workers import worker_main
from app.crons.setup import crons
from apps.orchestrator.worker import worker_main as orchestrator_worker_main
from apps.signal_forwarder.consumer import main as signal_forwarder_main
from global_utils.cache_utils import (
    apply_cache_to_functions,
    CACHE_FUNCTIONS,
    CACHE_EXPIRES,
)
from aiocache import caches

# ... (OpenTelemetry patching, cache setup)

def initialize_telemetry_and_error_tracking():
    initialize_opentelemetry()
    if loaded_config.ENABLE_SENTRY:
        sentry_sdk.init(dsn=loaded_config.SENTRY_DSN)

def download_certificates():
    """Write API certs from env vars to filesystem."""
    public_certificate = loaded_config.API_PUBLIC_CERTIFICATE
    private_key = loaded_config.API_PRIVATE_KEY

    cert_directory = "/srv/app/certificates"
    public_cert_file = os.path.join(cert_directory, "api_public_cert.pem")
    private_key_file = os.path.join(cert_directory, "api_private_key.pem")

    os.makedirs(cert_directory, exist_ok=True)
    public_certificate = public_certificate.replace("\\n", "\n")
    private_key = private_key.replace("\\n", "\n")

    with open(public_cert_file, "w") as pub_file:
        pub_file.write(public_certificate)

    with open(private_key_file, "w") as private_file:
        private_file.write(private_key)

    # Create SSL context for API
    API_SSL_CONTEXT = ssl.create_default_context()
    cert_path = os.path.join(os.getcwd(), 'certificates', 'api_public_cert.pem')
    key_path = os.path.join(os.getcwd(), 'certificates', 'api_private_key.pem')
    API_SSL_CONTEXT.load_cert_chain(certfile=cert_path, keyfile=key_path)

def start_server():
    server_main()

def start_consumer():
    asyncio.run(consumer_main())

def start_temporal_worker():
    worker_mode = loaded_config.WORKER_MODE
    asyncio.run(worker_main(worker_mode))

def start_orchestrator_worker():
    worker_mode = loaded_config.WORKER_MODE or "orchestrator_worker"
    asyncio.run(orchestrator_worker_main(worker_mode))

def start_signal_forwarder():
    asyncio.run(signal_forwarder_main())

def start_cron():
    cron_job = crons.get(loaded_config.CRON_JOB)
    if cron_job:
        asyncio.run(cron_job())

mode_actions = {
    "server": start_server,
    "webhook_server": start_server,  # Alias for server
    "test": start_server,             # Test mode uses server
    "consumer": start_consumer,
    "temporal_worker": start_temporal_worker,
    "orchestrator_worker": start_orchestrator_worker,        # Workflow execution worker
    "signal_forwarder": start_signal_forwarder, # Signal forwarding consumer
    "cron": start_cron,
}

if __name__ == "__main__":
    initialize_telemetry_and_error_tracking()
    download_certificates()
    action = mode_actions.get(loaded_config.MODE)
    if action:
        action()
```

**Extended modes**:
- `server` / `webhook_server` / `test` → FastAPI server (aliases for different deploy contexts)
- `consumer` → Kafka consumer
- `temporal_worker` → Temporal workflow worker
- `orchestrator_worker` → Workflow execution worker
- `signal_forwarder` → Signal forwarding consumer (separate from main consumer)
- `cron` → Scheduled job (lookup cron function from `crons` registry)

**Cert bootstrap**: `download_certificates()` writes API public cert and private key from env vars (with `\n` literal replacement) to filesystem before starting any mode.

## Minimal Pattern with Cert Writing

**Example from a production service**:

```python
import asyncio
import base64
import os
import re
import shutil
from pathlib import Path

from app.main import main as server_main
from services.temporal.run_workers import worker_main
from config.docker_config import loaded_config

CERT_DIR = Path("/tmp/kafka_certificates")

def _restore_pem(env_value: str) -> str:
    """Restore PEM file content from a space-separated env var."""
    result = re.sub(r'(-----(?:BEGIN|END) [A-Z ]+-----)', r'\n\1\n', env_value)
    lines = result.strip().split('\n')
    rebuilt = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith('-----'):
            rebuilt.append(line)
        else:
            rebuilt.extend(line.split())
    return '\n'.join(rebuilt) + '\n'

def _write_kafka_certificates() -> None:
    """Write Kafka certificate files from env-var secrets."""
    CERT_DIR.mkdir(parents=True, exist_ok=True)

    # PEM / key files — stored as space-separated text in env vars
    pem_files = {
        "server.pem": loaded_config.KAFKA_SERVER_PEM,
        "ca-certificate.pem": loaded_config.KAFKA_CA_CERTIFICATE_PEM,
        "ca-certificate.key": loaded_config.KAFKA_CA_CERTIFICATE_KEY,
    }
    for filename, content in pem_files.items():
        path = CERT_DIR / filename
        path.write_text(_restore_pem(content))
        os.chmod(path, 0o600)
        print(f"[entrypoint] Wrote {path}", flush=True)

    # Keytab — stored as base64 in env var
    keytab_path = CERT_DIR / "service.keytab"
    keytab_path.write_bytes(
        base64.b64decode(loaded_config.KAFKA_KEYTAB_BASE64)
    )
    os.chmod(keytab_path, 0o600)
    print(f"[entrypoint] Wrote {keytab_path}", flush=True)

    # Copy krb5.conf from repo into the cert dir
    repo_root = Path(__file__).resolve().parent
    krb5_src = repo_root / "kafka_certificates" / "krb5.conf"
    krb5_dst = CERT_DIR / "krb5.conf"
    shutil.copy2(krb5_src, krb5_dst)
    print(f"[entrypoint] Copied {krb5_dst}", flush=True)

    # Point existing env vars at the generated files
    os.environ["KAFKA_CERT_DIR"] = str(CERT_DIR)
    os.environ["KAFKA_SSL_CA_FILE"] = str(CERT_DIR / "server.pem")
    os.environ["KAFKA_SSL_CERT_FILE"] = str(CERT_DIR / "ca-certificate.pem")
    os.environ["KAFKA_SSL_KEY_FILE"] = str(CERT_DIR / "ca-certificate.key")
    os.environ["KAFKA_KEYTAB_PATH"] = str(CERT_DIR / "service.keytab")

def start_server():
    server_main()

def start_temporal_worker():
    worker_mode = loaded_config.WORKER_MODE
    asyncio.run(worker_main(worker_mode))

def start_consumer():
    _write_kafka_certificates()  # Write certs BEFORE starting consumer
    from services.kafka.consumer.consumer import main as consumer_main
    asyncio.run(consumer_main())

mode_actions = {
    "server": start_server,
    "data-server": start_server,      # Alias for data processing server
    "temporal_worker": start_temporal_worker,
    "consumer": start_consumer
}

if __name__ == "__main__":
    action = mode_actions.get(loaded_config.MODE)
    if action:
        action()
```

**Cert bootstrap**: `_write_kafka_certificates()` is called ONLY when `MODE=consumer` (Kafka consumer needs certs/keytab for SASL_SSL + GSSAPI Kerberos auth). Not needed for server or temporal_worker.

**PEM restoration**: PEM files are stored as space-separated strings in env vars (to fit in single-line env vars); `_restore_pem()` rebuilds newlines around `-----BEGIN/END-----` markers.

**Keytab decode**: Keytab binary is base64-encoded in env var; decoded at runtime.

## Minimal Two-Mode Pattern

**Example from a production service**:

```python
from opentelemetry.instrumentation import auto_instrumentation

auto_instrumentation.initialize()

from config.docker_config import loaded_config

if loaded_config.MODE == "server":
    from app.main import main as server_main

    if __name__ == "__main__":
        server_main()

elif loaded_config.MODE == "consumer":
    import asyncio
    from services.kafka.consumer.consumer import main as consumer_main

    print("Starting Consumer")
    asyncio.run(consumer_main())

else:
    print("MODE not available")
```

**Modes**:
- `server` → FastAPI server
- `consumer` → Kafka consumer

**Minimal pattern**: Just OpenTelemetry auto-instrumentation and two modes (no worker/cron/temporal).

## Common Patterns

### Mode Registry

Use a `mode_actions` dict to map MODE strings to functions:

```python
mode_actions = {
    "server": start_server,
    "consumer": start_consumer,
    "worker": start_worker,
    "cron": start_cron,
}

if __name__ == "__main__":
    action = mode_actions.get(os.environ.get("MODE"))
    if action:
        action()
    else:
        print(f"MODE {os.environ.get('MODE')} not available")
```

### Worker/Cron Disambiguation

For `MODE=worker` or `MODE=cron`, read a second env var (`WORKER_MODE`, `CRON_JOB`) to select which worker pool or cron function:

```python
if MODE == "worker":
    worker_mode = loaded_config.WORKER_MODE  # e.g., "db_events_publisher"
    asyncio.run(worker_main(worker_mode))

if MODE == "cron":
    cron_job = loaded_config.CRON_JOB  # e.g., "vendor_updates_pull"
    asyncio.run(cron_main(cron_job))
```

### Temporal Worker Config

Temporal workers need both `WORKER_MODE` (which workflows to handle) and `TEMPORAL_QUEUE` (which queue to poll):

```python
if MODE == "temporal_worker":
    worker_mode = loaded_config.WORKER_MODE      # e.g., "parent", "child"
    temporal_queue = loaded_config.TEMPORAL_QUEUE # e.g., "parent-temporal-queue"
    asyncio.run(worker_main(worker_mode, temporal_queue))
```

### Mode Aliases

Multiple MODE values can point to the same function (e.g., `server`, `webhook_server`, `test` all start the FastAPI app):

```python
mode_actions = {
    "server": start_server,
    "webhook_server": start_server,
    "test": start_server,
}
```

### Bootstrap Order

1. Import config
2. Initialize observability (Sentry, OpenTelemetry, metrics)
3. Write certs/keytabs if needed (for consumer mode)
4. Dispatch to mode function

```python
if __name__ == "__main__":
    initialize_telemetry()
    download_certificates()  # If needed
    action = mode_actions.get(MODE)
    if action:
        action()
```
