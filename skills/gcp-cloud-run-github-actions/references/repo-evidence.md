# Repo Evidence

Genericized snippets from real production GitHub Actions workflows deploying to Cloud Run. All internal names, project IDs, registry hosts, and service names have been replaced with placeholders.

## Workflow file structure

```
.github/
  workflows/
    deploy-dev.yml       # Development environment
    deploy-staging.yml   # Staging environment
    deploy-prod.yml      # Production environment
```

## Authentication step

```yaml
- id: auth
  uses: google-github-actions/auth@v2
  with:
    credentials_json: "${{ vars.GCP_SA_KEY }}"
    project_id: ${{ vars.GCP_PROJECT_ID }}
```

From: Multiple workflows across repositories

## Setup gcloud and Docker

```yaml
- uses: google-github-actions/setup-gcloud@v2
  with:
    project_id: ${{ vars.GCP_PROJECT_ID }}

- name: Configure Docker
  run: gcloud auth configure-docker <registry-host> --quiet
```

From: Multiple workflows across repositories

Registry hosts observed:
- `asia.gcr.io` (legacy GCR, Asia region)
- `us-docker.pkg.dev` (Artifact Registry)

## Image existence check pattern

```yaml
- name: Check if image exists
  id: check-image
  run: |
    if docker manifest inspect <registry>/<path>/backend:${{ github.sha }} > /dev/null 2>&1; then
      echo "exists=true" >> $GITHUB_OUTPUT
    else
      echo "exists=false" >> $GITHUB_OUTPUT
    fi

- name: Build and push Docker image
  if: steps.check-image.outputs.exists == 'false'
  run: |
    cd backend
    docker build \
      -t <registry>/<path>/backend:${{ github.sha }} .
    docker push <registry>/<path>/backend:${{ github.sha }}
```

From: `.github/workflows/deploy-{dev,staging,prod}.yml` in multiple repositories

## Backend deployment with full configuration

```yaml
- name: Deploy server to Cloud Run
  run: |
    gcloud run deploy my-backend \
      --image <registry>/<path>/backend:${{ github.sha }} \
      --platform managed \
      --region ${{ vars.GCP_REGION }} \
      --allow-unauthenticated \
      --port 8000 \
      --memory ${{ vars.BACKEND_MEMORY || '2Gi' }} \
      --cpu ${{ vars.BACKEND_CPU || '2' }} \
      --min-instances ${{ vars.BACKEND_MIN_INSTANCES || '1' }} \
      --max-instances ${{ vars.BACKEND_MAX_INSTANCES || '10' }} \
      --timeout 600 \
      --concurrency 100 \
      --add-cloudsql-instances ${{ vars.CLOUDSQL_INSTANCE_CONNECTION }} \
      --vpc-connector ${{ vars.VPC_CONNECTOR }} \
      --service-account ${{ vars.GCP_SA_NAME }} \
      --set-env-vars="ENVIRONMENT=production,\
        MODE=server,\
        POSTGRES_HOST=/cloudsql/${{ vars.CLOUDSQL_INSTANCE_CONNECTION }},\
        POSTGRES_USER=${{ vars.POSTGRES_USER }},\
        POSTGRES_PASSWORD=${{ vars.POSTGRES_PASSWORD }},\
        POSTGRES_DB=${{ vars.POSTGRES_DB }},\
        REDIS_URL=${{ vars.REDIS_URL }},\
        TEMPORAL_HOST=${{ vars.TEMPORAL_HOST }},\
        TEMPORAL_PORT=${{ vars.TEMPORAL_PORT }},\
        TEMPORAL_NAMESPACE=${{ vars.TEMPORAL_NAMESPACE }},\
        TEMPORAL_API_KEY=${{ vars.TEMPORAL_API_KEY }},\
        TEMPORAL_ENABLED=true,\
        JWT_SECRET_KEY=${{ vars.JWT_SECRET_KEY }},\
        OPENAI_API_KEY=${{ vars.OPENAI_API_KEY }},\
        ANTHROPIC_API_KEY=${{ vars.ANTHROPIC_API_KEY }},\
        GOOGLE_CLOUD_PROJECT=${{ vars.GOOGLE_CLOUD_PROJECT }},\
        GCS_BUCKET=${{ vars.GCS_BUCKET }},\
        LANGFUSE_PUBLIC_KEY=${{ vars.LANGFUSE_PUBLIC_KEY }},\
        LANGFUSE_SECRET_KEY=${{ vars.LANGFUSE_SECRET_KEY }},\
        LANGFUSE_HOST=${{ vars.LANGFUSE_HOST }},\
        SENTRY_DSN=${{ vars.SENTRY_DSN }}" \
      --ingress all
```

From: `.github/workflows/deploy-prod.yml` in a production application repository

## Worker deployment (reusing backend image)

```yaml
deploy-worker:
  name: Deploy Worker to Cloud Run
  runs-on: ubuntu-latest
  environment: production
  needs: deploy-backend  # waits for backend to ensure image exists
  steps:
    - uses: actions/checkout@v4

    - id: auth
      uses: google-github-actions/auth@v2
      with:
        credentials_json: "${{ vars.GCP_SA_KEY }}"
        project_id: ${{ vars.GCP_PROJECT_ID }}

    - uses: google-github-actions/setup-gcloud@v2
      with:
        project_id: ${{ vars.GCP_PROJECT_ID }}

    - name: Configure Docker
      run: gcloud auth configure-docker <registry-host> --quiet

    - name: Deploy worker to Cloud Run
      run: |
        gcloud run deploy my-worker \
          --image <registry>/<path>/backend:${{ github.sha }} \
          --platform managed \
          --region ${{ vars.GCP_REGION }} \
          --no-allow-unauthenticated \
          --memory ${{ vars.WORKER_MEMORY || '8Gi' }} \
          --cpu ${{ vars.WORKER_CPU || '4' }} \
          --min-instances ${{ vars.WORKER_MIN_INSTANCES || '1' }} \
          --max-instances ${{ vars.WORKER_MAX_INSTANCES || '10' }} \
          --timeout 3600 \
          --add-cloudsql-instances ${{ vars.CLOUDSQL_INSTANCE_CONNECTION }} \
          --vpc-connector ${{ vars.VPC_CONNECTOR }} \
          --service-account ${{ vars.GCP_SA_NAME }} \
          --set-env-vars="ENVIRONMENT=production,\
            MODE=worker,\
            POSTGRES_HOST=/cloudsql/${{ vars.CLOUDSQL_INSTANCE_CONNECTION }},\
            POSTGRES_USER=${{ vars.POSTGRES_USER }},\
            POSTGRES_PASSWORD=${{ vars.POSTGRES_PASSWORD }},\
            POSTGRES_DB=${{ vars.POSTGRES_DB }},\
            REDIS_URL=${{ vars.REDIS_URL }},\
            TEMPORAL_HOST=${{ vars.TEMPORAL_HOST }},\
            TEMPORAL_PORT=${{ vars.TEMPORAL_PORT }},\
            TEMPORAL_NAMESPACE=${{ vars.TEMPORAL_NAMESPACE }},\
            TEMPORAL_API_KEY=${{ vars.TEMPORAL_API_KEY }},\
            TEMPORAL_ENABLED=true" \
          --ingress all
```

From: `.github/workflows/deploy-prod.yml` in a production application repository

Pattern: Worker reuses backend image but sets `MODE=worker` and uses higher memory/CPU, longer timeout, and `--no-allow-unauthenticated`.

## Frontend deployment with build args

```yaml
- name: Check if image exists
  id: check-image
  run: |
    if docker manifest inspect <registry>/<path>/frontend:${{ github.sha }} > /dev/null 2>&1; then
      echo "exists=true" >> $GITHUB_OUTPUT
    else
      echo "exists=false" >> $GITHUB_OUTPUT
    fi

- name: Build and push Docker image
  if: steps.check-image.outputs.exists == 'false'
  run: |
    docker build -f frontend/Dockerfile \
      --build-arg VITE_API_BASE_URL=${{ vars.BACKEND_BASE_URL }}/api/v1 \
      --build-arg VITE_APP_NAME=MyApp \
      --build-arg VITE_SENTRY_DSN=${{ vars.VITE_SENTRY_DSN }} \
      --build-arg VITE_APP_ENV=production \
      -t <registry>/<path>/frontend:${{ github.sha }} .
    docker push <registry>/<path>/frontend:${{ github.sha }}

- name: Deploy frontend to Cloud Run
  run: |
    gcloud run deploy my-frontend \
      --image <registry>/<path>/frontend:${{ github.sha }} \
      --platform managed \
      --region ${{ vars.GCP_REGION }} \
      --allow-unauthenticated \
      --port 80 \
      --memory 512Mi \
      --cpu 1 \
      --min-instances ${{ vars.FRONTEND_MIN_INSTANCES || '1' }} \
      --max-instances ${{ vars.FRONTEND_MAX_INSTANCES || '5' }} \
      --set-env-vars="BACKEND_URL=${{ vars.BACKEND_BASE_URL }}" \
      --ingress all
```

From: `.github/workflows/deploy-prod.yml` in a production application repository

Pattern: Frontend uses build args (`--build-arg VITE_*`) during Docker build for Vite-based apps. Note minimal runtime env vars.

## Next.js app deployment with build args

```yaml
- name: Build and push Docker image
  if: steps.check-image.outputs.exists == 'false'
  run: |
    docker build \
      -f app/Dockerfile \
      --build-arg API_KEY=${{ vars.API_KEY }} \
      --build-arg TENANT_ID=${{ vars.TENANT_ID }} \
      --build-arg NEXT_PUBLIC_API_BASE_URL=${{ vars.BACKEND_BASE_URL }} \
      -t <registry>/<path>/app:${{ github.sha }} .
    docker push <registry>/<path>/app:${{ github.sha }}

- name: Deploy app to Cloud Run
  run: |
    gcloud run deploy my-app \
      --image <registry>/<path>/app:${{ github.sha }} \
      --platform managed \
      --region ${{ vars.GCP_REGION }} \
      --allow-unauthenticated \
      --port 3000 \
      --memory 512Mi \
      --cpu 1 \
      --min-instances ${{ vars.APP_MIN_INSTANCES || '0' }} \
      --max-instances ${{ vars.APP_MAX_INSTANCES || '3' }} \
      --ingress all
```

From: `.github/workflows/deploy-prod.yml` in a production application repository

Pattern: Next.js apps use `--build-arg NEXT_PUBLIC_*` for client-side env vars and `--build-arg` (no `NEXT_PUBLIC_` prefix) for server-side build-time vars.

## Post-deploy sanity check job

```yaml
sanity-check:
  name: Post-Deploy Sanity Check
  runs-on: ubuntu-latest
  environment: production
  needs: [deploy-backend, deploy-worker, deploy-frontend]
  steps:
    - uses: actions/checkout@v4

    - uses: actions/setup-python@v5
      with:
        python-version: "3.11"

    - name: Install dependencies
      run: pip install httpx

    - name: Run sanity checks
      run: python scripts/sanity_check.py ${{ vars.FRONTEND_URL }}
      env:
        BACKEND_URL: ${{ vars.BACKEND_BASE_URL }}
        DEMO_STORE_URL: ${{ vars.DEMO_STORE_URL }}
```

From: `.github/workflows/deploy-{dev,staging,prod}.yml` in multiple repositories

## Sanity check script structure

```python
#!/usr/bin/env python3
"""Post-deployment sanity check for Cloud Run services.

Usage: ./scripts/sanity_check.py <base-url>
Example: ./scripts/sanity_check.py https://my-frontend-xyz.run.app

Runs against live URLs. Non-destructive (read-only except login).

Requires: Python 3.9+, httpx (pip install httpx)
Optional env vars:
  BACKEND_URL    — override backend URL (default: derived from base-url)
  DEMO_STORE_URL — override demo store URL (default: skipped if not set)
"""
import os
import sys

import httpx

# Demo credentials (from seed data)
EMAIL = "demo@example.com"
PASSWORD = "demo1234"


class SanityChecker:
    def __init__(self, base_url: str, backend_url: str | None, demo_store_url: str | None):
        self.base_url = base_url.rstrip("/")
        self.api = f"{backend_url.rstrip('/')}/api/v1" if backend_url else f"{self.base_url}/api/v1"
        self.demo_store_url = demo_store_url.rstrip("/") if demo_store_url else None
        self.passed = 0
        self.failed = 0
        self.warnings = 0
        self.client = httpx.Client(timeout=10, follow_redirects=True)

    def check(self, name: str, fn) -> bool:
        try:
            fn()
            print(f"  [PASS] {name}")
            self.passed += 1
            return True
        except Exception:
            print(f"  [FAIL] {name}")
            self.failed += 1
            return False

    def warn_check(self, name: str, fn):
        try:
            fn()
            print(f"  [PASS] {name}")
            self.passed += 1
        except Exception:
            print(f"  [WARN] {name} (non-critical)")
            self.warnings += 1

    def run(self) -> int:
        print("=== Production Sanity Check ===")
        print(f"  Frontend: {self.base_url}")
        print(f"  Backend:  {self.api}")
        print(f"  Demo Store: {self.demo_store_url or 'skipped'}")
        print()

        # --- 1. Frontend ---
        print("--- Frontend ---")
        self.check(
            "Frontend serves SPA",
            lambda: self._assert_contains(self.client.get(f"{self.base_url}/"), '<div id="root">'),
        )

        # --- 2. Backend ---
        print()
        print(f"--- Backend API ({self.api}) ---")
        self.check(
            "Backend responds",
            lambda: self._assert_json_key(self.client.get(f"{self.api}/dev/config"), "environment"),
        )

        # --- 3. Auth flow ---
        print()
        print("--- Auth Flow ---")
        token = self._login()
        if not token:
            print("  [FAIL] Login failed (demo account)")
            self.failed += 1
            self._print_results()
            print("Aborting -- cannot test authenticated endpoints without a token")
            return 1

        print("  [PASS] Login succeeds (demo account)")
        self.passed += 1
        auth_headers = {"Authorization": f"Bearer {token}"}

        self.check(
            "GET /users/me returns user",
            lambda: self._assert_json_key(self.client.get(f"{self.api}/users/me", headers=auth_headers), "email"),
        )

        # --- Results ---
        self._print_results()
        return 0 if self.failed == 0 else 1

    # --- Helpers ---

    def _login(self) -> str | None:
        try:
            resp = self.client.post(
                f"{self.api}/auth/login",
                json={"email": EMAIL, "password": PASSWORD},
            )
            resp.raise_for_status()
            return resp.json().get("access_token")
        except Exception:
            return None

    def _assert_ok(self, resp: httpx.Response):
        resp.raise_for_status()

    def _assert_contains(self, resp: httpx.Response, text: str):
        resp.raise_for_status()
        if text not in resp.text:
            raise AssertionError(f"Response does not contain '{text}'")

    def _assert_json_key(self, resp: httpx.Response, key: str):
        resp.raise_for_status()
        data = resp.json()
        if key not in data:
            raise AssertionError(f"Key '{key}' not in response")

    def _print_results(self):
        print()
        print("===========================================")
        print(f"  Results: {self.passed} passed, {self.failed} failed, {self.warnings} warnings")
        print("===========================================")


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <base-url>")
        sys.exit(1)

    base_url = sys.argv[1]
    backend_url = os.environ.get("BACKEND_URL") or None
    demo_store_url = os.environ.get("DEMO_STORE_URL") or None

    checker = SanityChecker(base_url, backend_url, demo_store_url)
    sys.exit(checker.run())


if __name__ == "__main__":
    main()
```

From: `scripts/sanity_check.py` in a production application repository (genericized)

Pattern: The script:
- Accepts frontend URL as CLI arg
- Reads optional `BACKEND_URL` and `DEMO_STORE_URL` from environment
- Checks frontend serves SPA (`<div id="root">`)
- Validates backend responds to config/health endpoints
- Tests auth flow (login with demo credentials)
- Validates core data endpoints return expected structure
- Returns non-zero exit code on failure

## Environment-specific workflow triggers

```yaml
# Development
on:
  push:
    branches: [dev]
  workflow_dispatch:

# Staging
on:
  push:
    branches: [staging]
  workflow_dispatch:

# Production
on:
  workflow_dispatch:
  # push:
  #   branches: [main]  # uncomment for auto-deploy
```

From: `.github/workflows/deploy-{dev,staging,prod}.yml` in multiple repositories

Pattern: Dev and staging auto-deploy on push; production is manual-only until confidence is high.

## Resource settings per environment

From GitHub environment variables in production repositories:

### Development
- `BACKEND_MEMORY`: `2Gi`
- `BACKEND_CPU`: `2`
- `BACKEND_MIN_INSTANCES`: `0` (scale to zero)
- `BACKEND_MAX_INSTANCES`: `3`
- `WORKER_MEMORY`: `4Gi`
- `WORKER_MIN_INSTANCES`: `1`
- `FRONTEND_MIN_INSTANCES`: `0`

### Staging
- `BACKEND_MEMORY`: `2Gi`
- `BACKEND_CPU`: `2`
- `BACKEND_MIN_INSTANCES`: `1`
- `BACKEND_MAX_INSTANCES`: `5`
- `WORKER_MEMORY`: `4Gi`

### Production
- `BACKEND_MEMORY`: `4Gi`
- `BACKEND_CPU`: `2`
- `BACKEND_MIN_INSTANCES`: `1`
- `BACKEND_MAX_INSTANCES`: `10`
- `WORKER_MEMORY`: `8Gi`
- `WORKER_CPU`: `4`
- `WORKER_MAX_INSTANCES`: `10`

Pattern: Production uses more memory, higher max instances, and never scales to zero.
