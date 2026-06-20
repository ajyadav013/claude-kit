# Frontend Dockerfile Anatomy

Multi-stage build structure, lockfile caching, and slim runtime patterns.

## Multi-Stage Pattern: Build + Runtime

**Build stage (node:alpine)**:
- Base: `node:20-alpine` or `node:22-alpine` (smallest Node.js footprint)
- Purpose: Install dependencies, transpile TypeScript, bundle with Vite/Webpack
- Output: `dist/` directory with static HTML/JS/CSS
- Tools: npm/pnpm/yarn, TypeScript compiler, Vite bundler
- Size: ~500MB (node + node_modules + source)

**Runtime stage (nginx:alpine or node:alpine)**:
- Base: `nginx:alpine` (~40MB) for static serving, or `node:22-alpine` for Node.js server
- Purpose: Serve static files, reverse-proxy API requests
- Input: Only `dist/` directory from build stage
- No node_modules, no source code, no TypeScript compiler
- Size: ~50MB (nginx + dist) or ~200MB (node + dist + minimal server script)

**Why two stages**: Build tools and dependencies are not needed at runtime; separating them reduces final image size by 80-90%.

## Lockfile-First Dependency Caching

**Pattern**:
```dockerfile
# Copy lockfiles before source
COPY package.json package-lock.json* ./
RUN npm ci && npm cache clean --force

# Copy source after deps are installed
COPY . .
RUN npm run build
```

**How Docker caching works**: Each Docker `RUN`, `COPY`, `ADD` instruction creates a layer; layers are cached by content hash. If `package.json` or lockfile changes, Docker invalidates the cache from that line forward and re-runs `npm ci`. If only source code changes, Docker reuses the cached `npm ci` layer.

**npm ci vs npm install**:
- `npm ci`: Deletes node_modules, installs from lockfile exactly, never mutates lockfile, faster (~2x)
- `npm install`: Updates node_modules incrementally, can mutate lockfile if versions drift, slower

Always use `npm ci` in Dockerfiles. The `*` glob in `package-lock.json*` makes the COPY non-fatal if lockfile is missing (useful for pnpm/yarn multi-manager repos).

**npm cache clean --force**: Deletes npm's download cache (`~/.npm/`) after install; reduces layer size by ~100-200MB. Not needed in multi-stage builds (the cache is discarded with the build stage), but harmless and makes single-stage Dockerfiles smaller.

## Build-Time vs Runtime Configuration

**Build-time (ARG + VITE_* / REACT_APP_*)**:
- Declared as `ARG VITE_API_BASE_URL=/api/v1` before build command
- Passed via `docker build --build-arg VITE_API_BASE_URL=https://api.example.com`
- Replaced at transpilation time by Vite/Webpack; baked into the JavaScript bundle
- **Not configurable at runtime** — changing the value requires rebuilding the image
- Use for: API URLs, feature flags, analytics IDs, Sentry DSN (values constant per environment)

**Runtime (ENV + envsubst)**:
- Declared as `ENV BACKEND_URL=http://backend:8000` in Dockerfile or set at `docker run -e BACKEND_URL=...`
- Injected into nginx config via `envsubst` in entrypoint script
- **Configurable at container start** — same image can serve dev/staging/prod with different env vars
- Use for: Backend URLs in k8s ConfigMaps, dynamic service discovery, per-deployment overrides

**Guideline**: If the value is constant per environment (dev always uses dev API, prod always uses prod API), use build-time ARG and build one image per environment. If the value changes frequently or is set by an orchestrator (k8s, Nomad), use runtime ENV.

## Node.js vs Nginx Runtime

**Nginx runtime (recommended)**:
- Pros: Smallest image (~40MB), fastest static serving, built-in gzip/brotli, mature reverse proxy
- Cons: Requires nginx.conf knowledge, two-language stack (Dockerfile + nginx config)
- Best for: Production SPA deployments, high-traffic sites, when you need reverse proxy

**Node.js static server runtime**:
- Pros: Single-language stack (JavaScript everywhere), easier for Node.js-focused teams, simpler server.js than nginx.conf
- Cons: Larger image (~200MB), slower static serving than nginx, more memory overhead
- Best for: Lower-traffic apps, teams unfamiliar with nginx, when you need server-side logic (SSR precursor, A/B testing)

**Pattern (Node.js server)**:
```dockerfile
FROM node:22-alpine AS build
# ... build stage ...

FROM node:22-alpine
WORKDIR /app
COPY --from=build /app/dist ./dist
COPY server.cjs ./
EXPOSE 80
CMD ["node", "server.cjs"]
```

```javascript
// server.cjs
const express = require('express');
const path = require('path');
const app = express();
app.use(express.static('dist'));
app.get('*', (req, res) => res.sendFile(path.join(__dirname, 'dist', 'index.html')));
app.listen(80);
```

## Monorepo Build Context

**Challenge**: Frontend is in `frontend/` subdirectory; it imports from `../shared/` at build time; Vite needs access to the full repo to resolve imports.

**Solution**: Build from repo root with `-f frontend/Dockerfile .` and adjust COPY paths.

**Example**:
```dockerfile
# Build context: repo root (.)
# Dockerfile path: frontend/Dockerfile
FROM node:22-alpine AS build
WORKDIR /app

# Install frontend deps
COPY frontend/package*.json ./frontend/
RUN cd frontend && npm ci

# Copy shared libs (imported by frontend)
COPY shared/ ./shared/

# Copy frontend source
COPY frontend/ ./frontend/

# Build
RUN cd frontend && npm run build

# Runtime
FROM nginx:alpine
COPY --from=build /app/frontend/dist /usr/share/nginx/html
```

**Command**: `docker build -f frontend/Dockerfile .` (context is `.`, Dockerfile is `frontend/Dockerfile`)

**Why**: Vite resolves `import { foo } from '../../shared/utils'` at build time; the build context must include `shared/`. If you build from `frontend/` directory, Vite can't access `../shared/`.

## Alpine vs Slim Base Images

**node:22-alpine** (~180MB):
- Pros: Smallest Node.js image, fast layer pulls, minimal attack surface
- Cons: Uses musl libc instead of glibc; some native modules fail to compile or run (node-gyp, binary addons)
- Best for: Pure JavaScript projects, Vite/React/Vue frontends (no native deps)

**node:22-slim** (~250MB):
- Pros: Uses glibc; broader compatibility with native modules
- Cons: Larger image, slower pulls
- Best for: Projects with native dependencies (sharp, canvas, sqlite3)

**nginx:alpine** (~40MB):
- Pros: Smallest nginx image, sufficient for static serving + reverse proxy
- Cons: None for this use case
- Best for: Frontend runtime (always use alpine for nginx)

## Security Considerations

**Remove .git in build stage**: `RUN git rev-parse HEAD > gitsha && rm -rf .git` captures commit SHA for version tagging, then deletes .git to avoid leaking repo history into image layers.

**Don't copy secrets**: Never `COPY .env` or `COPY secrets/` into the image. Secrets should be passed at runtime via env vars or mounted volumes (k8s Secrets, Cloud Run secrets).

**.dockerignore**: Always exclude `node_modules/`, `.git/`, `.env*`, `dist/`, `*.log` from build context to avoid leaking secrets and bloating context size.

**Non-root user (optional)**: Nginx runs as root by default (to bind port 80); switching to non-root requires `listen 8080` and `pid /tmp/nginx.pid;`. Cloud Run and many k8s clusters enforce non-root via platform-level user namespacing, so adding `USER` in Dockerfile is often redundant.
