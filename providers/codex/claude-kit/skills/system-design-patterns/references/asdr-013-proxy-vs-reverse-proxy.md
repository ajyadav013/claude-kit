---
source: https://blog.algomaster.io/p/proxy-vs-reverse-proxy-explained
author: AlgoMaster (Ashish Pratap Singh)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Forward vs reverse proxies: whose identity is being shielded?

## What it teaches

Both kinds of proxy are intermediaries in the request path; the entire
distinction is *which side they represent*. A forward proxy stands in for
clients: outbound requests from a private network detour through it, the
destination only ever sees the proxy's address, and the proxy can veto,
forward, or answer from cache. A reverse proxy stands in for servers: it is
the single advertised entry point of a backend fleet, receives every inbound
request, and picks which hidden origin server handles it. One hides who is
asking; the other hides who is answering.

For the forward direction, the article covers the classic uses — anonymity,
corporate access control and usage monitoring, content filtering, and shared
caching — plus two worked scenarios: routing through a proxy in another
country to appear local to a geo-restricted service, and an office caching
proxy that serves repeat requests from local storage with a time-to-live to
expire stale entries. It also draws the proxy/VPN line: both mask your
address, but a VPN encrypts the whole traffic stream while a plain proxy just
relays requests.

For the reverse direction, it enumerates the standard duties of the modern
edge tier: shielding origin addresses from direct attack, distributing load
across replicas, caching static assets, terminating TLS so backends skip the
crypto work, and inspecting requests as a web application firewall. Cloudflare
is used as the real-world case — WAF plus DDoS filtering in front of origins,
with content cached across 200+ global points of presence. A short Nginx
section (config shown in the source, described here in prose only) shows that
standing up a reverse proxy amounts to: listen on the public port, relay
requests to an upstream address, and pass along headers that preserve the
original host and true client IP. Balancing across an upstream pool is a
declared server list plus a chosen algorithm — round-robin by default, with
least-connections or source-IP-hash (which pins a client to one backend) as
one-line alternatives.

## Key patterns & decisions

- **Direction-of-representation as the defining axis**: forward proxy = agent
  of the client, reverse proxy = agent of the server fleet; every other
  difference follows from that.
- **Single controlled ingress point**: funneling all inbound traffic through
  one gatekeeper enables filtering, rate discipline, and hidden origins.
- **Edge caching with TTL expiry**: serve repeats from proxy storage; bound
  staleness with a configured lifetime rather than manual invalidation.
- **TLS termination at the edge**: decrypt once at the proxy and relay
  plaintext internally, offloading handshake/crypto cost from app servers.
- **WAF at the reverse proxy**: request inspection and malicious-traffic
  blocking belong at the boundary, before application code runs.
- **Client-identity forwarding headers**: because the proxy replaces the
  client on the wire, the original host and caller IP must be carried in
  dedicated forwarded-for style headers or backends lose that information.
- **Pluggable balancing algorithms**: round-robin for uniform spread,
  least-connections for uneven work, IP-hash when session affinity matters.

## When to apply / trade-offs

Use a forward proxy when the *organization of clients* needs policy: egress
control, monitoring, shared caching, or location masking. Use a reverse proxy
in front of essentially any multi-instance or internet-facing backend — it is
the natural home for TLS, WAF, static caching, and load distribution.
Trade-offs: any proxy is an added hop and a potential single point of failure
or bottleneck; caching layers introduce staleness windows; TLS termination
means traffic behind the proxy is plaintext unless you re-encrypt; IP-hash
affinity fights even distribution. A proxy is also not a VPN — do not mistake
address masking for transport encryption.

## Fidelity check

1. *Claim*: the destination server never learns the real client address when
   a forward proxy is in use. — *Capture support*: the request walkthrough
   states the target site sees only the proxy's IP, never the user's.
2. *Claim*: the default Nginx upstream balancing behavior is round-robin, and
   the algorithm is switched by naming an alternative in the upstream
   declaration. — *Capture support*: the article says Nginx balances
   round-robin unless another method such as source-IP hashing is added to
   the upstream block.
3. *Claim*: Cloudflare operates as a reverse proxy combining attack filtering
   with a global cache. — *Capture support*: the article describes
   Cloudflare's WAF/DDoS layer blocking malicious traffic before it reaches
   origin servers, plus caching at more than 200 data centers to cut latency.

Note: the closing comparison table in the source rendered as an image and did
not survive text capture; its substance is covered by the prose sections.
