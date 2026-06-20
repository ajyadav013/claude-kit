---
name: dockerfile-frontend
description: Multi-stage Dockerfile patterns for React/Vite/TypeScript frontends — node:alpine build stage with lockfile-first dependency caching, build-time VITE_* variables baked at image build, slim nginx runtime serving static dist with SPA history fallback (try_files $uri /index.html), envsubst for runtime backend URL configuration, and non-root security. Use when containerizing Vite/React/Next.js static frontends, implementing build-time vs runtime configuration, setting up nginx reverse proxy with SPA routing, or deploying frontend containers to k8s/Cloud Run.
---

# Dockerfile for Frontend Applications

Multi-stage Dockerfile patterns for building and serving React/Vite/TypeScript frontend applications with nginx or Node.js static servers.

## When to use

- Containerizing Vite, React, Next.js, or other Node.js-based frontend applications
- Building production-optimized static bundles in Docker
- Implementing build-time configuration via VITE_* or REACT_APP_* env vars
- Setting up nginx to serve SPAs with history API fallback routing
- Configuring runtime environment variables (backend URLs) via envsubst
- Deploying frontend containers to Kubernetes, Cloud Run, or container platforms
- Reverse-proxying API calls from frontend nginx to backend services

## Core conventions

### Multi-Stage Build: Node.js Build + Nginx Runtime

**Build stage (node:alpine)**: Use `node:20-alpine` or `node:22-alpine` for the build stage; install dependencies with lockfile-first caching (`COPY package.json package-lock.json* ./` then `npm ci`), then build the static bundle (`npm run build` or `npx vite build`).

**Runtime stage (nginx:alpine)**: Use `nginx:alpine` for the runtime stage; copy only the built `dist/` directory from the build stage to `/usr/share/nginx/html`. The final image contains no source code, no node_modules, only static files.

**Why**: Multi-stage builds keep the runtime image minimal (nginx:alpine ≈ 40MB vs node:alpine ≈ 180MB); faster deploys, smaller attack surface, lower storage costs.

**Alternative runtime (node server)**: Some projects use a lightweight Node.js static server (e.g., `node server.cjs` serving `./dist`) instead of nginx; useful when you need server-side logic or prefer a single-language stack.

### Lockfile-First Dependency Caching

**Pattern**: `COPY package.json package-lock.json* ./` (or `pnpm-lock.yaml` / `yarn.lock`) before `COPY . .`; run `npm ci` (or `pnpm install --frozen-lockfile` / `yarn install --frozen-lockfile`) immediately after.

**Why**: Docker layer caching reuses the `npm ci` layer unless lockfiles change; code changes don't trigger full npm reinstall. The `*` glob allows optional lockfile (won't fail if missing).

**npm ci vs npm install**: `npm ci` is faster and more deterministic; always uses lockfile, never mutates it. Use `npm ci` in Dockerfiles.

**Clean cache after install**: Run `npm cache clean --force` after `npm ci` to reduce layer size.

### Build-Time Configuration (VITE_*, REACT_APP_*)

**ARG declarations**: Declare build-time env vars as `ARG VITE_API_BASE_URL=/api/v1`, `ARG VITE_APP_NAME=MyApp`, `ARG REACT_APP_ENV=production` before the build command.

**Pass via --build-arg**: In CI/CD, pass values via `docker build --build-arg VITE_API_BASE_URL=https://api.example.com`.

**Baked at build time**: Vite and Create React App embed these variables into the JavaScript bundle at build time (replaced at transpilation); they are NOT runtime configurable. Rebuilding the image is required to change them.

**When to use**: Use build-time vars for values that differ per environment (dev/staging/prod) but are constant within that environment (API base URLs, feature flags, Sentry DSN).

**Defaults in Dockerfile**: Provide sensible defaults in `ARG` declarations (e.g., `ARG VITE_API_BASE_URL=/api/v1`) so the image builds without --build-arg.

### Runtime Configuration via envsubst

**Pattern**: For values that must be runtime-configurable (backend URL in k8s ConfigMap), use nginx config templates with `${BACKEND_URL}` placeholders and envsubst in an entrypoint script.

**nginx template**: Copy nginx config with placeholders to `/etc/nginx/templates/default.conf.template`.

**Entrypoint script**: `envsubst '${BACKEND_URL}' < /etc/nginx/templates/default.conf.template > /etc/nginx/conf.d/default.conf` then `exec "$@"` to start nginx.

**Why**: Allows one image to serve multiple environments; backend URL set at container start via env var, not baked into image.

**nginx:alpine built-in support**: Recent nginx:alpine images support `/etc/nginx/templates/` directory and auto-run envsubst; you can skip the manual entrypoint script if you only need simple env var substitution.

### Nginx SPA History Fallback

**try_files pattern**: In nginx config, use `location / { try_files $uri $uri/ /index.html; }` for SPA routing.

**Why**: Frontend routers (React Router, Vue Router) use browser history API; `/about` is a client-side route, not a file. Without `try_files`, nginx returns 404 for `/about`. With `try_files`, nginx serves `index.html` for all non-file paths, and the JS router handles the route.

**Static asset caching**: Add `location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2|ttf|eot)$ { expires 1y; add_header Cache-Control "public, immutable"; }` to cache hashed static assets.

**API reverse proxy**: Proxy `/api/*` requests to backend with `proxy_pass http://backend:8000;` (or `${BACKEND_URL}` via envsubst).

### Docker Embedded DNS Resolver

**Pattern**: In nginx config, add `resolver 127.0.0.11 valid=10s;` at the server level; use `set $backend ${BACKEND_URL}; proxy_pass $backend;` instead of `proxy_pass ${BACKEND_URL};` directly.

**Why**: Docker's embedded DNS (`127.0.0.11`) re-resolves hostnames; if the backend container restarts or scales, the IP changes. Using `set $backend` triggers per-request DNS lookup, avoiding stale IPs and 502 errors.

**When to use**: Use when proxying to dynamic backend services in docker-compose or k8s; skip for static external URLs.

### Non-Root User (Optional)

**Pattern**: In nginx stage, `RUN addgroup -S appgroup && adduser -S appuser -G appgroup` then `USER appuser` before `CMD`.

**Why**: Running as non-root reduces privilege escalation risk; some k8s clusters enforce non-root via PodSecurityPolicy.

**Nginx caveat**: nginx:alpine runs as root by default (binding to port 80 requires root); switching to non-root requires changing `listen` to 8080 and setting `pid /tmp/nginx.pid;`.

**Simpler pattern for Cloud Run/k8s**: Many platforms handle user namespacing externally; omitting `USER` is acceptable if your platform enforces it.

### Build Context and Monorepo Support

**Monorepo build context**: If frontend is in `frontend/` subdirectory of a monorepo, build from repo root with `-f frontend/Dockerfile .` and adjust COPY paths: `COPY frontend/package.json ./frontend/`.

**Shared dependencies**: Copy shared libraries before frontend source: `COPY shared/ ./shared/` then `COPY frontend/ ./frontend/`.

**Why**: Vite can import from `../shared/` at build time; the build stage needs access to the full monorepo context.

## Skeleton / example

```dockerfile
# Multi-stage Dockerfile: node build + nginx runtime
FROM node:22-alpine AS build

WORKDIR /app

# Lockfile-first caching
COPY package.json package-lock.json* ./
RUN npm ci && npm cache clean --force

# Copy source
COPY . .

# Build-time env vars (baked into bundle)
ARG VITE_API_BASE_URL=/api/v1
ARG VITE_APP_NAME=MyApp
ARG VITE_APP_ENV=production

# Build static bundle
RUN npm run build

# Runtime stage (nginx)
FROM nginx:alpine

# Copy built static files
COPY --from=build /app/dist /usr/share/nginx/html

# Copy nginx config (with SPA fallback)
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
```

```nginx
# nginx.conf — SPA fallback + API proxy
server {
    listen 80;
    server_name localhost;
    root /usr/share/nginx/html;
    index index.html;

    # SPA history fallback
    location / {
        try_files $uri $uri/ /index.html;
    }

    # Cache static assets
    location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2|ttf|eot)$ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    # Reverse proxy to backend
    location /api/ {
        proxy_pass http://backend:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

```dockerfile
# Runtime config via envsubst
FROM node:22-alpine AS build
# ... (build stage as above)

FROM nginx:alpine

# Install envsubst tool
RUN apk add --no-cache gettext

# Copy build output
COPY --from=build /app/dist /usr/share/nginx/html

# Copy nginx template (with ${BACKEND_URL} placeholder)
COPY nginx.conf.template /etc/nginx/templates/default.conf.template

# Copy entrypoint script
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

EXPOSE 80

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["nginx", "-g", "daemon off;"]
```

```bash
#!/bin/sh
# docker-entrypoint.sh — envsubst runtime config
set -e

# Default backend URL if not set
: "${BACKEND_URL:=http://backend:8000}"
echo "[entrypoint] Using BACKEND_URL=${BACKEND_URL}"

# Render nginx config from template
envsubst '${BACKEND_URL}' \
  < /etc/nginx/templates/default.conf.template \
  > /etc/nginx/conf.d/default.conf

# Start nginx
exec "$@"
```

```nginx
# nginx.conf.template — runtime backend URL
server {
    listen 80;
    root /usr/share/nginx/html;
    index index.html;

    # Docker embedded DNS resolver
    resolver 127.0.0.11 valid=10s;

    location /api/ {
        # Use set + variable to trigger per-request DNS lookup
        set $backend ${BACKEND_URL};
        proxy_pass $backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }

    location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2|ttf|eot)$ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
}
```

```dockerfile
# Node.js static server runtime (alternative to nginx)
FROM node:22-alpine AS build
# ... (build stage as above)

FROM node:22-alpine

WORKDIR /app

# Copy only the built dist and server script
COPY --from=build /app/dist ./dist
COPY server.cjs ./

EXPOSE 80

CMD ["node", "server.cjs"]
```

```javascript
// server.cjs — simple Node.js static server
const express = require('express');
const path = require('path');

const app = express();
const PORT = process.env.PORT || 80;

// Serve static files
app.use(express.static(path.join(__dirname, 'dist')));

// SPA fallback
app.get('*', (req, res) => {
  res.sendFile(path.join(__dirname, 'dist', 'index.html'));
});

app.listen(PORT, () => {
  console.log(`Server listening on port ${PORT}`);
});
```

## Anti-patterns to avoid

- **Installing dev dependencies in production** — use `npm ci --omit=dev` or rely on multi-stage build to exclude node_modules from runtime.
- **Copying node_modules from build stage** — never copy node_modules to runtime; only copy the built `dist/` directory.
- **Missing .dockerignore** — without `.dockerignore`, COPY includes node_modules, .git, .env; bloats build context and risks leaking secrets. Always ignore `node_modules/`, `.git/`, `.env*`, `dist/`.
- **Copying all files before lockfile** — breaks layer caching; copy package.json first, install deps, then copy source.
- **Using npm install instead of npm ci** — `npm install` can mutate lockfile and is slower; always use `npm ci` in Dockerfiles.
- **Hardcoding backend URL in source** — makes the image environment-specific; use build-time ARG or runtime envsubst.
- **Forgetting try_files for SPAs** — client-side routes return 404 on page reload; always add `try_files $uri $uri/ /index.html`.
- **Missing Docker DNS resolver** — nginx caches backend IPs; backend restarts cause 502s. Use `resolver 127.0.0.11 valid=10s;` and `set $backend`.
- **Exposing privileged port 80 as non-root** — nginx can't bind to port 80 without root; use `listen 8080` or omit non-root user.
- **Running tsc in Dockerfile when build script already does** — duplicates work; trust `npm run build` to handle TypeScript compilation.
- **Printing build args or env vars in RUN echo** — secrets leak into image layers; never log credentials.

## References

- [frontend-dockerfile-anatomy.md](./references/frontend-dockerfile-anatomy.md) — Multi-stage structure, lockfile caching, build vs runtime config
- [build-args-and-nginx.md](./references/build-args-and-nginx.md) — VITE_*/REACT_APP_* build args, envsubst runtime config, nginx SPA patterns
- [repo-evidence.md](./references/repo-evidence.md) — Genericized snippets from production services
- [containerization-and-deployment](../containerization-and-deployment/SKILL.md) — Cross-reference for backend Docker patterns, docker-compose, Cloud Run deployment
