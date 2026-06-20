# Deployment Patterns

How services are deployed, containerized, and scaled across the reference repositories.

## Deployment modes

### Server-only

Simplest deployment: single Dockerfile, single process, runs FastAPI HTTP server only.

**Dockerfile CMD**:
```dockerfile
CMD ["gunicorn", "app.application:get_app()", \
     "--workers", "4", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--bind", "0.0.0.0:8000"]
```

**When to use**: Pure API service, no background workers, no Kafka consumers. Workers/consumers would be separate repos/deployments.

**Pros**: Simple, minimal configuration, easy to debug.

**Cons**: Needs separate deployments for any async tasks (Temporal workers, Kafka consumers).

---

### Multi-mode

Single Docker image deployed in multiple modes via `MODE` environment variable.

**Dockerfile CMD**:
```dockerfile
CMD ["python", "entrypoint.py"]
```

**Kubernetes deployment examples**:

**Server deployment**:
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: myservice-server
spec:
  replicas: 3
  template:
    spec:
      containers:
      - name: myservice
        image: myservice:latest
        env:
        - name: MODE
          value: "server"
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: myservice-secrets
              key: database-url
        ports:
        - containerPort: 8000
```

**Consumer deployment**:
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: myservice-consumer
spec:
  replicas: 2
  template:
    spec:
      containers:
      - name: myservice
        image: myservice:latest
        env:
        - name: MODE
          value: "consumer"
        - name: KAFKA_BOOTSTRAP_SERVERS
          value: "kafka:9092"
        - name: KAFKA_CONSUMER_GROUP
          value: "myservice-consumer"
```

**Temporal worker deployment**:
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: myservice-temporal-worker
spec:
  replicas: 2
  template:
    spec:
      containers:
      - name: myservice
        image: myservice:latest
        env:
        - name: MODE
          value: "temporal_worker"
        - name: WORKER_MODE
          value: "data_worker"
        - name: TEMPORAL_QUEUE
          value: "myservice-tasks"
```

**Cron job**:
```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: myservice-sync-data
spec:
  schedule: "0 * * * *"  # Every hour
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: myservice
            image: myservice:latest
            env:
            - name: MODE
              value: "cron"
            - name: CRON_JOB
              value: "sync_data"
          restartPolicy: OnFailure
```

**When to use**: Service needs background workers, Kafka consumers, Temporal workers, or cron jobs that share business logic with the API.

**Pros**: Single codebase, shared models/DAOs/config, easier to maintain consistency, atomic deploys.

**Cons**: Larger image size (includes all dependencies even if MODE only uses subset), harder to scale modes independently.

---

### Multi-deployment

Single codebase deployed as multiple server types with different router sets.

**Kubernetes deployments**:

**Public server** (customer-facing):
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: myservice-public
spec:
  replicas: 5
  template:
    spec:
      containers:
      - name: myservice
        image: myservice:latest
        env:
        - name: MODE
          value: "server"
        - name: SERVER_TYPE
          value: "public"
```

**Internal server** (internal tools):
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: myservice-internal
spec:
  replicas: 2
  template:
    spec:
      containers:
      - name: myservice
        image: myservice:latest
        env:
        - name: MODE
          value: "server"
        - name: SERVER_TYPE
          value: "internal"
```

**Platform server** (third-party integrations):
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: myservice-platform
spec:
  replicas: 3
  template:
    spec:
      containers:
      - name: myservice
        image: myservice:latest
        env:
        - name: MODE
          value: "server"
        - name: SERVER_TYPE
          value: "platform"
```

**Webhook server** (inbound webhooks from partners):
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: myservice-webhook
spec:
  replicas: 2
  template:
    spec:
      containers:
      - name: myservice
        image: myservice:latest
        env:
        - name: MODE
          value: "server"
        - name: SERVER_TYPE
          value: "webhook"
```

**Ingress routing**:
```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: myservice
spec:
  rules:
  - host: api.example.com
    http:
      paths:
      - path: /service/public/product/feature
        pathType: Prefix
        backend:
          service:
            name: myservice-public
            port:
              number: 8000
      - path: /service/internal/product/feature
        pathType: Prefix
        backend:
          service:
            name: myservice-internal
            port:
              number: 8000
      - path: /service/platform/product/feature
        pathType: Prefix
        backend:
          service:
            name: myservice-platform
            port:
              number: 8000
      - path: /service/webhook/product/feature
        pathType: Prefix
        backend:
          service:
            name: myservice-webhook
            port:
              number: 8000
```

**When to use**: Single service with multiple audiences (public/internal/partner), different authorization/rate-limiting/router sets per audience, want to scale each independently.

**Pros**: Single codebase, shared models/DAOs/config, independent scaling per server type, fine-grained access control.

**Cons**: Complex routing logic, must test all SERVER_TYPE variants, risk of accidental route exposure.

---

### Monorepo

Multiple apps/ (services) in one repo, each with its own Dockerfile.

**Directory structure**:
```
myservice/
├── apps/
│   ├── api/Dockerfile
│   ├── orchestrator/Dockerfile
│   ├── node_workers/Dockerfile
│   └── signal_forwarder/Dockerfile
└── packages/
    ├── common/
    ├── db/
    └── sdk/
```

**Build context** (each app/):
```dockerfile
# apps/api/Dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY packages/ ./packages/
COPY apps/api/ ./apps/api/
RUN pip install -e ./packages/common -e ./packages/db -e ./apps/api
CMD ["python", "apps/api/entrypoint.py"]
```

**When to use**: Multiple services sharing substantial common code (models, DAOs, utilities), coordinated releases, single source of truth.

**Pros**: Shared code without duplication, easier refactoring across services, consistent versioning.

**Cons**: Complex build pipeline, must coordinate changes across services, larger repo, harder to scale teams.

---

## Scaling considerations

| Pattern | Horizontal scaling | Vertical scaling | Independent scaling |
|---------|-------------------|------------------|---------------------|
| **Server-only** | Easy (replicas) | Easy (resources) | N/A (single mode) |
| **Multi-mode** | Easy per MODE | Easy per MODE | Excellent (scale each MODE independently) |
| **Multi-deployment** | Easy per SERVER_TYPE | Easy per SERVER_TYPE | Excellent (scale each SERVER_TYPE independently) |
| **Monorepo** | Easy per app/ | Easy per app/ | Excellent (scale each app independently) |

---

## Health checks

All patterns expose standard health check endpoints:

**Liveness probe** (`/_healthz`):
```python
@router.get("/_healthz")
async def healthz():
    return {"status": "ok"}
```

**Readiness probe** (`/_readyz`):
```python
@router.get("/_readyz")
async def readyz(connection_handler = Depends(get_connection_handler)):
    # Check database connectivity
    await connection_handler.session.execute(text("SELECT 1"))
    # Check Redis connectivity
    await connection_handler.redis.ping()
    return {"status": "ready"}
```

**Kubernetes probes**:
```yaml
livenessProbe:
  httpGet:
    path: /_healthz
    port: 8000
  initialDelaySeconds: 10
  periodSeconds: 5

readinessProbe:
  httpGet:
    path: /_readyz
    port: 8000
  initialDelaySeconds: 5
  periodSeconds: 3
```

---

## Graceful shutdown

All patterns use FastAPI lifespan context manager for graceful startup/shutdown.

**Lifespan pattern**:
```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Startup
    setup_logging()
    ConnectionManager()  # init singleton
    
    yield
    
    # Shutdown: close all connections before process exits
    await ConnectionManager().close_connections()
    shutdown_telemetry()
```

**Kubernetes termination grace period**:
```yaml
spec:
  template:
    spec:
      terminationGracePeriodSeconds: 30  # Wait up to 30s for graceful shutdown
      containers:
      - name: myservice
        lifecycle:
          preStop:
            exec:
              command: ["/bin/sh", "-c", "sleep 5"]  # Give load balancer time to deregister
```

---

## Best practices

1. **Always include health checks**: Liveness + readiness probes prevent traffic to unhealthy pods.
2. **Graceful shutdown**: Use lifespan context manager, close connections before exit, respect termination grace period.
3. **Separate secrets from config**: Use k8s Secrets or external secret management (Vault, AWS Secrets Manager), never commit secrets to git.
4. **Resource limits**: Set CPU/memory requests and limits to prevent noisy neighbor issues.
5. **Horizontal pod autoscaling**: Scale on CPU, memory, or custom metrics (requests/sec, queue depth).
6. **Rolling updates**: Use deployment strategy `RollingUpdate` with `maxSurge: 1, maxUnavailable: 0` for zero-downtime deploys.
7. **Monitoring**: Prometheus metrics endpoint (`/metrics`), structured logs (JSON), distributed tracing (OpenTelemetry).
