---
source: https://www.uber.com/en-IN/blog/modernizing-logging-with-clp-ii/
author: Uber
license-note: ideas absorbed in own words; no text or code reproduced
---

# CLP at Uber, part II: an end-to-end system for unstructured logs

## What it teaches

Part II of Uber's CLP (Compressed Log Processor) series moves beyond the
compression story of part I — where a split into per-host streaming
compression followed by columnar archival yielded a 169:1 ratio, ended
SSD burnout from log write volume, and stretched retention 10x — into a
full log-management platform. The thesis: search and aggregation, which
most observability tools stop at, only bootstrap a debugging session; to
understand *why* something failed, an engineer must read the sequence of
events around it, so first-class log-file *viewing* and programmable
analytics on compressed data are the missing features. The article also
argues that unstructured and structured logs are fundamentally different
workloads: structured events are mostly independent trace-points suited to
index-backed databases and monitoring, while unstructured free-text logs
collectively reconstruct an execution path and get ruinously expensive
when shoehorned into index-based stores (index bloat, memory-per-query
growth).

## Key patterns & decisions

- Two-phase compression split: lightweight row-oriented streaming
  compression at the source produces an intermediate representation per
  container/host; a later pass recompresses into more efficient columnar
  archives — decoupling ingest latency from archival efficiency.
- Treat log viewing as a first-class feature: a serverless, in-browser
  viewer (built on VS Code's Monaco editor) decompresses on the fly and
  adds log-specific affordances — smart pagination for huge files,
  log-level filtering that keeps the cursor anchored on the same event,
  regex search across pages, multi-line event handling for stack traces,
  timestamp-synchronized side-by-side viewing, per-event permalinks, and
  prettification of minified JSON — all possible because CLP already
  parsed out timestamps, levels, and variables during compression.
- Analytics libraries over compressed archives: a C++ core with native
  bindings for Python, Go, and Java exposes the parsed structure
  (timestamp, static log type, extracted variables, message), so users
  skip hand-written text parsing; deduplicating by log *type* rather than
  rendered message groups similar events despite differing variable
  values.
- HDFS-to-object-store migration for log archives: the NameNode could not
  index the flood of small files, and Kerberos walled off developer
  access; object stores scale to billions of objects, add lifecycle-based
  retention, ACLs, encryption, and pay-as-you-go elasticity (e.g.,
  temporarily extending retention after a security incident). Stable
  hierarchical log paths map cleanly onto flat object keys.
- 16MB rotation chunks as a deliberate compromise: small enough to bound
  upload/sync overhead and enable freshness on append-less object stores,
  large enough to preserve compression ratio while only mildly raising
  per-object API costs — and 16MB compressed represents far more raw log
  data.
- Soft/hard deadline upload policy: after an event is logged, upload after
  a soft delay that further events can push back, but never later than a
  guaranteed hard bound (example given: 10s soft, 300s hard); both delays
  are configurable per log level so ERROR events ship sooner than INFO —
  balancing near-real-time freshness against per-request API cost.
- Tag-based scoping: compressed logs carry multiple identifiers (service,
  job, app, user, time range) via paths, metadata, or an external DB, so
  search/view requests narrow to the relevant files immediately —
  matching how users actually debug (they usually already know which job
  and when).
- FFI-based cross-platform integration: rather than re-implementing CLP
  per language/framework (the original Java port for Log4j/Spark), native
  bindings let each language's logging library adopt streaming
  compression without application-code changes.
- Know the tool's lane: CLP is positioned for logs that do not need
  near-real-time indexed search; it complements rather than replaces
  online indexing systems, and cold logs are migration candidates.

## When to apply / trade-offs

- Reach for this architecture when unstructured log volume makes
  index-everything approaches (Elasticsearch-style) cost-prohibitive but
  engineers still need fast search plus contextual file reading.
- The soft/hard deadline pattern generalizes to any batched uploader that
  must trade freshness against per-call cost — an adaptive debounce with a
  guaranteed upper bound, tiered by event severity.
- Producer/consumer asymmetry in adoption is a useful signal: the Python
  analytics library saw ~141,880 downloads versus ~4,845 for the logging
  plugin over six months, reflecting many log readers per log producer —
  design for the reader.
- Roadmap items flag the remaining gaps: host-level collection outside app
  containers (to survive OOM kills and capture non-app logs), and native
  structured-log support (an OSDI '24 paper is cited as forthcoming).

## Fidelity check

1. Claim: the phase-one split delivered a 169:1 compression ratio, fixed
   SSD burnout, and extended retention 10x. Support: the capture's intro
   recaps the two-phase design (streaming intermediate representation,
   then columnar archives) and credits it with a 169:1 ratio, resolving
   SSD burnouts from log writes, and a 10x longer retention period.
2. Claim: uploads follow a per-level-configurable soft deadline that new
   events can extend, capped by a hard deadline. Support: the capture
   defines soft delay S and hard bound H with a worked example (S=10s,
   H=300s: an event uploads at T+10 if nothing else arrives, otherwise no
   later than T+300) and says delays are configurable per log level.
3. Claim: 16MB was chosen as the compressed rotation size to balance
   compression ratio, storage/sync overhead, and API access cost on
   object stores. Support: the capture states rotation triggers at the
   16MB mark and describes that size as a strategic compromise maximizing
   compression while minimizing storage and synchronization overhead at a
   slight API-cost increase.
