---
source: https://research.google/blog/answering-billions-of-reporting-queries-each-day-with-low-latency/
author: Google Research
license-note: ideas absorbed in own words; no text or code reproduced
---

# Google Napa: "good enough" progressive partitioning for skew-proof query parallelism

## What it teaches
Napa, the warehouse behind Google Ads reporting dashboards, must answer billions of daily
queries whose cost varies wildly — one advertiser's key filters match a handful of records,
another's match millions. Serving all of them within strict latency targets requires
deciding, per query and within milliseconds, how to slice the matching records into
equal-work chunks across machines. The post (summarizing a VLDB 2023 paper) explains why
naive record-count estimation fails under skew and how a tree-guided, anytime partitioning
algorithm solves it.

## Key patterns & decisions
- Parallelization is a per-query, latency-budgeted decision: too-uneven splits create
  straggler machines; too-fine splits waste infrastructure; and the split decision itself
  must consume only a small fraction of the query budget (tens of milliseconds when the
  answer is due in hundreds).
- Store partitioning statistics inside the storage structure: tables live as
  log-structured merge forests indexed by B-trees, and every B-tree node carries the count
  of entries beneath it — so work estimates come free with the index rather than from a
  separate statistics pipeline.
- Decouple ingest from serving with atomic version swaps: queries always run against a
  stable snapshot, and a freshly prepared ingest batch becomes visible in one atomic step,
  so partitioning never races live updates.
- "Good enough" (anytime) partitioning with an explicit error bound: while walking the tree
  to split records into halves, the algorithm continuously tracks how unequal the pieces
  could still be; each descent into a subtree tightens that bound, and the walk stops the
  moment the bound is acceptable rather than continuing to exactness.
- Steer effort toward the skew: node statistics guide which subtree to expand next, so
  traversal work concentrates on the dense, uncertain regions of the key space instead of
  scanning uniformly.
- Interruptibility as a feature: stopping the algorithm early still yields a usable
  partitioning whose quality corresponds to the time invested — a graceful-degradation
  property that fixed-cost approaches lack.
- Tree-guided beats sample-based: prior systems partition using sampled tables, but at
  petabyte scale even the sample (and the statistics generally) can reach terabytes;
  exploiting the hierarchy of an existing index is both smaller and faster, with the
  measured speedup growing as queries get larger.
- Simple ingredients, carefully composed: the authors stress that ordinary tree traversal
  over well-designed data structures — not exotic machinery — carries a critical
  Google-scale workload.

## When to apply / trade-offs
- Apply when fanning skewed work across workers under a hard latency ceiling: query
  engines, batch shard planners, or any scatter-gather system where item costs vary by
  orders of magnitude.
- Requires an index or hierarchical summary that already carries per-subtree counts; if
  the storage layer lacks that, the statistics must be built and maintained, which is the
  real cost of the approach.
- Exact balance is deliberately not the goal: accepting bounded imbalance is what makes
  millisecond decisions possible; systems that need perfectly equal shards must pay more.
- The atomic-snapshot ingest model trades a little freshness for the stability that makes
  precomputed statistics trustworthy at query time.

## Fidelity check
1. Claim: the index itself supplies the work estimates. Capture support: the post states
   each B-tree node records how many entries sit in each of its subtrees, and that this
   is what aids query parallelization.
2. Claim: the algorithm is anytime — early termination still gives usable output. Capture
   support: the post says that if the process is stopped at any point one still obtains a
   good partitioning, with quality corresponding to the time spent, and that longer runs
   make the pieces more equal.
3. Claim: it outperforms sampling-based partitioning, especially for big queries. Capture
   support: experiments comparing against multi-resolution table sampling showed progressive
   partitioning was much faster, with the relative speedup increasing with query size; the
   post also notes statistics for petabyte tables can reach terabytes, motivating the
   tree-based method.
