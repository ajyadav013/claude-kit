---
source: https://www.uber.com/en-IN/blog/single-zone-failure-tolerance/
author: Uber Engineering
license-note: ideas absorbed in own words; no text or code reproduced
---

# Making a live Cassandra fleet survive the loss of one availability zone — with zero downtime

## What it teaches

Uber runs Cassandra as an internal database service across many zones and
regions, but for years all nodes in a region shared one "rack" label. Because
Cassandra's placement algorithm only spreads replicas across distinct rack
values, this meant a majority — or even all three — copies of a record could
land in the same zone, so a single zone outage could take data offline. The
article walks through how Uber converted the whole fleet, in production, to a
zone-per-rack layout where every zone holds at most a minority of each record's
replicas, without downtime, client changes, or SLO regressions.

The most instructive part is *why the obvious fix doesn't work*: you cannot
just relabel or add multi-rack nodes to an existing single-rack ring. The
moment one node advertises a second rack, the placement algorithm tries to put
a replica of *everything* on that lone node, instantly creating a hotspot. So
the safe path is a parallel-ring (blue/green) migration: stand up an entire new
correctly-labeled ring beside the old one, replicate into it, flip traffic,
and retire the original.

## Key patterns & decisions

- **Zone-as-rack replica placement**: map each availability zone to a distinct
  Cassandra rack so quorum survives any single-zone loss (needs zone count >=
  replication factor).
- **Parallel-ring (blue/green) topology migration**: never mutate a live
  ring's rack topology in place; build a second ring with the target layout
  and swap, because incremental rack introduction creates an instant hotspot.
- **Two-stream data sync**: catch live writes by adding the new ring to
  keyspace replication (cross-dc replication), and backfill history with the
  built-in node rebuild/streaming tooling — both must complete before cutover.
- **Native-transport as a traffic valve**: provision new nodes with client
  connections disabled, then flip the cutover by enabling client transport on
  the new ring and disabling it on the old one — no client redeploys.
- **Service-discovery-backed contact points**: a small dedicated service
  publishes each cluster's current same-region node addresses, so
  applications never hardcode topology and migrations stay invisible to them.
- **Remove topology pinning in clients**: dropping the DC-pinning load
  balancing policy (in favor of token-aware/round-robin plus a same-region
  host filter) is what lets clients drift automatically to whichever ring is
  accepting connections.
- **Local-quorum + region-by-region rollout**: because clients only talk to
  local-region coordinators with local-quorum consistency, each region can be
  migrated independently without cross-region blast radius.
- **Accept temporary tolerance loss under capacity pressure**: when a zone
  lacks spare capacity during urgent scaling, scale first (sacrificing the
  zone-failure property), then automatically relocate nodes back into balance
  when capacity arrives.

## When to apply / trade-offs

- Applies to any quorum-replicated store (Cassandra, etcd-like layouts,
  Kafka rack awareness) deployed across zones: the failure-tolerance property
  is a *placement* property, not a replication-factor property.
- The parallel-ring approach doubles hardware in the region for the duration
  of the migration — that is the price of zero downtime plus rollback (either
  ring can serve until the old one is decommissioned).
- Requires clients that can re-discover topology dynamically; if your drivers
  pin to specific hosts or DCs, fix the client layer first or the cutover
  can't be transparent.
- Zone-balanced placement constrains scaling: every zone must be scaled
  uniformly, which becomes an ops/capacity-planning burden that Uber handled
  with control-plane automation rather than manual work.
- Validation matters: they ran deliberate full-zone shutdown drills in
  production to prove the property held, rather than trusting the topology on
  paper.

## Fidelity check

1. Claim: a single mislabeled-rack setup can put a replica majority in one
   zone. Support: the capture explains all Uber nodes shared one default rack
   value, so replicas were not separated and a zone failure could remove the
   majority of a record's copies.
2. Claim: in-place conversion creates a hotspot. Support: the capture states
   that introducing a node with a new rack into a single-rack ring causes the
   placement algorithm to route a replica of every record to that new rack
   even when it contains just one node.
3. Claim: cutover was done without client action. Support: the capture
   describes enabling native transport on the new ring and disabling it on
   the old, with Uber's forked Go/Java drivers plus a contact-point service
   automatically reconnecting clients to the new ring.
