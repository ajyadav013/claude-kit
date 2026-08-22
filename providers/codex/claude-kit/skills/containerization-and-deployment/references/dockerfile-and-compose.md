# Dockerfile and Docker Compose Patterns

Multi-stage builds, base image selection, dependency caching, and docker-compose service orchestration.

## Multi-Stage Dockerfile (Alpine Pattern)

**Example from a production service**:

```dockerfile
ARG PYTHON_VERSION=3.10.15-alpine3.20

# Builder stage
FROM python:${PYTHON_VERSION} AS builder

ENV PYTHONUNBUFFERED=1

RUN apk update && apk upgrade && \
    apk add --no-cache curl openssh git librdkafka-dev g++ && \
    rm -rf /var/cache/apk/*

WORKDIR /srv/app

COPY ./requirements/requirements.txt .

# Create virtual environment in builder
RUN python -m venv /opt/venv
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

RUN pip install --upgrade --no-cache-dir pip wheel && \
    pip install --upgrade --no-cache-dir setuptools && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

# Capture git SHA before removing .git
RUN git rev-parse HEAD > gitsha && rm -rf .git

# Runtime stage
FROM python:${PYTHON_VERSION}

ENV PYTHONUNBUFFERED=1

RUN apk update && apk upgrade && \
    apk add --no-cache vim librdkafka-dev && \
    rm -rf /var/cache/apk/*

WORKDIR /srv/app
COPY --from=builder /srv/app .
COPY --from=builder /opt/venv /opt/venv

ENV VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

EXPOSE 80

RUN chmod +x ci-test.sh && \
    mkdir -p /var/log/app && chmod 777 /var/log/app

ENTRYPOINT ["python", "entrypoint.py"]
```

**Key features**:
- Builder stage installs build tools (`g++`, `git`, `openssh`) and compiles dependencies
- Runtime stage only includes runtime libs (`librdkafka-dev`) and the compiled virtual environment
- `--no-cache-dir` reduces image size by skipping pip cache
- `git rev-parse HEAD > gitsha && rm -rf .git` captures commit SHA for versioning, then removes .git to save space
- Virtual environment isolated in `/opt/venv` for clean separation

## Slim Dockerfile Pattern

**Example from a production service**:

```dockerfile
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir ".[prod]"

COPY . .
ENV PYTHONPATH=/app
ENV WEB_CONCURRENCY=4

EXPOSE 8000
CMD ["gunicorn", "app.application:get_app()", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--workers", "4", \
     "--bind", "0.0.0.0:8000", \
     "--timeout", "120", \
     "--graceful-timeout", "30", \
     "--access-logfile", "-"]
```

**Key features**:
- Single-stage Dockerfile (simpler, but larger final image)
- Uses `python:3.12-slim` for broader library compatibility (vs alpine)
- Installs from `pyproject.toml` with extras `[prod]`
- Runs gunicorn with uvicorn workers (ASGI server for FastAPI)
- `--access-logfile -` sends logs to stdout for Docker logging

## Docker Compose with Health Checks

**Example from a production service**:

```yaml
version: '3.9'

services:
  api:
    build:
      context: .
      dockerfile: ./deploy/Dockerfile
    image: app:${APP_VERSION:-latest}
    restart: always
    env_file:
      - .env
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
      kafka:
        condition: service_healthy
    environment:
      APP_HOST: 0.0.0.0
      DB_HOST: app-db
      DB_PORT: 5432
      DB_USER: app
      DB_PASS: app
      DB_NAME: app
      KAFKA_BOOTSTRAP_SERVERS: '["app-kafka:9092"]'

  db:
    image: postgres:13.8-bullseye
    hostname: app-db
    environment:
      POSTGRES_PASSWORD: "app"
      POSTGRES_USER: "app"
      POSTGRES_DB: "app"
    volumes:
      - app-db-data:/var/lib/postgresql/data
    restart: always
    healthcheck:
      test: pg_isready -U app
      interval: 2s
      timeout: 3s
      retries: 40

  redis:
    image: bitnami/redis:6.2.5
    hostname: "app-redis"
    restart: always
    environment:
      ALLOW_EMPTY_PASSWORD: "yes"
    healthcheck:
      test: redis-cli ping
      interval: 1s
      timeout: 3s
      retries: 50

  kafka:
    image: "bitnami/kafka:3.2.0"
    hostname: "app-kafka"
    environment:
      KAFKA_BROKER_ID: "1"
      ALLOW_PLAINTEXT_LISTENER: "yes"
      KAFKA_CFG_LISTENERS: "PLAINTEXT://0.0.0.0:9092"
      KAFKA_CFG_ADVERTISED_LISTENERS: "PLAINTEXT://app-kafka:9092"
      KAFKA_CFG_ZOOKEEPER_CONNECT: "app-zookeeper:2181"
    healthcheck:
      test: kafka-topics.sh --list --bootstrap-server localhost:9092
      interval: 1s
      timeout: 3s
      retries: 30
    depends_on:
      zookeeper:
        condition: service_healthy

volumes:
  app-db-data:
    name: app-db-data
```

**Key patterns**:
- `depends_on` with `condition: service_healthy` ensures postgres/redis/kafka are ready before starting the API
- Health checks use service-specific commands (`pg_isready`, `redis-cli ping`, `kafka-topics.sh --list`)
- Named volumes for persistent data (`app-db-data`)
- Hostnames match service names for DNS resolution within the Docker network

## One Image, Many Containers Pattern

**Example from a production service**:

```yaml
version: '3.4'

x-environment: &common-environment-variables
  ENV: DEV
  POSTGRES_READ_WRITE: postgresql://admin:<REDACTED>@app-postgres:5432/app_db
  KAFKA_BROKERS: kafka:29092
  REDIS_READ_WRITE: redis://app-redis:6379/9?decode_responses=true
  GOOGLE_CLOUD_PROJECT: "project-non-prod"

services:
  app-server:
    build:
      context: ..
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
      - ..:/srv/app
      - $HOME/.config/gcloud:/root/.config/gcloud

  db-events-worker:
    image: app:latest  # Reuse the same image
    container_name: db-events-worker
    ports:
      - '5680:5680'
    environment:
      <<: *common-environment-variables
      MODE: worker
      WORKER_MODE: db_events_publisher
      DEBUG_PORT: 5680
    volumes:
      - ..:/srv/app

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
      - ..:/srv/app

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
      - ..:/srv/app

networks:
  appnet:
    external: true
    name: appnet
```

**Key patterns**:
- YAML anchor `x-environment: &common-environment-variables` defines shared env once
- Each service references with `<<: *common-environment-variables`
- Same `image: app:latest` used for server, worker, consumer, cron
- Only `MODE`, `WORKER_MODE`, `CONSUMER_NAME`, `CRON_JOB` env vars differ
- Unique debug ports (5679, 5680, 5681, 5683) per container for debugpy attachment
- Volume mount `..:/srv/app` enables hot reload without rebuilding
- Mount `$HOME/.config/gcloud` for local GCP service account auth
- External network `appnet` allows cross-service communication (shared Kafka, Redis, Postgres)
