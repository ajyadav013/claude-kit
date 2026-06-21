# The Trust Contract — In Depth

Reference for implementing and reviewing the edge-to-service forwarded-identity contract.

## 1. Canonicalization

The signature must cover everything that matters and be **unambiguous**. A loose
`method + path + role` concatenation is forgeable (e.g. `GET/admin` + role `x` vs `GET` + `/adminx` +
role). Build a canonical string with explicit separators and a fixed field order:

```
<METHOD>\n
<PATH>\n
<SHA256(body) hex>\n
<UNIX_TIMESTAMP>\n
<sorted "name:value" identity headers, one per line>
```

Rules:

- **Uppercase the method**, use the raw path (no query string unless you also sign it — pick one and be
  consistent on both sides).
- **Hash the body**, don't include the raw body in the string (binary-safe, bounded length). An empty
  body hashes the empty string.
- **Sort identity header names** so the edge and service agree on order regardless of how the HTTP layer
  reordered them.
- Lower-case header names before sorting/joining.
- The **timestamp is part of the signed string** — that is what makes replay detection tamper-proof.

## 2. Which headers to sign

Sign exactly the identity envelope the service will trust — typically:

| Header | Meaning |
|--------|---------|
| `x-user-id` | authenticated principal id |
| `x-user-role` | role/claim used for RBAC |
| `x-tenant-id` | active tenant/org for scoping |
| `x-user-data` | JSON envelope (when used instead of discrete headers) |

Do **not** sign volatile or hop-by-hop headers (`date`, `content-length`, proxy headers) — they change in
transit and break verification.

## 3. Edge responsibilities

1. Authenticate the user (session/JWT/OAuth) — out of scope here, see `auth-and-rbac`.
2. **Strip** any inbound `x-gateway-*`, `x-user-*`, `x-tenant-*` headers from the **client** request so a
   client can never inject identity.
3. Set the identity headers from the authenticated principal.
4. Compute `x-gateway-timestamp` (now) and `x-gateway-signature = HMAC-SHA256(secret, canonical)`.
5. Forward to the internal service.

An ingress that signs in Lua/JS at the edge follows the same canonical rules as the service's verifier —
keep one shared spec so both sides compute identical strings.

## 4. Service responsibilities (fail-closed order)

```
1. signature header present?         no  -> 401  (NEVER fail open)
2. timestamp present & parseable?     no  -> 401
3. |now - timestamp| <= MAX_SKEW?     no  -> 401  (replay)
4. recompute HMAC, compare_digest?    no  -> 401  (forged / wrong secret)
5. parse identity headers -> principal
6. enforce RBAC + tenant scoping for THIS action  (origin != authorization)
```

`MAX_SKEW` is typically 30–120s — large enough for clock drift, small enough to bound replay. Keep edge
and service clocks in sync (NTP).

## 5. Secret rotation

- Hold two secrets in config: `GATEWAY_SIGNING_SECRET` (current) and `GATEWAY_SIGNING_SECRET_PREVIOUS`.
- Edge signs with **current**.
- Service verifies against **current, then previous** (accept either) during the rotation window.
- Rotation procedure: deploy new `PREVIOUS = old current`, `current = new` to the edge and services →
  wait one window → drop `PREVIOUS`.
- Secrets come from env / a secrets manager; never source, never an image layer, never a committed file.

## 6. Conflict-detection matrix

When a fact can come from more than one source, decide per fact and **reject mismatches**:

| Fact | Sources | On mismatch |
|------|---------|-------------|
| user id | signed `x-user-id`, JWT `sub`, session | 401 — identity confusion |
| tenant id | signed `x-tenant-id`, JWT `tenant_id`, session `active_tenant_id` | 400/401 — tenant confusion, log |
| role | signed `x-user-role`, JWT `role` | 401 — privilege confusion |

Resolution *order* (which wins when sources are absent) is fine to define (see
`multi-tenancy-patterns`), but two **present and disagreeing** sources is a security event — log it with
both values and reject.

## 7. Why network isolation is not enough

"Services are on a private network, only the gateway can reach them" fails when:

- a pod is compromised and pivots laterally,
- an SSRF in one service lets an attacker craft internal requests,
- a NetworkPolicy is missing/misconfigured (see `kubernetes-workload-hardening`),
- a service is accidentally exposed (LoadBalancer/NodePort) during a change.

The signature is the control that still holds in all of these. Network isolation is the second layer.

## 8. Review checklist

- [ ] Edge strips client-supplied identity headers before setting its own
- [ ] Canonical string is identical on both sides (order, separators, body hashing, case)
- [ ] Timestamp is inside the signed string and skew-checked on verify
- [ ] Missing signature → reject (no fail-open branch)
- [ ] Constant-time compare (`compare_digest` / `timingSafeEqual`)
- [ ] Secret from env/secrets manager, rotation supports current + previous
- [ ] Service still enforces RBAC + tenant scoping after verifying origin
- [ ] Conflicting identity/tenant/role across sources is rejected and logged
- [ ] No `verify_signature=False`-then-trust, no commented-out/flagged-off gates
