---
name: edge-to-service-trust-boundary
description: The cryptographic trust contract between an API gateway / edge and the backend services behind it — edge HMAC-signs forwarded identity and tenant headers (signature + timestamp), downstream services verify with constant-time compare and FAIL CLOSED, reject replayed/skewed requests, detect conflicts when identity is resolvable from multiple sources, and still enforce their own authz. Use when building a service that sits behind a gateway/ingress that forwards identity, designing the edge signing step, verifying forwarded headers, hardening against header spoofing or direct-to-service bypass, or reviewing code for naked-header trust and verify_signature=False. Do NOT use for general application-code hardening (use security-and-hardening) or for building the downstream auth dependencies/RBAC that consume the verified identity (use auth-and-rbac).
---

# Edge-to-Service Trust Boundary

The signed contract for **forwarded identity** in a gateway + microservices topology. The edge
authenticates the end user once and forwards identity/tenant context to internal services; this skill
defines how services can *trust* those forwarded claims without re-authenticating — and how they fail
when the trust is violated.

> Companion skills: `auth-and-rbac` (how the gateway authenticates and the `x-user-data` forwarding
> mechanic), `multi-tenancy-patterns` (tenant resolution order + RLS), `security-and-hardening`
> (OWASP boundary system). This skill is the **crypto contract + fail-closed semantics** between them —
> it does not re-explain how the gateway logs a user in.

## When to use

- Building a backend service that sits **behind** an API gateway / ingress that forwards identity
- Designing the **edge signing** step (which headers to sign, canonicalization, secret rotation)
- Implementing **service-side verification** of forwarded identity/tenant headers
- Hardening against **header spoofing** or a caller reaching a service **directly** (bypassing the edge)
- Preventing **replay** of captured signed requests
- Detecting **conflicts** when identity/tenant can be resolved from more than one source
- Reviewing code for **naked-header trust**, `verify_signature=False`, or disabled/commented-out auth

## The trust model in one paragraph

The edge is the **only** component that authenticates the end user (session, JWT, OAuth). It then
forwards a small, well-defined identity envelope to internal services — e.g. `x-user-id`,
`x-user-role`, `x-tenant-id`, or a JSON `x-user-data`. Internal services do **not** re-authenticate,
but they must **prove the request actually came from the edge** before trusting those headers. They do
that by verifying an **HMAC signature** the edge computed over the forwarded headers + a timestamp.
Network isolation (services on a private network, only the gateway as ingress) is a *second* layer, not
the primary one — never rely on network posture alone.

## Core conventions

### Edge: sign the forwarded identity

- **Sign a canonical string**, not a loose concatenation. Canonical = `method` + `\n` + `path` + `\n` +
  `sha256(body)` + `\n` + `timestamp` + `\n` + the **sorted** identity headers (`name:value` joined by
  `\n`). Sorting + explicit separators prevent ambiguity attacks.
- **HMAC-SHA256** with a shared secret held only by the edge and the services. Emit two headers:
  `x-gateway-signature: <hex>` and `x-gateway-timestamp: <unix-seconds>`.
- **Rotate the secret.** Keep `GATEWAY_SIGNING_SECRET` plus `GATEWAY_SIGNING_SECRET_PREVIOUS`; sign with
  the current secret, let services verify against either during the rotation window.
- The edge **strips** any inbound `x-gateway-*`, `x-user-*`, `x-tenant-*` headers from the client before
  setting its own — a client must never be able to inject them.

### Service: verify, then fail closed

- **Require the signature.** If `x-gateway-signature` is missing → **401**. Never fail open ("no
  signature, must be internal traffic" is exactly how the bypass works).
- **Recompute and constant-time compare** with `hmac.compare_digest` (Python) / `crypto.timingSafeEqual`
  (Node). Never `==` on the hex string (timing leak).
- **Reject replay.** If `abs(now - x-gateway-timestamp) > MAX_SKEW` (e.g. 60s) → **401**. The timestamp is
  inside the signed canonical string, so it cannot be altered without breaking the signature.
- **Only after verification** parse the identity headers and build the request principal.
- **Still enforce authz.** "Signed by the gateway" proves *origin*, not *authorization*. The service must
  still check the role/permission for the action and scope every tenant query (see `auth-and-rbac`,
  `multi-tenancy-patterns`). A valid signature on `x-user-role: member` does not authorize an admin route.

### Detect conflicts across resolution sources

When the same fact (user id, tenant id, role) can be read from **multiple** places — a signed header, a
JWT claim, a session — do **not** silently pick one. Resolve in a defined order **and reject on
mismatch**: a request whose signed `x-tenant-id` disagrees with its JWT `tenant_id` is either a bug or an
attempt at privilege/tenant confusion → **400/401**, log it. (This complements the resolution *order* in
`multi-tenancy-patterns`, which assumes the sources agree.)

### Secret & network posture

- Shared HMAC secret lives in env / a secrets manager, **never** in source or an image. Rotate on a
  schedule and on suspected exposure.
- Services bind to the private network; the gateway is the only ingress. Treat this as **defense in
  depth** — sign anyway, because a compromised pod, an SSRF, or a misconfigured NetworkPolicy can put an
  attacker on the internal network.

## Skeleton / example

```python
# edge/signing.py — the gateway computes the signature (illustrative)
import hashlib, hmac, time

def canonical(method: str, path: str, body: bytes, ts: str, identity: dict[str, str]) -> bytes:
    body_hash = hashlib.sha256(body or b"").hexdigest()
    headers = "\n".join(f"{k.lower()}:{identity[k]}" for k in sorted(identity))
    return "\n".join([method.upper(), path, body_hash, ts, headers]).encode()

def sign_request(method, path, body, identity, secret: str) -> dict[str, str]:
    ts = str(int(time.time()))
    sig = hmac.new(secret.encode(), canonical(method, path, body, ts, identity), hashlib.sha256).hexdigest()
    return {**identity, "x-gateway-timestamp": ts, "x-gateway-signature": sig}

# service/verify.py — FastAPI dependency that fails closed
from fastapi import Depends, HTTPException, Request
from starlette.status import HTTP_401_UNAUTHORIZED

MAX_SKEW_SECONDS = 60

async def require_gateway_identity(request: Request) -> dict[str, str]:
    sig = request.headers.get("x-gateway-signature")
    ts = request.headers.get("x-gateway-timestamp")
    if not sig or not ts:
        raise HTTPException(HTTP_401_UNAUTHORIZED, "missing gateway signature")  # FAIL CLOSED

    try:
        skew = abs(int(time.time()) - int(ts))
    except ValueError:
        raise HTTPException(HTTP_401_UNAUTHORIZED, "bad timestamp")
    if skew > MAX_SKEW_SECONDS:
        raise HTTPException(HTTP_401_UNAUTHORIZED, "stale request (replay?)")

    identity = {k: v for k, v in request.headers.items() if k.lower().startswith(("x-user-", "x-tenant-"))}
    body = await request.body()
    for secret in (settings.GATEWAY_SIGNING_SECRET, settings.GATEWAY_SIGNING_SECRET_PREVIOUS):
        if not secret:
            continue
        expected = hmac.new(
            secret.encode(),
            canonical(request.method, request.url.path, body, ts, identity),
            hashlib.sha256,
        ).hexdigest()
        if hmac.compare_digest(expected, sig):           # constant-time
            return identity
    raise HTTPException(HTTP_401_UNAUTHORIZED, "invalid gateway signature")  # FAIL CLOSED

# conflict detection across sources
def resolve_tenant(signed: dict, jwt_claims: dict | None) -> str:
    from_header = signed.get("x-tenant-id")
    from_jwt = (jwt_claims or {}).get("tenant_id")
    if from_header and from_jwt and from_header != from_jwt:
        logger.warning("tenant_conflict", header=from_header, jwt=from_jwt)
        raise HTTPException(400, "tenant context conflict")   # never silently pick one
    return from_header or from_jwt
```

```javascript
// service/verify.js — Express middleware, fail-closed (illustrative)
const crypto = require("crypto");
const MAX_SKEW_MS = 60_000;

function requireGatewayIdentity(req, res, next) {
  const sig = req.get("x-gateway-signature");
  const ts = req.get("x-gateway-timestamp");
  if (!sig || !ts) return res.status(401).json({ error: "missing gateway signature" }); // fail closed
  if (Math.abs(Date.now() - Number(ts) * 1000) > MAX_SKEW_MS)
    return res.status(401).json({ error: "stale request" });

  const expected = crypto
    .createHmac("sha256", process.env.GATEWAY_SIGNING_SECRET)
    .update(canonical(req, ts))
    .digest("hex");
  const ok =
    expected.length === sig.length &&
    crypto.timingSafeEqual(Buffer.from(expected), Buffer.from(sig)); // constant-time
  if (!ok) return res.status(401).json({ error: "invalid gateway signature" }); // fail closed
  next();
}
```

## Anti-patterns to avoid

- **`jwt.decode(token, options={"verify_signature": False})` and then trusting the claims** — decoding
  without verification is fine *only* to read a key id you then use to verify; using the unverified
  payload for identity/authz lets anyone forge a token. (Distinct from the read-`kid`-then-verify flow in
  `auth-and-rbac`.)
- **Naked header trust** — reading `x-user-role` / `x-user-id` / `x-tenant-id` and authorizing on them
  with no signature check. Any caller that reaches the service directly then becomes admin.
- **Fail open on a missing signature** — "no signature header, so it must be internal" is the bypass.
  Missing signature = reject.
- **`==` / string equality on the signature** — use `hmac.compare_digest` / `timingSafeEqual`.
- **No timestamp / no skew check** — a captured signed request replays forever.
- **Commented-out or feature-flagged-off auth in production** — `# verify_signature(...)` left disabled,
  or `if FALSE:` guards around the check. Remove them; don't ship disabled gates.
- **Trusting client-controllable headers for identity** — `X-Forwarded-For`, `X-Real-IP`, or a raw
  `x-user-data` the edge didn't sign and the edge didn't strip from the client.
- **Treating "signed by gateway" as "authorized"** — origin proof is not authorization; still run RBAC
  and tenant scoping.
- **One static secret forever** — no rotation path means a single leak is permanent; keep current +
  previous secrets.
- **Silently picking one source on conflict** — mismatched tenant/role across header vs JWT vs session is
  a security event, not a tie to break arbitrarily.

## References

- [trust-contract.md](./references/trust-contract.md) — Canonicalization, signing/verifying in depth,
  secret rotation, replay windows, conflict-detection matrix
- [repo-evidence.md](./references/repo-evidence.md) — Representative source patterns (gateway-side
  signing, service-side verification middleware) described generically
