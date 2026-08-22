# NetworkPolicy & RBAC — Least Privilege at the Network and API Layers

## NetworkPolicy: default-deny then allow

A namespace with **no** NetworkPolicy is a flat network: every pod can open a connection to every other
pod, in any namespace that also lacks policies. One compromised pod then reaches the whole mesh. The fix
is two-step: deny everything, then allow exactly the required flows.

### Step 1 — default-deny (ingress + egress)

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny
  namespace: my-namespace
spec:
  podSelector: {}                 # selects every pod in the namespace
  policyTypes: ["Ingress", "Egress"]
  # no ingress/egress rules => nothing allowed
```

### Step 2 — allow only what the app needs

```yaml
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
            matchLabels: { name: ingress }    # only the gateway/ingress namespace
      ports: [{ protocol: TCP, port: 8080 }]
  egress:
    - to:                                      # DNS is required for service discovery
        - namespaceSelector:
            matchLabels: { kubernetes.io/metadata.name: kube-system }
          podSelector:
            matchLabels: { k8s-app: kube-dns }
      ports: [{ protocol: UDP, port: 53 }, { protocol: TCP, port: 53 }]
    - to:                                      # database
        - podSelector: { matchLabels: { app: postgres } }
      ports: [{ protocol: TCP, port: 5432 }]
    - to:                                      # cache
        - podSelector: { matchLabels: { app: redis } }
      ports: [{ protocol: TCP, port: 6379 }]
```

Notes:

- **Don't forget DNS egress** — a default-deny egress policy breaks name resolution until you allow UDP/TCP
  53 to kube-dns. This is the most common "why can't my pod connect to anything" cause.
- Prefer `namespaceSelector` + `podSelector` over CIDR blocks; pod IPs are ephemeral.
- NetworkPolicy is enforced by the CNI plugin — confirm the cluster's CNI supports it.

## RBAC & ServiceAccount least privilege

### Dedicated ServiceAccount, token off by default

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: app-sa
  namespace: my-namespace
automountServiceAccountToken: false      # the app doesn't call the K8s API
```

Reference it from the pod (`serviceAccountName: app-sa`) and keep `automountServiceAccountToken: false`
at the pod level too. A mounted SA token is cluster credentials; don't hand them to a pod that never uses
them.

### Minimal Role when the app DOES call the API

Grant the exact resources and verbs — never wildcards, never `cluster-admin`:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: app-config-reader
  namespace: my-namespace
rules:
  - apiGroups: [""]
    resources: ["configmaps"]
    verbs: ["get", "list", "watch"]      # read-only, configmaps only
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: app-config-reader
  namespace: my-namespace
subjects:
  - kind: ServiceAccount
    name: app-sa
    namespace: my-namespace
roleRef:
  kind: Role
  name: app-config-reader
  apiGroup: rbac.authorization.k8s.io
```

Prefer a namespaced `Role`/`RoleBinding` over a `ClusterRole`/`ClusterRoleBinding` unless the workload
genuinely needs cluster-wide scope.

## Verification

```bash
# What can this ServiceAccount do?  (should be a short list)
kubectl auth can-i --list --as=system:serviceaccount:my-namespace:app-sa -n my-namespace

# It must NOT be able to do dangerous things
kubectl auth can-i create pods --as=system:serviceaccount:my-namespace:app-sa -n my-namespace   # no
kubectl auth can-i '*' '*' --as=system:serviceaccount:my-namespace:app-sa                       # no

# Confirm policies exist
kubectl get networkpolicy -n my-namespace
```
