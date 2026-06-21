# Kubernetes Workload Hardening

A stack-derived security skill for the **runtime / manifest layer** of Kubernetes workloads.

A non-root, minimal container image (built per the Dockerfile skills) still runs **privileged**, on a
**flat network**, with a **writable root filesystem** and a **cluster-admin token** if the manifest
allows it. This skill closes that gap: it hardens what the pod is allowed to do, what it can reach, and
what identity it runs as.

## What this skill covers

- **securityContext** (pod + container): `runAsNonRoot`, non-zero UID/GID, `allowPrivilegeEscalation:
  false`, `readOnlyRootFilesystem`, `capabilities.drop: [ALL]`, `seccompProfile: RuntimeDefault`.
- **NetworkPolicy**: default-deny ingress/egress + explicit narrow allows (gateway, DB, DNS).
- **Images**: digest pinning, `imagePullPolicy`, `imagePullSecrets`.
- **Resources**: requests/limits to bound resource-exhaustion DoS.
- **PodSecurity admission**: enforcing the `restricted` profile per namespace.
- **ServiceAccount & RBAC**: dedicated SA, `automountServiceAccountToken: false`, least-privilege Role.
- **Secrets**: `secretRef`/projected volumes, never baked or in ConfigMaps.

## Relationship to other skills

- `docker-shared`, `dockerfile-backend`, `dockerfile-frontend` — the **image-build** layer (non-root
  user, minimal base). This skill is the **runtime** layer on top of those images.
- `observability-and-logging` — liveness/readiness probe endpoints referenced by the manifests.
- `edge-to-service-trust-boundary` — why NetworkPolicy is defense-in-depth, not the only control.
- `security-and-hardening` / `devops-engineer` — the broader security and delivery context.

## How to use

Read `SKILL.md` for the conventions and a complete hardened Deployment + NetworkPolicy + namespace
example. See `references/` for field-by-field securityContext detail and NetworkPolicy/RBAC patterns.

> Stack-derived: encodes a real GCP/Kubernetes deployment topology. **Not** wired into `claude-kit init`;
> install it deliberately. All names (registry, namespace, image) are generic placeholders — no internal
> hosts, project IDs, or cluster names.
