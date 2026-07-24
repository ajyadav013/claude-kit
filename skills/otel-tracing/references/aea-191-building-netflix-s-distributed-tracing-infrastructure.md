---
source: https://netflixtechblog.com/building-netflixs-distributed-tracing-infrastructure-bb856c319304
author: Netflix TechBlog
license-note: ideas absorbed in own words; no text or code reproduced
---

# Tracing infrastructure economics: sampling policy, stream processing, and storage cost curves

## What it teaches

The tracing backbone behind Edgar (Netflix's streaming-session troubleshooting
tool) is presented as three linked problems: instrumenting a polyglot fleet
without losing engineers' trust, deciding what fraction of traces to keep, and
storing the result without linear cost growth. The strongest lessons are the
sampling philosophy — troubleshooting tools are useless if the trace you need
was sampled away, so mission-critical paths record 100% — and the storage
journey: Elasticsearch buckling under write-heavy ingest, migration to
Cassandra, then a sequence of concrete optimizations (EBS over instance SSDs,
compaction-strategy tuning, Zstd compression, rules-based tail filtering) that
cut operating cost 71% while multiplying retained data 35x.

## Key patterns & decisions

- **Hybrid head-based sampling**: record every trace for a configurable set of
  business-critical request paths while randomly sampling everything else —
  because a heavily sampled dataset cannot answer "why did THIS member's
  session fail", but 100% everywhere is unaffordable in CPU/network/storage.
- **Context propagation via standard headers across paved and unpaved roads**:
  they adopted Zipkin's B3 header scheme, guaranteed it on supported Java/Node
  runtimes, and let other-runtime teams own their tracer choice plus the
  responsibility of propagating context correctly (freedom-and-responsibility
  applied to instrumentation).
- **Consistent infrastructure tagging as a join key**: injecting service name,
  scaling group, and container ids into every span lets the UI join traces
  with logs and deep-link into deploy/monitoring tools — tags are the glue of
  the observability estate.
- **Chained, independently scalable stream jobs**: one backpressure-aware job
  buffers spans until a trace is complete; a second taps that feed, applies
  tail sampling, and writes to storage — each stage scales on its own, and the
  live feed doubles as an ad-hoc query surface.
- **Match the datastore to the write/read shape**: Elasticsearch's index-heavy
  ingest degraded both reads and writes under exponential trace growth;
  Cassandra with simple lookup indices sustained heavy writes at acceptable
  read latency.
- **Sub-linear storage cost as an explicit goal**: elastic block volumes that
  grow without re-provisioning nodes (instead of adding nodes when local SSDs
  fill), tuned time-window compaction to cut disk churn and replication
  traffic, and block compression halving file sizes — jointly 71% cheaper and
  35x more retained data.
- **Usage-informed tail sampling**: observing that users examined under 1% of
  stored traces justified a rules filter that keeps only "interesting" traces
  (those whose buffered spans contain errors, warnings, or retries) for rarely
  queried call paths — 20% volume cut with no user-visible loss.
- **Tiered storage as the next inflection**: hot recent hours in Cassandra,
  older data compacted out to object storage, fronted by a gateway that hides
  which tier serves a query.
- **Trace data as a multi-tenant signal**: the same corpus powers app-health
  topology inference, chaos-experiment verification, regional-evacuation
  prescaling, and A/B-test cost estimation — instrument once, reuse widely.

## When to apply / trade-offs

Use this playbook when introducing tracing to a service fleet: lead with the
integration-cost question service owners will actually ask, make sampling
policy an explicit product decision per request class rather than a global
knob, and expect the storage tier to be re-platformed as volume grows —
budgeting for sub-linear cost, not just capacity. Trade-offs: 100% sampling on
critical paths raises per-service resource use (teams re-tuned services to
absorb it); tail filtering risks discarding a trace someone later wants (they
scoped it to rarely-viewed paths); and buffering spans to assemble complete
traces before tail-sampling adds latency and memory in the pipeline.

## Fidelity check

1. Claim: sampling is hybrid — full capture on chosen paths, random elsewhere.
   Support: the stream-processing section describes head-based sampling that
   records all traces for a configurable request set while auxiliary systems
   like offline batch stay minimally sampled.
2. Claim: the Cassandra optimization campaign cut cost 71% and grew retention
   35x. Support: the storage section credits EBS migration, time-window
   compaction tuning, and Zstd block compression with exactly those figures.
3. Claim: tail filtering was justified by observed usage. Support: the article
   reports users explored under 1% of collected traces, and the resulting
   rules-based filter (keep traces containing error/warning/retry tags on rare
   paths) shrank volume ~20% without hurting the experience.
4. Claim: they moved off Elasticsearch because index build cost degraded the
   cluster. Support: the storage narrative describes read queries slowing as
   clusters spent compute indexing the ever-growing ingest until both reads
   and writes degraded, prompting the Cassandra migration.
