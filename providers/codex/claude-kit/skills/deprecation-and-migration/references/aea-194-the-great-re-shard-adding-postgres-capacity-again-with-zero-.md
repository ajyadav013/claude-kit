---
source: https://www.notion.com/blog/the-great-re-shard
author: Notion
license-note: ideas absorbed in own words; no text or code reproduced
---

# Tripling a live Postgres fleet 32 -> 96 shards with zero downtime

## What it teaches

Notion's workspace-content cluster ("space shards", partitioned by workspace
id) was nearing hard limits — shards past 90% CPU at peak, disk IOPS near
provisioned ceilings, connection-pooler limits — with a predictable new-year
traffic spike incoming. The team horizontally re-sharded from 32 to 96 Postgres
machines with no observable downtime. The article is a complete migration
playbook: pre-splitting via logical schemas, logical replication for sync, a
forced detour to shard the PgBouncer layer itself when connection math broke,
dark-read verification, and a scripted, checkpointed failover with reverse
replication as the rollback parachute.

## Key patterns & decisions

- **Pre-partitioned logical schemas make re-sharding a redistribution, not a
  re-keying**: each of the 32 databases already held 15 logical schema
  partitions, so tripling capacity meant reassigning schemas (15 → 5 per
  machine), never rewriting the partition function or moving individual rows'
  ownership.
- **Horizontal over vertical, chosen for tunability too**: bigger machines
  merely defer the same wall, and spreading load across more, smaller
  instances lets each be sized to its actual traffic (shard load is uneven) —
  plus new shards got smaller disks since storage wasn't the bottleneck and
  can grow later.
- **Native logical replication with publications aligned to the split**: three
  publications per old database, each covering the 5 schemas destined for one
  new machine; new databases just subscribe to their publication.
- **Drop indexes during bulk copy, rebuild after**: skipping index maintenance
  during the initial copy took total sync time from 3 days to 12 hours.
- **The proxy layer becomes the hidden bottleneck**: with ~100 poolers x 6
  connections per shard (~600/shard), pointing 3 new logical entries at each
  old database tripled connection demand mid-migration; too few connections
  backed queries up. The fix was sharding PgBouncer itself into 4 groups of 24
  downstream databases — also buying blast-radius isolation (a pooler-group
  incident now touches 25% of the fleet).
- **Migrate the pooler with the same technique in miniature**: many small
  load-balancer steps, exploiting PgBouncer's near-statelessness — shift new
  traffic, let old connections drain.
- **Dark reads for correctness at production scale, carefully budgeted**:
  sample a small fraction of requests, compare follower vs primary results
  only for queries returning at most 5 rows (extra comparison CPU on the hot
  path showed up as user latency), and delay the shadow query ~1s so
  replication can catch up; near-100% equivalence (residual mismatch blamed on
  nondeterministic queries and lag) green-lit the cutover.
- **Failover as a scripted four-step with rollback at every checkpoint**:
  pause client traffic at the pooler and let in-flight queries drain → verify
  replication is fully caught up → repoint the pooler mapping, revoke app
  login on the old database, and reverse the replication direction → resume.
  Worst user impact was about a second of a saving spinner.
- **Reverse replication as the rollback plan**: after cutover the old shard
  tails the new shard's WAL, so rolling back stays possible without data loss;
  the whole sequence was rehearsed repeatedly in staging first.
- **More shards sharpen outlier visibility**: spreading load exposed that a
  few workspaces dominate CPU on their shard — a diagnostic bonus of finer
  granularity.

## When to apply / trade-offs

This is the reference recipe for growing a sharded relational fleet in place:
pre-split with more logical partitions than machines on day one, sync with
logical replication, verify with sampled dark reads, and cut over
per-database behind a pause-capable proxy with reverse replication armed.
Budget for second-order capacity problems — connection pools, pooler topology,
replication throughput — because the migration itself multiplies them before
it relieves anything. Trade-offs: dark-read comparison costs hot-path CPU
(hence sampling and row caps); a brief per-database write pause is accepted
in exchange for strict consistency at cutover; and pooler sharding adds
operational surface even as it isolates failures.

## Fidelity check

1. Claim: the trigger was measured resource exhaustion, not speculation.
   Support: the capture cites shards above 90% CPU at peak, near-full
   provisioned IOPS, and PgBouncer connection-limit pressure in late 2022,
   ahead of a historically spiky new year.
2. Claim: skipping index creation during copy cut sync time by 6x. Support:
   the implementation notes report total machine synchronization dropping
   from 3 days to 12 hours when indexes were built only after the data copy
   finished.
3. Claim: PgBouncer had to be sharded before the database failover could
   proceed. Support: the article walks the connection arithmetic (about 100
   pooler instances, up to 6 server connections each per shard, ~600 total)
   and shows that naive migration meant 18 connections per pooler per old
   shard, resolved by splitting the pooler fleet into 4 groups of 24
   databases.
4. Claim: user-visible impact was roughly one second. Support: the failover
   section says the worst case was about a second of a "saving" spinner while
   queries drained, configs reloaded, and replication flipped, with no
   downtime observed in metrics or reports.
