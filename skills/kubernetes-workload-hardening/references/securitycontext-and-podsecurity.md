# securityContext & PodSecurity — Field by Field

What each control does and what it prevents. Apply at the pod level for defaults, override per container
where needed (the container context wins).

## Pod-level fields

| Field | Set to | Prevents |
|-------|--------|----------|
| `runAsNonRoot` | `true` | Container running as UID 0; admission rejects a root image |
| `runAsUser` / `runAsGroup` | non-zero (e.g. `10001`) | Implicit root; pins a known unprivileged identity |
| `fsGroup` | app gid | Volume files owned by root / unreadable by the app |
| `seccompProfile.type` | `RuntimeDefault` | Unfiltered syscalls; applies the runtime's default filter |
| `supplementalGroups` | minimal | Unneeded group access to host/volume resources |

## Container-level fields

| Field | Set to | Prevents |
|-------|--------|----------|
| `allowPrivilegeEscalation` | `false` | `setuid`/`setgid` binaries gaining privilege (`no_new_privs`) |
| `privileged` | `false` | Near-root-on-node access to all devices and host kernel |
| `readOnlyRootFilesystem` | `true` | Attacker writing binaries / tampering with app files |
| `capabilities.drop` | `["ALL"]` | Keeping the default Linux capability set |
| `capabilities.add` | only justified (e.g. `NET_BIND_SERVICE`) | Broad capabilities; add back the minimum |

### readOnlyRootFilesystem in practice

A read-only root needs writable scratch for `/tmp`, caches, and any runtime-written path:

```yaml
securityContext:
  readOnlyRootFilesystem: true
volumeMounts:
  - { name: tmp, mountPath: /tmp }
  - { name: cache, mountPath: /var/cache/app }
volumes:
  - { name: tmp, emptyDir: {} }
  - { name: cache, emptyDir: {} }
```

### NET_BIND_SERVICE

Only needed to bind a port < 1024. Prefer configuring the app on a high port (e.g. 8080) and dropping
**all** capabilities — then no `add:` is required at all.

## The restricted PodSecurity profile

Labeling a namespace enforces the cluster-side backstop:

```yaml
metadata:
  labels:
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/enforce-version: latest
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/warn: restricted
```

The `restricted` profile requires (among others): `runAsNonRoot`, `allowPrivilegeEscalation: false`,
`capabilities.drop: ["ALL"]`, a non-default `seccompProfile`, no host namespaces, no `hostPath`. Setting
the securityContext fields above makes pods compliant; the label makes non-compliant pods **rejected**
rather than merely discouraged. Roll out with `warn`/`audit` first, then `enforce`.

## Verification

```bash
# A pod's effective securityContext
kubectl get pod <pod> -o jsonpath='{.spec.securityContext}{"\n"}{.spec.containers[*].securityContext}'

# Confirm it is not running as root inside the container
kubectl exec <pod> -- id        # uid should be non-zero, not uid=0(root)

# Confirm the root filesystem is read-only
kubectl exec <pod> -- sh -c 'touch /nope 2>&1 || echo "read-only root OK"'
```
