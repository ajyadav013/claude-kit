# Cloud Run Deploy Flags and Patterns

Reference guide for `gcloud run deploy` flags commonly used in production deployments.

## Basic deployment command

```bash
gcloud run deploy <service-name> \
  --image <registry>/<image>:<tag> \
  --platform managed \
  --region <region>
```

## Authentication and access control

```bash
--allow-unauthenticated          # Public service (no auth required)
--no-allow-unauthenticated       # Private service (requires auth)
--service-account <email>        # Service account for the Cloud Run service
--ingress all                    # Accept traffic from internet
--ingress internal               # Only from VPC and other Cloud Run services
--ingress internal-and-cloud-load-balancing  # VPC + load balancer only
```

**Common pattern**: Use `--allow-unauthenticated` for frontend and public APIs, `--no-allow-unauthenticated` for workers and internal services.

## Resource limits

```bash
--memory <size>                  # Memory allocation (e.g., 512Mi, 2Gi, 8Gi)
--cpu <count>                    # CPU count (e.g., 1, 2, 4)
--timeout <seconds>              # Request timeout (default 300, max 3600)
--concurrency <n>                # Concurrent requests per instance (default 80)
```

**Common patterns**:
- Backend API: `--memory 2Gi --cpu 2 --timeout 600 --concurrency 100`
- Worker: `--memory 8Gi --cpu 4 --timeout 3600 --concurrency 1`
- Frontend: `--memory 512Mi --cpu 1 --timeout 300 --concurrency 80`

## Autoscaling

```bash
--min-instances <n>              # Minimum instances (0 = scale to zero)
--max-instances <n>              # Maximum instances
```

**Common patterns**:
- Production: `--min-instances 1 --max-instances 10` (avoid cold starts)
- Development: `--min-instances 0 --max-instances 3` (scale to zero to save costs)
- Worker: `--min-instances 1 --max-instances 10` (keep at least one running)

## VPC and database

```bash
--vpc-connector <name>                       # VPC connector for private network access
--add-cloudsql-instances <connection-name>   # Cloud SQL instance connection
```

**Cloud SQL connection format**: `project:region:instance` (e.g., `my-project:us-central1:my-db`)

**Common pattern**: Services that access Cloud SQL or private resources need both `--vpc-connector` and `--add-cloudsql-instances`.

## Environment variables

```bash
--set-env-vars="KEY1=value1,KEY2=value2,..."
```

**Common pattern**: Use line continuation for readability in GitHub Actions:

```bash
--set-env-vars="ENVIRONMENT=production,\
  MODE=server,\
  POSTGRES_HOST=/cloudsql/my-project:us-central1:my-db,\
  POSTGRES_USER=myuser,\
  POSTGRES_PASSWORD=mypassword,\
  POSTGRES_DB=mydb,\
  REDIS_URL=redis://...,\
  GOOGLE_CLOUD_PROJECT=my-project,\
  GCS_BUCKET=my-bucket,\
  LANGFUSE_PUBLIC_KEY=pk-...,\
  LANGFUSE_SECRET_KEY=sk-...,\
  LANGFUSE_HOST=https://...,\
  SENTRY_DSN=https://..."
```

## One-image-many-roles pattern

Deploy the same Docker image to multiple Cloud Run services (e.g., backend and worker) and differentiate behavior via `MODE` environment variable:

```bash
# Backend server
gcloud run deploy my-backend \
  --image registry.example.com/my-app:abc123 \
  --set-env-vars="MODE=server,..." \
  --port 8000 \
  --timeout 600

# Worker
gcloud run deploy my-worker \
  --image registry.example.com/my-app:abc123 \
  --set-env-vars="MODE=worker,..." \
  --timeout 3600 \
  --no-allow-unauthenticated
```

The application reads `MODE` at startup and starts the appropriate process (FastAPI server vs Temporal/Celery worker).

## Port configuration

```bash
--port <port>                    # Container port (e.g., 8000, 80, 3000)
```

**Common patterns**:
- Backend: `--port 8000` (FastAPI/Django/Express default)
- Frontend (Nginx): `--port 80`
- Next.js: `--port 3000`

## Cloud SQL socket path

When using `--add-cloudsql-instances`, the Cloud SQL proxy creates a Unix socket at `/cloudsql/<connection-name>`. Set `POSTGRES_HOST` or equivalent to this path:

```bash
--set-env-vars="POSTGRES_HOST=/cloudsql/my-project:us-central1:my-db,..."
```

## Example: Backend deployment

```bash
gcloud run deploy my-backend \
  --image us-docker.pkg.dev/my-project/my-repo/backend:abc123 \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --port 8000 \
  --memory 2Gi \
  --cpu 2 \
  --min-instances 1 \
  --max-instances 10 \
  --timeout 600 \
  --concurrency 100 \
  --add-cloudsql-instances my-project:us-central1:my-db \
  --vpc-connector my-vpc-connector \
  --service-account my-service-account@my-project.iam.gserviceaccount.com \
  --set-env-vars="ENVIRONMENT=production,MODE=server,POSTGRES_HOST=/cloudsql/my-project:us-central1:my-db,..." \
  --ingress all
```

## Example: Worker deployment (reusing backend image)

```bash
gcloud run deploy my-worker \
  --image us-docker.pkg.dev/my-project/my-repo/backend:abc123 \
  --platform managed \
  --region us-central1 \
  --no-allow-unauthenticated \
  --memory 8Gi \
  --cpu 4 \
  --min-instances 1 \
  --max-instances 10 \
  --timeout 3600 \
  --add-cloudsql-instances my-project:us-central1:my-db \
  --vpc-connector my-vpc-connector \
  --service-account my-service-account@my-project.iam.gserviceaccount.com \
  --set-env-vars="ENVIRONMENT=production,MODE=worker,POSTGRES_HOST=/cloudsql/my-project:us-central1:my-db,..." \
  --ingress all
```

## Example: Frontend deployment

```bash
gcloud run deploy my-frontend \
  --image us-docker.pkg.dev/my-project/my-repo/frontend:abc123 \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --port 80 \
  --memory 512Mi \
  --cpu 1 \
  --min-instances 1 \
  --max-instances 5 \
  --set-env-vars="BACKEND_URL=https://my-backend-xyz.run.app" \
  --ingress all
```

## Resource sizing guidelines

| Service Type | Memory | CPU | Timeout | Concurrency | Min Instances (Prod) | Max Instances |
|--------------|--------|-----|---------|-------------|----------------------|---------------|
| API Backend  | 2-4Gi  | 2   | 600s    | 100         | 1                    | 10            |
| Worker       | 4-8Gi  | 4   | 3600s   | 1           | 1                    | 10            |
| Frontend     | 512Mi  | 1   | 300s    | 80          | 1                    | 5             |

Adjust based on actual workload. Use Cloud Run metrics (CPU utilization, memory usage, request latency) to tune.
