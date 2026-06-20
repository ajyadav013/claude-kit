# Makefile Developer Workflow

Makefile patterns for standardizing docker-compose and kubectl operations in local development and deployment.

## Composite docker-compose Commands

**Multiple config files**: Production services often split docker-compose into a base file (shared config) and an override file (local dev mounts, debug ports). Makefiles consolidate the invocation.

**Pattern**:

```makefile
COMPOSE_FILES := -f docker-compose.base.yml -f docker-compose.override.yml

up:
	docker-compose $(COMPOSE_FILES) up --build -d
	docker-compose $(COMPOSE_FILES) logs -f server

down:
	docker-compose $(COMPOSE_FILES) down

restart: down up
```

**Real-world variation**: Some projects use `DOCKER_BUILDKIT=1 COMPOSE_DOCKER_CLI_BUILD=1` env vars for BuildKit; the Makefile wraps this complexity.

```makefile
up:
	DOCKER_BUILDKIT=1 COMPOSE_DOCKER_CLI_BUILD=1 \
		docker-compose -f docker-compose.shared.yml up --build -d
	DOCKER_BUILDKIT=1 COMPOSE_DOCKER_CLI_BUILD=1 \
		docker-compose -f docker-compose.shared.yml -f docker-compose.yml up --build -d
	docker-compose -f docker-compose.shared.yml -f docker-compose.yml logs -f server
```

## Shell Access Shortcuts

**Container exec targets**: Instead of `docker-compose exec <service-name> /bin/bash`, developers run `make enter` or `make enter-worker`.

```makefile
enter:
	docker-compose $(COMPOSE_FILES) exec server /bin/bash

enter-worker:
	docker-compose $(COMPOSE_FILES) exec worker /bin/bash

enter-db:
	docker-compose $(COMPOSE_FILES) exec db psql -U user -d dbname
```

**Why**: Container service names vary by project; the Makefile documents the canonical names and shell commands.

## Log Tailing Targets

**Service-specific logs**: Multi-container compose setups interleave logs; developers need to filter to one service.

```makefile
logs-server:
	docker-compose $(COMPOSE_FILES) logs -f server

logs-worker:
	docker-compose $(COMPOSE_FILES) logs -f worker

logs-db:
	docker-compose $(COMPOSE_FILES) logs -f db

logs-all:
	docker-compose $(COMPOSE_FILES) logs -f
```

**-f flag**: Follow mode; logs tail in real-time.

## Build and Deploy Targets

**Docker build**: Wrap `docker build` with project-specific image tags.

```makefile
build:
	docker build -t app:latest .

build-prod:
	docker build -t gcr.io/my-project/app:$(shell git rev-parse HEAD) .
```

**Kubernetes deploy**: Consolidate kubectl commands.

```makefile
k8s-deploy:
	kubectl apply -f k8s/

k8s-delete:
	kubectl delete -f k8s/

k8s-status:
	kubectl get pods -l app=myapp
	kubectl get services -l app=myapp
```

## Test and Lint Targets

**Backend tests**:

```makefile
test:
	pytest tests/ -v --cov=app --cov-report=html

test-unit:
	pytest tests/unit/ -x -q

test-api:
	pytest tests/api/ -v

test-integration:
	pytest tests/integration/ -v
```

**Linting and formatting**:

```makefile
lint:
	ruff check src tests
	mypy src

format:
	ruff format src tests
	black src tests
```

**Frontend tests** (monorepo):

```makefile
test-frontend:
	cd frontend && npm run test:run

test-e2e:
	npx playwright test
```

## Help Target

**Self-documenting Makefile**: A `help` target lists all available commands with descriptions.

```makefile
.PHONY: help

help:
	@echo "Available commands:"
	@echo "  make up            - Start all services"
	@echo "  make down          - Stop all services"
	@echo "  make restart       - Restart all services"
	@echo "  make enter         - Shell into server container"
	@echo "  make enter-worker  - Shell into worker container"
	@echo "  make logs-server   - Follow server logs"
	@echo "  make logs-worker   - Follow worker logs"
	@echo "  make test          - Run all tests"
	@echo "  make lint          - Run linting"
	@echo "  make k8s-deploy    - Deploy to Kubernetes"
```

**Default target**: Make `help` the default when running `make` with no arguments.

```makefile
.DEFAULT_GOAL := help
```

## .PHONY Declarations

**Always declare non-file targets as .PHONY**: Prevents conflicts if a file with the same name exists.

```makefile
.PHONY: help up down restart enter enter-worker logs-server logs-worker \
        build test lint format k8s-deploy
```

## Database Targets (Local Dev)

**Setup and migrations**:

```makefile
db-setup:
	docker-compose $(COMPOSE_FILES) exec db createdb -U user dbname

db-migrate:
	docker-compose $(COMPOSE_FILES) exec server alembic upgrade head

db-rollback:
	docker-compose $(COMPOSE_FILES) exec server alembic downgrade -1

db-seed:
	docker-compose $(COMPOSE_FILES) exec server python scripts/seed.py
```

## Dev Server Targets

**Run without Docker** (for local iteration):

```makefile
dev:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

dev-worker:
	python workers/run.py
```

## Example: Full Makefile

```makefile
.PHONY: help up down restart enter enter-worker logs-server logs-worker \
        build test lint k8s-deploy

.DEFAULT_GOAL := help

COMPOSE_FILES := -f docker-compose.base.yml -f docker-compose.override.yml

help:
	@echo "Available commands:"
	@echo "  make up            - Start all services"
	@echo "  make down          - Stop all services"
	@echo "  make restart       - Restart all services"
	@echo "  make enter         - Shell into server container"
	@echo "  make enter-worker  - Shell into worker container"
	@echo "  make logs-server   - Follow server logs"
	@echo "  make logs-worker   - Follow worker logs"
	@echo "  make build         - Build Docker image"
	@echo "  make test          - Run tests"
	@echo "  make lint          - Run linting"
	@echo "  make k8s-deploy    - Deploy to Kubernetes"

up:
	docker-compose $(COMPOSE_FILES) up --build -d
	docker-compose $(COMPOSE_FILES) logs -f server

down:
	docker-compose $(COMPOSE_FILES) down

restart: down up

enter:
	docker-compose $(COMPOSE_FILES) exec server /bin/bash

enter-worker:
	docker-compose $(COMPOSE_FILES) exec worker /bin/bash

logs-server:
	docker-compose $(COMPOSE_FILES) logs -f server

logs-worker:
	docker-compose $(COMPOSE_FILES) logs -f worker

build:
	docker build -t app:latest .

test:
	docker-compose $(COMPOSE_FILES) exec server pytest tests/ -v

lint:
	docker-compose $(COMPOSE_FILES) exec server ruff check src tests

k8s-deploy:
	kubectl apply -f k8s/
```

## Anti-patterns

- **Hardcoding container IDs**: Use service names from docker-compose; never `docker exec <container-id>`.
- **Missing .PHONY**: Targets fail if a file with the same name exists (e.g., a `test` directory).
- **No help target**: Teammates have to read the Makefile or README to discover commands.
- **Overly complex Makefiles**: If logic becomes baroque, move to a shell script and invoke it from the Makefile.
