# langfuse-llm-tracing

Production-grade LLM observability patterns for Python and TypeScript services using Langfuse.

## What this covers

This skill encodes real-world patterns for:

- **Lazy singleton client initialization** — environment-gated Langfuse client with graceful no-op when disabled
- **Completion tracing context managers** — Python `@contextmanager` pattern for one-shot LLM call tracing with input/output/error recording
- **TypeScript singleton service** — class-based service with `getInstance()` pattern and app versioning
- **Trace wrapper methods** — `traceOpenAICall()` and similar wrappers that measure latency, extract token usage, and handle errors
- **Metadata enrichment** — provider, model, task, sessionId, userId correlation for filtering and analysis
- **Lifecycle management** — shutdown hooks with flush() to ensure events are sent in serverless environments
- **Graceful degradation** — no-op when keys are missing or library import fails; never crashes the service

## Derived from production services

These patterns are extracted from multiple real production backend services that use Langfuse for LLM observability. All code snippets have been genericized to remove internal service names, project IDs, and proprietary details.

## Structure

- `SKILL.md` — Full pattern guide with YAML frontmatter, usage triggers, conventions, examples, and anti-patterns
- `references/langfuse-client-and-tracing.md` — Python lazy client, tracer context manager, flush/shutdown
- `references/python-and-typescript.md` — Cross-language singleton patterns, error handling, lifecycle
- `references/repo-evidence.md` — Genericized code snippets from real services

## Usage

This skill is designed to be used with Claude Code or similar AI-assisted development tools. Reference it when:

- Adding LLM call tracing to a new or existing service
- Implementing observability for Claude, OpenAI, or other LLM providers
- Debugging LLM failures with structured error capture
- Setting up usage analytics and cost tracking
- Migrating from logging-only to structured tracing

## Cross-references

- **observability-and-logging** — General observability patterns (structlog, OpenTelemetry, Prometheus, Sentry). Use for non-LLM instrumentation.
- **fastapi-service-patterns** — FastAPI app structure, middleware, dependency injection (context for where to integrate Langfuse)
- **async-python-patterns** — Async/await, context managers, lifecycle management (foundations for Python tracer implementation)

## Key differences from general observability

Langfuse is LLM-specific telemetry (generations, tokens, prompts, model performance). It complements but does not replace general observability tools:

- **Langfuse** → LLM call tracing, token usage, prompt debugging, model comparison
- **OpenTelemetry** → Distributed tracing, service dependency graphs, request flow
- **Prometheus** → RED metrics (rate, errors, duration), resource usage
- **Sentry** → Error aggregation, stack traces, release tracking
- **structlog** → Structured logging, request correlation, debug context

Use langfuse-llm-tracing for LLM-specific observability and observability-and-logging for general service instrumentation.
