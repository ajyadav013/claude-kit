# Build Args and Nginx Configuration

Build-time env vars, runtime envsubst, SPA routing, and reverse proxy patterns.

## Build-Time Environment Variables (VITE_*, REACT_APP_*)

**How Vite/CRA embed env vars**:
- Vite: Reads `import.meta.env.VITE_*` at build time; replaces with literal values in bundle
- Create React App: Reads `process.env.REACT_APP_*` at build time; replaces with literals
- Result: `fetch(import.meta.env.VITE_API_BASE_URL)` becomes `fetch("/api/v1")` in the transpiled JS

**Dockerfile pattern**:
```dockerfile
# Declare build args with defaults
ARG VITE_API_BASE_URL=/api/v1
ARG VITE_APP_NAME=MyApp
ARG VITE_APP_ENV=production
ARG VITE_SENTRY_DSN=

# Build command picks up ARGs as env vars
RUN npm run build
```

**CI/CD usage**:
```bash
docker build \
  --build-arg VITE_API_BASE_URL=https://api.staging.example.com \
  --build-arg VITE_APP_ENV=staging \
  --build-arg VITE_SENTRY_DSN=https://abc123@sentry.io/456 \
  -t myapp:staging .
```

**Key rules**:
1. Prefix with `VITE_` (Vite) or `REACT_APP_` (CRA) or they won't be embedded
2. Declare ARG in Dockerfile with sensible defaults (so build works without --build-arg)
3. Pass via --build-arg in CI/CD for environment-specific values
4. Never pass secrets as build args — they leak into image layers (use runtime ENV instead)
5. Rebuilding the image is required to change build-time vars

**When to use**: API URLs, feature flags, analytics IDs, Sentry DSN, public keys (values constant per environment).

## Runtime Environment Variables (envsubst)

**Use case**: Backend URL must be configurable at container start (k8s ConfigMap, Cloud Run env vars) without rebuilding the image.

**Pattern**: Nginx config template with `${BACKEND_URL}` placeholder; entrypoint script runs `envsubst` to generate final config.

**nginx.conf.template**:
```nginx
server {
    listen 80;
    root /usr/share/nginx/html;
    index index.html;

    location /api/ {
        proxy_pass ${BACKEND_URL};  # ← envsubst replaces this
        proxy_set_header Host $host;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

**docker-entrypoint.sh**:
```bash
#!/bin/sh
set -e

# Default if not set
: "${BACKEND_URL:=http://backend:8000}"
echo "[entrypoint] Using BACKEND_URL=${BACKEND_URL}"

# Generate nginx config from template
envsubst '${BACKEND_URL}' \
  < /etc/nginx/templates/default.conf.template \
  > /etc/nginx/conf.d/default.conf

# Start nginx
exec "$@"
```

**Dockerfile**:
```dockerfile
FROM nginx:alpine

# Install envsubst (part of gettext package)
RUN apk add --no-cache gettext

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["nginx", "-g", "daemon off;"]
```

**Usage**:
```bash
docker run -e BACKEND_URL=http://prod-backend:8000 myapp:latest
```

**Built-in nginx:alpine support**: Recent nginx:alpine images auto-run envsubst on `/etc/nginx/templates/*.template` files at startup; you can skip the manual entrypoint script if you only need simple env var substitution.

## Nginx SPA History Fallback

**Problem**: React Router uses browser history API; `/about` is a client-side route, not a file. Nginx returns 404 for `/about` on page reload.

**Solution**: `try_files $uri $uri/ /index.html` serves `index.html` for all non-file routes; the React router handles the route client-side.

**Pattern**:
```nginx
server {
    listen 80;
    root /usr/share/nginx/html;
    index index.html;

    # SPA fallback
    location / {
        try_files $uri $uri/ /index.html;
    }

    # Static assets (no fallback)
    location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2|ttf|eot)$ {
        try_files $uri =404;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
}
```

**Why regex for static assets**: Without the regex location block, all 404s (including missing images) would fallback to `index.html` instead of returning 404. The regex block takes priority for static files, and the `/` block handles everything else.

**Cache-Control headers**: Vite/Webpack generate content-hashed filenames (`main.a1b2c3d4.js`); these files never change (new builds have new hashes). Setting `expires 1y` and `immutable` allows browsers and CDNs to cache them indefinitely.

## Nginx Reverse Proxy to Backend

**Pattern**:
```nginx
location /api/ {
    proxy_pass http://backend:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

**Why proxy from frontend nginx**: Avoids CORS preflight requests; frontend and API share the same origin (same domain + port). Browser sends `fetch('/api/users')` to frontend nginx; nginx proxies to `http://backend:8000/api/users`.

**Headers**:
- `Host`: Preserves original host header (important for multi-tenant backends)
- `X-Real-IP`: Original client IP (nginx replaces it with its own IP without this)
- `X-Forwarded-For`: Chain of proxies (load balancer → nginx → backend)
- `X-Forwarded-Proto`: Original protocol (http vs https; important for redirect logic)

## Docker Embedded DNS Resolver

**Problem**: Nginx resolves `backend:8000` at startup, caches the IP; when the backend container restarts or scales, the IP changes, and nginx keeps proxying to the stale IP, causing 502 errors.

**Solution**: Use Docker's embedded DNS resolver (`127.0.0.11`) and trigger per-request DNS lookup via nginx variable.

**Pattern**:
```nginx
server {
    listen 80;
    root /usr/share/nginx/html;

    # Docker embedded DNS
    resolver 127.0.0.11 valid=10s;

    location /api/ {
        # Use set + variable to force per-request DNS lookup
        set $backend http://backend:8000;
        proxy_pass $backend;
        proxy_set_header Host $host;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

**Why `set $backend`**: Nginx only re-resolves hostnames when they appear as variables. `proxy_pass http://backend:8000;` resolves once at startup; `set $backend http://backend:8000; proxy_pass $backend;` resolves on every request (or every 10s, per `valid=10s`).

**When to use**: Always use in docker-compose and k8s when proxying to dynamic backend services. Skip for static external URLs (CDNs, third-party APIs).

**Alternative (envsubst + resolver)**: Combine runtime envsubst with resolver:
```nginx
resolver 127.0.0.11 valid=10s;

location /api/ {
    set $backend ${BACKEND_URL};  # envsubst replaces ${BACKEND_URL} at startup
    proxy_pass $backend;
}
```

## Nginx Security Headers

**Pattern**:
```nginx
server {
    listen 80;
    root /usr/share/nginx/html;

    # Security headers
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Content-Security-Policy "frame-ancestors 'self'" always;

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

**Headers**:
- `X-Content-Type-Options: nosniff`: Prevents MIME-type sniffing (browser won't execute .txt as .js)
- `X-XSS-Protection: 1; mode=block`: Enables browser XSS filter (legacy; CSP is preferred)
- `Content-Security-Policy`: Restricts embedding (prevents clickjacking); `frame-ancestors 'self'` allows same-origin embedding only

**When to use**: Always add in production; adjust CSP for third-party embeds (analytics, maps, widgets).

## Nginx Gzip Compression

**Pattern**:
```nginx
http {
    gzip on;
    gzip_vary on;
    gzip_min_length 1024;
    gzip_proxied any;
    gzip_types
        text/plain
        text/css
        text/xml
        text/javascript
        application/javascript
        application/json
        application/xml+rss;

    server {
        listen 80;
        root /usr/share/nginx/html;
        # ... rest of config
    }
}
```

**Why**: Reduces payload size by 70-80% for text files (HTML/CSS/JS/JSON); faster page loads, lower bandwidth costs.

**gzip_min_length 1024**: Only compress files >1KB; tiny files compress inefficiently.

**gzip_types**: Only compress text formats; images/videos are already compressed (gzipping them wastes CPU).

**gzip_vary on**: Adds `Vary: Accept-Encoding` header so CDNs cache gzipped and non-gzipped versions separately.

## Health Check Endpoint

**Pattern**:
```nginx
location = /health {
    access_log off;
    default_type text/plain;
    return 200 "healthy\n";
}
```

**Why**: k8s liveness/readiness probes need a fast endpoint that doesn't depend on backend availability. This returns 200 immediately without proxying.

**When to use**: Always add for k8s/Cloud Run deployments; orchestrators poll `/health` every few seconds.
