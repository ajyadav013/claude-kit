---
source: https://algomaster.io/learn/system-design/ip-address
author: AlgoMaster (algomaster.io)
license-note: ideas absorbed in own words; no text or code reproduced
---

# IP addresses are routing coordinates, not identity

## What it teaches
An IP address answers exactly one question — where should this packet go
next — and system-design bugs bloom whenever it's asked to answer anything
else (who is this user, is this device trusted, will this address still exist
tomorrow). The chapter covers the mechanics (IPv4 exhaustion and how NAT,
private ranges, and CIDR stretched it; IPv6 and dual-stack reality;
longest-prefix-match, hop-by-hop routing; TTL; BGP) but the throughline is
operational: addresses attach to interfaces, not machines; they're shared by
NAT and carrier-grade NAT; they're rewritten by proxies and load balancers;
and containers churn through them. It closes with the design consequences:
plan CIDR space like architecture, preserve original client IPs deliberately,
and bind service contracts to names, not numbers.

## Key patterns & decisions
- **Treat IPs as routing coordinates, never identity or trust**: rate
  limiting by public IP punishes everyone behind one NAT; office-IP
  allowlists break under VPNs and mobile; pods and containers churn
  addresses — use IP as one weak signal in a broader identity model.
- **CIDR planning is infrastructure architecture**: overlapping VPC ranges
  (everyone defaulting to the same /16) is among the costliest cloud
  mistakes, forcing NAT, proxies, or renumbering to ever connect the
  networks; reserve room for growth, future regions, corporate/VPN/partner
  ranges, and Kubernetes pod appetite up front.
- **Know the subnet arithmetic and its exceptions**: prefix length fixes the
  block size; classic IPv4 subnets lose network + broadcast addresses;
  /31s and /32s break the "minus two" rule; cloud providers quietly reserve
  extra addresses per subnet; IPv6 has no broadcast at all.
- **NAT is a scarcity workaround with a failure-mode bill**: connection-
  table exhaustion under churn, idle-timeout drops on long-lived
  connections, inbound reachability requiring port-forwarding/LB/VPN,
  shared-IP blame in logs and rate limits, and NAT gateways becoming cost,
  capacity, and availability chokepoints for high-egress workloads.
- **Preserve the real client address only via trusted infrastructure**:
  X-Forwarded-For/Forwarded/proxy-protocol values are client-forgeable
  unless a proxy you control overwrites them; behind LBs the socket source
  IP is the proxy, not the user.
- **Bind-address semantics are a classic footgun**: loopback binding
  exposes a service only to the same host, all-interfaces binding exposes
  it to the network — the root of many "works locally, unreachable
  remotely" mysteries; the all-zeros address means different things as bind
  address, default route, and unassigned source.
- **Memorize the special ranges that show up in incidents**: loopback,
  link-local self-assignment (a 169.254.x.x address usually means DHCP
  failed), the cloud metadata endpoint at 169.254.169.254 (an SSRF
  crown-jewel — treat access as security-sensitive), carrier-grade NAT
  space, and default-route notation.
- **Routing = longest prefix match, hop by hop**: the most specific route
  wins; each router only knows the next hop; TTL/hop-limit expiry is both
  loop protection and the mechanism traceroute exploits.
- **Reachability is a layer of its own**: BGP announces ranges without
  knowing application health; the 2021 Facebook outage was prefixes
  vanishing from global routing, not an app or database failure.
- **Prefer DNS/service-discovery names in contracts**: names allow
  failover, migration, cert validation, and regional routing; hard-coded
  IPs should be rare, infrastructure-level, and documented.
- **Dual-stack doubles the failure surface**: publishing both A and AAAA
  avoids a hard IPv6 cutover, but firewalls, discovery, metrics, logs, and
  runbooks must all handle two address families.

## When to apply / trade-offs
- Apply the "IP is not identity" rule when designing rate limiting, abuse
  detection, allowlists, and audit logging; accept that IP-based controls
  are coarse and pair them with authenticated identity.
- Do CIDR planning before the first VPC ships; the cost of fixing overlap
  grows with every peering, merger, and migration. Kubernetes pod ranges
  deserve explicit early sizing.
- NAT gateways are fine defaults for private-subnet egress but budget for
  them as capacity/cost/availability dependencies when workloads pull
  large artifacts or open many connections.
- Header-based client-IP recovery is only as trustworthy as the proxy
  chain; strip or overwrite forwarded headers at the trust boundary.

## Fidelity check
1. Claim: overlapping private ranges are called one of the most expensive
   cloud networking mistakes. Capture support: the text states that if two
   VPCs both use the same 10.x /16, connecting them becomes difficult or
   impossible without NAT, proxying, renumbering, or complex translation.
2. Claim: forwarded-client-IP headers must only be trusted from controlled
   infrastructure. Capture support: it lists X-Forwarded-For, Forwarded,
   proxy protocol, and LB metadata as the mechanisms, warning that clients
   can fake HTTP headers unless a trusted proxy cleans or overwrites them.
3. Claim: the metadata endpoint and link-local range are debugging/security
   landmarks. Capture support: it explains a 169.254.x.x self-assigned
   address signals DHCP failure, and that 169.254.169.254 serves cloud
   instance metadata that can expose credentials — flagged as especially
   dangerous in systems fetching user-supplied URLs.
