# docker-shared

Shared Docker building blocks for multi-service architectures — base images, .dockerignore conventions, and compose fragment reuse.

## What this skill covers

- **Shared base images**: Creating a `Dockerfile.base` with heavy system dependencies, publishing to private registries, and consuming with tag or digest pinning
- **Private registry authentication**: Passing build-arg tokens for registry/package auth (with critical anti-patterns to avoid)
- **.dockerignore conventions**: Excluding secrets, tests, dependencies, and build artifacts from the Docker build context
- **Shared compose fragments**: YAML anchors, x- extension fields, external networks/volumes for reusing configuration across services

## Origin

This skill is derived from real-world production services across multiple backend microservices that share a common base image and compose infrastructure. All examples have been genericized to remove internal names, registry hostnames, and credentials.

## When to use

Use this skill when:
- Creating a base image to share heavy system dependencies across multiple related services
- Setting up .dockerignore to exclude secrets, tests, and development artifacts
- Sharing compose configuration fragments (env vars, logging, resource limits) across services
- Handling private registry authentication during image builds

For broader Docker topics (multi-stage builds, entrypoint MODE dispatch, deployment), see the **containerization-and-deployment** skill.
