---
source: https://engineering.fb.com/2022/05/04/data-infrastructure/delta/
author: Meta Engineering (Kumar Mrinal, Binbin Lu)
license-note: ideas absorbed in own words; no text or code reproduced
---

# Delta: chain replication as the deliberately-boring bottom layer of Meta's recovery stack

## What it teaches

Delta is Meta's object store for the stuff that has to survive when everything else
is down: build and distribution artifacts and the bootstrap data used to restore the
rest of the infrastructure from a handful of machines. Because it sits at the very
bottom of the dependency stack, its design inverts the usual priorities — simplicity
and recoverability outrank latency, throughput, and storage efficiency. The API is
just four operations (put, get, delete, list), it is explicitly not a filesystem and
not a general-purpose store, and it accepts full-copy replication cost to avoid the
complexity of erasure coding and quorum consensus.

The replication mechanism is chain replication: each logical shard is a linear
sequence of servers. Writes enter at the head, propagate link by link, and are only
acknowledged after the tail has durably persisted them; reads go to the tail. Since
the tail's state is by construction present on every node in the chain, reads are
strongly consistent without any leader election — the head is trivially the write
leader, and the only consensus-ish problem left is maintaining the chain-to-host
mapping in a bucket config.

## Key patterns & decisions

- **Complexity budget tied to stack position**: for bootstrap/disaster-recovery
  systems, add complexity only when it increases reliability; performance and
  efficiency are explicitly non-goals.
- **Chain replication for strong consistency without leader election**: acknowledge
  writes at the tail after full propagation; serve reads from the tail; a chain of n
  nodes survives n−2 failures, at the cost of higher write latency and n full copies
  versus quorum or erasure-coded systems.
- **Bucket = many chains, chains spread across failure domains**: objects map to
  chains by consistent hashing of the name; an authoritative bucket config records
  the chain-host layout and is updated on membership changes; horizontal scaling is
  chain rebalancing onto new servers.
- **Fail-stop assumption plus peer voting for ejection**: chain neighbors detect a
  bad host via heartbeats and failed hand-offs; a threshold of two independent
  suspicions ejects a host (one would let mutually-suspicious pairs kill each other;
  a high bar leaves sick hosts serving too long). Automated repair makes it cheap to
  tolerate false positives from sensitive thresholds.
- **Rejoin at the tail with deferred reads**: a recovered or new host is appended to
  the rear of the chain, resyncs missing/stale objects from its upstream, may accept
  new writes during catch-up, but forwards reads upstream until fully synchronized —
  the same mechanism serves both repair and capacity expansion.
- **Apportioned queries to fix the tail-read bottleneck (CRAQ pattern)**: any node
  may serve a read after checking with the tail whether its local copy is clean
  (committed chain-wide); dirty objects are served at the last committed version.
  The cheap version-check round trip buys read throughput that scales with chain
  length while preserving strong consistency.
- **Control-plane service for fleet repair with placement invariants**: an external
  CPS re-links broken chains while preserving failure-domain spread and uniform
  chain-per-server counts, prefers re-adding the original host (partial resync is
  cheaper than a full copy), sanity-checks hosts before re-admission, and injects
  standby hosts once a chain loses more than half its members.
- **Hybrid geo-replication**: write once, replicate synchronously to a few regions
  for latency-bounded durability and asynchronously to the rest; partitioned regions
  are excluded and backfilled when they return.
- **Continuous cold-storage backup as a product feature**: integration with archival
  services for continuous backup and restore is what makes Delta credible as the
  recovery provider other teams depend on.

## When to apply / trade-offs

Chain replication is a strong fit when you want strong consistency with a simple
mental model and can tolerate higher write latency and full-copy storage overhead —
especially for foundational or low-dependency systems where operational simplicity
is a survival property. Avoid it when storage efficiency or write latency dominate
(quorum or erasure-coded designs win there) or when read hotspotting cannot be
mitigated (plain chain replication bottlenecks all reads on the tail; the CRAQ-style
apportioned-query variant is the standard mitigation). The peer-voting ejection
threshold is a tunable that trades detection speed against false ejections, and
automating repair is what makes aggressive tuning safe.

## Fidelity check

1. Claim: a chain of n nodes tolerates n−2 failures. Capture support: the post's
   fault-tolerance comparison states an n-node chain stays available with up to n−2
   node failures, versus quorum systems that always need w writers and r readers up.
2. Claim: the ejection vote threshold is two, and this is a deliberate middle
   ground. Capture support: the article explains one vote would let two chain
   members disable each other, too high a limit keeps unhealthy hosts in the fleet,
   and a limit of two has worked well given each host sits in many chains, with an
   automated repair flow absorbing false positives.
3. Claim: rejoining hosts serve writes before they serve reads. Capture support:
   during reconstruction a re-added tail host copies missing or outdated objects
   from upstream and can accept incoming writes, but must defer read traffic to its
   upstream until it has fully caught up.
