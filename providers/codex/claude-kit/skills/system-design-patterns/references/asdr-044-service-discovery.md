---
source: https://blog.algomaster.io/p/service-discovery-in-distributed-systems
author: AlgoMaster (Ashish Pratap Singh)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Service discovery: a dynamic registry instead of hardcoded service addresses

## What it teaches

Once an application splits into many services whose instances scale up and down and
change hosts, hardcoding network locations breaks: any move or scale event would
ripple through every caller's configuration. Service discovery solves this with a
service registry — a continuously updated, queryable source of truth mapping logical
service names to live instances. A registry record holds the basics (name, IP, port,
status) plus metadata (version, environment, region, tags), health information (last
check, current status), load-balancing hints (weights, priorities), and secure-
communication details (protocols, certificates). The payoff is zero manual endpoint
wiring, seamless scale-out/in, automatic routing away from unhealthy instances via
health checks, and one central place to observe the whole topology.

The article decomposes the problem into two independent axes. First, how instances
get INTO the registry: manual entry (static systems only), self-registration (the
service registers itself at startup and keeps itself fresh with heartbeats),
third-party/sidecar registration (a co-located agent detects the service and
registers on its behalf, keeping registry logic out of the application),
orchestrator-automatic registration (Kubernetes assigns addresses and populates its
built-in DNS as workloads start/stop), and config-management-tool registration
(Chef/Puppet/Ansible updating the registry as they manage lifecycles). Second, how
callers get instances OUT: client-side discovery, where the caller queries the
registry itself, picks an instance with its own load-balancing logic, and connects
directly (Netflix Eureka is the canonical tool); versus server-side discovery,
where the caller just addresses a load balancer or API gateway by service name and
that middle tier does the registry lookup, instance selection, and routing (AWS ELB
is the given example).

## Key patterns & decisions

- **Service registry as single source of truth**: logical names resolve to live
  instance sets enriched with health, version, region, and weight metadata — never
  hardcoded addresses.
- **Self-registration with heartbeat renewal**: an instance announces itself at
  startup and periodically re-confirms liveness so the registry reflects reality.
- **Sidecar (third-party) registration**: an external co-located agent handles
  registration, decoupling discovery plumbing from application code.
- **Orchestrator-native discovery**: in Kubernetes-like platforms, registration is a
  platform side effect (built-in DNS), not application logic — prefer it when
  available.
- **Client-side vs. server-side discovery split**: client-side gives callers custom
  load-balancing control and removes a central hop but forces discovery logic into
  every consumer and couples clients to the registry protocol; server-side
  centralizes routing behind a gateway/LB at the cost of an extra hop and a
  potential single point of failure.
- **Registry high availability is non-negotiable**: replicate the registry, run
  multiple instances, and rehearse failover — it is the system's address book.
- **Health-checked eviction and deregistration hygiene**: automatically remove
  failing instances and ensure clean deregistration so stale entries don't route
  traffic into the void.
- **Registry-query caching**: cache discovery results in clients/gateways to cut
  registry load and lookup latency.
- **Versioned service naming**: unique, versioned names (e.g., a payments service
  with an explicit v-suffix) prevent routing collisions during upgrades.

## When to apply / trade-offs

Essential for any microservice or multi-instance deployment with dynamic scaling;
irrelevant for a single static server. Choose client-side discovery when consumers
need bespoke instance-selection strategies and you can afford discovery libraries
in every client; choose server-side when you want thin clients and centralized
policy, accepting the extra network hop and hardening the LB/gateway against
becoming the failure domain. In orchestrated environments, prefer the platform's
built-in mechanism over bolting on a separate registry. The recurring failure modes
the best-practices list guards against: an unreplicated registry taking down all
inter-service calls, stale registrations from crashed instances, and registry
overload absent caching. (A reader comment asks whether ZooKeeper counts as a
registry — historically yes, it is a common coordination-store choice, though the
article itself names Eureka and AWS ELB.)

## Fidelity check

1. Claim: registry records carry more than address/port — health, version, region,
   weights, and security details. Capture support: the article's registry-contents
   list enumerates basic details (name, IP, port, status), metadata (version,
   environment, region, tags), health status with last check, load-balancing
   weights/priorities, and secure-communication protocols/certificates.
2. Claim: there are five registration routes, from manual to config-management.
   Capture support: the registration-options section walks through manual
   registration, self-registration (with heartbeat upkeep), third-party/sidecar
   registration, automatic registration by orchestrators such as Kubernetes with
   built-in DNS, and configuration-management tools (Chef, Puppet, Ansible).
3. Claim: client-side discovery trades consumer complexity for load-balancing
   control, server-side trades an extra hop and SPOF risk for thin clients.
   Capture support: the pros/cons lists state client-side is simple and reduces
   central-LB load but requires discovery logic in consumers and couples them to
   registry protocol changes, while server-side centralizes discovery logic but
   introduces an additional network hop and a load balancer that can become a
   single point of failure; Eureka and AWS ELB are cited as the respective examples.
