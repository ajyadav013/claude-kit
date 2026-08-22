# Representative Patterns

Patterns illustrating the edge-to-service trust contract as seen across production gateway +
microservice deployments. Sources are described generically — no internal service, host, or secret
values.

## Edge signs forwarded identity (gateway / ingress)

**Pattern:** the ingress validates the end-user session, then forwards identity headers together with an
HMAC signature so downstream services can prove the request originated at the edge.

```
# ingress signing step (pseudocode, mirrors a Lua/edge validateSignature routine)
identity = { "x-user-id": user.id, "x-user-role": user.role, "x-tenant-id": tenant.id }
ts       = now_unix()
canon    = method .. "\n" .. path .. "\n" .. sha256(body) .. "\n" .. ts .. "\n" .. sorted_headers(identity)
sig      = hmac_sha256(GATEWAY_SIGNING_SECRET, canon)
proxy_set_header("x-gateway-timestamp", ts)
proxy_set_header("x-gateway-signature", sig)
```

## Service verifies before trusting (request middleware)

**Pattern:** a routing/permission middleware on the service rejects requests without a valid signature
*before* any handler runs, then builds the principal from the verified headers.

```python
# permission middleware (representative)
async def __call__(self, request, call_next):
    if request.url.path in PUBLIC_PATHS:
        return await call_next(request)
    identity = verify_gateway_signature(request)   # raises 401 on missing/invalid/stale
    request.state.principal = build_principal(identity)
    return await call_next(request)
```

## Identity envelope as JSON (x-user-data)

**Pattern:** instead of discrete headers, the edge forwards a signed JSON envelope; the service parses it
only after signature verification and falls back to an anonymous principal if absent on a public route.

```python
raw = request.headers.get("x-user-data")           # only trusted because the request was signed
principal = json.loads(raw) if raw else ANONYMOUS
```

## Multi-source resolution with conflict rejection

**Pattern:** when both a signed header and a JWT claim carry the tenant, the service compares them and
rejects on mismatch rather than silently choosing one (prevents tenant/privilege confusion).

```python
if header_tenant and jwt_tenant and header_tenant != jwt_tenant:
    raise HTTPException(400, "tenant context conflict")
```

## Anti-patterns observed in the wild (captured as warnings)

- A service reading `x-user-role` and authorizing on it **with no signature check** — exploitable by any
  caller that can reach the service directly.
- `jwt.decode(token, options={"verify_signature": False})` whose **unverified** payload is then used for
  authorization.
- A signature-verification branch **commented out** or guarded by an always-false flag in a deployed
  service.

These are documented here so reviewers recognize and remove them — not as recommended patterns.
