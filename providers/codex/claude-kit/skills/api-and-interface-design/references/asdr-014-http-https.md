---
source: https://algomaster.io/learn/system-design/http-https
author: AlgoMaster (Ashish Pratap Singh)
license-note: ideas absorbed in own words; no text or code reproduced
---

# HTTP semantics are stable; the transport underneath keeps changing

## What it teaches

A production-oriented tour of HTTP/HTTPS that separates the durable layer
(methods, status codes, headers, bodies, caching rules) from the evolving
layer (which transport carries the frames). HTTP/1.1 and HTTP/2 ride TCP;
HTTP/3 rides QUIC over UDP — but the request/response meaning is identical
across all three. HTTPS is simply HTTP inside a TLS channel, giving
confidentiality, tamper detection, and *server* authentication — and the
article is careful to list what TLS does NOT give you: user authentication,
application-level safety, or full metadata privacy (the destination IP and,
often, the hostname via SNI still leak).

The method table is framed around two operational properties rather than REST
aesthetics: *safe* (read-only intent) and *idempotent* (repeat = same intended
effect). Those properties are what proxies, gateways, and retry logic key off,
so a state-changing POST needs an idempotency key before anyone may retry it.
Status codes are treated as part of the API contract — a generic 500 for a
validation error, or a 200 wrapping an error payload, actively breaks caches,
metrics, SDKs, and retry policies.

The TLS section corrects a common textbook story: modern TLS 1.3 does not
encrypt a pre-master secret under the server's public key; it uses ephemeral
key agreement (ECDHE), which yields forward secrecy — recorded traffic stays
sealed even if the server key later leaks. ALPN negotiates the application
protocol in the handshake; 0-RTT resumption trims latency but is replayable,
so it is only for idempotent operations. Version history: HTTP/1.1 serializes
responses per connection (clients open several connections to compensate;
pipelining never worked out); HTTP/2 multiplexes binary-framed streams with
header compression but still stalls *all* streams when one TCP segment is
lost; HTTP/3/QUIC gives per-stream loss recovery and connection migration
across network changes, at the price of UDP reachability problems that demand
fallback paths. HTTP/2 server push is dead — do not design around it.

## Key patterns & decisions

- **Safety/idempotency as the retry contract**: retry policy must be derived
  from method semantics; unsafe non-idempotent calls need idempotency keys.
- **Precise status codes as machine-readable contract**: pick codes that
  caches, clients, and dashboards can act on; never smuggle errors in a 200.
- **Conditional requests and cache-control headers**: version-tag revalidation
  avoids re-downloading unchanged bodies; personalized responses must be
  explicitly marked private or non-storable.
- **Stateless protocol, deliberately placed state**: HTTP carries no session
  memory, so decide where state lives and what happens when a request is
  retried, rerouted, or completes after the client gave up.
- **Forward secrecy via ephemeral key exchange**: TLS 1.3's ECDHE model
  protects past recordings from future key compromise.
- **0-RTT only for replay-safe operations**: early data cuts a round trip but
  an attacker can replay it, so restrict it to idempotent reads.
- **Head-of-line blocking moves down the stack**: HTTP/2 fixed it at the HTTP
  layer, TCP reintroduces it at the segment layer, QUIC fixes it per stream.
- **Per-stage timeouts plus an overall deadline**: separate limits for DNS,
  connect, TLS handshake, request write, and header wait; library defaults
  are unsafe.
- **Bounded retries with backoff, jitter, and budgets**: post-timeout retries
  are ambiguous (the server may have acted), and aggressive retries deepen
  outages.
- **Trust forwarding headers only from your own edge**: client-supplied
  forwarded-for/proto headers are forgeable unless the boundary proxy strips
  or rewrites them.
- **Percentile-and-dimension observability**: break latency, status classes,
  retry rates, and cache hits down by route/method/client/region — averages
  hide user-visible failures.

## When to apply / trade-offs

This is baseline material for any API, gateway, or service-mesh design review:
default to HTTPS everywhere (TLS cost is negligible next to app and network
work), encode retryability into methods and idempotency keys, and set every
timeout explicitly. Adopt HTTP/3 only where its wins (mobile network
switching, many parallel streams, handshake latency) matter *and* you can
monitor QUIC failures and fall back to HTTP/2/1.1, since some networks
degrade or block UDP. For streaming (e.g. AI token output), plan cancellation,
idle timeouts, backpressure, and time-to-first-token metrics from the start.

## Fidelity check

1. *Claim*: TLS 1.3 achieves forward secrecy through ephemeral key exchange,
   not public-key encryption of a shared secret. — *Capture support*: the
   article explicitly flags the old pre-master-secret description as not the
   TLS 1.3 model and credits ECDHE with keeping previously recorded
   connections safe after a later key theft.
2. *Claim*: HTTP/2 does not eliminate head-of-line blocking, it only lifts it
   to the TCP layer. — *Capture support*: the capture states that one lost
   TCP segment can force every multiplexed HTTP/2 stream on that connection
   to wait for the missing bytes.
3. *Claim*: forwarded-identity headers must only be trusted when set by
   infrastructure you control. — *Capture support*: the article warns public
   clients can fake forwarded-for style headers unless the edge proxy removes
   or rewrites them.
