---
name: gcp-cloud-run-github-actions
description: Standardize GitHub Actions workflows for deploying containerized services to Google Cloud Run with authentication, image caching, multi-job pipelines (backend, worker, frontend), VPC/Cloud SQL integration, environment variables, and post-deploy validation. Use when building CI/CD pipelines for Cloud Run, setting up multi-service deployments with shared images, configuring VPC connectors and Cloud SQL instances, or adding deployment sanity checks.
---

Standardize GitHub Actions workflows for deploying containerized services to Google Cloud Run with authentication, image caching, multi-job pipelines, and post-deploy validation.

## When to use

- Setting up CI/CD pipelines to deploy services to Google Cloud Run
- Deploying multiple services (backend, worker, frontend) from a monorepo
- Configuring Cloud Run services with VPC connectors, Cloud SQL instances, and environment variables
- Implementing one-image-many-roles pattern (same Docker image, different MODE env var)
- Optimizing build times by skipping rebuilds when images already exist in the registry
- Adding post-deployment sanity checks to validate service health
- Configuring per-environment (dev/staging/prod) Cloud Run settings (min/max instances, memory, CPU)
- Authenticating GitHub Actions to GCP using service account keys or Workload Identity Federation
- Deploying frontend apps with build-time environment variables

## Core conventions

1. **GitHub Actions authentication via `google-github-actions/auth@v2`**: use `credentials_json: "${{ vars.GCP_SA_KEY }}"` for service account key-based auth, or `workload_identity_provider` + `service_account` for Workload Identity Federation (preferred for security). Set `project_id: ${{ vars.GCP_PROJECT_ID }}` to scope the session.

2. **Setup gcloud CLI via `google-github-actions/setup-gcloud@v2`**: after authentication, configure gcloud with `project_id: ${{ vars.GCP_PROJECT_ID }}` to enable `gcloud run deploy` commands.

3. **Configure Docker for GCR/Artifact Registry**: run `gcloud auth configure-docker <registry-host> --quiet` (e.g., `asia.gcr.io`, `us-docker.pkg.dev`) to authenticate Docker for pushing images to the container registry.

4. **Image existence check with `docker manifest inspect`**: before building, check if the image already exists in the registry using `docker manifest inspect <registry>/<image>:<tag> > /dev/null 2>&1`. Set a step output `exists=true/false` and conditionally run the build step only if `exists == 'false'`. Tag images with `${{ github.sha }}` for commit-based reproducibility.

5. **Build and push Docker images**: use `docker build -t <registry>/<image>:<tag> .` followed by `docker push <registry>/<image>:<tag>`. For frontend apps, pass build-time environment variables via `--build-arg VITE_API_BASE_URL=...` or equivalent. Use `-f <path>/Dockerfile` to specify Dockerfile location for monorepos.

6. **Deploy to Cloud Run with `gcloud run deploy`**: core flags include:
   - `--image <registry>/<image>:<tag>` — the container image to deploy
   - `--platform managed` — use fully managed Cloud Run
   - `--region <region>` — deployment region (e.g., `us-central1`, `asia-southeast1`)
   - `--allow-unauthenticated` or `--no-allow-unauthenticated` — public vs private service
   - `--port <port>` — container port (e.g., `8000` for backend, `80` for frontend)
   - `--memory <size>` — memory allocation (e.g., `2Gi`, `512Mi`)
   - `--cpu <count>` — CPU count (e.g., `2`, `4`)
   - `--min-instances <n>` and `--max-instances <n>` — autoscaling bounds (use `0` for dev to scale to zero)
   - `--timeout <seconds>` — request timeout (default 300, max 3600 for worker jobs)
   - `--concurrency <n>` — concurrent requests per instance (default 80, adjust based on workload)
   - `--add-cloudsql-instances <connection-name>` — attach Cloud SQL instance (format: `project:region:instance`)
   - `--vpc-connector <name>` — attach VPC connector for private network access
   - `--service-account <email>` — service account for the Cloud Run service
   - `--set-env-vars="KEY=value,..."` — environment variables (comma-separated)
   - `--ingress all|internal|internal-and-cloud-load-balancing` — ingress control

7. **One-image-many-roles pattern with MODE env var**: deploy the same Docker image to multiple Cloud Run services (e.g., `backend` and `worker`) and differentiate behavior via `MODE=server` vs `MODE=worker` environment variable. The application startup logic reads `MODE` and starts the appropriate process (FastAPI server vs Temporal/Celery worker).

8. **Environment variables via `--set-env-vars`**: pass config as a single comma-separated string (use line continuation `\` for readability). Common patterns:
   - `ENVIRONMENT=production|development|staging`
   - `MODE=server|worker` (for one-image-many-roles)
   - `POSTGRES_HOST=/cloudsql/<connection-name>` (Cloud SQL socket path)
   - `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` (database credentials)
   - `REDIS_URL`, `TEMPORAL_HOST`, `TEMPORAL_API_KEY` (external service connections)
   - `GOOGLE_CLOUD_PROJECT`, `GCS_BUCKET` (GCP resource identifiers)
   - Standard observability keys: `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`, `SENTRY_DSN`
   - Third-party API keys: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `SENDGRID_API_KEY`

9. **GitHub environment variables via `vars.*` and `secrets.*`**: use GitHub environment-scoped variables (`vars.GCP_PROJECT_ID`, `vars.BACKEND_MEMORY`) for non-sensitive config and secrets (`secrets.JWT_SECRET_KEY`) for sensitive values. Prefer `vars` over `secrets` when possible to enable visibility in workflow logs. Use default values via `${{ vars.BACKEND_MEMORY || '2Gi' }}`.

10. **Multi-job pipeline with job dependencies**: structure workflows as parallel or sequential jobs (e.g., `deploy-backend`, `deploy-worker`, `deploy-frontend`, `sanity-check`). Use `needs: [deploy-backend]` to create dependencies (e.g., worker waits for backend, sanity check waits for all deployments). Reuse the same image for multiple services (backend/worker share one image).

11. **Post-deploy sanity check job**: add a final job that runs health checks against deployed services. Use `needs: [deploy-backend, deploy-worker, deploy-frontend]` to wait for all deployments. Implement as a Python script (`scripts/sanity_check.py`) that performs non-destructive read-only checks: frontend serves SPA, backend responds, auth flow works, core data endpoints return expected structure. Pass service URLs via environment variables (`BACKEND_URL`, `FRONTEND_URL`, `DEMO_STORE_URL`).

12. **Environment-specific workflows**: separate workflow files for each environment (`deploy-dev.yml`, `deploy-staging.yml`, `deploy-prod.yml`) with different triggers:
   - Dev: `on: push: branches: [dev]` + `workflow_dispatch`
   - Staging: `on: push: branches: [staging]` + `workflow_dispatch`
   - Prod: `on: workflow_dispatch` only (manual deployments), or `on: push: branches: [main]` if auto-deploy is desired

13. **GitHub environment protection**: use `environment: production|staging|development` on jobs to enforce environment-specific secrets/variables and optionally require manual approval for production deployments via branch protection rules.

14. **Conditional rebuild optimization**: since `docker manifest inspect` checks if an image exists, you can skip rebuilds entirely for services that reuse images (e.g., worker reuses backend image). Only the first service in the pipeline builds; subsequent services just reference the existing image.

## Skeleton / example

```yaml
name: Deploy to GCP Cloud Run (Production)

on:
  workflow_dispatch:
  # push:
  #   branches: [main]  # uncomment for auto-deploy

jobs:
  deploy-backend:
    name: Deploy Backend to Cloud Run
    runs-on: ubuntu-latest
    environment: production
    steps:
      - uses: actions/checkout@v4

      # Authenticate to GCP (service account key method)
      - id: auth
        uses: google-github-actions/auth@v2
        with:
          credentials_json: "${{ vars.GCP_SA_KEY }}"
          project_id: ${{ vars.GCP_PROJECT_ID }}

      # Setup gcloud CLI
      - uses: google-github-actions/setup-gcloud@v2
        with:
          project_id: ${{ vars.GCP_PROJECT_ID }}

      # Configure Docker for registry
      - name: Configure Docker
        run: gcloud auth configure-docker us-docker.pkg.dev --quiet

      # Check if image already exists
      - name: Check if image exists
        id: check-image
        run: |
          if docker manifest inspect us-docker.pkg.dev/${{ vars.GCP_PROJECT_ID }}/my-repo/backend:${{ github.sha }} > /dev/null 2>&1; then
            echo "exists=true" >> $GITHUB_OUTPUT
          else
            echo "exists=false" >> $GITHUB_OUTPUT
          fi

      # Build and push only if image doesn't exist
      - name: Build and push Docker image
        if: steps.check-image.outputs.exists == 'false'
        run: |
          cd backend
          docker build \
            -t us-docker.pkg.dev/${{ vars.GCP_PROJECT_ID }}/my-repo/backend:${{ github.sha }} .
          docker push us-docker.pkg.dev/${{ vars.GCP_PROJECT_ID }}/my-repo/backend:${{ github.sha }}

      # Deploy backend server
      - name: Deploy server to Cloud Run
        run: |
          gcloud run deploy my-backend \
            --image us-docker.pkg.dev/${{ vars.GCP_PROJECT_ID }}/my-repo/backend:${{ github.sha }} \
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
              JWT_SECRET_KEY=${{ vars.JWT_SECRET_KEY }},\
              GOOGLE_CLOUD_PROJECT=${{ vars.GOOGLE_CLOUD_PROJECT }},\
              GCS_BUCKET=${{ vars.GCS_BUCKET }},\
              LANGFUSE_PUBLIC_KEY=${{ vars.LANGFUSE_PUBLIC_KEY }},\
              LANGFUSE_SECRET_KEY=${{ vars.LANGFUSE_SECRET_KEY }},\
              LANGFUSE_HOST=${{ vars.LANGFUSE_HOST }},\
              SENTRY_DSN=${{ vars.SENTRY_DSN }}" \
            --ingress all

  deploy-worker:
    name: Deploy Worker to Cloud Run
    runs-on: ubuntu-latest
    environment: production
    needs: deploy-backend  # wait for backend to ensure image exists
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
        run: gcloud auth configure-docker us-docker.pkg.dev --quiet

      # Deploy worker (reuses backend image, different MODE)
      - name: Deploy worker to Cloud Run
        run: |
          gcloud run deploy my-worker \
            --image us-docker.pkg.dev/${{ vars.GCP_PROJECT_ID }}/my-repo/backend:${{ github.sha }} \
            --platform managed \
            --region ${{ vars.GCP_REGION }} \
            --no-allow-unauthenticated \
            --memory ${{ vars.WORKER_MEMORY || '4Gi' }} \
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
              REDIS_URL=${{ vars.REDIS_URL }}" \
            --ingress all

  deploy-frontend:
    name: Deploy Frontend to Cloud Run
    runs-on: ubuntu-latest
    environment: production
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
        run: gcloud auth configure-docker us-docker.pkg.dev --quiet

      - name: Check if image exists
        id: check-image
        run: |
          if docker manifest inspect us-docker.pkg.dev/${{ vars.GCP_PROJECT_ID }}/my-repo/frontend:${{ github.sha }} > /dev/null 2>&1; then
            echo "exists=true" >> $GITHUB_OUTPUT
          else
            echo "exists=false" >> $GITHUB_OUTPUT
          fi

      # Build frontend with build-time env vars
      - name: Build and push Docker image
        if: steps.check-image.outputs.exists == 'false'
        run: |
          docker build -f frontend/Dockerfile \
            --build-arg VITE_API_BASE_URL=${{ vars.BACKEND_BASE_URL }}/api/v1 \
            --build-arg VITE_APP_ENV=production \
            --build-arg VITE_SENTRY_DSN=${{ vars.VITE_SENTRY_DSN }} \
            -t us-docker.pkg.dev/${{ vars.GCP_PROJECT_ID }}/my-repo/frontend:${{ github.sha }} .
          docker push us-docker.pkg.dev/${{ vars.GCP_PROJECT_ID }}/my-repo/frontend:${{ github.sha }}

      - name: Deploy frontend to Cloud Run
        run: |
          gcloud run deploy my-frontend \
            --image us-docker.pkg.dev/${{ vars.GCP_PROJECT_ID }}/my-repo/frontend:${{ github.sha }} \
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
```

## Anti-patterns to avoid

1. **Hardcoding GCP project IDs, registry hosts, or service names**: use GitHub environment variables (`vars.GCP_PROJECT_ID`, `vars.GCP_REGION`) to make workflows portable across environments.

2. **Rebuilding images every time**: use `docker manifest inspect` to skip builds when images already exist in the registry, especially for worker services that reuse backend images.

3. **Using service account keys instead of Workload Identity Federation**: prefer Workload Identity Federation for better security (no long-lived keys). If using keys, store them as GitHub secrets, never in code.

4. **Setting `--min-instances=0` in production**: causes cold starts for user-facing services. Use `--min-instances=1` or higher for prod; scale to zero only in dev/staging.

5. **Overly permissive `--allow-unauthenticated` on worker services**: workers should typically be `--no-allow-unauthenticated` and triggered via Cloud Tasks, Pub/Sub, or Temporal.

6. **Not setting resource limits (memory/CPU)**: always specify `--memory` and `--cpu` to control costs and avoid OOM kills. Use higher values for workers than for API servers.

7. **Exposing secrets in `--set-env-vars` logs**: GitHub Actions logs show command output. Use GitHub secrets (`secrets.*`) for sensitive values, not `vars.*` which are visible in logs.

8. **Skipping post-deploy sanity checks**: deployments can succeed but fail at runtime (DB migration issues, missing env vars). Always validate with a sanity check job.

9. **Using `latest` tags instead of `${{ github.sha }}`**: immutable tags enable rollback and reproducibility. Tag images with commit SHAs or semantic versions.

10. **Not using environment-specific workflows**: a single workflow with environment branching logic becomes hard to maintain. Separate workflows per environment (dev/staging/prod) are clearer.

11. **Forgetting to configure Docker authentication**: `docker push` fails without `gcloud auth configure-docker`. Always configure Docker after setting up gcloud.

12. **Setting `--timeout` too low for worker jobs**: workers processing long-running tasks need higher timeouts (e.g., `3600` seconds). Servers can use default `300` or `600`.

13. **Not setting `--concurrency` based on workload**: default concurrency (80) may be too high for CPU-bound workloads or too low for I/O-bound workloads. Tune based on service behavior.

## References

- [cloud-run-deploy.md](references/cloud-run-deploy.md) — gcloud run deploy flags and patterns
- [workflow-structure.md](references/workflow-structure.md) — GitHub Actions workflow structure, authentication, multi-job pipelines
- [repo-evidence.md](references/repo-evidence.md) — genericized snippets from real workflows
