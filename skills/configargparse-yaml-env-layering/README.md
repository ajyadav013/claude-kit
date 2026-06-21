# configargparse-yaml-env-layering

A Claude Skill capturing the three-layer service configuration pattern: YAML defaults → configargparse CLI/env merging → Pydantic BaseSettings singleton.

## What this skill covers

This skill documents a production-tested configuration pattern for Python backend services with multiple runtime modes. The pattern provides:

- **Three-layer config hierarchy** with clear precedence: YAML defaults < environment variables < CLI arguments
- **Mode-based entrypoint dispatch** (server, consumer, temporal_worker, cron) via a single entrypoint.py
- **Type-safe config access** through Pydantic BaseSettings validation
- **Auto environment variable discovery** using configargparse's `auto_env_var_prefix=""`
- **Module-level singleton** (`loaded_config`) for consistent config access across the codebase

This pattern is ideal for services deployed in containers where environment variables override YAML defaults, and where different runtime modes (FastAPI server, Kafka consumer, Temporal worker, cron job) share the same codebase.

## Derived from real production services

This skill is grounded in patterns observed across multiple production Python backend services. The conventions have been genericized and scrubbed of internal identifiers to make them safe for public use. The pattern is stack-agnostic but commonly appears in services using:

- FastAPI for HTTP APIs
- Kafka for event streaming
- Temporal for workflow orchestration
- PostgreSQL and Redis for data storage
- Google Cloud Platform for infrastructure

## How to use

Read `SKILL.md` for the full pattern guide, including:

- When to use this pattern vs. plain .env loading
- Core conventions for the three layers
- Complete skeleton code for config_parser.py, default.yaml, docker_config.py, and entrypoint.py
- Anti-patterns to avoid
- Cross-references to related patterns (pydantic-schema-patterns, backend-repo-architecture)

The `references/` directory contains deeper dives into config layering anatomy, mode dispatch, and real-world evidence.

## Differences from other patterns

- **vs. python-dotenv**: configargparse supports CLI override and YAML structure; dotenv is flat key-value only
- **vs. pydantic-settings alone**: configargparse adds YAML defaults and CLI args; pydantic-settings focuses on BaseSettings validation
- **vs. plain environment variables**: YAML provides local defaults without .env files; configargparse merges all three sources with clear precedence

## License

This skill is part of the claude-kit project and is provided as-is for use with Claude Code.
