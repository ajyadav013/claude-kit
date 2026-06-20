# Deployment and Secrets Management

Cloud Run deployment, k8s patterns, cert/keytab writing, and secrets hygiene.

## Cloud Run Deployment (GitHub Actions)

**Example from a production service**:

```yaml
name: Deploy to GCP Cloud Run (Development)

on:
  push:
    branches: [dev]
  workflow_dispatch:

jobs:
  deploy-backend:
    name: Deploy Backend to Cloud Run (Dev)
    runs-on: ubuntu-latest
    environment: development
    steps:
      - uses: actions/checkout@v4

      - id: auth
        uses: google-github-actions/auth@v2
        with:
          credentials_json: "${{ vars.GCP_SA_KEY }}"
          project_id: ${{ vars.GCP_PROJECT_ID }}

      - uses: google-github-actions/setup-gcloud@v2
        with:
          project_id: ${{ vars.GCP_PROJECT_ID }}

      - name: Configure Docker
        run: gcloud auth configure-docker asia.gcr.io --quiet

      - name: Check if image exists
        id: check-image
        run: |
          if docker manifest inspect gcr.io/${{ vars.GCP_PROJECT_ID }}/app-backend-dev:${{ github.sha }} > /dev/null 2>&1; then
            echo "exists=true" >> $GITHUB_OUTPUT
          else
            echo "exists=false" >> $GITHUB_OUTPUT
          fi

      - name: Build and push Docker image
        if: steps.check-image.outputs.exists == 'false'
        run: |
          cd backend
          docker build \
            -t gcr.io/${{ vars.GCP_PROJECT_ID }}/app-backend-dev:${{ github.sha }} .
          docker push gcr.io/${{ vars.GCP_PROJECT_ID }}/app-backend-dev:${{ github.sha }}

      - name: Deploy server to Cloud Run
        run: |
          gcloud run deploy app-backend-dev \
            --image gcr.io/${{ vars.GCP_PROJECT_ID }}/app-backend-dev:${{ github.sha }} \
            --platform managed \
            --region ${{ vars.GCP_REGION }} \
            --allow-unauthenticated \
            --port 8000 \
            --memory ${{ vars.BACKEND_MEMORY || '2Gi' }} \
            --cpu ${{ vars.BACKEND_CPU || '2' }} \
            --min-instances ${{ vars.BACKEND_MIN_INSTANCES || '0' }} \
            --max-instances ${{ vars.BACKEND_MAX_INSTANCES || '3' }} \
            --timeout 600 \
            --concurrency 100 \
            --add-cloudsql-instances ${{ vars.CLOUDSQL_INSTANCE_CONNECTION }} \
            --vpc-connector ${{ vars.VPC_CONNECTOR }} \
            --service-account ${{ vars.GCP_SA_NAME }} \
            --set-env-vars="ENVIRONMENT=development,\
              MODE=server,\
              POSTGRES_HOST=/cloudsql/${{ vars.CLOUDSQL_INSTANCE_CONNECTION }},\
              POSTGRES_USER=${{ vars.POSTGRES_USER }},\
              POSTGRES_PASSWORD=${{ vars.POSTGRES_PASSWORD }},\
              REDIS_URL=${{ vars.REDIS_URL }},\
              TEMPORAL_HOST=${{ vars.TEMPORAL_HOST }},\
              TEMPORAL_PORT=${{ vars.TEMPORAL_PORT }},\
              TEMPORAL_NAMESPACE=${{ vars.TEMPORAL_NAMESPACE }},\
              TEMPORAL_API_KEY=${{ vars.TEMPORAL_API_KEY }},\
              TEMPORAL_ENABLED=true,\
              JWT_SECRET_KEY=${{ vars.JWT_SECRET_KEY }},\
              OPENAI_API_KEY=${{ vars.OPENAI_API_KEY }},\
              ANTHROPIC_API_KEY=${{ vars.ANTHROPIC_API_KEY }},\
              FAL_KEY=${{ vars.FAL_KEY }},\
              GOOGLE_CLOUD_PROJECT=${{ vars.GOOGLE_CLOUD_PROJECT }},\
              GCS_BUCKET=${{ vars.GCS_BUCKET }}"
```

**Key patterns**:
- **Image caching**: Check if image exists with `docker manifest inspect` before building; skip build if SHA already pushed
- **MODE env var**: Set `MODE=server` to deploy as FastAPI server (same image could be deployed as `MODE=consumer` for Kafka consumer)
- **CloudSQL socket**: `--add-cloudsql-instances` + `POSTGRES_HOST=/cloudsql/{INSTANCE_CONNECTION}` for managed Postgres access
- **VPC connector**: `--vpc-connector` for private resource access (Redis, Kafka)
- **Secrets as env vars**: All credentials (`POSTGRES_PASSWORD`, `JWT_SECRET_KEY`, API keys) passed as `--set-env-vars`
- **Autoscaling**: `--min-instances 0` for scale-to-zero; `--max-instances 3` for cost control
- **Resource limits**: `--memory 2Gi`, `--cpu 2`, `--timeout 600` for request timeout

## Cert/Keytab Writing from Env Vars

**Example from a production service**:

```python
import base64
import os
import re
from pathlib import Path

CERT_DIR = Path("/tmp/kafka_certificates")

def _restore_pem(env_value: str) -> str:
    """Restore PEM file content from a space-separated env var.
    
    Cloud platforms expose secrets as single-line env vars; PEM files
    need newlines around -----BEGIN/END----- markers.
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
            # PEM body may be space-separated in env var
            rebuilt.extend(line.split())
    return '\n'.join(rebuilt) + '\n'

def _write_kafka_certificates() -> None:
    """Write Kafka certificate files from env-var secrets.
    
    Called at entrypoint startup before Kafka consumer starts.
    Converts env-var secrets to filesystem files with correct permissions.
    """
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
        os.chmod(path, 0o600)  # Secure permissions
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
```

**Why this pattern**:
- Cloud Run and k8s expose secrets as env vars (not mounted volumes)
- Kafka SASL_SSL and Kerberos libraries require file paths, not in-memory certs
- Solution: write env-var secrets to `/tmp/` with correct permissions at startup

**Security considerations**:
- Write to `/tmp/` (ephemeral, cleared on container restart)
- Set `0o600` permissions (owner read/write only)
- Print paths (for debugging) but never log cert contents
- Update env vars to point at generated files (so Kafka config can reference them)

## Secrets Hygiene Pattern

**Example from a production service**:

```python
def download_certificates():
    """Write API certs from env vars to filesystem."""
    public_certificate = loaded_config.API_PUBLIC_CERTIFICATE
    private_key = loaded_config.API_PRIVATE_KEY

    cert_directory = "/srv/app/certificates"
    public_cert_file = os.path.join(cert_directory, "api_public_cert.pem")
    private_key_file = os.path.join(cert_directory, "api_private_key.pem")

    os.makedirs(cert_directory, exist_ok=True)
    
    # Replace literal \n with actual newlines
    public_certificate = public_certificate.replace("\\n", "\n")
    private_key = private_key.replace("\\n", "\n")

    with open(public_cert_file, "w") as pub_file:
        pub_file.write(public_certificate)

    with open(private_key_file, "w") as private_file:
        private_file.write(private_key)
```

**Pattern**: PEM certs stored in env vars with `\n` literal (escaped newline); replace with actual `\n` at runtime.

**Why**: Some secret management systems escape newlines as `\n` literal when storing multi-line secrets in env vars.

## Docker Compose Secrets (Local Dev)

**Example from a production service**:

```yaml
services:
  api:
    env_file:
      - .env  # Load env vars from .env file
    environment:
      DB_HOST: app-db
      DB_PORT: 5432
      DB_USER: app
      DB_PASS: app  # Dummy credential for local dev
      DB_NAME: app

  db:
    environment:
      POSTGRES_PASSWORD: "app"  # Dummy password
      POSTGRES_USER: "app"
      POSTGRES_DB: "app"
```

**Pattern**: Use `.env` file for local dev secrets; never commit it (`.gitignore`). Use dummy/weak credentials for local dev (not production secrets).

## Health Checks in docker-compose

**Example from a production service**:

```yaml
db:
  healthcheck:
    test: pg_isready -U app
    interval: 2s
    timeout: 3s
    retries: 40

redis:
  healthcheck:
    test: redis-cli ping
    interval: 1s
    timeout: 3s
    retries: 50

kafka:
  healthcheck:
    test: kafka-topics.sh --list --bootstrap-server localhost:9092
    interval: 1s
    timeout: 3s
    retries: 30
```

**Pattern**: Use service-specific commands for health checks:
- Postgres: `pg_isready -U <user>`
- Redis: `redis-cli ping`
- Kafka: `kafka-topics.sh --list --bootstrap-server localhost:9092`

**Why**: Ensures services are fully ready before dependent services start (via `depends_on: condition: service_healthy`).

## API Path Versioning for Deployment Compatibility

**Convention**: Prefix all API routes with `/v1/`, `/v2/`, etc.

**Example** (from backend-repo-architecture skill):

```python
# app/main.py
app.include_router(users_router, prefix="/v1")
app.include_router(posts_router, prefix="/v1")
app.include_router(users_v2_router, prefix="/v2")
```

**Why**: Allows rolling deployments with backward compatibility:
- Deploy new version with `/v2/` endpoints
- Old clients continue using `/v1/` endpoints
- Gradually migrate clients to `/v2/`
- Deprecate and remove `/v1/` after migration window

**Deployment benefit**: Can deploy breaking changes without downtime (old and new versions coexist).

## Secrets Checklist

### Never commit
- `.env` files
- Keytabs, SSL certs, private keys
- Database passwords, API keys, JWT secrets
- Service account JSON files

### Always use env vars for
- Database credentials (`POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`)
- API keys (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `JWT_SECRET_KEY`)
- Cloud provider credentials (GCP service account, AWS access keys)
- Third-party service credentials (Temporal, Sentry, Redis)

### Base64-encode for binary secrets
- Keytabs: `base64.b64decode(env_var)`
- SSL certs (if binary): `base64.b64decode(env_var)`

### Escape newlines for multi-line secrets
- PEM certs: store with `\n` literal or space-separated; restore at runtime
- Private keys: store with `\n` literal; replace with `\n` at runtime

### File permissions
- Write certs/keytabs to `/tmp/` with `0o600` (owner read/write only)
- Never world-readable (`0o644`) for secrets

### Local dev vs production
- Use dummy credentials in docker-compose (weak passwords, localhost)
- Use secret managers (GCP Secret Manager, AWS Secrets Manager) in production
- Never mount production secrets in local dev environments
