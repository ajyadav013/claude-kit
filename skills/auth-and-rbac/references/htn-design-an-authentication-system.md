# Digest: Design an Authentication System

- **Source:** https://x.com/Harry_The_Nerd/status/2048758919770816850
- **Author:** Harshit Khosla (@Harry_The_Nerd)
- **Category:** HLD (high-level design)
- **Fetched:** 2026-07-23/24 via logged-out browser render
- **License note:** Content (c) the author; this digest is an own-words summary for internal engineering reference — no verbatim text.

## Patterns

### Salted adaptive password hashing (bcrypt / Argon2)

Credentials must never sit in the database in cleartext; a breach would hand every account over directly. Plain hashing closes that hole only partially, because identical passwords hash identically, which lets attackers match rows against precomputed rainbow tables. The remedy is a per-user random salt combined with the password before hashing, so two accounts sharing a password still produce unrelated digests. The salt lives next to the hash in the same row — it is not a secret, its only job is uniqueness. The article recommends bcrypt or Argon2 specifically because both bake salting in and are deliberately expensive to compute, which throttles offline brute-forcing. Trade-off: intentional slowness costs CPU on every login, which is acceptable because logins are rare relative to normal traffic.

### Stateless JWT access tokens

Once a user authenticates, the server hands back a JSON Web Token so the password never travels again. The token is three dot-separated segments: a header naming the signing algorithm (HS256 in the example), a payload of claims (user id, role, expiry timestamp), and a signature computed over header+payload with a server-held secret. Any tampering breaks the signature. The defining property is statelessness: verification is pure computation with no database or cache round-trip, so the article pegs it at sub-millisecond per request. Trade-off: the server keeps nothing, so it also cannot revoke an individual token before its expiry — which motivates the next pattern.

### Dual-token session management (short-lived access + DB-backed refresh)

Because a stolen JWT stays valid until it expires, a single long-lived token is dangerous, while a single short-lived one forces constant re-login. The pattern splits the session into two credentials issued together at login: an access token (a JWT expiring in 15 minutes, never persisted server-side) and a refresh token (an opaque random string good for 30 days, persisted in the database and cached in Redis). Routine requests carry only the access token and stay database-free. When it lapses, the client trades the refresh token — validated against the store — for a fresh access token. Logout deletes the refresh-token row, so a stolen access token dies within its 15-minute window and cannot be renewed. The result balances a small revocation blast radius against uninterrupted UX; the cost is one extra table plus a periodic refresh round-trip.

### Hardened OTP flow for password reset

Forgot-password works by emailing/texting a 6-digit one-time code, but the design treats the OTP itself as a credential: it is stored hashed (never plaintext), carries a 10-minute TTL, and each row tracks a failure counter. After 3 wrong submissions the code is invalidated and the user must request a new one. Attempt limiting is essential here because a 6-digit code has only about one million possibilities — trivially enumerable without a lockout. Delivery is delegated to a separate notification service (SMS or email). Rows are short-lived and purged after expiry.

### OAuth 2.0 authorization-code delegation

"Login with Google" hands the identity-verification problem to a trusted external provider. Four parties participate: the end user, your application, the provider's authorization server, and the provider's resource/API server. The flow: your app redirects the user to the provider, the user consents, the provider redirects back with a short-lived authorization code, and your backend exchanges that code plus its client secret for an access token it then uses to pull the profile (name, email, avatar). The indirection through a code exists because the browser redirect is observable — an intercepted code is worthless without the confidential client secret held server-side. The article frames the division of labor cleanly: OAuth answers who vouches for this user; JWT is merely the token wire format; the two compose rather than compete. Trade-off: you shed password-storage liability entirely for those users, at the cost of a dependency on the provider.

### Auth data-layer layout (three tables + one cache)

The storage design is minimal and role-separated, all on PostgreSQL plus Redis:

- **Users table** — user id, email, password hash, salt, role, creation time. Touched only at registration and login; never holds plaintext passwords or any tokens.
- **Refresh-token table** — token id, user id, the token value, expiry, device info, creation time. One row per active session; the row's deletion *is* logout.
- **OTP table** — otp id, user id, hashed code, expiry, attempt counter, creation time. Ephemeral rows auto-cleaned after expiry.
- **Redis** — hot-path refresh-token lookups, cached session data (role, email), and failed-login counters for rate limiting.

Deliberate omission: access tokens appear in no store at all, because a self-verifying JWT makes persistence pointless — the article treats that absence as the core of the design.

### Stateless horizontal scaling with a thin shared-state layer

Because JWT verification needs no per-server session memory, any auth-service replica can validate any request, so the service scales out with zero cross-node coordination. The only shared mutable state — refresh tokens and rate-limit counters — is small and lives in Redis. Latency follows the same shape: the everyday path (signature check) is math-only; the occasional path (refresh) hits Redis; the rare path (login/registration) is the only one that reaches PostgreSQL.

### Rate limiting login attempts via Redis counters

Failed-login counts are tracked in Redis and used to throttle credential-guessing. This is listed alongside the hashing/expiry measures as part of the layered defense: slow hashes blunt offline attacks, counters blunt online ones, short expiries and attempt caps bound token and OTP abuse.

## Not absorbed

- **Series branding** ("High-Level Design Questions-Based Series #9") — interview-prep framing, not engineering content.
- **Closing sign-off** ("That's all folks!"-style outro) — flourish only.
- **Engagement chrome** (view counts, reply/like tallies, timestamp captured with the post) — platform metadata, not article content.

## Fidelity check

- **Post count in capture:** 1 (single long-form article post; no `---AUTHOR-POST-BREAK---` separators present).
- **Article outline as authored:**
  1. Intro — authentication vs authorization, scope of the design
  2. Functional requirements (register, login, session management, token refresh, forgot password, logout)
  3. Password storage: hashing and salting
  4. JWT — JSON Web Token
  5. The refresh token pattern
  6. OTP — forgot password flow
  7. OAuth 2.0 — Login with Google
  8. The data layer (three DB tables and one cache)
  9. Non-functional requirements — Latency, Scalability, Security
  10. Sign-off
- **Pattern-to-section citations:**
  - Salted adaptive password hashing → section 3 ("Password storage: hashing and salting")
  - Stateless JWT access tokens → section 4 ("JWT - JSON Web Token")
  - Dual-token session management → section 5 ("The refresh token pattern")
  - Hardened OTP flow → section 6 ("OTP - forgot password flow")
  - OAuth 2.0 authorization-code delegation → section 7 ("OAuth 2.0 - Login with Google")
  - Auth data-layer layout → section 8 ("The data layer")
  - Stateless horizontal scaling → section 9 (Non-functional requirements: Latency + Scalability)
  - Rate limiting via Redis counters → sections 8 and 9 (data layer's Redis role; Security subsection)
