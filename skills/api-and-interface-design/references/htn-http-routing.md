# Digest: HTTP & Routing

- **Source:** https://x.com/Harry_The_Nerd/status/2053366145995178087
- **Author:** Harshit Khosla (@Harry_The_Nerd)
- **Category:** Backend Engineering (article #1 of the author's backend series)
- **Fetched:** 2026-07-23/24 via logged-out browser render
- **License note:** Content (c) the author; this digest is an own-words summary for internal engineering reference — no verbatim text.

## Patterns

### Three-part HTTP response anatomy
Every response the server returns is built from the same three pieces: a status line (protocol version + numeric code + reason phrase), a header block of metadata that tells the client how to interpret what follows, and an optional body carrying the payload (JSON, HTML, binary, or nothing). Use this decomposition when debugging: the status line answers "did it work?", the headers answer "how should I treat it?", and only then does the body matter. Trade-off awareness: a body-less response is legitimate (e.g., 304), so client code must not assume content is always present.

### Status-code families as a triage system
Codes are bucketed by their first digit — 1xx informational, 2xx success, 3xx redirection, 4xx caller error, 5xx server fault — so the family alone tells you which side of the wire to blame before reading anything else. The article singles out the codes an engineer should reach for deliberately: 200 (success with data), 201 (resource created), 301 (permanent move; browsers cache it, so it is hard to undo), 304 (client's cached copy is still valid), 400 (malformed input), 401 (authentication missing) vs 403 (authenticated but not authorized — a distinction worth encoding correctly), 404 (no such resource), 429 (rate limited), 500 (unhandled server failure), 503 (server down or saturated). When to use: designing API error semantics and writing client retry logic (429/503 are retryable; 4xx generally are not).

### Cache and security headers that do real work
A small set of response headers carries most of the operational weight:
- `Content-Type` declares the body format; without it the client cannot parse reliably.
- `Cache-Control` sets caching policy — a max-age in seconds for shareable data, `no-store` for anything sensitive, `private` to keep copies out of shared caches/CDNs.
- `Set-Cookie` with the three hardening flags: `HttpOnly` (script cannot read the cookie), `Secure` (transmitted only over HTTPS), `SameSite=Strict` (never attached to cross-site requests). Default to all three for session cookies.
- `ETag` gives the response a content fingerprint; the client echoes it on the next request and an unchanged resource comes back as a tiny 304 instead of a full payload — a bandwidth optimization with almost no downside beyond server-side fingerprint computation.
- `Retry-After` accompanies 429/503 to tell well-behaved clients exactly how long to back off, turning blind retry loops into scheduled ones.

### CORS as a browser-enforced read gate
When a page calls an origin other than its own (origin = scheme + host + port, so an api subdomain is already a different origin), the browser checks whether the responding server has allow-listed the calling origin via `Access-Control-Allow-Origin`. The threat it neutralizes: because browsers auto-attach cookies to requests toward the cookie's domain, a malicious page could fire an authenticated fetch at your bank and read the reply. CORS does not stop the request or the response — it stops the attacker's JavaScript from *reading* the response when the allow header is absent. Critical operational fact: this is purely a browser mechanism; curl, Postman, and server-side runtimes ignore it entirely, so CORS is user protection, never API access control. Don't mistake a permissive CORS policy for security, and don't expect CORS to defend against non-browser clients.

### Simple vs. preflighted requests and preflight caching
Browsers split cross-origin calls into two classes. Reads with plain headers (GET, HEAD, basic POST) fly immediately and only the response is policy-checked — safe, because an unreadable response does no harm. Mutating or exotic requests (PUT, DELETE, custom headers like Authorization) trigger an automatic OPTIONS probe first, announcing the intended method and headers; the real request goes out only if the server approves. Rationale: a destructive operation causes damage the moment it executes, so permission must be checked *before* firing, not after. Cost: preflights double round trips; mitigate with `Access-Control-Max-Age` (e.g., 86400 = a day) so the browser reuses one approval instead of re-asking per request.

### Content negotiation across four axes
Client and server agree on the shape of the payload before it is sent, along four dimensions, each an Accept-style request header answered by a Content-* response header:
1. **Format** — `Accept` lists media types with q-weights (0–1 preference scores); the server picks the best supported match and confirms via `Content-Type`, or returns 406 if nothing overlaps.
2. **Compression** — `Accept-Encoding` advertises supported codecs; the server answers with `Content-Encoding`. Rough numbers from the article: gzip cuts JSON around 77% and works everywhere; Brotli reaches roughly 82% but is HTTPS-only; Zstandard is newer and decodes faster at comparable ratios. Decompression is transparent to application code.
3. **Language** — `Accept-Language` with q-weights lets one URL serve localized bodies, confirmed via `Content-Language`.
4. **Charset** — effectively settled; always emit UTF-8.
Use negotiation whenever one endpoint must serve heterogeneous clients; the trade-off is server-side branching complexity and the caching hazard handled by `Vary` (below).

### Vary as the cache-correctness contract
Any response whose body differs based on request headers must declare those headers in `Vary` (e.g., encoding and language). This instructs CDNs and intermediary caches to key stored copies on those header values. Omitting it is a classic production bug: a cache stores one client's compressed variant and hands it to a client that cannot decode it. Rule of thumb: whatever you negotiate on, you list in Vary. Cost: more cache keys means lower hit rates, so negotiate only on axes you actually serve differently.

### Method + path as the routing key
Routing maps the pair (HTTP method, URL path) onto a handler function. Because the method participates in the key, a GET and a POST at the same path are distinct routes with independent logic — the method carries intent (read vs. create vs. replace vs. delete), the path carries destination. This is the foundation for organizing handler code and for the REST convention of one resource path exposing several verbs.

### Static vs. dynamic routes; path vs. query parameters
Static routes are fixed strings; dynamic routes embed named placeholders (colon-prefixed in Express-style syntax) whose runtime segment values the framework extracts and hands to the handler. Complementing that, the article draws the parameter split: path parameters identify *which* resource (an ID embedded in the path), while query parameters — key/value pairs after the `?` — modify *how* the resource collection is handled: filtering, sorting, searching, pagination. Practical driver: GET requests carry no body, so the query string is their data channel. Design rule: identity in the path, behavior modifiers in the query.

### Nested routes for resource hierarchy
Parent-child resources can be expressed structurally in the URL (a posts collection scoped under a specific user's ID). Benefit: the route itself documents the relationship and handlers receive both parent and child identifiers. Trade-off: deep nesting couples client URLs to your data model; keep hierarchies shallow.

### Versioning and deprecation lifecycle
APIs evolve without breaking existing consumers by running multiple versions side by side — commonly a version segment in the path (v1, v2), alternatively a header or query parameter. Retirement is a signaled process, not a surprise: the `Deprecation` and `Sunset` HTTP headers announce that a version is obsolete and when it will disappear, giving clients a migration window before removal.

### Catch-all routes as the fallback layer
A wildcard route (Express/React Router `*`, Next.js bracket-spread segments) matches anything no explicit route claimed. Standard uses: serving 404 pages, handling arbitrarily deep dynamic paths, and the SPA pattern of routing every unknown path to the app shell so client-side routing can take over. Keep it registered last so it never shadows real routes.

## Not absorbed

- **Series announcement intro** — the author launching his backend + system design series and hoping readers enjoy it; personal framing, no engineering content.
- **"What the heck is your backend?" section** — a beginner-level definition of frontend vs. backend; audience-orientation prose rather than a pattern.
- **The nightclub/bouncer analogy for CORS** — pedagogical device; the underlying mechanism is captured in the CORS pattern above.
- **Conversational asides in the status-code list** (jokey glosses on 401/429 etc.) — tone, not substance; the codes themselves are absorbed.
- **Closing sign-off and engagement counts** (views/likes/reposts) — platform chrome.

## Fidelity check

**Post count in capture:** 1 (a single long-form article post; the JSON reports postCount 1 and contains no `---AUTHOR-POST-BREAK---` separators).

**Article outline as the author structured it:**
1. Series intro
2. What the heck is your backend?
3. What is HTTP?
4. HTTP Responses (status line / headers / body)
5. Status Codes
6. The Headers That Matter
7. CORS: Cross-Origin Resource Sharing (nightclub analogy; Why CORS Exists; Simple vs Preflighted Requests)
8. Content Negotiation and Compression (The Core Idea; The Four Things They Negotiate On; Vary; A Full Real-World Exchange)
9. Routing (What is Routing; Types of Routes; Path Parameters vs. Query Parameters; Nested Routing; Route Versioning and Deprecation; Catch-All Routes)
10. Sign-off

**Pattern-to-section citations:**
- Three-part HTTP response anatomy → section 4, "HTTP Responses"
- Status-code families as a triage system → section 5, "Status Codes"
- Cache and security headers that do real work → section 6, "The Headers That Matter"
- CORS as a browser-enforced read gate → section 7, "CORS" + "Why CORS Exists" (browser-only caveat from the end of the CORS section)
- Simple vs. preflighted requests and preflight caching → section 7, "Simple vs Preflighted Requests"
- Content negotiation across four axes → section 8, "The Four Things They Negotiate On"
- Vary as the cache-correctness contract → section 8, the Vary passage and "A Full Real-World Exchange"
- Method + path as the routing key → section 9, "What is Routing?"
- Static vs. dynamic routes; path vs. query parameters → section 9, "Types of Routes" + "Path Parameters vs. Query Parameters"
- Nested routes for resource hierarchy → section 9, "Nested Routing"
- Versioning and deprecation lifecycle → section 9, "Route Versioning and Deprecation"
- Catch-all routes as the fallback layer → section 9, "Catch-All Routes"
