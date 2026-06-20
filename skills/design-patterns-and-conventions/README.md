# design-patterns-and-conventions

Cross-cutting design patterns, architectural conventions, naming standards, and anti-pattern catalogue for FastAPI backends derived from real-world production Python services.

## What this skill covers

- **Layered architecture:** Router → Service → DAO → Model separation
- **Dependency injection:** FastAPI `Depends()` patterns, connection handlers
- **Configuration management:** `loaded_config` singleton (Pydantic BaseSettings)
- **Singleton metaclass:** For ConnectionManager, event bridges, and global resources
- **Factory pattern:** `get_app()` / `create_app()` application factories
- **Custom API routes:** Centralized request/response logging and error handling via `CustomRequestRoute`
- **Response envelopes:** Uniform `ResponseData` wrapper for success/error responses
- **Event-driven architecture:** Kafka producer/consumer with config-driven topic-to-handler maps
- **Workflow orchestration:** Temporal integration, JSON-DAG workflow DSL
- **Multi-mode entrypoints:** One Docker image, multiple roles (server/consumer/worker/cron) selected by MODE
- **Naming conventions:** snake_case files/functions, PascalCase classes
- **Folder layout:** Per-domain modules, versioned APIs, standard top-level structure
- **Testing patterns:** Unit tests for services, integration tests for routers, DAO tests, Kafka/Temporal testing strategies
- **Troubleshooting:** Diagnostics and fixes for session leaks, blocked event loops, CORS errors, Kafka/Temporal issues, and more
- **Anti-patterns catalogue:** Hardcoded secrets, CORS wildcards, sync clients in async code, copy-pasted DAOs, missing rollback, deprecated lifecycle hooks, unscoped sessions, and more

## Source

Derived from real-world production Python/FastAPI services demonstrating layered architecture, dependency injection, event-driven patterns with Kafka, workflow orchestration with Temporal, and multi-mode deployment strategies.

## How to apply

1. **New service architecture:** Start with the layered pattern (router/service/dao/model), apply the factory pattern for `create_app()`, use `CustomRequestRoute` for cross-cutting concerns, and return `ResponseData` envelopes from all endpoints.
2. **Configuration:** Create a single `config/docker_config.py` with a Pydantic `BaseSettings` class; export `loaded_config = Settings()` and import it everywhere. Never hardcode secrets; use environment variables.
3. **Database connections:** Use the Singleton `ConnectionManager` pattern with `async_scoped_session(scopefunc=current_task)` to prevent session leaks. Inject sessions via `Depends(get_connection_handler_for_app)`.
4. **Multi-mode deployment:** If your service has multiple roles (API server + Kafka consumer + Temporal worker), use a single `entrypoint.py` that branches on `loaded_config.MODE` and calls the appropriate `main()` function.
5. **Naming and layout:** Follow snake_case for files/functions, PascalCase for classes; organize by domain (one folder per feature with `router.py`, `service.py`, `dao.py`, `models.py` inside).
6. **Anti-pattern audits:** Review `references/anti-patterns.md` before committing; check for hardcoded secrets, CORS wildcards, sync clients in async paths, copy-pasted code, missing rollback, and deprecated lifecycle hooks.

## Additional Resources

- **Testing Patterns:** See `references/testing-patterns.md` for pytest strategies, mocking, test fixtures, and CI/CD integration for testing the layered architecture, dependency injection, Kafka, and Temporal workflows.
- **Troubleshooting:** See `references/troubleshooting.md` for common issues (session leaks, blocked event loops, duplicate routes, CORS errors, Kafka/Temporal problems) with diagnostics and fixes.

## Provenance

- **Codebase-derived:** All patterns, naming conventions, folder layouts, anti-patterns, and troubleshooting scenarios are extracted from real production FastAPI services. Code snippets are verified against working implementations.
- **Internet-confirmed:** None. This skill is purely evidence-driven from production systems.
