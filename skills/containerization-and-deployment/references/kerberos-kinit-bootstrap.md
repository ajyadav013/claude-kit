# Kerberos kinit Bootstrap

Container startup pattern for Kerberos authentication via keytab, enabling SASL_SSL + GSSAPI connections to Kafka.

## Problem

**Kerberos libraries expect system-wide config**: Default `krb5.conf` lives in `/etc/krb5.conf` and references system paths like `/etc/krb5.conf.d/` (via `includedir` directive) and uses KEYRING credential caches (`KEYRING:persistent:%{uid}`).

**Containers lack these dependencies**: Alpine images don't ship with KEYRING support; Cloud Run and minimal container runtimes don't have `/etc/krb5.conf.d/` directories.

**Result**: Kafka clients using GSSAPI fail with "Credentials cache not found" or "includedir not supported" errors.

## Solution: Patch krb5.conf at Runtime

**Read repo-bundled config**: Ship `krb5.conf` as part of the application code (e.g., `config/krb5.conf`); read it at container startup.

**Strip unsupported directives**: Remove `includedir /etc/krb5.conf.d/` lines (not present in containers).

**Replace credential cache type**: Change `KEYRING:persistent:%{uid}` to `FILE:/tmp/krb5cc_%{uid}` (file-based credential cache).

**Write patched config**: Save to `/tmp/krb5_patched.conf` with `0o644` permissions.

**Point KRB5_CONFIG env var**: Set `KRB5_CONFIG=/tmp/krb5_patched.conf` before running `kinit`.

**Authenticate with keytab**: Run `kinit -kt /path/to/service.keytab service-principal@REALM` to populate the credential cache.

## Code Pattern

**Python entrypoint snippet**:

```python
import os
import subprocess
from pathlib import Path

CERT_DIR = Path("/tmp/kafka_certificates")
KEYTAB_PATH = CERT_DIR / "service.keytab"
KRB5_CONF_SRC = Path(__file__).resolve().parent / "config" / "krb5.conf"
KRB5_CONF_PATCHED = Path("/tmp/krb5_patched.conf")
KERBEROS_PRINCIPAL = "service-principal@EXAMPLE.COM"

def setup_kerberos():
    """Patch krb5.conf for container compatibility and authenticate."""
    print("[setup_kerberos] Patching krb5.conf...", flush=True)

    # Read repo-bundled krb5.conf
    with KRB5_CONF_SRC.open("r") as f:
        content = f.read()

    # Strip includedir, replace KEYRING with FILE credential cache
    lines = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("includedir"):
            print(f"[setup_kerberos]   Skipping: {stripped}", flush=True)
            continue
        # Replace KEYRING with FILE
        line = line.replace("KEYRING:persistent:%{uid}", "FILE:/tmp/krb5cc_%{uid}")
        lines.append(line)

    # Write patched config to /tmp
    KRB5_CONF_PATCHED.write_text("\n".join(lines) + "\n")
    os.chmod(KRB5_CONF_PATCHED, 0o644)
    os.environ["KRB5_CONFIG"] = str(KRB5_CONF_PATCHED)
    print(f"[setup_kerberos] KRB5_CONFIG={KRB5_CONF_PATCHED}", flush=True)

    # Authenticate with keytab (use list args to avoid shell injection)
    print(f"[setup_kerberos] Running kinit for {KERBEROS_PRINCIPAL}...", flush=True)
    result = subprocess.run(
        ["kinit", "-kt", str(KEYTAB_PATH), KERBEROS_PRINCIPAL],
        capture_output=True,
        text=True
    )

    if result.returncode == 0:
        print("[setup_kerberos] kinit succeeded.", flush=True)
    else:
        print(f"[setup_kerberos] kinit failed: {result.stderr.strip()}", flush=True)
        # Some services tolerate kinit failure (e.g., if keytab is optional); others should exit
        # raise RuntimeError("Kerberos authentication failed")
```

**Where to call**:

```python
# In entrypoint.py, before starting Kafka consumer
def start_consumer():
    setup_kerberos()  # Authenticate first
    from services.kafka.consumer import main as consumer_main
    consumer_main()
```

## Generic krb5.conf Template

**Repo-bundled config** (ships in `config/krb5.conf`, read at runtime):

```ini
[libdefaults]
    default_realm = EXAMPLE.COM
    # Before patching: KEYRING:persistent:%{uid}
    # After patching:  FILE:/tmp/krb5cc_%{uid}
    default_ccache_name = KEYRING:persistent:%{uid}
    dns_lookup_realm = false
    dns_lookup_kdc = false
    ticket_lifetime = 24h
    renew_lifetime = 7d
    forwardable = true
    rdns = false

[realms]
    EXAMPLE.COM = {
        kdc = kdc.example.com:88
        admin_server = kdc.example.com:749
        default_domain = example.com
    }

[domain_realm]
    .example.com = EXAMPLE.COM
    example.com = EXAMPLE.COM

# This directive causes failures in containers:
# includedir /etc/krb5.conf.d/
```

**After patching** (what gets written to `/tmp/krb5_patched.conf`):

```ini
[libdefaults]
    default_realm = EXAMPLE.COM
    default_ccache_name = FILE:/tmp/krb5cc_%{uid}
    dns_lookup_realm = false
    dns_lookup_kdc = false
    ticket_lifetime = 24h
    renew_lifetime = 7d
    forwardable = true
    rdns = false

[realms]
    EXAMPLE.COM = {
        kdc = kdc.example.com:88
        admin_server = kdc.example.com:749
        default_domain = example.com
    }

[domain_realm]
    .example.com = EXAMPLE.COM
    example.com = EXAMPLE.COM
```

## Keytab Handling

**Write keytab from base64 env var** (before calling `setup_kerberos`):

```python
import base64

def _write_keytab():
    """Decode keytab from env var and write to /tmp."""
    keytab_b64 = os.environ.get("KEYTAB_BASE64")
    if not keytab_b64:
        print("[_write_keytab] KEYTAB_BASE64 not set; skipping.", flush=True)
        return

    CERT_DIR.mkdir(parents=True, exist_ok=True)
    KEYTAB_PATH.write_bytes(base64.b64decode(keytab_b64))
    os.chmod(KEYTAB_PATH, 0o600)
    print(f"[_write_keytab] Wrote {KEYTAB_PATH}", flush=True)

# In entrypoint.py:
def start_consumer():
    _write_keytab()
    setup_kerberos()
    # ... start consumer
```

**Keytab storage**: In Cloud Run / k8s, store the keytab as a base64-encoded secret:

```bash
# Create secret from keytab file
cat service.keytab | base64 > keytab_base64.txt

# Set as env var in Cloud Run
gcloud run deploy ... --set-env-vars="KEYTAB_BASE64=$(cat keytab_base64.txt)"

# Or in k8s secret
kubectl create secret generic kafka-keytab --from-literal=KEYTAB_BASE64="$(cat keytab_base64.txt)"
```

## Kafka Client Config (GSSAPI)

**kafka-python example**:

```python
from kafka import KafkaConsumer
import ssl

# After setup_kerberos() has run
ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
ssl_ctx.load_verify_locations("/tmp/kafka_ca.pem")
ssl_ctx.load_cert_chain(certfile="/tmp/kafka_client_cert.pem", keyfile="/tmp/kafka_client_key.pem")

consumer = KafkaConsumer(
    "my-topic",
    bootstrap_servers=["broker1.example.com:9093", "broker2.example.com:9093"],
    security_protocol="SASL_SSL",
    sasl_mechanism="GSSAPI",
    sasl_kerberos_service_name="kafka",
    ssl_context=ssl_ctx,
    group_id="my-consumer-group",
    auto_offset_reset="latest",
)
```

**confluent-kafka-python example**:

```python
from confluent_kafka import Consumer

conf = {
    'bootstrap.servers': 'broker1.example.com:9093,broker2.example.com:9093',
    'security.protocol': 'SASL_SSL',
    'sasl.mechanism': 'GSSAPI',
    'sasl.kerberos.service.name': 'kafka',
    'ssl.ca.location': '/tmp/kafka_ca.pem',
    'ssl.certificate.location': '/tmp/kafka_client_cert.pem',
    'ssl.key.location': '/tmp/kafka_client_key.pem',
    'group.id': 'my-consumer-group',
    'auto.offset.reset': 'latest',
}

consumer = Consumer(conf)
consumer.subscribe(['my-topic'])
```

**KRB5_CONFIG must be set before importing kafka libraries**: Some libraries read `KRB5_CONFIG` at import time; ensure `setup_kerberos()` runs before any `from kafka import ...` statements.

## Debugging Kerberos Issues

**Check credential cache**:

```bash
# Inside container
klist
# Should show:
# Ticket cache: FILE:/tmp/krb5cc_0
# Default principal: service-principal@EXAMPLE.COM
```

**Check KRB5_CONFIG**:

```bash
echo $KRB5_CONFIG
# Should print: /tmp/krb5_patched.conf

cat $KRB5_CONFIG
# Verify no includedir, and credential cache is FILE:/tmp/krb5cc_%{uid}
```

**Test kinit manually**:

```bash
kinit -kt /tmp/kafka_certificates/service.keytab service-principal@EXAMPLE.COM
klist
```

**Common errors**:

- `kinit: Generic preauthentication failure while getting initial credentials` → Keytab is invalid or principal mismatch.
- `kinit: Cannot find KDC for realm "EXAMPLE.COM"` → KDC host unreachable; check network/firewall.
- `Credentials cache file '/tmp/krb5cc_0' not found` → KRB5_CONFIG not set, or credential cache type still KEYRING.
- `includedir /etc/krb5.conf.d/ not supported` → krb5.conf not patched; `includedir` still present.

## Alternative: Dockerfile-level Patching

**Patch at build time instead of runtime** (if `krb5.conf` never changes):

```dockerfile
COPY config/krb5.conf /tmp/krb5.conf
RUN sed -i '/includedir/d' /tmp/krb5.conf && \
    sed -i 's|KEYRING:persistent:%{uid}|FILE:/tmp/krb5cc_%{uid}|g' /tmp/krb5.conf && \
    mv /tmp/krb5.conf /etc/krb5.conf

ENV KRB5_CONFIG=/etc/krb5.conf
```

**Trade-off**: Runtime patching allows `krb5.conf` to be updated without rebuilding the image; Dockerfile-level patching bakes it into the image (simpler entrypoint, but less flexible).

## Security Notes

- **Keytab permissions**: Always `chmod 0o600` on keytab files; readable only by the container's user.
- **Credential cache location**: `/tmp/krb5cc_%{uid}` is world-readable unless you set `umask 077` before `kinit`.
- **Secrets in env vars**: Keytabs in env vars are visible in `docker inspect` and k8s describe; use secret managers or mounted volumes for higher security.
- **Principal naming**: Use service accounts (e.g., `service-principal@EXAMPLE.COM`), not user principals, for automated services.

## Anti-patterns

- **Hardcoding realm/principal/KDC in code**: Read from env vars; different environments (dev/staging/prod) use different realms.
- **Skipping kinit error checks**: If Kafka connections fail silently, check `result.returncode` and raise an exception on kinit failure.
- **Using KEYRING in containers**: Unsupported in most container runtimes; always patch to FILE.
- **Committing keytabs to git**: Ship `krb5.conf` in the repo; keytabs are secrets and must be env vars or secret managers.
