---
name: kubernetes-workload-hardening
description: Runtime/manifest-layer Kubernetes security — securityContext, NetworkPolicy, digest-pinned images, PodSecurity. Use for Deployment/Helm manifests. Do NOT use for app-code vulns (use security-and-hardening).
---

# Kubernetes Workload Hardening

Security for the **runtime / manifest layer** of a Kubernetes workload: what the pod is allowed to do,
what it can reach, and what identity it runs as. This is distinct from — and complementary to — the
image-build hardening in the Dockerfile skills (`dockerfile-backend`, `dockerfile-frontend`,
`docker-shared`): a perfectly built non-root image still runs privileged if the manifest lets it.

> Companion skills: `docker-shared` / `dockerfile-*` (the image you deploy), `devops-engineer`
> (delivery & CI), `observability-and-logging` (liveness/readiness probes), `security-and-hardening`
> (the broader boundary system), `edge-to-service-trust-boundary` (why NetworkPolicy is defense-in-depth,
> not the only control).

## When to use

- Writing a **Deployment / StatefulSet / DaemonSet / Job** manifest or a Helm chart `values`/templates
- Adding or reviewing **pod and container `securityContext`**
- Locking down pod networking with **NetworkPolicy**
- **Pinning images** by digest in manifests and setting `imagePullPolicy`
- Setting **resource requests/limits** to bound resource-exhaustion DoS
- Enforcing **PodSecurity admission** (`restricted`) on a namespace
- Giving a workload a **least-privilege ServiceAccount** and RBAC
- Reviewing manifests for **privilege escalation, container-escape, or flat-network** risks

## Core conventions

### Pod-level securityContext

- `runAsNonRoot: true` and an explicit non-zero `runAsUser` / `runAsGroup` — never run as UID 0.
- `fsGroup` for volume ownership when the app writes to a mounted volume.
- `seccompProfile.type: RuntimeDefault` — apply the runtime's default syscall filter.

### Container-level securityContext

- `allowPrivilegeEscalation: false` — block `setuid`/`setgid` escalation (`no_new_privs`).
- `privileged: false` (the default — assert it explicitly in security-sensitive charts).
- `readOnlyRootFilesystem: true` — mount an `emptyDir` at `/tmp` (and any real write path) instead of a
  writable root.
- `capabilities.drop: ["ALL"]`, then `add:` only what's truly needed (e.g. `NET_BIND_SERVICE` *only* if
  the process must bind a port < 1024 — prefer a high port and drop even that).

### Images

- **Pin by digest**: `image: registry.example.com/app@sha256:<digest>` — a digest is immutable; a tag is
  not. Never deploy `:latest` or an untagged image.
- Set `imagePullPolicy` deliberately (`IfNotPresent` for digest-pinned; `Always` only when you must
  re-resolve a mutable tag).
- Use `imagePullSecrets` referencing a Secret for private registries — never embed registry creds.

### Resources

- Set both `requests` and `limits` for CPU and memory. Missing limits let one pod starve the node
  (resource-exhaustion DoS) and break the QoS class.

### NetworkPolicy (default-deny + explicit allow)

- Apply a **default-deny** policy (ingress *and* egress) per namespace, then add narrow allows:
  ingress from the gateway/ingress namespace only; egress to the database, cache, and DNS only.
- A namespace with no NetworkPolicy is a **flat network** — any compromised pod can reach every other.

### PodSecurity admission

- Label the namespace `pod-security.kubernetes.io/enforce: restricted` (plus `audit`/`warn`) so the
  cluster rejects pods that violate the restricted profile — a backstop for the securityContext above.

### ServiceAccount & RBAC

- Give each workload a **dedicated** ServiceAccount; do not use `default`.
- Set `automountServiceAccountToken: false` unless the pod actually calls the Kubernetes API.
- Grant the minimum Role/RoleBinding the workload needs — never `cluster-admin`, never wildcard verbs.

### Secrets

- Inject via `envFrom.secretRef` or a projected/CSI volume — never literal values in env, never in a
  ConfigMap, never baked into the image. (See `edge-to-service-trust-boundary` for the gateway HMAC
  secret specifically.)

### Host isolation

- `hostNetwork`, `hostPID`, `hostIPC`: **false**. No `hostPath` volumes for application workloads
  (they're a direct path to node compromise).

### Probes

- Define `livenessProbe` and `readinessProbe` (and `startupProbe` for slow starts) — see
  `observability-and-logging` for `/_healthz` / `/_readyz` endpoints.

## Skeleton / example

```yaml
# Hardened Deployment (illustrative — generic names)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: app
  namespace: my-namespace
spec:
  replicas: 2
  selector:
    matchLabels: { app: app }
  template:
    metadata:
      labels: { app: app }
    spec:
      serviceAccountName: app-sa
      automountServiceAccountToken: false
      securityContext:                       # pod-level
        runAsNonRoot: true
        runAsUser: 10001
        runAsGroup: 10001
        fsGroup: 10001
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: app
          image: registry.example.com/app@sha256:<digest>   # pin by digest, not :latest
          imagePullPolicy: IfNotPresent
          ports:
            - containerPort: 8080
          securityContext:                   # container-level
            allowPrivilegeEscalation: false
            privileged: false
            readOnlyRootFilesystem: true
            capabilities:
              drop: ["ALL"]
          resources:
            requests: { cpu: "100m", memory: "128Mi" }
            limits:   { cpu: "500m", memory: "256Mi" }
          envFrom:
            - secretRef: { name: app-secrets }   # secrets injected, not baked
          volumeMounts:
            - { name: tmp, mountPath: /tmp }      # writable scratch with RO root fs
          livenessProbe:
            httpGet: { path: /_healthz, port: 8080 }
          readinessProbe:
            httpGet: { path: /_readyz, port: 8080 }
      volumes:
        - name: tmp
          emptyDir: {}
---
# Namespace: enforce the restricted PodSecurity profile
apiVersion: v1
kind: Namespace
metadata:
  name: my-namespace
  labels:
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/warn: restricted
---
# Default-deny everything, then allow only what's needed
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny
  namespace: my-namespace
spec:
  podSelector: {}
  policyTypes: ["Ingress", "Egress"]
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-app
  namespace: my-namespace
spec:
  podSelector:
    matchLabels: { app: app }
  policyTypes: ["Ingress", "Egress"]
  ingress:
    - from:
        - namespaceSelector:
            matchLabels: { name: ingress }   # only the gateway namespace
      ports:
        - { protocol: TCP, port: 8080 }
  egress:
    - to:                                     # DNS (UDP + TCP — large responses / DNSSEC use TCP)
        - namespaceSelector:
            matchLabels: { kubernetes.io/metadata.name: kube-system }
          podSelector:
            matchLabels: { k8s-app: kube-dns }
      ports:
        - { protocol: UDP, port: 53 }
        - { protocol: TCP, port: 53 }
    - to:                                     # database
        - podSelector:
            matchLabels: { app: postgres }
      ports:
        - { protocol: TCP, port: 5432 }
---
# Dedicated least-privilege ServiceAccount
apiVersion: v1
kind: ServiceAccount
metadata:
  name: app-sa
  namespace: my-namespace
automountServiceAccountToken: false
```

## Anti-patterns to avoid

- **Running as root** — no `runAsNonRoot`/`runAsUser`, so the container runs UID 0; a compromise has root
  in the container and a head start on node escape.
- **`privileged: true` / `allowPrivilegeEscalation: true`** — privileged is near-equivalent to root on the
  node; only ever for dedicated, audited infra DaemonSets.
- **`:latest` or untagged images** — non-reproducible, silently mutable; pin by digest.
- **No resource limits** — one pod can exhaust node CPU/memory; also drops the pod to BestEffort QoS.
- **No NetworkPolicy (flat network)** — every pod can reach every other; one foothold reaches all.
- **`automountServiceAccountToken: true` by default** — hands a SA token to a pod that never calls the
  API; a compromise gets cluster credentials for free.
- **`hostPath`, `hostNetwork`, `hostPID`, `hostIPC`** for app workloads — direct routes to node/host
  compromise.
- **Writable root filesystem** — lets an attacker drop binaries / modify the app; use
  `readOnlyRootFilesystem: true` + `emptyDir` for scratch.
- **Capabilities not dropped** — keep `drop: ["ALL"]` and add back only the one capability you can
  justify.
- **Secrets in env literals or ConfigMaps** — use `secretRef`/projected volumes; ConfigMaps are not
  secret and are world-readable to anyone with namespace read.
- **`cluster-admin` / wildcard RBAC for an app** — scope a Role to the exact resources and verbs.

## References

- [securitycontext-and-podsecurity.md](./references/securitycontext-and-podsecurity.md) — Field-by-field
  pod/container securityContext, the restricted PodSecurity profile, and what each control prevents
- [networkpolicy-and-rbac.md](./references/networkpolicy-and-rbac.md) — Default-deny + allow patterns,
  egress control, dedicated ServiceAccount, least-privilege Role/RoleBinding
- [repo-evidence.md](./references/repo-evidence.md) — Representative manifest/chart patterns described
  generically
