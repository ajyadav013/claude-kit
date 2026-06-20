# .dockerignore and Build Secrets

Conventions for excluding files from the Docker build context and handling build-time authentication secrets.

## .dockerignore Conventions

**.dockerignore** excludes files from the build context sent to the Docker daemon. This:
- **Reduces build context size** (faster uploads to Docker daemon)
- **Speeds up builds** (fewer files to consider)
- **Prevents secrets from leaking** (`.env`, `.pem` files, private keys)
- **Reduces final image size** (if excluded files would have been COPYied)

### Standard .dockerignore Template

Derived from production services (Python and Node.js backends):

```
# Version control
.git
.gitignore

# Dependencies (not needed in image)
node_modules
npm-debug.log*
yarn-debug.log*
__pycache__
*.pyc
*.pyo
.venv
venv
env
ENV

# Tests and coverage
tests/
test/
*.test.js
*.spec.js
.pytest_cache/
.coverage
htmlcov/
coverage/
*.lcov

# Development and secrets
.env
.env.local
.env.development.local
.env.test.local
.env.production.local
.env.secrets
.env.secrets.*
*.key
*.pem

# IDE and editors
.vscode
.idea
*.swp
*.swo
*~

# OS generated files
.DS_Store
.DS_Store?
._*
.Spotlight-V100
.Trashes
ehthumbs.db
Thumbs.db

# Docker files (don't copy Docker files into the image)
Dockerfile*
docker-compose*
.dockerignore

# Documentation (unless your image serves docs)
*.md
docs/

# Logs and runtime artifacts
*.log
logs/
screenshots/
videos/
test-results/
allure-results/
allure-report/

# Build artifacts
dist/
build/
*.egg-info/
*.whl
target/

# Temporary files
*.tmp
*.temp
temp/
tmp/

# Database files (local dev only)
*.sqlite
*.db
data/
```

### Include Exceptions

Use `!` to re-include specific files after a broader exclusion:

```
# Exclude all markdown
*.md

# But include the README
!README.md
```

### Python-Specific Additions

```
# Python cache and artifacts
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg
MANIFEST

# Virtual environments
venv/
env/
ENV/
.venv/

# Test artifacts
.pytest_cache/
.coverage
htmlcov/
```

### Node.js-Specific Additions

```
# Node.js dependencies
node_modules
npm-debug.log*
yarn-debug.log*
yarn-error.log*

# Testing
coverage

# Optional npm cache directory
.npm

# ESLint cache
.eslintcache

# Runtime data
pids
*.pid
*.seed
*.pid.lock
```

## Build-Time Secrets: ARG Anti-Pattern

**Problem**: Dockerfiles need authentication tokens to pull from private registries, fetch private scripts, or install from private package indexes. Using `ARG` to pass secrets is common but dangerous.

**Critical Anti-Pattern**: **NEVER echo, print, or write a build-arg secret to a RUN layer or the console.**

### Why This is Dangerous

Docker layers are **immutable and visible** in:
- The final image (even if the layer is later discarded in a multi-stage build, it persists in the build cache)
- Build logs (printed to console and stored in CI/CD logs)
- Image history (`docker history <image>`)

**Example of the ANTI-PATTERN** (observed in production code):

```dockerfile
FROM python:3.11-slim

ARG PRIVATE_REGISTRY_TOKEN

# ❌ ANTI-PATTERN: This prints the token to build logs
RUN echo "===== TOKEN START =====" && \
    printf "%s\n" "$PRIVATE_REGISTRY_TOKEN" && \
    echo "===== TOKEN END ====="

# ❌ ANTI-PATTERN: This writes the token to a file in an image layer
RUN echo "===== TOKEN START =====" && \
    printf "%s\n" "$PRIVATE_REGISTRY_TOKEN" > /tmp/token.txt && \
    cat /tmp/token.txt && \
    echo "===== TOKEN END ====="

# ❌ ANTI-PATTERN: Even this debug line bakes the token into logs
RUN echo 'DEBUG_LITERAL_$PRIVATE_REGISTRY_TOKEN'

# ❌ ANTI-PATTERN: Using the token is fine, but printing it is not
RUN curl -H "Authorization: Basic $PRIVATE_REGISTRY_TOKEN" \
         https://internal-registry.example.com/scripts/setup.sh \
         -o /tmp/setup.sh && \
    echo "===== DOWNLOADED SCRIPT =====" && \
    cat /tmp/setup.sh && \  # ❌ If the script echoes the token, it's leaked
    sh /tmp/setup.sh
```

**Why these are anti-patterns**:
- `echo "$PRIVATE_REGISTRY_TOKEN"` → token appears in build logs and CI/CD logs
- `printf "%s\n" "$PRIVATE_REGISTRY_TOKEN" > /tmp/token.txt` → token is baked into the image layer
- `cat /tmp/token.txt` → token appears in build logs
- Even `echo 'DEBUG_LITERAL_$PRIVATE_REGISTRY_TOKEN'` (with single quotes) appears in build logs and may be misread as exposing the token

### Correct ARG Usage

**Do**: Use the ARG without printing it:

```dockerfile
FROM python:3.11-slim

ARG PRIVATE_REGISTRY_TOKEN

# ✅ Correct: Use the token without printing it
RUN curl -H "Authorization: Bearer $PRIVATE_REGISTRY_TOKEN" \
         https://internal-registry.example.com/scripts/setup.sh \
         -o /tmp/setup.sh && \
    sh /tmp/setup.sh && \
    rm /tmp/setup.sh
```

**Do**: Install from a private package index:

```dockerfile
RUN pip install --no-cache-dir \
    --index-url https://:$PRIVATE_REGISTRY_TOKEN@internal-pypi.example.com/simple \
    -r requirements.txt
```

**Do**: Unset the ARG or use multi-stage builds to discard the builder stage:

```dockerfile
FROM python:3.11-slim AS builder

ARG PRIVATE_REGISTRY_TOKEN

RUN curl -H "Authorization: Bearer $PRIVATE_REGISTRY_TOKEN" \
         https://internal-registry.example.com/scripts/setup.sh \
         -o /tmp/setup.sh && \
    sh /tmp/setup.sh

# Runtime stage (no ARG, no token)
FROM python:3.11-slim
COPY --from=builder /app /app
WORKDIR /app
ENTRYPOINT ["python", "app.py"]
```

## Secure Alternative: BuildKit Secrets

**Best practice**: Use Docker BuildKit `--mount=type=secret` to pass secrets that never appear in layers or build history.

**Example**:

```dockerfile
# syntax=docker/dockerfile:1.4
FROM python:3.11-slim

RUN --mount=type=secret,id=registry_token \
    REGISTRY_TOKEN=$(cat /run/secrets/registry_token) && \
    curl -H "Authorization: Bearer $REGISTRY_TOKEN" \
         https://internal-registry.example.com/scripts/setup.sh \
         -o /tmp/setup.sh && \
    sh /tmp/setup.sh && \
    rm /tmp/setup.sh
```

**Build command**:

```bash
# Store the token in a file (NOT committed to git)
echo "your-token-here" > token.txt

# Build with BuildKit secret mount
docker buildx build --secret id=registry_token,src=token.txt -t app:latest .

# The token is never baked into layers or build logs
```

**Why this is better**:
- The secret is mounted into the build container at `/run/secrets/registry_token` **only during that RUN step**
- It's **never written to an image layer**
- It **never appears in build logs** (unless you explicitly `cat` it, which you shouldn't)
- The secret file is discarded after the RUN step completes

## Passing Build Args from CI/CD

**GitHub Actions example**:

```yaml
- name: Build base image
  run: |
    docker build -f Dockerfile.base \
      --build-arg PRIVATE_REGISTRY_TOKEN=${{ secrets.REGISTRY_TOKEN }} \
      -t registry.example.com/base-images/myservice-base:v1 .
```

**Never**:
- Commit the token to the repo
- Echo the token in the Dockerfile
- Print the token in CI/CD logs (`echo ${{ secrets.REGISTRY_TOKEN }}`)

**Do**:
- Store the token in GitHub Secrets
- Pass it via `--build-arg` (or `--secret` for BuildKit)
- Ensure the Dockerfile uses it without printing it
