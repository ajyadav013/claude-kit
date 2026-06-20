# Config and SASL Kerberos

Full SASL_SSL + GSSAPI Kerberos wiring including entrypoint certificate writing and kinit automation, derived from production Python/FastAPI services.

## Config flow

```
Environment / docker-compose
        ↓
config/docker_config.py (loaded_config)
        ↓
services/kafka/constants.py
  - KAFKA_OFFSET_RESET_STRATEGY
  - KAFKA_SESSION_TIMEOUT_IN_MS
  - KAFKA_SERIALIZATION_FORMAT
  - Topic name constants
        ↓
services/kafka/consumer/config.py
  - get_consumer_config() returns the config map
  - Reads loaded_config for broker lists, cert paths
        ↓
services/kafka/consumer/consumer.py
  - Reads CONSUMER_NAME from loaded_config
  - Calls get_consumer_config()[CONSUMER_NAME]
  - Instantiates consumer with config["consumer_config"]
```

### Config keys used

**From docker_config:**
- `KAFKA_BROKER_LIST` — Comma-separated broker hosts (REDACTED)
- `KAFKA_CERT_DIR` — Directory for certificates (default: `repo_root/kafka_certificates`)
- `KAFKA_SSL_CA_FILE` — CA certificate PEM path
- `KAFKA_SSL_CERT_FILE` — Client certificate PEM path
- `KAFKA_SSL_KEY_FILE` — Client key file path
- `KAFKA_SASL_KERBEROS_SERVICE_NAME` — Kerberos service name (default: "kafka")
- `KAFKA_KEYTAB_PATH` — Keytab file path
- `KAFKA_KRB5_CONF_PATH` — krb5.conf source path
- `KAFKA_KRB5_CONFIG_OUT` — krb5.conf output path (default: `/tmp/krb5_kafka.conf`)
- `KAFKA_KERBEROS_PRINCIPAL` — Kerberos principal (REDACTED, e.g., `user@REALM.COM`)
- `KAFKA_KDC_HOSTS` — Comma-separated KDC hosts (REDACTED)
- `KERBEROS_AUTH_ENABLED` — Boolean flag to enable Kerberos setup
- `CONSUMER_NAME` — Which consumer to start

**From constants.py:**
- `KAFKA_OFFSET_RESET_STRATEGY` — "earliest" or "latest"
- `KAFKA_SESSION_TIMEOUT_IN_MS` — Typically 30000 (30 seconds)
- `KAFKA_SERIALIZATION_FORMAT` — "JSON", "AVRO", or "MSGPACK"

---

## SASL_SSL + GSSAPI Kerberos setup

### Step 1: Write certificates at entrypoint

**File:** `entrypoint.py`

```python
import os
import re
import shutil
import base64
from pathlib import Path
from config.docker_config import loaded_config

CERT_DIR = Path("/tmp/kafka_certificates")

def _restore_pem(env_value: str) -> str:
    """Restore PEM file content from a space-separated env var.
    
    Certificates are stored in env vars with spaces instead of newlines
    (to avoid shell escaping issues). This function:
    1. Inserts newlines around BEGIN/END markers
    2. Splits the rest on spaces (each base64 line was space-separated)
    3. Rebuilds with proper newlines
    """
    # Insert newlines around -----BEGIN/END ... ----- markers
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
            # Split space-separated base64 chunks back to individual lines
            rebuilt.extend(line.split())
    return '\n'.join(rebuilt) + '\n'


def _write_kafka_certificates() -> None:
    """Write Kafka certificate files from env-var secrets.
    
    Certificates and keys are stored in env vars (base64 content with spaces
    instead of newlines). Keytab is base64-encoded binary.
    """
    CERT_DIR.mkdir(parents=True, exist_ok=True)

    # PEM / key files — stored as space-separated text in env vars
    pem_files = {
        "server.pem": loaded_config.KAFKA_CERTIFICATES_SERVER_PEM,
        "ca-certificate.pem": loaded_config.KAFKA_CERTIFICATES_CA_CERTIFICATE_PEM,
        "ca-certificate.key": loaded_config.KAFKA_CERTIFICATES_CA_CERTIFICATE_KEY,
    }
    for filename, content in pem_files.items():
        path = CERT_DIR / filename
        path.write_text(_restore_pem(content))
        os.chmod(path, 0o600)  # Secure permissions
        print(f"[entrypoint] Wrote {path}", flush=True)

    # Keytab — stored as base64 in env var
    keytab_path = CERT_DIR / "app.keytab"
    keytab_path.write_bytes(
        base64.b64decode(loaded_config.KAFKA_CERTIFICATES_KEYTAB)
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
    os.environ["KAFKA_KEYTAB_PATH"] = str(CERT_DIR / "app.keytab")
    os.environ["KAFKA_KRB5_CONF_PATH"] = str(krb5_dst)


def start_consumer():
    """Consumer entrypoint: write certs, then start consumer."""
    _write_kafka_certificates()
    from services.kafka.consumer.consumer import main as consumer_main
    asyncio.run(consumer_main())
```

**Key features:**
- Certificates/keys stored in env vars as space-separated base64 (workaround for newline escaping in docker-compose/k8s)
- `_restore_pem()` re-inserts newlines around BEGIN/END markers and between base64 lines
- Keytab is base64-encoded binary, decoded with `base64.b64decode()`
- All files written with `chmod 0o600` (owner-read-only) for security
- Env vars updated to point to written files (so consumer config can read them)

---

### Step 2: Build SSL context

**File:** `services/kafka/consumer/config.py`

```python
import os
import ssl
from pathlib import Path
from config.docker_config import loaded_config
from services.kafka.constants import KAFKA_OFFSET_RESET_STRATEGY, KAFKA_SESSION_TIMEOUT_IN_MS

def _build_consumer_config():
    REPO_ROOT = Path(__file__).resolve().parents[3]
    CERT_DIR = Path(
        os.getenv("KAFKA_CERT_DIR", str(REPO_ROOT / "kafka_certificates"))
    )
    KAFKA_SSL_CA_FILE = os.getenv(
        "KAFKA_SSL_CA_FILE", str(CERT_DIR / "server.pem")
    )
    KAFKA_SSL_CERT_FILE = os.getenv(
        "KAFKA_SSL_CERT_FILE", str(CERT_DIR / "ca-certificate.pem")
    )
    KAFKA_SSL_KEY_FILE = os.getenv(
        "KAFKA_SSL_KEY_FILE", str(CERT_DIR / "ca-certificate.key")
    )
    KAFKA_SASL_KERBEROS_SERVICE_NAME = os.getenv(
        "KAFKA_SASL_KERBEROS_SERVICE_NAME", "kafka"
    )

    # Create SSL context
    ssl_context = ssl.create_default_context(cafile=KAFKA_SSL_CA_FILE)
    ssl_context.check_hostname = False  # Disable hostname verification (REDACTED broker hosts)
    ssl_context.verify_mode = ssl.CERT_NONE  # Disable cert verification (internal CA)
    ssl_context.load_cert_chain(
        certfile=KAFKA_SSL_CERT_FILE,
        keyfile=KAFKA_SSL_KEY_FILE
    )

    # SASL_SSL + GSSAPI auth config
    KAFKA_KERBEROS_CONFIG = {
        "security_protocol": "SASL_SSL",
        "sasl_mechanism": "GSSAPI",
        "sasl_kerberos_service_name": KAFKA_SASL_KERBEROS_SERVICE_NAME,
        "ssl_context": ssl_context,
    }

    # Consumer config map (spread Kerberos config into each consumer)
    return {
        "app_consumer": {
            "service_name": "app_consumer",
            "deserialization_format": "JSON",
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
        },
        # ... more consumers
    }
```

**Key features:**
- `ssl.create_default_context(cafile=CA_PEM)` initializes SSL with CA cert
- `check_hostname = False` and `verify_mode = ssl.CERT_NONE` disable verification (internal CA, REDACTED broker hosts)
  - **Security note:** Only acceptable for internal networks with self-signed CAs; production should use proper CA trust
- `load_cert_chain(certfile, keyfile)` loads client cert for mutual TLS
- Auth config dict spread into each consumer's `consumer_config` with `**KAFKA_KERBEROS_CONFIG`

---

### Step 3: Kerberos kinit (acquire ticket)

**File:** `services/kafka/consumer/consumer.py`

```python
import os
import subprocess
from pathlib import Path
from config.docker_config import loaded_config


def _setup_kerberos_auth() -> None:
    """Rewrite krb5.conf and acquire Kerberos ticket via kinit.
    
    The stock krb5.conf from the repo needs fixes:
    1. Strip 'includedir' directives (not available in container)
    2. Inject KDC hosts from config (REDACTED in base krb5.conf)
    3. Switch ccache from KEYRING to FILE (KEYRING not available in container)
    
    Then run kinit with keytab to acquire a Kerberos ticket.
    """
    repo_root = Path(__file__).resolve().parents[3]
    cert_dir = Path(
        os.getenv("KAFKA_CERT_DIR", str(repo_root / "kafka_certificates"))
    )

    keytab_path = Path(
        os.getenv("KAFKA_KEYTAB_PATH", str(cert_dir / "app.keytab"))
    )
    krb5_conf_src = Path(
        os.getenv("KAFKA_KRB5_CONF_PATH", str(cert_dir / "krb5.conf"))
    )
    krb5_conf_fixed = Path(
        os.getenv("KAFKA_KRB5_CONFIG_OUT", "/tmp/krb5_kafka.conf")
    )
    kerberos_principal = os.getenv(
        "KAFKA_KERBEROS_PRINCIPAL", "<REDACTED>@<REDACTED>.COM"
    )

    # Read source krb5.conf
    with open(krb5_conf_src, "r", encoding="utf-8") as fp:
        content = fp.read()

    # Fix 1: Strip includedir lines (not available in minimal container)
    # Fix 2: Remove existing kdc/admin_server lines (will inject fresh ones)
    # Fix 3: Switch ccache from KEYRING to FILE
    fixed_lines = []
    for line in content.splitlines():
        if line.strip().startswith("includedir"):
            continue
        if line.strip().startswith("kdc =") or line.strip().startswith("admin_server ="):
            continue
        fixed_lines.append(
            line.replace("KEYRING:persistent:%{uid}", "FILE:/tmp/krb5cc_%{uid}")
        )

    # Inject KDC hosts from config
    kdc_hosts = loaded_config.KAFKA_KDC_HOSTS.split(",")
    kdc_lines = []
    for host in kdc_hosts:
        host = host.strip()
        kdc_lines.append(f"  kdc = {host}")
    kdc_lines.append(f"  admin_server = {kdc_hosts[0].strip()}")

    # Insert KDC lines after realm declaration
    realm_marker = "<REDACTED>.COM = {"  # REDACTED realm name
    final_lines = []
    for line in fixed_lines:
        final_lines.append(line)
        if realm_marker in line:
            final_lines.extend(kdc_lines)

    # Write fixed krb5.conf
    with open(krb5_conf_fixed, "w", encoding="utf-8") as fp:
        fp.write("\n".join(final_lines) + "\n")

    # Point Kerberos at our fixed config
    os.environ["KRB5_CONFIG"] = str(krb5_conf_fixed)

    # Acquire Kerberos ticket via kinit
    result = subprocess.run(
        ["kinit", "-kt", str(keytab_path), kerberos_principal],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "Kerberos authentication failed via kinit: "
            f"{result.stderr.strip() or 'unknown error'}"
        )
    print("[consumer] Kerberos authentication successful", flush=True)


async def main():
    """Consumer main: setup Kerberos if enabled, then start consumer."""
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
- Read source `krb5.conf` from repo (checked in with placeholders)
- Strip `includedir` directives (not available in container filesystem)
- Remove existing `kdc =` and `admin_server =` lines
- Switch ccache from `KEYRING:persistent:%{uid}` to `FILE:/tmp/krb5cc_%{uid}` (KEYRING not available in minimal containers)
- Inject KDC hosts from `loaded_config.KAFKA_KDC_HOSTS` (comma-separated, REDACTED in code)
- Write fixed config to `/tmp/krb5_kafka.conf`
- Set `KRB5_CONFIG` env var to override system krb5.conf
- Run `kinit -kt <keytab> <principal>` to acquire ticket
- Raise error if kinit fails (stderr captured and logged)

---

## Full consumer bootstrap with SASL_SSL + GSSAPI

**Combined flow:**

```python
# entrypoint.py
def start_consumer():
    _write_kafka_certificates()  # Write certs/keytab from env vars
    from services.kafka.consumer.consumer import main
    asyncio.run(main())

# services/kafka/consumer/consumer.py
async def main():
    if loaded_config.KERBEROS_AUTH_ENABLED:
        _setup_kerberos_auth()  # Rewrite krb5.conf, run kinit

    loop = asyncio.get_running_loop()
    consumer_state = {}

    await asyncio.gather(
        asyncio.to_thread(_run_kafka_consumer, loop, consumer_state),
        _healthz(consumer_state),
        _readyz(),
    )

def _run_kafka_consumer(loop, consumer_state):
    config = get_consumer_config()[loaded_config.CONSUMER_NAME]
    consumer_cfg = config["consumer_config"]
    
    consumer = SyncKafkaConsumer(
        bootstrap_servers=consumer_cfg["bootstrap_servers"],
        security_protocol=consumer_cfg["security_protocol"],  # "SASL_SSL"
        sasl_mechanism=consumer_cfg["sasl_mechanism"],  # "GSSAPI"
        sasl_kerberos_service_name=consumer_cfg["sasl_kerberos_service_name"],  # "kafka"
        ssl_context=consumer_cfg["ssl_context"],  # Built with certs from _build_consumer_config
        group_id=consumer_cfg["group_id"],
        enable_auto_commit=False,
        # ... other settings
    )
    
    consumer.subscribe(topics)
    
    while True:
        records = consumer.poll(timeout_ms=5000)
        # ... process records, call batch_tasks
        consumer.commit()
```

**Startup sequence:**
1. Entrypoint calls `_write_kafka_certificates()` — writes PEM/key/keytab from env vars to `/tmp/kafka_certificates/` with 0o600 permissions
2. Consumer main calls `_setup_kerberos_auth()` if `KERBEROS_AUTH_ENABLED` — rewrites krb5.conf, sets `KRB5_CONFIG`, runs `kinit -kt <keytab> <principal>`
3. Consumer instantiation reads `ssl_context` from config (built in `_build_consumer_config()` from written cert files)
4. kafka-python uses SASL_SSL + GSSAPI with the acquired Kerberos ticket to authenticate to brokers

---

## Security considerations

### REDACTED credentials

All code and configs **must redact**:
- Broker hostnames/IPs (`KAFKA_BROKER_LIST`)
- Kerberos principal (`KAFKA_KERBEROS_PRINCIPAL`)
- KDC hosts (`KAFKA_KDC_HOSTS`)
- Realm names (in krb5.conf)
- Certificate/keytab bytes (in env vars)

### File permissions

- Certificates, keys, and keytabs written with `chmod 0o600` (owner-read-only)
- Cert directory created with `mkdir(mode=0o700)` (owner-only access)

### TLS verification disabled

**Production pattern:**
```python
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE
```

**Why:** Internal brokers with self-signed CA, hostnames may not match certificate SAN/CN.

**Security risk:** Allows MITM attacks. Acceptable only in isolated internal networks with network-level security.

**Better alternatives for production:**
1. Use proper CA-signed certificates with correct hostnames
2. Add internal CA to system trust store and enable verification
3. Use `verify_mode = ssl.CERT_REQUIRED` with `check_hostname = True` and properly-issued certs

### Keytab storage

**Current pattern:** Keytab stored in env var as base64, written to disk at startup.

**Better alternatives:**
1. Mount keytab from Kubernetes secret volume (avoids env var size limits)
2. Use Vault or cloud secret manager with dynamic keytab generation
3. Rotate keytabs periodically

### Kerberos ticket refresh

**Current pattern:** `kinit` run once at startup; ticket TTL depends on KDC policy (typically 10-24 hours).

**Limitation:** Consumer will fail after ticket expires unless restarted.

**Better alternative:** Background thread to periodically run `kinit -R` (renew ticket) or re-acquire with `kinit -kt`.

---

## Config summary

### Required environment variables (SASL_SSL + GSSAPI)

```bash
# Kafka brokers
KAFKA_BROKER_LIST=<REDACTED>

# Kerberos
KERBEROS_AUTH_ENABLED=true
KAFKA_KERBEROS_PRINCIPAL=<REDACTED>@<REDACTED>.COM
KAFKA_KDC_HOSTS=<REDACTED>

# Certificates (space-separated base64 PEM content)
KAFKA_CERTIFICATES_SERVER_PEM=<REDACTED>
KAFKA_CERTIFICATES_CA_CERTIFICATE_PEM=<REDACTED>
KAFKA_CERTIFICATES_CA_CERTIFICATE_KEY=<REDACTED>

# Keytab (base64-encoded binary)
KAFKA_CERTIFICATES_KEYTAB=<REDACTED>

# Consumer to start
CONSUMER_NAME=app_consumer

# Optional overrides
KAFKA_CERT_DIR=/tmp/kafka_certificates
KAFKA_SASL_KERBEROS_SERVICE_NAME=kafka
KAFKA_KRB5_CONFIG_OUT=/tmp/krb5_kafka.conf
```

### Required Kafka settings (consumer_config)

```python
{
    "security_protocol": "SASL_SSL",
    "sasl_mechanism": "GSSAPI",
    "sasl_kerberos_service_name": "kafka",
    "ssl_context": ssl.SSLContext,  # Created with cert/key files
    "bootstrap_servers": str | list[str],
    "group_id": str,
    "enable_auto_commit": False,
    # ... other Kafka settings
}
```

---

## Alternative auth patterns

Some production services use simpler authentication patterns instead of SASL_SSL + GSSAPI:

### SASL_PLAIN (username/password)

```python
consumer_config = {
    "bootstrap_servers": "broker:9092",
    "security_protocol": "SASL_PLAINTEXT",  # or "SASL_SSL" with TLS
    "sasl_mechanism": "PLAIN",
    "sasl_plain_username": os.environ["KAFKA_USERNAME"],
    "sasl_plain_password": os.environ["KAFKA_PASSWORD"],
}
```

### No auth (internal-only cluster)

```python
consumer_config = {
    "bootstrap_servers": "broker:9092",
    # No security_protocol / sasl_mechanism
}
```

### TLS only (mutual TLS, no SASL)

```python
ssl_context = ssl.create_default_context(cafile=CA_PEM)
ssl_context.load_cert_chain(certfile=CERT_PEM, keyfile=KEY_FILE)

consumer_config = {
    "bootstrap_servers": "broker:9093",
    "security_protocol": "SSL",
    "ssl_context": ssl_context,
}
```

**Note:** Some production services use internal-only clusters or config-injected authentication at deployment.
