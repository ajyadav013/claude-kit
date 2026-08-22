---
source: https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices
author: Model Context Protocol project (LF Projects)
license-note: ideas absorbed in own words; no text or code reproduced
---

# MCP's real attack surface is OAuth delegation, not the tool calls

## What it teaches

The MCP security guidance is not about prompt injection or malicious tool
descriptions; it is an OAuth threat catalogue for the case where an agent
runtime sits between a user, a client, and third-party APIs. Its spine is
delegation: whenever one component holds credentials on behalf of another,
somebody can be tricked into acting with authority it should not lend. The
document enumerates concrete failures — a proxy with a static upstream client
ID that lets a browser consent cookie skip the approval screen for a freshly
registered attacker client; a server that accepts a token minted for a
different audience and relays it downstream; a client that dutifully fetches
whatever discovery URL a hostile server advertises, including cloud metadata
endpoints; a stateless server that treats possession of a workflow handle as
proof of identity. For each it states normative controls in RFC 2119 terms,
and it is unusually blunt about which mitigations do *not* work: PKCE does
not stop mix-up attacks, and a CIMD metadata document cannot prove which
local process owns a localhost redirect URI.

## Key patterns & decisions

- **Per-client consent must precede the upstream flow** — a proxy that
  authenticates to a third-party authorization server under one static client
  ID, while letting MCP clients dynamically register their own IDs, inherits
  the upstream's consent cookie. The fix is an MCP-level consent registry
  keyed per user per client_id, checked before any redirect upstream.

- **Set the state cookie only after consent is approved** — the ordering is
  the whole control. If the session or cookie carrying the OAuth `state` is
  established before the user clicks approve, an attacker can craft a request
  that walks straight past the consent screen. State values must be
  cryptographically random, server-stored, single-use, and short-lived (the
  page suggests roughly ten minutes).

- **Token passthrough is forbidden, not discouraged** — a server must reject
  any token not explicitly issued to it, checking the audience claim per
  RFC 9068. Relaying an unvalidated token defeats rate limiting and request
  validation, makes downstream logs attribute actions to the wrong principal,
  and turns the server into an exfiltration proxy for a stolen credential.

- **Discovery URLs are attacker-controlled input** — `resource_metadata` from
  a `WWW-Authenticate` header, `authorization_servers`, `token_endpoint` and
  friends all come from the server being talked to. Clients should require
  HTTPS outside loopback, block private and reserved ranges (10/8, 172.16/12,
  192.168/16, 127/8, 169.254/16, fc00::/7, fe80::/10), and validate every
  redirect hop rather than following blindly.

- **Do not hand-roll the IP allowlist** — encoding tricks (octal, hex,
  IPv4-mapped IPv6) defeat bespoke parsers, and DNS is a TOCTOU hazard where a
  name resolves safely at validation and internally at fetch time. The
  recommended posture is an egress proxy plus DNS pinning, i.e. push the
  control into the network rather than the parser.

- **The same SSRF exposure runs the other direction** — an authorization
  server that accepts Client ID Metadata Documents fetches a URL supplied by
  an unauthenticated stranger, so the private-range and egress-proxy
  mitigations apply to authorization servers too, not only clients.

- **State handles are capabilities, not identities** — MCP has no
  protocol-level session, so servers mint handles (cart ID, workflow ID) that
  return as ordinary tool arguments. Bind each handle server-side to the user
  ID derived from the verified token, key stored state by that pair, and
  reject a handle presented by any other principal.

- **Local server startup is arbitrary code execution** — one-click config must
  show the untruncated command, flag dangerous patterns and sensitive paths,
  require explicit approval, and ideally sandbox the child process. Servers
  meant to run locally should prefer stdio or an authenticated IPC socket over
  an open HTTP port, which is reachable by DNS rebinding.

- **Authorization URLs need scheme allowlisting and shell-free opening** — a
  hostile server can return a `javascript:` or shell-metacharacter URL; the
  client must accept only http/https (http on loopback only) and must never
  route the URL through a shell. In proxy architectures this chains: XSS in
  the client steals the proxy auth token, and the proxy will spawn processes.

- **Scope minimization is an incident-blast-radius control** — publishing
  every scope in `scopes_supported` and using omnibus scopes drives consent
  abandonment and makes a stolen token universal. Start at a minimal baseline,
  elevate via targeted `WWW-Authenticate` scope challenges, accept
  down-scoped tokens, and log which subset was granted.

## When to apply / trade-offs

Apply this whenever a project builds or hosts an MCP server, or runs an MCP
client that talks to servers it does not control — especially when the server
fronts a third-party API, because that proxy shape is where the confused
deputy lives. The cost is real: per-client consent means a consent UI, a
consent store and CSRF protection you would not otherwise build; step-up scope
challenges add round trips and client-side scope accumulation logic; egress
proxies add infrastructure. A purely local, single-user stdio server with no
OAuth touches almost none of this, and stacking a step-up flow onto such a
setup is ceremony without benefit. Note also that some mitigations are only
as good as their counterparty — issuer-based authorization response validation
protects against mix-up only if the honest authorization server actually emits
`iss`, and no client-side control can distinguish two processes competing for
the same localhost redirect URI.

## Fidelity check

1. Claim: the state cookie must not be set until after consent approval, or
   the consent screen is ineffective. Support: the capture states this
   explicitly, requiring the state tracking cookie or session be set
   immediately before the redirect to the third-party identity provider and
   only after consent has been approved, and notes single-use state with a
   short expiration given as roughly ten minutes.
2. Claim: token passthrough is prohibited and hinges on audience validation.
   Support: the capture says servers MUST NOT accept tokens not explicitly
   issued to them, cites the audience claim and RFC 9068, and lists the
   consequences as control circumvention, broken audit trails, trust-boundary
   breakage, and future-compatibility risk.
3. Claim: clients should block private and link-local ranges and avoid
   hand-written IP validation. Support: the capture enumerates 10.0.0.0/8,
   172.16.0.0/12, 192.168.0.0/16, 127.0.0.0/8, 169.254.0.0/16, fc00::/7 and
   fe80::/10 citing RFC 9728 Section 7.7, warns that octal, hex and
   IPv4-mapped IPv6 encodings defeat custom parsers, and recommends egress
   proxies and DNS pinning against TOCTOU.
