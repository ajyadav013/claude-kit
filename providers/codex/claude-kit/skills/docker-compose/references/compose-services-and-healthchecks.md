# Compose Services and Health Checks

Health check commands for infrastructure services, depends_on patterns, and migration service setup.

## Health Check Patterns

### Postgres

**Basic pattern**:
```yaml
db:
  image: postgres:13.8-bullseye
  healthcheck:
    test: pg_isready -U username
    interval: 2s
    timeout: 3s
    retries: 40
```

**Array syntax with database name**:
```yaml
postgres:
  image: postgres:18
  healthcheck:
    test: ["CMD-SHELL", "pg_isready -U app -d app_db"]
    interval: 5s
    timeout: 5s
    retries: 5
```

**Key points**:
- `pg_isready` is built into postgres images
- `-U username` matches `POSTGRES_USER` env var
- `-d dbname` optionally checks specific database
- `interval: 2s` provides fast feedback for local dev (production can use 5s-10s)
- `retries: 40` allows 80 seconds total startup time (accommodates slow machines)

### Redis

**String test syntax**:
```yaml
redis:
  image: bitnami/redis:6.2.5
  healthcheck:
    test: redis-cli ping
    interval: 1s
    timeout: 3s
    retries: 50
```

**Array test syntax**:
```yaml
redis:
  image: redis:7-alpine
  healthcheck:
    test: ["CMD", "redis-cli", "ping"]
    interval: 5s
    timeout: 5s
    retries: 5
```

**Key points**:
- `redis-cli ping` returns `PONG` when ready
- Array syntax `["CMD", ...]` is more explicit but equivalent to string syntax for simple commands
- `interval: 1s` provides immediate feedback; increase to 5s for production

### Kafka

**With Zookeeper**:
```yaml
kafka:
  image: bitnami/kafka:3.2.0
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
```

**KRaft mode (Kafka 3.7+, no Zookeeper)**:
```yaml
kafka:
  image: bitnami/kafka:3.7
  environment:
    KAFKA_CFG_NODE_ID: 0
    KAFKA_CFG_PROCESS_ROLES: controller,broker
    KAFKA_CFG_CONTROLLER_QUORUM_VOTERS: 0@kafka:9093
    KAFKA_CFG_LISTENERS: PLAINTEXT://:9092,CONTROLLER://:9093
    KAFKA_CFG_ADVERTISED_LISTENERS: PLAINTEXT://kafka:9092
    KAFKA_CFG_LISTENER_SECURITY_PROTOCOL_MAP: CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT
    KAFKA_CFG_CONTROLLER_LISTENER_NAMES: CONTROLLER
    KAFKA_CFG_AUTO_CREATE_TOPICS_ENABLE: "true"
```

**Key points**:
- `kafka-topics.sh --list` confirms broker is accepting connections
- Kafka startup is slow (15-30 seconds); `retries: 30` + `interval: 1s` allows 30s total
- KRaft mode removes Zookeeper dependency; simpler for local dev

### Zookeeper

```yaml
zookeeper:
  image: bitnami/zookeeper:3.7.1
  environment:
    ALLOW_ANONYMOUS_LOGIN: "yes"
    ZOO_LOG_LEVEL: "ERROR"
  healthcheck:
    test: zkServer.sh status
    interval: 1s
    timeout: 3s
    retries: 30
```

**Key points**:
- `zkServer.sh status` checks Zookeeper server status
- `ZOO_LOG_LEVEL: "ERROR"` reduces log noise for local dev

## Conditional Startup with depends_on

**Basic pattern**:
```yaml
services:
  api:
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
      kafka:
        condition: service_healthy
```

**Why**: Without `condition: service_healthy`, docker-compose starts services in dependency order but doesn't wait for them to be ready. The API container starts, tries to connect to postgres, and fails because postgres is still initializing.

**service_started vs service_healthy**:
- `condition: service_started` — waits for container to start (default behavior)
- `condition: service_healthy` — waits for health check to pass (requires `healthcheck` defined on dependency)

**Example failure without health checks**:
```
api_1  | sqlalchemy.exc.OperationalError: (psycopg2.OperationalError) could not connect to server
api_1  | postgres is starting up
```

**Fixed with health checks**:
```yaml
db:
  healthcheck:
    test: pg_isready -U app
    interval: 2s
api:
  depends_on:
    db:
      condition: service_healthy
```

Result: API waits until postgres is ready, connects successfully.

## Migration Service Pattern

**One-shot migrator service**:
```yaml
services:
  migrator:
    image: app:${APP_VERSION:-latest}
    restart: "no"
    command: alembic upgrade head
    environment:
      DB_HOST: app-db
      DB_PORT: 5432
      DB_USER: app
      DB_PASS: app
      DB_NAME: app
    depends_on:
      db:
        condition: service_healthy
```

**Key points**:
- `restart: "no"` ensures migrator runs once and exits (never restarts on failure)
- `command: alembic upgrade head` overrides Dockerfile CMD to run migrations
- `depends_on: db: condition: service_healthy` ensures postgres is ready before migrations run
- Reuses the same application image (`app:latest`) — no separate Dockerfile needed

**Flyway alternative**:
```yaml
migrator:
  image: app:latest
  restart: "no"
  command: flyway migrate
  environment:
    FLYWAY_URL: jdbc:postgresql://app-db:5432/app
    FLYWAY_USER: app
    FLYWAY_PASSWORD: app
```

**Why this pattern**:
- Migrations run before the API starts (via depends_on)
- Failures are visible (migrator exits with non-zero code)
- No need to run migrations in entrypoint.py (separates concerns)
- Easy to run migrations separately: `docker-compose up migrator`

## Full Service Orchestration Example

```yaml
version: '3.9'

services:
  api:
    build: .
    image: app:latest
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
      kafka:
        condition: service_healthy
    environment:
      DB_HOST: app-db
      REDIS_HOST: app-redis
      KAFKA_BROKERS: app-kafka:9092

  db:
    image: postgres:13.8-bullseye
    hostname: app-db
    environment:
      POSTGRES_USER: app
      POSTGRES_PASSWORD: app
      POSTGRES_DB: app
    volumes:
      - db-data:/var/lib/postgresql/data
    healthcheck:
      test: pg_isready -U app
      interval: 2s
      timeout: 3s
      retries: 40

  migrator:
    image: app:latest
    restart: "no"
    command: alembic upgrade head
    environment:
      DB_HOST: app-db
      DB_USER: app
      DB_PASS: app
      DB_NAME: app
    depends_on:
      db:
        condition: service_healthy

  redis:
    image: bitnami/redis:6.2.5
    hostname: app-redis
    environment:
      ALLOW_EMPTY_PASSWORD: "yes"
    healthcheck:
      test: redis-cli ping
      interval: 1s
      timeout: 3s
      retries: 50

  zookeeper:
    image: bitnami/zookeeper:3.7.1
    hostname: app-zookeeper
    environment:
      ALLOW_ANONYMOUS_LOGIN: "yes"
      ZOO_LOG_LEVEL: "ERROR"
    healthcheck:
      test: zkServer.sh status
      interval: 1s
      timeout: 3s
      retries: 30

  kafka:
    image: bitnami/kafka:3.2.0
    hostname: app-kafka
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
  db-data:
```

**Startup order**:
1. db, redis, zookeeper start in parallel
2. Health checks run until all pass (2-30 seconds)
3. kafka starts (depends on zookeeper health)
4. kafka health check passes
5. migrator runs (depends on db health)
6. api starts (depends on db, redis, kafka health)

**Result**: No connection errors, clean startup, reproducible across machines.
