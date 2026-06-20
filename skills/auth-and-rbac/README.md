# Auth and RBAC Skill

Authentication and authorization patterns for FastAPI services, extracted from production identity and multi-tenant systems.

## Coverage

This skill documents:

- **Session-based auth chains** — Cookie-based sessions with Redis storage, fingerprint validation, request signing
- **JWT authentication** — RS256 token issuance/verification, refresh token rotation, JWKS endpoints
- **Password hashing** — argon2id with async thread pool, password rotation tracking, rehash detection
- **Multi-factor authentication** — TOTP setup/verification with pyotp, Email OTP, backup codes, MFA enforcement
- **Role-based access control** — Hierarchical role dependencies, org path-based access checks, role registration restrictions
- **API gateway identity forwarding** — x-user-data JSON header pattern for downstream services
- **Security hardening** — Login rate limiting, password expiry, account lockout, session fingerprinting, request signing

## Provenance

Derived from real-world production Python/FastAPI services implementing authentication and authorization at scale.

## Coverage Notes

**Strong coverage**: Session-based auth chains, JWT RS256, argon2id, TOTP/Email OTP, hierarchical RBAC, org path-based access — all patterns confirmed with comprehensive production implementations.

**Moderate coverage**: API gateway x-user-data header forwarding (read-only identity extraction); client-side JWT auth (OAuth2PasswordBearer + DB secret lookup).

**Thin coverage**: Permission-based RBAC (decorator/middleware) — the documented patterns focus on role-based checks. If fine-grained permission-level RBAC is needed, consider supplementing with libraries like FastAPI-Permissions or Casbin.

## Related Skills

- `multi-tenancy-patterns` — Tenant resolution, RLS, multi-pool isolation (cross-references org hierarchy and tenant-scoped auth)
