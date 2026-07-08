# Compose skeletons — four full worked files

Deep-dive reference for the `docker-compose` skill. The conventions behind every block here are
explained in SKILL.md; these are the complete files to copy and adapt.

```yaml
# docker-compose.yml (base)
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

  zookeeper:
    image: "bitnami/zookeeper:3.7.1"
    hostname: "app-zookeeper"
    environment:
      ALLOW_ANONYMOUS_LOGIN: "yes"
      ZOO_LOG_LEVEL: "ERROR"
    healthcheck:
      test: zkServer.sh status
      interval: 1s
      timeout: 3s
      retries: 30

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

```yaml
# docker-compose.dev.yml
version: '3.9'

x-environment: &common-dev-env
  ENV: DEV
  POSTGRES_URL: postgresql://app:app@app-db:5432/app
  REDIS_URL: redis://app-redis:6379/0
  KAFKA_BROKERS: app-kafka:9092

services:
  server:
    build: .
    image: app:latest
    ports:
      - '8000:80'
      - '5678:5678'  # debugpy
    environment:
      <<: *common-dev-env
      MODE: server
      DEBUG_PORT: 5678
      RELOAD: "true"
    volumes:
      - .:/srv/app
      - $HOME/.config/gcloud:/root/.config/gcloud
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy

  consumer:
    image: app:latest
    ports:
      - '5679:5679'
    environment:
      <<: *common-dev-env
      MODE: consumer
      DEBUG_PORT: 5679
    volumes:
      - .:/srv/app
    depends_on:
      kafka:
        condition: service_healthy

  worker:
    image: app:latest
    ports:
      - '5680:5680'
    environment:
      <<: *common-dev-env
      MODE: worker
      WORKER_MODE: background_tasks
      DEBUG_PORT: 5680
    volumes:
      - .:/srv/app

  db:
    image: postgres:13.8-bullseye
    hostname: app-db
    ports:
      - '5432:5432'
    environment:
      POSTGRES_PASSWORD: "app"
      POSTGRES_USER: "app"
      POSTGRES_DB: "app"
    volumes:
      - db-data:/var/lib/postgresql/data
    healthcheck:
      test: pg_isready -U app
      interval: 2s
      timeout: 3s
      retries: 40

  redis:
    image: bitnami/redis:6.2.5
    hostname: "app-redis"
    ports:
      - '6379:6379'
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
    ports:
      - '9092:9092'
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

  zookeeper:
    image: "bitnami/zookeeper:3.7.1"
    hostname: "app-zookeeper"
    ports:
      - '2181:2181'
    environment:
      ALLOW_ANONYMOUS_LOGIN: "yes"
      ZOO_LOG_LEVEL: "ERROR"
    healthcheck:
      test: zkServer.sh status
      interval: 1s
      timeout: 3s
      retries: 30

volumes:
  db-data:
```

```yaml
# docker-compose.prod-test.yml
# Usage: docker-compose -f docker-compose.yml -f docker-compose.prod-test.yml up --build
# Simulates Cloud Run deployment locally

services:
  backend:
    build: ./backend
    ports:
      - "8000:8000"
    environment:
      ENVIRONMENT: production
      MODE: server
      POSTGRES_HOST: postgres
      POSTGRES_PORT: "5432"
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: app_db
      REDIS_HOST: redis
      REDIS_PORT: "6379"
      TEMPORAL_HOST: temporal
      TEMPORAL_PORT: "7233"
      TEMPORAL_ENABLED: "true"
      JWT_SECRET_KEY: "local-prod-test-secret-not-default"
      USE_MOCK_LLM: "true"
      DEBUG: "false"
    env_file:
      - path: ./backend/.env.secrets
        required: false
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy

  worker:
    build: ./backend
    environment:
      ENVIRONMENT: production
      MODE: worker
      POSTGRES_HOST: postgres
      REDIS_HOST: redis
      TEMPORAL_HOST: temporal
      TEMPORAL_ENABLED: "true"
      JWT_SECRET_KEY: "local-prod-test-secret-not-default"
      DEBUG: "false"
    depends_on:
      postgres:
        condition: service_healthy
      temporal:
        condition: service_started
    healthcheck:
      disable: true
```

```yaml
# docker-compose with profiles
services:
  backend:
    build: ./backend
    ports:
      - "8000:8000"
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy

  postgres:
    image: postgres:18
    environment:
      POSTGRES_USER: app
      POSTGRES_PASSWORD: app
      POSTGRES_DB: app_db
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U app -d app_db"]
      interval: 5s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 5

  # Optional infrastructure (activate with --profile kafka)
  kafka:
    image: bitnami/kafka:3.7
    profiles: ["kafka"]
    ports:
      - "9092:9092"
    environment:
      KAFKA_CFG_NODE_ID: 0
      KAFKA_CFG_PROCESS_ROLES: controller,broker
      KAFKA_CFG_CONTROLLER_QUORUM_VOTERS: 0@kafka:9093
      KAFKA_CFG_LISTENERS: PLAINTEXT://:9092,CONTROLLER://:9093
      KAFKA_CFG_ADVERTISED_LISTENERS: PLAINTEXT://kafka:9092

  # Optional monitoring stack (activate with --profile monitoring)
  prometheus:
    image: prom/prometheus:v2.52.0
    profiles: ["monitoring"]
    ports:
      - "9090:9090"
    volumes:
      - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml

  grafana:
    image: grafana/grafana-oss:11.0.0
    profiles: ["monitoring"]
    ports:
      - "3001:3000"
    depends_on:
      - prometheus

  # Optional Temporal (activate with --profile temporal)
  temporal:
    image: temporalio/auto-setup:1.24
    profiles: ["temporal"]
    ports:
      - "7233:7233"
    environment:
      DB: postgresql
      DB_PORT: 5432
      POSTGRES_USER: app
      POSTGRES_PWD: app
      POSTGRES_SEEDS: postgres
    depends_on:
      postgres:
        condition: service_healthy
```
