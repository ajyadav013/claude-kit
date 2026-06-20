# Dockerfile for Frontend Applications

Multi-stage Dockerfile patterns for React/Vite/TypeScript frontends, derived from real-world production services.

## What this skill covers

- **Multi-stage builds**: node:alpine build stage → nginx:alpine runtime stage
- **Lockfile-first dependency caching**: maximize Docker layer reuse
- **Build-time configuration**: VITE_* / REACT_APP_* build args baked into bundles
- **Runtime configuration**: envsubst for backend URLs set at container start
- **Nginx SPA routing**: try_files fallback for React Router / Vue Router
- **Docker DNS resolver**: per-request backend lookup to avoid stale IPs
- **API reverse proxy**: nginx proxying /api/ to backend services
- **Static asset caching**: long-lived cache headers for hashed bundles
- **Alternative runtimes**: Node.js static server instead of nginx
- **Monorepo support**: build context from repo root with shared dependencies

## Production-tested patterns

All patterns in this skill are extracted and genericized from production frontend services running in containerized environments (Kubernetes, Cloud Run, docker-compose). No internal service names, registry URLs, or credentials are included — only reusable, stack-agnostic Docker conventions.

## Usage

Reference `SKILL.md` for detailed conventions, skeleton examples, anti-patterns, and cross-links to the backend containerization skill.

## Structure

- `SKILL.md` — Core skill content (frontmatter + conventions + examples + anti-patterns)
- `references/frontend-dockerfile-anatomy.md` — Deep dive on multi-stage structure
- `references/build-args-and-nginx.md` — Build-time vs runtime config, nginx patterns
- `references/repo-evidence.md` — Genericized real-world snippets (no internal refs)
