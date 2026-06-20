# Dockerfile for Python Backend Services

This skill captures production-proven multi-stage Dockerfile patterns for Python/FastAPI backend services, derived from real-world microservices handling PostgreSQL, Kafka, and Kerberos authentication.

## What this covers

- **Multi-stage builds**: Builder vs runtime stage separation for minimal final image size
- **Base image trade-offs**: When to use `python:3.11-slim` (Debian-based, broader compatibility) vs `python:3.10-alpine` (minimal footprint, more build complexity)
- **System dependencies**: Installing libpq (PostgreSQL), librdkafka (Kafka clients), krb5 (Kerberos/GSSAPI authentication) in builder vs runtime stages
- **Layer caching optimization**: Copying dependency manifests (requirements.txt, pyproject.toml) before application code to maximize Docker build cache hits
- **Virtual environment patterns**: Creating `/opt/venv` in builder stage and copying to runtime for clean dependency isolation
- **Security hardening**: Non-root users, removing .git after capturing commit SHA, `PYTHONUNBUFFERED=1`, avoiding secrets in build args
- **Multi-mode entrypoints**: Using `entrypoint.py` with MODE env var to run server/consumer/worker/cron from one image
- **Production server setup**: Gunicorn + uvicorn workers for ASGI FastAPI applications
- **Health checks**: Dockerfile HEALTHCHECK and k8s readiness/liveness probe patterns

## Source

Patterns are derived from production Python backend services in the wild, genericized to remove any internal references. The skill reflects real-world Docker builds that power services handling:

- FastAPI REST APIs with PostgreSQL databases
- Kafka consumers with confluent-kafka-python and librdkafka
- Temporal workflow workers
- Kerberos-authenticated Kafka streams (SASL_GSSAPI)
- Multi-role deployments (server/consumer/worker/cron from one image)

## Cross-references

- **containerization-and-deployment skill**: Broader patterns including entrypoint.py MODE dispatch, docker-compose for local dev, Cloud Run/k8s deployment, cert/keytab writing from env vars
- **fastapi-service-patterns rule**: Application-level FastAPI patterns (routers, dependency injection, error handling)
- **python-dao-and-database rule**: Database connection pooling, SQLAlchemy patterns
- **kafka-config-driven rule**: Kafka consumer configuration and error handling

This is the granular Dockerfile deep-dive; cross-link to containerization-and-deployment for the full deployment story.
