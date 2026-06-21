# Representative Patterns

Manifest/chart patterns illustrating runtime-layer hardening as seen across production Kubernetes
deployments. Described generically — no internal registry hosts, namespaces, project IDs, or cluster
names.

## Hardened workload securityContext

**Pattern:** Deployments set a pod-level non-root context and a container-level no-escalation, dropped-caps
context, with a read-only root filesystem and an `emptyDir` for scratch.

```yaml
securityContext:            # pod
  runAsNonRoot: true
  runAsUser: 10001
  seccompProfile: { type: RuntimeDefault }
# container
securityContext:
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: true
  capabilities: { drop: ["ALL"] }
```

## Digest-pinned images

**Pattern:** production manifests reference images by `@sha256:` digest (immutable) rather than a moving
tag; promotion between environments updates the digest, not a `:latest` pointer.

```yaml
image: registry.example.com/app@sha256:<digest>
imagePullPolicy: IfNotPresent
```

## Default-deny networking

**Pattern:** each namespace ships a `default-deny` NetworkPolicy plus per-app allow policies; the only
ingress is from the gateway/ingress namespace, and egress is restricted to DNS, the database, and the
cache.

## Least-privilege ServiceAccount

**Pattern:** each workload runs under a dedicated ServiceAccount with `automountServiceAccountToken:
false`; API-calling workloads get a narrow namespaced Role (e.g. read-only ConfigMaps) rather than broad
or cluster-wide grants.

## Secrets injected, not baked

**Pattern:** application secrets are delivered via `envFrom.secretRef` or a projected/CSI volume sourced
from a secrets manager — never literal env values, never ConfigMaps, never image layers.

## Anti-patterns observed (captured as warnings)

- Workloads with **no securityContext** (default root, escalation allowed) reaching production.
- Images deployed as **`:latest`**, making rollbacks and provenance ambiguous.
- Namespaces with **no NetworkPolicy** (flat east-west traffic).
- `automountServiceAccountToken` left **on** for pods that never call the API.

Documented so reviewers recognize and fix them — not as recommended patterns.
