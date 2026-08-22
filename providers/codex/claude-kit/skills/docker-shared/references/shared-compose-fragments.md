# Shared Compose Fragments

Reusing configuration across services in docker-compose using YAML anchors, extension fields, external networks, and external volumes.

## YAML Anchors and Aliases

**Pattern**: Define a block once with `x-<name>: &anchor-name`, then reference it with `<<: *anchor-name`.

**Use cases**: Shared environment variables, logging configuration, resource limits, restart policies, volume mounts.

### Example: Shared Environment Variables

```yaml
version: '3.9'

# Define shared environment variables once
x-common-env: &common-env
  DATABASE_URL: postgresql://user:pass@db:5432/app
  REDIS_URL: redis://redis:6379/0
  KAFKA_BROKERS: kafka:9092
  LOG_LEVEL: INFO
  GOOGLE_CLOUD_PROJECT: project-dev

services:
  api:
    image: app:latest
    environment:
      <<: *common-env
      MODE: server
    ports:
      - '8000:80'

  worker:
    image: app:latest
    environment:
      <<: *common-env
      MODE: worker
      WORKER_MODE: background_tasks

  consumer:
    image: app:latest
    environment:
      <<: *common-env
      MODE: consumer
```

**Why this works**:
- Environment variables shared across multiple services (DB URL, Redis URL, Kafka brokers) are defined once
- Each service adds service-specific env vars (`MODE`, `WORKER_MODE`) after merging the common block
- Changes to shared env vars (e.g., DB password) only need to be updated in one place

### Example: Shared Resource Limits

```yaml
version: '3.9'

# Define shared resource limits
x-resource-limits: &resource-limits
  deploy:
    resources:
      limits:
        memory: 2G
        cpus: '1.0'
      reservations:
        memory: 512M
        cpus: '0.5'

services:
  api:
    image: app:latest
    <<: *resource-limits
    ports:
      - '8000:80'

  worker:
    image: app:latest
    <<: *resource-limits
```

### Example: Shared Logging Configuration

```yaml
version: '3.9'

# Define shared logging
x-logging: &default-logging
  driver: json-file
  options:
    max-size: "10m"
    max-file: "3"

services:
  api:
    image: app:latest
    logging: *default-logging

  worker:
    image: app:latest
    logging: *default-logging

  db:
    image: postgres:13
    logging: *default-logging
```

### Example: Shared Volume Mounts (Development)

```yaml
version: '3.9'

# Define shared volume mounts for local dev
x-dev-volumes: &dev-volumes
  volumes:
    - ./app:/srv/app
    - $HOME/.config/gcloud:/root/.config/gcloud:ro

services:
  api:
    image: app:latest
    <<: *dev-volumes

  worker:
    image: app:latest
    <<: *dev-volumes
```

## x- Extension Fields

**What**: Top-level keys prefixed with `x-` are ignored by Docker Compose but can hold reusable fragments. This is the standard way to define anchors.

**Example**:

```yaml
version: '3.9'

# Extension fields (ignored by Docker Compose, used for anchors)
x-common-env: &common-env
  DATABASE_URL: postgresql://user:pass@db:5432/app
  REDIS_URL: redis://redis:6379/0

x-resource-limits: &resource-limits
  deploy:
    resources:
      limits:
        memory: 2G

services:
  api:
    image: app:latest
    environment:
      <<: *common-env
      MODE: server
    <<: *resource-limits
```

## External Networks

**Pattern**: Use `external: true` to reference a Docker network created outside the compose file.

**Use case**: Share a network across multiple compose projects (e.g., a shared Kafka cluster, Redis instance, or monitoring stack).

**Example**:

```yaml
version: '3.9'

services:
  api:
    image: app:latest
    networks:
      - app-network

  worker:
    image: app:latest
    networks:
      - app-network

networks:
  app-network:
    external: true
    name: prod-network  # Must already exist
```

**Create the network externally**:

```bash
# Create the network once (before docker-compose up)
docker network create prod-network

# Now all services can connect to it
docker-compose up
```

**Why this works**:
- Multiple compose projects can reference the same `prod-network`
- Services from different compose files can communicate (e.g., app A can reach Kafka from compose file B)
- Useful for local dev where one compose file manages infrastructure (Kafka, Redis, Postgres) and other compose files manage application services

### Real-World Example (Genericized)

From production services:

```yaml
# docker-compose.yml (service A)
version: '3.4'

services:
  api:
    image: serviceA:latest
    networks:
      - shared-infra

networks:
  shared-infra:
    external: true
    name: local-infra-network
```

```yaml
# docker-compose.yml (service B, different repo)
version: '3.4'

services:
  api:
    image: serviceB:latest
    networks:
      - shared-infra

networks:
  shared-infra:
    external: true
    name: local-infra-network
```

```bash
# Infrastructure compose (Kafka, Redis, Postgres)
# docker-compose.infra.yml
version: '3.4'

services:
  kafka:
    image: bitnami/kafka:3.2.0
    networks:
      - local-infra-network

  redis:
    image: redis:7-alpine
    networks:
      - local-infra-network

networks:
  local-infra-network:
    driver: bridge
```

**Workflow**:

```bash
# 1. Start infrastructure
docker-compose -f docker-compose.infra.yml up -d

# 2. Start service A (in its repo)
cd /path/to/serviceA
docker-compose up -d

# 3. Start service B (in its repo)
cd /path/to/serviceB
docker-compose up -d

# All services can now reach Kafka and Redis via the shared network
```

## External Volumes

**Pattern**: Use `external: true` to reference a Docker volume created outside the compose file.

**Use case**: Share persistent data across multiple compose projects (e.g., a shared database volume, a shared NFS mount).

**Example**:

```yaml
version: '3.9'

services:
  api:
    image: app:latest
    volumes:
      - shared-data:/data

volumes:
  shared-data:
    external: true
    name: prod-shared-data  # Must already exist
```

**Create the volume externally**:

```bash
# Create the volume once
docker volume create prod-shared-data

# Now all services can mount it
docker-compose up
```

### NFS Volume Example (Genericized)

From production services (test automation with shared test reports):

```yaml
version: '3.8'

services:
  test-api:
    image: test-automation:latest
    volumes:
      - ./logs:/srv/test_automation/logs
      - ./screenshots:/srv/test_automation/screenshots
      - nfs-test-reports:/mnt/nfs/test-reports

volumes:
  nfs-test-reports:
    driver: local
    driver_opts:
      type: nfs
      o: addr=nfs-server.example.com,rw
      device: ":/export/test-reports"
```

**Why this works**:
- Multiple test runners can write to the same NFS-backed volume
- Test reports are aggregated in one place
- The NFS server is managed externally (outside Docker Compose)

## Service Extends (Deprecated, Legacy Pattern)

**Note**: `extends` is deprecated in Compose v3+ but still appears in some production codebases.

**Pattern**: Inherit configuration from another service in the same file or a different file.

**Example**:

```yaml
# base-compose.yml
version: '3.9'

services:
  base-service:
    image: app:latest
    environment:
      LOG_LEVEL: INFO
    restart: unless-stopped
```

```yaml
# docker-compose.yml
version: '3.9'

services:
  api:
    extends:
      file: base-compose.yml
      service: base-service
    ports:
      - '8000:80'
    environment:
      MODE: server
```

**Recommendation**: Prefer YAML anchors for same-file reuse; use `extends` only for cross-file inheritance (rare).

## Compose Include (Compose v2.20+)

**Pattern**: Import entire compose files as fragments.

**Use case**: Split a monolithic compose file into smaller files (e.g., `docker-compose.db.yml`, `docker-compose.monitoring.yml`).

**Example**:

```yaml
# docker-compose.yml
version: '3.9'

include:
  - path: ./compose/docker-compose.db.yml
  - path: ./compose/docker-compose.monitoring.yml

services:
  api:
    image: app:latest
    depends_on:
      - db  # Defined in docker-compose.db.yml
      - prometheus  # Defined in docker-compose.monitoring.yml
```

```yaml
# compose/docker-compose.db.yml
services:
  db:
    image: postgres:13
    environment:
      POSTGRES_USER: user
      POSTGRES_PASSWORD: pass
```

```yaml
# compose/docker-compose.monitoring.yml
services:
  prometheus:
    image: prom/prometheus:latest
    ports:
      - '9090:9090'
```

**Why this works**:
- Modularize large compose files
- Share common infrastructure (DB, monitoring) across multiple projects
- Keep the main compose file focused on application services

## Real-World Example: One Image, Many Containers

From production services (genericized):

```yaml
version: '3.4'

# Shared environment variables
x-environment: &common-environment-variables
  ENV: DEV
  POSTGRES_URL: postgresql://admin:pass@postgres:5432/app_db
  KAFKA_BROKERS: kafka:29092
  REDIS_URL: redis://redis:6379/9?decode_responses=true
  GOOGLE_CLOUD_PROJECT: project-dev

services:
  # API server
  app-server:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: app-server
    image: app:latest
    ports:
      - '8081:80'
      - '5679:5679'
    environment:
      <<: *common-environment-variables
      MODE: server
      DEBUG_PORT: 5679
    volumes:
      - .:/srv/app
      - $HOME/.config/gcloud:/root/.config/gcloud
    networks:
      - app-net

  # Background worker
  db-events-worker:
    image: app:latest
    container_name: db-events-worker
    ports:
      - '5680:5680'
    environment:
      <<: *common-environment-variables
      MODE: worker
      WORKER_MODE: db_events_publisher
      DEBUG_PORT: 5680
    volumes:
      - .:/srv/app
    networks:
      - app-net

  # Kafka consumer
  audit-consumer:
    image: app:latest
    container_name: audit-consumer
    ports:
      - '5681:5681'
    environment:
      <<: *common-environment-variables
      MODE: consumer
      CONSUMER_NAME: audit_consumer
      DEBUG_PORT: 5681
    volumes:
      - .:/srv/app
    networks:
      - app-net

  # Scheduled cron job
  scheduled-job:
    image: app:latest
    container_name: scheduled-job
    ports:
      - '5683:5683'
    environment:
      <<: *common-environment-variables
      MODE: cron
      CRON_JOB: daily_sync
      DEBUG_PORT: 5683
    volumes:
      - .:/srv/app
    networks:
      - app-net

networks:
  app-net:
    external: true
    name: local-infra-network
```

**Key features**:
- YAML anchor `x-environment: &common-environment-variables` defines shared env once
- Each service references with `<<: *common-environment-variables`
- Same `image: app:latest` used for server, worker, consumer, cron
- Only `MODE`, `WORKER_MODE`, `CONSUMER_NAME`, `CRON_JOB` differ
- Unique debug ports (5679, 5680, 5681, 5683) for debugpy attachment
- Volume mount `.:/srv/app` enables hot reload
- External network `local-infra-network` allows cross-repo service communication
