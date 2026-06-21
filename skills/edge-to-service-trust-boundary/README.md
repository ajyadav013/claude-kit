# Edge-to-Service Trust Boundary

A stack-derived security skill for the **forwarded-identity trust contract** between an API gateway /
ingress and the backend services behind it.

In a gateway + microservices topology the edge authenticates the end user **once** and forwards a small
identity envelope (`x-user-id`, `x-user-role`, `x-tenant-id`, or a JSON `x-user-data`) to internal
services. Those services do not re-authenticate — so they must **prove the request came from the edge**
before trusting the headers. This skill encodes that contract: the edge **HMAC-signs** the forwarded
headers (signature + timestamp), services **verify with a constant-time compare and fail closed**, reject
replayed/skewed requests, **detect conflicts** when identity is resolvable from multiple sources, and
**still enforce their own authorization**.

## What this skill covers

- **Edge signing**: canonicalization, HMAC-SHA256 over headers + body hash + timestamp, secret rotation,
  stripping client-supplied identity headers.
- **Service verification**: require-signature / fail-closed, constant-time compare, replay (timestamp
  skew) rejection, parse-identity-only-after-verify, authz still enforced.
- **Conflict detection**: reject (not silently resolve) when signed header vs JWT claim vs session
  disagree on user/tenant/role.
- **Anti-patterns**: `verify_signature=False` then trust, naked header trust, fail-open, `==` on
  signatures, disabled/commented-out gates, trusting `X-Forwarded-For` for identity.

## Relationship to other skills

- `auth-and-rbac` — how the gateway authenticates the user and the `x-user-data` forwarding mechanic.
- `multi-tenancy-patterns` — tenant resolution order and RLS scoping (this skill adds conflict rejection).
- `security-and-hardening` — the broader OWASP boundary system.

## How to use

Read `SKILL.md` for the contract, conventions, and a worked example (Python + Node). See
`references/trust-contract.md` for the canonicalization rules, rotation window, and conflict matrix.

> Stack-derived: this skill encodes a real Python/FastAPI + Node/Express gateway topology. It is **not**
> wired into `claude-kit init`; install it deliberately. All examples are generic illustrations — no
> internal service, host, or secret values.
