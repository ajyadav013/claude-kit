# Repo Evidence

Genericized snippets from production frontend Dockerfiles and nginx configurations. All internal service names, registry URLs, and credentials have been removed.

## Multi-Stage Dockerfile (nginx runtime)

**Example from a production service**:

```dockerfile
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 3000
CMD ["nginx", "-g", "daemon off;"]
```

**Pattern**: Minimal two-stage build; build stage installs deps and runs `npm run build`, runtime stage copies only `dist/` to nginx.

## Multi-Stage Dockerfile (Node.js runtime)

**Example from a production service**:

```dockerfile
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:22-alpine
WORKDIR /app
COPY --from=build /app/dist ./dist
COPY config.cjs server.cjs ./
EXPOSE 80
CMD ["node", "server.cjs"]
```

**Pattern**: Uses a simple Node.js static server instead of nginx; useful for teams unfamiliar with nginx config or when server-side logic is needed.

## Development Dockerfile (single-stage, hot reload)

**Example from a production service**:

```dockerfile
FROM node:22-alpine

WORKDIR /app

# Install dependencies (cached layer)
COPY package.json package-lock.json ./
RUN npm ci

# Copy source
COPY . .

EXPOSE 3000

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
```

**Pattern**: Single-stage Dockerfile for local development; uses volume mount for hot reload; runs Vite dev server (not production build). The `--host 0.0.0.0` flag allows access from outside the container.

## Build Args and Advanced Build

**Example from a production service**:

```dockerfile
# Build context must be the repo root: docker build -f frontend/Dockerfile .
FROM node:20-alpine AS build

WORKDIR /app

# Install frontend dependencies
COPY frontend/package*.json ./frontend/
RUN cd frontend && npm ci && npm cache clean --force

# Copy shared assets (imported by frontend at build time)
COPY shared/ ./shared/

# Copy frontend source
COPY frontend/ ./frontend/

# Build-time env vars (injected via --build-arg in CI)
ARG VITE_API_BASE_URL=/api/v1
ARG VITE_APP_NAME=MyApp
ARG VITE_SENTRY_DSN=
ARG VITE_APP_ENV=production

# Skip tsc -b (type-checking runs separately in CI lint).
# Vite bundles and tree-shakes without needing tsc output.
RUN cd frontend && npx vite build

# ---------- Runtime stage (nginx) ----------
FROM nginx:alpine

# Static files
COPY --from=build /app/frontend/dist /usr/share/nginx/html

# Nginx config template (envsubst resolves ${BACKEND_URL} at startup)
COPY frontend/nginx.conf /etc/nginx/templates/default.conf.template

# Entrypoint runs envsubst then starts nginx
COPY frontend/docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

EXPOSE 80

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["nginx", "-g", "daemon off;"]
```

**Pattern**: Monorepo build context; copies shared libs before frontend source; declares build-time VITE_* args; uses nginx template + envsubst for runtime config.

## Nginx Config (SPA fallback + API proxy)

**Example from a production service**:

```nginx
server {
    listen 3000;
    server_name localhost;
    root /usr/share/nginx/html;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    location /v1/ {
        proxy_pass http://backend:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /_healthz {
        proxy_pass http://backend:8000;
    }

    location /_readyz {
        proxy_pass http://backend:8000;
    }
}
```

**Pattern**: Minimal SPA config; all routes fallback to index.html; /v1/ and health endpoints proxy to backend.

## Advanced Nginx Config (OpenResty + envsubst + DNS resolver)

**Example from a production service**:

```dockerfile
FROM node:20-alpine AS build

WORKDIR /app
COPY package*.json ./
RUN npm install && npm cache clean --force
COPY . .

ARG NODE_OPTIONS="--max-old-space-size=4096"
ENV NODE_OPTIONS=$NODE_OPTIONS
RUN npx vite build

# Runtime stage (OpenResty)
FROM openresty/openresty:alpine

# envsubst
RUN apk add --no-cache gettext

# Default upstream (override at runtime)
ENV BACKEND_BASE_URL=http://backend:7001

# Nginx config template (envsubst will render this at startup)
COPY nginx.conf /usr/local/openresty/nginx/conf/nginx.conf.template

# Static files
COPY --from=build /app/dist /usr/local/openresty/nginx/html

# Entrypoint
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

EXPOSE 80
CMD ["/docker-entrypoint.sh"]
```

```bash
#!/usr/bin/env sh
# docker-entrypoint.sh
set -eu

: "${BACKEND_BASE_URL:=http://backend:7001}"
echo "[entrypoint] Using BACKEND_BASE_URL=${BACKEND_BASE_URL}"

# Render nginx.conf from template
envsubst '$BACKEND_BASE_URL' \
  < /usr/local/openresty/nginx/conf/nginx.conf.template \
  > /usr/local/openresty/nginx/conf/nginx.conf

# Show the effective upstream once (nice for debugging)
grep -n 'proxy_pass' /usr/local/openresty/nginx/conf/nginx.conf || true

# Start OpenResty in foreground
exec openresty -g 'daemon off;'
```

```nginx
# nginx.conf.template
env BACKEND_BASE_URL;

worker_processes auto;

events {
    worker_connections 1024;
}

http {
    include       mime.types;
    default_type  application/octet-stream;

    # Add MIME type for .mjs files (ES modules)
    types {
        application/javascript mjs;
    }

    # Gzip
    gzip on;
    gzip_vary on;
    gzip_min_length 10240;
    gzip_proxied expired no-cache no-store private auth;
    gzip_types
        text/plain
        text/css
        text/xml
        text/javascript
        application/x-javascript
        application/xml+rss
        application/javascript
        application/json;

    server {
        listen 80;
        server_name localhost;

        root  /usr/local/openresty/nginx/html;
        index index.html;

        # Security headers
        add_header Content-Security-Policy "frame-ancestors 'self' * file:" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header X-XSS-Protection "1; mode=block" always;

        # Static assets (long cache)
        location ~* \.(js|mjs|css|png|jpg|jpeg|gif|ico|svg|woff|woff2|ttf|eot)$ {
            expires 1y;
            add_header Cache-Control "public, immutable";
            try_files $uri =404;
        }

        # API proxy (LITERAL after envsubst; no resolver needed)
        location /graphql {
            proxy_pass ${BACKEND_BASE_URL};

            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";

            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;

            proxy_cache_bypass $http_upgrade;
            proxy_ssl_server_name on;
        }

        location /api {
            proxy_pass ${BACKEND_BASE_URL};

            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";

            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;

            proxy_cache_bypass $http_upgrade;
            proxy_ssl_server_name on;
        }

        # SPA fallback
        location / {
            try_files $uri $uri/ /index.html;
        }

        # Health
        location = /health {
            access_log off;
            default_type text/plain;
            return 200 "healthy\n";
        }
    }
}
```

**Pattern**: OpenResty (nginx + Lua) with envsubst for runtime backend URL; comprehensive security headers, gzip, static asset caching, WebSocket support (Upgrade headers), health endpoint.

## Nginx Config (Docker DNS resolver)

**Example from a production service**:

```nginx
server {
    listen 80;
    root /usr/share/nginx/html;
    index index.html;

    # Docker embedded DNS — re-resolve backend hostname on each request
    # so container IP changes (restarts, scaling) don't cause 502s
    resolver 127.0.0.11 valid=10s;

    # API reverse proxy (BACKEND_URL resolved at container startup via envsubst)
    location /api/ {
        set $backend ${BACKEND_URL};
        proxy_pass $backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # SPA fallback — serve index.html for all non-file routes
    location / {
        try_files $uri $uri/ /index.html;
    }

    # Cache static assets
    location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2|ttf|eot)$ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
}
```

**Pattern**: Uses Docker's embedded DNS (`127.0.0.11`) with `set $backend` to trigger per-request DNS lookup; prevents 502s when backend container restarts.

## Docker Entrypoint (envsubst)

**Example from a production service**:

```bash
#!/bin/sh
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

**Pattern**: Minimal entrypoint for runtime env var substitution; defaults to `http://backend:8000` if not set; uses `exec "$@"` to forward CMD to nginx.

## Build Commands (package.json)

**Examples from production services**:

```json
{
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview"
  }
}
```

**Pattern**: Standard Vite build pipeline; `tsc -b` (incremental TypeScript build) then `vite build` (bundle + tree-shake). Some projects skip `tsc -b` in Dockerfile (type-checking runs in CI lint separately) and only run `vite build`.

## .dockerignore

**Example**:

```
node_modules/
.git/
.env*
dist/
build/
*.log
.DS_Store
coverage/
.vscode/
.idea/
```

**Pattern**: Exclude build artifacts, dependencies, IDE files, and secrets from Docker build context; reduces context size and prevents leaking .env.
