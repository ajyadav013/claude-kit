# GitHub Actions Workflow Structure for Cloud Run

Patterns for structuring GitHub Actions workflows that deploy to Cloud Run, including authentication, multi-job pipelines, environment management, and post-deploy validation.

## Workflow triggers

```yaml
# Development: auto-deploy on push to dev branch
on:
  push:
    branches: [dev]
  workflow_dispatch:

# Staging: auto-deploy on push to staging branch
on:
  push:
    branches: [staging]
  workflow_dispatch:

# Production: manual deploy only (safer)
on:
  workflow_dispatch:
  # push:
  #   branches: [main]  # uncomment to enable auto-deploy
```

**Pattern**: Use `workflow_dispatch` to enable manual triggers via GitHub UI. Enable auto-deploy (`on: push`) for dev/staging but keep prod manual-only until confidence is high.

## GitHub Environments

```yaml
jobs:
  deploy-backend:
    runs-on: ubuntu-latest
    environment: production  # Links to GitHub environment settings
    steps:
      # ...
```

**Pattern**: Use GitHub Environments to:
- Scope secrets and variables per environment (dev/staging/prod)
- Enforce manual approval for production deployments (configure in repo settings)
- Enable deployment history and tracking

## Authentication to GCP

### Method 1: Service Account Key (simple but less secure)

```yaml
- id: auth
  uses: google-github-actions/auth@v2
  with:
    credentials_json: "${{ vars.GCP_SA_KEY }}"
    project_id: ${{ vars.GCP_PROJECT_ID }}
```

Store the service account JSON key in GitHub secrets (`vars.GCP_SA_KEY`). Simple but requires rotating long-lived keys.

### Method 2: Workload Identity Federation (recommended)

```yaml
- id: auth
  uses: google-github-actions/auth@v2
  with:
    workload_identity_provider: "${{ vars.GCP_WORKLOAD_IDENTITY_PROVIDER }}"
    service_account: "${{ vars.GCP_SERVICE_ACCOUNT }}"
    project_id: ${{ vars.GCP_PROJECT_ID }}
```

No long-lived keys; GitHub issues short-lived OIDC tokens that GCP exchanges for credentials. More secure but requires GCP Workload Identity Pool setup.

## Setup gcloud CLI

```yaml
- uses: google-github-actions/setup-gcloud@v2
  with:
    project_id: ${{ vars.GCP_PROJECT_ID }}
```

Configures gcloud CLI to use the authenticated credentials from the previous step.

## Configure Docker authentication

```yaml
- name: Configure Docker
  run: gcloud auth configure-docker <registry-host> --quiet
```

Common registry hosts:
- `gcr.io` (legacy Google Container Registry)
- `us.gcr.io`, `asia.gcr.io`, etc. (regional GCR)
- `us-docker.pkg.dev`, `asia-docker.pkg.dev`, etc. (Artifact Registry)

**Pattern**: Use Artifact Registry (modern) instead of GCR (legacy) for new projects.

## Image existence check

```yaml
- name: Check if image exists
  id: check-image
  run: |
    if docker manifest inspect <registry>/<image>:${{ github.sha }} > /dev/null 2>&1; then
      echo "exists=true" >> $GITHUB_OUTPUT
    else
      echo "exists=false" >> $GITHUB_OUTPUT
    fi

- name: Build and push Docker image
  if: steps.check-image.outputs.exists == 'false'
  run: |
    cd backend
    docker build -t <registry>/<image>:${{ github.sha }} .
    docker push <registry>/<image>:${{ github.sha }}
```

**Pattern**: Skip builds when images already exist. Useful for:
- Rebuilding a failed deployment without rebuilding the image
- Worker services that reuse backend images

## Multi-job pipeline structure

```yaml
jobs:
  deploy-backend:
    # builds and deploys backend image
    steps:
      - name: Build and push Docker image
        # ...
      - name: Deploy server to Cloud Run
        # ...

  deploy-worker:
    needs: deploy-backend  # waits for backend to ensure image exists
    steps:
      - name: Deploy worker to Cloud Run
        # reuses backend image, different MODE env var

  deploy-frontend:
    # builds and deploys frontend independently
    steps:
      - name: Build and push Docker image
        # ...
      - name: Deploy frontend to Cloud Run
        # ...

  sanity-check:
    needs: [deploy-backend, deploy-worker, deploy-frontend]  # waits for all
    steps:
      - name: Run sanity checks
        # validates services are healthy
```

**Pattern**: Use `needs:` to create dependencies between jobs. Backend builds first; worker reuses its image; sanity check runs after all deployments.

## Building frontend with build-time arguments

```yaml
- name: Build and push Docker image
  run: |
    docker build -f frontend/Dockerfile \
      --build-arg VITE_API_BASE_URL=${{ vars.BACKEND_BASE_URL }}/api/v1 \
      --build-arg VITE_APP_ENV=production \
      --build-arg VITE_SENTRY_DSN=${{ vars.VITE_SENTRY_DSN }} \
      -t <registry>/frontend:${{ github.sha }} .
    docker push <registry>/frontend:${{ github.sha }}
```

**Pattern**: Frontend frameworks (Vite, Create React App, Next.js) often require build-time environment variables (prefixed `VITE_`, `REACT_APP_`, `NEXT_PUBLIC_`). Pass them via `--build-arg` during Docker build.

## Deploying with environment variables

```yaml
- name: Deploy server to Cloud Run
  run: |
    gcloud run deploy my-backend \
      --image <registry>/backend:${{ github.sha }} \
      --set-env-vars="ENVIRONMENT=production,\
        MODE=server,\
        POSTGRES_HOST=/cloudsql/${{ vars.CLOUDSQL_INSTANCE_CONNECTION }},\
        POSTGRES_USER=${{ vars.POSTGRES_USER }},\
        POSTGRES_PASSWORD=${{ vars.POSTGRES_PASSWORD }},\
        POSTGRES_DB=${{ vars.POSTGRES_DB }},\
        REDIS_URL=${{ vars.REDIS_URL }},\
        JWT_SECRET_KEY=${{ vars.JWT_SECRET_KEY }},\
        GOOGLE_CLOUD_PROJECT=${{ vars.GOOGLE_CLOUD_PROJECT }},\
        GCS_BUCKET=${{ vars.GCS_BUCKET }},\
        LANGFUSE_PUBLIC_KEY=${{ vars.LANGFUSE_PUBLIC_KEY }},\
        LANGFUSE_SECRET_KEY=${{ vars.LANGFUSE_SECRET_KEY }},\
        LANGFUSE_HOST=${{ vars.LANGFUSE_HOST }},\
        SENTRY_DSN=${{ vars.SENTRY_DSN }}" \
      --region ${{ vars.GCP_REGION }} \
      --memory 2Gi \
      # ...
```

**Pattern**: Use `\` line continuation for readability. Group related env vars (database, observability, external APIs).

## Using GitHub variables with defaults

```yaml
--memory ${{ vars.BACKEND_MEMORY || '2Gi' }}
--cpu ${{ vars.BACKEND_CPU || '2' }}
--min-instances ${{ vars.BACKEND_MIN_INSTANCES || '1' }}
```

**Pattern**: Use `||` operator to provide default values when GitHub variables are not set. Enables environment-specific overrides without changing the workflow.

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

**Pattern**: Implement sanity checks as a Python script that:
- Checks frontend serves the SPA (`<div id="root">`)
- Validates backend responds to health/config endpoints
- Tests auth flow (login with demo credentials)
- Validates core data endpoints return expected structure
- Returns non-zero exit code on failure to fail the workflow

Example `scripts/sanity_check.py` structure:

```python
import httpx
import sys

def check_frontend(url):
    resp = httpx.get(url)
    assert '<div id="root">' in resp.text, "Frontend SPA not found"

def check_backend(api_url):
    resp = httpx.get(f"{api_url}/health")
    assert resp.status_code == 200, "Backend health check failed"

def check_auth(api_url):
    resp = httpx.post(f"{api_url}/auth/login", json={"email": "demo@example.com", "password": "demo1234"})
    assert "access_token" in resp.json(), "Login failed"
    return resp.json()["access_token"]

def main(frontend_url, backend_url):
    print("Running sanity checks...")
    check_frontend(frontend_url)
    check_backend(backend_url)
    token = check_auth(backend_url)
    print(f"All checks passed. Token: {token[:20]}...")

if __name__ == "__main__":
    main(sys.argv[1], sys.env["BACKEND_URL"])
```

## Complete multi-service workflow

```yaml
name: Deploy to GCP Cloud Run (Production)

on:
  workflow_dispatch:

jobs:
  deploy-backend:
    runs-on: ubuntu-latest
    environment: production
    steps:
      - uses: actions/checkout@v4
      - uses: google-github-actions/auth@v2
        with:
          credentials_json: "${{ vars.GCP_SA_KEY }}"
          project_id: ${{ vars.GCP_PROJECT_ID }}
      - uses: google-github-actions/setup-gcloud@v2
        with:
          project_id: ${{ vars.GCP_PROJECT_ID }}
      - run: gcloud auth configure-docker us-docker.pkg.dev --quiet
      - id: check-image
        run: |
          if docker manifest inspect us-docker.pkg.dev/${{ vars.GCP_PROJECT_ID }}/my-repo/backend:${{ github.sha }} > /dev/null 2>&1; then
            echo "exists=true" >> $GITHUB_OUTPUT
          else
            echo "exists=false" >> $GITHUB_OUTPUT
          fi
      - if: steps.check-image.outputs.exists == 'false'
        run: |
          cd backend
          docker build -t us-docker.pkg.dev/${{ vars.GCP_PROJECT_ID }}/my-repo/backend:${{ github.sha }} .
          docker push us-docker.pkg.dev/${{ vars.GCP_PROJECT_ID }}/my-repo/backend:${{ github.sha }}
      - run: |
          gcloud run deploy my-backend \
            --image us-docker.pkg.dev/${{ vars.GCP_PROJECT_ID }}/my-repo/backend:${{ github.sha }} \
            --platform managed \
            --region ${{ vars.GCP_REGION }} \
            --allow-unauthenticated \
            --port 8000 \
            --memory 2Gi \
            --cpu 2 \
            --min-instances 1 \
            --max-instances 10 \
            --timeout 600 \
            --set-env-vars="ENVIRONMENT=production,MODE=server,..."

  deploy-worker:
    runs-on: ubuntu-latest
    environment: production
    needs: deploy-backend
    steps:
      - uses: actions/checkout@v4
      - uses: google-github-actions/auth@v2
        with:
          credentials_json: "${{ vars.GCP_SA_KEY }}"
          project_id: ${{ vars.GCP_PROJECT_ID }}
      - uses: google-github-actions/setup-gcloud@v2
        with:
          project_id: ${{ vars.GCP_PROJECT_ID }}
      - run: |
          gcloud run deploy my-worker \
            --image us-docker.pkg.dev/${{ vars.GCP_PROJECT_ID }}/my-repo/backend:${{ github.sha }} \
            --platform managed \
            --region ${{ vars.GCP_REGION }} \
            --no-allow-unauthenticated \
            --memory 8Gi \
            --cpu 4 \
            --min-instances 1 \
            --max-instances 10 \
            --timeout 3600 \
            --set-env-vars="ENVIRONMENT=production,MODE=worker,..."

  deploy-frontend:
    runs-on: ubuntu-latest
    environment: production
    steps:
      - uses: actions/checkout@v4
      - uses: google-github-actions/auth@v2
        with:
          credentials_json: "${{ vars.GCP_SA_KEY }}"
          project_id: ${{ vars.GCP_PROJECT_ID }}
      - uses: google-github-actions/setup-gcloud@v2
        with:
          project_id: ${{ vars.GCP_PROJECT_ID }}
      - run: gcloud auth configure-docker us-docker.pkg.dev --quiet
      - id: check-image
        run: |
          if docker manifest inspect us-docker.pkg.dev/${{ vars.GCP_PROJECT_ID }}/my-repo/frontend:${{ github.sha }} > /dev/null 2>&1; then
            echo "exists=true" >> $GITHUB_OUTPUT
          else
            echo "exists=false" >> $GITHUB_OUTPUT
          fi
      - if: steps.check-image.outputs.exists == 'false'
        run: |
          docker build -f frontend/Dockerfile \
            --build-arg VITE_API_BASE_URL=${{ vars.BACKEND_BASE_URL }}/api/v1 \
            --build-arg VITE_APP_ENV=production \
            -t us-docker.pkg.dev/${{ vars.GCP_PROJECT_ID }}/my-repo/frontend:${{ github.sha }} .
          docker push us-docker.pkg.dev/${{ vars.GCP_PROJECT_ID }}/my-repo/frontend:${{ github.sha }}
      - run: |
          gcloud run deploy my-frontend \
            --image us-docker.pkg.dev/${{ vars.GCP_PROJECT_ID }}/my-repo/frontend:${{ github.sha }} \
            --platform managed \
            --region ${{ vars.GCP_REGION }} \
            --allow-unauthenticated \
            --port 80 \
            --memory 512Mi \
            --cpu 1 \
            --min-instances 1 \
            --max-instances 5

  sanity-check:
    runs-on: ubuntu-latest
    environment: production
    needs: [deploy-backend, deploy-worker, deploy-frontend]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install httpx
      - run: python scripts/sanity_check.py ${{ vars.FRONTEND_URL }}
        env:
          BACKEND_URL: ${{ vars.BACKEND_BASE_URL }}
```

## Environment-specific settings

Use GitHub environment variables to configure per-environment settings:

| Variable | Dev | Staging | Prod |
|----------|-----|---------|------|
| `BACKEND_MIN_INSTANCES` | `0` | `1` | `1` |
| `BACKEND_MAX_INSTANCES` | `3` | `5` | `10` |
| `BACKEND_MEMORY` | `2Gi` | `2Gi` | `4Gi` |
| `WORKER_MEMORY` | `4Gi` | `4Gi` | `8Gi` |
| `FRONTEND_MIN_INSTANCES` | `0` | `1` | `1` |

**Pattern**: Scale to zero in dev (`min-instances=0`) to save costs. Keep at least one instance running in staging/prod to avoid cold starts.
