# Digest: Serialization, Deserialization, Authentication and Authorization

- **Source:** https://x.com/Harry_The_Nerd/status/2053487726033559704
- **Author:** Harshit Khosla (@Harry_The_Nerd)
- **Category:** Backend Engineering
- **Fetched:** 2026-07-23/24 via logged-out browser render
- **License note:** Content (c) the author; this digest is an own-words summary for internal engineering reference — no verbatim text.

## Patterns

### Serialization / deserialization as the transport boundary

Serialization converts a live in-memory structure (a class instance, dict, or object) into a
storable/transmittable representation — JSON text, XML, or raw binary. Deserialization is the
inverse: parsing that representation and rebuilding a usable object on the receiving side.
Use it any time data crosses a process or machine boundary: HTTP API responses, message-queue
publishing (Kafka/RabbitMQ), Redis caching, database persistence, and inter-service calls over
REST or gRPC all depend on it. The key mental model: rich runtime objects become flat portable
encodings on the wire and are reconstituted at the destination.

### Choosing a wire format by trade-off

The article surveys five formats and their selection criteria:

- **JSON** — dominant on the web; human-readable, works in every language and toolchain.
  Weakness: no built-in schema enforcement, so field contracts are informal.
- **XML** — verbose and older, but still entrenched in enterprise integrations and SOAP-based
  APIs; pick it when the ecosystem demands it.
- **Protocol Buffers** — schema-first (`.proto` definitions with numbered fields, e.g. a message
  with a string, a float, and a bool tagged 1/2/3) compiled to compact binary. Very small
  payloads and fast encode/decode make it a favorite for microservice RPC; costs are the schema
  tooling step and loss of human readability.
- **MessagePack** — binary encoding of JSON-shaped data; a near drop-in speed/size upgrade for
  systems already speaking JSON semantics, at the price of readability.
- **Avro** — Apache format common in Kafka and data-pipeline stacks; schemas travel with the
  data or live in a registry, and it supports schema evolution well. Setup is heavier than the
  alternatives, so it earns its keep mainly in streaming/ETL contexts.

Rule of thumb implied: JSON for debuggable public APIs, Protobuf/MessagePack for
performance-sensitive internal traffic, Avro where schema evolution across streaming consumers
matters.

### Serialization failure modes to design against

Because this layer is invisible plumbing, it usually breaks silently and downstream: a renamed
field in a producer breaks consuming clients (mobile apps especially), binary formats make
production debugging harder, and — the security-critical one — deserializing untrusted input
can be an exploit vector. Treat inbound payloads as hostile and validate before reconstruction.

### AuthN vs AuthZ as two distinct questions

Authentication answers identity ("who is this?"); authorization answers permission ("what may
they do?"). The article's framing: an ID check at a building entrance vs the list of floors
that ID unlocks. Conflating the two is a design error — every request needs both an identity
decision and an access decision, and they are enforced by different mechanisms.

### Password storage with slow hashes

Credentials must never be persisted in plaintext. Hash with a deliberately slow, salted
algorithm — bcrypt, Argon2, or scrypt — and verify by re-hashing the submitted password.
Fast digests (MD5, SHA-1) are disqualified precisely because their speed makes offline
brute-forcing cheap. Slowness is the security property here, not a defect.

### Server-side sessions for revocable state

Because HTTP carries no memory between requests, login must mint something the client presents
subsequently. The session model: server stores a record (in a DB or a store like Redis) mapping
a random session id to a user id, and hands the client that id in a cookie; each request does a
lookup. Strength: instant revocation by deleting the record. Weakness: server-side state, which
complicates horizontal scaling across many nodes.

### JWTs for stateless verification

The alternative: the server signs a self-contained token and stores nothing. A JWT is three
dot-separated base64 segments — a header (algorithm, e.g. HS256), a claims payload (user id,
role, expiry timestamp), and an HMAC signature over the first two computed with a server
secret. Any payload tampering invalidates the signature, so verification needs no database
round-trip — ideal across microservices. Trade-offs: revocation before expiry requires an
explicit blocklist (reintroducing state), and a leaked signing secret compromises every token.

### MFA factor classes

Layer independent proof categories: something known (password/PIN), something possessed
(authenticator-app OTP, SMS code, hardware key), something inherent (fingerprint, face).
Two-factor auth combines any two, so a stolen password alone is insufficient to log in.

### Delegated authentication via OAuth 2.0 / OIDC

Rather than owning credential handling, delegate identity to a trusted provider (Google,
GitHub, Apple). Flow: user authenticates at the provider, the provider returns an
authorization code to your backend, and the backend exchanges that code for an access token —
your system never sees the user's password. OAuth 2.0 is the delegation framework; OpenID
Connect layers the identity semantics on top.

### RBAC — role-based access control

Users map to roles; roles map to permission sets (e.g. admin = full CRUD, editor = read+write,
viewer = read-only). Simple to reason about, audit, and administer — the right default for
most applications with a small, stable set of permission tiers.

### ABAC — attribute-based access control

Decisions are policy functions over attributes of the user, the resource, and the environment
— e.g. matching department, a clearance level at or above the document's sensitivity, an
action whitelist, and a business-hours time window, all evaluated together. Far more
expressive than roles for conditional/contextual rules, but harder to audit and reason about;
adopt only when RBAC's granularity genuinely runs out.

### ACLs — per-resource permission lists

Each resource carries its own list of principal→rights entries (the Unix-permissions /
document-sharing model). Maximally precise per-object control, but management cost explodes at
scale — millions of resources times thousands of users becomes unmanageable without tooling.

### Defense-in-depth authorization (route, service, query)

Enforce access at three layers, not one: (1) middleware/route guards (a role-required
decorator gating the endpoint), (2) business-logic checks (ownership or admin verification
before a destructive operation), and (3) data-layer scoping (queries filtered to the current
user's rows so unauthorized data can never even be fetched). Relying solely on the route guard
is the classic root cause of IDOR bugs, where an attacker substitutes another user's resource
id into a URL and the deeper layers hand it over unchecked.

### Auth hardening checklist

Operational best practices collected at the end: slow password hashing (bcrypt/Argon2);
short-lived access JWTs paired with refresh tokens to bound stolen-token damage; authorization
checks at the resource level, not merely "is logged in"; rate limiting on login endpoints
against brute force and credential stuffing; TLS everywhere because bearer tokens over
plaintext HTTP are trivially interceptable; least-privilege permission grants; and audit
logging of auth events (failed logins, token refreshes, permission denials).

## Not absorbed

- Series framing ("second article", recap of the HTTP/routing installment) — meta-navigation, not substance.
- Parcel-shipping and office-security-guard analogies — pedagogical devices; the underlying concepts are captured above.
- Conversational asides and jokes ("bois & grills", the Quicksilver nickname for Protobuf, apology for handwriting) — voice, not engineering.
- The hand-drawn end-to-end flow diagram — referenced but present only as an image, not in the text capture.
- Closing motivational paragraph about gatekeepers/business liability — rhetorical wrap-up; its actionable content is already in the checklist.
- Trailing engagement metrics (views/likes/reposts) — platform chrome from the render.

## Fidelity check

- **Post count in capture:** 1 (single long-form article post; no `---AUTHOR-POST-BREAK---` separators present).

**Article outline as authored:**
1. Intro / series framing
2. The Art of Packing and Unpacking Data (analogy)
3. What Is Serialization?
4. What Is Deserialization?
5. Why backend engineering cares (data-movement contexts)
6. The Popular Formats (JSON, XML, Protobuf, MessagePack, Avro)
7. P.S. — failure modes of the invisible plumbing
8. Authentication and Authorization ("Who are you?" vs "What can you do?")
9. Authentication: Proving Your Identity (username+password, hashing rule)
10. The Token Problem: Staying Logged In — Sessions vs JWT
11. Multi-Factor Authentication (MFA)
12. OAuth 2.0: "Login With Google" (+ OIDC)
13. Authorization: What You're Allowed To Do — RBAC / ABAC / ACL
14. How Authorization Happens in Code (middleware, service, database layers; IDOR)
15. Best Practices at a Glance
16. The Full Picture in One Flow + closing

**Pattern → source-section mapping:**
- Serialization/deserialization as the transport boundary → sections 2–5
- Choosing a wire format by trade-off → section 6 (The Popular Formats)
- Serialization failure modes to design against → section 7 (P.S.)
- AuthN vs AuthZ as two distinct questions → section 8
- Password storage with slow hashes → section 9 (Authentication: Proving Your Identity)
- Server-side sessions for revocable state → section 10 (The Token Problem — Sessions)
- JWTs for stateless verification → section 10 (The Token Problem — JWT)
- MFA factor classes → section 11
- Delegated authentication via OAuth 2.0 / OIDC → section 12
- RBAC → section 13 (Role-Based Access Control)
- ABAC → section 13 (Attribute-Based Access Control)
- ACLs → section 13 (Permission-Based / ACL)
- Defense-in-depth authorization → section 14 (How Authorization Happens in Code)
- Auth hardening checklist → section 15 (Best Practices at a Glance)
